"""Golden Set 與回歸 API。

GET    /vision/flows/{id}/golden                    列表（含 image_url）
POST   /vision/flows/{id}/golden                    multipart images[]（＋expect_status、note）
                                                     或 JSON {from_batch: [{image_ref, name, expect_status, expect_outputs, note}]}
GET    /vision/flows/{id}/golden/baseline           最新基準
GET    /vision/flows/{id}/golden/{case_id}/image    ?max=&fmt=&token=（<img> 可直接載）
PATCH  /vision/flows/{id}/golden/{case_id}          {name, expect_status, expect_outputs, note}
DELETE /vision/flows/{id}/golden/{case_id}
POST   /vision/flows/{id}/regress                   {graph?, save_baseline?, fail_under?} → 回歸報告

可見即可看／跑；擁有者或管理員才能增刪改；執行前 principal.can_execute()。
"""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, HttpResponse
from ninja import Router, Schema

from apps.accounts.security import authenticate, principal, require_feature
from apps.core.errors import NotFound, ValidationError
from apps.golden import regress
from apps.golden.models import GoldenBaseline, GoldenCase
from apps.vision.api import _decode_upload, _editable_flow, _visible_flows
from apps.vision.images import encode_image, store
from apps.vision.models import Flow
from apps.vision.runner import get_flow

router = Router(tags=["golden"])

MAX_UPLOAD = 200


def _visible_flow(request: HttpRequest, flow_id: int) -> Flow:
    flow = get_flow(flow_id)
    if not _visible_flows(request).filter(pk=flow.pk).exists():
        raise NotFound(f"Flow {flow_id} not found", code="flow_not_found")
    return flow


def _case_out(c: GoldenCase) -> dict[str, Any]:
    return {
        "id": c.id, "flow_id": c.flow_id, "name": c.name, "expect_status": c.expect_status, "expect_outputs": c.expect_outputs or {},
        "note": c.note, "created_at": c.created_at.isoformat(),
        "image_url": f"/api/vision/flows/{c.flow_id}/golden/{c.id}/image",
    }


def _get_case(flow: Flow, case_id: int) -> GoldenCase:
    case = GoldenCase.objects.filter(flow=flow, pk=case_id).first()
    if case is None:
        raise NotFound("Golden case not found", code="golden_case_not_found")
    return case


def _validate_expect_outputs(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValidationError("expect_outputs must be an object", code="bad_expect_outputs")
    for k, v in value.items():
        if isinstance(v, dict) and "value" in v and "tol" in v and regress._num(v["tol"]) is None:
            raise ValidationError(f"expect_outputs.{k}.tol must be a number", code="bad_expect_outputs")
    return value


# ---------------------------------------------------------------------------
# 列表 / 建立
# ---------------------------------------------------------------------------
@router.get("/flows/{flow_id}/golden")
def list_cases(request: HttpRequest, flow_id: int):
    flow = _visible_flow(request, flow_id)
    p = principal(request)
    items = [_case_out(c) for c in GoldenCase.objects.filter(flow=flow)]
    baseline = GoldenBaseline.latest_for(flow.id)
    return {
        "items": items, "total": len(items), "can_manage": p.can_edit_flow(flow),
        "baseline_version": baseline.flow_version if baseline else None,
        "baseline_at": baseline.created_at.isoformat() if baseline else None,
        "flow_version": flow.version,
    }


@router.post("/flows/{flow_id}/golden", response={201: dict})
def create_cases(request: HttpRequest, flow_id: int):
    require_feature(request, "golden")
    flow = _editable_flow(request, flow_id)
    created: list[GoldenCase] = []
    if request.content_type and request.content_type.startswith("application/json"):
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            raise ValidationError("Malformed JSON", code="bad_json") from None
        items = body.get("from_batch") if isinstance(body, dict) else None
        if not isinstance(items, list) or not items:
            raise ValidationError("A from_batch array is required", code="bad_request")
        if len(items) > MAX_UPLOAD:
            raise ValidationError(f"{MAX_UPLOAD} images at a time is the limit", code="too_many_images")
        gone = []
        prepared = []
        for i, item in enumerate(items):
            if not isinstance(item, dict) or not item.get("image_ref"):
                raise ValidationError(f"from_batch[{i}] has no image_ref", code="bad_request")
            image = store.get(str(item["image_ref"]))
            if image is None:
                gone.append(item["image_ref"])
                continue
            prepared.append((item, image))
        if gone:
            raise NotFound(f"No longer cached: {', '.join(map(str, gone[:5]))}", code="image_gone")
        for item, image in prepared:
            path = regress.save_image(flow.id, image)
            created.append(GoldenCase.objects.create(
                flow=flow, name=str(item.get("name") or item["image_ref"])[:200], image_path=path,
                expect_status=regress.normalize_expect_status(item.get("expect_status")),
                expect_outputs=_validate_expect_outputs(item.get("expect_outputs")), note=str(item.get("note") or ""),
            ))
    else:
        uploads = request.FILES.getlist("images") or request.FILES.getlist("images[]")
        if not uploads:
            raise ValidationError("images[] files are required", code="bad_request")
        if len(uploads) > MAX_UPLOAD:
            raise ValidationError(f"{MAX_UPLOAD} images at a time is the limit", code="too_many_images")
        expect_status = regress.normalize_expect_status(request.POST.get("expect_status"))
        note = request.POST.get("note") or ""
        raw_outputs = request.POST.get("expect_outputs")
        try:
            expect_outputs = _validate_expect_outputs(json.loads(raw_outputs)) if raw_outputs else {}
        except json.JSONDecodeError:
            raise ValidationError("expect_outputs is not valid JSON", code="bad_expect_outputs") from None
        decoded = []
        for up in uploads:
            try:
                decoded.append((up.name or "image", _decode_upload(up)))
            except ValidationError:
                raise ValidationError(f"Could not decode {up.name}", code="bad_image") from None
        for name, image in decoded:
            path = regress.save_image(flow.id, image)
            created.append(GoldenCase.objects.create(flow=flow, name=name[:200], image_path=path, expect_status=expect_status, expect_outputs=expect_outputs, note=note))
    return 201, {"items": [_case_out(c) for c in created], "created": len(created)}


# ---------------------------------------------------------------------------
# 基準（要放在 /{case_id} 之前）
# ---------------------------------------------------------------------------
@router.get("/flows/{flow_id}/golden/baseline")
def get_baseline(request: HttpRequest, flow_id: int):
    flow = _visible_flow(request, flow_id)
    b = GoldenBaseline.latest_for(flow.id)
    return {"baseline": regress.baseline_out(b), "flow_version": flow.version, "case_count": GoldenCase.objects.filter(flow=flow).count()}


# ---------------------------------------------------------------------------
# 單一 case
# ---------------------------------------------------------------------------
class GoldenAutotuneIn(Schema):
    graph: dict[str, Any] | None = None
    max_evals: int = 60
    deadline_s: float = 25.0
    groups: dict[int, str] = {}


@router.post("/flows/{flow_id}/golden/autotune")
def autotune_flow(request: HttpRequest, flow_id: int, payload: GoldenAutotuneIn):
    """用 Golden Set 的期望值自動調參（只動現場調機參數）；不寫回流程，回調整後的 graph 讓前端帶回編輯器。"""
    require_feature(request, "golden")
    from apps.vision.agent import autotune, service
    from apps.vision.graph import validate_graph

    flow = _visible_flow(request, flow_id)
    principal(request).can_execute()
    labeled, heldout, skipped = [], [], []
    if any(group not in ("tune", "accept") for group in payload.groups.values()):
        raise ValidationError("group must be tune or accept", code="bad_group")
    for case in GoldenCase.objects.filter(flow=flow).order_by("id"):
        image = regress.load_image(case.image_path)
        if image is None:
            skipped.append(case.name)
            continue
        group = payload.groups.get(case.id, "tune")
        (heldout if group == "accept" else labeled).append(autotune.Labeled(image, case.expect_status, case.expect_outputs or {}, case.name, group))
    if not labeled:
        raise ValidationError("The Golden Set has no readable case images", code="no_cases")
    graph = validate_graph(payload.graph or flow.graph)
    res = autotune.coordinate_search(graph, labeled, max_evals=max(1, min(200, payload.max_evals)), deadline_s=max(1.0, min(120.0, payload.deadline_s)),
                                     trial=lambda g, im: service.trial_run(g, im, keep_images=False))
    accepted = autotune.acceptance(res["graph"], heldout, lambda g, im: service.trial_run(g, im, keep_images=False))
    return {"flow_id": flow.id, "flow_version": flow.version, "graph_override": payload.graph is not None, "cases": len(labeled), "skipped": skipped,
            "acceptance": accepted, "acceptance_note": autotune.acceptance_text(accepted),
            **{k: res[k] for k in ("graph", "before", "after", "changes", "change_text", "evals", "elapsed_ms", "improved", "budget_hit")}}


@router.get("/flows/{flow_id}/golden/{case_id}/image", auth=None)
def case_image(request: HttpRequest, flow_id: int, case_id: int, max: int = 0, fmt: str = "jpeg", q: int = 85):
    # <img> 直接載入帶不了 header；authenticate() 接受 ?token= / ?api_key=。
    p = authenticate(request)
    if p is None:
        return HttpResponse(status=401)
    request.auth = p
    flow = _visible_flow(request, flow_id)
    case = _get_case(flow, case_id)
    image = regress.load_image(case.image_path)
    if image is None:
        raise NotFound("The image file does not exist", code="image_gone")
    data = encode_image(image, max_side=max or None, fmt="png" if fmt == "png" else "jpeg", quality=q)
    response = HttpResponse(data, content_type="image/png" if fmt == "png" else "image/jpeg")
    response["Cache-Control"] = "private, max-age=3600"
    return response


class CasePatch(Schema):
    name: str | None = None
    expect_status: str | None = None
    expect_outputs: dict[str, Any] | None = None
    note: str | None = None


@router.patch("/flows/{flow_id}/golden/{case_id}")
def patch_case(request: HttpRequest, flow_id: int, case_id: int, payload: CasePatch):
    require_feature(request, "golden")
    flow = _editable_flow(request, flow_id)
    case = _get_case(flow, case_id)
    if payload.name is not None:
        case.name = payload.name.strip()[:200] or case.name
    if payload.expect_status is not None:
        if payload.expect_status not in ("ok", "ng", "any"):
            raise ValidationError("expect_status must be ok, ng or any", code="bad_expect_status")
        case.expect_status = payload.expect_status
    if payload.expect_outputs is not None:
        case.expect_outputs = _validate_expect_outputs(payload.expect_outputs)
    if payload.note is not None:
        case.note = payload.note
    case.save()
    return _case_out(case)


@router.delete("/flows/{flow_id}/golden/{case_id}", response={204: None})
def delete_case(request: HttpRequest, flow_id: int, case_id: int):
    require_feature(request, "golden")
    flow = _editable_flow(request, flow_id)
    case = _get_case(flow, case_id)
    regress.remove_image(case.image_path)
    case.delete()
    return 204, None


# ---------------------------------------------------------------------------
# 回歸
# ---------------------------------------------------------------------------
class RegressIn(Schema):
    graph: dict[str, Any] | None = None
    save_baseline: bool = False
    fail_under: float | None = None


@router.post("/flows/{flow_id}/regress")
def regress_flow(request: HttpRequest, flow_id: int, payload: RegressIn):
    require_feature(request, "golden")
    flow = _visible_flow(request, flow_id)
    p = principal(request)
    p.can_execute()
    if payload.save_baseline and not p.can_edit_flow(flow):
        raise ValidationError("Only the owner or an administrator can save a baseline", code="not_owner")
    fail_under = payload.fail_under
    if fail_under is not None and not (0.0 <= fail_under <= 1.0):
        raise ValidationError("fail_under must be between 0 and 1", code="bad_fail_under")
    return regress.run_regression(flow, graph=payload.graph, save_baseline=payload.save_baseline, fail_under=fail_under)
