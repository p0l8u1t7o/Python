"""固定影像的 API：上傳（多檔）、把快取裡的影像收進來（ref）、取檔與縮圖。

    POST /vision/fixed-images                 multipart files[]（或 file）→ {"items": [descriptor…]}
    POST /vision/fixed-images/from-ref        {ref, name?} → descriptor（把試執行／API 送進來的快取影像存成固定影像）
    GET  /vision/fixed-images/{id}            PNG 原圖（auth=None＋?token=，與資產檔案同一套）
    GET  /vision/fixed-images/{id}/thumb?w=   JPEG 縮圖
    GET  /vision/fixed-images                 {"count", "bytes", "orphans"}（管理用）
"""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, HttpResponse
from ninja import File, Router, UploadedFile

from apps.accounts.security import authenticate, principal, require_feature
from apps.core.errors import NotFound, PermissionDenied, ValidationError
from apps.vision import fixed_images
from apps.vision.images import store

router = Router(tags=["fixed-images"])


def _err(exc: fixed_images.FixedImageError) -> ValidationError:
    return ValidationError(str(exc), code="bad_image")


@router.post("/fixed-images", response={201: dict})
def upload_fixed_images(request: HttpRequest, files: list[UploadedFile] = File(...)):
    require_feature(request, "flows.edit")
    items: list[dict[str, Any]] = []
    for f in files:
        try:
            items.append(fixed_images.store_bytes(f.read(), f.name or ""))
        except fixed_images.FixedImageError as exc:
            raise _err(exc) from None
    if not items:
        raise ValidationError("No file was uploaded (field: files)", code="bad_request")
    return 201, {"items": items}


@router.post("/fixed-images/from-ref", response={201: dict})
def fixed_image_from_ref(request: HttpRequest):
    require_feature(request, "flows.edit")
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise ValidationError("Malformed JSON", code="bad_json") from None
    ref = str((body or {}).get("ref") or "")
    image = store.get(ref) if ref else None
    if image is None:
        raise NotFound("The picture is no longer in the cache; upload it as a file instead", code="image_gone")
    try:
        return 201, fixed_images.store(image, str((body or {}).get("name") or ref.replace(":", "_")))
    except fixed_images.FixedImageError as exc:
        raise _err(exc) from None


@router.get("/fixed-images")
def fixed_images_info(request: HttpRequest):
    require_feature(request, "flows.edit")
    ids = fixed_images.list_ids()
    return {"count": len(ids), "bytes": fixed_images.total_bytes(), "orphans": fixed_images.orphans()}


def _auth_or_401(request: HttpRequest) -> None:
    who = authenticate(request)
    if who is None:
        raise PermissionDenied("Sign in to view pictures", code="unauthorized", status=401) if hasattr(PermissionDenied, "__init__") else PermissionDenied("Sign in")


@router.get("/fixed-images/{image_id}", auth=None)
def fixed_image_file(request: HttpRequest, image_id: str):
    who = authenticate(request)
    if who is None:
        principal(request)  # 沒有身分：這裡會拋 401
    if not fixed_images.exists(image_id):
        raise NotFound("Fixed image not found", code="fixed_image_not_found")
    with open(fixed_images.path_of(image_id), "rb") as fh:
        data = fh.read()
    resp = HttpResponse(data, content_type="image/png")
    resp["Cache-Control"] = "private, max-age=86400, immutable"
    return resp


@router.get("/fixed-images/{image_id}/thumb", auth=None)
def fixed_image_thumb(request: HttpRequest, image_id: str, w: int = 160):
    who = authenticate(request)
    if who is None:
        principal(request)
    data = fixed_images.thumbnail(image_id, max(24, min(640, int(w))))
    if data is None:
        raise NotFound("Fixed image not found", code="fixed_image_not_found")
    resp = HttpResponse(data, content_type="image/jpeg")
    resp["Cache-Control"] = "private, max-age=86400, immutable"
    return resp
