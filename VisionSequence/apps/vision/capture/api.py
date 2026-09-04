"""擷取端 API：`/vision/capture/*`（已連線擷取端與通道、通道預覽、串流開關、擷取端程式下載）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from ninja import Router, Schema

from apps.accounts.security import authenticate, principal
from apps.core.errors import APIError, NotFound, ServiceUnavailable
from apps.vision.capture.hub import CaptureError, hub
from apps.vision.images import encode_image

router = Router(tags=["capture"])

DOWNLOAD_DIRNAME = "downloads"
ZIP_PREFIX = "VisionSequenceCapture-"


def download_dir() -> Path:
    return Path(getattr(settings, "DATA_DIR", ".")) / DOWNLOAD_DIRNAME


def download_info() -> dict[str, Any]:
    """讀 data/downloads/manifest.json（build_capture_client.ps1 產生）；沒有 manifest 就找最新的 zip。"""
    folder = download_dir()
    manifest = folder / "manifest.json"
    info: dict[str, Any] = {}
    if manifest.is_file():
        try:
            info = json.loads(manifest.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            info = {}
    path = folder / str(info.get("filename") or "") if info.get("filename") else None
    if path is None or not path.is_file():
        zips = sorted(folder.glob(f"{ZIP_PREFIX}*.zip"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []
        path = zips[0] if zips else None
    if path is None:
        return {"available": False, "version": "", "filename": "", "size": 0, "sha256": "", "built_at": None, "url": "/api/vision/capture/download"}
    stat = path.stat()
    version = str(info.get("version") or path.stem.removeprefix(ZIP_PREFIX).split("-")[0])
    return {
        "available": True, "version": version, "filename": path.name, "size": int(info.get("size") or stat.st_size),
        "sha256": str(info.get("sha256") or ""), "built_at": info.get("built_at"), "url": "/api/vision/capture/download", "path": str(path),
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
    info = download_info()
    if not info["available"]:
        raise NotFound("尚未建置擷取端程式：請於伺服端執行 scripts/build_capture_client.ps1，產物放在 data/downloads/", code="capture_download_missing")
    response = FileResponse(open(info["path"], "rb"), as_attachment=True, filename=info["filename"])
    response["Cache-Control"] = "no-store"
    return response


@router.get("/capture/clients/{name}/channels/{cid}/preview", auth=None)
def channel_preview(request: HttpRequest, name: str, cid: str, max: int = 1280):
    """通道預覽（<img> 用；?token=／?api_key= 驗證，同 /sources/{id}/preview）。"""
    if authenticate(request) is None:
        raise APIError("未登入", code="unauthenticated", status_code=401)
    if hub.get(name) is None:
        raise NotFound(f"擷取端「{name}」未連線", code="capture_client_not_found")
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
