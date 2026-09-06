"""形狀範本（shape model）資產的 API（WP-01）。

    POST /vision/assets/shape-model                 JSON：{asset_id 或 ref, region, exclude?, name?, group?, 建模參數…} → 201 資產（kind=file，npz）
    GET  /vision/assets/{id}/shape-model            → meta ＋ 第 0 層邊緣點（顯示用，最多 600 點）
    GET  /vision/assets/{id}/shape-model/preview    → 範本影像疊邊緣點的 PNG（<img> 直接載入，帶 ?token=）

`ref` 是影像快取裡的圖（編輯器試執行的節點影像、標定頁拍的照片都可以）；`asset_id` 是影像資產。
region 是範本區（任何形狀；非矩形以遮罩取邊緣），exclude 是要排除的區域（例如會變的印字）。
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import cv2
import numpy as np
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja import Router

from apps.accounts.security import authenticate, require_feature
from apps.core import audit
from apps.core.errors import NotFound, ValidationError
from apps.vision import shapemodel
from apps.vision.api import _asset_out
from apps.vision.images import store
from apps.vision.models import Asset
from apps.vision.tools.roi import crop as roi_crop
from apps.vision.tools.roi import mask_for

router = Router(tags=["shape-model"])

TEACH_PARAMS = ("contrast_low", "contrast_high", "min_contrast", "pyramid_levels", "max_points", "angle_start", "angle_extent", "scale_min", "scale_max")


def _body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("Malformed JSON", code="bad_json") from None
    if not isinstance(data, dict):
        raise ValidationError("The body must be a JSON object", code="bad_json")
    return data


def _source_image(body: dict[str, Any]) -> tuple[np.ndarray, str]:
    asset_id = body.get("asset_id")
    if asset_id:
        asset = Asset.objects.filter(pk=asset_id).first()
        if asset is None:
            raise NotFound(f"Asset {asset_id} not found", code="asset_not_found")
        try:
            buf = np.fromfile(asset.path, dtype=np.uint8)
        except OSError:
            raise NotFound("The asset file is missing", code="asset_file_missing") from None
        image = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValidationError("The asset is not a decodable image", code="bad_image")
        return image, f"asset {asset.name}"
    ref = str(body.get("ref") or "")
    image = store.get(ref) if ref else None
    if image is None:
        raise NotFound("Give asset_id (an image asset) or ref (a cached picture)", code="image_gone")
    return image, f"picture {ref}"


def _number(value: Any, default: float | None) -> float | None:
    if value in (None, "", "auto"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{value!r} is not a number", code="bad_number") from None


def build_model(image: np.ndarray, region: dict[str, Any] | None, exclude: dict[str, Any] | None, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """影像＋範本區（＋排除區）＋建模參數 → (model, meta)。ValidationError 給 API、ShapeModelError 由呼叫端翻譯。"""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    c = roi_crop(gray, region)
    if c.image.size == 0:
        raise ValidationError("The region falls outside the image", code="bad_region")
    mask = c.mask
    if exclude:
        ex = mask_for(exclude, c.image.shape[1], c.image.shape[0], offset=(c.x0, c.y0))
        cv2.bitwise_not(ex, dst=ex)
        mask = ex if mask is None else cv2.bitwise_and(mask, ex)
    kwargs: dict[str, Any] = {}
    for key in TEACH_PARAMS:
        if key in params and params[key] not in (None, ""):
            kwargs[key] = _number(params[key], None)
    if "pyramid_levels" in kwargs:
        kwargs["pyramid_levels"] = int(kwargs["pyramid_levels"])
    if "max_points" in kwargs:
        kwargs["max_points"] = max(50, int(kwargs["max_points"]))
    model = shapemodel.teach(np.ascontiguousarray(c.image), mask=mask, **kwargs)
    meta = shapemodel.describe(model)
    meta["region"] = region
    meta["exclude"] = exclude
    meta["offset"] = [int(c.x0), int(c.y0)]
    return model, meta


@router.post("/assets/shape-model", response={201: dict})
def create_shape_model(request: HttpRequest):
    require_feature(request, "assets")
    body = _body(request)
    image, source = _source_image(body)
    region = body.get("region")
    if region is not None and (not isinstance(region, dict) or not region.get("shape")):
        raise ValidationError("region must be an ROI object", code="bad_region")
    exclude = body.get("exclude")
    if exclude is not None and (not isinstance(exclude, dict) or not exclude.get("shape")):
        raise ValidationError("exclude must be an ROI object", code="bad_region")
    try:
        model, meta = build_model(image, region, exclude, body)
    except shapemodel.ShapeModelError as exc:
        raise ValidationError(str(exc), code="bad_template") from None
    asset_id = uuid.uuid4()
    path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.npz")
    size = shapemodel.save(path, model)
    name = str(body.get("name") or f"shape model {asset_id.hex[:6]}")[:200]
    asset = Asset.objects.create(id=asset_id, name=name, kind="file", group=str(body.get("group") or "").strip()[:60], path=path, size=size, meta=meta)
    # 範本影像本身也留一份（顯示用）：與模型同名 .png
    ok, buf = cv2.imencode(".png", roi_crop(image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), region).image)
    if ok:
        buf.tofile(os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.template.png"))
    audit.record(request, "asset.shape_model", f"asset:{asset.id}", summary=f"{asset.name}: {meta['levels']} levels, {meta['points'][0]} edge points from {source}")
    return 201, _asset_out(asset)


def _shape_asset(asset_id: uuid.UUID) -> tuple[Asset, dict[str, Any]]:
    asset = Asset.objects.filter(pk=asset_id).first()
    if asset is None:
        raise NotFound(f"Asset {asset_id} not found", code="asset_not_found")
    try:
        model = shapemodel.load(asset.path)
    except shapemodel.ShapeModelError as exc:
        raise ValidationError(str(exc), code="not_shape_model") from None
    return asset, model


@router.get("/assets/{asset_id}/shape-model")
def shape_model_info(request: HttpRequest, asset_id: uuid.UUID):
    require_feature(request, "assets")
    asset, model = _shape_asset(asset_id)
    c = model["centroid"]
    pts = shapemodel.model_outline(model, float(c[0]), float(c[1]), 0.0, 1.0, max_points=600)
    return {**_asset_out(asset), "meta": {**(asset.meta or {}), **shapemodel.describe(model)}, "points": pts,
            "preview": f"/api/vision/assets/{asset.id}/shape-model/preview"}


@router.get("/assets/{asset_id}/shape-model/preview", auth=None)
def shape_model_preview(request: HttpRequest, asset_id: uuid.UUID):
    if authenticate(request) is None:
        raise ValidationError("Unauthorized", code="unauthorized", status=401)
    asset, model = _shape_asset(asset_id)
    w, h = int(model["width"]), int(model["height"])
    tpl_path = os.path.splitext(asset.path)[0] + ".template.png"
    canvas = None
    if os.path.exists(tpl_path):
        tpl = cv2.imdecode(np.fromfile(tpl_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if tpl is not None and tpl.shape[:2] == (h, w):
            canvas = cv2.cvtColor(tpl, cv2.COLOR_GRAY2BGR)
    if canvas is None:
        canvas = np.full((h, w, 3), 40, np.uint8)
    c = model["centroid"]
    for x, y in shapemodel.model_outline(model, float(c[0]), float(c[1]), 0.0, 1.0, max_points=4000):
        xi, yi = int(round(x)), int(round(y))
        if 0 <= yi < h and 0 <= xi < w:
            canvas[yi, xi] = (0, 255, 0)
    cv2.drawMarker(canvas, (int(round(c[0])), int(round(c[1]))), (0, 200, 255), cv2.MARKER_CROSS, 12, 1)
    ok, buf = cv2.imencode(".png", canvas)
    if not ok:
        raise ValidationError("Encoding failed", code="encode_failed")
    return HttpResponse(buf.tobytes(), content_type="image/png", headers={"Cache-Control": "private, max-age=60"})
