"""SAM／SAM2 智慧標記：點擊（正／負點）、框選提示 → polygon 輪廓建議；沒有提示 → 全圖自動分割提案。

- 依賴 ultralytics（torch）＝可選安裝、延後 import（與 yolo trainer 相同慣例）；缺件回 TrainError 提示安裝指令。
- 權重預設 VISION_SAM_MODEL（sam2.1_t.pt，約 150MB；SAM2 比 mobile_sam 準且支援多物件），第一次使用經
  yolo.resolve_model 自動下載到 ASSET_DIR/dl/weights；下載失敗自動退回 mobile_sam.pt（40MB）並記 log。
  請求可帶 model="sam2.1_s.pt"／"mobile_sam.pt" 等官方名稱或本機 .pt 路徑。
- 模型 session 以路徑快取在模組層（載入秒級、不重複載）；SAM predictor 有內部狀態，推論用鎖序列化。
- 裝置：有 CUDA 用 GPU（sam2.1_t 點擊約 60ms），CPU 也能用（秒級）。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import cv2
import numpy as np

from apps.vision.dl.base import TrainError
from apps.vision.dl.yolo import _INSTALL_HINT, resolve_model

log = logging.getLogger(__name__)

FALLBACK_MODEL = "mobile_sam.pt"

_sessions: dict[str, Any] = {}
_lock = threading.Lock()


def default_model() -> str:
    try:
        from django.conf import settings  # noqa: PLC0415

        return str(settings.VISION.get("SAM_MODEL") or "sam2.1_t.pt")
    except Exception:  # noqa: BLE001
        return "sam2.1_t.pt"


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
    name = model_name or default_model()
    try:
        path = resolve_model(name, log_fn)
    except TrainError as exc:
        if name == FALLBACK_MODEL:
            raise
        log.warning("SAM 權重 %s 無法取得（%s），退回 %s", name, exc, FALLBACK_MODEL)
        if log_fn:
            log_fn(f"{name} 無法取得，改用 {FALLBACK_MODEL}")
        path = resolve_model(FALLBACK_MODEL, log_fn)
    with _lock:
        model = _sessions.get(path)
        if model is None:
            model = SAM(path)
            _sessions.clear()  # 只留一份（換權重時釋放舊模型記憶體）
            _sessions[path] = model
    return model


def loaded_model() -> str:
    with _lock:
        return next(iter(_sessions), "")


def _mask_to_polygons(poly_list, width: int, height: int, max_points: int = 48, min_area: float | None = None) -> list[list[list[float]]]:
    """ultralytics 的 masks.xy（像素座標 polygon）→ 簡化＋0~1 正規化；太小或退化的略過。"""
    out = []
    if min_area is None:
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


def _to_px(points_norm: list[list[float]], w: int, h: int) -> list[list[int]]:
    return [[int(round(min(max(float(x), 0.0), 1.0) * (w - 1))), int(round(min(max(float(y), 0.0), 1.0) * (h - 1)))] for x, y in points_norm]


def suggest_shapes(image: np.ndarray, points_norm: list[list[float]] | None = None, labels: list[int] | None = None,
                   model_name: str = "", device: str = "cpu", log_fn=None, boxes_norm: list[list[float]] | None = None) -> list[dict[str, Any]]:
    """提示 → SAM 分割 → shapes（kind=polygon、0~1 座標、label 留空由前端掛目前類別）。

    points_norm：0~1 正規化的點擊座標（同一個物件的正／負點）；labels：1=前景、0=背景（預設全 1）。
    boxes_norm：0~1 的 [x0, y0, x1, y1] 框（每個框一個物件）；有框時以框為主、點作為該框的補充提示。
    """
    h, w = image.shape[:2]
    pts = _to_px(points_norm or [], w, h)
    boxes = [[*_to_px([[b[0], b[1]]], w, h)[0], *_to_px([[b[2], b[3]]], w, h)[0]] for b in (boxes_norm or []) if len(b) >= 4]
    boxes = [b for b in boxes if b[2] > b[0] + 1 and b[3] > b[1] + 1]
    if not pts and not boxes:
        raise TrainError("至少要一個點擊座標或一個框")
    model = _session(model_name, log_fn)
    kw: dict[str, Any] = {"device": device, "verbose": False}
    if boxes:
        kw["bboxes"] = boxes
        if pts and len(boxes) == 1:
            kw["points"] = [pts]
            kw["labels"] = [[int(v) for v in (labels or [1] * len(pts))][: len(pts)]]
    else:
        kw["points"] = [pts]
        kw["labels"] = [[int(v) for v in (labels or [1] * len(pts))][: len(pts)]]
    with _lock:  # SAM predictor 有內部狀態，推論不重入
        results = model(image, **kw)
    shapes: list[dict[str, Any]] = []
    for r in results:
        masks = getattr(r, "masks", None)
        if masks is None:
            continue
        for poly in _mask_to_polygons(getattr(masks, "xy", None), w, h):
            shapes.append({"kind": "polygon", "label": "", "points": poly})
    return shapes


def suggest_everything(image: np.ndarray, model_name: str = "", device: str = "cpu", *, max_masks: int = 30,
                       min_area_ratio: float = 0.002, log_fn=None) -> list[dict[str, Any]]:
    """沒有提示的全圖自動分割（SAM「everything」）→ shapes（面積大到小、最多 max_masks 個；label 留空）。
    用於 shapes 專案還沒有訓練權重時的自動標記提案；提案一律掛第一個類別，交給使用者確認／改類。"""
    h, w = image.shape[:2]
    model = _session(model_name, log_fn)
    with _lock:
        results = model(image, device=device, verbose=False)
    polys: list[list[list[float]]] = []
    for r in results:
        masks = getattr(r, "masks", None)
        if masks is None:
            continue
        polys += _mask_to_polygons(getattr(masks, "xy", None), w, h, min_area=max(16.0, w * h * min_area_ratio))
    # 面積大到小；蓋住整張圖的背景遮罩（> 90%）略過
    scored = []
    for poly in polys:
        area = cv2.contourArea(np.asarray([[x * w, y * h] for x, y in poly], dtype=np.float32))
        if area >= 0.9 * w * h:
            continue
        scored.append((area, poly))
    scored.sort(key=lambda t: -t[0])
    return [{"kind": "polygon", "label": "", "points": poly} for _, poly in scored[:max_masks]]
