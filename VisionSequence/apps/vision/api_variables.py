"""流程變數的 API：整合端與 PLC 不必經過流程也能讀寫（換線送料號、重置計數、看目前累計）。

    GET    /vision/flows/{id}/variables            {"items": {name: value}, "station": {name: value}}
    PUT    /vision/flows/{id}/variables            {"values": {name: value, ...}}  合併寫入（現場作業：flows.teach）
    DELETE /vision/flows/{id}/variables/{name}
    GET    /vision/variables                        站台範圍
    PUT    /vision/variables                        {"values": {...}}
    DELETE /vision/variables/{name}

寫入走 write-through：API 回應前已寫進資料庫，不像引擎執行緒那樣等持久化執行緒批次寫。
"""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest
from ninja import Router

from apps.accounts.security import require_feature
from apps.core import audit
from apps.core.values import fmt_value
from apps.core.errors import NotFound, ValidationError
from apps.vision import variables
from apps.vision.api import _visible_flows, get_flow
from apps.vision.models import Flow

router = Router(tags=["variables"])

MAX_PER_REQUEST = 200


def _values_body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("Malformed JSON", code="bad_json") from None
    values = data.get("values") if isinstance(data, dict) else None
    if not isinstance(values, dict) or not values:
        raise ValidationError('Send {"values": {"name": value, ...}}', code="bad_values")
    if len(values) > MAX_PER_REQUEST:
        raise ValidationError(f"At most {MAX_PER_REQUEST} variables per request", code="too_many")
    return values


def _apply(scope: variables.Scope, values: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    for name, value in values.items():
        try:
            variables.store.set(scope, name, value)
        except variables.VariableError as exc:
            raise ValidationError(f"{name}: {exc}", code="bad_variable") from None
        changed[str(name)] = value
    variables.store.flush()
    return changed


def _flow_for(request: HttpRequest, flow_id: int) -> Flow:
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"Flow {flow_id} not found", code="flow_not_found")
    return flow


@router.get("/flows/{flow_id}/variables")
def list_flow_variables(request: HttpRequest, flow_id: int):
    flow = _flow_for(request, flow_id)
    variables.store.ensure_loaded(flow.id)
    variables.store.ensure_loaded(None)
    return {"flow_id": flow.id, "items": variables.store.snapshot(flow.id), "station": variables.store.snapshot(None)}


@router.put("/flows/{flow_id}/variables")
def put_flow_variables(request: HttpRequest, flow_id: int):
    flow = _flow_for(request, flow_id)
    require_feature(request, "flows.teach")
    variables.store.ensure_loaded(flow.id)
    changed = _apply(flow.id, _values_body(request))
    audit.record(request, "flow.variables", flow, summary=", ".join(f"{k}={fmt_value(v, 48)}" for k, v in list(changed.items())[:6]), detail=changed)
    return {"flow_id": flow.id, "items": variables.store.snapshot(flow.id)}


@router.delete("/flows/{flow_id}/variables/{name}", response={204: None})
def delete_flow_variable(request: HttpRequest, flow_id: int, name: str):
    flow = _flow_for(request, flow_id)
    require_feature(request, "flows.teach")
    variables.store.ensure_loaded(flow.id)
    try:
        found = variables.store.delete(flow.id, name)
    except variables.VariableError as exc:
        raise ValidationError(str(exc), code="bad_variable") from None
    if not found:
        raise NotFound(f"No variable named '{name}'", code="variable_not_found")
    variables.store.flush()
    audit.record(request, "flow.variables", flow, summary=f"deleted {name}")
    return 204, None


@router.get("/variables")
def list_station_variables(request: HttpRequest):
    variables.store.ensure_loaded(None)
    return {"items": variables.store.snapshot(None)}


@router.put("/variables")
def put_station_variables(request: HttpRequest):
    require_feature(request, "flows.teach")
    variables.store.ensure_loaded(None)
    changed = _apply(None, _values_body(request))
    audit.record(request, "station.variables", "station", summary=", ".join(f"{k}={fmt_value(v, 48)}" for k, v in list(changed.items())[:6]), detail=changed)
    return {"items": variables.store.snapshot(None)}


@router.delete("/variables/{name}", response={204: None})
def delete_station_variable(request: HttpRequest, name: str):
    require_feature(request, "flows.teach")
    variables.store.ensure_loaded(None)
    try:
        found = variables.store.delete(None, name)
    except variables.VariableError as exc:
        raise ValidationError(str(exc), code="bad_variable") from None
    if not found:
        raise NotFound(f"No variable named '{name}'", code="variable_not_found")
    variables.store.flush()
    audit.record(request, "station.variables", "station", summary=f"deleted {name}")
    return 204, None
