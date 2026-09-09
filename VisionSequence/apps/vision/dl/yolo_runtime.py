"""ultralytics 模型的行程內快取與推論（ai_* 工具、SAM 智慧標記共用）。

- 模型物件依「解析後的檔案路徑」快取在模組層（載入秒級、GPU 記憶體不重複）；ultralytics 的 predictor
  有內部狀態，同一個模型的推論用鎖序列化（不同模型可並行）。
- 官方名稱（yolo11n.pt、yolo11n-seg.pt…）第一次使用經 yolo.resolve_model 下載到 ASSET_DIR/dl/weights。
- 依賴（torch／ultralytics）延後 import：沒裝時工具回 ToolError，平台照常啟動。
- 裝置：auto＝有 CUDA 就用 GPU；指定 cuda 但沒有時退回 CPU 並在 note 說明。
"""

from __future__ import annotations

import copy
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
_track_states: dict[tuple[str, str], Any] = {}
_ts_ready: set[tuple[str, tuple[int, ...]]] = set()
#: 每個模型的「輸入形狀 → 編譯圖」表與原始 forward：同一個模型可能被不同 imgsz／ROI 尺寸的流程共用，
#: wrapper 不能只記最後一種形狀，遇到沒編譯過的形狀要退回**原本的** forward（不是直接呼叫內層 module，
#: 那個簽名跟版本綁在一起——實測 8.4.137 的 BaseModel.predict 不吃 visualize，會炸）。
_ts_compiled: dict[str, dict[tuple[int, ...], Any]] = {}
_ts_orig: dict[str, Any] = {}


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
        return "cpu", "CUDA was not found; using the CPU instead"
    return pref, ""


def _import_yolo():
    try:
        os.environ.setdefault("YOLO_OFFLINE", "1")
        from ultralytics import YOLO  # noqa: PLC0415

        return YOLO
    except ImportError:
        raise ModelUnavailable(f"ultralytics and torch are not installed, so the YOLO tools cannot run.{_INSTALL_HINT}") from None


def load(path_or_name: str, *, task: str = "", log_fn=None) -> Any:
    """取得（快取的）ultralytics 模型。path_or_name：資產檔路徑、本機 .pt／.onnx 路徑或官方名稱。"""
    YOLO = _import_yolo()
    name = str(path_or_name or "").strip()
    if not name:
        raise ModelUnavailable("No model is configured: choose a model asset, or give a stock model name such as yolo11n.pt")
    try:
        path = resolve_model(name, log_fn)
    except Exception as exc:  # noqa: BLE001  TrainError（下載失敗等）
        raise ModelUnavailable(str(exc)) from None
    if not os.path.isfile(path):
        raise ModelUnavailable(f"Model file not found: {path}")
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
        raise ModelUnavailable(f"Loading the model failed: {str(exc)[:200]}") from None
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
            raise ModelUnavailable(f"Inference failed: {str(exc)[:200]}") from None
    return results[0] if results else None


def _model_key(model: Any) -> str:
    return next((k for k, m in _models.items() if m is model), "")


def track(model: Any, image: np.ndarray, *, state_key: str | None, tracker: str, **kw: Any) -> Any:
    """單張追蹤 → ultralytics Results（第一筆），tracker 狀態依 state_key 分開保存。"""
    key = _model_key(model)
    lock = _locks.get(key or "", None) or threading.Lock()
    tracker_name = f"{tracker}.yaml" if tracker and not tracker.endswith(".yaml") else tracker
    with lock:
        predictor = getattr(model, "predictor", None)
        old_trackers = getattr(predictor, "trackers", None) if predictor is not None else None
        state_id = (key, str(state_key or "")) if state_key else None
        if state_id is not None and predictor is not None and state_id in _track_states:
            predictor.trackers = _track_states[state_id]
        post_predictor = predictor
        try:
            try:
                results = model.track(image, verbose=False, persist=bool(state_key), tracker=tracker_name, **kw)
            except ModuleNotFoundError as exc:
                if exc.name == "lap":
                    raise ModelUnavailable("The tracking extra is not installed; run .venv\\Scripts\\pip install -r requirements-dl.txt") from None
                raise
            post_predictor = getattr(model, "predictor", None)
            if state_id is not None and post_predictor is not None and hasattr(post_predictor, "trackers"):
                _track_states[state_id] = post_predictor.trackers
            return results[0] if results else None
        except ModelUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable(f"Tracking failed: {str(exc)[:200]}") from None
        finally:
            if state_id is None and post_predictor is not None:
                post_predictor.trackers = old_trackers


class _FlatForward:
    """延遲建立 torch wrapper，避免沒裝 torch 時模組 import 失敗。"""

    @staticmethod
    def make(module: Any) -> Any:
        import torch  # noqa: PLC0415

        class FlatForward(torch.nn.Module):
            """把分割模型輸出攤平成可 trace 的 tensor tuple。"""

            def __init__(self, inner: Any) -> None:
                super().__init__()
                self.inner = inner

            def forward(self, x):  # noqa: ANN001
                y = self.inner(x)
                if isinstance(y, (list, tuple)) and y and isinstance(y[0], (list, tuple)):
                    return tuple(v for v in y[0] if hasattr(v, "shape"))
                if isinstance(y, (list, tuple)):
                    return tuple(v for v in y if hasattr(v, "shape"))
                return (y,)

        return FlatForward(module)


def install_torchscript(model: Any, sample_image: np.ndarray) -> bool:
    """嘗試用 TorchScript 接管 backend.forward；逐候選與 eager bit-identical 才採用。"""
    key = _model_key(model)
    pred = getattr(model, "predictor", None)
    backend = getattr(getattr(pred, "model", None), "backend", None)
    module = getattr(backend, "model", None)
    if pred is None or backend is None or module is None:
        return False
    try:
        import torch  # noqa: PLC0415

        if not isinstance(module, torch.nn.Module):
            return False
        sample = pred.preprocess([sample_image])
        ready_key = (key, tuple(int(v) for v in sample.shape))
        if ready_key in _ts_ready:
            return True
        with torch.inference_mode():
            ref = _FlatForward.make(module).eval()(sample)
            try:
                traced = torch.jit.freeze(torch.jit.trace(_FlatForward.make(copy.deepcopy(module)).eval(), (sample,), check_trace=False).eval())
            except Exception:  # noqa: BLE001
                return False
            best = None
            for candidate in (_try(lambda: torch.jit.optimize_for_inference(traced)), traced):
                if candidate is None:
                    continue
                try:
                    got = candidate(sample)
                except Exception:  # noqa: BLE001
                    continue
                got_tuple = got if isinstance(got, tuple) else (got,)
                if len(ref) == len(got_tuple) and all(torch.equal(a, b) for a, b in zip(ref, got_tuple, strict=False)):
                    best = candidate
                    break
            if best is None:
                return False
            intact = _FlatForward.make(module).eval()(sample)
            if len(ref) != len(intact) or not all(torch.equal(a, b) for a, b in zip(ref, intact, strict=False)):
                return False

        shape = tuple(sample.shape)
        table = _ts_compiled.setdefault(key, {})
        table[shape] = best
        if key not in _ts_orig:
            _ts_orig[key] = backend.forward
            orig_forward = backend.forward

            def _forward(im, *args, **kwargs):  # noqa: ANN001, ANN202
                # 退回原 forward 時**原樣轉傳**呼叫者給的參數：不同版本的 AutoBackend.forward 簽名不同
                # （8.4.137 已沒有 visualize），自己補上明確的關鍵字會被塞進 **kwargs 再傳給 predict 而炸。
                plain = not args and all(not v for v in kwargs.values())
                compiled = table.get(tuple(im.shape)) if plain else None
                if compiled is None:
                    return orig_forward(im, *args, **kwargs)
                return [tuple(compiled(im)), {}]

            backend.forward = _forward
        _ts_ready.add(ready_key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _try(fn):
    """執行可選最佳化，失敗只退回 None。"""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def clear() -> None:
    with _guard:
        _models.clear()
        _locks.clear()
        _track_states.clear()
        _ts_ready.clear()
        _ts_compiled.clear()
        _ts_orig.clear()


def loaded() -> list[dict[str, Any]]:
    with _guard:
        return [{"path": k, "task": task_of(m), "classes": len(names_of(m))} for k, m in _models.items()]
