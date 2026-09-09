"""模擬相機：合成影像（靜態底圖＋移動方塊），給測試與沒有相機的示範用。支援硬體 ROI、軟體觸發、曝光影響亮度。

`fake:0`～`fake:3` 是不同解析度的機種（含 500 萬與 2000 萬畫素），可用來量測大影格的傳輸效能。
底圖只在參數變動時重算一次，每次取像＝從緩衝池借一張、複製底圖、畫上方塊——與真實相機交出 DMA 緩衝的成本相當。
"""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from vscapture.cameras.base import Camera, CameraError, CameraParamError, DeviceDescription, DeviceInfo, ParamSpec, align
from vscapture.config import Roi
from vscapture.frames import BufferPool

#: 機種（感測器尺寸）：0／1 是小圖（預設與測試用），2／3 給大影格效能驗證。
FAKE_MODELS = [(640, 480), (640, 480), (2448, 2048), (5472, 3648)]


def _model_label(i: int) -> str:
    w, h = FAKE_MODELS[i]
    mp = round(w * h / 1e6)  # 百萬畫素（業界的「N 萬畫素」＝ mp × 100）
    return f"模擬相機 {i}（{w}×{h}）" if mp < 2 else f"模擬相機 {i}（{w}×{h}，{mp * 100} 萬畫素）"


class FakeCamera(Camera):
    backend = "fake"
    label = "模擬相機"

    def __init__(self) -> None:
        self._open = False
        self._running = False
        self._sensor = FAKE_MODELS[0]
        self._template: np.ndarray | None = None
        # 3 張：已發布的最新影格、推送中的、正在畫的——少於 3 會每張都重新配置（20MP 一次 17 ms）
        self._pool = BufferPool(max_buffers=3, max_bytes=384 << 20)
        self._roi = Roi()
        self._exposure = 5000.0
        self._gain = 0.0
        self._fps = 30.0
        self._pixel_format = "BGR8"
        self._trigger = "freerun"
        self._trigger_source = "Software"
        self._trigger_delay_us = 0.0
        self.output_levels = {"Line1": False, "Line2": False}
        self._user_sets: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self._last = 0.0
        self._trigger_event = threading.Event()
        self._serial = ""

    @classmethod
    def enumerate(cls) -> list[DeviceInfo]:
        return [DeviceInfo("fake", f"fake:{i}", _model_label(i), model=f"FakeCam{FAKE_MODELS[i][0]}", serial=f"FAKE{i:04d}") for i in range(len(FAKE_MODELS))]

    def open(self, device_id: str) -> DeviceDescription:
        if not device_id.startswith("fake:"):
            raise CameraError(f"找不到模擬相機 {device_id}")
        try:
            index = int(device_id.split(":")[1])
        except (IndexError, ValueError):
            raise CameraError(f"找不到模擬相機 {device_id}") from None
        if not 0 <= index < len(FAKE_MODELS):
            raise CameraError(f"找不到模擬相機 {device_id}")
        self._sensor = FAKE_MODELS[index]
        self._serial = f"FAKE{index:04d}"
        self._template = None
        self._open = True
        return self.describe()

    def close(self) -> None:
        self._running = False
        self._open = False
        self._template = None
        self._pool.clear()

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

    def _build_template(self, roi: Roi) -> np.ndarray:
        """靜態底圖（斜紋），只在解析度／ROI／曝光／增益／格式變動時重算。以廣播產生，2000 萬畫素也只配置一張。"""
        base = 40.0 + 180.0 * min(1.0, self._exposure / 20000.0) * (1.0 + self._gain / 24.0)
        xs = np.arange(roi.x, roi.x + roi.w, dtype=np.int32)[None, :]
        ys = np.arange(roi.y, roi.y + roi.h, dtype=np.int32)[:, None]
        gray = np.clip(base * 0.3 + ((xs * 13 + ys * 7) % 17) * 2.0, 0, 255).astype(np.uint8)
        if self._pixel_format != "BGR8":
            return gray
        img = np.empty((roi.h, roi.w, 3), np.uint8)
        img[:, :, 0] = gray
        np.copyto(img[:, :, 1], np.clip(gray.astype(np.int16) - 20, 0, 255).astype(np.uint8))
        np.copyto(img[:, :, 2], np.clip(gray.astype(np.int16) + 10, 0, 255).astype(np.uint8))
        return img

    def _render(self) -> tuple[np.ndarray, tuple[int, int]]:
        self._seq += 1
        sw, sh = self._sensor
        roi = self._roi if not self._roi.is_full() else Roi(0, 0, sw, sh)
        tmpl = self._template
        if tmpl is None or tmpl.shape[:2] != (roi.h, roi.w) or (tmpl.ndim == 3) != (self._pixel_format == "BGR8"):
            tmpl = self._template = self._build_template(roi)
        out = self._pool.take(tmpl.shape, tmpl.dtype)
        np.copyto(out, tmpl)
        # 移動方塊：只寫一小塊，成本與影格大小無關
        t, side = self._seq, max(24, min(roi.w, roi.h) // 12)
        cx = (t * 7) % max(1, roi.w - side)
        cy = (t * 3) % max(1, roi.h - side)
        level = int(min(255, 60 + 195 * min(1.0, self._exposure / 20000.0) * (1.0 + self._gain / 24.0)))
        out[cy : cy + side, cx : cx + side] = level
        return out, (roi.x, roi.y)

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
            "fps": ParamSpec("fps", "float", self._fps, 1.0, 240.0, 1.0, unit="fps", standard=True, label="影格率"),
            "pixel_format": ParamSpec("pixel_format", "enum", self._pixel_format, choices=["Mono8", "BGR8"], standard=True, label="像素格式"),
            "width": ParamSpec("width", "int", self._roi.w or sw, 8, sw, 8, standard=True, label="寬"),
            "height": ParamSpec("height", "int", self._roi.h or sh, 8, sh, 8, standard=True, label="高"),
            "offset_x": ParamSpec("offset_x", "int", self._roi.x, 0, sw - 8, 8, standard=True, label="X 位移"),
            "offset_y": ParamSpec("offset_y", "int", self._roi.y, 0, sh - 8, 8, standard=True, label="Y 位移"),
            "trigger_mode": ParamSpec("trigger_mode", "enum", self._trigger, choices=["freerun", "software"], standard=True, label="觸發模式"),
            "trigger_source": ParamSpec("trigger_source", "enum", self._trigger_source, choices=["Line1", "Line2", "Software"], standard=True, label="觸發來源"),
            "trigger_delay_us": ParamSpec("trigger_delay_us", "float", self._trigger_delay_us, 0.0, 1000000.0, 1.0, unit="µs", standard=True, label="觸發延遲"),
            "Pattern": ParamSpec("Pattern", "enum", "moving_square", choices=["moving_square"], label="Pattern"),
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
                elif key == "trigger_source":
                    if value not in spec.choices:
                        raise ValueError("不支援的觸發來源")
                    self._trigger_source = str(value)
                    applied[key] = self._trigger_source
                elif key == "trigger_delay_us":
                    self._trigger_delay_us = float(max(spec.min, min(spec.max, float(value))))
                    applied[key] = self._trigger_delay_us
                elif key in ("width", "height", "offset_x", "offset_y"):
                    applied[key] = int(value)
                else:
                    applied[key] = value
            except (TypeError, ValueError) as exc:
                errors[key] = str(exc)
        if any(k in applied for k in ("exposure_us", "gain_db", "pixel_format")):
            self._template = None
        if any(k in applied for k in ("width", "height", "offset_x", "offset_y")):
            sw, sh = self._sensor
            roi = Roi(applied.get("offset_x", self._roi.x), applied.get("offset_y", self._roi.y), applied.get("width", self._roi.w or sw), applied.get("height", self._roi.h or sh))
            _, roi = self.apply_roi(roi, True)
            applied.update({"offset_x": roi.x, "offset_y": roi.y, "width": roi.w or sw, "height": roi.h or sh})
        if errors:
            raise CameraParamError(errors)
        return applied

    def apply_roi(self, roi: Roi, hardware: bool) -> tuple[bool, Roi]:
        self._template = None
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
        return DeviceDescription("fake", "FakeCam", self._serial, self._sensor[0], self._sensor[1], ["Mono8", "BGR8"], True, False, True, True, ["Line1", "Line2"])

    def set_output(self, line: str, level: bool) -> None:
        if line not in self.output_levels:
            raise CameraError(f"unknown output line '{line}'")
        self.output_levels[line] = bool(level)

    def _user_set_values(self) -> dict[str, Any]:
        return {key: spec.value for key, spec in self.get_params().items() if spec.writable and key != "Pattern"}

    def save_user_set(self, name: str) -> None:
        key = str(name or "").strip()
        if not key:
            raise CameraError("user set name is required")
        self._user_sets[key] = dict(self._user_set_values())

    def load_user_set(self, name: str) -> None:
        key = str(name or "").strip()
        if not key:
            raise CameraError("user set name is required")
        values = self._user_sets.get(key)
        if values is None:
            raise CameraError(f"user set '{key}' does not exist")
        self.set_params(dict(values))
