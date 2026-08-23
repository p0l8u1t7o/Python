"""從一條實測曲線反解有效分配係數 k_eff。

方法
----
給定批次的製程條件（熔區長度比 l/L、pass 次數）與進料濃度 C0，物理模型
對任意 k 都能算出整條預測曲線。「擬合」就是找出讓預測最貼近實測的那個 k。

參數只有 1~3 個：
    k       有效分配係數（必要）
    c0_mul  進料濃度倍率（僅在 C0 未實測時開啟，範圍 [1/3, 3]）
    sigma   對數殘差標準差（一併估計，因為它決定設限點的權重）

對比機器學習方法：XGBoost 的有效參數數以百計、小型神經網路數以千計，
在 40 批資料下必然是背答案；而且學到的東西無法外插——問它沒跑過的速率，
只會回傳最接近的訓練值。1 個物理參數則綽綽有餘，且外插有依據。

搜尋策略
--------
k 的 likelihood 曲面偶爾有局部極小（尤其設限點多時），所以先在 k 網格上
做粗掃找到最佳起點，再用有界的 Nelder-Mead 精修。粗掃靠 ProfileGrid 的
查表，成本可以忽略。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np
from scipy.optimize import minimize

from ..logging_setup import get_logger
from ..physics.profile_grid import PositionSlice, get_profile_grid
from .censored import SIGMA_MAX, SIGMA_MIN, TobitData, standardized_residuals, tobit_nll

log = get_logger(__name__)


@dataclass
class KeffFit:
    """單一批次、單一元素的 k_eff 擬合結果。"""

    batch_id: str
    element: str
    k_eff: float
    c0_ppm: float
    sigma_log: float
    n_points: int
    n_censored: int
    rmse_log: float
    converged: bool = True
    c0_fitted: bool = False          # True 表示 C0 是擬合出來的（未實測）
    k_lo: float | None = None        # bootstrap 95% 下界
    k_hi: float | None = None
    k_se: float | None = None
    residuals: list[float] = field(default_factory=list)
    x_norm: list[float] = field(default_factory=list)
    pred_ppm: list[float] = field(default_factory=list)
    obs_ppm: list[float] = field(default_factory=list)
    censored_flags: list[bool] = field(default_factory=list)
    note: str = ""

    @property
    def interpretation(self) -> str:
        k = self.k_eff
        if k < 0.15:
            return "偏析效果好，此元素容易以區域熔煉去除"
        if k < 0.4:
            return "偏析效果中等，需要較多 pass 次數或較慢速率"
        if k < 0.75:
            return "偏析效果有限，得料率會被此元素綁住"
        return "k_eff 接近 1，此元素幾乎無法用偏析法去除，應由前段製程處理"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["interpretation"] = self.interpretation
        return d


def _make_objective(data: TobitData, slice_: PositionSlice, c0: float,
                    fit_c0: bool):
    """建立目標函數。回傳 (fun, unpack)。參數皆為無界實數，內部再轉換。"""

    def unpack(theta: np.ndarray) -> tuple[float, float, float]:
        k = float(np.clip(theta[0], 1e-4, 0.999))
        sigma = float(np.clip(theta[1], SIGMA_MIN, SIGMA_MAX))
        mul = float(np.clip(theta[2], 1.0 / 3.0, 3.0)) if fit_c0 else 1.0
        return k, sigma, mul

    log_c0 = np.log(max(c0, 1e-12))

    def fun(theta: np.ndarray) -> float:
        k, sigma, mul = unpack(theta)
        log_pred = slice_.predict_log(k) + log_c0 + np.log(mul)
        return tobit_nll(log_pred, data, sigma)

    return fun, unpack


def fit_keff(
    x_norm,
    values_ppm,
    lod_ppm,
    censored,
    zone_len_frac: float,
    n_passes: int,
    c0_ppm: float,
    fit_c0: bool = False,
    batch_id: str = "",
    element: str = "",
    n_cells: int = 240,
) -> KeffFit:
    """反解 k_eff。

    Args:
        x_norm:     (P,) 歸一化取樣位置。
        values_ppm: (P,) 觀測濃度；設限點填 LOD。
        lod_ppm:    (P,) 各點的檢測極限。
        censored:   (P,) bool。
        zone_len_frac: l / L。
        n_passes:   純化次數。
        c0_ppm:     進料濃度。
        fit_c0:     C0 未實測時設 True，會一併擬合倍率。
        n_cells:    模擬離散格數。

    Returns:
        KeffFit
    """
    data = TobitData.from_points(x_norm, values_ppm, lod_ppm, censored)
    if data.n < 3:
        raise ValueError(f"{batch_id}/{element}: 至少需要 3 個取樣點，收到 {data.n}")

    grid = get_profile_grid(zone_len_frac, n_passes, n_cells)
    slice_ = PositionSlice(grid, data.x)
    fun, unpack = _make_objective(data, slice_, c0_ppm, fit_c0)

    # ── 粗掃：在 k 網格上找最佳起點，避開局部極小 ──────────────
    best_k, best_nll = float(grid.k_grid[0]), float("inf")
    for k in grid.k_grid:
        val = fun(np.array([k, 0.15, 1.0]))
        if val < best_nll:
            best_nll, best_k = val, float(k)

    # ── 精修 ────────────────────────────────────────────────────
    x0 = np.array([best_k, 0.15, 1.0])
    res = minimize(fun, x0, method="Nelder-Mead",
                   options={"xatol": 1e-5, "fatol": 1e-7, "maxiter": 1200})
    k, sigma, mul = unpack(res.x)
    if not res.success and res.fun > best_nll:
        k, sigma, mul = best_k, 0.15, 1.0

    c0_eff = c0_ppm * mul
    log_pred = slice_.predict_log(k) + np.log(max(c0_eff, 1e-12))
    resid = standardized_residuals(log_pred, data, sigma)
    obs_mask = ~data.censored
    rmse = float(np.sqrt(np.mean((data.log_y[obs_mask] - log_pred[obs_mask]) ** 2))) \
        if np.any(obs_mask) else float("nan")

    note = ""
    if data.n_censored == data.n:
        note = ("全部測點皆低於檢測極限，k_eff 只有上界資訊、無法可靠估計。"
                "需要更低 LOD 的分析方法或更靠尾端的取樣點。")
    elif data.n_censored > data.n * 0.6:
        note = (f"{data.n_censored}/{data.n} 個測點低於檢測極限，"
                f"k_eff 的不確定度會偏大。")
    elif sigma > 0.5:
        note = (f"對數殘差標準差 {sigma:.2f}（相當於 ±{100*(np.exp(sigma)-1):.0f}% 的"
                f"相對誤差），遠高於典型 GDMS 水準，模型與資料明顯不吻合——"
                f"檢查取樣位置、進料濃度或是否有製程偏移。")

    return KeffFit(
        batch_id=batch_id, element=element,
        k_eff=float(k), c0_ppm=float(c0_eff), sigma_log=float(sigma),
        n_points=data.n, n_censored=data.n_censored, rmse_log=rmse,
        converged=bool(res.success), c0_fitted=bool(fit_c0 and abs(mul - 1) > 1e-6),
        residuals=[float(v) for v in resid],
        x_norm=[float(v) for v in data.x],
        pred_ppm=[float(v) for v in np.exp(log_pred)],
        obs_ppm=[float(v) for v in np.exp(data.log_y)],
        censored_flags=[bool(v) for v in data.censored],
        note=note,
    )


def fit_batch(detail, elements: list[str] | None = None,
              n_cells: int = 240) -> dict[str, KeffFit]:
    """對一個批次的所有元素擬合 k_eff。

    Args:
        detail: BatchDetail。
        elements: 限定元素；None 表示全部。

    Returns:
        {元素名: KeffFit}。個別元素擬合失敗時記錄警告並略過，不讓整批失敗。
    """
    out: dict[str, KeffFit] = {}
    zone_frac = detail.batch.zone_len_frac
    for el in (elements or detail.elements):
        pts = detail.points(el)
        if len(pts) < 3:
            log.warning("批次 %s 的 %s 只有 %d 點，略過擬合",
                        detail.batch.batch_id, el, len(pts))
            continue
        spec = next((s for s in detail.element_specs if s.element == el), None)
        c0 = spec.c0_ppm if spec else 1.0
        try:
            out[el] = fit_keff(
                [p.x_norm for p in pts], [p.value_ppm for p in pts],
                [p.lod_ppm for p in pts], [p.censored for p in pts],
                zone_len_frac=zone_frac, n_passes=detail.batch.n_passes,
                c0_ppm=c0, fit_c0=bool(spec and not spec.c0_measured),
                batch_id=detail.batch.batch_id, element=el, n_cells=n_cells,
            )
        except (ValueError, FloatingPointError) as exc:
            log.warning("批次 %s 的 %s 擬合失敗：%s", detail.batch.batch_id, el, exc)
    return out


def fit_all(details: list, elements: list[str] | None = None,
            n_cells: int = 240) -> dict[str, dict[str, KeffFit]]:
    """對多個批次擬合。回傳 {batch_id: {element: KeffFit}}。"""
    return {d.batch.batch_id: fit_batch(d, elements, n_cells) for d in details}
