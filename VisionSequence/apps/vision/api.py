"""REST API（django-ninja）。

GET    /vision/tool-types                 工具目錄（前端調色盤 + 參數表單）
GET    /vision/capacity                   執行緒池狀態、忙碌中的流程
GET    /vision/flows                      列表（含統計）
POST   /vision/flows                      建立
GET    /vision/flows/{id}
PATCH  /vision/flows/{id}                 存圖 → version+1
DELETE /vision/flows/{id}
POST   /vision/flows/{id}/run             執行（JSON 或 multipart 附 image）；wait=1 同步回結果
POST   /vision/flows/{id}/preview         編輯器試跑（未存檔的圖）
POST   /vision/flows/{id}/continuous      {"running": true|false}
GET    /vision/flows/{id}/runs            歷史（DB）
GET    /vision/flows/{id}/recent          記憶體內最近 run（含節點輸出、overlay、影像 ref）
GET    /vision/runs/{run_id}              單次 run 詳情（先查記憶體，再查 DB）
GET    /vision/images/{ref}               影像（?max=1024&fmt=jpeg&q=85）
GET/POST/PATCH/DELETE /vision/sources     影像來源
GET    /vision/sources/{id}/preview       抓一張回 JPEG
POST   /vision/sources/{id}/push          upload 型來源送圖（multipart image）
GET    /vision/sources/kinds
GET/POST/DELETE /vision/assets            資產（範本影像、模型）
GET    /vision/assets/{id}/file
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Any

import cv2
import numpy as np
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from ninja import File, Form, Router, Schema, UploadedFile

from apps.accounts.security import authenticate, principal
from apps.core.errors import Conflict, NotFound, PermissionDenied, ValidationError
from apps.vision import schemas, scripts, trace
from apps.vision.graph import validate_graph
from apps.vision.images import encode_image, store
from apps.vision.models import Asset, Flow, FlowRecipe, FlowRun, ImageSource, ResourceGroup
from apps.vision.runner import get_flow, runner
from apps.vision.sources import close_source, grab_by_id, kinds as source_kinds, open_source, source_info, try_grab
from apps.vision.tools import base as tools

router = Router(tags=["vision"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _flow_out(flow: Flow) -> dict[str, Any]:
    rt = runner.runtime(flow.id)
    return {
        "id": flow.id,
        "name": flow.name,
        "description": flow.description,
        "graph": flow.graph or {"nodes": [], "edges": []},
        "owner_id": flow.owner_id,
        "owner_name": flow.owner.username if flow.owner_id else "",
        "is_enabled": flow.is_enabled,
        "version": flow.version,
        "continuous_interval_ms": flow.continuous_interval_ms,
        "commissioned": flow.commissioned,
        "recipe_count": flow.recipes.count(),
        "node_count": len((flow.graph or {}).get("nodes") or []),
        "created_at": flow.created_at.isoformat(),
        "updated_at": flow.updated_at.isoformat(),
        "stats": rt.stats.to_dict(),
        "continuous": runner.is_continuous(flow.id),
    }


def _source_out(source: ImageSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "kind": source.kind,
        "group": source.group,
        "config": source.config or {},
        "is_enabled": source.is_enabled,
        "status": source_info(source),
        "created_at": source.created_at.isoformat(),
        "updated_at": source.updated_at.isoformat(),
    }


def _asset_out(asset: Asset) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "name": asset.name,
        "kind": asset.kind,
        "group": asset.group,
        "size": asset.size,
        "meta": asset.meta or {},
        "created_at": asset.created_at.isoformat(),
    }


def _decode_upload(upload: UploadedFile | None) -> np.ndarray | None:
    if upload is None:
        return None
    data = np.frombuffer(upload.read(), dtype=np.uint8)
    if data.size == 0:
        raise ValidationError("影像檔是空的", code="bad_image")
    try:
        image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except cv2.error:
        image = None
    if image is None:
        raise ValidationError("無法解碼影像", code="bad_image")
    if image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _run_row_out(run: FlowRun) -> dict[str, Any]:
    return {
        "id": run.id.hex,
        "flow_id": run.flow_id,
        "flow_version": run.flow_version,
        "status": run.status,
        "trigger": run.trigger,
        "station_id": run.station_id,
        "recipe": run.recipe,
        "duration_ms": run.duration_ms,
        "nodes": run.nodes,
        "outputs": run.outputs,
        "error": run.error,
        "started_at": run.started_at.timestamp(),
        "finished_at": run.finished_at.timestamp() if run.finished_at else None,
        "persisted": True,
    }


# ---------------------------------------------------------------------------
# 目錄 / 容量
# ---------------------------------------------------------------------------
@router.get("/tool-types")
def tool_types(request: HttpRequest):
    return {
        "items": tools.catalogue(),
        "categories": [{"key": k, "label": v} for k, v in sorted(tools.CATEGORY_LABELS.items(), key=lambda kv: tools.CATEGORY_ORDER.get(kv[0], 99))],
        "param_kinds": list(tools.PARAM_KINDS),
        "port_types": list(tools.PORT_TYPES),
    }


@router.get("/capacity")
def capacity(request: HttpRequest):
    data = runner.capacity()
    names = {f.id: f.name for f in Flow.objects.filter(id__in=[b["flow_id"] for b in data["flows"]])}
    for b in data["flows"]:
        b["flow_name"] = names.get(b["flow_id"], "")
    return data


# ---------------------------------------------------------------------------
# 流程
# ---------------------------------------------------------------------------
def _editable_flow(request: HttpRequest, flow_id: int) -> Flow:
    flow = get_flow(flow_id)
    if not principal(request).can_edit_flow(flow):
        raise PermissionDenied("這不是你的流程", code="not_owner")
    return flow


def _visible_flows(request: HttpRequest):
    p = principal(request)
    qs = Flow.objects.select_related("owner")
    if p.is_admin:
        return qs
    return qs.filter(Q(owner=p.user) | Q(owner__isnull=True))


@router.get("/flows")
def list_flows(request: HttpRequest, q: str = "", limit: int = 100, offset: int = 0, mine: bool = False):
    qs = _visible_flows(request)
    p = principal(request)
    if mine and p.user:
        qs = qs.filter(owner=p.user)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    total = qs.count()
    return {"items": [_flow_out(f) for f in qs[offset : offset + limit]], "total": total, "limit": limit, "offset": offset}


@router.post("/flows", response={201: dict})
def create_flow(request: HttpRequest, payload: schemas.FlowIn):
    graph = validate_graph(payload.graph) if payload.graph else {"nodes": [], "edges": []}
    scripts.check_graph_edit(principal(request), graph)  # Python 腳本：一般使用者只能用已核准的程式碼
    try:
        with transaction.atomic():
            flow = Flow.objects.create(
                name=payload.name.strip(),
                description=payload.description,
                owner=principal(request).user,
                graph=graph,
                is_enabled=payload.is_enabled,
                continuous_interval_ms=payload.continuous_interval_ms,
            )
    except IntegrityError:
        raise Conflict("已有同名流程", code="flow_name_taken") from None
    return 201, _flow_out(flow)


@router.get("/flows/{flow_id}")
def get_flow_api(request: HttpRequest, flow_id: int):
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"流程 {flow_id} 不存在", code="flow_not_found")
    return _flow_out(flow)


@router.patch("/flows/{flow_id}")
def patch_flow(request: HttpRequest, flow_id: int, payload: schemas.FlowPatch):
    flow = _editable_flow(request, flow_id)
    if payload.name is not None:
        flow.name = payload.name.strip()
    if payload.description is not None:
        flow.description = payload.description
    if payload.is_enabled is not None:
        flow.is_enabled = payload.is_enabled
        if not flow.is_enabled:
            runner.stop_continuous(flow.id)
    if payload.continuous_interval_ms is not None:
        flow.continuous_interval_ms = max(0, payload.continuous_interval_ms)
    if payload.commissioned is not None:
        flow.commissioned = payload.commissioned
    if payload.graph is not None:
        new_graph = validate_graph(payload.graph)
        scripts.check_graph_edit(principal(request), new_graph, flow=flow)  # Python 腳本：一般使用者只能用已核准的程式碼
        flow.graph = new_graph
        flow.version += 1
    try:
        with transaction.atomic():
            flow.save()
    except IntegrityError:
        raise Conflict("已有同名流程", code="flow_name_taken") from None
    return _flow_out(flow)


@router.delete("/flows/{flow_id}", response={204: None})
def delete_flow(request: HttpRequest, flow_id: int):
    flow = _editable_flow(request, flow_id)
    runner.forget(flow.id)
    flow.delete()
    return 204, None


@router.post("/flows/{flow_id}/duplicate", response={201: dict})
def duplicate_flow(request: HttpRequest, flow_id: int):
    flow = get_flow(flow_id)
    name = f"{flow.name} (副本)"
    i = 2
    while Flow.objects.filter(name=name).exists():
        name = f"{flow.name} (副本 {i})"
        i += 1
    copy = Flow.objects.create(name=name, description=flow.description, graph=flow.graph, owner=principal(request).user, is_enabled=False, continuous_interval_ms=flow.continuous_interval_ms)
    return 201, _flow_out(copy)


# ---------------------------------------------------------------------------
# 執行
# ---------------------------------------------------------------------------
def _parse_context(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ValidationError("context 不是合法 JSON", code="bad_context") from None
    if not isinstance(value, dict):
        raise ValidationError("context 必須是物件", code="bad_context")
    return value


@router.post("/flows/{flow_id}/run")
def run_flow(
    request: HttpRequest,
    flow_id: int,
    image: UploadedFile | None = File(None),
    context: str | None = Form(None),
    wait: bool = True,
    timeout_s: float | None = None,
    include_images: bool = False,
    trigger: str = "api",
    recipe: str | None = None,
):
    """執行一次。

    - multipart：`image` 檔案（可選）、`context` JSON 字串（可選）。
    - 或 JSON body：{"context": {...}}。
    - wait=1（預設）等結果回 200；wait=0 立即回 202 + run_id。
    """
    flow = get_flow(flow_id)
    principal(request).can_execute()
    ctx: dict[str, Any] | None = None
    input_image = _decode_upload(image)
    if request.content_type and request.content_type.startswith("application/json") and request.body:
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            raise ValidationError("JSON 格式錯誤", code="bad_json") from None
        ctx = body.get("context") if isinstance(body, dict) else None
        wait = bool(body.get("wait", wait)) if isinstance(body, dict) else wait
        timeout_s = body.get("timeout_s", timeout_s) if isinstance(body, dict) else timeout_s
        include_images = bool(body.get("include_images", include_images)) if isinstance(body, dict) else include_images
        recipe = body.get("recipe", body.get("recipe_id", recipe)) if isinstance(body, dict) else recipe
    else:
        recipe = request.POST.get("recipe") or recipe
        ctx = _parse_context(context)
    trigger = trigger if trigger in ("api", "manual", "tcp") else "api"
    future = runner.submit(flow, trigger=trigger, input_image=input_image, context=scripts.client_context(ctx), recipe=recipe or None)
    if not wait:
        trace.record("http", f"POST /flows/{flow.id}/run（不等結果）", direction="in", name=trigger, detail={"flow": flow.name, "wait": False})
        return HttpResponse(status=202, content=json.dumps({"queued": True, "flow_id": flow.id}), content_type="application/json")
    report = future.result(timeout=(timeout_s or float(settings.VISION["RUN_TIMEOUT_S"])) + 5)
    out = report.to_dict(include_node_outputs=include_images)
    trace.record(  # 整合頁「命令與結果」：外部系統這次要了什麼、拿到什麼
        "http", f"POST /flows/{flow.id}/run → {out.get('status')}", direction="in", name=trigger,
        detail={"flow": flow.name, "recipe": recipe, "judge": out.get("judge"), "outputs": out.get("outputs"), "run_id": out.get("id"), "error": out.get("error")},
        ok=out.get("status") != "failed", ms=out.get("duration_ms"),
    )
    return out


# ---------------------------------------------------------------------------
# 配方（多料號換線）
# ---------------------------------------------------------------------------
def _recipe_out(r: FlowRecipe) -> dict[str, Any]:
    return {"id": r.id, "flow_id": r.flow_id, "name": r.name, "description": r.description, "param_overrides": r.param_overrides or {}, "is_default": r.is_default, "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat()}


@router.get("/flows/{flow_id}/recipes")
def list_recipes(request: HttpRequest, flow_id: int):
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"流程 {flow_id} 不存在", code="flow_not_found")
    return {"items": [_recipe_out(r) for r in flow.recipes.all()]}


@router.post("/flows/{flow_id}/recipes", response={201: dict})
def create_recipe(request: HttpRequest, flow_id: int, payload: schemas.RecipeIn):
    flow = _editable_flow(request, flow_id)
    _validate_overrides(flow, payload.param_overrides)
    try:
        with transaction.atomic():
            if payload.is_default:
                flow.recipes.update(is_default=False)
            r = FlowRecipe.objects.create(flow=flow, name=payload.name.strip(), description=payload.description, param_overrides=payload.param_overrides, is_default=payload.is_default)
    except IntegrityError:
        raise Conflict("已有同名配方", code="recipe_name_taken") from None
    return 201, _recipe_out(r)


@router.patch("/flows/{flow_id}/recipes/{recipe_id}")
def patch_recipe(request: HttpRequest, flow_id: int, recipe_id: int, payload: schemas.RecipePatch):
    flow = _editable_flow(request, flow_id)
    r = flow.recipes.filter(pk=recipe_id).first()
    if r is None:
        raise NotFound("配方不存在", code="recipe_not_found")
    if payload.name is not None:
        r.name = payload.name.strip()
    if payload.description is not None:
        r.description = payload.description
    if payload.param_overrides is not None:
        _validate_overrides(flow, payload.param_overrides)
        r.param_overrides = payload.param_overrides
    if payload.is_default is not None:
        if payload.is_default:
            flow.recipes.exclude(pk=r.pk).update(is_default=False)
        r.is_default = payload.is_default
    try:
        with transaction.atomic():
            r.save()
    except IntegrityError:
        raise Conflict("已有同名配方", code="recipe_name_taken") from None
    return _recipe_out(r)


@router.delete("/flows/{flow_id}/recipes/{recipe_id}", response={204: None})
def delete_recipe(request: HttpRequest, flow_id: int, recipe_id: int):
    flow = _editable_flow(request, flow_id)
    deleted, _ = flow.recipes.filter(pk=recipe_id).delete()
    if not deleted:
        raise NotFound("配方不存在", code="recipe_not_found")
    return 204, None


def _validate_overrides(flow: Flow, overrides: dict[str, Any]) -> None:
    """覆寫只能指向圖裡存在的節點與該工具宣告的參數；疊上去後的圖也要能通過驗證。"""
    if not isinstance(overrides, dict):
        raise ValidationError("param_overrides 必須是物件", code="bad_overrides")
    nodes = {str(n.get("id")): n for n in (flow.graph or {}).get("nodes") or []}
    for node_id, patch in overrides.items():
        node = nodes.get(str(node_id))
        if node is None:
            raise ValidationError(f"節點 '{node_id}' 不在流程裡", code="bad_overrides", details={"node_id": node_id})
        if not isinstance(patch, dict):
            raise ValidationError(f"節點 '{node_id}' 的覆寫必須是物件", code="bad_overrides")
        if node.get("type") in ("note",):
            continue
        declared = {p.key for p in tools.get(str(node["type"])).params}
        if node.get("type") == scripts.SCRIPT_TOOL and "code" in patch:
            raise ValidationError("配方不能覆寫 Python 腳本的程式碼（只有管理員能修改腳本）", code="bad_overrides", details={"node_id": node_id})
        unknown = [k for k in patch if k not in declared]
        if unknown:
            raise ValidationError(f"節點 '{node_id}' 沒有參數 {unknown}", code="bad_overrides", details={"node_id": node_id, "unknown": unknown})
    from apps.vision.runner import apply_recipe

    class _R:
        param_overrides = overrides

    validate_graph(apply_recipe(flow.graph, _R()))


@router.post("/flows/{flow_id}/preview")
def preview_flow(request: HttpRequest, flow_id: int, payload: schemas.PreviewRequest):
    """編輯器試跑：用送來的圖（未存檔），保留所有中間影像供檢視。"""
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"流程 {flow_id} 不存在", code="flow_not_found")
    principal(request).can_execute()
    input_image = None
    if payload.reuse_image_ref:
        input_image = store.get(payload.reuse_image_ref)
        if input_image is None:
            raise NotFound("指定的影像已不在快取中", code="image_gone")
    report = runner.run_sync(
        flow,
        trigger="preview",
        preview=True,
        graph_override=payload.graph,
        input_image=input_image,
        context=scripts.client_context(payload.context, admin=principal(request).is_admin),  # 管理員試執行可跑未核准的腳本
        until_node=payload.until_node,
        recipe=payload.recipe or None,
    )
    data = report.to_dict(include_node_outputs=True)
    if payload.analysis and payload.until_node:
        data["analysis"] = _node_analysis(report, payload.until_node)
    return data


def _histogram(image: np.ndarray | None) -> list[int] | None:
    if image is None:
        return None
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten().astype(int).tolist()


def _node_analysis(report, node_id: str) -> dict[str, Any]:
    """工具專屬頁的參考資訊：輸入／輸出影像直方圖與灰階統計、輸出裡的數值清單分布。"""
    node = report.nodes.get(node_id)
    if node is None:
        return {}
    out: dict[str, Any] = {"node_id": node_id}
    input_ref = (node.detail or {}).get("_input_ref")
    image_in = store.get(input_ref) if input_ref else None
    out["input"] = {"ref": input_ref, "histogram": _histogram(image_in)}
    if image_in is not None:
        g = image_in if image_in.ndim == 2 else cv2.cvtColor(image_in, cv2.COLOR_BGR2GRAY)
        out["input"]["stats"] = {"mean": float(g.mean()), "std": float(g.std()), "min": int(g.min()), "max": int(g.max()), "width": int(g.shape[1]), "height": int(g.shape[0])}
    # 隱含直通埠（_image）排最後：分析要看的是工具「真正的」影像輸出
    for key, value in sorted(node.outputs.items(), key=lambda kv: kv[0].startswith("_")):
        if isinstance(value, dict) and value.get("ref"):
            image_out = store.get(value["ref"])
            if image_out is not None:
                g = image_out if image_out.ndim == 2 else cv2.cvtColor(image_out, cv2.COLOR_BGR2GRAY)
                out["output"] = {"port": key, "ref": value["ref"], "histogram": _histogram(image_out),
                                 "stats": {"mean": float(g.mean()), "std": float(g.std()), "min": int(g.min()), "max": int(g.max()), "width": int(g.shape[1]), "height": int(g.shape[0])}}
                break
    # 數值分布：list[dict] 的數值欄位（例如 blobs 的 area／circularity）
    series: dict[str, list[float]] = {}
    for key, value in node.outputs.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value[:2000]:
                for k, v in item.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        series.setdefault(f"{key}.{k}", []).append(float(v))
    out["series"] = {k: {"count": len(v), "min": min(v), "max": max(v), "mean": sum(v) / len(v), "values": v[:500]} for k, v in series.items()}
    return out


@router.delete("/flows/{flow_id}/recent", response={204: None})
def clear_recent(request: HttpRequest, flow_id: int):
    """重置：清除該流程記憶體內的執行紀錄與統計（資料庫歷史不動）。"""
    _editable_flow(request, flow_id)
    runner.clear_recent(flow_id)
    return 204, None


@router.post("/flows/{flow_id}/scratch-image", response={201: dict})
def upload_scratch_image(request: HttpRequest, flow_id: int, image: UploadedFile = File(...)):
    """暫存影像：只放進影像快取供試跑（reuse_image_ref），不進影像來源庫。"""
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"流程 {flow_id} 不存在", code="flow_not_found")
    frame = _decode_upload(image)
    run_id = f"scratch{uuid.uuid4().hex[:12]}"
    info = store.put(f"{run_id}:upload:image", frame, flow_id=flow.id, run_id=run_id, pinned=True)
    return 201, {**info, "name": image.name}


@router.post("/flows/{flow_id}/continuous")
def set_continuous(request: HttpRequest, flow_id: int):
    flow = _editable_flow(request, flow_id)
    principal(request).can_execute()
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("JSON 格式錯誤", code="bad_json") from None
    running = bool(body.get("running", True))
    if running:
        runner.start_continuous(flow)
    else:
        runner.stop_continuous(flow.id)
    return {"flow_id": flow.id, "running": runner.is_continuous(flow.id)}


@router.get("/flows/{flow_id}/recent")
def recent_runs(request: HttpRequest, flow_id: int, limit: int = 8, include_node_outputs: bool = True):
    get_flow(flow_id)
    rt = runner.runtime(flow_id)
    items = [r.to_dict(include_node_outputs=include_node_outputs) for r in rt.recent[-limit:]][::-1]
    return {"items": items, "stats": rt.stats.to_dict(), "continuous": runner.is_continuous(flow_id)}


@router.get("/flows/{flow_id}/runs")
def run_history(request: HttpRequest, flow_id: int, status: str = "", limit: int = 50, offset: int = 0):
    get_flow(flow_id)
    qs = FlowRun.objects.filter(flow_id=flow_id)
    if status:
        qs = qs.filter(status=status)
    total = qs.count()
    return {"items": [_run_row_out(r) for r in qs[offset : offset + limit]], "total": total, "limit": limit, "offset": offset}


@router.get("/flows/{flow_id}/stats")
def flow_stats(request: HttpRequest, flow_id: int, hours: int = 24):
    """DB 內的統計：各狀態數量、平均耗時、最近 N 小時每小時的 OK/NG。"""
    get_flow(flow_id)
    from django.db.models import Avg, Count, Max
    from django.utils import timezone
    import datetime as dt

    since = timezone.now() - dt.timedelta(hours=hours)
    qs = FlowRun.objects.filter(flow_id=flow_id, started_at__gte=since)
    by_status = {row["status"]: row["n"] for row in qs.values("status").annotate(n=Count("id"))}
    agg = qs.aggregate(avg=Avg("duration_ms"), mx=Max("duration_ms"), n=Count("id"))
    buckets: dict[str, dict[str, int]] = {}
    for started, status_ in qs.values_list("started_at", "status"):
        key = started.astimezone(timezone.get_current_timezone()).strftime("%Y-%m-%d %H:00")
        b = buckets.setdefault(key, {"ok": 0, "ng": 0, "failed": 0})
        b[status_ if status_ in b else "failed"] += 1
    return {
        "hours": hours,
        "total": agg["n"] or 0,
        "by_status": by_status,
        "avg_ms": round(agg["avg"] or 0, 2),
        "max_ms": round(agg["mx"] or 0, 2),
        "hourly": [{"hour": k, **v} for k, v in sorted(buckets.items())],
        "live": runner.runtime(flow_id).stats.to_dict(),
    }


@router.get("/runs/{run_id}")
def get_run(request: HttpRequest, run_id: str):
    for rt in list(runner._runtimes.values()):
        report = rt.report(run_id)
        if report:
            return {**report.to_dict(include_node_outputs=True), "persisted": False}
    try:
        uid = uuid.UUID(run_id)
    except ValueError:
        raise NotFound("run 不存在", code="run_not_found") from None
    row = FlowRun.objects.filter(pk=uid).first()
    if row is None:
        raise NotFound("run 不存在", code="run_not_found")
    return _run_row_out(row)


# ---------------------------------------------------------------------------
# 影像
# ---------------------------------------------------------------------------
@router.get("/images/{path:ref}", auth=None)
def get_image(request: HttpRequest, ref: str, max: int = 0, fmt: str = "jpeg", q: int = 85):
    # 影像會被 <img> 直接載入，帶不了 header；authenticate() 接受 ?token= / ?api_key=。
    if authenticate(request) is None:
        return HttpResponse(status=401)
    max_side = max or None
    data = store.encode(ref, max_side=max_side, fmt="png" if fmt == "png" else "jpeg", quality=q)
    if data is None:
        raise NotFound("影像已不在快取中", code="image_gone")
    response = HttpResponse(data, content_type="image/png" if fmt == "png" else "image/jpeg")
    response["Cache-Control"] = "private, max-age=3600"
    return response


# ---------------------------------------------------------------------------
# 影像來源
# 資源群組（影像來源庫／資產庫共用）
# ---------------------------------------------------------------------------
def _json_body(request: HttpRequest) -> dict:
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("JSON 格式錯誤", code="bad_json") from None
    return body if isinstance(body, dict) else {}


def _group_kind(kind: str) -> str:
    if kind not in ("source", "asset"):
        raise ValidationError("kind 必須是 source 或 asset", code="bad_kind")
    return kind


def _group_items(kind: str):
    return ImageSource.objects if kind == "source" else Asset.objects


def _group_counts(kind: str) -> dict[str, int]:
    from collections import Counter

    return Counter(g for g in _group_items(kind).values_list("group", flat=True) if g)


@router.get("/groups")
def list_groups(request: HttpRequest, kind: str):
    """群組清單（含項目數）。項目上出現但表裡沒有的群組自動補列（舊資料回填）。"""
    kind = _group_kind(kind)
    counts = _group_counts(kind)
    known = set(ResourceGroup.objects.filter(kind=kind).values_list("name", flat=True))
    for name in counts.keys() - known:
        with transaction.atomic():
            ResourceGroup.objects.get_or_create(kind=kind, name=name)
    rows = ResourceGroup.objects.filter(kind=kind)
    return {"items": [{"id": g.id, "name": g.name, "count": counts.get(g.name, 0)} for g in rows]}


@router.post("/groups", response={201: dict})
def create_group(request: HttpRequest):
    body = _json_body(request)
    kind = _group_kind(str(body.get("kind") or ""))
    name = str(body.get("name") or "").strip()[:60]
    if not name:
        raise ValidationError("需要群組名稱", code="bad_name")
    try:
        with transaction.atomic():
            row = ResourceGroup.objects.create(kind=kind, name=name)
    except IntegrityError:
        raise Conflict("已有同名群組", code="group_name_taken") from None
    return 201, {"id": row.id, "name": row.name, "count": _group_counts(kind).get(name, 0)}


@router.patch("/groups/{group_id}")
def rename_group(request: HttpRequest, group_id: int):
    """改名：{"name"}；群組下項目的 group 字串一併更新。"""
    row = ResourceGroup.objects.filter(pk=group_id).first()
    if row is None:
        raise NotFound("群組不存在", code="group_not_found")
    name = str(_json_body(request).get("name") or "").strip()[:60]
    if not name:
        raise ValidationError("需要群組名稱", code="bad_name")
    old_name = row.name
    try:
        with transaction.atomic():
            row.name = name
            row.save(update_fields=["name"])
            _group_items(row.kind).filter(group=old_name).update(group=name)
    except IntegrityError:
        raise Conflict("已有同名群組", code="group_name_taken") from None
    return {"id": row.id, "name": row.name, "count": _group_counts(row.kind).get(name, 0)}


@router.delete("/groups/{group_id}", response={204: None})
def delete_group(request: HttpRequest, group_id: int, delete_items: bool = False):
    """刪群組。delete_items=1 連同群組下的資源一併刪（資產含檔案）；否則所屬資源變為未分組。"""
    row = ResourceGroup.objects.filter(pk=group_id).first()
    if row is None:
        raise NotFound("群組不存在", code="group_not_found")
    items = _group_items(row.kind).filter(group=row.name)
    if delete_items:
        if row.kind == "source":
            for source in items:
                close_source(source.id)
            items.delete()
        else:
            for asset in items:
                try:
                    os.remove(asset.path)
                except OSError:
                    pass
                runner.forget_asset(str(asset.id))
            items.delete()
    else:
        items.update(group="")
    row.delete()
    return 204, None


# ---------------------------------------------------------------------------
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


@router.get("/fs")
def browse_fs(request: HttpRequest, path: str = ""):
    """伺服器檔案瀏覽（來源設定選資料夾／影像檔用；登入者可用——來源路徑本來就是伺服器路徑）。

    空 path＝磁碟機清單（Windows）或根目錄（POSIX）。每層最多列 500 項，影像檔以副檔名過濾。
    """
    import string

    if not path.strip():
        if os.name == "nt":
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            return {"path": "", "parent": None, "dirs": drives, "files": []}
        path = "/"
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise NotFound("資料夾不存在", code="dir_not_found")
    dirs, files = [], []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.name.startswith((".", "$")) or len(dirs) + len(files) >= 500:
                    continue
                try:
                    if entry.is_dir():
                        dirs.append(entry.name)
                    elif entry.name.lower().endswith(IMAGE_EXTS):
                        files.append(entry.name)
                except OSError:
                    continue
    except PermissionError:
        raise ValidationError("沒有權限讀取此資料夾", code="permission_denied") from None
    parent = os.path.dirname(path.rstrip("\\/"))
    if os.name == "nt" and len(path) <= 3:
        parent = ""  # 磁碟機根 → 回磁碟機清單
    return {"path": path, "parent": parent if parent != path else None, "dirs": sorted(dirs, key=str.lower), "files": sorted(files, key=str.lower)}


@router.get("/sources/usb-scan")
def usb_scan(request: HttpRequest, max_index: int = 6):
    """枚舉伺服器上的相機：逐一開啟探測（會短暫佔用裝置，掃描時暫停使用中的取像）。"""
    max_index = max(1, min(10, max_index))
    in_use = {int((s.config or {}).get("index", -1)): s.name for s in ImageSource.objects.filter(kind="usb")}
    items = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(i)
        try:
            if cap.isOpened():
                items.append({
                    "index": i,
                    "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 0,
                    "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0,
                    "in_use_by": in_use.get(i, ""),
                })
        finally:
            cap.release()
    return {"items": items}


@router.get("/sources/kinds")
def list_source_kinds(request: HttpRequest):
    return {"items": source_kinds()}


@router.get("/sources")
def list_sources(request: HttpRequest):
    return {"items": [_source_out(s) for s in ImageSource.objects.all()]}


@router.post("/sources", response={201: dict})
def create_source(request: HttpRequest, payload: schemas.SourceIn):
    try:
        with transaction.atomic():
            source = ImageSource.objects.create(name=payload.name.strip(), kind=payload.kind, config=payload.config, is_enabled=payload.is_enabled, group=payload.group.strip())
    except IntegrityError:
        raise Conflict("已有同名來源", code="source_name_taken") from None
    return 201, _source_out(source)


def _get_source(source_id: int) -> ImageSource:
    source = ImageSource.objects.filter(pk=source_id).first()
    if source is None:
        raise NotFound("影像來源不存在", code="source_not_found")
    return source


class SourceTestIn(Schema):
    kind: str
    config: dict[str, Any] = {}


# 固定路徑要註冊在 /sources/{source_id} 之前，否則被 {source_id} 吃掉回 405。
@router.post("/sources/test")
def test_source(request: HttpRequest, payload: SourceTestIn):
    """儲存前試擷取：依 kind／config 建暫時 grabber 抓一張（不快取、不落地），回尺寸、耗時與縮圖 data URL；失敗 422 帶原因。"""
    started = time.perf_counter()
    try:
        image = try_grab(payload.kind, dict(payload.config or {}))
    except (ValidationError, NotFound):
        raise
    except Exception as exc:  # noqa: BLE001 — 來源的任何錯誤都翻成可讀原因回前端
        raise ValidationError(f"擷取失敗：{exc}", code="source_test_failed") from exc
    if image is None:
        raise ValidationError("來源沒有回傳影像：請確認路徑、檔名樣式或裝置設定", code="no_frame")
    ms = round((time.perf_counter() - started) * 1000, 1)
    data = base64.b64encode(encode_image(image, max_side=480)).decode("ascii")
    return {"width": int(image.shape[1]), "height": int(image.shape[0]), "ms": ms, "image": f"data:image/jpeg;base64,{data}"}


@router.get("/sources/{source_id}")
def get_source(request: HttpRequest, source_id: int):
    return _source_out(_get_source(source_id))


@router.patch("/sources/{source_id}")
def patch_source(request: HttpRequest, source_id: int, payload: schemas.SourcePatch):
    source = _get_source(source_id)
    if payload.name is not None:
        source.name = payload.name.strip()
    if payload.kind is not None:
        source.kind = payload.kind
    if payload.config is not None:
        source.config = payload.config
    if payload.is_enabled is not None:
        source.is_enabled = payload.is_enabled
    if payload.group is not None:
        source.group = payload.group.strip()
    try:
        with transaction.atomic():
            source.save()
    except IntegrityError:
        raise Conflict("已有同名來源", code="source_name_taken") from None
    close_source(source.id)
    return _source_out(source)


@router.delete("/sources/{source_id}", response={204: None})
def delete_source(request: HttpRequest, source_id: int):
    source = _get_source(source_id)
    close_source(source.id)
    source.delete()
    return 204, None


@router.get("/sources/{source_id}/preview", auth=None)
def preview_source(request: HttpRequest, source_id: int, max: int = 1280):
    if authenticate(request) is None:
        return HttpResponse(status=401)
    image = grab_by_id(source_id)
    if image is None:
        raise NotFound("來源沒有回傳影像", code="no_frame")
    response = HttpResponse(encode_image(image, max_side=max or None), content_type="image/jpeg")
    response["Cache-Control"] = "no-store"
    return response


@router.post("/sources/{source_id}/push")
def push_source(request: HttpRequest, source_id: int, image: UploadedFile = File(...)):
    source = _get_source(source_id)
    grabber = open_source(source)
    if not hasattr(grabber, "push"):
        raise ValidationError("此來源不接受送圖", code="source_not_pushable")
    frame = _decode_upload(image)
    grabber.push(frame)  # type: ignore[attr-defined]
    return {"ok": True, "width": int(frame.shape[1]), "height": int(frame.shape[0])}


# ---------------------------------------------------------------------------
# 資產
# ---------------------------------------------------------------------------
@router.get("/assets")
def list_assets(request: HttpRequest, kind: str = ""):
    qs = Asset.objects.all()
    if kind:
        qs = qs.filter(kind=kind)
    return {"items": [_asset_out(a) for a in qs]}


@router.post("/assets", response={201: dict})
def upload_asset(request: HttpRequest, file: UploadedFile = File(...), kind: str = Form("image"), name: str = Form(""), group: str = Form("")):
    if kind not in ("image", "model", "file"):
        raise ValidationError("kind 必須是 image / model / file", code="bad_kind")
    asset_id = uuid.uuid4()
    ext = os.path.splitext(file.name or "")[1].lower() or ""
    folder = settings.VISION["ASSET_DIR"]
    path = os.path.join(str(folder), f"{asset_id.hex}{ext}")
    data = file.read()
    meta: dict[str, Any] = {}
    if kind == "image":
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValidationError("無法解碼影像", code="bad_image")
        meta = {"width": int(image.shape[1]), "height": int(image.shape[0]), "channels": int(image.shape[2]) if image.ndim == 3 else 1}
    with open(path, "wb") as fh:
        fh.write(data)
    asset = Asset.objects.create(id=asset_id, name=name or file.name or asset_id.hex, kind=kind, path=path, size=len(data), meta=meta, group=group.strip())
    return 201, _asset_out(asset)



@router.post("/assets/from-image", response={201: dict})
def asset_from_image(request: HttpRequest):
    """從快取影像裁一塊存成範本資產：{"ref": "...", "region": {...}, "name": "..."}"""
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("JSON 格式錯誤", code="bad_json") from None
    from apps.vision.tools.roi import crop

    image = store.get(str(body.get("ref") or ""))
    if image is None:
        raise NotFound("影像已不在快取中", code="image_gone")
    region = body.get("region")
    piece = crop(image, region, upright=True).image if region else image
    if piece.size == 0:
        raise ValidationError("區域為空", code="empty_region")
    asset_id = uuid.uuid4()
    path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.png")
    ok, buf = cv2.imencode(".png", piece)
    if not ok:
        raise ValidationError("編碼失敗", code="encode_failed")
    buf.tofile(path)
    asset = Asset.objects.create(
        id=asset_id, name=str(body.get("name") or f"template-{time.strftime('%H%M%S')}"), kind="image", path=path,
        size=int(buf.size), meta={"width": int(piece.shape[1]), "height": int(piece.shape[0]), "channels": int(piece.shape[2]) if piece.ndim == 3 else 1},
    )
    return 201, _asset_out(asset)


@router.patch("/assets/{asset_id}")
def patch_asset(request: HttpRequest, asset_id: uuid.UUID):
    """改名／改群組：{"name"?, "group"?}（檔案內容不可改，重傳即可）。

    注意要註冊在 /assets/from-image 之後——ninja 依註冊順序比對，{asset_id} 會把靜態子路徑攔成 405。
    """
    asset = Asset.objects.filter(pk=asset_id).first()
    if asset is None:
        raise NotFound("資產不存在", code="asset_not_found")
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("JSON 格式錯誤", code="bad_json") from None
    fields = []
    if "name" in body and str(body["name"]).strip():
        asset.name = str(body["name"]).strip()[:200]
        fields.append("name")
    if "group" in body:
        asset.group = str(body["group"] or "").strip()[:60]
        fields.append("group")
    if fields:
        asset.save(update_fields=fields)
    return _asset_out(asset)


@router.get("/assets/{asset_id}/file", auth=None)
def asset_file(request: HttpRequest, asset_id: uuid.UUID, max: int = 0):
    if authenticate(request) is None:
        return HttpResponse(status=401)
    asset = Asset.objects.filter(pk=asset_id).first()
    if asset is None or not os.path.isfile(asset.path):
        raise NotFound("資產不存在", code="asset_not_found")
    if asset.kind == "image":
        image = cv2.imdecode(np.fromfile(asset.path, dtype=np.uint8), cv2.IMREAD_COLOR)
        return HttpResponse(encode_image(image, max_side=max or None, fmt="png"), content_type="image/png")
    with open(asset.path, "rb") as fh:
        return HttpResponse(fh.read(), content_type="application/octet-stream")


@router.delete("/assets/{asset_id}", response={204: None})
def delete_asset(request: HttpRequest, asset_id: uuid.UUID):
    asset = Asset.objects.filter(pk=asset_id).first()
    if asset is None:
        raise NotFound("資產不存在", code="asset_not_found")
    try:
        os.remove(asset.path)
    except OSError:
        pass
    runner.forget_asset(str(asset.id))
    asset.delete()
    return 204, None
