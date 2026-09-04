"""相機後端登錄：webcam（網路攝影機／USB 相機）、basler（pylon）、ids（IDS peak）、ueye（舊款 uEye）、fake（模擬）。

各後端模組延後 import（SDK 可能沒裝）；`availability()` 回每種後端是否可用與原因。
"""

from __future__ import annotations

import importlib
from typing import Any

from vscapture.cameras.base import Camera, CameraError, DeviceInfo, SdkMissing

BACKEND_MODULES = {
    "webcam": ("vscapture.cameras.webcam", "WebcamCamera"),
    "basler": ("vscapture.cameras.basler", "BaslerCamera"),
    "ids": ("vscapture.cameras.ids", "IdsPeakCamera"),
    "ueye": ("vscapture.cameras.ueye", "UeyeCamera"),
    "fake": ("vscapture.cameras.fake", "FakeCamera"),
}
BACKEND_LABELS = {
    "webcam": "網路攝影機／USB 相機",
    "basler": "Basler（pylon）",
    "ids": "IDS peak",
    "ueye": "IDS uEye（舊款）",
    "fake": "模擬相機",
}
_CLASSES: dict[str, type[Camera]] = {}


def backend_class(backend: str) -> type[Camera]:
    if backend in _CLASSES:
        return _CLASSES[backend]
    spec = BACKEND_MODULES.get(backend)
    if spec is None:
        raise CameraError(f"未知的相機種類：{backend}")
    module = importlib.import_module(spec[0])
    cls = getattr(module, spec[1])
    _CLASSES[backend] = cls
    return cls


def availability() -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
    for name in BACKEND_MODULES:
        try:
            out[name] = backend_class(name).available()
        except Exception as exc:  # noqa: BLE001
            out[name] = (False, str(exc))
    return out


def enumerate_all(backends: list[str] | None = None) -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for name in backends or list(BACKEND_MODULES):
        try:
            cls = backend_class(name)
            ok, _ = cls.available()
            if ok:
                devices.extend(cls.enumerate())
        except Exception:  # noqa: BLE001 — 某個 SDK 壞掉不影響其他種類
            continue
    return devices


def create(backend: str) -> Camera:
    cls = backend_class(backend)
    ok, reason = cls.available()
    if not ok:
        raise SdkMissing(reason or f"{BACKEND_LABELS.get(backend, backend)} 的 SDK 尚未安裝")
    return cls()


def describe_backends() -> list[dict[str, Any]]:
    avail = availability()
    return [{"backend": k, "label": BACKEND_LABELS[k], "available": avail[k][0], "reason": avail[k][1]} for k in BACKEND_MODULES]
