"""擷取端安裝檔（data/downloads/）：讀 manifest.json、開檔給下載端點與 hub 的更新推播共用。

`scripts/build_capture_client.ps1` 產出 `VisionSequenceCapture-<版本>-win64.zip` 與 `manifest.json`；
下載走 HTTP（網頁）或擷取連線（已連上的擷取端自動更新，不必再開一個埠）。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from django.conf import settings

DOWNLOAD_DIRNAME = "downloads"
ZIP_PREFIX = "VisionSequenceCapture-"
CACHE_TTL_S = 5.0

_lock = threading.Lock()
_cache: tuple[str, float, dict[str, Any]] | None = None


def download_dir() -> Path:
    return Path(getattr(settings, "DATA_DIR", ".")) / DOWNLOAD_DIRNAME


def _read() -> dict[str, Any]:
    """讀 data/downloads/manifest.json（沒有 manifest 就找最新的 zip）；回 available/version/filename/size/sha256/built_at/path。"""
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
        return {"available": False, "version": "", "filename": "", "size": 0, "sha256": "", "built_at": None, "path": ""}
    stat = path.stat()
    return {
        "available": True,
        "version": str(info.get("version") or path.stem.removeprefix(ZIP_PREFIX).split("-")[0]),
        "filename": path.name,
        "size": int(info.get("size") or stat.st_size),
        "sha256": str(info.get("sha256") or ""),
        "built_at": info.get("built_at"),
        "path": str(path),
        "mtime": stat.st_mtime,
    }


def info(*, fresh: bool = False) -> dict[str, Any]:
    """建置資訊（5 秒快取；hub 每次心跳都會問，不能每次讀磁碟）。"""
    global _cache
    now = time.monotonic()
    key = str(download_dir())
    with _lock:
        if not fresh and _cache is not None and _cache[0] == key and now - _cache[1] < CACHE_TTL_S:
            return dict(_cache[2])
        data = _read()
        _cache = (key, now, data)
        return dict(data)


def read_chunk(offset: int, length: int) -> tuple[bytes, bool]:
    """讀安裝檔的一段，回 (資料, 是否已到檔尾)。給擷取連線上的自動更新用。"""
    data = info()
    path = Path(str(data.get("path") or ""))
    if not data.get("available") or not path.is_file():
        raise FileNotFoundError("尚未建置擷取端安裝檔")
    size = int(data["size"])
    offset = max(0, int(offset))
    length = max(0, min(int(length), size - offset))
    with path.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read(length)
    return chunk, offset + len(chunk) >= size


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None
