"""Visual control flows: the definition, and the state of one execution.

A workflow is a graph an operator draws. It is *triggered* - from the editor,
by another workflow, or over the API - rather than polled, so an execution is a
long-lived thing with a position, not a function that returns.

Three decisions shape everything below.

**The graph lives in one JSON column, not in node and edge tables.** The editor
saves the whole canvas at once and nothing queries an individual node, so
relational storage would buy joins nobody performs and cost an atomic save. The
shape is validated on the way in - see :mod:`apps.workflows.graph`.

**Execution state is relational, because it is queried constantly.** "Which
runs are active", "how many is this tenant using", "what happened at 14:03" are
all real questions with real indexes behind them.

**Parallelism is modelled as tokens, not threads.** A run holds one or more
:class:`WorkflowToken` rows, each sitting at a node. A branch that forks adds
tokens; one that ends removes them. No OS thread is involved, which is what
makes a run survivable across a process restart - the position is in the
database, not on a stack.
"""

from __future__ import annotations

import datetime as dt

from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Organization, User
from apps.core.models import SoftDeleteModel, TimeStampedModel, UUIDPrimaryKeyModel
from apps.devices.models import Site

#: Node ids are authored in the editor and referenced by ``jump`` targets, so
#: they have to survive a round trip through JSON and stay greppable.
NODE_ID_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$",
    message=_("Node id must be 1-64 characters of letters, digits, '_' or '-'."),
)


class RunStatus(models.TextChoices):
    """Where an execution is.

    ``WAITING`` is distinct from ``RUNNING`` on purpose: a run parked on a
    timer is healthy and should not be counted against the "is anything stuck"
    question, but it is also not doing work and should not look busy.
    """

    PENDING = "pending", _("Queued")
    RUNNING = "running", _("Running")
    WAITING = "waiting", _("Waiting on a timer")
    #: Halted by an operator or a breakpoint, resumable. Distinct from
    #: ``WAITING``: a paused run does not move however long you wait.
    PAUSED = "paused", _("Paused")
    SUCCEEDED = "succeeded", _("Finished")
    FAILED = "failed", _("Failed")
    CANCELLED = "cancelled", _("Stopped by an operator")


#: Statuses the engine should pick up and move.
RUNNABLE_STATUSES = (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING)

#: Statuses that still occupy one of the tenant's concurrent slots. Paused
#: counts: the run holds tokens and can resume at any moment, so exempting it
#: would let pausing become a way to stack unlimited runs.
ACTIVE_STATUSES = (*RUNNABLE_STATUSES, RunStatus.PAUSED)

#: Statuses nothing will move again.
TERMINAL_STATUSES = (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED)


class TriggerSource(models.TextChoices):
    MANUAL = "manual", _("Started from the editor")
    API = "api", _("Started over the API")
    WORKFLOW = "workflow", _("Started by another workflow")
    STORAGE_PLAN = "storage_plan", _("Started by a storage plan")


class Workflow(UUIDPrimaryKeyModel, TimeStampedModel, SoftDeleteModel):
    """One graph an operator drew."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflows"
    )
    #: Optional scoping. A workflow bound to a site can only command devices
    #: at that site, which is what makes it safe to hand to a site operator.
    site = models.ForeignKey(
        Site,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflows",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    #: ``{"nodes": [...], "edges": [...]}`` exactly as the editor saved it,
    #: including canvas positions. Validated by :mod:`apps.workflows.graph`.
    graph = models.JSONField(default=dict, blank=True)

    #: Disabled workflows can be edited but never started. A separate flag from
    #: deletion because "switch this off for a fortnight" is the common case and
    #: deleting loses the drawing.
    is_enabled = models.BooleanField(default=True)

    #: Bumped on every save of the graph. A run records the version it started
    #: under, so a log read months later is not silently reinterpreted against
    #: a graph that has since been redrawn.
    version = models.PositiveIntegerField(default=1)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "workflows_workflow"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_workflow_org_name",
            )
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def nodes(self) -> list[dict]:
        return list((self.graph or {}).get("nodes") or [])

    @property
    def edges(self) -> list[dict]:
        return list((self.graph or {}).get("edges") or [])


class WorkflowRun(UUIDPrimaryKeyModel, TimeStampedModel):
    """One execution of a workflow."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="workflow_runs"
    )
    workflow = models.ForeignKey(
        Workflow, on_delete=models.CASCADE, related_name="runs"
    )
    #: The graph as it was when this run started. A run that outlives an edit
    #: keeps executing what the operator actually approved.
    graph = models.JSONField(default=dict, blank=True)
    workflow_version = models.PositiveIntegerField(default=1)

    status = models.CharField(
        max_length=12, choices=RunStatus.choices, default=RunStatus.PENDING
    )
    trigger = models.CharField(
        max_length=16, choices=TriggerSource.choices, default=TriggerSource.MANUAL
    )
    #: Set when another workflow started this one, so a chain can be followed
    #: back to whatever kicked it off.
    parent_run = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )
    started_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    #: Values the run carries between nodes, and the inputs it was started
    #: with. Node parameters can read from it.
    context = models.JSONField(default=dict, blank=True)

    #: **Dry runs evaluate every condition but send no commands.** This is the
    #: editor's test button, and it is a field on the run rather than a
    #: parameter so that a log read later still says whether anything actually
    #: reached the hardware.
    dry_run = models.BooleanField(default=False)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    #: When the engine should next look at this run. Null means "as soon as
    #: possible"; a future time is a timer that has not expired.
    wake_at = models.DateTimeField(null=True, blank=True, db_index=True)
    error = models.TextField(blank=True)

    #: Guard against a runaway ``jump`` loop. Counted in node transitions, not
    #: wall clock, because a tight loop burns steps without burning time.
    steps_taken = models.PositiveIntegerField(default=0)

    #: Extra seconds inserted between node executions - slow motion, for
    #: watching a run walk the canvas. On the run rather than the workflow
    #: because it is a property of *this viewing*, not of the logic.
    step_delay_seconds = models.FloatField(default=0.0)

    class Meta:
        db_table = "workflows_run"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["status", "wake_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.workflow_id} [{self.status}]"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def duration(self) -> dt.timedelta | None:
        if self.started_at is None:
            return None
        return (self.finished_at or timezone.now()) - self.started_at


class WorkflowToken(models.Model):
    """One position in a running graph.

    A run with three tokens is executing three branches at once. Forking adds
    tokens, a branch reaching the end removes one, and the run finishes when
    the last one goes - which is also why a graph with no reachable end never
    finishes on its own and has to be stopped or hit the step limit.
    """

    run = models.ForeignKey(
        WorkflowRun, on_delete=models.CASCADE, related_name="tokens"
    )
    node_id = models.CharField(max_length=64, validators=[NODE_ID_VALIDATOR])
    #: Per-token scratch space. The timer node keeps "since when has the
    #: condition been true" here, which is why it survives a restart.
    state = models.JSONField(default=dict, blank=True)
    #: Null means ready now.
    wake_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workflows_token"
        indexes = [models.Index(fields=["run", "node_id"])]

    def __str__(self) -> str:
        return f"{self.run_id}@{self.node_id}"


class LogLevel(models.TextChoices):
    DEBUG = "debug", _("Debug")
    INFO = "info", _("Info")
    WARNING = "warning", _("Warning")
    ERROR = "error", _("Error")


class WorkflowLog(models.Model):
    """What the engine did, step by step.

    The editor's test view reads this back, so it is written for a person
    debugging their own graph: which node, what it decided, and why. A log that
    only records failures cannot answer "why did it take the false branch",
    which is the question people actually have.
    """

    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="logs")
    ts = models.DateTimeField(default=timezone.now, db_index=True)
    node_id = models.CharField(max_length=64, blank=True)
    node_label = models.CharField(max_length=200, blank=True)
    level = models.CharField(max_length=8, choices=LogLevel.choices, default=LogLevel.INFO)
    message = models.TextField(blank=True)
    #: Which output handle the node left by, for drawing the taken path.
    branch = models.CharField(max_length=32, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "workflows_log"
        ordering = ["ts", "id"]
        indexes = [models.Index(fields=["run", "ts"])]

    def __str__(self) -> str:
        return f"{self.node_id}: {self.message[:60]}"
