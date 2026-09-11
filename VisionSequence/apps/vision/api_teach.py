"""站台層級現場教導參數 API。

群組只保存使用者常用參數的捷徑，實際值仍留在各自 `Flow.graph`。儲存參數值沿用
`PATCH /vision/flows/{id}`，因此操作員邊界仍由 `teachguard.assert_teach_only()` 判定。
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db import transaction
from django.http import HttpRequest
from ninja import Router, Schema

from apps.accounts.models import UserPref
from apps.accounts.security import principal, require_feature
from apps.core.errors import NotFound, ValidationError
from apps.vision.graph import topological_order
from apps.vision.models import Flow
from apps.vision.tools import base as tools

router = Router(tags=["vision-teach"])

GROUP_KEY = "station_teach_groups"
MAX_GROUPS = 32


class TeachGroupRef(Schema):
    flow_id: int
    node_id: str
    param: str


class TeachGroupIn(Schema):
    name: str | None = None
    items: list[TeachGroupRef] | None = None


class TeachGroupOrderIn(Schema):
    ids: list[str]


def _visible_flows(request: HttpRequest):
    principal(request)
    return Flow.objects.filter(kind="flow").select_related("owner").order_by("name")


def _node_title(node: dict[str, Any], fallback: str) -> str:
    return str(node.get("label") or fallback or node.get("id") or "")


def _param_visible(spec: Any, params: dict[str, Any]) -> bool:
    rule = getattr(spec, "visible_when", None)
    if not isinstance(rule, dict):
        return True
    key = rule.get("param")
    options = rule.get("in")
    if not isinstance(key, str) or not isinstance(options, list):
        return True
    return params.get(key) in options


def _teach_params_for_flow(flow: Flow) -> list[dict[str, Any]]:
    graph = flow.graph or {"nodes": [], "edges": []}
    nodes = graph.get("nodes") or []
    node_map = {str(n.get("id")): n for n in nodes if isinstance(n, dict) and n.get("id")}
    order = topological_order(nodes, graph.get("edges") or [])
    rows: list[dict[str, Any]] = []
    for node_id in order:
        node = node_map.get(node_id)
        if not node:
            continue
        try:
            tool = tools.get(str(node.get("type") or ""))
        except Exception:  # noqa: BLE001 - 舊圖若有外掛遺失，其他節點仍要列出
            continue
        params = node.get("params") or {}
        for spec in getattr(tool, "params", []) or []:
            if not getattr(spec, "teach", False) or not _param_visible(spec, params):
                continue
            rows.append({
                "id": f"{flow.id}:{node_id}:{spec.key}",
                "flow_id": flow.id,
                "flow_name": flow.name,
                "flow_version": flow.version,
                "node_id": node_id,
                "node_label": _node_title(node, tool.label),
                "tool_type": tool.key,
                "tool_label": tool.label,
                "tool_category": tool.category,
                "param": spec.as_dict(),
                "value": params.get(spec.key, spec.default),
            })
    return rows


def _clean_ref(ref: TeachGroupRef | dict[str, Any]) -> dict[str, Any]:
    data = ref.dict() if hasattr(ref, "dict") else dict(ref)
    flow_id = int(data.get("flow_id") or 0)
    node_id = str(data.get("node_id") or "").strip()
    param = str(data.get("param") or "").strip()
    if flow_id < 1 or not node_id or not param:
        raise ValidationError("A group item needs flow_id, node_id and param", code="bad_group_item")
    return {"flow_id": flow_id, "node_id": node_id[:120], "param": param[:120]}


def _clean_group(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    gid = str(raw.get("id") or "").strip() or uuid.uuid4().hex
    name = str(raw.get("name") or "").strip()[:80]
    if not name:
        return None
    items: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for item in raw.get("items") or []:
        try:
            clean = _clean_ref(item)
        except ValidationError:
            continue
        key = (clean["flow_id"], clean["node_id"], clean["param"])
        if key in seen:
            continue
        seen.add(key)
        items.append(clean)
    return {"id": gid[:40], "name": name, "items": items[:200]}


def _pref(request: HttpRequest) -> UserPref | None:
    p = principal(request)
    if p.user is None:
        return None
    return UserPref.objects.get_or_create(user=p.user)[0]


def _groups_for(request: HttpRequest) -> list[dict[str, Any]]:
    pref = _pref(request)
    if pref is None:
        return []
    raw = (pref.ui or {}).get(GROUP_KEY)
    if not isinstance(raw, list):
        return []
    groups = [_clean_group(g) for g in raw]
    return [g for g in groups if g is not None][:MAX_GROUPS]


def _save_groups(request: HttpRequest, groups: list[dict[str, Any]]) -> None:
    pref = _pref(request)
    if pref is None:
        raise ValidationError("A user account is required for teach groups", code="no_user")
    ui = dict(pref.ui or {})
    ui[GROUP_KEY] = groups
    pref.ui = ui
    pref.save(update_fields=["ui", "updated_at"])


def _resolver(request: HttpRequest) -> dict[tuple[int, str, str], dict[str, Any]]:
    rows: dict[tuple[int, str, str], dict[str, Any]] = {}
    for flow in _visible_flows(request):
        for item in _teach_params_for_flow(flow):
            rows[(item["flow_id"], item["node_id"], item["param"]["key"])] = item
    return rows


def _group_out(group: dict[str, Any], lookup: dict[tuple[int, str, str], dict[str, Any]]) -> dict[str, Any]:
    items = []
    for ref in group.get("items") or []:
        key = (int(ref.get("flow_id") or 0), str(ref.get("node_id") or ""), str(ref.get("param") or ""))
        resolved = lookup.get(key)
        if resolved:
            items.append({"valid": True, **ref, "resolved": resolved})
        else:
            items.append({"valid": False, **ref, "reason": "missing"})
    return {"id": group["id"], "name": group["name"], "items": items, "count": len(items)}


@router.get("/teach/params")
def teach_params(request: HttpRequest):
    """所有可見流程的 teach=True 參數彙總；值儲存仍走 PATCH /flows/{id}。"""
    flows = list(_visible_flows(request))
    items: list[dict[str, Any]] = []
    for flow in flows:
        items.extend(_teach_params_for_flow(flow))
    return {"items": items, "total": len(items), "flow_count": len(flows)}


@router.get("/teach/groups")
def teach_groups(request: HttpRequest):
    """目前使用者的站台教導參數捷徑群組。"""
    lookup = _resolver(request)
    return {"items": [_group_out(g, lookup) for g in _groups_for(request)], "limit": MAX_GROUPS}


@router.post("/teach/groups", response={201: dict})
def create_teach_group(request: HttpRequest, payload: TeachGroupIn):
    require_feature(request, "flows.teach")
    groups = _groups_for(request)
    if len(groups) >= MAX_GROUPS:
        raise ValidationError("A user can have at most 32 teach groups", code="too_many_groups")
    name = str(payload.name or "").strip()[:80]
    if not name:
        raise ValidationError("A group name is required", code="bad_name")
    group = {"id": uuid.uuid4().hex, "name": name, "items": [_clean_ref(i) for i in payload.items or []]}
    groups.append(group)
    with transaction.atomic():
        _save_groups(request, groups)
    return 201, _group_out(group, _resolver(request))


@router.patch("/teach/groups/order")
def reorder_teach_groups(request: HttpRequest, payload: TeachGroupOrderIn):
    require_feature(request, "flows.teach")
    groups = _groups_for(request)
    by_id = {g["id"]: g for g in groups}
    ordered = [by_id[gid] for gid in payload.ids if gid in by_id]
    ordered.extend(g for g in groups if g["id"] not in payload.ids)
    _save_groups(request, ordered)
    lookup = _resolver(request)
    return {"items": [_group_out(g, lookup) for g in ordered], "limit": MAX_GROUPS}


@router.patch("/teach/groups/{group_id}")
def patch_teach_group(request: HttpRequest, group_id: str, payload: TeachGroupIn):
    require_feature(request, "flows.teach")
    groups = _groups_for(request)
    group = next((g for g in groups if g["id"] == group_id), None)
    if group is None:
        raise NotFound("Teach group not found", code="teach_group_not_found")
    if payload.name is not None:
        name = payload.name.strip()[:80]
        if not name:
            raise ValidationError("A group name is required", code="bad_name")
        group["name"] = name
    if payload.items is not None:
        group["items"] = [_clean_ref(i) for i in payload.items]
    _save_groups(request, groups)
    return _group_out(group, _resolver(request))


@router.delete("/teach/groups/{group_id}", response={204: None})
def delete_teach_group(request: HttpRequest, group_id: str):
    require_feature(request, "flows.teach")
    groups = _groups_for(request)
    kept = [g for g in groups if g["id"] != group_id]
    if len(kept) == len(groups):
        raise NotFound("Teach group not found", code="teach_group_not_found")
    _save_groups(request, kept)
    return 204, None
