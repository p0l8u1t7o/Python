"""流程匯出／匯入 API（格式見 apps/vision/serialize.py 與 docs/golden.html）。

GET  /vision/flows/{id}/export      下載 .flow.json（Content-Disposition attachment）
POST /vision/flows/import           JSON body {doc?, ...doc, source_id?} 或 multipart file（＋form source_id）→ {flow, created}
"""

from __future__ import annotations

import json
import re
from typing import Any

from django.http import HttpRequest, HttpResponse
from ninja import Router

from apps.accounts.security import principal, require_engineer
from apps.core.errors import NotFound, ValidationError
from apps.vision import serialize
from apps.vision import scripts
from apps.vision.api import _flow_out, _visible_flows
from apps.vision.models import ImageSource
from apps.vision.runner import get_flow

router = Router(tags=["flow-io"])


def _safe_filename(name: str) -> str:
    stem = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_") or "flow"
    return f"{stem}.flow.json"


@router.get("/flows/{flow_id}/export")
def export_flow(request: HttpRequest, flow_id: int, download: bool = True):
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"Flow {flow_id} not found", code="flow_not_found")
    data = serialize.to_bytes(serialize.export_flow(flow))
    response = HttpResponse(data, content_type="application/json; charset=utf-8")
    if download:
        ascii_name = _safe_filename(flow.name).encode("ascii", "ignore").decode() or "flow.flow.json"
        response["Content-Disposition"] = f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{_percent(_safe_filename(flow.name))}'
    return response


def _percent(s: str) -> str:
    from urllib.parse import quote

    return quote(s, safe="")


@router.post("/flows/import", response={200: dict, 201: dict})
def import_flow(request: HttpRequest):
    """JSON：整份流程檔當 body（可加 source_id 欄位），或 {"doc": {...}, "source_id": 3}。
    multipart：file 欄位 ＋ 可選 form 欄位 source_id。"""
    require_engineer(request)
    p = principal(request)
    source_id: int | None = None
    doc: dict[str, Any]
    upload = request.FILES.get("file")
    if upload is not None:
        doc = serialize.parse(upload.read())
        raw_sid = request.POST.get("source_id")
        source_id = int(raw_sid) if raw_sid not in (None, "") else None
    else:
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            raise ValidationError("Malformed JSON", code="bad_json") from None
        if not isinstance(body, dict):
            raise ValidationError("The body must be an object", code="bad_json")
        if isinstance(body.get("doc"), dict):
            doc = serialize.parse(json.dumps(body["doc"]))
            sid = body.get("source_id")
        else:
            sid = body.pop("source_id", None)
            doc = serialize.parse(json.dumps(body))
        source_id = int(sid) if sid not in (None, "") else None
    if source_id is not None and not ImageSource.objects.filter(pk=source_id).exists():
        raise NotFound("Image source not found", code="source_not_found")
    existing = serialize.find_flow(doc["name"])
    if existing is not None and not p.can_edit_flow(existing):
        raise NotFound("The flow does not exist or cannot be updated", code="flow_not_found")
    scripts.check_graph_edit(p, doc.get("graph"), flow=existing)  # Python 腳本：一般使用者只能匯入已核准的程式碼
    flow, created = serialize.import_flow(doc, source_id=source_id, owner=p.user)
    return (201 if created else 200), {"flow": _flow_out(flow), "created": created}
