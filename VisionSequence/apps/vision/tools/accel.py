"""前處理加速的透明後端切換（WP-16）：`VISION_ACCEL=auto|cpu|opencl|cuda`，工具介面不變。

先量再說（docs/performance.html §5.7o）：這台 RTX 5070 Ti 筆電上 OpenCV 的 OpenCL（T-API，UMat）對 4000×3000——
remap 2.65×、medianBlur 2.5×、filter2D 1.8×、dft 1.65×；GaussianBlur 0.39×（反而慢）、形態學 1.0×；上傳＋下載只佔 4 ms／30 ms。
「blur→filter→open→threshold」整段合併只有 1.04×，逐工具 0.68×；1280×960 除了 remap／median 之外全部變慢。
所以：**不做編譯期的 GPU 區段合併**（瓶頸不是傳輸，是高斯模糊與形態學在 OpenCL 沒有賺頭），只把量得到有賺的四種運算包成 wrapper，
而且只在影像夠大（`ACCEL_MIN_PIXELS`，預設 4 MP）時走 OpenCL；`cv2.cuda` 在 headless wheel 裡不存在，`cuda` 選項偵測不到就退回。
沒有 GPU 的機器行為與現在完全一致（wrapper 直接呼叫 cv2 的 ndarray 版本）。OpenCL 與 CPU 的結果：medianBlur 完全相同、filter2D 與 remap 內部
差 1 灰階以內；remap 取樣點落在影像外的邊界像素，OpenCL 核心對常數邊界的捨入與 CPU 不同（4.8 MP 隨機圖實測 56 個像素）——極座標環與鏡頭校正
的邊界本來就是黑的，不影響量測。

用法：`from apps.vision.tools import accel` → `accel.remap(img, mx, my, interp)`、`accel.median_blur(img, k)`、`accel.filter2d(img, ddepth, kernel)`、
`accel.dft(src, flags)`；回傳永遠是 ndarray。`accel.status()` 給 doctor／API 看目前後端。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import cv2
import numpy as np

log = logging.getLogger("vision.accel")

MODES = ("auto", "cpu", "opencl", "cuda")
#: 低於這個像素數不值得上 GPU（1280×960 實測全部變慢、4000×3000 才有賺）
DEFAULT_MIN_PIXELS = 4_000_000
_state: dict[str, Any] = {"mode": "cpu", "backend": "cpu", "device": "", "min_pixels": DEFAULT_MIN_PIXELS, "reason": "not configured", "calls": 0, "accelerated": 0}
_lock = threading.Lock()


def configure(mode: str = "auto", min_pixels: int = DEFAULT_MIN_PIXELS) -> dict[str, Any]:
    """啟動時呼叫一次（apps.ready）；也給測試切換用。回 status()。"""
    mode = (mode or "auto").strip().lower()
    if mode not in MODES:
        log.warning("VISION_ACCEL=%r 不認得，改用 cpu", mode)
        mode = "cpu"
    backend, device, reason = "cpu", "", ""
    if mode in ("auto", "cuda"):
        try:
            n = cv2.cuda.getCudaEnabledDeviceCount() if hasattr(cv2, "cuda") else 0
        except cv2.error:
            n = 0
        if n > 0:
            backend, device = "cuda", "cuda"
        elif mode == "cuda":
            reason = "this OpenCV build has no CUDA module (opencv-python-headless); falling back"
    if backend == "cpu" and mode in ("auto", "opencl", "cuda"):
        try:
            ok = bool(cv2.ocl.haveOpenCL())
        except cv2.error:
            ok = False
        if ok:
            try:
                cv2.ocl.setUseOpenCL(True)
                ok = bool(cv2.ocl.useOpenCL())
                device = cv2.ocl.Device.getDefault().name() if ok else ""
            except cv2.error:
                ok = False
        if ok:
            backend = "opencl"
        elif mode != "auto" and not reason:
            reason = "OpenCL is not available on this machine; falling back"
    if backend == "cpu":
        try:
            cv2.ocl.setUseOpenCL(False)
        except cv2.error:
            pass
        if not reason:
            reason = "cpu requested" if mode == "cpu" else "no GPU backend detected"
    with _lock:
        _state.update({"mode": mode, "backend": backend, "device": device, "min_pixels": int(min_pixels), "reason": reason, "calls": 0, "accelerated": 0})
    if backend == "cpu" and mode != "cpu":
        log.info("前處理加速：%s（VISION_ACCEL=%s）", reason, mode)
    elif backend != "cpu":
        log.info("前處理加速：%s（%s），影像 ≥ %d 像素的 remap／median／filter2D／dft 走 GPU", backend, device, int(min_pixels))
    return status()


def status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _use_gpu(image: np.ndarray) -> bool:
    if _state["backend"] != "opencl":  # cuda 模組在 headless wheel 沒有；有 cuda 也先走 T-API（同一條路）
        return False
    return int(image.shape[0]) * int(image.shape[1]) >= _state["min_pixels"]


def _count(gpu: bool) -> None:
    with _lock:
        _state["calls"] += 1
        if gpu:
            _state["accelerated"] += 1


def _run(image: np.ndarray, fn) -> np.ndarray:
    """有賺就丟 UMat 跑、失敗（驅動炸、記憶體不足）退回 CPU 並記一行。"""
    gpu = _use_gpu(image)
    _count(gpu)
    if gpu:
        try:
            out = fn(cv2.UMat(image))
            return out.get() if isinstance(out, cv2.UMat) else np.asarray(out)
        except cv2.error as exc:  # noqa: BLE001 - 退回 CPU 是設計的一部分
            log.warning("OpenCL 路徑失敗，退回 CPU：%s", str(exc).splitlines()[0] if str(exc) else exc)
    return fn(image)


def remap(image: np.ndarray, map_x: np.ndarray, map_y: np.ndarray, interpolation: int = cv2.INTER_LINEAR, border_mode: int = cv2.BORDER_CONSTANT, border_value: Any = 0) -> np.ndarray:
    gpu = _use_gpu(image)
    _count(gpu)
    if gpu:
        try:
            out = cv2.remap(cv2.UMat(image), cv2.UMat(np.ascontiguousarray(map_x, dtype=np.float32)), cv2.UMat(np.ascontiguousarray(map_y, dtype=np.float32)), interpolation, borderMode=border_mode, borderValue=border_value)
            return out.get()
        except cv2.error as exc:
            log.warning("OpenCL remap 失敗，退回 CPU：%s", str(exc).splitlines()[0] if str(exc) else exc)
    return cv2.remap(image, map_x, map_y, interpolation, borderMode=border_mode, borderValue=border_value)


def median_blur(image: np.ndarray, ksize: int) -> np.ndarray:
    return _run(image, lambda src: cv2.medianBlur(src, int(ksize)))


def filter2d(image: np.ndarray, ddepth: int, kernel: np.ndarray, border_type: int = cv2.BORDER_DEFAULT) -> np.ndarray:
    return _run(image, lambda src: cv2.filter2D(src, ddepth, kernel, borderType=border_type))


def dft(src: np.ndarray, flags: int = 0) -> np.ndarray:
    return _run(src, lambda s: cv2.dft(s, flags=flags))


def idft(src: np.ndarray, flags: int = 0) -> np.ndarray:
    return _run(src, lambda s: cv2.idft(s, flags=flags))
