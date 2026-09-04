"""擷取端 API：`/vision/capture/*`（已連線擷取端與通道、通道預覽、串流開關、擷取端程式下載）。"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from ninja import Router, Schema

from apps.accounts.security import authenticate, principal
from apps.core.errors import APIError, NotFound, ServiceUnavailable
from apps.vision.capture import build
from apps.vision.capture.hub import CaptureError, hub
from apps.vision.images import encode_image

router = Router(tags=["capture"])


def download_info() -> dict[str, Any]:
    """建置資訊給網頁下載鈕用（實體檔案與 manifest 的解析在 apps/vision/capture/build.py）。"""
    data = build.info(fresh=True)
    return {
        "available": bool(data["available"]), "version": data["version"], "filename": data["filename"], "size": data["size"],
        "sha256": data["sha256"], "built_at": data["built_at"], "url": "/api/vision/capture/download",
    }


@router.get("/capture/clients")
def list_clients(request: HttpRequest):
    return {"listening": hub.listening, "host": hub.host or settings.VISION["CAPTURE_HOST"], "port": hub.port or settings.VISION["CAPTURE_PORT"], "items": hub.clients()}


@router.get("/capture/download/info")
def capture_download_info(request: HttpRequest):
    info = download_info()
    info.pop("path", None)
    return info


@router.get("/capture/download")
def capture_download(request: HttpRequest):
    info = build.info(fresh=True)
    if not info["available"]:
        raise NotFound("The capture client has not been built: run scripts/build_capture_client.ps1 on the server; the result goes in data/downloads/", code="capture_download_missing")
    response = FileResponse(open(info["path"], "rb"), as_attachment=True, filename=info["filename"])
    response["Cache-Control"] = "no-store"
    return response


@router.get("/capture/clients/{name}/channels/{cid}/preview", auth=None)
def channel_preview(request: HttpRequest, name: str, cid: str, max: int = 1280):
    """通道預覽（<img> 用；?token=／?api_key= 驗證，同 /sources/{id}/preview）。"""
    if authenticate(request) is None:
        raise APIError("Not signed in", code="unauthenticated", status_code=401)
    if hub.get(name) is None:
        raise NotFound(f'Capture client "{name}" is not connected', code="capture_client_not_found")
    try:
        frame = hub.request_frame(name, cid, timeout=2.0, min_seq=0, after_request=False)
    except CaptureError as exc:
        if exc.code in ("no_channel", "channel_disabled"):
            raise NotFound(str(exc), code="capture_channel_not_found") from None
        raise ServiceUnavailable(str(exc), code="capture_unavailable") from None
    response = HttpResponse(encode_image(frame.image, max_side=max or None), content_type="image/jpeg")
    response["Cache-Control"] = "no-store"
    return response


class StreamIn(Schema):
    enabled: bool
    max_fps: float = 0


@router.post("/capture/clients/{name}/channels/{cid}/stream")
def set_channel_stream(request: HttpRequest, name: str, cid: str, payload: StreamIn):
    principal(request).can_execute()
    try:
        hub.set_stream(name, cid, payload.enabled, payload.max_fps)
    except CaptureError as exc:
        if exc.code == "client_offline":
            raise NotFound(str(exc), code="capture_client_not_found") from None
        if exc.code in ("no_channel", "channel_disabled"):
            raise NotFound(str(exc), code="capture_channel_not_found") from None
        raise ServiceUnavailable(str(exc), code="capture_unavailable") from None
    return {"ok": True, "streaming": payload.enabled}
