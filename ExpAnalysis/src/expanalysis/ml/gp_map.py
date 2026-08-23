"""L2 — 高斯過程回歸：製程參數 → k_eff 的映射。

為什麼用高斯過程而不是線性回歸
------------------------------
線性回歸是「我先假設它是直線，然後找最好的那條直線」。
高斯過程是「我不假設形狀，只假設相近的 v 應該有相近的 k_eff，
然後讓資料自己決定曲線長什麼樣」。

它額外送你一個線性回歸給不了的東西：**每一點的不確定範圍**。
問一個沒跑過的速率，它會回「k_eff 大概 0.30，但可能在 0.10~0.60 之間」——
這正是外插時需要的護欄。

三個關鍵設計
------------
1. **目標變數用 z = ln(1/k_eff - 1)，不是 k_eff 本身**
   反變換 k = 1/(1+exp(z)) 天然保證 k ∈ (0,1)，GP 不可能吐出不合物理的值；
   而且依 BPS，z 對 v 是線性的，所以 GP 只需要學「偏離直線的部分」。

2. **以 BPS 線性擬合當作 GP 的均值函數（parametric mean）**
   sklearn 的 GP 假設均值為 0，離資料遠的地方會回歸到 0——那沒有物理意義。
   這裡先用 BPS 擬出直線，GP 只建模殘差；外插時自然回歸到 BPS 直線，
   而不是回歸到一個沒意義的常數。這就是 physics-informed（灰箱）做法。

3. **每點的量測不確定度來自 bootstrap**
   k_eff 的 SE 由 bootstrap 給出，轉成 z 空間後餵給 GP 的 alpha 參數。
   擬得準的批次權重高，擬得糊的批次權重低——這是線性回歸做不到的。

資料量：GP 的甜蜜點正好是 10~50 個樣本，它本來就是為小資料設計的。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import warnings as _warnings

from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

from ..logging_setup import get_logger
from ..physics.bps import BPSModel, bps_inverse_linearize, bps_linearize, fit_bps_linear

log = get_logger(__name__)

# GP 輸入特徵。n_passes 不放進來——它不影響 k_eff（k_eff 是單次凝固的性質），
# 只影響最終分布。把它混進來會製造假關聯。
FEATURES = ("speed_mm_hr", "temp_c")


@dataclass
class GPKeffModel:
    """單一元素的 k_eff = f(v, T) 映射。"""

    element: str
    bps: BPSModel
    gp: object = None                      # GaussianProcessRegressor，或 None（資料太少）
    x_mean: np.ndarray = field(default_factory=lambda: np.zeros(2))
    x_std: np.ndarray = field(default_factory=lambda: np.ones(2))
    x_train: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    z_train: np.ndarray = field(default_factory=lambda: np.zeros(0))
    batch_ids: list[str] = field(default_factory=list)
    n_train: int = 0
    gp_used: bool = False
    kernel_repr: str = ""

    # ── 預測 ────────────────────────────────────────────────────
    def _standardize(self, X: np.ndarray) -> np.ndarray:
        return (X - self.x_mean) / self.x_std

    def predict_z(self, speed, temp_c, return_std: bool = True):
        """回傳 (z, z_std)。z = ln(1/k_eff - 1)。"""
        speed = np.atleast_1d(np.asarray(speed, dtype=np.float64))
        temp = np.atleast_1d(np.asarray(temp_c, dtype=np.float64))
        speed, temp = np.broadcast_arrays(speed, temp)
        X = np.column_stack([speed.ravel(), temp.ravel()])

        z_mean = bps_linearize(self.bps.predict(X[:, 0], X[:, 1]))
        if not self.gp_used or self.gp is None:
            # 沒有 GP 時，不確定度以 BPS 斜率的標準誤外推
            se = self.bps.slope_se if np.isfinite(self.bps.slope_se) else 0.5
            std = np.full(X.shape[0], max(se * np.std(X[:, 0]) if X.shape[0] else se, 0.15))
            return (z_mean, std) if return_std else z_mean

        dz, dz_std = self.gp.predict(self._standardize(X), return_std=True)
        z = z_mean + dz
        return (z, dz_std) if return_std else z

    def predict(self, speed, temp_c, return_ci: bool = True, ci: float = 0.95):
        """回傳 k_eff 與信賴區間。

        區間在 z 空間對稱，轉回 k 空間後不對稱——這是正確的，因為 k 有界。
        """
        z, z_std = self.predict_z(speed, temp_c, return_std=True)
        k = bps_inverse_linearize(z)
        if not return_ci:
            return k
        from scipy.stats import norm
        q = norm.ppf(0.5 + ci / 2.0)
        # z 大 → k 小，所以上下界要交換
        k_hi = bps_inverse_linearize(z - q * z_std)
        k_lo = bps_inverse_linearize(z + q * z_std)
        return k, k_lo, k_hi

    def in_training_range(self, speed, temp_c, margin: float = 0.10) -> np.ndarray:
        """查詢點是否落在訓練資料範圍內（含 margin 的邊界緩衝）。

        這是 L1 殘差學習「禁止外插」護欄的判斷依據，UI 也用它標示警示。
        """
        speed = np.atleast_1d(np.asarray(speed, dtype=np.float64))
        temp = np.atleast_1d(np.asarray(temp_c, dtype=np.float64))
        speed, temp = np.broadcast_arrays(speed, temp)
        if self.x_train.shape[0] == 0:
            return np.zeros(speed.size, dtype=bool)
        lo = self.x_train.min(axis=0)
        hi = self.x_train.max(axis=0)
        span = np.maximum(hi - lo, 1e-9)
        lo_m, hi_m = lo - margin * span, hi + margin * span
        X = np.column_stack([speed.ravel(), temp.ravel()])
        return np.all((X >= lo_m) & (X <= hi_m), axis=1)

    def to_dict(self) -> dict:
        return {
            "element": self.element,
            "n_train": self.n_train,
            "gp_used": self.gp_used,
            "kernel": self.kernel_repr,
            "bps": self.bps.to_dict(),
            "batch_ids": self.batch_ids,
            "train_speed": [float(v) for v in self.x_train[:, 0]],
            "train_temp": [float(v) for v in self.x_train[:, 1]],
            "train_keff": [float(v) for v in bps_inverse_linearize(self.z_train)],
            "train_z": [float(v) for v in self.z_train],
        }


@dataclass
class KeffMapping:
    """全部元素的映射集合。"""

    models: dict[str, GPKeffModel] = field(default_factory=dict)
    n_batches: int = 0
    warnings: list[str] = field(default_factory=list)

    def __getitem__(self, element: str) -> GPKeffModel:
        return self.models[element]

    def __contains__(self, element: str) -> bool:
        return element in self.models

    @property
    def elements(self) -> list[str]:
        return sorted(self.models)

    def predict_all(self, speed: float, temp_c: float) -> dict[str, dict]:
        out = {}
        for el, m in self.models.items():
            k, lo, hi = m.predict(speed, temp_c)
            out[el] = {"k_eff": float(k[0]), "k_lo": float(lo[0]), "k_hi": float(hi[0]),
                       "in_range": bool(m.in_training_range(speed, temp_c)[0])}
        return out

    def to_dict(self) -> dict:
        return {
            "n_batches": self.n_batches,
            "elements": self.elements,
            "warnings": self.warnings,
            "models": {el: m.to_dict() for el, m in self.models.items()},
        }


def fit_keff_mapping(
    rows: list[dict],
    use_gp: bool = True,
    min_gp_points: int = 6,
) -> KeffMapping:
    """由各批次的 k_eff 擬合結果建立映射。

    Args:
        rows: 每筆 {batch_id, element, speed_mm_hr, temp_c, k_eff, k_se(optional)}。
        use_gp: False 時只做 BPS 線性回歸（作為對照組與退回路徑）。
        min_gp_points: 少於此數量就不啟用 GP——樣本太少時 GP 的超參數估計
                       本身就不可靠，硬用反而更差。

    Returns:
        KeffMapping
    """
    by_el: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("k_eff") is None or not np.isfinite(r["k_eff"]):
            continue
        by_el.setdefault(r["element"], []).append(r)

    mapping = KeffMapping(n_batches=len({r["batch_id"] for r in rows}))

    for el, items in sorted(by_el.items()):
        v = np.array([r["speed_mm_hr"] for r in items], dtype=np.float64)
        t = np.array([r["temp_c"] for r in items], dtype=np.float64)
        k = np.array([r["k_eff"] for r in items], dtype=np.float64)
        z = bps_linearize(k)
        ids = [r["batch_id"] for r in items]

        # z 空間的量測標準差：由 k 的 SE 以一階近似轉換
        #   dz/dk = -1 / (k * (1 - k))
        se_k = np.array([r.get("k_se") or np.nan for r in items], dtype=np.float64)
        with np.errstate(divide="ignore", invalid="ignore"):
            se_z = np.abs(se_k / np.clip(k * (1.0 - k), 1e-6, None))
        se_z = np.where(np.isfinite(se_z) & (se_z > 0), se_z, np.nan)
        default_se = np.nanmedian(se_z) if np.any(np.isfinite(se_z)) else 0.20
        se_z = np.where(np.isfinite(se_z), se_z, default_se)
        # 下限 0.08：bootstrap 只涵蓋「量測雜訊」，涵蓋不到批間的未建模變異
        # （氧化程度、舟的狀態、進料微量差異）。在 pass 次數多的批次，
        # k_eff 的量測不確定度可以低到 1e-4，若直接採用，GP 會把每一點都
        # 當成鐵律去內插，等於過擬合。0.08 是保守的工程下限，並在文件中揭露。
        se_z = np.clip(se_z, 0.08, 2.0)

        if v.size < 2:
            mapping.warnings.append(f"{el}：只有 {v.size} 個批次，無法建立映射。")
            continue

        bps = fit_bps_linear(v, k, t, weights=1.0 / se_z ** 2, element=el)
        model = GPKeffModel(element=el, bps=bps,
                            x_train=np.column_stack([v, t]), z_train=z,
                            batch_ids=ids, n_train=v.size)

        if use_gp and v.size >= min_gp_points:
            X = np.column_stack([v, t])
            model.x_mean = X.mean(axis=0)
            model.x_std = np.where(X.std(axis=0) > 1e-9, X.std(axis=0), 1.0)
            Xs = (X - model.x_mean) / model.x_std
            residual = z - bps_linearize(bps.predict(v, t))    # GP 只學殘差

            kernel = (ConstantKernel(1.0, (1e-3, 1e3))
                      * Matern(length_scale=[1.0, 1.0],
                               length_scale_bounds=(0.2, 20.0), nu=2.5)
                      + WhiteKernel(noise_level=0.05, noise_level_bounds=(1e-5, 1.0)))
            try:
                gp = GaussianProcessRegressor(
                    kernel=kernel, alpha=se_z ** 2,
                    normalize_y=False, n_restarts_optimizer=4, random_state=0,
                )
                # 超參數觸及邊界是預期行為（殘差幾乎為零時 GP 會退化成常數），
                # 這代表「BPS 直線已經解釋得夠好」，不是錯誤，不該噴警告給使用者。
                with _warnings.catch_warnings():
                    _warnings.simplefilter("ignore", ConvergenceWarning)
                    gp.fit(Xs, residual)
                model.gp = gp
                model.gp_used = True
                model.kernel_repr = str(gp.kernel_)
            except (ValueError, np.linalg.LinAlgError) as exc:
                log.warning("%s 的 GP 擬合失敗（%s），退回 BPS 線性模型", el, exc)
                mapping.warnings.append(f"{el}：GP 擬合失敗，已退回 BPS 線性模型。")
        elif use_gp:
            mapping.warnings.append(
                f"{el}：僅 {v.size} 個批次（<{min_gp_points}），"
                f"未啟用高斯過程，使用 BPS 線性模型。")

        if bps.linearity_note:
            mapping.warnings.append(f"{el}：{bps.linearity_note}")

        mapping.models[el] = model

    return mapping
