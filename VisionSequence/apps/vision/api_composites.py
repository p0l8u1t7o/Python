"""複合工具 API（PRODUCT-DIRECTION v2 §3）：工具庫 CRUD、影響清單、.tool.json 匯出匯入、另存為我的工具。

GET    /vision/composite-tools                    清單（含用了幾條流程）
POST   /vision/composite-tools                    建立 {key, label, description?, category?, icon?, graph, interface}（tools.edit）
POST   /vision/composite-tools/import             multipart file 或 JSON {doc | ...doc, replace?}（tools.edit）
GET    /vision/composite-tools/{id}               含 graph 與影響數
PUT    /vision/composite-tools/{id}               部分更新（tools.edit；內建工具 409）
DELETE /vision/composite-tools/{id}               仍被使用回 409 composite_in_use（details 列出流程與工具）
GET    /vision/composite-tools/{id}/usage         影響清單
GET    /vision/composite-tools/{id}/versions      版本清單；/{id}/versions/{v} 那一版的圖與介面；/{id}/diff?from_version=&to_version= 兩版差異（P5）
GET    /vision/composite-tools/{id}/export        .tool.json（含巢狀依賴與固定影像）
POST   /vision/composite-tools/{id}/duplicate     另存為我的工具 {key?, label?}
"""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, HttpResponse
from ninja import Body, Router

from apps.accounts.security import principal, require_feature
from apps.core import audit
from apps.core.errors import ValidationError
from apps.vision import composites, serialize
from apps.vision.models import CompositeTool

router = Router(tags=["composite-tools"])


@router.get("/composite-tools")
def list_tools(request: HttpRequest):
    principal(request)
    rows = CompositeTool.objects.select_related("flow", "created_by").order_by("-builtin", "label")
    return {"items": [composites.out(row, with_usage=True) for row in rows]}


@router.post("/composite-tools", response={201: dict})
def create_tool(request: HttpRequest, payload: Body[dict]):
    p = require_feature(request, "tools.edit")
    row = composites.create(p.user, payload)
    audit.record(request, "tool.create", row, summary=row.key)
    return 201, composites.out(row, graph=True, with_usage=True)


@router.post("/composite-tools/import", response={200: dict, 201: dict})
def import_tool(request: HttpRequest):
    """multipart：file 欄位＋可選 form 欄位 replace；JSON：整份 .tool.json 當 body，或 {"doc": {...}, "replace": true}。"""
    p = require_feature(request, "tools.edit")
    upload = request.FILES.get("file")
    replace = False
    if upload is not None:
        doc: Any = serialize.parse_any(upload.read())
        replace = str(request.POST.get("replace") or "").lower() in ("1", "true", "yes")
    else:
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Not valid JSON: {exc}", code="bad_json") from None
        if isinstance(body, dict) and isinstance(body.get("doc"), dict):
            doc = body["doc"]
            replace = bool(body.get("replace"))
        else:
            doc = body
    row, action = composites.import_doc(p.user, doc, replace=replace)
    audit.record(request, "tool.import", row, summary=f"{row.key}: {action}")
    return (201 if action == "created" else 200), {"tool": composites.out(row, with_usage=True), "action": action}


@router.get("/composite-tools/{tool_id}")
def get_tool(request: HttpRequest, tool_id: int):
    principal(request)
    return composites.out(composites.get_tool(tool_id), graph=True, with_usage=True)


@router.put("/composite-tools/{tool_id}")
def update_tool(request: HttpRequest, tool_id: int, payload: Body[dict]):
    p = require_feature(request, "tools.edit")
    row = composites.update(composites.get_tool(tool_id), payload, user=p.user)
    audit.record(request, "tool.update", row, summary=f"{row.key} v{row.version}")
    return composites.out(row, graph=True, with_usage=True)


@router.delete("/composite-tools/{tool_id}", response={204: None})
def delete_tool(request: HttpRequest, tool_id: int):
    require_feature(request, "tools.edit")
    row = composites.get_tool(tool_id)
    audit.record(request, "tool.delete", row, summary=row.key)
    composites.delete(row)
    return 204, None


@router.get("/composite-tools/{tool_id}/versions")
def tool_versions(request: HttpRequest, tool_id: int):
    """每一版的清單（最新在前）；實例的 `meta.tool_version` 對照這裡。"""
    principal(request)
    row = composites.get_tool(tool_id)
    return {"version": int(row.version or 1), "items": composites.versions_of(row)}


@router.get("/composite-tools/{tool_id}/versions/{version}")
def tool_version(request: HttpRequest, tool_id: int, version: int):
    principal(request)
    row = composites.get_tool(tool_id)
    snap = composites.snapshot_of(row, version)
    return {"version": snap.version, "label": snap.label, "description": snap.description, "graph": snap.graph, "interface": snap.interface,
            "saved_at": snap.saved_at.isoformat() if snap.saved_at else "", "saved_by": snap.saved_by.username if snap.saved_by_id else ""}


@router.get("/composite-tools/{tool_id}/diff")
def tool_diff(request: HttpRequest, tool_id: int, from_version: int, to_version: int | None = None):
    """兩版之間變了什麼（省略 to_version＝目前最新版）：參數逐條、結構數量、介面多／少的埠與參數。"""
    principal(request)
    return composites.diff_versions(composites.get_tool(tool_id), from_version, to_version)


@router.get("/composite-tools/{tool_id}/usage")
def tool_usage(request: HttpRequest, tool_id: int):
    principal(request)
    return composites.usage(composites.get_tool(tool_id).key)


@router.get("/composite-tools/{tool_id}/export")
def export_tool(request: HttpRequest, tool_id: int, download: bool = True):
    principal(request)
    row = composites.get_tool(tool_id)
    response = HttpResponse(serialize.to_bytes(composites.export_doc(row)), content_type="application/json; charset=utf-8")
    if download:
        response["Content-Disposition"] = f'attachment; filename="{row.key}.tool.json"'
    return response


@router.post("/composite-tools/{tool_id}/duplicate", response={201: dict})
def duplicate_tool(request: HttpRequest, tool_id: int, payload: Body[dict]):
    p = require_feature(request, "tools.edit")
    row = composites.get_tool(tool_id)
    made = composites.duplicate(row, p.user, payload or {})
    audit.record(request, "tool.create", made, summary=f"{made.key} (copy of {row.key})")
    return 201, composites.out(made, graph=True, with_usage=True)
