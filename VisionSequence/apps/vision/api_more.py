"""流程範本庫、批次測試、整合測試工具的 API。

GET    /vision/templates                  內建（builtin:<key>）＋自訂範本
POST   /vision/templates                  存為範本 {name, description, category, graph}
DELETE /vision/templates/{id}             自訂範本（擁有者或管理員）
POST   /vision/templates/{id}/instantiate {source_id?} → {graph}：把 {SOURCE} 佔位符換成來源 id、節點 id 重新命名
POST   /vision/flows/{id}/batch           批次測試：multipart images[]（≤50 張）→ 每張的判定／輸出／耗時／影像 ref
POST   /vision/flows/{id}/batch-source    批次測試：從來源抓 n 張
GET    /vision/integration/info           主機、埠、金鑰是否設定、範例指令
POST   /vision/integration/tcp            {"command": "RUN 1"} → 透過真實 TCP socket 送到本機 TCP 介面（沒開則直接呼叫 handle_command）
"""

from __future__ import annotations

import json
import socket
import time
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import File, Router, Schema, UploadedFile

from apps.accounts.security import principal
from apps.core.errors import Conflict, NotFound, PermissionDenied, ValidationError
from apps.vision import demo, trace
from apps.vision.api import _decode_upload, _visible_flows
from apps.vision.graph import validate_graph
from apps.vision.models import FlowTemplate, ImageSource
from apps.vision.runner import get_flow, runner

router = Router(tags=["more"])

SOURCE_PLACEHOLDER = "{SOURCE}"
MAX_BATCH = 50


# ---------------------------------------------------------------------------
# 範本
# ---------------------------------------------------------------------------
class TemplateIn(Schema):
    name: str
    description: str = ""
    category: str = "custom"
    graph: dict[str, Any]


class InstantiateIn(Schema):
    source_id: int | None = None
    #: 節點 id 前綴，避免載進已有內容的畫布時撞名。
    prefix: str = ""


_BUILTIN_CACHE: dict[str, Any] = {"at": 0.0, "items": []}
_BUILTIN_TTL_S = 30.0


def _builtin_templates() -> list[dict[str, Any]]:
    """內建範本目錄。builder 要跑 14 次＋查範例資產，每次開畫廊都重算太浪費：快取 30 秒
    （範例資產只在 seed 時建立，短 TTL 足以在 seed 後自動更新）。"""
    now = time.monotonic()
    if _BUILTIN_CACHE["items"] and now - _BUILTIN_CACHE["at"] < _BUILTIN_TTL_S:
        return _BUILTIN_CACHE["items"]
    items = []
    for key, name, desc, category, builder in demo.BUILTIN_TEMPLATES:
        graph = builder(SOURCE_PLACEHOLDER)
        items.append({
            "id": f"builtin:{key}", "name": name, "description": desc, "category": category, "source": "builtin",
            "node_count": len(graph["nodes"]), "graph": graph, "owner_name": "", "created_at": None,
        })
    _BUILTIN_CACHE.update(at=now, items=items)
    return items


def _template_out(t: FlowTemplate) -> dict[str, Any]:
    return {
        "id": str(t.id), "name": t.name, "description": t.description, "category": t.category, "source": "custom",
        "node_count": len((t.graph or {}).get("nodes") or []), "graph": t.graph,
        "owner_name": t.owner.username if t.owner_id else "", "created_at": t.created_at.isoformat(),
    }


def templatize(graph: dict[str, Any]) -> dict[str, Any]:
    """把 image_source 的 source_id 換成佔位符：範本不能綁死某台機器的來源 id。"""
    out = json.loads(json.dumps(graph))
    for node in out.get("nodes", []):
        if node.get("type") == "image_source":
            params = node.setdefault("params", {})
            if params.get("source_id"):
                params["source_id"] = SOURCE_PLACEHOLDER
    return out


def instantiate(graph: dict[str, Any], *, source_id: int | None, prefix: str = "") -> dict[str, Any]:
    out = json.loads(json.dumps(graph))
    rename = {n["id"]: f"{prefix}{n['id']}" for n in out.get("nodes", [])} if prefix else {}
    for node in out.get("nodes", []):
        if rename:
            node["id"] = rename[node["id"]]
        params = node.get("params") or {}
        if node.get("type") == "image_source" and params.get("source_id") == SOURCE_PLACEHOLDER:
            params["source_id"] = source_id if source_id is not None else ""
    for edge in out.get("edges", []):
        if rename:
            edge["source"] = rename.get(edge["source"], edge["source"])
            edge["target"] = rename.get(edge["target"], edge["target"])
            edge["id"] = f"{prefix}{edge.get('id') or ''}"
    return out


@router.get("/templates")
def list_templates(request: HttpRequest):
    p = principal(request)
    qs = FlowTemplate.objects.select_related("owner")
    custom = [_template_out(t) for t in qs]
    return {"items": _builtin_templates() + custom, "can_manage": p.is_admin}


@router.post("/templates", response={201: dict})
def create_template(request: HttpRequest, payload: TemplateIn):
    p = principal(request)
    graph = templatize(validate_graph(payload.graph))
    try:
        with transaction.atomic():
            t = FlowTemplate.objects.create(name=payload.name.strip(), description=payload.description, category=payload.category or "custom", graph=graph, owner=p.user)
    except IntegrityError:
        raise Conflict("已有同名範本", code="template_name_taken") from None
    return 201, _template_out(t)


def _find_template(template_id: str) -> dict[str, Any]:
    if template_id.startswith("builtin:"):
        for t in _builtin_templates():
            if t["id"] == template_id:
                return t
        raise NotFound("範本不存在", code="template_not_found")
    row = FlowTemplate.objects.filter(pk=template_id).first()
    if row is None:
        raise NotFound("範本不存在", code="template_not_found")
    return {**_template_out(row), "_row": row}


@router.delete("/templates/{template_id}", response={204: None})
def delete_template(request: HttpRequest, template_id: str):
    p = principal(request)
    t = _find_template(template_id)
    if t["source"] == "builtin":
        raise ValidationError("內建範本不能刪除", code="builtin_template")
    row = t["_row"]
    if not (p.is_admin or (p.user and row.owner_id == p.user.id)):
        raise PermissionDenied("這不是你的範本", code="not_owner")
    row.delete()
    return 204, None


@router.post("/templates/{template_id}/instantiate")
def instantiate_template(request: HttpRequest, template_id: str, payload: InstantiateIn):
    t = _find_template(template_id)
    source_id = payload.source_id
    if source_id is not None and not ImageSource.objects.filter(pk=source_id).exists():
        raise NotFound("影像來源不存在", code="source_not_found")
    graph = instantiate(t["graph"], source_id=source_id, prefix=payload.prefix)
    missing = source_id is None and any(n.get("type") == "image_source" for n in graph["nodes"])
    return {"graph": validate_graph(graph), "missing_source": missing, "name": t["name"], "description": t["description"]}


# ---------------------------------------------------------------------------
# 批次測試
# ---------------------------------------------------------------------------
def _batch_run(request: HttpRequest, flow_id: int, images: list[tuple[str, Any]], graph: dict | None) -> dict[str, Any]:
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"流程 {flow_id} 不存在", code="flow_not_found")
    principal(request).can_execute()
    rows = []
    t0 = time.perf_counter()
    for name, image in images:
        report = runner.run_sync(flow, trigger="preview", preview=True, graph_override=graph, input_image=image)
        src_ref = None
        for nid, nr in report.nodes.items():
            if report.nodes[nid] and nr.outputs:
                for v in nr.outputs.values():
                    if isinstance(v, dict) and v.get("ref") and ":image" in v["ref"]:
                        src_ref = v["ref"]
                        break
            if src_ref:
                break
        error_node = next((nid for nid, nr in report.nodes.items() if nr.status == "error"), None)
        rows.append({
            "name": name, "run_id": report.id, "status": report.status, "duration_ms": round(report.duration_ms, 2),
            "outputs": report.outputs, "error": report.error, "error_node": error_node, "image_ref": src_ref,
            "width": int(image.shape[1]), "height": int(image.shape[0]),
        })
    summary = {
        "total": len(rows),
        "ok": sum(r["status"] == "ok" for r in rows),
        "ng": sum(r["status"] == "ng" for r in rows),
        "failed": sum(r["status"] not in ("ok", "ng") for r in rows),
        "avg_ms": round(sum(r["duration_ms"] for r in rows) / len(rows), 2) if rows else 0,
        "max_ms": max((r["duration_ms"] for r in rows), default=0),
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    return {"items": rows, "summary": summary}


@router.post("/flows/{flow_id}/batch")
def batch_upload(request: HttpRequest, flow_id: int, images: list[UploadedFile] = File(...)):
    """批次測試：一次上傳多張影像（≤50），每張以試跑模式執行（影像留在快取供檢視）。
    可附 form 欄位 graph（JSON 字串）用未儲存的圖。"""
    if len(images) > MAX_BATCH:
        raise ValidationError(f"一次最多 {MAX_BATCH} 張", code="too_many_images")
    graph = None
    raw = request.POST.get("graph")
    if raw:
        try:
            graph = json.loads(raw)
        except json.JSONDecodeError:
            raise ValidationError("graph 不是合法 JSON", code="bad_graph") from None
    decoded = []
    for up in images:
        try:
            decoded.append((up.name or "image", _decode_upload(up)))
        except ValidationError:
            decoded.append((up.name or "image", None))
    bad = [n for n, im in decoded if im is None]
    if bad:
        raise ValidationError(f"無法解碼：{', '.join(bad[:5])}", code="bad_image")
    return _batch_run(request, flow_id, decoded, graph)


class BatchSourceIn(Schema):
    source_id: int
    count: int = 10
    graph: dict[str, Any] | None = None


@router.post("/flows/{flow_id}/batch-source")
def batch_from_source(request: HttpRequest, flow_id: int, payload: BatchSourceIn):
    from apps.vision.sources import grab_by_id

    n = max(1, min(MAX_BATCH, int(payload.count)))
    images = []
    for i in range(n):
        frame = grab_by_id(payload.source_id)
        if frame is None:
            break
        images.append((f"frame-{i + 1}", frame))
    if not images:
        raise ValidationError("來源沒有回傳影像", code="no_frame")
    return _batch_run(request, flow_id, images, payload.graph)


# ---------------------------------------------------------------------------
# 整合測試工具
# ---------------------------------------------------------------------------
@router.get("/integration/info")
def integration_info(request: HttpRequest):
    cfg = settings.VISION
    host = request.get_host().split(":")[0]
    port = request.get_port()
    return {
        "http_base": f"{request.scheme}://{request.get_host()}/api",
        "host": host,
        "http_port": int(port) if str(port).isdigit() else port,
        "tcp_host": cfg["TCP_HOST"],
        # 綁定位址是 0.0.0.0 時，那不是 PLC 該填的東西——給一個真的連得到的位址。
        "tcp_connect_host": _reachable_host(cfg["TCP_HOST"], host),
        "tcp_port": cfg["TCP_PORT"],
        "tcp_listening": _tcp_listening(cfg["TCP_PORT"]),
        "capture_host": cfg["CAPTURE_HOST"],
        "capture_connect_host": _reachable_host(cfg["CAPTURE_HOST"], host),
        "capture_port": cfg["CAPTURE_PORT"],
        "capture_listening": _tcp_listening(cfg["CAPTURE_PORT"]),
        "capture_download_url": "/api/vision/capture/download",
        "events_url": "/api/vision/events",
        "flow_events_url": "/api/vision/flows/{flow_id}/stream",
        "api_key_required": bool(cfg.get("API_KEY")),
        "max_workers": cfg["MAX_WORKERS"],
        "max_queue_per_flow": runner.max_queue_per_flow,
        "run_timeout_s": cfg["RUN_TIMEOUT_S"],
        "commands": ["PING", "LIST", "RUN <flow> [k=v ...]", "TRIGGER <flow> [k=v ...]", "STATUS [flow]", "START <flow>", "STOP <flow>"],
    }


def _reachable_host(bind: str, request_host: str) -> str:
    """把綁定位址換成「外部真的連得到」的位址。

    `0.0.0.0`／`::` 是「所有介面」，填給 PLC 是連不上的。優先用這次請求的主機名／IP
    （管理員就是從那個位址進來的，同一張網路卡最可能通），拿不到才退回本機 IP。
    """
    if str(bind) not in ("0.0.0.0", "::", ""):
        return str(bind)
    if request_host and request_host not in ("0.0.0.0", "::"):
        return request_host
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def _tcp_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.2):
            return True
    except OSError:
        return False


class TcpIn(Schema):
    command: str
    timeout_s: float = 10.0


@router.get("/integration/trace")
def integration_trace(request: HttpRequest, channel: str = "", since: int = 0, limit: int = 200):
    """整合追蹤：各整合介面的「命令與結果」（除錯用）。查詢本身會讓後端開始記錄兩分鐘。"""
    items = trace.entries(channel or None, since=since, limit=limit)
    return {"items": items, "seq": items[-1]["seq"] if items else int(since or 0), "channels": list(trace.CHANNELS), **trace.stats()}


@router.delete("/integration/trace")
def integration_trace_clear(request: HttpRequest, channel: str = ""):
    trace.clear(channel or None)
    return {"ok": True}


@router.post("/integration/tcp")
def integration_tcp(request: HttpRequest, payload: TcpIn):
    """從前端測 TCP 介面：真的連本機 TCP 埠送一行指令；埠沒開時直接呼叫指令處理器並註明。"""
    principal(request).can_execute()
    command = payload.command.strip()
    if not command:
        raise ValidationError("指令為空", code="empty_command")
    port = int(settings.VISION["TCP_PORT"])
    t0 = time.perf_counter()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=min(60.0, max(0.5, payload.timeout_s))) as sock:
            sock.sendall((command + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        raw = buf.decode("utf-8", errors="replace").strip()
        try:
            response = json.loads(raw)
        except json.JSONDecodeError:
            response = {"raw": raw}
        via = "tcp"
    except OSError:
        from apps.vision.tcp_server import handle_command

        response = handle_command(command)
        via = "direct"
    return {"command": command, "response": response, "via": via, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2), "tcp_port": port}
