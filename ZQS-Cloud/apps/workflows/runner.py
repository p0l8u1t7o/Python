"""Starting, stopping and driving runs.

The concurrency cap lives here because it has to be enforced at exactly one
point: the moment a run is created. Checking it anywhere else - in the API, in
the node that starts other workflows - would mean two places that must agree,
and one of them eventually would not.

The cap is per organisation and is a **server setting, not a tenant setting**.
An operator can add and remove flows freely up to it; they cannot raise it,
because the thing it protects is the server everyone shares.
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.errors import Conflict
from apps.core.logging import get_logger
from apps.workflows.engine import StepReport, advance
from apps.workflows.graph import entry_nodes, validate_graph
from apps.workflows.models import (
    ACTIVE_STATUSES,
    RUNNABLE_STATUSES,
    RunStatus,
    TriggerSource,
    Workflow,
    WorkflowLog,
    WorkflowRun,
    WorkflowToken,
)

logger = get_logger("workflows.runner")


class ConcurrencyLimit(Conflict):
    """Raised when starting would exceed the tenant's branch budget."""

    def __init__(self, limit: int, active: int, requested: int = 1) -> None:
        super().__init__(
            f"This organization already has {active} workflow branch(es) "
            f"running, and the server allows {limit} at once. Starting this "
            f"would add {requested} more. Stop something first.",
            code="workflow_concurrency_limit",
            details={"limit": limit, "active": active, "requested": requested},
        )


def max_concurrent_runs() -> int:
    return int(settings.WORKFLOWS["MAX_CONCURRENT_RUNS"])


def active_branches(organization) -> int:
    """Live branches (tokens), not runs.

    The limit protects engine work per tick, and that scales with branches: a
    run whose graph has two entry points costs two of everything a
    single-branch run costs. Counting runs would let one ten-branch graph eat
    the tick while looking like one unit of load. Tokens of paused runs count
    too - they resume at any moment.
    """
    return WorkflowToken.objects.filter(
        run__organization=organization, run__status__in=ACTIVE_STATUSES
    ).count()


#: Kept as an alias for callers that predate branch accounting.
active_runs = active_branches


@transaction.atomic
def start_run(
    workflow: Workflow,
    *,
    trigger: str = TriggerSource.MANUAL,
    started_by=None,
    parent_run: WorkflowRun | None = None,
    dry_run: bool = False,
    context: dict | None = None,
    step_delay_seconds: float = 0.0,
    start_paused: bool = False,
) -> WorkflowRun:
    """Create a run and place a token on every entry node.

    Raises :class:`ConcurrencyLimit` rather than queueing. A queue would let a
    graph that starts workflows in a loop build an unbounded backlog that looks
    fine until it is executed; refusing is visible immediately.
    """
    if not workflow.is_enabled:
        raise Conflict(
            f"Workflow '{workflow.name}' is disabled",
            code="workflow_disabled",
        )

    validate_graph(workflow.graph)

    # Dry runs still count. They evaluate conditions, read the database and
    # take engine steps; exempting them would make the limit meaningless the
    # moment somebody left a test running.
    # The unit is branches: this run will place one token per entry node, and
    # all of them have to fit under the budget together.
    starts = entry_nodes(workflow.graph)
    limit = max_concurrent_runs()
    active = active_branches(workflow.organization)
    if active + max(len(starts), 1) > limit:
        raise ConcurrencyLimit(limit, active, requested=max(len(starts), 1))

    run = WorkflowRun.objects.create(
        organization=workflow.organization,
        workflow=workflow,
        graph=workflow.graph,
        workflow_version=workflow.version,
        # Born paused is how single-stepping from the first node works: the
        # tokens are placed but nothing moves until the operator steps.
        status=RunStatus.PAUSED if start_paused else RunStatus.PENDING,
        trigger=trigger,
        parent_run=parent_run,
        started_by=started_by,
        dry_run=dry_run,
        context=dict(context or {}),
        # Clamped: a delay is a viewing aid, and an hour-long one would look
        # exactly like a hung engine.
        step_delay_seconds=max(0.0, min(float(step_delay_seconds or 0.0), 30.0)),
        wake_at=None if start_paused else timezone.now(),
    )

    WorkflowToken.objects.bulk_create(
        [WorkflowToken(run=run, node_id=node_id) for node_id in starts]
    )
    WorkflowLog.objects.create(
        run=run,
        level="info",
        message=(
            f"Run started ({trigger}"
            + (", dry run" if dry_run else "")
            + f") with {len(starts)} branch(es)"
        ),
        detail={"entry_nodes": starts},
    )
    logger.info(
        "workflow run started",
        extra={
            "workflow": workflow.name,
            "run": str(run.id),
            "branches": len(starts),
            "dry_run": dry_run,
        },
    )
    return run


def stop_run(run: WorkflowRun, *, reason: str = "") -> WorkflowRun:
    """Stop a run where it stands. Already-finished runs are left alone."""
    if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
        return run

    run.status = RunStatus.CANCELLED
    run.finished_at = timezone.now()
    run.wake_at = None
    run.error = reason[:2000]
    run.save(update_fields=["status", "finished_at", "wake_at", "error", "updated_at"])
    run.tokens.all().delete()
    WorkflowLog.objects.create(
        run=run, level="warning", message=reason or "Stopped by an operator"
    )
    return run


def due_runs(moment: dt.datetime | None = None):
    """Runs the engine should look at now. Paused runs are not among them."""
    moment = moment or timezone.now()
    from django.db.models import Q

    return (
        WorkflowRun.objects.filter(status__in=RUNNABLE_STATUSES)
        .filter(Q(wake_at__isnull=True) | Q(wake_at__lte=moment))
        .select_related("workflow", "organization")
        .order_by("wake_at", "created_at")
    )


def pause_run(run: WorkflowRun, *, reason: str = "") -> WorkflowRun:
    """Freeze a run where it stands. Everything is kept - tokens, timers,
    context - so Resume continues exactly there."""
    if run.status not in RUNNABLE_STATUSES:
        return run
    run.status = RunStatus.PAUSED
    run.wake_at = None
    run.save(update_fields=["status", "wake_at", "updated_at"])
    WorkflowLog.objects.create(
        run=run, level="info", message=reason or "Paused by an operator"
    )
    return run


def resume_run(run: WorkflowRun) -> WorkflowRun:
    """Set a paused run moving again on the next tick."""
    if run.status != RunStatus.PAUSED:
        return run
    run.status = RunStatus.RUNNING
    run.wake_at = timezone.now()
    run.save(update_fields=["status", "wake_at", "updated_at"])
    WorkflowLog.objects.create(run=run, level="info", message="Resumed")
    return run


def step_run(run: WorkflowRun) -> WorkflowRun:
    """Execute exactly one node, then pause again.

    The debugger's single-step. A paused run is nudged forward one transition;
    a run that finishes on that step finishes; anything still alive is put
    straight back on pause so the operator stays in control of the pace.
    """
    from apps.workflows.engine import advance

    if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
        return run

    if run.status == RunStatus.PAUSED:
        run.status = RunStatus.RUNNING
        run.save(update_fields=["status", "updated_at"])

    # See through the slow-motion delay: a token parked only for viewing pace
    # is ready as far as the operator is concerned. Tokens parked by a Wait
    # node or a timer keep their wake time - stepping must not shorten those.
    for token in run.tokens.filter(wake_at__isnull=False):
        if (token.state or {}).get("_slowmo"):
            token.wake_at = None
            token.save(update_fields=["wake_at"])

    advance(run, step_budget=1)
    run.refresh_from_db()
    if run.status in RUNNABLE_STATUSES:
        run.status = RunStatus.PAUSED
        run.wake_at = None
        run.save(update_fields=["status", "wake_at", "updated_at"])
    return run


@transaction.atomic
def run_single_node(
    workflow: Workflow,
    *,
    node_id: str,
    started_by=None,
    dry_run: bool = False,
    context: dict | None = None,
) -> WorkflowRun:
    """Execute exactly one node, on its own, and finish.

    The editor's "run this node" button: the selected node runs once with its
    parameters, its outcome is logged, and the run ends without following any
    edge. Breakpoint and disabled flags on the node are ignored - the operator
    pointed at this node and asked for it by name.
    """
    if not workflow.is_enabled:
        raise Conflict(
            f"Workflow '{workflow.name}' is disabled", code="workflow_disabled"
        )

    graph = validate_graph(workflow.graph)
    target = next((n for n in graph["nodes"] if str(n.get("id")) == node_id), None)
    if target is None:
        raise Conflict(f"Node '{node_id}' is not in the graph", code="node_not_found")
    if str(target.get("type")) == "note":
        raise Conflict("A note is decoration and cannot be run", code="node_is_note")

    limit = max_concurrent_runs()
    active = active_branches(workflow.organization)
    if active + 1 > limit:
        raise ConcurrencyLimit(limit, active)

    # The run gets its own copy of the graph with the flags that would stop
    # the node from executing stripped from it - the stored workflow is not
    # touched.
    solo = {
        "nodes": [
            {k: v for k, v in n.items() if k not in ("breakpoint", "enabled")}
            if str(n.get("id")) == node_id
            else n
            for n in graph["nodes"]
        ],
        "edges": graph["edges"],
    }

    run = WorkflowRun.objects.create(
        organization=workflow.organization,
        workflow=workflow,
        graph=solo,
        workflow_version=workflow.version,
        status=RunStatus.PENDING,
        trigger=TriggerSource.MANUAL,
        started_by=started_by,
        dry_run=dry_run,
        context=dict(context or {}),
        wake_at=timezone.now(),
    )
    WorkflowToken.objects.create(run=run, node_id=node_id)
    WorkflowLog.objects.create(
        run=run,
        level="info",
        message=f"Single-node run of '{node_id}'" + (", dry run" if dry_run else ""),
        node_id=node_id,
    )

    advance(run, step_budget=1)
    run.refresh_from_db()
    if run.status not in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
        run.status = RunStatus.SUCCEEDED
        run.finished_at = timezone.now()
        run.wake_at = None
        run.save(update_fields=["status", "finished_at", "wake_at", "updated_at"])
        run.tokens.all().delete()
        WorkflowLog.objects.create(
            run=run, level="info", message="Single-node run finished"
        )
    return run


def tick(moment: dt.datetime | None = None, *, limit: int = 50) -> list[StepReport]:
    """Advance every run that is due. One pass, no loop.

    Called on a short interval by ``run_workflows``. Short because a run parked
    on a timer wakes by wall clock, and the interval is the resolution of every
    timer in the system.
    """
    moment = moment or timezone.now()
    reports: list[StepReport] = []
    for run in list(due_runs(moment)[:limit]):
        try:
            reports.append(advance(run, moment=moment))
        except Exception:  # noqa: BLE001 - one bad run must not stop the rest
            logger.exception("workflow run failed to advance", extra={"run": str(run.id)})
    return reports


def sweep_orphans(older_than_seconds: int = 3600) -> int:
    """Fail runs that are active but have no tokens left to move.

    Should not happen. It exists because "the run says running and nothing is
    moving" is the failure mode that would otherwise sit there occupying a
    concurrency slot forever, and a slot that never comes back is the way a
    tenant loses the ability to start anything at all.
    """
    cutoff = timezone.now() - dt.timedelta(seconds=older_than_seconds)
    stuck = (
        WorkflowRun.objects.filter(status__in=ACTIVE_STATUSES, updated_at__lt=cutoff)
        .filter(tokens__isnull=True)
        .distinct()
    )
    count = 0
    for run in stuck:
        logger.error("workflow run had no tokens", extra={"run": str(run.id)})
        run.status = RunStatus.FAILED
        run.error = "Run had no branches left to execute"
        run.finished_at = timezone.now()
        run.wake_at = None
        run.save(update_fields=["status", "error", "finished_at", "wake_at", "updated_at"])
        count += 1
    return count
