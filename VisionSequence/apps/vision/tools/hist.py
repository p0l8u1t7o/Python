"""灰階直方圖的小工具（Otsu 門檻等），量測與檢測工具共用。"""

from __future__ import annotations

import cv2
import numpy as np


def masked_hist(gray: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    """256 階直方圖（float64 計數）；mask 給定時只算遮罩內。"""
    sub = gray if gray.dtype == np.uint8 else np.clip(gray, 0, 255).astype(np.uint8)
    m = None if mask is None else np.ascontiguousarray(mask)
    return cv2.calcHist([np.ascontiguousarray(sub)], [0], m, [256], [0, 256]).reshape(-1).astype(np.float64)


def otsu_from_hist(hist: np.ndarray) -> float:
    """由直方圖算 Otsu 門檻（類間變異最大）；門檻 t 代表灰階 > t 為前景，與 cv2.THRESH_OTSU 相同。"""
    total = hist.sum()
    if total <= 0:
        return 0.0
    levels = np.arange(256, dtype=np.float64)
    w0 = np.cumsum(hist)
    w1 = total - w0
    sum0 = np.cumsum(hist * levels)
    mu0 = np.divide(sum0, w0, out=np.zeros(256), where=w0 > 0)
    mu1 = np.divide(sum0[-1] - sum0, w1, out=np.zeros(256), where=w1 > 0)
    between = w0 * w1 * (mu0 - mu1) ** 2
    return float(int(between.argmax()))
