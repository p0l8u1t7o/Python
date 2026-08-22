"""Advance a run: move its tokens until they are blocked, done, or capped.

The engine is deliberately a *stepper*, not a thread. It is called, it moves
every token that can move right now, it writes the new positions down and it
returns. Nothing is held on a Python stack between calls, which is why a run
survives a process restart and why a thirty-second timer costs no resources.

Three rules keep a drawn graph from becoming a runaway:

* **A step budget per run**, counted in node transitions. A ``jump`` loop burns
  steps without burning wall clock, so a time limit would not catch it.
* **A step budget per call**, so one busy run cannot starve the others in the
  same tick.
* **Blocked means blocked.** A token with nowhere to go ends. A run whose last
  token ends is finished. A graph that can never finish is a graph the operator
  has to stop - which is visible, rather than a silent leak.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.core.logging import get_logger
from apps.workflows import nodes
from apps.workflows.models import (
    LogLevel,
    RunStatus,
    WorkflowLog,
    WorkflowRun,
    WorkflowToken,
)

logger = get_logger("workflows.engine")


@dataclass(slots=True)
class StepReport:
    """What one call to :func:`advance` did."""

    run_id: Any
    steps: int = 0
    finished: bool = False
    status: str = ""
    error: str = ""


def _node_map(graph: dict) -> dict[str, dict]:
    return {str(node.get("id")): node for node in (graph.get("nodes") or []) if node.get("id")}


def _edges_from(graph: dict, node_id: str, handle: str) -> list[str]:
    """Targets of every edge leaving ``node_id`` by ``handle``.

    More than one target is a fork, and that is the whole parallelism model:
    the operator draws two lines from one output and gets two branches. There
    is no separate "parallel" node to forget to use.
    """
    targets: list[str] = []
    for edge in graph.get("edges") or []:
        if str(edge.get("source")) != node_id:
            continue
        # A node with a single unnamed output writes no handle; treat blank as
        # matching so simple graphs need no ceremony.
        source_handle = str(edge.get("source_handle") or edge.get("sourceHandle") or "")
        if source_handle and handle and source_handle != handle:
            continue
        target = str(edge.get("target") or "")
        if target:
            targets.append(target)
    return targets


def _log(run: WorkflowRun, node: dict | None, result_message: str, *,
         level: str = LogLevel.INFO, branch: str = "", detail: dict | None = None) -> None:
    # Debug lines are the step-by-step trace a test run needs and a production
    # loop would drown in. Kept for dry runs, dropped otherwise.
    if level == LogLevel.DEBUG and not run.dry_run:
        return
    WorkflowLog.objects.create(
        run=run,
        node_id=str((node or {}).get("id") or ""),
        node_label=str((node or {}).get("label") or (node or {}).get("type") or "")[:200],
        level=level,
        message=result_message[:2000],
        branch=branch[:32],
        detail=detail or {},
    )


def _finish(run: WorkflowRun, status: str, error: str = "") -> None:
    run.status = status
    run.finished_at = timezone.now()
    run.wake_at = None
    run.error = error[:2000]
    run.save(update_fields=["status", "finished_at", "wake_at", "error", "updated_at"])
    run.tokens.all().delete()


def advance(
    run: WorkflowRun,
    *,
    moment: dt.datetime | None = None,
    step_budget: int | None = None,
) -> StepReport:
    """Move ``run`` as far as it can go right now.

    ``step_budget`` caps this one call - the single-step debugger passes 1.
    The per-run limit still applies on top of it.
    """
    moment = moment or timezone.now()
    report = StepReport(run_id=run.id)

    if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
        report.status = run.status
        return report
    # Paused is a hard stop, not a wait: however long the clock runs, a paused
    # run does not move until someone resumes it.
    if run.status == RunStatus.PAUSED:
        report.status = run.status
        return report

    limits = settings.WORKFLOWS
    per_call = step_budget if step_budget is not None else int(limits["MAX_STEPS_PER_CALL"])
    per_run = int(limits["MAX_STEPS_PER_RUN"])

    graph = run.graph or {}
    node_map = _node_map(graph)
    organization = run.organization
    site = run.workflow.site if run.workflow_id else None
    context = dict(run.context or {})

    if run.started_at is None:
        run.started_at = moment
    run.status = RunStatus.RUNNING

    # Fair interleaving: each token gets one step per lap, and a new lap only
    # starts once every ready token has had its turn.
    #
    # Per *lap* rather than per call, which is the whole subtlety. Limiting a
    # token to one step per call would be fair but glacial - a straight line of
    # five nodes would need five ticks. Limiting it per lap keeps a branch that
    # loops from starving the others while still letting a graph run to
    # completion in one pass.
    lap: set[int] = set()

    while report.steps < per_call:
        # 0 disables the per-run cap: a control loop that holds a setpoint
        # forever is a legitimate drawing, and killing it after N steps made
        # the engine fail exactly the flows it exists for. The per-call cap
        # below still bounds work per tick.
        if per_run and run.steps_taken >= per_run:
            _log(run, None, "Step limit reached", level=LogLevel.ERROR,
                 detail={"limit": per_run})
            _finish(run, RunStatus.FAILED, f"Step limit of {per_run} reached")
            report.finished = True
            report.status = run.status
            report.error = run.error
            return report

        token = _next_token(run, moment, lap)
        if token is None:
            if not lap:
                break
            # Everyone has had a turn; go round again.
            lap = set()
            continue
        lap.add(token.id)

        node = node_map.get(token.node_id)
        if node is None:
            _log(run, {"id": token.node_id}, "Node is not in the graph",
                 level=LogLevel.ERROR)
            token.delete()
            continue

        # A disabled node is stepped over, not executed. That is what the
        # per-node switch is for: comment a step out without redrawing the
        # edges around it.
        if node.get("enabled") is False:
            targets = _edges_from(graph, token.node_id, "out") or _default_targets(
                graph, token.node_id
            )
            _log(run, node, "Skipped (disabled)", level=LogLevel.DEBUG)
            _move(run, token, targets, wake_at=_delay_wake(run, moment))
            run.steps_taken += 1
            report.steps += 1
            continue

        # A breakpoint pauses the run *before* the node executes, so the
        # operator inspects the state the node is about to act on. The marker
        # in token state lets Resume execute this node once without
        # immediately re-pausing on it.
        if node.get("breakpoint") and (token.state or {}).get("_bp") != token.node_id:
            state = dict(token.state or {})
            state["_bp"] = token.node_id
            token.state = state
            token.save(update_fields=["state"])
            _log(run, node, "Paused at breakpoint", branch="")
            run.status = RunStatus.PAUSED
            run.wake_at = None
            run.context = context
            run.save(
                update_fields=["status", "wake_at", "context", "steps_taken",
                               "started_at", "updated_at"]
            )
            report.status = run.status
            return report
        if (token.state or {}).get("_bp"):
            state = dict(token.state or {})
            state.pop("_bp", None)
            token.state = state

        try:
            node_type = nodes.get(str(node.get("type") or ""))
        except nodes.UnknownNodeType as exc:
            _log(run, node, str(exc), level=LogLevel.ERROR)
            _finish(run, RunStatus.FAILED, str(exc))
            report.finished = True
            report.status = run.status
            report.error = run.error
            return report

        ctx = nodes.NodeContext(
            run=run,
            token=token,
            node=node,
            organization=organization,
            site=site,
            context=context,
            moment=moment,
            dry_run=run.dry_run,
            log=lambda message, level=LogLevel.INFO, detail=None: _log(
                run, node, message, level=level, detail=detail
            ),
        )

        try:
            result = node_type.execute(ctx)
        except Exception as exc:  # noqa: BLE001 - one bad node must not lose the run
            logger.exception("workflow node failed", extra={"node": token.node_id})
            _log(run, node, f"Node raised: {exc!r}", level=LogLevel.ERROR)
            _finish(run, RunStatus.FAILED, f"{token.node_id}: {exc!r}")
            report.finished = True
            report.status = run.status
            report.error = run.error
            return report

        run.steps_taken += 1
        report.steps += 1

        if result.context:
            context.update(result.context)
        if result.token_state is not None:
            state = dict(token.state or {})
            state.update(result.token_state)
            token.state = state

        if result.message:
            _log(run, node, result.message, level=result.level,
                 branch=result.branch, detail=result.detail)

        if result.goto:
            if result.goto not in node_map:
                _log(run, node, f"Jump target '{result.goto}' does not exist",
                     level=LogLevel.ERROR)
                token.delete()
                continue
            if _occupied(run, result.goto, exclude_pk=token.pk):
                # Same merge rule as _move: two branches at one node is one
                # branch, or a loop through a fork doubles forever.
                _log(run, node, "Branch merged into the one already at the "
                     f"jump target '{result.goto}'", level=LogLevel.DEBUG)
                token.delete()
                continue
            token.node_id = result.goto
            # A jump carries a wake time, so the two are handled together
            # rather than the wait being silently dropped by the earlier
            # branch returning first.
            token.wake_at = result.wait_until
            token.save(update_fields=["node_id", "state", "wake_at"])
            continue

        if result.wait_until is not None:
            state = dict(token.state or {})
            state.pop("_slowmo", None)
            token.state = state
            token.wake_at = result.wait_until
            token.save(update_fields=["state", "wake_at"])
            continue

        if result.stop:
            token.delete()
            continue

        targets = _edges_from(graph, token.node_id, result.branch)
        _move(run, token, targets, wake_at=_delay_wake(run, moment))

    run.context = context
    return _settle(run, report, moment)


def _delay_wake(run: WorkflowRun, moment: dt.datetime) -> dt.datetime | None:
    """Slow-motion: the wake time an inter-node delay imposes, if one is set."""
    delay = float(run.step_delay_seconds or 0.0)
    if delay <= 0:
        return None
    return moment + dt.timedelta(seconds=delay)


def _next_token(run: WorkflowRun, moment: dt.datetime, lap: set[int]):
    """The next ready token that has not had its turn this lap.

    Round-robin rather than "whichever is oldest", so a branch that loops
    cannot monopolise the call budget while the others sit still.
    """
    return (
        run.tokens.filter(models_wake_filter(moment))
        .exclude(id__in=lap)
        .order_by("created_at", "id")
        .first()
    )


def models_wake_filter(moment: dt.datetime):
    """Tokens that are ready to move: no wake time, or one already past."""
    from django.db.models import Q

    return Q(wake_at__isnull=True) | Q(wake_at__lte=moment)


def _default_targets(graph: dict, node_id: str) -> list[str]:
    """Every edge leaving a node, whichever handle it uses.

    Used when stepping over a disabled node: the operator switched off what the
    node *does*, not the path through it, so the branch it would have chosen is
    unknowable and every outgoing edge is followed.
    """
    return [
        str(edge.get("target"))
        for edge in graph.get("edges") or []
        if str(edge.get("source")) == node_id and edge.get("target")
    ]


def _occupied(run: WorkflowRun, node_id: str, *, exclude_pk=None) -> bool:
    """Whether another branch of this run already sits at ``node_id``."""
    queryset = run.tokens.filter(node_id=node_id)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.exists()


def _move(
    run: WorkflowRun,
    token: WorkflowToken,
    targets: list[str],
    *,
    wake_at: dt.datetime | None = None,
) -> None:
    """Send a token onward, forking if the branch has more than one edge.

    **Arrivals merge.** A branch arriving at a node where another branch of
    the same run already stands joins it instead of duplicating it. Without
    this, a jump back to a forking node re-forks on every lap and the branch
    count doubles per cycle - 2, 4, 8 ... - until the step budget kills the
    run. One branch per node is the PLC reading of the drawing: the node is
    either being worked on or it is not.

    ``wake_at`` is the slow-motion delay; it applies to the forks as well, or
    the copies would sprint ahead of the original.
    """
    if not targets:
        token.delete()
        return

    # Slow-motion wakes are tagged in token state so the single-step control
    # can tell them apart from a Wait node's own timer: stepping should see
    # through the viewing delay but must never shorten a real wait.
    state = dict(token.state or {})
    if wake_at is not None:
        state["_slowmo"] = True
    else:
        state.pop("_slowmo", None)
    token.state = state

    # Each extra edge is another branch - unless one is already there.
    for target in targets[1:]:
        if _occupied(run, target, exclude_pk=token.pk):
            _log(run, {"id": target}, "Branch merged into the one already here",
                 level=LogLevel.DEBUG)
            continue
        WorkflowToken.objects.create(
            run=run, node_id=target, state=dict(token.state or {}), wake_at=wake_at
        )

    if _occupied(run, targets[0], exclude_pk=token.pk):
        _log(run, {"id": targets[0]}, "Branch merged into the one already here",
             level=LogLevel.DEBUG)
        token.delete()
        return

    token.node_id = targets[0]
    token.wake_at = wake_at
    token.save(update_fields=["node_id", "state", "wake_at"])


def _settle(run: WorkflowRun, report: StepReport, moment: dt.datetime) -> StepReport:
    """Work out the run's status now that its tokens have stopped moving."""
    remaining = list(run.tokens.all())
    if not remaining:
        _log(run, None, "All branches finished")
        _finish(run, RunStatus.SUCCEEDED)
        report.finished = True
        report.status = run.status
        return report

    wakes = [token.wake_at for token in remaining if token.wake_at is not None]
    ready = any(token.wake_at is None or token.wake_at <= moment for token in remaining)

    if ready:
        # Ran out of per-call budget with work still to do; come straight back.
        run.status = RunStatus.RUNNING
        run.wake_at = moment
    else:
        run.status = RunStatus.WAITING
        run.wake_at = min(wakes) if wakes else moment

    run.save(
        update_fields=["status", "wake_at", "context", "steps_taken",
                       "started_at", "updated_at"]
    )
    report.status = run.status
    return report
