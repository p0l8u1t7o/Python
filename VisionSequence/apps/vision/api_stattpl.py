"""統計範本資產的 API（WP-07）。

    POST /vision/assets/stat-template                 multipart：images[]（≥ 3 張良品）或 batch_set_id（批次影像集，only_ok=1 只取標 OK 的）
                                                      ＋ name／group／region（JSON 字串）／align（phase｜none）／max_shift → 201 資產
    GET  /vision/assets/{id}/stat-template            → meta（樣本數、尺寸、對齊殘差、std 分位數、有效比例）
    GET  /vision/assets/{id}/stat-template/{which}    → mean｜std｜valid 的 PNG（<img> 直接載入，帶 ?token=）

範本本身是 Asset(kind="file") 的 npz（apps/vision/stattpl.py），defect_stat 工具的 `model` 參數選它。
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
from ninja import File, Form, Router, UploadedFile

from apps.accounts.security import authenticate, require_feature
from apps.core import audit
from apps.core.errors import NotFound, ValidationError
from apps.vision import stattpl
from apps.vision.api import _asset_out, _visible_flows
from apps.vision.batch import store as batch_store
from apps.vision.models import Asset, BatchSet

router = Router(tags=["stat-template"])

MAX_IMAGES = 200


def _decode(data: bytes, label: str) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValidationError(f"{label} is not a decodable image", code="bad_image")
    return image


def _batch_images(request: HttpRequest, set_id: int, only_ok: bool) -> list[np.ndarray]:
    row = BatchSet.objects.select_related("flow").filter(pk=set_id).first()
    if row is None or not _visible_flows(request).filter(pk=row.flow_id).exists():
        raise NotFound(f"Image set {set_id} not found", code="set_not_found")
    out = []
    for item in (row.images or [])[:MAX_IMAGES]:
        if only_ok and str(item.get("expected") or "") == "ng":
            continue
        img = batch_store.load_image(item)
        if img is not None:
            out.append(img)
    return out


@router.post("/assets/stat-template", response={201: dict})
def create_stat_template(request: HttpRequest, images: list[UploadedFile] = File(None), name: str = Form(""), group: str = Form(""),
                         region: str = Form(""), align: str = Form("phase"), max_shift: float = Form(0.0), batch_set_id: int = Form(0), only_ok: bool = Form(True)):
    require_feature(request, "assets")
    if batch_set_id:
        frames = _batch_images(request, int(batch_set_id), bool(only_ok))
        source = f"image set {batch_set_id}"
    else:
        uploads = list(images or [])[:MAX_IMAGES]
        frames = [_decode(f.read(), f.name or f"image {i + 1}") for i, f in enumerate(uploads)]
        source = f"{len(frames)} uploaded images"
    region_dict: dict[str, Any] | None = None
    if region.strip():
        try:
            region_dict = json.loads(region)
        except json.JSONDecodeError:
            raise ValidationError("region is not valid JSON", code="bad_json") from None
        if not isinstance(region_dict, dict) or not region_dict.get("shape"):
            raise ValidationError("region must be an ROI object", code="bad_region")
    try:
        payload, meta = stattpl.build(frames, region_dict, align, float(max_shift or 0))
    except stattpl.StatTemplateError as exc:
        raise ValidationError(str(exc), code="bad_samples") from None
    asset_id = uuid.uuid4()
    path = os.path.join(str(settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.npz")
    size = stattpl.save(path, payload)
    asset = Asset.objects.create(id=asset_id, name=(name.strip() or f"statistical template {asset_id.hex[:6]}")[:200], kind="file", group=group.strip()[:60], path=path, size=size, meta=meta)
    audit.record(request, "asset.stat_template", f"asset:{asset.id}", summary=f"{asset.name}: {meta['samples']} samples from {source}, {meta['width']}×{meta['height']}")
    return 201, _asset_out(asset)


def _stat_asset(asset_id: uuid.UUID) -> tuple[Asset, dict[str, Any]]:
    asset = Asset.objects.filter(pk=asset_id).first()
    if asset is None:
        raise NotFound(f"Asset {asset_id} not found", code="asset_not_found")
    try:
        payload = stattpl.load(asset.path)
    except stattpl.StatTemplateError as exc:
        raise ValidationError(str(exc), code="not_stat_template") from None
    return asset, payload


@router.get("/assets/{asset_id}/stat-template")
def stat_template_info(request: HttpRequest, asset_id: uuid.UUID):
    require_feature(request, "assets")
    asset, payload = _stat_asset(asset_id)
    meta = stattpl.describe(payload)
    return {**_asset_out(asset), "meta": {**(asset.meta or {}), **meta}, "shifts": np.asarray(payload.get("shifts", [])).round(3).tolist(),
            "images": {which: f"/api/vision/assets/{asset.id}/stat-template/{which}" for which in ("mean", "std", "valid")}}


@router.get("/assets/{asset_id}/stat-template/{which}", auth=None)
def stat_template_image(request: HttpRequest, asset_id: uuid.UUID, which: str):
    # <img> 直接載入帶不了 header；authenticate() 接受 ?token= / ?api_key=（與 /images/{ref} 相同）
    if authenticate(request) is None:
        raise ValidationError("Unauthorized", code="unauthorized", status=401)
    _, payload = _stat_asset(asset_id)
    if which == "mean":
        image = cv2.convertScaleAbs(payload["mean"])
    elif which == "std":
        image = cv2.convertScaleAbs(payload["std"], alpha=8.0)  # 1 灰階 σ ＝ 8，32 σ 飽和
    elif which == "valid":
        image = payload["valid"]
    else:
        raise NotFound("which must be mean, std or valid", code="bad_which")
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValidationError("Encoding failed", code="encode_failed")
    return HttpResponse(buf.tobytes(), content_type="image/png", headers={"Cache-Control": "private, max-age=60"})
