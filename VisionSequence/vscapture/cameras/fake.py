"""模擬相機：合成影像（移動方塊＋序號＋雜訊），給測試與沒有相機的示範用。支援硬體 ROI、軟體觸發、曝光影響亮度。"""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from vscapture.cameras.base import Camera, CameraError, CameraParamError, DeviceDescription, DeviceInfo, ParamSpec, align
from vscapture.config import Roi


class FakeCamera(Camera):
    backend = "fake"
    label = "模擬相機"

    def __init__(self) -> None:
        self._open = False
        self._running = False
        self._sensor = (640, 480)
        self._roi = Roi()
        self._exposure = 5000.0
        self._gain = 0.0
        self._fps = 30.0
        self._pixel_format = "BGR8"
        self._trigger = "freerun"
        self._seq = 0
        self._last = 0.0
        self._trigger_event = threading.Event()
        self._serial = ""

    @classmethod
    def enumerate(cls) -> list[DeviceInfo]:
        return [DeviceInfo("fake", f"fake:{i}", f"模擬相機 {i}", model="FakeCam", serial=f"FAKE{i:04d}") for i in range(2)]

    def open(self, device_id: str) -> DeviceDescription:
        if not device_id.startswith("fake:"):
            raise CameraError(f"找不到模擬相機 {device_id}")
        self._serial = f"FAKE{int(device_id.split(':')[1]):04d}"
        self._open = True
        return self.describe()

    def close(self) -> None:
        self._running = False
        self._open = False

    def start(self) -> None:
        if not self._open:
            raise CameraError("相機尚未開啟")
        self._running = True
        self._last = 0.0

    def stop(self) -> None:
        self._running = False

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def trigger_mode(self) -> str:
        return self._trigger

    def _render(self) -> tuple[np.ndarray, tuple[int, int]]:
        self._seq += 1
        sw, sh = self._sensor
        roi = self._roi if not self._roi.is_full() else Roi(0, 0, sw, sh)
        h, w = roi.h, roi.w
        yy, xx = np.mgrid[roi.y : roi.y + h, roi.x : roi.x + w]
        base = 40.0 + 180.0 * min(1.0, self._exposure / 20000.0) * (1.0 + self._gain / 24.0)
        t = self._seq
        cx, cy = (t * 7) % max(1, sw), (t * 3) % max(1, sh)
        square = ((np.abs(xx - cx) < 40) & (np.abs(yy - cy) < 40)).astype(np.float32)
        img = np.clip(base * 0.3 + base * 0.7 * square + ((xx * 13 + yy * 7 + t * 5) % 17) * 2.0, 0, 255).astype(np.uint8)
        if self._pixel_format == "BGR8":
            img = np.stack([img, np.clip(img.astype(np.int16) - 20, 0, 255).astype(np.uint8), np.clip(img.astype(np.int16) + 10, 0, 255).astype(np.uint8)], axis=-1)
        return np.ascontiguousarray(img), (roi.x, roi.y)

    def grab_one(self, timeout: float) -> tuple[np.ndarray, tuple[int, int]] | None:
        if not self._running:
            return None
        if self._trigger == "software":
            if not self._trigger_event.wait(timeout):
                return None
            self._trigger_event.clear()
            return self._render()
        period = 1.0 / max(1.0, self._fps)
        now = time.perf_counter()
        wait = self._last + period - now
        if wait > 0:
            if wait > timeout:
                time.sleep(timeout)
                return None
            time.sleep(wait)
        self._last = time.perf_counter()
        return self._render()

    def snap(self, timeout: float) -> tuple[np.ndarray, tuple[int, int]]:
        if self._trigger == "software":
            self._trigger_event.set()
        got = self.grab_one(timeout)
        if got is None:
            raise CameraError("擷取逾時")
        return got

    def get_params(self) -> dict[str, ParamSpec]:
        sw, sh = self._sensor
        return {
            "exposure_us": ParamSpec("exposure_us", "float", self._exposure, 10.0, 100000.0, 1.0, unit="µs", standard=True, label="曝光時間"),
            "gain_db": ParamSpec("gain_db", "float", self._gain, 0.0, 24.0, 0.1, unit="dB", standard=True, label="增益"),
            "fps": ParamSpec("fps", "float", self._fps, 1.0, 120.0, 1.0, unit="fps", standard=True, label="影格率"),
            "pixel_format": ParamSpec("pixel_format", "enum", self._pixel_format, choices=["Mono8", "BGR8"], standard=True, label="像素格式"),
            "width": ParamSpec("width", "int", self._roi.w or sw, 8, sw, 8, standard=True, label="寬"),
            "height": ParamSpec("height", "int", self._roi.h or sh, 8, sh, 8, standard=True, label="高"),
            "offset_x": ParamSpec("offset_x", "int", self._roi.x, 0, sw - 8, 8, standard=True, label="X 位移"),
            "offset_y": ParamSpec("offset_y", "int", self._roi.y, 0, sh - 8, 8, standard=True, label="Y 位移"),
            "trigger_mode": ParamSpec("trigger_mode", "enum", self._trigger, choices=["freerun", "software"], standard=True, label="觸發模式"),
            "Pattern": ParamSpec("Pattern", "enum", "moving_square", choices=["moving_square"], group="進階", label="圖案"),
        }

    def set_params(self, values: dict[str, Any]) -> dict[str, Any]:
        applied: dict[str, Any] = {}
        errors: dict[str, str] = {}
        specs = self.get_params()
        for key, value in values.items():
            spec = specs.get(key)
            if spec is None:
                errors[key] = "不支援的參數"
                continue
            try:
                if key == "exposure_us":
                    self._exposure = float(max(spec.min, min(spec.max, float(value))))
                    applied[key] = self._exposure
                elif key == "gain_db":
                    self._gain = float(max(spec.min, min(spec.max, float(value))))
                    applied[key] = self._gain
                elif key == "fps":
                    self._fps = float(max(spec.min, min(spec.max, float(value))))
                    applied[key] = self._fps
                elif key == "pixel_format":
                    if value not in spec.choices:
                        raise ValueError("不支援的像素格式")
                    self._pixel_format = str(value)
                    applied[key] = self._pixel_format
                elif key == "trigger_mode":
                    if value not in spec.choices:
                        raise ValueError("不支援的觸發模式")
                    self._trigger = str(value)
                    applied[key] = self._trigger
                elif key in ("width", "height", "offset_x", "offset_y"):
                    applied[key] = int(value)
                else:
                    applied[key] = value
            except (TypeError, ValueError) as exc:
                errors[key] = str(exc)
        if any(k in applied for k in ("width", "height", "offset_x", "offset_y")):
            sw, sh = self._sensor
            roi = Roi(applied.get("offset_x", self._roi.x), applied.get("offset_y", self._roi.y), applied.get("width", self._roi.w or sw), applied.get("height", self._roi.h or sh))
            _, roi = self.apply_roi(roi, True)
            applied.update({"offset_x": roi.x, "offset_y": roi.y, "width": roi.w or sw, "height": roi.h or sh})
        if errors:
            raise CameraParamError(errors)
        return applied

    def apply_roi(self, roi: Roi, hardware: bool) -> tuple[bool, Roi]:
        if not hardware:
            self._roi = Roi()
            return False, roi
        sw, sh = self._sensor
        r = roi.clamp(sw, sh)
        if r.is_full():
            self._roi = Roi()
            return True, Roi()
        x = align(r.x, 0, sw - 8, 8)
        y = align(r.y, 0, sh - 8, 8)
        w = align(r.w, 8, sw - x, 8)
        h = align(r.h, 8, sh - y, 8)
        self._roi = Roi(x, y, w, h)
        return True, self._roi

    def describe(self) -> DeviceDescription:
        return DeviceDescription("fake", "FakeCam", self._serial, self._sensor[0], self._sensor[1], ["Mono8", "BGR8"], True, False, True, True)
