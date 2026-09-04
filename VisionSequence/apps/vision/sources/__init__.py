"""影像來源：每種 kind 一個 Grabber 類別，`open_source()` 依 ImageSource 設定建立並快取。

Grabber 介面：
    grab() -> np.ndarray | None   取一張（BGR uint8 或灰階）
    close()
    info() -> dict                 狀態（前端顯示）
外掛（三選一，見 docs/plugins.html）：
- 資料夾外掛：繼承 Grabber 的 .py 丟進 plugins/，啟動時自動註冊（register_kind）。
- settings.VISION["SOURCE_PLUGINS"] = {"gige": "plugins.gige:GigEGrabber"}。
- kind="plugin" 的來源以 config["class"] 指定類別路徑。
"""

from __future__ import annotations

import importlib
import logging
import threading
from typing import Any

import numpy as np
from django.conf import settings

from apps.core.errors import NotFound, ValidationError
from apps.vision.sources.grabbers import FileGrabber, FolderGrabber, Grabber, SyntheticGrabber, UploadGrabber, UsbGrabber

# 擷取端相機（apps/vision/capture）：grabber 模組只依賴 grabbers.py 與 hub，放在 grabbers import 之後不會循環。
from apps.vision.capture.grabber import CaptureGrabber  # noqa: E402

log = logging.getLogger(__name__)

_BUILTIN = {
    "folder": FolderGrabber,
    "file": FileGrabber,
    "usb": UsbGrabber,
    "synthetic": SyntheticGrabber,
    "upload": UploadGrabber,
    "capture": CaptureGrabber,
}

#: 資料夾外掛註冊的 kind（apps.core.plugins 掛載）。
_PLUGIN_KINDS: dict[str, type[Grabber]] = {}

_lock = threading.Lock()
#: source_id → (updated_at iso, grabber)
_open: dict[int, tuple[str, Grabber]] = {}


def register_kind(cls: type[Grabber]) -> bool:
    """註冊資料夾外掛的來源類別；kind 已存在（內建或先註冊者優先）回 False。"""
    kind = str(getattr(cls, "kind", "") or "")
    if not kind or kind in _BUILTIN:
        log.warning("影像來源外掛 %s 的 kind '%s' 無效或與內建重複，略過", cls.__name__, kind)
        return False
    if kind in _PLUGIN_KINDS:
        if _PLUGIN_KINDS[kind] is not cls:
            log.warning("影像來源 kind '%s' 已被 %s 註冊，略過 %s", kind, _PLUGIN_KINDS[kind].__name__, cls.__name__)
        return False
    _PLUGIN_KINDS[kind] = cls
    return True


def _resolve_class(kind: str, config: dict[str, Any]):
    if kind in _BUILTIN:
        return _BUILTIN[kind]
    if kind in _PLUGIN_KINDS:
        return _PLUGIN_KINDS[kind]
    plugins = getattr(settings, "VISION", {}).get("SOURCE_PLUGINS", {})
    path = config.get("class") if kind == "plugin" else plugins.get(kind)
    if not path or ":" not in path:
        raise ValidationError(f"未知的影像來源類型 '{kind}'", code="unknown_source_kind")
    module, cls = path.split(":", 1)
    return getattr(importlib.import_module(module), cls)


def open_source(source) -> Grabber:
    """依模型列建立（或取回快取的）grabber。設定變更（updated_at 變）會重開。"""
    stamp = source.updated_at.isoformat() if source.updated_at else ""
    with _lock:
        cached = _open.get(source.id)
        if cached and cached[0] == stamp:
            return cached[1]
        if cached:
            try:
                cached[1].close()
            except Exception:  # noqa: BLE001
                log.exception("關閉影像來源 %s 失敗", source.name)
        cls = _resolve_class(source.kind, source.config or {})
        grabber = cls(dict(source.config or {}), source_id=source.id, name=source.name)
        _open[source.id] = (stamp, grabber)
        return grabber


def grab_by_id(source_id: int | str) -> np.ndarray | None:
    from apps.vision.models import ImageSource

    try:
        sid = int(source_id)
    except (TypeError, ValueError):
        raise NotFound(f"影像來源 '{source_id}' 不存在", code="source_not_found") from None
    with _lock:
        cached = _open.get(sid)
    if cached:
        return cached[1].grab()
    source = ImageSource.objects.filter(pk=sid).first()
    if source is None:
        raise NotFound(f"影像來源 {sid} 不存在", code="source_not_found")
    return open_source(source).grab()


def try_grab(kind: str, config: dict[str, Any] | None) -> np.ndarray | None:
    """儲存前的「測試擷取」：依 kind／config 建一個暫時 grabber 抓一張就關，不快取、不落資料庫。"""
    cls = _resolve_class(kind, config or {})
    grabber = cls(dict(config or {}), source_id=0, name="")
    try:
        image = grabber.grab()
        if image is None and grabber.last_error:
            # 把來源自己知道的原因帶給「測試擷取」（例如擷取端未連線），不要只回泛用的沒影像
            raise ValidationError(grabber.last_error, code="no_frame")
        return image
    finally:
        try:
            grabber.close()
        except Exception:  # noqa: BLE001
            log.exception("關閉測試擷取的影像來源失敗")


def last_error_of(source_id: int | str) -> str:
    """快取中 grabber 的 last_error（不碰 DB；引擎在來源沒回影像時拿來組錯誤訊息）。"""
    try:
        sid = int(source_id)
    except (TypeError, ValueError):
        return ""
    with _lock:
        cached = _open.get(sid)
    return str(getattr(cached[1], "last_error", "") or "") if cached else ""


def close_source(source_id: int) -> None:
    with _lock:
        cached = _open.pop(source_id, None)
    if cached:
        try:
            cached[1].close()
        except Exception:  # noqa: BLE001
            log.exception("關閉影像來源失敗")


def close_all() -> None:
    with _lock:
        items = list(_open.items())
        _open.clear()
    for _, (_, grabber) in items:
        try:
            grabber.close()
        except Exception:  # noqa: BLE001
            pass


def source_info(source) -> dict[str, Any]:
    with _lock:
        cached = _open.get(source.id)
    if not cached:
        if source.kind == "capture":
            from apps.vision.capture.grabber import channel_status

            cfg = source.config or {}
            return {"open": False, "client": str(cfg.get("client") or ""), "channel": str(cfg.get("channel") or ""), **channel_status(str(cfg.get("client") or ""), str(cfg.get("channel") or ""))}
        return {"open": False}
    try:
        return {"open": True, **cached[1].info()}
    except Exception as exc:  # noqa: BLE001
        return {"open": True, "error": str(exc)}


def kinds() -> list[dict[str, Any]]:
    plugins = getattr(settings, "VISION", {}).get("SOURCE_PLUGINS", {})
    out = [
        {"kind": "folder", "label": "資料夾（循環讀取影像檔）", "fields": ["path", "loop", "sort", "pattern"]},
        {"kind": "file", "label": "單一影像檔", "fields": ["path"]},
        {"kind": "usb", "label": "USB / 網路攝影機（OpenCV）", "fields": ["index", "width", "height", "fps"]},
        {"kind": "synthetic", "label": "合成測試影像", "fields": ["width", "height", "pattern", "seed"]},
        {"kind": "upload", "label": "手動上傳（API 送圖）", "fields": []},
        {"kind": "capture", "label": CaptureGrabber.label, "fields": list(CaptureGrabber.fields), "description": CaptureGrabber.description},
    ]
    for kind, cls in _PLUGIN_KINDS.items():
        out.append({
            "kind": kind,
            "label": getattr(cls, "label", "") or f"外掛：{kind}",
            "fields": list(getattr(cls, "fields", []) or []),
            "description": getattr(cls, "description", ""),
        })
    for kind in plugins:
        if kind not in _PLUGIN_KINDS:
            out.append({"kind": kind, "label": f"外掛：{kind}", "fields": []})
    out.append({"kind": "plugin", "label": "外掛（自訂類別路徑）", "fields": ["class"]})
    return out
