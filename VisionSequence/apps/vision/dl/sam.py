"""SAM 點擊智慧標記：在標記編輯器點一下物件 → 回傳 polygon 輪廓建議。

- 依賴 ultralytics（torch）＝可選安裝、延後 import（與 yolo_seg 相同慣例）；缺件回 TrainError 提示 pip 指令。
- 權重預設 mobile_sam.pt（約 40MB），第一次使用經 yolo.resolve_model 自動下載到 ASSET_DIR/dl/weights；
  想要更準可在請求帶 model="sam2.1_b.pt" 等官方名稱或本機 .pt 路徑。
- 模型 session 以路徑快取在模組層（載入秒級、不重複載）；SAM predictor 有內部狀態，推論用鎖序列化。
"""

from __future__ import annotations

import threading
from typing import Any

import cv2
import numpy as np

from apps.vision.dl.base import TrainError
from apps.vision.dl.yolo import _INSTALL_HINT, resolve_model

DEFAULT_MODEL = "mobile_sam.pt"

_sessions: dict[str, Any] = {}
_lock = threading.Lock()


def _import_sam():
    try:
        import os

        os.environ.setdefault("YOLO_OFFLINE", "1")
        from ultralytics import SAM  # noqa: PLC0415

        return SAM
    except ImportError:
        raise TrainError(f"未安裝 ultralytics／torch，無法使用智慧選取。{_INSTALL_HINT}") from None


def _session(model_name: str, log_fn=None):
    SAM = _import_sam()  # 先驗依賴：缺 ultralytics 要立刻提示，不能先跑去下載權重
    path = resolve_model(model_name or DEFAULT_MODEL, log_fn)
    with _lock:
        model = _sessions.get(path)
        if model is None:
            model = SAM(path)
            _sessions.clear()  # 只留一份（換權重時釋放舊模型記憶體）
            _sessions[path] = model
    return model


def _mask_to_polygons(poly_list, width: int, height: int, max_points: int = 48) -> list[list[list[float]]]:
    """ultralytics 的 masks.xy（像素座標 polygon）→ 簡化＋0~1 正規化；太小或退化的略過。"""
    out = []
    min_area = max(16.0, width * height * 1e-4)
    for poly in poly_list or []:
        pts = np.asarray(poly, dtype=np.float32)
        if len(pts) < 3 or cv2.contourArea(pts) < min_area:
            continue
        # approxPolyDP 逐步放寬 epsilon 直到點數 ≤ max_points（保形又不巨量）
        eps = 0.0025 * cv2.arcLength(pts, True)
        for _ in range(6):
            approx = cv2.approxPolyDP(pts, eps, True).reshape(-1, 2)
            if len(approx) <= max_points:
                break
            eps *= 1.8
        if len(approx) < 3:
            continue
        out.append([[float(np.clip(x / width, 0, 1)), float(np.clip(y / height, 0, 1))] for x, y in approx])
    return out


def suggest_shapes(image: np.ndarray, points_norm: list[list[float]], labels: list[int] | None = None,
                   model_name: str = "", device: str = "cpu", log_fn=None) -> list[dict[str, Any]]:
    """點擊提示 → SAM 分割 → shapes（kind=polygon、0~1 座標、label 留空由前端掛目前類別）。

    points_norm：0~1 正規化的點擊座標；labels：1=前景、0=背景（預設全 1）。
    """
    h, w = image.shape[:2]
    pts = [[int(round(min(max(x, 0.0), 1.0) * (w - 1))), int(round(min(max(y, 0.0), 1.0) * (h - 1)))] for x, y in points_norm]
    if not pts:
        raise TrainError("至少要一個點擊座標")
    lbl = [int(v) for v in (labels or [1] * len(pts))][: len(pts)]
    model = _session(model_name, log_fn)
    with _lock:  # SAM predictor 有內部狀態，推論不重入
        results = model(image, points=[pts], labels=[lbl], device=device, verbose=False)
    shapes: list[dict[str, Any]] = []
    for r in results:
        masks = getattr(r, "masks", None)
        if masks is None:
            continue
        for poly in _mask_to_polygons(getattr(masks, "xy", None), w, h):
            shapes.append({"kind": "polygon", "label": "", "points": poly})
    return shapes
