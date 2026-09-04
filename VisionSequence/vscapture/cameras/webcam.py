"""網路攝影機／USB 相機（DirectShow／UVC）。裝置以索引指定（`index:N`），無硬體 ROI、無硬體觸發。"""

from __future__ import annotations

import math
import os
import time
from typing import Any

import numpy as np

from vscapture.cameras.base import Camera, CameraError, CameraParamError, DeviceDescription, DeviceInfo, ParamSpec

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

MAX_PROBE = 6


def _backend() -> int:
    return cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY


def _device_names() -> list[str]:
    """DirectShow 裝置名稱（有裝 pygrabber 才有；沒有就用索引）。"""
    try:
        from pygrabber.dshow_graph import FilterGraph  # type: ignore

        return list(FilterGraph().get_input_devices())
    except Exception:  # noqa: BLE001
        return []


class WebcamCamera(Camera):
    backend = "webcam"
    label = "網路攝影機／USB 相機"
    EXTRA_PROPS = {
        "brightness": ("CAP_PROP_BRIGHTNESS", "亮度"), "contrast": ("CAP_PROP_CONTRAST", "對比"), "saturation": ("CAP_PROP_SATURATION", "飽和度"),
        "sharpness": ("CAP_PROP_SHARPNESS", "銳利度"), "auto_wb": ("CAP_PROP_AUTO_WB", "自動白平衡"), "focus": ("CAP_PROP_FOCUS", "對焦"),
    }

    def __init__(self) -> None:
        self.cap: Any = None
        self._index = -1
        self._running = False
        self._mono = False
        self._fps = 0.0
        self._width = 0
        self._height = 0
        self._failures = 0

    @classmethod
    def available(cls) -> tuple[bool, str]:
        return (True, "") if cv2 is not None else (False, "尚未安裝影像函式庫（opencv-python）")

    @classmethod
    def enumerate(cls) -> list[DeviceInfo]:
        if cv2 is None:
            return []
        names = _device_names()
        out: list[DeviceInfo] = []
        for i in range(MAX_PROBE):
            cap = cv2.VideoCapture(i, _backend())
            try:
                if not cap.isOpened():
                    if i >= len(names):
                        break
                    continue
                w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            finally:
                cap.release()
            name = names[i] if i < len(names) else f"網路攝影機 {i}"
            out.append(DeviceInfo("webcam", f"index:{i}", f"{name}（{w}×{h}）", model=name, extra={"width": w, "height": h}))
        return out

    def open(self, device_id: str) -> DeviceDescription:
        if cv2 is None:
            raise CameraError("尚未安裝影像函式庫")
        try:
            self._index = int(str(device_id).split(":")[-1])
        except ValueError:
            raise CameraError(f"裝置識別無效：{device_id}") from None
        cap = cv2.VideoCapture(self._index, _backend())
        if not cap.isOpened():
            raise CameraError(f"無法開啟網路攝影機 {self._index}")
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap = cap
        self._width, self._height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        self._failures = 0
        return self.describe()

    def close(self) -> None:
        self._running = False
        cap, self.cap = self.cap, None
        if cap is not None:
            cap.release()

    def start(self) -> None:
        if self.cap is None:
            raise CameraError("相機尚未開啟")
        self._running = True

    def stop(self) -> None:
        self._running = False

    @property
    def is_open(self) -> bool:
        return self.cap is not None

    @property
    def is_running(self) -> bool:
        return self._running

    def grab_one(self, timeout: float) -> tuple[np.ndarray, tuple[int, int]] | None:
        cap = self.cap
        if cap is None or not self._running:
            return None
        cap.grab()  # 丟掉緩衝的一張，拿現在這張
        ok, frame = cap.read()
        if not ok or frame is None:
            self._failures += 1
            if self._failures >= 30:
                self._failures = 0
                raise CameraError("相機沒有回傳影像（可能已拔除）")
            time.sleep(min(timeout, 0.05))
            return None
        self._failures = 0
        if self._mono and frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return frame, (0, 0)

    def _prop(self, name: str) -> float | None:
        cap = self.cap
        if cap is None or not hasattr(cv2, name):
            return None
        try:
            v = float(cap.get(getattr(cv2, name)))
        except cv2.error:
            return None
        return None if v == -1 else v

    def get_params(self) -> dict[str, ParamSpec]:
        cap = self.cap
        if cap is None:
            return {}
        exposure = self._prop("CAP_PROP_EXPOSURE")
        auto_exp = self._prop("CAP_PROP_AUTO_EXPOSURE")
        exposure_us = (2.0 ** exposure) * 1e6 if exposure is not None and exposure < 0 else (exposure * 1e3 if exposure is not None else None)
        out = {
            "exposure_us": ParamSpec("exposure_us", "float", exposure_us, 100.0, 1_000_000.0, None, unit="µs", standard=True, label="曝光時間（自動曝光關閉時生效）",
                                     writable=exposure is not None),
            "gain_db": ParamSpec("gain_db", "float", self._prop("CAP_PROP_GAIN"), 0.0, 255.0, 1.0, standard=True, label="增益（驅動單位）", writable=self._prop("CAP_PROP_GAIN") is not None),
            "fps": ParamSpec("fps", "float", self._fps, 1.0, 120.0, 1.0, unit="fps", standard=True, label="影格率"),
            "pixel_format": ParamSpec("pixel_format", "enum", "Mono8" if self._mono else "BGR8", choices=["BGR8", "Mono8"], standard=True, label="像素格式"),
            "width": ParamSpec("width", "int", self._width, 160, 4096, 2, standard=True, label="寬"),
            "height": ParamSpec("height", "int", self._height, 120, 3072, 2, standard=True, label="高"),
            "trigger_mode": ParamSpec("trigger_mode", "enum", "freerun", choices=["freerun"], standard=True, label="觸發模式", writable=False),
            "auto_exposure": ParamSpec("auto_exposure", "bool", auto_exp is not None and auto_exp > 0.5, group="進階", label="自動曝光"),
        }
        for key, (prop, label) in self.EXTRA_PROPS.items():
            v = self._prop(prop)
            if v is not None:
                out[key] = ParamSpec(key, "bool" if key == "auto_wb" else "float", bool(v) if key == "auto_wb" else v, group="進階", label=label)
        return out

    def set_params(self, values: dict[str, Any]) -> dict[str, Any]:
        cap = self.cap
        if cap is None:
            raise CameraError("相機尚未開啟")
        applied: dict[str, Any] = {}
        errors: dict[str, str] = {}
        size_changed = False
        for key, value in values.items():
            try:
                if key == "exposure_us":
                    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
                    level = round(math.log2(max(1e-6, float(value) / 1e6)))
                    cap.set(cv2.CAP_PROP_EXPOSURE, level)
                    got = self._prop("CAP_PROP_EXPOSURE")
                    applied[key] = (2.0 ** got) * 1e6 if got is not None else float(value)
                elif key == "auto_exposure":
                    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75 if value else 0.25)
                    applied[key] = bool(value)
                elif key == "gain_db":
                    cap.set(cv2.CAP_PROP_GAIN, float(value))
                    applied[key] = self._prop("CAP_PROP_GAIN") or float(value)
                elif key == "fps":
                    cap.set(cv2.CAP_PROP_FPS, float(value))
                    self._fps = float(cap.get(cv2.CAP_PROP_FPS) or value)
                    applied[key] = self._fps
                elif key == "pixel_format":
                    if value not in ("BGR8", "Mono8"):
                        raise ValueError("只支援 BGR8／Mono8")
                    self._mono = value == "Mono8"
                    applied[key] = value
                elif key in ("width", "height"):
                    setattr(self, f"_{key}", int(value))
                    size_changed = True
                elif key == "trigger_mode":
                    if value != "freerun":
                        raise ValueError("網路攝影機只支援自由取像")
                    applied[key] = "freerun"
                elif key in self.EXTRA_PROPS:
                    prop = getattr(cv2, self.EXTRA_PROPS[key][0])
                    cap.set(prop, float(value) if key != "auto_wb" else (1.0 if value else 0.0))
                    applied[key] = self._prop(self.EXTRA_PROPS[key][0])
                elif key in ("offset_x", "offset_y"):
                    applied[key] = 0
                else:
                    errors[key] = "不支援的參數"
            except (TypeError, ValueError, cv2.error) as exc:
                errors[key] = str(exc)
        if size_changed:
            # 高解析度要先設 MJPG 再設尺寸／fps，否則有些驅動會壓回 640×480
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            self._width, self._height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            applied["width"], applied["height"] = self._width, self._height
        if errors:
            raise CameraParamError(errors)
        return applied

    def describe(self) -> DeviceDescription:
        return DeviceDescription("webcam", f"網路攝影機 {self._index}", str(self._index), self._width, self._height, ["BGR8", "Mono8"], False, False, False, True)
