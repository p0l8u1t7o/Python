"""BPS (Burton–Prim–Slichter) 有效分配係數模型。

物理來源
--------
凝固介面把雜質吐回液體，這些雜質要靠擴散散進整個液池，但擴散很慢。
凝固速度快時雜質來不及散開，在介面前堆成一層濃度較高的邊界層，使得
「實際感受到的分配係數」k_eff 比平衡值 k0 更接近 1（純化效果變差）。

    k_eff = k0 / [ k0 + (1 - k0) * exp(-v * delta / D) ]

    v      熔區移動速率        [mm/hr]
    delta  邊界層厚度（攪拌越強越薄）[mm]
    D      雜質在液態銦中的擴散係數 [mm^2/hr]

實務上 delta 與 D 無法分開量測，只有比值 (delta/D) 可辨識，本模組一律以
單一參數 ``delta_over_d`` 表示，單位 [hr/mm]。

線性化（這是本專案能用小資料做事的關鍵）
----------------------------------------
    1/k_eff - 1 = (1/k0 - 1) * exp(-v * delta/D)
    ln(1/k_eff - 1) = ln(1/k0 - 1) - (delta/D) * v
                       └── 截距 ──┘   └─ 斜率 ─┘

左邊由資料算出，右邊對 v 是一次式。所以只要 5~6 個不同速率的批次就能畫出
一條直線，得到 k0 與 delta/D，而且斜率有物理意義、可以外插。

這也是誠實度檢查：若散點根本不成直線，代表有別的機制在作怪（氧化、對流
不穩、量測不準），這個發現本身就有價值——不要硬套模型。

溫度怎麼進來
------------
溫度不是獨立的物理變數，它透過兩條路徑影響結果：
  1. 溫度高 → 熔區變長 l → 曲線形狀改變（這由 zone_len_frac 承接）
  2. 溫度高 → 液池對流變強 → delta 變薄 → k_eff 變好
本模組以 (T - T_ref) 的一次項與交互作用項承接第 2 條路徑；若客戶有實測熔區
長度，應優先把 l 當自變數，溫度只是它的代理指標。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from .pfann import K_MIN, K_MAX

_EPS = 1e-12


def _inv_logit_neg(z):
    """數值安全的 1 / (1 + exp(z))。

    直覺寫法 ``np.where(z >= 0, exp(-z)/(1+exp(-z)), 1/(1+exp(z)))`` 是錯的：
    np.where 會把**兩個分支都算完**再挑，所以 z = -800 時仍會執行 exp(800)
    而溢位，噴出 RuntimeWarning 並產生 inf/nan 中間值。這裡改成用遮罩分別
    計算，只有真正需要的那一半會被求值。
    """
    z_arr = np.atleast_1d(np.asarray(z, dtype=np.float64))
    out = np.empty_like(z_arr)
    pos = z_arr >= 0
    ez = np.exp(-z_arr[pos])
    out[pos] = ez / (1.0 + ez)
    out[~pos] = 1.0 / (1.0 + np.exp(z_arr[~pos]))
    return out.reshape(np.shape(z)) if np.shape(z) else out[0]


def keff_from_bps(
    v: float | np.ndarray,
    k0: float,
    delta_over_d: float,
    temp_c: float | np.ndarray | None = None,
    t_ref: float = 0.0,
    beta_t: float = 0.0,
    beta_tv: float = 0.0,
) -> np.ndarray:
    """由製程參數計算 k_eff。

    完整形式（含溫度修正）：

        z = ln(1/k0 - 1) - (delta/D) * v + beta_t * dT + beta_tv * dT * v
        k_eff = 1 / (1 + exp(z))       其中 dT = T - T_ref

    beta_t = beta_tv = 0 時退化為純 BPS。

    Args:
        v: 熔區移動速率 [mm/hr]。
        k0: 平衡分配係數，須在 (0, 1)。
        delta_over_d: delta/D [hr/mm]，須 >= 0。
        temp_c: 熔區溫度 [°C]；None 表示不套用溫度修正。
        t_ref: 溫度中心化基準 [°C]。
        beta_t / beta_tv: 溫度主效應與 溫度×速率 交互作用係數。

    Returns:
        與 v 同形狀的 k_eff，值域 (0, 1)。
    """
    k0 = float(np.clip(k0, K_MIN, K_MAX))
    v = np.asarray(v, dtype=np.float64)
    z = np.log(1.0 / k0 - 1.0) - float(delta_over_d) * v
    if temp_c is not None and (beta_t != 0.0 or beta_tv != 0.0):
        d_t = np.asarray(temp_c, dtype=np.float64) - t_ref
        z = z + beta_t * d_t + beta_tv * d_t * v
    return np.asarray(_inv_logit_neg(z))


def bps_linearize(k_eff: float | np.ndarray) -> np.ndarray:
    """k_eff → z = ln(1/k_eff - 1)。這是全專案 GP 與線性回歸使用的目標變數。

    用這個連結函數（logit 的反號）有三個好處：
      1. 值域無限制，適合高斯過程與線性模型
      2. 反變換 1/(1+exp(z)) 天然保證 k_eff ∈ (0,1)，模型不可能吐出不合物理的值
      3. 對 v 是線性的，符合 BPS
    """
    k = np.clip(np.asarray(k_eff, dtype=np.float64), K_MIN, K_MAX)
    return np.log(1.0 / k - 1.0)


def bps_inverse_linearize(z: float | np.ndarray) -> np.ndarray:
    """z → k_eff = 1 / (1 + exp(z))，數值安全（見 :func:`_inv_logit_neg`）。"""
    return np.asarray(_inv_logit_neg(z))


@dataclass
class BPSModel:
    """擬合完成的 BPS 映射，是 L2 高斯過程的物理基準（parametric baseline）。"""

    element: str
    k0: float
    delta_over_d: float
    beta_t: float = 0.0
    beta_tv: float = 0.0
    t_ref: float = 0.0
    r2: float = float("nan")
    n_points: int = 0
    slope_se: float = float("nan")
    linearity_note: str = ""

    def predict(self, v, temp_c=None) -> np.ndarray:
        return keff_from_bps(
            v, self.k0, self.delta_over_d, temp_c,
            self.t_ref, self.beta_t, self.beta_tv,
        )

    def to_dict(self) -> dict:
        return asdict(self)


def fit_bps_linear(
    v: np.ndarray,
    k_eff: np.ndarray,
    temp_c: np.ndarray | None = None,
    weights: np.ndarray | None = None,
    element: str = "",
    use_temperature: bool = True,
) -> BPSModel:
    """以最小平方法擬合 BPS 線性化模型。

    設計矩陣（use_temperature 且提供 temp_c 時）：
        [1, v, dT, dT*v]
    否則：
        [1, v]

    Args:
        v: (M,) 速率 [mm/hr]。
        k_eff: (M,) 由各批次曲線反解得到的有效分配係數。
        temp_c: (M,) 溫度 [°C]，可為 None。
        weights: (M,) 權重，建議用 1/SE^2（SE 來自 bootstrap）。
        element: 元素名稱，僅作標記。
        use_temperature: 是否加入溫度項。

    Returns:
        BPSModel。linearity_note 會標示線性假設是否成立。
    """
    v = np.asarray(v, dtype=np.float64).ravel()
    z = bps_linearize(np.asarray(k_eff, dtype=np.float64).ravel())
    n = v.size
    if n < 2:
        raise ValueError(f"至少需要 2 個批次才能擬合 BPS，收到 {n}")

    with_t = bool(use_temperature and temp_c is not None and n >= 5)
    t_ref = 0.0
    if with_t:
        t = np.asarray(temp_c, dtype=np.float64).ravel()
        t_ref = float(np.mean(t))
        d_t = t - t_ref
        if np.ptp(d_t) < 1e-9:      # 溫度全都一樣，加進去只會讓矩陣奇異
            with_t = False

    if with_t:
        X = np.column_stack([np.ones(n), v, d_t, d_t * v])
    else:
        X = np.column_stack([np.ones(n), v])

    w = np.ones(n) if weights is None else np.asarray(weights, dtype=np.float64).ravel()
    w = np.clip(w, _EPS, None)
    sw = np.sqrt(w)
    beta, *_ = np.linalg.lstsq(X * sw[:, None], z * sw, rcond=None)

    z_hat = X @ beta
    ss_res = float(np.sum(w * (z - z_hat) ** 2))
    ss_tot = float(np.sum(w * (z - np.average(z, weights=w)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > _EPS else float("nan")

    dof = max(1, n - X.shape[1])
    sigma2 = ss_res / dof
    try:
        cov = sigma2 * np.linalg.inv((X * w[:, None]).T @ X)
        slope_se = float(np.sqrt(max(cov[1, 1], 0.0)))
    except np.linalg.LinAlgError:
        slope_se = float("nan")

    intercept = float(beta[0])
    # ln(1/k0 - 1) = intercept  →  k0 = 1/(1+exp(intercept))
    k0 = float(bps_inverse_linearize(intercept))
    delta_over_d = float(-beta[1])          # 斜率為 -(delta/D)

    note = ""
    if not np.isnan(r2) and r2 < 0.5:
        note = ("線性假設不成立（R²<0.5）。可能有 BPS 以外的機制在作用："
                "氧化夾帶、對流不穩、取樣位置不一致、或量測不確定度大於製程效應。"
                "建議先做量測系統分析，不要硬套模型。")
    elif delta_over_d < 0:
        note = ("擬合出的 delta/D 為負，代表速率越快 k_eff 反而越好——這與 BPS 相反。"
                "通常是資料涵蓋的速率範圍太窄、或有共線的混淆變數（例如速率與溫度同動）。")
    elif n < 5:
        note = f"僅 {n} 個批次，斜率不確定度大，建議至少 5~6 個不同速率的批次。"

    return BPSModel(
        element=element,
        k0=k0,
        delta_over_d=delta_over_d,
        beta_t=float(beta[2]) if with_t else 0.0,
        beta_tv=float(beta[3]) if with_t else 0.0,
        t_ref=t_ref,
        r2=r2,
        n_points=n,
        slope_se=slope_se,
        linearity_note=note,
    )
