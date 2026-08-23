"""Request and response shapes for the workflow API."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from ninja import Field, FilterSchema, Schema

from apps.workflows.models import RunStatus, TriggerSource


class WorkflowIn(Schema):
    name: str = Field(max_length=200)
    description: str = ""
    site_id: uuid.UUID | None = None
    is_enabled: bool = True
    #: ``{"nodes": [...], "edges": [...]}`` straight from the editor, canvas
    #: positions included. Validated by :mod:`apps.workflows.graph`.
    graph: dict[str, Any] = Field(default_factory=dict)


class WorkflowUpdateIn(Schema):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    site_id: uuid.UUID | None = None
    is_enabled: bool | None = None
    graph: dict[str, Any] | None = None


class WorkflowOut(Schema):
    id: uuid.UUID
    name: str
    description: str
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    is_enabled: bool
    version: int
    graph: dict[str, Any] = Field(default_factory=dict)
    node_count: int = 0
    #: Runs of this workflow that are still going.
    active_run_count: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime

    @staticmethod
    def resolve_site_name(obj) -> str | None:
        return obj.site.name if obj.site_id else None

    @staticmethod
    def resolve_node_count(obj) -> int:
        return len(obj.nodes)

    @staticmethod
    def resolve_active_run_count(obj) -> int:
        cached = getattr(obj, "active_runs_annotated", None)
        if cached is not None:
            return cached
        from apps.workflows.models import ACTIVE_STATUSES

        return obj.runs.filter(status__in=ACTIVE_STATUSES).count()


class WorkflowSummaryOut(Schema):
    """The lighter shape for pickers, without the graph."""

    id: uuid.UUID
    name: str
    is_enabled: bool
    site_id: uuid.UUID | None = None


class RunStartIn(Schema):
    #: Evaluate everything, send nothing. The editor's test button.
    dry_run: bool = False
    #: Seed values the graph can read.
    context: dict[str, Any] = Field(default_factory=dict)
    #: Slow motion: extra seconds between node executions, for watching a run
    #: walk the canvas. Clamped server-side to 0-30.
    step_delay_seconds: float = Field(default=0.0, ge=0.0, le=30.0)
    #: Born paused, for single-stepping from the very first node.
    start_paused: bool = False


class RunNodeIn(Schema):
    """Run exactly one node, alone. The editor's "run this node" button."""

    node_id: str = Field(max_length=64)
    dry_run: bool = False
    context: dict[str, Any] = Field(default_factory=dict)


class RunOut(Schema):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str = ""
    status: RunStatus
    trigger: TriggerSource
    dry_run: bool
    workflow_version: int
    steps_taken: int
    step_delay_seconds: float = 0.0
    error: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    wake_at: dt.datetime | None = None
    created_at: dt.datetime
    #: Where each branch currently sits, so the editor can light up the canvas.
    active_nodes: list[str] = Field(default_factory=list)

    @staticmethod
    def resolve_workflow_name(obj) -> str:
        return obj.workflow.name if obj.workflow_id else ""

    @staticmethod
    def resolve_active_nodes(obj) -> list[str]:
        return sorted({token.node_id for token in obj.tokens.all()})


class RunLogOut(Schema):
    id: int
    ts: dt.datetime
    node_id: str
    node_label: str
    level: str
    message: str
    branch: str
    detail: dict[str, Any] = Field(default_factory=dict)


class RunFilters(FilterSchema):
    workflow_id: uuid.UUID | None = Field(default=None, q="workflow_id")
    status: RunStatus | None = Field(default=None, q="status")
    #: Active means pending, running or waiting - the states that occupy a slot.
    active: bool | None = None


class NodeParamOut(Schema):
    key: str
    label: str
    kind: str
    required: bool
    default: Any = None
    help_text: str = ""
    options: list[dict[str, Any]] = Field(default_factory=list)
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None


class NodeHandleOut(Schema):
    key: str
    label: str
    tone: str


class NodeTypeOut(Schema):
    key: str
    label: str
    description: str
    category: str
    icon: str
    params: list[NodeParamOut] = Field(default_factory=list)
    handles: list[NodeHandleOut] = Field(default_factory=list)


class CapacityHolderOut(Schema):
    run_id: uuid.UUID
    workflow_name: str
    status: str
    branches: int


class WorkflowCapacityOut(Schema):
    """The branch budget and who is spending it.

    The console needs the numbers to explain a refusal before the operator
    presses the button - and the holder list to answer "I stopped everything,
    what is still using a slot?".
    """

    limit: int
    active: int
    runs: list[CapacityHolderOut] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------
class WorkflowTemplateOut(Schema):
    """一個範本。``id`` 內建為 ``builtin:<n>``、自訂為 UUID 字串。"""

    id: str
    name: str
    description: str = ""
    source: str  # builtin | custom
    category: str = ""
    node_count: int = 0
    #: 載入時需要解回的佔位符（BESS / METER / PV / LOAD / EMS / WORKFLOW:名稱）。
    placeholders: list[str] = Field(default_factory=list)
    placeholder_labels: dict[str, str] = Field(default_factory=dict)
    graph: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime | None = None


class WorkflowTemplateIn(Schema):
    name: str = Field(max_length=200)
    description: str = ""
    graph: dict[str, Any] = Field(default_factory=dict)


class TemplateInstantiateIn(Schema):
    #: 依這個場域解回佔位符；留空只換 run_workflow 目標。
    site_id: uuid.UUID | None = None
    #: 節點 id 重新產生，給「載進已有內容的畫布」用。
    fresh_ids: bool = False


class TemplateInstantiateOut(Schema):
    graph: dict[str, Any]
    #: 解不回來的佔位符；使用者要在畫布上自己挑設備。
    missing: list[str] = Field(default_factory=list)
    missing_labels: dict[str, str] = Field(default_factory=dict)
