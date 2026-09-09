"""擷取端預覽用的純量測函式（不含 Qt，也不 import Django）。"""

from __future__ import annotations

import cv2
import numpy as np


def _variance(image: np.ndarray) -> tuple[float, int]:
    """用與伺服端量測工具相同的 meanStdDev 算 variance。"""
    arr = np.ascontiguousarray(image)
    if arr.size <= 0:
        return 0.0, 0
    _, std = cv2.meanStdDev(arr)
    return float(std[0, 0] ** 2), int(arr.size)


def sharpness(gray: np.ndarray) -> float:
    """Laplacian variance，並依原灰階 variance 正規化，對齊伺服端 Sharpness 預設公式。"""
    image = np.asarray(gray)
    if image.ndim != 2 or image.size < 9:
        return 0.0
    contrast, _count = _variance(image)
    response = cv2.Laplacian(np.ascontiguousarray(image), cv2.CV_16S, ksize=3)
    raw, _ = _variance(response)
    return raw / max(contrast, 1e-6)
