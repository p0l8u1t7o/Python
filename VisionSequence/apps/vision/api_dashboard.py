"""Dashboard API：站台層級運行介面的版面與資料入口。"""

from __future__ import annotations

import copy
import json
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router

from apps.accounts.models import EngineLock
from apps.accounts.security import principal, require_feature
from apps.core import audit
from apps.core.errors import NotFound, ValidationError
from apps.vision import __version__, board, dashboard, variables
from apps.vision.api import _visible_flows
from apps.vision import models as vision_models
from apps.vision.runner import runner

Dashboard = vision_models.Dashboard

router = Router(tags=["dashboard"])


def _body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("Malformed JSON", code="bad_json") from None
    if not isinstance(data, dict):
        raise ValidationError("Request body must be an object", code="bad_json")
    return data


def _layout(raw: Any) -> dict[str, Any]:
    try:
        return dashboard.validate(copy.deepcopy(raw))
    except dashboard.DashboardError as exc:
        raise ValidationError(str(exc), code="bad_layout") from None


def _dashboard(row_id: int) -> Dashboard:
    row = Dashboard.objects.select_related("owner").filter(pk=row_id).first()
    if row is None:
        raise NotFound("Dashboard not found", code="dashboard_not_found")
    return row


def _out(row: Dashboard) -> dict[str, Any]:
    layout = dashboard.effective(row.layout)
    return {
        "id": row.id,
        "name": row.name,
        "is_default": row.is_default,
        "owner_name": row.owner.username if row.owner_id else "",
        "updated_at": row.updated_at.isoformat(),
        "widget_count": len(layout.get("widgets") or []),
    }


def _full(row: Dashboard) -> dict[str, Any]:
    return {**_out(row), "layout": dashboard.effective(row.layout)}


@router.get("/dashboards")
def list_dashboards(request: HttpRequest):
    principal(request)
    return {"items": [_out(row) for row in Dashboard.objects.select_related("owner").all()]}


@router.post("/dashboards", response={201: dict})
def create_dashboard(request: HttpRequest):
    p = require_feature(request, "flows.edit")
    data = _body(request)
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("A dashboard name is required", code="bad_name")
    layout = _layout(data.get("layout", dashboard.DEFAULT_LAYOUT))
    with transaction.atomic():
        row = Dashboard.objects.create(name=name[:200], layout=layout, is_default=bool(data.get("is_default")), owner=p.user)
    audit.record(request, "dashboard.create", row, summary=("default" if row.is_default else ""), detail={"widget_count": len(layout.get("widgets") or [])})
    return 201, _full(row)


@router.get("/dashboards/default")
def get_default_dashboard(request: HttpRequest):
    principal(request)
    row = Dashboard.objects.select_related("owner").filter(is_default=True).first()
    if row is None:
        raise NotFound("No default dashboard is configured", code="no_default")
    return _full(row)


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(request: HttpRequest, dashboard_id: int):
    principal(request)
    return _full(_dashboard(dashboard_id))


@router.patch("/dashboards/{dashboard_id}")
def patch_dashboard(request: HttpRequest, dashboard_id: int):
    require_feature(request, "flows.edit")
    row = _dashboard(dashboard_id)
    data = _body(request)
    before = {"name": row.name, "layout": row.layout, "is_default": row.is_default}
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValidationError("A dashboard name is required", code="bad_name")
        row.name = name[:200]
    if "layout" in data:
        row.layout = _layout(data.get("layout"))
    if "is_default" in data:
        row.is_default = bool(data.get("is_default"))
    with transaction.atomic():
        row.save()
    after = {"name": row.name, "layout": row.layout, "is_default": row.is_default}
    changes = audit.fields_diff(before, after, ("name", "layout", "is_default"))
    audit.record(request, "dashboard.update", row, summary=audit.summarize_fields(changes) if changes else "", detail=changes)
    return _full(row)


@router.delete("/dashboards/{dashboard_id}", response={204: None})
def delete_dashboard(request: HttpRequest, dashboard_id: int):
    require_feature(request, "flows.edit")
    row = _dashboard(dashboard_id)
    audit.record(request, "dashboard.delete", row)
    row.delete()
    return 204, None


@router.get("/dashboards/{dashboard_id}/data")
def dashboard_data(request: HttpRequest, dashboard_id: int):
    principal(request)
    row = _dashboard(dashboard_id)
    layout = dashboard.effective(row.layout)
    flow_ids = dashboard.flows_of(layout)
    visible = {f.id: f for f in _visible_flows(request).filter(id__in=flow_ids)}
    counts = board.today_counts_many(flow_ids)
    flows: dict[int, Any] = {}
    for flow_id in sorted(flow_ids):
        flow = visible.get(flow_id)
        if flow is None:
            flows[flow_id] = {"missing": True}
            continue
        variables.store.ensure_loaded(flow.id)
        rt = runner.runtime(flow.id)
        latest = rt.recent[-1].to_dict(include_node_outputs=True) if rt.recent else None
        original_board = flow.board
        flow.board = {**(original_board or {}), "show_counts": False}
        try:
            payload = board.build(flow, latest, variables=variables.store.snapshot(flow.id), stats=rt.stats.to_dict())
        finally:
            flow.board = original_board
        payload["counts"] = counts.get(flow.id) if board.effective(original_board).get("show_counts") else None
        flows[flow.id] = payload
    variables.store.ensure_loaded(None)
    capacity = runner.capacity()
    lock = EngineLock.current()
    return {
        "generated_at": timezone.now().isoformat(),
        "flows": flows,
        "device": {
            "station_id": str(settings.VISION.get("STATION_ID", "ST01")),
            "version": __version__,
            "lock": {"locked": bool(lock.locked), "holder": lock.holder, "reason": lock.reason},
            "capacity": capacity,
            "flows_running": [row["flow_id"] for row in capacity.get("flows", []) if row.get("running")],
        },
        "variables": {"station": variables.store.snapshot(None)},
    }
