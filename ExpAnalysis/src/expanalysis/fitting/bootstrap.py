"""Bootstrap 不確定性估計。

為什麼用 bootstrap 而不是查表算標準誤
--------------------------------------
擬合出 k = 0.12，客戶一定會問「有多準？」。傳統做法要推導 Fisher 資訊矩陣，
在有設限資料 + 非線性模型的情況下很麻煩且假設多。Bootstrap 是純程式操作、
零統計背景也能實作、而且更直觀：

    把手上的 8 個點隨機重抽 N 次（可重複），每次各擬合一次，看 k 飄多少。
    飄得少 → 這個 k 可信；飄得很兇 → 資料撐不住這個結論，該說出來。

兩種重抽方式，預設用參數式
--------------------------
* ``parametric``（**預設**）：從擬合好的模型重新「生成」一組資料——
  y* = C_pred * exp(sigma * eps)，再依各點的 LOD 重新判定設限，然後重擬合。
* ``case``：直接重抽既有的觀測點。

為什麼預設不是 case：本專案的取樣點常常只有 8 個、其中一半以上低於檢測極限。
在這種情況下 case bootstrap 會嚴重**低估**不確定度（實測到 SE ≈ 2e-5，
但同一批的 k_eff 對真值其實偏了 40%），因為重抽只是在同一組資料點裡換權重，
沒有把「量測雜訊本身」與「設限造成的資訊損失」帶進來。參數式重抽兩者都涵蓋，
給出的區間才誠實。

case 模式仍保留：當懷疑模型設定本身有誤（例如取樣位置可疑）時，
case bootstrap 對模型誤設較不敏感，可以拿來交叉檢查。

效能：全向量化，不是迴圈
------------------------
天真寫法是「for 每次重抽 → 呼叫最佳化器」，一批一元素要 0.5 秒，
80 個組合就是 40 秒，UI 完全不能用。

這裡改成：把所有重抽的所有 k 網格點一次算完（(K, D, n) 三維陣列），
在 k 軸上取最小值，再用三點拋物線內插取得次網格精度。同樣的工作量
從 0.5 秒降到約 20 毫秒，而且結果與逐次最佳化在 1e-4 以內一致。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from scipy.stats import norm

from ..logging_setup import get_logger
from ..physics.profile_grid import PositionSlice, get_profile_grid
from .censored import SIGMA_MAX, SIGMA_MIN, TobitData

log = get_logger(__name__)


@dataclass
class BootstrapResult:
    k_median: float
    k_lo: float
    k_hi: float
    k_se: float
    n_success: int
    n_draws: int
    samples: list[float]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["samples"] = [round(v, 6) for v in self.samples[:400]]   # 畫直方圖足夠
        return d


def _nll_over_k(log_pred: np.ndarray, log_y: np.ndarray, log_lod: np.ndarray,
                censored: np.ndarray, sigma: float) -> np.ndarray:
    """向量化的 Tobit 負對數概似。

    Args:
        log_pred: (K, D, n) 各 k 網格點、各重抽、各測點的預測 ln(濃度)。
        log_y:    (D, n) 觀測 ln(濃度)。
        log_lod:  (D, n) ln(LOD)。
        censored: (D, n) bool。
        sigma:    對數殘差標準差（固定）。

    Returns:
        (K, D) 負對數概似（省略與 k 無關的常數項）。
    """
    obs = ~censored                                     # (D, n)
    r = (log_y[None, :, :] - log_pred) / sigma
    nll = np.sum(0.5 * r * r * obs[None, :, :], axis=2)

    if np.any(censored):
        z = (log_lod[None, :, :] - log_pred) / sigma
        # logcdf 在 z 很負時仍數值穩定
        lc = norm.logcdf(np.clip(z, -37.0, 37.0))
        nll -= np.sum(lc * censored[None, :, :], axis=2)
    return nll


def _parabolic_refine(k_grid: np.ndarray, nll: np.ndarray) -> np.ndarray:
    """對每一欄（每次重抽）在最小值附近做三點拋物線內插，取得次網格精度。

    Args:
        k_grid: (K,)
        nll:    (K, D)

    Returns:
        (D,) 精修後的 k 估計。
    """
    j = np.argmin(nll, axis=0)
    j = np.clip(j, 1, k_grid.size - 2)
    d = np.arange(nll.shape[1])
    x0, x1, x2 = k_grid[j - 1], k_grid[j], k_grid[j + 1]
    y0, y1, y2 = nll[j - 1, d], nll[j, d], nll[j + 1, d]

    # 非等距三點的拋物線頂點
    denom = (x0 - x1) * (x0 - x2) * (x1 - x2)
    a = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1))
    b = (x2 * x2 * (y0 - y1) + x1 * x1 * (y2 - y0) + x0 * x0 * (y1 - y2))
    with np.errstate(divide="ignore", invalid="ignore"):
        vertex = np.where(np.abs(a) > 1e-30, -b / (2.0 * a), x1)
    # 頂點超出三點範圍時代表不是凸的，退回網格最小值
    lo, hi = np.minimum(x0, x2), np.maximum(x0, x2)
    return np.where((vertex >= lo) & (vertex <= hi) & np.isfinite(vertex), vertex, x1)


def bootstrap_keff(
    x_norm,
    values_ppm,
    lod_ppm,
    censored,
    zone_len_frac: float,
    n_passes: int,
    c0_ppm: float,
    sigma_log: float,
    k_eff: float | None = None,
    method: str = "parametric",
    n_draws: int = 300,
    seed: int = 12345,
    ci: float = 0.95,
    n_cells: int = 240,
    max_cells: int = 4_000_000,
) -> BootstrapResult:
    """對 k_eff 做 bootstrap（全向量化）。

    Args:
        k_eff: 主擬合的 k 估計。parametric 模式必填（用來生成資料）。
        method: "parametric"（預設）或 "case"。
        sigma_log: 主擬合估出的對數殘差標準差；重抽時固定不重估，
                   這樣各次重抽才可比較，也避免小樣本退化到下限。
    """
    data = TobitData.from_points(x_norm, values_ppm, lod_ppm, censored)
    grid = get_profile_grid(zone_len_frac, n_passes, n_cells)
    base = PositionSlice(grid, data.x)
    log_c0 = np.log(max(c0_ppm, 1e-12))
    sigma = float(np.clip(sigma_log, SIGMA_MIN, SIGMA_MAX))

    n = data.n
    k_grid = base.k_grid
    K = k_grid.size
    chunk = max(1, min(n_draws, int(max_cells / max(K * n, 1))))   # 記憶體保護

    rng = np.random.default_rng(seed)
    est: list[np.ndarray] = []

    if method == "parametric":
        if k_eff is None:
            raise ValueError("parametric bootstrap 需要提供 k_eff")
        mu = base.predict_log(float(k_eff)) + log_c0                # (n,)
        for start in range(0, n_draws, chunk):
            d = min(chunk, n_draws - start)
            eps = rng.normal(0.0, sigma, size=(d, n))
            log_y = mu[None, :] + eps                               # (D, n)
            cen = log_y < data.log_lod[None, :]                     # 依 LOD 重新判定設限
            log_y = np.where(cen, data.log_lod[None, :], log_y)
            keep = ~np.all(cen, axis=1)
            if not np.any(keep):
                continue
            log_y, cen = log_y[keep], cen[keep]
            log_pred = np.repeat(base.log_cols[:, None, :], log_y.shape[0], axis=1) + log_c0
            nll = _nll_over_k(log_pred, log_y,
                              np.repeat(data.log_lod[None, :], log_y.shape[0], axis=0),
                              cen, sigma)
            est.append(_parabolic_refine(k_grid, nll))
    elif method == "case":
        for start in range(0, n_draws, chunk):
            d = min(chunk, n_draws - start)
            idx = rng.integers(0, n, size=(d, n))                 # (D, n)
            keep = ~np.all(data.censored[idx], axis=1)            # 全設限的重抽無資訊
            if not np.any(keep):
                continue
            idx = idx[keep]
            log_pred = base.log_cols[:, idx] + log_c0             # (K, D, n)
            nll = _nll_over_k(log_pred, data.log_y[idx], data.log_lod[idx],
                              data.censored[idx], sigma)
            est.append(_parabolic_refine(k_grid, nll))
    else:
        raise ValueError(f"未知的 bootstrap 方法：{method!r}")

    if not est:
        log.warning("bootstrap 無有效重抽（可能全部測點皆設限）")
        return BootstrapResult(float("nan"), float("nan"), float("nan"),
                               float("nan"), 0, n_draws, [])

    arr = np.clip(np.concatenate(est), k_grid[0], k_grid[-1])
    alpha = (1.0 - ci) / 2.0
    return BootstrapResult(
        k_median=float(np.median(arr)),
        k_lo=float(np.quantile(arr, alpha)),
        k_hi=float(np.quantile(arr, 1.0 - alpha)),
        k_se=float(np.std(arr, ddof=1)) if arr.size > 1 else float("nan"),
        n_success=int(arr.size), n_draws=n_draws,
        samples=[float(v) for v in arr],
    )
