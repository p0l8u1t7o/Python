"""一維序列缺陷的共用零件：基線、離群、把「超標的點」串成缺陷區段。

沿著一條幾何（圓周、直線、圓弧、手繪路徑）佈一排卡尺，就會得到一條序列——半徑、寬度、
到基準線的距離。缺陷判斷都是同一套：**算基線 → 看偏離 → 過門檻 → 連續超標的串成一段**，
差別只在序列從哪裡來、基線怎麼估。`profile_defect` 工具最早寫了這一套；沿參考直線／圓弧
佈卡尺的邊緣缺陷檢測要用同樣的邏輯，所以抽到這裡共用，行為不變（`bench_tools.py` 鎖住）。

慣例：序列用 float64，找不到的位置是 NaN（卡尺打空）——**打空本身就是缺陷訊號**，
大缺口會讓卡尺完全找不到邊，是最容易漏判的一種。`wrap=True` 表示序列頭尾相連（繞一圈）。
"""

from __future__ import annotations

import numpy as np


def robust_outliers(values: np.ndarray, sigma: float) -> np.ndarray:
    """MAD 離群：|v − median| > sigma × 1.4826 × MAD 的為 True（NaN 不算）。"""
    ok = np.isfinite(values)
    out = np.zeros(len(values), dtype=bool)
    if ok.sum() < 4 or sigma <= 0:
        return out
    med = float(np.median(values[ok]))
    mad = float(np.median(np.abs(values[ok] - med))) * 1.4826
    if mad < 1e-6:
        mad = 1e-6
    out[ok] = np.abs(values[ok] - med) > sigma * mad
    return out


def moving_median(values: np.ndarray, window: int, wrap: bool) -> np.ndarray:
    """滑動中位數基線（NaN 略過；wrap＝序列頭尾相連）。"""
    n = len(values)
    w = max(3, int(window) | 1)
    half = w // 2
    out = np.full(n, np.nan)
    if n == 0:
        return out
    if wrap:
        padded = np.concatenate([values[-half:], values, values[:half]])
    else:
        padded = np.concatenate([np.full(half, np.nan), values, np.full(half, np.nan)])
    for i in range(n):
        seg = padded[i : i + w]
        seg = seg[np.isfinite(seg)]
        if len(seg):
            out[i] = np.median(seg)
    return out


def segments(flag: np.ndarray, wrap: bool) -> list[tuple[int, int]]:
    """連續 True 的區段 [(start, end)]（end 含）；wrap 時跨頭尾的區段合併（end 可能小於 start）。"""
    n = len(flag)
    if n == 0 or not flag.any():
        return []
    if flag.all():
        return [(0, n - 1)]
    segs: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if flag[i]:
            j = i
            while j + 1 < n and flag[j + 1]:
                j += 1
            segs.append((i, j))
            i = j + 1
        else:
            i += 1
    if wrap and len(segs) >= 2 and segs[0][0] == 0 and segs[-1][1] == n - 1:
        first, last = segs[0], segs[-1]
        segs = segs[1:-1] + [(last[0], first[1])]
    return segs


def seg_len(seg: tuple[int, int], n: int) -> int:
    """區段長度（跨頭尾的算兩截）。"""
    s, e = seg
    return e - s + 1 if e >= s else (n - s) + (e + 1)


def seg_indices(seg: tuple[int, int], n: int) -> np.ndarray:
    """區段涵蓋的索引（跨頭尾的接起來）。"""
    s, e = seg
    return np.arange(s, e + 1) if e >= s else np.concatenate([np.arange(s, n), np.arange(0, e + 1)])
