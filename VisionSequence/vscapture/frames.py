"""影格與最新影格槽：相機執行緒 publish 一張新陣列（之後不再改動），讀者只讀不改、只在需要時複製一次。

`prepare()` 把影格依通道設定裁 ROI（view）→ 可選單色 → 可選縮小 → 連續化，回傳 FRAME 表頭需要的欄位與陣列。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from vscapture.config import DeliveryConfig, Roi
from vscapture.protocol import DTYPE_CODES, Encoding, FrameFlags


@dataclass(frozen=True)
class Frame:
    seq: int
    ts_ns: int
    image: np.ndarray
    origin: tuple[int, int] = (0, 0)  # 硬體 ROI 時影像左上角在全感測器的位置
    full: tuple[int, int] = (0, 0)  # 全感測器 (w, h)；0 = 與影像同尺寸

    @property
    def channels(self) -> int:
        return 1 if self.image.ndim == 2 else int(self.image.shape[2])

    @property
    def dtype_code(self) -> int:
        return DTYPE_CODES[{"uint8": "u8", "uint16": "u16", "float32": "f32"}[str(self.image.dtype)]]


class FrameSlot:
    """單一最新影格槽：publish 覆蓋、latest 取用、wait_for 等到 seq ≥ min_seq。"""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame: Frame | None = None
        self._seq = 0

    @property
    def seq(self) -> int:
        return self._seq

    def publish(self, image: np.ndarray, ts_ns: int | None = None, origin: tuple[int, int] = (0, 0), full: tuple[int, int] = (0, 0)) -> Frame:
        with self._cond:
            self._seq += 1
            frame = Frame(self._seq, ts_ns if ts_ns is not None else time.time_ns(), image, origin, full)
            self._frame = frame
            self._cond.notify_all()
            return frame

    def latest(self) -> Frame | None:
        with self._cond:
            return self._frame

    def wait_for(self, min_seq: int, timeout: float) -> Frame | None:
        with self._cond:
            if not self._cond.wait_for(lambda: self._frame is not None and self._frame.seq >= min_seq, timeout):
                return None
            return self._frame

    def clear(self) -> None:
        with self._cond:
            self._frame = None


def crop_roi(image: np.ndarray, roi: Roi, origin: tuple[int, int] = (0, 0)) -> tuple[np.ndarray, int, int]:
    """依全感測器座標的 ROI 切 view；回 (view, roi_x, roi_y)（全感測器座標）。ROI 超界自動夾。"""
    h, w = image.shape[:2]
    ox, oy = origin
    if roi.is_full():
        return image, ox, oy
    x0 = max(0, min(roi.x - ox, w - 1))
    y0 = max(0, min(roi.y - oy, h - 1))
    x1 = max(x0 + 1, min(roi.x - ox + roi.w, w))
    y1 = max(y0 + 1, min(roi.y - oy + roi.h, h))
    return image[y0:y1, x0:x1], ox + x0, oy + y0


def prepare(frame: Frame, roi: Roi, delivery: DeliveryConfig, *, force_raw: bool = False) -> tuple[dict[str, Any], np.ndarray]:
    """回 (表頭欄位, 連續陣列)。表頭欄位：width, height, channels, dtype, roi_x, roi_y, full_w, full_h, encoding, flags。"""
    view, rx, ry = crop_roi(frame.image, roi, frame.origin)
    out = view
    if delivery.mono and out.ndim == 3:
        import cv2

        out = cv2.cvtColor(np.ascontiguousarray(out), cv2.COLOR_BGR2GRAY if out.shape[2] == 3 else cv2.COLOR_BGRA2GRAY)
    if delivery.downscale > 1:
        import cv2

        h, w = out.shape[:2]
        out = cv2.resize(np.ascontiguousarray(out), (max(1, w // delivery.downscale), max(1, h // delivery.downscale)), interpolation=cv2.INTER_AREA)
    out = np.ascontiguousarray(out)
    full_w, full_h = frame.full if frame.full != (0, 0) else (frame.image.shape[1] + frame.origin[0], frame.image.shape[0] + frame.origin[1])
    channels = 1 if out.ndim == 2 else int(out.shape[2])
    enc = Encoding.RAW if force_raw else {"raw": Encoding.RAW, "lz4": Encoding.LZ4, "jpeg": Encoding.JPEG}[delivery.encoding]
    if enc == Encoding.JPEG and out.dtype != np.uint8:
        enc = Encoding.RAW
    if enc == Encoding.LZ4:
        from vscapture.protocol import lz4_available

        if not lz4_available():
            enc = Encoding.RAW
    flags = FrameFlags.CROPPED if (rx or ry or out.shape[1] != full_w or out.shape[0] != full_h) else 0
    fields = {
        "width": int(out.shape[1]), "height": int(out.shape[0]), "channels": channels, "dtype": Frame(0, 0, out).dtype_code,
        "roi_x": int(rx), "roi_y": int(ry), "full_w": int(full_w), "full_h": int(full_h), "encoding": int(enc), "flags": int(flags),
    }
    return fields, out


def encode(image: np.ndarray, encoding: int, jpeg_quality: int = 90) -> bytes:
    """連續陣列 → payload bytes（raw 直接 tobytes；lz4 區塊壓縮；jpeg 只給 u8）。"""
    image = np.ascontiguousarray(image)
    if encoding == Encoding.LZ4:
        from vscapture.protocol import compress_lz4

        return compress_lz4(image.data.cast("B"))
    if encoding == Encoding.JPEG:
        import cv2

        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)])
        if not ok:
            raise ValueError("JPEG 編碼失敗")
        return buf.tobytes()
    return image.tobytes()


def to_display(image: np.ndarray, max_w: int, max_h: int) -> np.ndarray:
    """預覽用縮小（u16／f32 先正規化到 u8）；縮小超過 2 倍用 INTER_AREA。"""
    import cv2

    img = image
    if img.dtype != np.uint8:
        x = img.astype(np.float32)
        lo, hi = float(np.nanmin(x)), float(np.nanmax(x))
        img = np.clip((x - lo) * (255.0 / (hi - lo) if hi > lo else 1.0), 0, 255).astype(np.uint8)
    h, w = img.shape[:2]
    scale = min(1.0, max_w / max(1, w), max_h / max(1, h))
    if scale < 1.0:
        img = cv2.resize(np.ascontiguousarray(img), (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA if scale <= 0.5 else cv2.INTER_LINEAR)
    return np.ascontiguousarray(img)
