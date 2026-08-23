"""Workflow endpoints: draw, start, watch, stop.

The trigger surface is deliberately narrow. A run starts from the editor, from
another workflow, from a storage plan or over this API - and all four go
through :func:`apps.workflows.runner.start_run`, so the concurrency cap and the
enabled check cannot be reached around.
"""

from __future__ import annotations

import uuid

from django.db.models import Count, Q
from ninja import Query, Router

from apps.accounts.models import Role
from apps.accounts.security import AuthContext, role_required
from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.core.errors import Conflict, NotFound
from apps.core.schemas import OkResponse, Page, PageParams, paginate
from apps.core.timeutils import now
from apps.devices.models import Site
from apps.workflows import nodes
from apps.workflows import schemas as s
from apps.workflows.graph import validate_graph
from apps.workflows import templates as tpl
from apps.workflows.models import (
    ACTIVE_STATUSES,
    TriggerSource,
    Workflow,
    WorkflowLog,
    WorkflowRun,
    WorkflowTemplate,
)
from apps.workflows.runner import (
    max_concurrent_runs,
    pause_run,
    resume_run,
    run_single_node,
    start_run,
    step_run,
    stop_run,
)

router = Router(tags=["workflows"])
runs_router = Router(tags=["workflow-runs"])


def _get_workflow(ctx: AuthContext, workflow_id: uuid.UUID) -> Workflow:
    workflow = (
        Workflow.objects.filter(
            pk=workflow_id, organization=ctx.organization, deleted_at__isnull=True
        )
        .select_related("site")
        .first()
    )
    if workflow is None:
        raise NotFound("Workflow not found")
    return workflow


def _resolve_site(ctx: AuthContext, site_id):
    if not site_id:
        return None
    site = Site.objects.filter(
        pk=site_id, organization=ctx.organization, deleted_at__isnull=True
    ).first()
    if site is None:
        raise NotFound("Site not found")
    return site


# --------------------------------------------------------------------------
# Node catalogue
# --------------------------------------------------------------------------
@router.get("/node-types", response=list[s.NodeTypeOut])
def list_node_types(request):
    """The palette, and the parameter form for each node.

    The console renders both from this, so registering a node type on the
    server is all it takes for it to appear in the editor with a working form.
    A hard-coded copy in the frontend would be a second list to keep in step,
    and it would be the one that fell behind.
    """
    return nodes.catalogue()


@router.get("/capacity", response=s.WorkflowCapacityOut)
def capacity(request):
    """The branch budget: the server limit, live usage, and who is using it.

    The unit is *branches* (parallel tokens), not runs - a run whose graph has
    two entry points costs two. The per-run breakdown exists because "1 / 5
    used and I stopped everything" is unanswerable without naming the run
    that is still holding a slot.
    """
    from django.db.models import Count

    ctx: AuthContext = request.auth
    holders = (
        WorkflowRun.objects.filter(
            organization=ctx.organization, status__in=ACTIVE_STATUSES
        )
        .annotate(branches=Count("tokens"))
        .select_related("workflow")
        .order_by("created_at")
    )
    return {
        "limit": max_concurrent_runs(),
        "active": sum(run.branches for run in holders),
        "runs": [
            {
                "run_id": run.id,
                "workflow_name": run.workflow.name,
                "status": run.status,
                "branches": run.branches,
            }
            for run in holders
        ],
    }


# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Templates（路由要排在 /{workflow_id} 之前，否則 "templates" 會被當成 id）
# --------------------------------------------------------------------------
def _template_out(template: tpl.Template, created_at=None) -> dict:
    return {
        "id": template.id, "name": template.name, "description": template.description,
        "source": template.source, "category": template.category, "node_count": template.node_count,
        "placeholders": template.placeholders,
        "placeholder_labels": {k: tpl.PLACEHOLDER_LABELS.get(k, k) for k in template.placeholders},
        "graph": template.graph, "created_at": created_at,
    }


def _custom_template(ctx: AuthContext, template_id: str) -> WorkflowTemplate:
    try:
        pk = uuid.UUID(template_id)
    except ValueError as exc:
        raise NotFound("Template not found") from exc
    row = WorkflowTemplate.objects.filter(organization=ctx.organization, pk=pk).first()
    if row is None:
        raise NotFound("Template not found")
    return row


def _load_template(ctx: AuthContext, template_id: str) -> tpl.Template:
    if template_id.startswith("builtin:"):
        found = tpl.builtin_by_id(template_id)
        if found is None:
            raise NotFound("Template not found")
        return found
    row = _custom_template(ctx, template_id)
    return tpl.Template(
        id=str(row.id), name=row.name, description=row.description, source="custom",
        graph=row.graph, placeholders=list(row.placeholders or []),
    )


@router.get("/templates", response=list[s.WorkflowTemplateOut])
def list_templates(request):
    """內建範本（程式碼）＋這個租戶自存的範本。"""
    ctx: AuthContext = request.auth
    out = [_template_out(t) for t in tpl.builtin_templates()]
    for row in WorkflowTemplate.objects.filter(organization=ctx.organization):
        out.append(_template_out(
            tpl.Template(id=str(row.id), name=row.name, description=row.description, source="custom",
                         graph=row.graph, placeholders=list(row.placeholders or [])),
            created_at=row.created_at,
        ))
    return out


@router.post("/templates", response={201: s.WorkflowTemplateOut}, auth=role_required(Role.OPERATOR))
def create_template(request, payload: s.WorkflowTemplateIn):
    """把目前畫布存成範本：設備 id 換成角色佔位符，才能載到別的場域。"""
    ctx: AuthContext = request.auth
    graph = validate_graph(payload.graph or {"nodes": [], "edges": []})
    templatized, placeholders = tpl.templatize(graph, ctx.organization)
    if WorkflowTemplate.objects.filter(organization=ctx.organization, name=payload.name).exists():
        raise Conflict(f"A template called '{payload.name}' already exists", code="template_name_taken")
    row = WorkflowTemplate.objects.create(
        organization=ctx.organization, name=payload.name, description=payload.description,
        graph=templatized, placeholders=placeholders, created_by=ctx.user,
    )
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=row,
           payload={"template": row.name, "action": "template_created"})
    return 201, _template_out(
        tpl.Template(id=str(row.id), name=row.name, description=row.description, source="custom",
                     graph=row.graph, placeholders=placeholders),
        created_at=row.created_at,
    )


@router.delete("/templates/{template_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_template(request, template_id: str):
    ctx: AuthContext = request.auth
    if template_id.startswith("builtin:"):
        raise Conflict("Built-in templates cannot be deleted", code="template_builtin")
    row = _custom_template(ctx, template_id)
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=row,
           payload={"template": row.name, "action": "template_deleted"})
    row.delete()
    return {"ok": True, "message": "template_deleted"}


@router.post("/templates/{template_id}/instantiate", response=s.TemplateInstantiateOut)
def instantiate_template(request, template_id: str, payload: s.TemplateInstantiateIn):
    """依場域把範本解成可載入畫布的圖。不寫資料庫——要不要變成流程由前端決定。"""
    ctx: AuthContext = request.auth
    template = _load_template(ctx, template_id)
    site = _resolve_site(ctx, payload.site_id)
    graph, missing = tpl.instantiate(template.graph, site, ctx.organization)
    if payload.fresh_ids:
        graph = tpl.with_fresh_ids(graph)
    return {
        "graph": graph, "missing": missing,
        "missing_labels": {k: tpl.PLACEHOLDER_LABELS.get(k, k) for k in missing},
    }


@router.get("", response=Page[s.WorkflowOut])
def list_workflows(request, params: Query[PageParams], site_id: uuid.UUID | None = None):
    ctx: AuthContext = request.auth
    queryset = (
        Workflow.objects.filter(
            organization=ctx.organization, deleted_at__isnull=True
        )
        .select_related("site")
        .annotate(
            active_runs_annotated=Count(
                "runs", filter=Q(runs__status__in=ACTIVE_STATUSES), distinct=True
            )
        )
        .order_by("name")
    )
    if site_id:
        queryset = queryset.filter(site_id=site_id)
    return paginate(queryset, params)


@router.post("", response={201: s.WorkflowOut}, auth=role_required(Role.OPERATOR))
def create_workflow(request, payload: s.WorkflowIn):
    ctx: AuthContext = request.auth
    graph = validate_graph(payload.graph or {"nodes": [], "edges": []})

    if Workflow.objects.filter(
        organization=ctx.organization, name=payload.name, deleted_at__isnull=True
    ).exists():
        raise Conflict(
            f"A workflow called '{payload.name}' already exists",
            code="workflow_name_taken",
        )

    workflow = Workflow.objects.create(
        organization=ctx.organization,
        site=_resolve_site(ctx, payload.site_id),
        name=payload.name,
        description=payload.description,
        is_enabled=payload.is_enabled,
        graph=graph,
        created_by=ctx.user,
    )
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=workflow,
           payload={"workflow": workflow.name, "action": "created"})
    return 201, workflow


@router.get("/{workflow_id}", response=s.WorkflowOut)
def get_workflow(request, workflow_id: uuid.UUID):
    return _get_workflow(request.auth, workflow_id)


@router.patch("/{workflow_id}", response=s.WorkflowOut, auth=role_required(Role.OPERATOR))
def update_workflow(request, workflow_id: uuid.UUID, payload: s.WorkflowUpdateIn):
    """Save the drawing.

    The graph is validated here rather than at run time so a typo surfaces
    while the operator is still looking at the canvas.
    """
    ctx: AuthContext = request.auth
    workflow = _get_workflow(ctx, workflow_id)
    data = payload.dict(exclude_unset=True)

    if "site_id" in data:
        workflow.site = _resolve_site(ctx, data.pop("site_id"))
    if "graph" in data:
        workflow.graph = validate_graph(data.pop("graph") or {})
        # Versioned so a run's log can still be read against the graph it
        # actually executed, months after the canvas moved on.
        workflow.version += 1
    for field, value in data.items():
        setattr(workflow, field, value)
    workflow.save()

    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=workflow,
           payload={"workflow": workflow.name, "version": workflow.version})
    return workflow


@router.delete("/{workflow_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_workflow(request, workflow_id: uuid.UUID):
    """Remove a workflow. Active runs are stopped first.

    Leaving them going would mean a deleted workflow still commanding
    equipment, with nothing in the console pointing at what was doing it.
    """
    ctx: AuthContext = request.auth
    workflow = _get_workflow(ctx, workflow_id)

    stopped = 0
    for run in workflow.runs.filter(status__in=ACTIVE_STATUSES):
        stop_run(run, reason="Workflow deleted")
        stopped += 1

    workflow.deleted_at = now()
    workflow.save(update_fields=["deleted_at", "updated_at"])
    record(AuditAction.EMS_PLAN_UPDATED, ctx=ctx, target=workflow,
           payload={"workflow": workflow.name, "action": "deleted",
                    "stopped_runs": stopped})
    return {"ok": True, "message": "workflow_deleted"}


@router.post(
    "/{workflow_id}/runs", response={202: s.RunOut}, auth=role_required(Role.OPERATOR)
)
def start_workflow(request, workflow_id: uuid.UUID, payload: s.RunStartIn):
    """Start a run. Refused, not queued, when the tenant is at its limit."""
    ctx: AuthContext = request.auth
    workflow = _get_workflow(ctx, workflow_id)
    run = start_run(
        workflow,
        trigger=TriggerSource.API if request.headers.get("X-Api-Key") else TriggerSource.MANUAL,
        started_by=ctx.user,
        dry_run=payload.dry_run,
        context=payload.context,
        step_delay_seconds=payload.step_delay_seconds,
        start_paused=payload.start_paused,
    )
    record(AuditAction.DEVICE_COMMAND_SENT, ctx=ctx, target=workflow,
           payload={"workflow": workflow.name, "run": str(run.id),
                    "dry_run": payload.dry_run})
    return 202, run


@router.post(
    "/{workflow_id}/run-node",
    response={202: s.RunOut},
    auth=role_required(Role.OPERATOR),
)
def run_workflow_node(request, workflow_id: uuid.UUID, payload: s.RunNodeIn):
    """Execute one node on its own and finish - no edges are followed."""
    ctx: AuthContext = request.auth
    workflow = _get_workflow(ctx, workflow_id)
    run = run_single_node(
        workflow,
        node_id=payload.node_id,
        started_by=ctx.user,
        dry_run=payload.dry_run,
        context=payload.context,
    )
    record(AuditAction.DEVICE_COMMAND_SENT, ctx=ctx, target=workflow,
           payload={"workflow": workflow.name, "run": str(run.id),
                    "node": payload.node_id, "dry_run": payload.dry_run,
                    "action": "run_node"})
    return 202, run


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------
@runs_router.get("", response=Page[s.RunOut])
def list_runs(request, filters: Query[s.RunFilters], params: Query[PageParams]):
    ctx: AuthContext = request.auth
    queryset = (
        WorkflowRun.objects.filter(organization=ctx.organization)
        .select_related("workflow")
        .prefetch_related("tokens")
    )
    active = filters.active
    filters = filters.model_copy(update={"active": None})
    queryset = filters.filter(queryset)
    if active is True:
        queryset = queryset.filter(status__in=ACTIVE_STATUSES)
    elif active is False:
        queryset = queryset.exclude(status__in=ACTIVE_STATUSES)
    return paginate(queryset.order_by("-created_at"), params)


def _get_run(ctx: AuthContext, run_id: uuid.UUID) -> WorkflowRun:
    run = (
        WorkflowRun.objects.filter(pk=run_id, organization=ctx.organization)
        .select_related("workflow")
        .prefetch_related("tokens")
        .first()
    )
    if run is None:
        raise NotFound("Run not found")
    return run


@runs_router.get("/{run_id}", response=s.RunOut)
def get_run(request, run_id: uuid.UUID):
    return _get_run(request.auth, run_id)


@runs_router.get("/{run_id}/logs", response=Page[s.RunLogOut])
def run_logs(request, run_id: uuid.UUID, params: Query[PageParams]):
    """What the engine did, oldest first - the order it happened in."""
    ctx: AuthContext = request.auth
    run = _get_run(ctx, run_id)
    return paginate(WorkflowLog.objects.filter(run=run).order_by("ts", "id"), params)


@runs_router.post("/{run_id}/stop", response=s.RunOut, auth=role_required(Role.OPERATOR))
def stop_workflow_run(request, run_id: uuid.UUID):
    ctx: AuthContext = request.auth
    run = _get_run(ctx, run_id)
    stop_run(run, reason=f"Stopped by {ctx.principal_label}")
    record(AuditAction.DEVICE_COMMAND_SENT, ctx=ctx, target=run.workflow,
           payload={"workflow": run.workflow.name, "run": str(run.id),
                    "action": "stopped"})
    run.refresh_from_db()
    return run


@runs_router.post("/{run_id}/pause", response=s.RunOut, auth=role_required(Role.OPERATOR))
def pause_workflow_run(request, run_id: uuid.UUID):
    """Freeze a run in place. Resume continues exactly where it stood."""
    ctx: AuthContext = request.auth
    run = _get_run(ctx, run_id)
    pause_run(run, reason=f"Paused by {ctx.principal_label}")
    run.refresh_from_db()
    return run


@runs_router.post("/{run_id}/resume", response=s.RunOut, auth=role_required(Role.OPERATOR))
def resume_workflow_run(request, run_id: uuid.UUID):
    ctx: AuthContext = request.auth
    run = _get_run(ctx, run_id)
    resume_run(run)
    run.refresh_from_db()
    return run


@runs_router.post("/{run_id}/step", response=s.RunOut, auth=role_required(Role.OPERATOR))
def step_workflow_run(request, run_id: uuid.UUID):
    """Execute exactly one node, then pause again - the debugger's single-step."""
    ctx: AuthContext = request.auth
    run = _get_run(ctx, run_id)
    step_run(run)
    run.refresh_from_db()
    return run
