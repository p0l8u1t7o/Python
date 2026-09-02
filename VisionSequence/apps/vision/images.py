"""行程內影像快取。

引擎每次 run 產生的影像（來源、各工具輸出）以 numpy 陣列留在記憶體，
前端用 ref（"run_id:node_id:port"）透過 GET /vision/images/{ref} 取縮圖或原圖。
編碼（JPEG/PNG）延後到有人要看時才做，且依請求的最長邊縮小——
產線全速跑時如果沒人開瀏覽器，這裡幾乎不花時間。

淘汰策略：每個 flow 保留最近 N 次 run；全域以 bytes 計 LRU。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np
from django.conf import settings


def _cfg(key: str, default: Any) -> Any:
    return getattr(settings, "VISION", {}).get(key, default)


#: 編碼結果快取筆數：前端每次試跑會對同一張影像抓多次縮圖（節點卡片、檢視器、輸出頁）。
ENCODE_CACHE_SIZE = 64


class ImageStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._images: OrderedDict[str, np.ndarray] = OrderedDict()
        self._bytes = 0
        #: flow_id → [run_id, ...]（舊到新）
        self._runs_by_flow: dict[int, list[str]] = {}
        self._refs_by_run: dict[str, list[str]] = {}
        #: (ref, max_side, fmt, quality) → bytes；同 ref 被 put／淘汰時一併清掉。
        self._encoded: OrderedDict[tuple[str, int | None, str, int], bytes] = OrderedDict()
        self._encoded_by_ref: dict[str, set[tuple[str, int | None, str, int]]] = {}

    # -- 寫入 -------------------------------------------------------------
    def put(self, ref: str, image: np.ndarray, *, flow_id: int, run_id: str, pinned: bool = False) -> dict:
        """pinned=True（暫存上傳、AI 助手影像）：不佔該流程「最近 N 次 run」的名額、不被 run 輪替淘汰，
        只受總容量 LRU 管理——否則工具頁每試跑一次就多一個 run，第 N+1 次就把暫存影像擠掉。"""
        if not isinstance(image, np.ndarray) or image.ndim not in (2, 3):
            raise ValueError("只接受 2D/3D ndarray")
        with self._lock:
            old = self._images.pop(ref, None)
            if old is not None:
                self._bytes -= old.nbytes
                self._forget_encoded_locked(ref)
            self._images[ref] = image
            self._bytes += image.nbytes
            self._refs_by_run.setdefault(run_id, []).append(ref)
            if not pinned:
                runs = self._runs_by_flow.setdefault(flow_id, [])
                if run_id not in runs:
                    runs.append(run_id)
                    keep = int(_cfg("KEEP_RUN_IMAGES", 8))
                    while len(runs) > keep:
                        self._drop_run_locked(runs.pop(0))
            self._enforce_budget_locked()
        h, w = image.shape[:2]
        return {"ref": ref, "width": int(w), "height": int(h), "channels": int(image.shape[2]) if image.ndim == 3 else 1}

    def _forget_encoded_locked(self, ref: str) -> None:
        for key in self._encoded_by_ref.pop(ref, ()):
            self._encoded.pop(key, None)

    def _drop_run_locked(self, run_id: str) -> None:
        for ref in self._refs_by_run.pop(run_id, []):
            img = self._images.pop(ref, None)
            if img is not None:
                self._bytes -= img.nbytes
            self._forget_encoded_locked(ref)

    def _enforce_budget_locked(self) -> None:
        budget = int(_cfg("IMAGE_CACHE_MB", 1024)) * 1024 * 1024
        while self._bytes > budget and self._images:
            ref, img = self._images.popitem(last=False)
            self._bytes -= img.nbytes
            self._forget_encoded_locked(ref)

    def drop_run(self, run_id: str) -> None:
        with self._lock:
            self._drop_run_locked(run_id)
            for runs in self._runs_by_flow.values():
                if run_id in runs:
                    runs.remove(run_id)

    # -- 讀取 -------------------------------------------------------------
    def get(self, ref: str) -> np.ndarray | None:
        with self._lock:
            img = self._images.get(ref)
            if img is not None:
                self._images.move_to_end(ref)
            return img

    def encode(self, ref: str, *, max_side: int | None = None, fmt: str = "jpeg", quality: int = 85) -> bytes | None:
        """編碼（或取快取的）縮圖／原圖。同一 ref、同一尺寸的結果快取 ENCODE_CACHE_SIZE 筆（LRU）。"""
        key = (ref, int(max_side) if max_side else None, fmt, int(quality))
        with self._lock:
            data = self._encoded.get(key)
            if data is not None:
                self._encoded.move_to_end(key)
                img = self._images.get(ref)
                if img is not None:
                    self._images.move_to_end(ref)
                return data
        img = self.get(ref)
        if img is None:
            return None
        data = encode_image(img, max_side=max_side, fmt=fmt, quality=quality)
        with self._lock:
            if ref in self._images:  # 編碼期間可能已被淘汰
                self._encoded[key] = data
                self._encoded_by_ref.setdefault(ref, set()).add(key)
                while len(self._encoded) > ENCODE_CACHE_SIZE:
                    old_key, _ = self._encoded.popitem(last=False)
                    keys = self._encoded_by_ref.get(old_key[0])
                    if keys is not None:
                        keys.discard(old_key)
                        if not keys:
                            self._encoded_by_ref.pop(old_key[0], None)
        return data

    def stats(self) -> dict:
        with self._lock:
            return {"images": len(self._images), "bytes": self._bytes, "runs": sum(len(v) for v in self._runs_by_flow.values()), "encoded": len(self._encoded)}


def encode_image(img: np.ndarray, *, max_side: int | None = None, fmt: str = "jpeg", quality: int = 85) -> bytes:
    if img.dtype != np.uint8:
        # 浮點／16 位元影像正規化到 8 位元顯示。
        lo, hi = float(np.nanmin(img)), float(np.nanmax(img))
        scale = 255.0 / (hi - lo) if hi > lo else 1.0
        img = np.clip((img.astype(np.float32) - lo) * scale, 0, 255).astype(np.uint8)
    if max_side:
        h, w = img.shape[:2]
        longest = max(h, w)
        if longest > max_side:
            f = max_side / longest
            # 縮小超過一半用 INTER_AREA（抗鋸齒）；小幅縮小 INTER_AREA 走一般路徑、比 INTER_LINEAR 慢 3 倍卻看不出差別。
            interp = cv2.INTER_AREA if f <= 0.5 else cv2.INTER_LINEAR
            img = cv2.resize(img, (max(1, int(w * f)), max(1, int(h * f))), interpolation=interp)
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    if fmt == "png":
        ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    else:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise RuntimeError("影像編碼失敗")
    return buf.tobytes()


store = ImageStore()
