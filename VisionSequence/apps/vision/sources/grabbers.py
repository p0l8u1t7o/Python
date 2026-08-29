from __future__ import annotations

import glob
import os
import threading
import time
from typing import Any

import cv2
import numpy as np

from apps.core.errors import ValidationError

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


def _read(path: str) -> np.ndarray | None:
    # imdecode 走 numpy 讀檔，避免 Windows 中文路徑讓 imread 靜默回 None。
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_UNCHANGED if path.lower().endswith((".tif", ".tiff")) else cv2.IMREAD_COLOR)


class Grabber:
    kind = ""

    def __init__(self, config: dict[str, Any], *, source_id: int = 0, name: str = "") -> None:
        self.config = config
        self.source_id = source_id
        self.name = name
        self.frames = 0
        self.last_error = ""
        self._lock = threading.Lock()

    def grab(self) -> np.ndarray | None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def info(self) -> dict[str, Any]:
        return {"kind": self.kind, "frames": self.frames, "last_error": self.last_error}


class FolderGrabber(Grabber):
    kind = "folder"

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.path = str(config.get("path") or "")
        if not self.path or not os.path.isdir(self.path):
            raise ValidationError(f"資料夾不存在：{self.path}", code="source_path_missing")
        self.loop = bool(config.get("loop", True))
        self.pattern = str(config.get("pattern") or "")
        self.index = 0
        self.files = self._scan()

    def _scan(self) -> list[str]:
        if self.pattern:
            files = glob.glob(os.path.join(self.path, self.pattern))
        else:
            files = [os.path.join(self.path, f) for f in os.listdir(self.path)]
        files = [f for f in files if f.lower().endswith(IMAGE_EXTS) and os.path.isfile(f)]
        sort = str(self.config.get("sort") or "name")
        if sort == "mtime":
            files.sort(key=os.path.getmtime)
        else:
            files.sort()
        return files

    def grab(self) -> np.ndarray | None:
        with self._lock:
            if not self.files:
                self.files = self._scan()
                if not self.files:
                    self.last_error = "資料夾內沒有影像"
                    return None
            if self.index >= len(self.files):
                if not self.loop:
                    self.last_error = "已讀到資料夾結尾"
                    return None
                self.index = 0
                self.files = self._scan()
            path = self.files[self.index]
            self.index += 1
            image = _read(path)
            if image is None:
                self.last_error = f"讀取失敗：{path}"
                return None
            self.frames += 1
            self.last_path = path
            return image

    def info(self) -> dict[str, Any]:
        return {**super().info(), "count": len(self.files), "index": self.index, "current": getattr(self, "last_path", "")}


class FileGrabber(Grabber):
    kind = "file"

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.path = str(config.get("path") or "")
        if not os.path.isfile(self.path):
            raise ValidationError(f"檔案不存在：{self.path}", code="source_path_missing")
        self._image = _read(self.path)
        self._mtime = os.path.getmtime(self.path)

    def grab(self) -> np.ndarray | None:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self.last_error = "檔案已消失"
            return None
        if mtime != self._mtime:
            self._image = _read(self.path)
            self._mtime = mtime
        self.frames += 1
        return None if self._image is None else self._image.copy()


class UsbGrabber(Grabber):
    kind = "usb"

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        index = int(config.get("index", 0))
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(index, backend)
        if not self.cap.isOpened():
            raise ValidationError(f"無法開啟相機 index={index}", code="camera_open_failed")
        if config.get("width"):
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(config["width"]))
        if config.get("height"):
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config["height"]))
        if config.get("fps"):
            self.cap.set(cv2.CAP_PROP_FPS, float(config["fps"]))
        # 緩衝區設 1：自動化要的是「現在這一張」，不是排隊的舊畫面。
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def grab(self) -> np.ndarray | None:
        with self._lock:
            # 先丟掉緩衝的一張，再讀最新。
            self.cap.grab()
            ok, frame = self.cap.read()
        if not ok:
            self.last_error = "read() 失敗"
            return None
        self.frames += 1
        return frame

    def close(self) -> None:
        self.cap.release()

    def info(self) -> dict[str, Any]:
        return {
            **super().info(),
            "width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(self.cap.get(cv2.CAP_PROP_FPS)),
        }


class SyntheticGrabber(Grabber):
    """合成測試影像：零件輪廓、圓孔、條碼狀線條與雜訊，每張略有位移／旋轉，
    讓沒有相機的機器也能完整走一遍定位→量測→判定。"""

    kind = "synthetic"

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self.w = int(config.get("width", 1280))
        self.h = int(config.get("height", 960))
        self.pattern = str(config.get("pattern") or "parts")
        self.rng = np.random.default_rng(int(config.get("seed", 0)) or None)
        self.defect_rate = float(config.get("defect_rate", 0.3))

    def grab(self) -> np.ndarray | None:
        w, h = self.w, self.h
        img = np.full((h, w, 3), 70, dtype=np.uint8)
        noise = self.rng.normal(0, 6, (h, w, 1)).astype(np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        t = self.frames
        dx = float(self.rng.uniform(-40, 40))
        dy = float(self.rng.uniform(-30, 30))
        angle = float(self.rng.uniform(-8, 8))
        cx, cy = w / 2 + dx, h / 2 + dy
        defect = self.rng.random() < self.defect_rate
        if self.pattern in ("parts", "plate"):
            rect = ((cx, cy), (w * 0.5, h * 0.4), angle)
            box = np.round(cv2.boxPoints(rect)).astype(np.int32)
            cv2.fillPoly(img, [box], (200, 200, 205))
            m = cv2.getRotationMatrix2D((cx, cy), -angle, 1.0)

            def at(ox: float, oy: float) -> tuple[int, int]:
                p = m @ np.array([cx + ox, cy + oy, 1.0])
                return int(round(p[0])), int(round(p[1]))

            holes = [(-w * 0.18, -h * 0.12), (w * 0.18, -h * 0.12), (-w * 0.18, h * 0.12), (w * 0.18, h * 0.12)]
            for i, (ox, oy) in enumerate(holes):
                if defect and i == 2:
                    continue  # 缺一個孔 → NG
                cv2.circle(img, at(ox, oy), int(min(w, h) * 0.035), (40, 40, 45), -1)
            cv2.circle(img, at(0, 0), int(min(w, h) * 0.08), (40, 40, 45), -1)
            # 條碼狀圖案（放在板子上緣，避開孔位；示範流程靠圓形度過濾它）
            x0, y0 = -w * 0.08, -h * 0.17
            for i in range(24):
                bw = 3 + (i * 7) % 5
                p1 = at(x0 + i * 9, y0)
                p2 = at(x0 + i * 9 + bw, y0 + h * 0.06)
                cv2.rectangle(img, p1, p2, (20, 20, 20), -1)
            if defect and self.rng.random() < 0.5:
                # 刮痕
                p1 = at(self.rng.uniform(-w * 0.2, w * 0.2), self.rng.uniform(-h * 0.15, h * 0.15))
                p2 = (p1[0] + int(self.rng.uniform(40, 160)), p1[1] + int(self.rng.uniform(-30, 30)))
                cv2.line(img, p1, p2, (90, 90, 95), 3)
            cv2.putText(img, f"LOT {t:05d}", at(-w * 0.06, h * 0.16), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2)
        elif self.pattern == "gradient":
            xs = np.linspace(0, 255, w, dtype=np.uint8)
            img[:] = np.stack([xs] * 3, axis=-1)[None, :, :]
        else:
            cv2.putText(img, f"frame {t}", (40, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3)
        self.frames += 1
        self.last_meta = {"dx": dx, "dy": dy, "angle": angle, "defect": defect}
        return img

    def info(self) -> dict[str, Any]:
        return {**super().info(), "width": self.w, "height": self.h, "pattern": self.pattern, "last": getattr(self, "last_meta", {})}


class UploadGrabber(Grabber):
    """API 送進來的影像（POST /vision/sources/{id}/push）；grab 回最近一張。"""

    kind = "upload"

    def __init__(self, config, **kw) -> None:
        super().__init__(config, **kw)
        self._image: np.ndarray | None = None
        self._ts = 0.0
        self.max_age = float(config.get("max_age_s", 0) or 0)

    def push(self, image: np.ndarray) -> None:
        with self._lock:
            self._image = image
            self._ts = time.time()

    def grab(self) -> np.ndarray | None:
        with self._lock:
            if self._image is None:
                self.last_error = "尚未收到影像"
                return None
            if self.max_age and time.time() - self._ts > self.max_age:
                self.last_error = "最近一張影像已過期"
                return None
            self.frames += 1
            return self._image

    def info(self) -> dict[str, Any]:
        return {**super().info(), "has_image": self._image is not None, "received_at": self._ts}
