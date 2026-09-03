"""批次測試 API（/vision/batch/...）。

影像集：GET /batch/sets（flow_id 選填，省略＝所有看得見的影像集）、POST /batch/sets（multipart images[]＋flow_id、name）、POST /batch/sets/from-source、
        GET/PATCH/DELETE /batch/sets/{id}、GET /batch/sets/{id}/images/{index}、POST /batch/sets/{id}/to-golden
執行：  GET /batch/sets/{id}/runs、POST /batch/sets/{id}/runs（flow_id 選填＝用哪個流程測，mode=run|autotune，202 背景）、GET/PATCH/DELETE /batch/runs/{id}、
        POST /batch/runs/{id}/cancel、GET /batch/runs/{id}/insights、GET /batch/runs/{id}/compare?other=、
        POST /batch/runs/{id}/rows/{index}/preview（單張重跑取標記）、POST /batch/runs/{id}/to-recipe
可見性沿用流程的 _visible_flows；建立與執行需 can_execute；刪除需影像集擁有者或流程可編輯者。
"""

from __future__ import annotations

import json
import time
from typing import Any

from django.http import HttpRequest, HttpResponse
from ninja import File, Router, Schema, UploadedFile

from apps.accounts.security import authenticate, principal
from apps.core.errors import Conflict, NotFound, PermissionDenied, ValidationError
from apps.golden import regress
from apps.golden.models import GoldenCase
from apps.vision.api import _decode_upload, _recipe_out, _validate_overrides, _visible_flows
from apps.vision.batch import insights as insights_mod
from apps.vision.batch import jobs, store
from apps.vision.graph import validate_graph
from apps.vision.images import encode_image
from apps.vision.models import BatchRun, BatchSet, Flow, FlowRecipe, ImageSource
from apps.vision.runner import apply_recipe, get_flow, resolve_recipe, runner
from apps.vision.sources import grab_by_id

router = Router(tags=["batch"])

ORIGINS = ("manual", "draft")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _visible_flow(request: HttpRequest, flow_id: int) -> Flow:
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"流程 {flow_id} 不存在", code="flow_not_found")
    return flow


def _set_or_404(request: HttpRequest, set_id: int) -> BatchSet:
    s = BatchSet.objects.select_related("flow").filter(pk=set_id).first()  # noqa: F841 - 可見性以流程為準
    if s is None or not _visible_flows(request).filter(pk=s.flow_id).exists():
        raise NotFound(f"影像集 {set_id} 不存在", code="set_not_found")
    return s


def _run_or_404(request: HttpRequest, run_id: int) -> BatchRun:
    r = BatchRun.objects.select_related("batch_set__flow", "flow").filter(pk=run_id).first()
    if r is None or not _visible_flows(request).filter(pk=r.batch_set.flow_id).exists():
        raise NotFound(f"批次執行 {run_id} 不存在", code="run_not_found")
    return store.reconcile(r)


def _can_manage(request: HttpRequest, s: BatchSet) -> bool:
    p = principal(request)
    return p.is_admin or p.can_edit_flow(s.flow) or (p.user is not None and s.owner_id == p.user.id)


def _require_manage(request: HttpRequest, s: BatchSet) -> None:
    if not _can_manage(request, s):
        raise PermissionDenied("只有影像集建立者、流程擁有者或管理員能修改", code="not_owner")


def _max_images() -> int:
    return int(store.cfg("BATCH_MAX_IMAGES", 200))


def _create_set(request: HttpRequest, flow: Flow, name: str, source: str, frames: list[tuple[str, Any]]) -> BatchSet:
    if not frames:
        raise ValidationError("至少要一張影像", code="no_image")
    if len(frames) > _max_images():
        raise ValidationError(f"一個影像集最多 {_max_images()} 張", code="too_many_images")
    p = principal(request)
    s = BatchSet.objects.create(flow=flow, owner=p.user, name=(name or f"{flow.name} {time.strftime('%m/%d %H:%M')}")[:120], source=source[:120])
    store.save_images(s, frames)
    store.prune_sets(flow)
    return s


def _latest_runs(sets: list[BatchSet]) -> dict[int, BatchRun]:
    latest: dict[int, BatchRun] = {}
    for r in BatchRun.objects.filter(batch_set__in=sets).defer("items", "graph", "insights").order_by("-created_at"):
        latest.setdefault(r.batch_set_id, r)
    return latest


# ---------------------------------------------------------------------------
# 影像集
# ---------------------------------------------------------------------------
@router.get("/batch/sets")
def list_sets(request: HttpRequest, flow_id: int | None = None):
    """影像集清單。flow_id 給定＝只看該流程建立的；省略＝所有看得見的（影像集是測試資料，可用任一流程測）。"""
    query = BatchSet.objects.select_related("flow")
    if flow_id is not None:
        query = query.filter(flow=_visible_flow(request, flow_id))
    else:
        query = query.filter(flow__in=_visible_flows(request))
    sets = list(query.order_by("-created_at"))
    latest = _latest_runs(sets)
    return {
        "items": [store.set_out(s, latest=latest.get(s.id)) for s in sets], "total": len(sets),
        "max_images": _max_images(), "keep_sets": int(store.cfg("KEEP_BATCH_SETS", 10)), "keep_runs": int(store.cfg("KEEP_BATCH_RUNS", 20)),
    }


class FromSourceIn(Schema):
    flow_id: int
    source_id: int
    count: int = 10
    name: str = ""


@router.post("/batch/sets/from-source", response={201: dict})
def create_set_from_source(request: HttpRequest, payload: FromSourceIn):
    flow = _visible_flow(request, payload.flow_id)
    principal(request).can_execute()
    source = ImageSource.objects.filter(pk=payload.source_id).first()
    if source is None:
        raise NotFound(f"影像來源 {payload.source_id} 不存在", code="source_not_found")
    n = max(1, min(_max_images(), int(payload.count)))
    frames = []
    for i in range(n):
        img = grab_by_id(source.id)
        if img is None:
            break
        frames.append((f"{source.name}-{i + 1}", img))
    if not frames:
        raise ValidationError("影像來源取不到影像", code="no_image")
    s = _create_set(request, flow, payload.name, f"source:{source.name}", frames)
    return 201, store.set_out(s, full=True)


@router.post("/batch/sets", response={201: dict})
def create_set(request: HttpRequest, images: list[UploadedFile] = File(...)):
    try:
        flow_id = int(request.POST.get("flow_id") or 0)
    except ValueError:
        raise ValidationError("flow_id 必須是整數", code="bad_request") from None
    flow = _visible_flow(request, flow_id)
    principal(request).can_execute()
    if len(images) > _max_images():
        raise ValidationError(f"一個影像集最多 {_max_images()} 張", code="too_many_images")
    frames = []
    for up in images:
        try:
            frames.append((up.name or "image", _decode_upload(up)))
        except ValidationError:
            raise ValidationError(f"無法解碼：{up.name}", code="bad_image") from None
    s = _create_set(request, flow, str(request.POST.get("name") or ""), "upload", frames)
    return 201, store.set_out(s, full=True)


@router.get("/batch/sets/{set_id}")
def get_set(request: HttpRequest, set_id: int):
    s = _set_or_404(request, set_id)
    latest = _latest_runs([s]).get(s.id)
    return {**store.set_out(s, full=True, latest=latest), "can_manage": _can_manage(request, s)}


class LabelIn(Schema):
    index: int
    expected: str | None = None
    expect_outputs: dict[str, Any] | None = None
    note: str | None = None


class SetPatch(Schema):
    name: str | None = None
    labels: list[LabelIn] = []
    remove: list[int] = []


@router.patch("/batch/sets/{set_id}")
def patch_set(request: HttpRequest, set_id: int, payload: SetPatch):
    s = _set_or_404(request, set_id)
    _require_manage(request, s)
    fields = ["updated_at"]
    if payload.name is not None and payload.name.strip():
        s.name = payload.name.strip()[:120]
        fields.append("name")
    images = list(s.images or [])
    if payload.labels:
        by_index = {int(im["index"]): im for im in images}
        for lb in payload.labels:
            im = by_index.get(lb.index)
            if im is None:
                raise NotFound(f"影像 {lb.index} 不存在", code="image_not_found")
            if lb.expected is not None:
                if lb.expected not in store.EXPECTED_VALUES:
                    raise ValidationError("expected 必須是 ok、ng 或空字串", code="bad_expected")
                im["expected"] = lb.expected
            if lb.expect_outputs is not None:
                im["expect_outputs"] = dict(lb.expect_outputs)
            if lb.note is not None:
                im["note"] = lb.note[:500]
        fields.append("images")
    if payload.remove:
        if s.runs.filter(status__in=("queued", "running")).exists():
            raise Conflict("執行中無法移除影像", code="set_busy")
        drop = set(int(i) for i in payload.remove)
        for im in images:
            if int(im["index"]) in drop:
                regress.remove_image(str(im.get("path", "")))
        images = [im for im in images if int(im["index"]) not in drop]
        fields.append("images")
        s.image_count = len(images)
        fields.append("image_count")
    s.images = images
    s.save(update_fields=sorted(set(fields)))
    if "images" in fields:
        store.refresh_matches(s)
    latest = _latest_runs([s]).get(s.id)
    return {**store.set_out(s, full=True, latest=latest), "can_manage": True}


@router.delete("/batch/sets/{set_id}", response={204: None})
def delete_set(request: HttpRequest, set_id: int):
    s = _set_or_404(request, set_id)
    _require_manage(request, s)
    if s.runs.filter(status__in=("queued", "running")).exists():
        raise Conflict("執行中無法刪除影像集", code="set_busy")
    store.delete_set(s)
    return 204, None


@router.get("/batch/sets/{set_id}/images/{index}", auth=None)
def set_image(request: HttpRequest, set_id: int, index: int, max: int = 0, fmt: str = "jpeg", q: int = 85):
    p = authenticate(request)
    if p is None:
        return HttpResponse(status=401)
    request.auth = p
    s = _set_or_404(request, set_id)
    item = store.image_by_index(s, index)
    image = store.load_image(item)
    if image is None:
        raise NotFound("影像檔不存在", code="image_gone")
    data = encode_image(image, max_side=max or None, fmt="png" if fmt == "png" else "jpeg", quality=q)
    response = HttpResponse(data, content_type="image/png" if fmt == "png" else "image/jpeg")
    response["Cache-Control"] = "private, max-age=3600"
    return response


class ToGoldenIn(Schema):
    indexes: list[int] = []
    #: label＝用影像集的期望標記；status＝用指定執行的判定
    expect_from: str = "label"
    run_id: int | None = None
    note: str = ""


@router.post("/batch/sets/{set_id}/to-golden", response={201: dict})
def set_to_golden(request: HttpRequest, set_id: int, payload: ToGoldenIn):
    s = _set_or_404(request, set_id)
    p = principal(request)
    if not p.can_edit_flow(s.flow):
        raise PermissionDenied("只有流程擁有者或管理員能建立 Golden Set 案例", code="not_owner")
    statuses: dict[int, str] = {}
    if payload.expect_from == "status":
        if payload.run_id is None:
            raise ValidationError("expect_from=status 需要 run_id", code="bad_request")
        run = _run_or_404(request, payload.run_id)
        statuses = {int(it.get("index", -1)): str(it.get("status", "")) for it in run.items or []}
    wanted = set(payload.indexes) if payload.indexes else None
    created = []
    for im in s.images or []:
        idx = int(im["index"])
        if wanted is not None and idx not in wanted:
            continue
        image = store.load_image(im)
        if image is None:
            continue
        expect = statuses.get(idx, "") if payload.expect_from == "status" else str(im.get("expected") or "")
        path = regress.save_image(s.flow_id, image)
        created.append(GoldenCase.objects.create(flow=s.flow, name=str(im.get("name") or f"batch-{s.id}-{idx}")[:200], image_path=path,
                                                 expect_status=regress.normalize_expect_status(expect or "any"), expect_outputs=im.get("expect_outputs") or {},
                                                 note=payload.note or str(im.get("note") or "")))
    return 201, {"created": len(created), "ids": [c.id for c in created]}


# ---------------------------------------------------------------------------
# 執行
# ---------------------------------------------------------------------------
class RunCreate(Schema):
    #: 用哪個流程測（省略＝影像集的流程）；影像集只是測試資料，可以拿去測任何看得見的流程。
    flow_id: int | None = None
    mode: str = "run"
    graph: dict[str, Any] | None = None
    recipe_id: int | None = None
    label: str = ""
    note: str = ""
    parent_run_id: int | None = None
    origin: str = "manual"
    max_evals: int = 40
    deadline_s: float = 60.0


@router.get("/batch/sets/{set_id}/runs")
def list_runs(request: HttpRequest, set_id: int):
    s = _set_or_404(request, set_id)
    rows = []
    for r in s.runs.defer("items", "graph", "insights").order_by("-created_at"):
        r.batch_set = s
        store.reconcile(r)
        rows.append(store.run_out(r, batch_set=s, progress=jobs.progress(r.id)))
    return {"items": rows, "total": len(rows)}


@router.post("/batch/sets/{set_id}/runs", response={202: dict})
def create_run(request: HttpRequest, set_id: int, payload: RunCreate):
    s = _set_or_404(request, set_id)
    p = principal(request)
    p.can_execute()
    flow = _visible_flow(request, payload.flow_id) if payload.flow_id is not None else s.flow
    if payload.mode not in ("run", "autotune"):
        raise ValidationError("mode 必須是 run 或 autotune", code="bad_mode")
    if not s.images:
        raise ValidationError("影像集沒有影像", code="no_image")
    parent = None
    if payload.parent_run_id is not None:
        parent = _run_or_404(request, payload.parent_run_id)
        if parent.batch_set_id != s.id:
            raise ValidationError("parent_run_id 必須屬於同一個影像集", code="bad_parent")
    # 沒帶 graph：同流程接續上一次的參數，換流程則用該流程的現圖（別把別的流程的參數帶過來）
    inherit = parent.graph if (parent is not None and store.run_flow(parent).id == flow.id) else None
    graph = payload.graph or inherit or flow.graph
    recipe_name = ""
    if payload.recipe_id is not None:
        recipe = resolve_recipe(flow, str(payload.recipe_id))
        graph = apply_recipe(graph, recipe)
        recipe_name = recipe.name if recipe else ""
    graph = validate_graph(graph)
    if payload.mode == "autotune" and not any(im.get("expected") in ("ok", "ng") for im in s.images):
        raise ValidationError("自動調參需要先為影像標記期望 OK／NG", code="no_labels")
    origin = "autotune" if payload.mode == "autotune" else (payload.origin if payload.origin in ORIGINS else "manual")
    run = BatchRun.objects.create(
        batch_set=s, flow=None if flow.id == s.flow_id else flow, parent=parent, owner=p.user, flow_version=flow.version, graph=graph, recipe_name=recipe_name,
        label=payload.label[:120], note=payload.note[:2000], origin=origin, status="queued", progress_total=len(s.images),
    )
    try:
        prog = jobs.start(run, mode=payload.mode, autotune={"max_evals": max(1, min(200, payload.max_evals)), "deadline_s": max(5.0, min(600.0, payload.deadline_s))})
    except Conflict:
        run.delete()
        raise
    run.status = "running"
    return 202, store.run_out(run, batch_set=s, progress=prog)


@router.get("/batch/runs/{run_id}")
def get_run(request: HttpRequest, run_id: int, items: int = 1):
    r = _run_or_404(request, run_id)
    prog = jobs.progress(r.id)
    live = jobs.live_items(r.id) if (r.status in ("queued", "running") and prog) else None
    return store.run_out(r, items=bool(items), progress=prog, live_items=live)


class RunPatch(Schema):
    label: str | None = None
    note: str | None = None


@router.patch("/batch/runs/{run_id}")
def patch_run(request: HttpRequest, run_id: int, payload: RunPatch):
    r = _run_or_404(request, run_id)
    _require_manage(request, r.batch_set)
    fields = []
    if payload.label is not None:
        r.label = payload.label[:120]
        fields.append("label")
    if payload.note is not None:
        r.note = payload.note[:2000]
        fields.append("note")
    if fields:
        r.save(update_fields=fields)
    return store.run_out(r, progress=jobs.progress(r.id))


@router.post("/batch/runs/{run_id}/cancel")
def cancel_run(request: HttpRequest, run_id: int):
    r = _run_or_404(request, run_id)
    return {"cancelled": jobs.cancel(r.id)}


@router.delete("/batch/runs/{run_id}", response={204: None})
def delete_run(request: HttpRequest, run_id: int):
    r = _run_or_404(request, run_id)
    _require_manage(request, r.batch_set)
    if r.status in ("queued", "running") and jobs.progress(r.id):
        raise Conflict("執行中無法刪除", code="run_busy")
    r.delete()
    return 204, None


@router.get("/batch/runs/{run_id}/insights")
def run_insights(request: HttpRequest, run_id: int):
    r = _run_or_404(request, run_id)
    if r.status != "done":
        return {"ready": False, "status": r.status}
    if not r.insights:
        s = r.batch_set
        parent = BatchRun.objects.filter(pk=r.parent_id).only("items", "graph").first() if r.parent_id else None
        r.insights = insights_mod.compute(r.graph, r.items or [], s.images or [], parent_items=parent.items if parent else None, parent_graph=parent.graph if parent else None)
        r.save(update_fields=["insights"])
    return {"ready": True, "status": r.status, **r.insights, "suggestions": insights_mod.suggestions_of(r.insights)}


@router.get("/batch/runs/{run_id}/compare")
def compare_runs(request: HttpRequest, run_id: int, other: int):
    a = _run_or_404(request, run_id)
    b = _run_or_404(request, other)
    if a.batch_set_id != b.batch_set_id:
        raise ValidationError("只能比較同一個影像集的兩次執行", code="bad_compare")
    images = {int(im["index"]): im for im in (a.batch_set.images or [])}
    rows_a = {int(it["index"]): it for it in a.items or []}
    rows_b = {int(it["index"]): it for it in b.items or []}
    rows = []
    changed = improved = regressed = 0
    for idx in sorted(rows_a.keys() | rows_b.keys()):
        ia, ib = rows_a.get(idx), rows_b.get(idx)
        im = images.get(idx, {})
        ma, _ = store.row_match(ia, im) if ia else (None, [])
        mb, _ = store.row_match(ib, im) if ib else (None, [])
        diff = bool(ia and ib and ia.get("status") != ib.get("status"))
        changed += int(diff)
        improved += int(ma is False and mb is True)
        regressed += int(ma is True and mb is False)
        rows.append({"index": idx, "name": im.get("name", ""), "expected": im.get("expected", ""), "a_status": (ia or {}).get("status"), "b_status": (ib or {}).get("status"),
                     "a_match": ma, "b_match": mb, "changed": diff, "a_outputs": (ia or {}).get("outputs") or {}, "b_outputs": (ib or {}).get("outputs") or {},
                     "image_url": store.image_url(a.batch_set_id, idx)})
    return {"a": store.run_out(a), "b": store.run_out(b), "rows": rows,
            "summary": {"changed": changed, "improved": improved, "regressed": regressed, "same": len(rows) - changed,
                        "a_match": (a.summary or {}).get("match"), "b_match": (b.summary or {}).get("match"), "labeled": (a.summary or {}).get("labeled")},
            "param_diff": store.graph_param_diff(a.graph, b.graph)}


class PreviewIn(Schema):
    graph: dict[str, Any] | None = None


@router.post("/batch/runs/{run_id}/rows/{index}/preview")
def preview_row(request: HttpRequest, run_id: int, index: int, payload: PreviewIn):
    """單張重跑取標記（影像進流程快取供影像視窗顯示）。"""
    r = _run_or_404(request, run_id)
    principal(request).can_execute()
    item = store.image_by_index(r.batch_set, index)
    image = store.load_image(item)
    if image is None:
        raise NotFound("影像檔不存在", code="image_gone")
    graph = validate_graph(payload.graph) if payload.graph else r.graph
    report = runner.run_sync(store.run_flow(r), trigger="preview", preview=True, graph_override=graph, input_image=image)
    return report.to_dict(include_node_outputs=True)


class ToRecipeIn(Schema):
    name: str
    description: str = ""
    is_default: bool = False


@router.post("/batch/runs/{run_id}/to-recipe", response={201: dict})
def run_to_recipe(request: HttpRequest, run_id: int, payload: ToRecipeIn):
    """把這次執行的參數與流程現圖的差異存成配方。"""
    r = _run_or_404(request, run_id)
    flow = store.run_flow(r)
    if not principal(request).can_edit_flow(flow):
        raise PermissionDenied("只有流程擁有者或管理員能建立配方", code="not_owner")
    overrides = store.to_overrides(store.graph_param_diff(flow.graph, r.graph))
    if not overrides:
        raise ValidationError("此次執行的參數與流程相同，沒有可存的差異", code="no_diff")
    _validate_overrides(flow, overrides)
    name = payload.name.strip()[:80]
    if not name:
        raise ValidationError("配方名稱不能是空的", code="bad_name")
    if FlowRecipe.objects.filter(flow=flow, name=name).exists():
        raise Conflict(f"配方「{name}」已存在", code="recipe_exists")
    if payload.is_default:
        FlowRecipe.objects.filter(flow=flow, is_default=True).update(is_default=False)
    recipe = FlowRecipe.objects.create(flow=flow, name=name, description=payload.description[:500], param_overrides=overrides, is_default=payload.is_default)
    return 201, {**_recipe_out(recipe), "overrides_json": json.dumps(overrides, ensure_ascii=False)}
