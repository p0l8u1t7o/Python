"""伺服端運算資源：onnxruntime providers、GPU 資訊，與使用者選擇的推論 provider。

熱路徑規則：dl 工具建 session 時只讀模組層快取（preferred_providers()），
DB 只在啟動（load_settings）與設定端點（save_settings，呼叫者執行緒）碰。
"""

from __future__ import annotations

import logging
import subprocess
import threading
from typing import Any

log = logging.getLogger(__name__)

#: 使用者選擇的推論 providers（記憶體快取；空 = 自動：照 available 順序）。
_preferred: list[str] = []
#: 訓練裝置偏好（cpu / cuda…）。
_train_device = "cpu"
_lock = threading.Lock()


def available_providers() -> list[str]:
    try:
        import onnxruntime as ort

        return list(ort.get_available_providers())
    except ImportError:
        return []


_torch_cuda: bool | None = None


def _torch_cuda_available() -> bool:
    """torch 的 CUDA 可用性——訓練走 torch，不能只看 onnxruntime providers
    （裝 CPU 版 onnxruntime＋CUDA 版 torch 時，訓練裝置仍應列出 cuda）。
    torch import 很重（秒級），查一次就快取。"""
    global _torch_cuda
    if _torch_cuda is None:
        try:
            import torch

            _torch_cuda = bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001 — 未安裝或初始化失敗都當沒有
            _torch_cuda = False
    return _torch_cuda


def _gpus() -> list[dict[str, Any]]:
    """NVIDIA GPU 資訊（nvidia-smi 存在才有；查不到就空清單，不報錯）。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    gpus = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            try:
                gpus.append({"name": parts[0], "memory_total_mb": int(parts[1]), "memory_used_mb": int(parts[2]), "utilization": int(parts[3])})
            except ValueError:
                gpus.append({"name": parts[0]})
    return gpus


def info() -> dict[str, Any]:
    """給前端顯示的伺服端資源總覽＋目前設定。"""
    providers = available_providers()
    try:
        import onnxruntime as ort

        ort_version = ort.__version__
    except ImportError:
        ort_version = ""
    accel = [p for p in providers if p != "CPUExecutionProvider"]
    with _lock:
        preferred = list(_preferred)
        train_device = _train_device
    train_devices = ["cpu"] + (["cuda"] if (_torch_cuda_available() or any("CUDA" in p for p in providers)) else [])
    return {
        "onnxruntime": ort_version,
        "providers": providers,
        "accelerators": accel,
        "gpus": _gpus(),
        "preferred_providers": preferred,
        "train_device": train_device,
        "train_devices": train_devices,
    }


def preferred_providers() -> list[str]:
    """dl 工具建 session 用：使用者選的（過濾掉不可用的）＋ CPU 墊底。純記憶體。"""
    with _lock:
        chosen = list(_preferred)
    avail = available_providers()
    out = [p for p in chosen if p in avail]
    if "CPUExecutionProvider" not in out:
        out.append("CPUExecutionProvider")
    return out


def train_device() -> str:
    with _lock:
        return _train_device


def load_settings() -> None:
    """啟動時把 DB 設定讀進記憶體（AppConfig.ready 呼叫；DB 還沒 migrate 時靜默略過）。

    刻意在啟動讀這一列（推論 providers 必須在第一次建 session 前就正確），
    Django 對 ready() 內查詢的 RuntimeWarning 在此局部抑制。
    """
    global _preferred, _train_device
    import warnings

    try:
        from apps.vision.models import DlSettings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            row = DlSettings.objects.filter(pk=1).first()
        if row:
            with _lock:
                _preferred = [str(p) for p in (row.providers or [])]
                _train_device = str(row.train_device or "cpu")
    except Exception:  # noqa: BLE001 — migrate 前／測試環境
        log.debug("DL 設定尚無法載入（資料表未建立）", exc_info=True)


def save_settings(providers: list[str] | None, device: str | None) -> dict[str, Any]:
    """設定端點用（呼叫者執行緒）：寫 DB、更新記憶體、清掉 dl session 快取讓新 provider 生效。"""
    global _preferred, _train_device
    from apps.vision.models import DlSettings
    from apps.vision.tools.builtin.dl import clear_sessions

    row, _ = DlSettings.objects.get_or_create(pk=1)
    if providers is not None:
        avail = set(available_providers())
        bad = [p for p in providers if p not in avail]
        if bad:
            from apps.core.errors import ValidationError

            raise ValidationError(f"此伺服器沒有這些 provider：{', '.join(bad)}", code="bad_provider", details={"available": sorted(avail)})
        row.providers = list(providers)
    if device is not None:
        row.train_device = str(device)
    row.save()
    with _lock:
        _preferred = [str(p) for p in (row.providers or [])]
        _train_device = str(row.train_device or "cpu")
    clear_sessions()
    return info()
