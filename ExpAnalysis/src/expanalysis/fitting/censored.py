"""左設限（left-censored）資料的 Tobit likelihood。

問題
----
6N 純度下，很多測值會是「< 0.05 ppm」——儀器測不到。這不是一個數字，
是一個不等式。三種處理方式：

    當成 0      → 頭端看起來完美，k 被低估
    當成 LOD    → 頭端看起來偏髒，k 被高估
    正確做法    → 告訴擬合程式「這點的真值落在 [0, LOD] 之間」

用軟體的比喻：log 裡寫 ``response_time: TIMEOUT (>30s)``。統計時把它當
30 秒會低估平均值，當成 0 更荒謬。你只知道「至少 30 秒」。

為什麼用對數常態
----------------
ppm 級的分析誤差，相對誤差才是穩定的（GDMS 標稱「±20%」而不是「±0.1 ppm」），
而且濃度必為正。所以殘差定義在 ln 空間：

    ln C_obs = ln C_pred + eps,   eps ~ N(0, sigma^2)

未設限點的貢獻是常態密度；設限點的貢獻是累積機率 Phi((ln LOD - ln C_pred)/sigma)，
也就是「真值低於 LOD 的機率」。兩者相加就是完整的 likelihood。

實作說明
--------
scipy 沒有現成的左設限非線性回歸，但自己寫不到 40 行。用
``scipy.stats.norm.logcdf`` 可避免小機率時的下溢。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

SIGMA_MIN = 0.02          # 對數殘差標準差下限（相對誤差 2%）
SIGMA_MAX = 1.50          # 上限；超過代表資料與模型根本對不上


@dataclass
class TobitData:
    """擬合用的觀測資料。

    Attributes:
        x:        (P,) 歸一化取樣位置。
        log_y:    (P,) 未設限點的 ln(觀測濃度)；設限點此欄為 ln(LOD)。
        log_lod:  (P,) ln(LOD)；未設限點可為 -inf（不會被用到）。
        censored: (P,) bool，True 表示該點為左設限。
    """

    x: np.ndarray
    log_y: np.ndarray
    log_lod: np.ndarray
    censored: np.ndarray

    @property
    def n(self) -> int:
        return int(self.x.size)

    @property
    def n_censored(self) -> int:
        return int(np.count_nonzero(self.censored))

    @classmethod
    def from_points(cls, x, values_ppm, lod_ppm, censored) -> "TobitData":
        x = np.asarray(x, dtype=np.float64).ravel()
        v = np.maximum(np.asarray(values_ppm, dtype=np.float64).ravel(), 1e-12)
        lod = np.asarray(lod_ppm, dtype=np.float64).ravel()
        cen = np.asarray(censored, dtype=bool).ravel()
        lod_safe = np.where(lod > 0, lod, v)
        return cls(x=x, log_y=np.log(v), log_lod=np.log(np.maximum(lod_safe, 1e-12)),
                   censored=cen)


def tobit_nll(log_pred: np.ndarray, data: TobitData, sigma: float) -> float:
    """負對數概似（越小越好）。

    Args:
        log_pred: (P,) 模型預測的 ln(濃度)。
        data: 觀測資料。
        sigma: 對數殘差標準差。

    Returns:
        負對數概似（純量）。數值不合法時回傳 +inf，讓最佳化器自然避開。
    """
    sigma = float(np.clip(sigma, SIGMA_MIN, SIGMA_MAX))
    obs = ~data.censored

    nll = 0.0
    if np.any(obs):
        r = (data.log_y[obs] - log_pred[obs]) / sigma
        nll += float(np.sum(0.5 * r * r + np.log(sigma)))
    if np.any(data.censored):
        z = (data.log_lod[data.censored] - log_pred[data.censored]) / sigma
        # logcdf 在 z 很小時仍數值穩定（避免 log(0)）
        nll -= float(np.sum(norm.logcdf(z)))

    return nll if np.isfinite(nll) else float("inf")


def standardized_residuals(log_pred: np.ndarray, data: TobitData,
                           sigma: float) -> np.ndarray:
    """標準化殘差，供 L3 異常偵測使用。

    設限點沒有真值，無法給出一般意義的殘差。慣例做法是回傳
    **期望殘差**（Tobit 的 generalized residual）：

        E[eps | eps < z] = -phi(z) / Phi(z)

    這個值在「預測遠低於 LOD」時趨近 0（模型與觀測不矛盾），
    在「預測遠高於 LOD」時是大的負值（模型說應該測得到，實際卻測不到）。
    """
    sigma = float(np.clip(sigma, SIGMA_MIN, SIGMA_MAX))
    res = np.empty(data.n, dtype=np.float64)
    obs = ~data.censored
    res[obs] = (data.log_y[obs] - log_pred[obs]) / sigma
    if np.any(data.censored):
        z = (data.log_lod[data.censored] - log_pred[data.censored]) / sigma
        log_phi = norm.logpdf(z)
        log_Phi = np.maximum(norm.logcdf(z), -700.0)
        res[data.censored] = -np.exp(log_phi - log_Phi)
    return res
