"""Pfann 單次 pass 解析解與正常凝固（normal freezing）解。

符號約定（全專案一致，請勿混用）：
    L       錠長 / 有效純化長度      [mm]
    l       熔區長度 (zone length)   [mm]
    x       距頭端之距離             [mm]
    g = x/L 歸一化位置（無因次，0=頭端, 1=尾端）
    C0      進料初始雜質濃度（假設均勻） [ppm]
    k       有效分配係數 k_eff（無因次）

上一版對話中曾把 Pfann 方程寫成 exp(-k*x/L)，那是錯的：分母是熔區長度 l
而不是錠長 L。本模組一律以 l 為準，並在介面上要求呼叫端明確給出 zone_len。
"""

from __future__ import annotations

import numpy as np

# k 的數值下限。k=0 在解析解中無妨，但在 BPS 對數變換與擬合中會爆炸，
# 故全專案統一夾在 [K_MIN, K_MAX]。
K_MIN = 1e-4
K_MAX = 1.0 - 1e-4


def clip_k(k: float | np.ndarray) -> float | np.ndarray:
    """把 k 夾到數值安全區間 [K_MIN, 5.0]。

    下界 K_MIN 是為了避免 exp(-k*x/l) 在 k→0 時整條曲線退化成常數；
    上界放到 5.0 而不是 K_MAX，是因為確實有 k>1 的元素（偏析方向相反、
    往頭端濃縮），物理上合法，只是本專案追蹤的 Cu/Fe/Ni/Sn 都是 k<1。

    注意 :data:`K_MAX`（= 1 − 1e-4）是另一件事：它只用在 BPS 的對數變換
    ln(1/k − 1)，那裡 k 必須嚴格小於 1，否則取對數會爆炸。
    """
    return np.clip(k, K_MIN, 5.0)


def pfann_profile(
    x: np.ndarray,
    k: float,
    zone_len: float,
    c0: float = 1.0,
) -> np.ndarray:
    """單次 pass 之固體雜質濃度分布（Pfann 1952）。

    C(x) = C0 * [ 1 - (1 - k) * exp(-k * x / l) ]

    有效範圍為 0 <= x <= L - l。最後一個熔區長度的區段屬於終端凝固，
    行為完全不同（濃度暴衝），須改用 :func:`normal_freezing_profile`。
    本函式不會替呼叫端裁切，因為裁切點取決於 L，由呼叫端掌握。

    Args:
        x: (N,) float64，距頭端距離 [mm]，需 >= 0。
        k: 有效分配係數。k<1 雜質往尾端濃縮；k>1 往頭端濃縮。
        zone_len: 熔區長度 l [mm]，須 > 0。
        c0: 初始均勻濃度 [ppm]。

    Returns:
        (N,) float64 濃度 [ppm]。
    """
    if zone_len <= 0:
        raise ValueError(f"zone_len 必須為正數，收到 {zone_len}")
    x = np.asarray(x, dtype=np.float64)
    if np.any(x < 0):
        raise ValueError("x 不可為負")
    k = float(clip_k(k))
    return c0 * (1.0 - (1.0 - k) * np.exp(-k * x / zone_len))


def pfann_head_concentration(k: float, c0: float = 1.0) -> float:
    """頭端（x=0）濃度 = k * C0。這是單次 pass 能達到的最佳純度。"""
    return float(clip_k(k)) * c0


def normal_freezing_profile(
    g: np.ndarray,
    k: float,
    c_liquid0: float,
) -> np.ndarray:
    """正常凝固（Scheil）方程，用於最後一個熔區的終端凝固段。

    C_s(g) = k * C_L0 * (1 - g)^(k - 1)

    Args:
        g: (M,) 已凝固分率，0 <= g < 1（相對於該終端熔區）。
        k: 有效分配係數。
        c_liquid0: 終端凝固開始時的液池濃度 [ppm]。

    Returns:
        (M,) float64 濃度 [ppm]。g -> 1 時發散，故上限夾在 1-1e-9。
    """
    g = np.clip(np.asarray(g, dtype=np.float64), 0.0, 1.0 - 1e-9)
    k = float(clip_k(k))
    return k * c_liquid0 * np.power(1.0 - g, k - 1.0)
