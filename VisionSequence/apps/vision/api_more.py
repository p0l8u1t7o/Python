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
from django.db.models import Q
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from ninja import File, Router, Schema, UploadedFile

from apps.accounts.security import authenticate, principal, require_admin, require_feature
from apps.core import audit
from apps.core import plugins as folder_plugins
from apps.core.models import AuditLog
from apps.core.errors import Conflict, NotFound, PermissionDenied, ValidationError
from apps.vision import __version__, demo, retention, summary, trace
from apps.vision.api import _decode_upload, _visible_flows
from apps.vision.graph import validate_graph
from apps.vision.images import store as image_store
from apps.vision.models import FlowTemplate, ImageSource
from apps.vision.runner import get_flow, runner
from apps.vision.tools.builtin import edge_defect

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
    use_samples: bool = True  # 沒選來源時，內建範本用自己的樣本圖（fixed_image）
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
            "node_count": len(graph["nodes"]), "graph": graph, "owner_name": "", "created_at": None, "has_samples": key in demo.TEMPLATE_SAMPLE_SETS,
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


def instantiate(graph: dict[str, Any], *, source_id: int | None, prefix: str = "", samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """把 {SOURCE} 換成來源 id；沒有來源但有樣本圖（samples＝固定影像描述子）時，取像節點改成 fixed_image 帶著那些圖（範本畫廊的預設）。"""
    out = json.loads(json.dumps(graph))
    rename = {n["id"]: f"{prefix}{n['id']}" for n in out.get("nodes", [])} if prefix else {}
    for node in out.get("nodes", []):
        if rename:
            node["id"] = rename[node["id"]]
        params = node.get("params") or {}
        if node.get("type") == "image_source" and params.get("source_id") == SOURCE_PLACEHOLDER:
            if source_id is None and samples:
                node["type"] = "fixed_image"
                node["label"] = node.get("label") or "Sample pictures"
                node["params"] = {"images": json.loads(json.dumps(samples)), "mode": "cycle", "index": 1, "convert": params.get("convert", "keep")}
            else:
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
    require_feature(request, "flows.edit")
    p = principal(request)
    graph = templatize(validate_graph(payload.graph))
    try:
        with transaction.atomic():
            t = FlowTemplate.objects.create(name=payload.name.strip(), description=payload.description, category=payload.category or "custom", graph=graph, owner=p.user)
    except IntegrityError:
        raise Conflict("A template with that name already exists", code="template_name_taken") from None
    return 201, _template_out(t)


def _find_template(template_id: str) -> dict[str, Any]:
    if template_id.startswith("builtin:"):
        for t in _builtin_templates():
            if t["id"] == template_id:
                return t
        raise NotFound("Template not found", code="template_not_found")
    row = FlowTemplate.objects.filter(pk=template_id).first()
    if row is None:
        raise NotFound("Template not found", code="template_not_found")
    return {**_template_out(row), "_row": row}


@router.delete("/templates/{template_id}", response={204: None})
def delete_template(request: HttpRequest, template_id: str):
    require_feature(request, "flows.edit")
    p = principal(request)
    t = _find_template(template_id)
    if t["source"] == "builtin":
        raise ValidationError("Built-in templates cannot be deleted", code="builtin_template")
    row = t["_row"]
    if not (p.is_admin or (p.user and row.owner_id == p.user.id)):
        raise PermissionDenied("That template is not yours", code="not_owner")
    row.delete()
    return 204, None


@router.post("/templates/{template_id}/instantiate")
def instantiate_template(request: HttpRequest, template_id: str, payload: InstantiateIn):
    require_feature(request, "flows.edit")
    t = _find_template(template_id)
    source_id = payload.source_id
    if source_id is not None and not ImageSource.objects.filter(pk=source_id).exists():
        raise NotFound("Image source not found", code="source_not_found")
    samples = None
    if source_id is None and payload.use_samples and str(t["id"]).startswith("builtin:"):
        samples = demo.template_samples(str(t["id"]).split(":", 1)[1]) or None
    graph = instantiate(t["graph"], source_id=source_id, prefix=payload.prefix, samples=samples)
    missing = source_id is None and any(n.get("type") == "image_source" for n in graph["nodes"])
    return {"graph": validate_graph(graph), "missing_source": missing, "used_samples": bool(samples), "name": t["name"], "description": t["description"]}


# ---------------------------------------------------------------------------
# 批次測試
# ---------------------------------------------------------------------------
def _batch_run(request: HttpRequest, flow_id: int, images: list[tuple[str, Any]], graph: dict | None) -> dict[str, Any]:
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"Flow {flow_id} not found", code="flow_not_found")
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
    require_feature(request, "batch")
    if len(images) > MAX_BATCH:
        raise ValidationError(f"{MAX_BATCH} images at a time is the limit", code="too_many_images")
    graph = None
    raw = request.POST.get("graph")
    if raw:
        try:
            graph = json.loads(raw)
        except json.JSONDecodeError:
            raise ValidationError("graph is not valid JSON", code="bad_graph") from None
    decoded = []
    for up in images:
        try:
            decoded.append((up.name or "image", _decode_upload(up)))
        except ValidationError:
            decoded.append((up.name or "image", None))
    bad = [n for n, im in decoded if im is None]
    if bad:
        raise ValidationError(f"Could not decode: {', '.join(bad[:5])}", code="bad_image")
    return _batch_run(request, flow_id, decoded, graph)


class BatchSourceIn(Schema):
    source_id: int
    count: int = 10
    graph: dict[str, Any] | None = None


class TeachContourIn(Schema):
    ref: str
    roi: dict[str, Any] | None = None
    simplify: float = 2.0


@router.post("/flows/{flow_id}/batch-source")
def batch_from_source(request: HttpRequest, flow_id: int, payload: BatchSourceIn):
    require_feature(request, "batch")
    from apps.vision.sources import grab_by_id

    n = max(1, min(MAX_BATCH, int(payload.count)))
    images = []
    for i in range(n):
        frame = grab_by_id(payload.source_id)
        if frame is None:
            break
        images.append((f"frame-{i + 1}", frame))
    if not images:
        raise ValidationError("The source returned no image", code="no_frame")
    return _batch_run(request, flow_id, images, payload.graph)


@router.post("/flows/{flow_id}/teach-contour")
def teach_contour_from_ref(request: HttpRequest, flow_id: int, payload: TeachContourIn):
    require_feature(request, "flows.edit")
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"Flow {flow_id} not found", code="flow_not_found")
    image = image_store.get(payload.ref)
    if image is None:
        raise NotFound("The picture is no longer in the cache", code="no_such_image")
    try:
        model, points = edge_defect.teach_contour_model(image, roi=payload.roi, simplify=payload.simplify)
    except Exception as exc:
        raise ValidationError("The teaching region is not valid", code="bad_region") from exc
    if model is None:
        raise ValidationError("No closed contour could be taught from the picture", code="no_contour")
    return {"model": model, "points": points}


# ---------------------------------------------------------------------------
# 資料夾外掛（apps/core/plugins.py）
# ---------------------------------------------------------------------------
def _plugins_out() -> dict[str, Any]:
    return {
        "dir": str(folder_plugins.plugin_dir()),
        "items": folder_plugins.inventory(),
        "docs_url": "/docs/plugins.html",
    }


@router.get("/plugins")
def list_plugins(request: HttpRequest):
    """外掛頁：plugins/ 底下每個檔案的載入結果（掛了什麼、停用、錯在哪）。"""
    require_feature(request, "integration")
    return _plugins_out()


@router.post("/plugins/rescan")
def rescan_plugins(request: HttpRequest):
    """掛載新放進來的外掛、重試上次失敗的；已載入的檔案改了仍要重啟。"""
    require_admin(request)
    mounted = folder_plugins.rescan()
    audit.record(request, "plugin.rescan", summary=", ".join(mounted) or "nothing new", target_type="plugins")
    return {**_plugins_out(), "mounted": mounted}


# ---------------------------------------------------------------------------
# 這一站的摘要（apps/vision/summary.py）
# ---------------------------------------------------------------------------
@router.get("/summary")
def station_summary(request: HttpRequest, hours: int = 24):
    """這一站的良率摘要：總覽頁用它，外部系統也可以輪詢它做跨站彙總。"""
    principal(request)
    return summary.of_this_station(hours)


# ---------------------------------------------------------------------------
# 稽核軌跡（apps/core/audit.py）
# ---------------------------------------------------------------------------
def _time_range(since: str, until: str):
    """時間區段：日期（YYYY-MM-DD，本地時區；until 含當天）或 ISO 時間；解析不了回 422。"""
    import datetime as dt

    from django.utils import dateparse, timezone

    def parse(raw: str, end: bool):
        raw = (raw or "").strip()
        if not raw:
            return None
        d = dateparse.parse_date(raw)
        if d is not None:
            base = timezone.make_aware(dt.datetime.combine(d, dt.time.min), timezone.get_current_timezone())
            return base + dt.timedelta(days=1) if end else base
        t = dateparse.parse_datetime(raw)
        if t is None:
            raise ValidationError(f"Cannot parse the time '{raw}' (use YYYY-MM-DD or an ISO time)", code="bad_time")
        return timezone.make_aware(t, timezone.get_current_timezone()) if timezone.is_naive(t) else t

    return parse(since, False), parse(until, True)


@router.get("/retention")
def retention_status(request: HttpRequest):
    """Retention settings, what the last clean-up removed, and how much space each store is using."""
    require_admin(request)
    return retention.status()


@router.patch("/retention")
def retention_patch(request: HttpRequest):
    """Change how long data is kept (days; 0 = keep for ever) and when the maintenance window runs."""
    require_admin(request)
    body = json.loads(request.body or b"{}")
    if not isinstance(body, dict):
        raise ValidationError("A JSON object is required", code="bad_body")
    unknown = sorted(set(body) - set(retention.FIELDS))
    if unknown:
        raise ValidationError(f"Unknown setting: {', '.join(unknown)}", code="bad_field", details={"fields": unknown})
    try:
        saved = retention.save(body)
    except (TypeError, ValueError):
        raise ValidationError("Days must be whole numbers and the size a number", code="bad_value") from None
    audit.record(request, "retention.update", target_type="settings", target_name="retention",
                 summary=f"run {saved['run_days']}d, audit {saved['audit_days']}d, measurements {saved['measurement_days']}d", detail=saved)
    return retention.status()


@router.post("/retention/sweep")
def retention_sweep(request: HttpRequest):
    """Clean up now (the same work the maintenance window does), instead of waiting for it."""
    require_admin(request)
    deep = bool(json.loads(request.body or b"{}").get("deep", True)) if request.body else True
    result = retention.sweep(deep=deep, force=True)
    audit.record(request, "retention.sweep", target_type="settings", target_name="retention",
                 summary=f"removed {result['runs']} runs, {result['audit']} audit rows, {result['archive_files']} pictures", detail=result)
    return {"result": result, "status": retention.status()}


@router.get("/audit")
def audit_log(request: HttpRequest, action: str = "", target_type: str = "", target_id: str = "",
              actor: str = "", q: str = "", since: str = "", until: str = "", limit: int = 50, offset: int = 0):
    """Who changed what, newest first. Administrators only — it records people, not machines."""
    require_feature(request, "audit")
    qs = AuditLog.objects.all()
    if action:
        qs = qs.filter(action__startswith=action)
    if target_type:
        qs = qs.filter(target_type=target_type)
    if target_id:
        qs = qs.filter(target_id=str(target_id))
    if actor:
        qs = qs.filter(actor_name=actor)
    if q:
        qs = qs.filter(Q(summary__icontains=q) | Q(target_name__icontains=q))
    lo, hi = _time_range(since, until)
    if lo is not None:
        qs = qs.filter(at__gte=lo)
    if hi is not None:
        qs = qs.filter(at__lt=hi)
    total = qs.count()
    limit = max(1, min(500, int(limit)))
    rows = list(qs.select_related("actor")[offset : offset + limit])
    return {
        "items": [audit.out(r) for r in rows], "total": total, "limit": limit, "offset": offset,
        # 模型預設依 at 排序，values_list().distinct() 會把 at 帶進 DISTINCT 而重複（前端下拉出現重複的 key）——用 set 去重
        "actions": sorted(set(AuditLog.objects.values_list("action", flat=True))),
        "actors": sorted({a for a in AuditLog.objects.values_list("actor_name", flat=True) if a}),
    }


@router.get("/audit.csv", auth=None)
def audit_csv(request: HttpRequest, action: str = "", target_type: str = "", actor: str = ""):
    """Same rows as CSV so quality can keep them outside the machine (UTF-8 BOM for Excel)."""
    # auth=None 的端點 ninja 不會設 request.auth，所以身分要用 authenticate() 的回傳值，
    # 不能再呼叫 principal(request)（它讀 request.auth，會自己拋 401）。
    who = authenticate(request)
    if who is None:
        return HttpResponse(status=401)
    if not who.is_admin:
        raise PermissionDenied("Administrator role required", code="permission_denied")
    qs = AuditLog.objects.all()
    if action:
        qs = qs.filter(action__startswith=action)
    if target_type:
        qs = qs.filter(target_type=target_type)
    if actor:
        qs = qs.filter(actor_name=actor)

    def rows():
        yield "\ufeff" + ",".join(("at", "actor", "actor_kind", "action", "target_type", "target_id", "target_name", "summary", "ip")) + "\r\n"
        for r in qs.iterator(chunk_size=500):
            cells = [r.at.isoformat(), r.actor_name, r.actor_kind, r.action, r.target_type, r.target_id, r.target_name, r.summary, r.ip or ""]
            yield ",".join('"' + str(c).replace('"', '""') + '"' for c in cells) + "\r\n"

    response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="audit.csv"'
    return response


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
        "version": __version__,
        "station_id": cfg.get("STATION_ID", ""),
        "api_key_required": bool(cfg.get("API_KEY")),
        "max_workers": cfg["MAX_WORKERS"],
        "max_queue_per_flow": runner.max_queue_per_flow,
        "run_timeout_s": cfg["RUN_TIMEOUT_S"],
        "commands": ["PING", "LIST", "RUN <flow> [k=v ...]", "TRIGGER <flow> [k=v ...]", "STATUS [flow]", "START <flow>", "STOP <flow>", "LOCK [reason=\"...\" ttl=600]", "UNLOCK"],
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
    require_feature(request, "integration").can_execute()
    command = payload.command.strip()
    if not command:
        raise ValidationError("The command is empty", code="empty_command")
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
