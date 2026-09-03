"""ultralytics 模型的行程內快取與推論（yolo_* 工具、SAM 智慧標記共用）。

- 模型物件依「解析後的檔案路徑」快取在模組層（載入秒級、GPU 記憶體不重複）；ultralytics 的 predictor
  有內部狀態，同一個模型的推論用鎖序列化（不同模型可並行）。
- 官方名稱（yolo11n.pt、yolo11n-seg.pt…）第一次使用經 yolo.resolve_model 下載到 ASSET_DIR/dl/weights。
- 依賴（torch／ultralytics）延後 import：沒裝時工具回 ToolError，平台照常啟動。
- 裝置：auto＝有 CUDA 就用 GPU；指定 cuda 但沒有時退回 CPU 並在 note 說明。
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Any

import numpy as np

from apps.vision.dl.yolo import _INSTALL_HINT, resolve_model

MAX_MODELS = 6
#: 工具目錄用：官方底模名稱建議（每任務一個小模型）。
DEFAULT_WEIGHTS = {"detect": "yolo11n.pt", "segment": "yolo11n-seg.pt", "classify": "yolo11n-cls.pt", "pose": "yolo11n-pose.pt", "obb": "yolo11n-obb.pt"}


class ModelUnavailable(Exception):
    """可預期的載入失敗（缺依賴、找不到檔、任務不符）；工具翻成 ToolError。"""


_models: "OrderedDict[str, Any]" = OrderedDict()
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()
_cuda: bool | None = None


def cuda_available() -> bool:
    global _cuda
    if _cuda is None:
        try:
            import torch  # noqa: PLC0415

            _cuda = bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001
            _cuda = False
    return _cuda


def pick_device(pref: str) -> tuple[str, str]:
    """(裝置, 說明)：auto → cuda 優先；要求 cuda 但沒有 → cpu 並附說明。"""
    pref = str(pref or "auto").lower()
    if pref in ("auto", "", "gpu"):
        return ("cuda" if cuda_available() else "cpu"), ""
    if pref.startswith("cuda") and not cuda_available():
        return "cpu", "找不到 CUDA，已退回 CPU"
    return pref, ""


def _import_yolo():
    try:
        os.environ.setdefault("YOLO_OFFLINE", "1")
        from ultralytics import YOLO  # noqa: PLC0415

        return YOLO
    except ImportError:
        raise ModelUnavailable(f"未安裝 ultralytics／torch，無法執行 YOLO 工具。{_INSTALL_HINT}") from None


def load(path_or_name: str, *, task: str = "", log_fn=None) -> Any:
    """取得（快取的）ultralytics 模型。path_or_name：資產檔路徑、本機 .pt／.onnx 路徑或官方名稱。"""
    YOLO = _import_yolo()
    name = str(path_or_name or "").strip()
    if not name:
        raise ModelUnavailable("沒有設定模型：選擇模型資產，或填官方底模名稱（例如 yolo11n.pt）")
    try:
        path = resolve_model(name, log_fn)
    except Exception as exc:  # noqa: BLE001  TrainError（下載失敗等）
        raise ModelUnavailable(str(exc)) from None
    if not os.path.isfile(path):
        raise ModelUnavailable(f"找不到模型檔 {path}")
    key = os.path.abspath(path)
    with _guard:
        model = _models.get(key)
        if model is not None:
            _models.move_to_end(key)
            return model
    try:
        kwargs = {"task": task} if task and key.lower().endswith((".onnx", ".engine")) else {}
        model = YOLO(key, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailable(f"載入模型失敗：{str(exc)[:200]}") from None
    with _guard:
        _models[key] = model
        _locks.setdefault(key, threading.Lock())
        while len(_models) > MAX_MODELS:
            old, _ = _models.popitem(last=False)
            _locks.pop(old, None)
    return model


def task_of(model: Any) -> str:
    return str(getattr(model, "task", "") or "")


def names_of(model: Any) -> dict[int, str]:
    raw = getattr(model, "names", None) or {}
    if isinstance(raw, dict):
        return {int(k): str(v) for k, v in raw.items()}
    return {i: str(v) for i, v in enumerate(raw)}


def predict(model: Any, image: np.ndarray, **kw: Any) -> Any:
    """單張推論 → ultralytics Results（第一筆）。同一模型序列化。"""
    key = next((k for k, m in _models.items() if m is model), None)
    lock = _locks.get(key or "", None)
    if lock is None:
        lock = threading.Lock()
    with lock:
        try:
            results = model.predict(image, verbose=False, **kw)
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable(f"推論失敗：{str(exc)[:200]}") from None
    return results[0] if results else None


def clear() -> None:
    with _guard:
        _models.clear()
        _locks.clear()


def loaded() -> list[dict[str, Any]]:
    with _guard:
        return [{"path": k, "task": task_of(m), "classes": len(names_of(m))} for k, m in _models.items()]
