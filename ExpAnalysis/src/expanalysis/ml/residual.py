"""L1 — 殘差學習（選配，四道護欄）。

這是唯一真的可能傷準確度的一層，所以：**放最後、標選配、預設關閉、
且必須通過留一批交叉驗證才允許上線**。

概念
----
    最終預測 = 物理模型預測  +  ML 學到的修正
                  (主體)          (小修)

物理模型有它照顧不到的東西：氧化皮夾帶、對流不穩、舟的材質污染、
環境濕度。這些會系統性地讓實測偏離理論，ML 去學這個偏差。

四道護欄（缺一不可）
--------------------
1. **限幅**：修正量硬性限制在物理預測的 ±20% 內，超過就截斷。
   ML 永遠不能推翻物理，只能微調。
2. **禁止外插**：查詢點落在訓練資料範圍外時，直接關閉 ML 修正，退回純物理。
3. **必須證明有用**：用留一批交叉驗證，ML 版沒有明顯贏過純物理版，
   就不上線（``validation.leave_one_batch_out`` 提供這個檢核）。
4. **雙軌顯示**：介面永遠同時顯示「純物理」與「物理+AI」兩個數字，
   工程師隨時看得到 AI 動了多少手腳。

模型選擇
--------
用 Ridge 回歸而非梯度提升樹。原因：修正量本來就該是平滑的小量，
樹模型會產生階梯狀的跳動，而且在 20~40 批的資料量下極易過擬合。
特徵刻意保持極少（速率、溫度、pass、位置），有效參數個位數。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from ..logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class DualTrackPrediction:
    """雙軌預測結果——介面上永遠成對顯示。"""

    physics_only: float
    physics_plus_ai: float
    delta: float
    delta_pct: float
    ai_applied: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResidualCorrector:
    """對 ln(濃度) 的加法修正模型。"""

    model: object = None
    scaler: object = None
    feature_names: tuple[str, ...] = ("speed", "temp", "n_passes", "x_norm", "x_norm^2")
    clip_frac: float = 0.20
    x_lo: np.ndarray = field(default_factory=lambda: np.zeros(3))
    x_hi: np.ndarray = field(default_factory=lambda: np.zeros(3))
    trained: bool = False
    n_train: int = 0
    train_r2: float = float("nan")
    enabled: bool = False              # 預設關閉，須通過 LOBO 驗證才開啟
    gate_note: str = "尚未通過留一批交叉驗證，預設不套用。"

    # ── 訓練 ────────────────────────────────────────────────────
    def fit(self, samples: list[dict]) -> "ResidualCorrector":
        """以 (條件, 位置, 物理預測, 實測) 訓練修正量。

        Args:
            samples: 每筆 {speed, temp, n_passes, x_norm, log_pred, log_obs}。
                     設限點必須先排除——它沒有真值可以學。
        """
        if len(samples) < 30:
            self.trained = False
            self.gate_note = f"可用樣本僅 {len(samples)} 筆（需 >= 30），不訓練殘差模型。"
            return self

        X = np.array([[s["speed"], s["temp"], float(s["n_passes"]),
                       s["x_norm"], s["x_norm"] ** 2] for s in samples], dtype=np.float64)
        y = np.array([s["log_obs"] - s["log_pred"] for s in samples], dtype=np.float64)

        self.scaler = StandardScaler().fit(X)
        self.model = Ridge(alpha=5.0).fit(self.scaler.transform(X), y)
        self.trained = True
        self.n_train = len(samples)
        y_hat = self.model.predict(self.scaler.transform(X))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        self.train_r2 = float(1 - np.sum((y - y_hat) ** 2) / ss_tot) if ss_tot > 1e-12 else float("nan")
        self.x_lo = X[:, :3].min(axis=0)
        self.x_hi = X[:, :3].max(axis=0)
        return self

    # ── 套用 ────────────────────────────────────────────────────
    def _in_range(self, speed: float, temp: float, n_passes: int,
                  margin: float = 0.10) -> bool:
        if not self.trained:
            return False
        q = np.array([speed, temp, float(n_passes)])
        span = np.maximum(self.x_hi - self.x_lo, 1e-9)
        return bool(np.all((q >= self.x_lo - margin * span) &
                           (q <= self.x_hi + margin * span)))

    def correction(self, speed: float, temp: float, n_passes: int,
                   x_norm: np.ndarray) -> np.ndarray:
        """回傳 ln 空間的修正量，已套用限幅護欄。

        限幅：|delta_ln| <= ln(1 + clip_frac)，等價於濃度修正不超過 ±20%。
        """
        if not (self.enabled and self.trained):
            return np.zeros_like(np.asarray(x_norm, dtype=np.float64))
        if not self._in_range(speed, temp, n_passes):
            return np.zeros_like(np.asarray(x_norm, dtype=np.float64))

        x = np.asarray(x_norm, dtype=np.float64).ravel()
        X = np.column_stack([np.full(x.size, speed), np.full(x.size, temp),
                             np.full(x.size, float(n_passes)), x, x ** 2])
        d = self.model.predict(self.scaler.transform(X))
        cap = np.log(1.0 + self.clip_frac)
        return np.clip(d, -cap, cap)

    def apply(self, profiles: dict[str, np.ndarray], speed: float,
              temp: float, n_passes: int) -> dict[str, np.ndarray]:
        """對各元素的濃度分布套用修正。"""
        out = {}
        for el, arr in profiles.items():
            a = np.asarray(arr, dtype=np.float64)
            x = np.linspace(0.0, 1.0, a.size)
            out[el] = a * np.exp(self.correction(speed, temp, n_passes, x))
        return out

    def dual_track(self, physics_value: float, ai_value: float,
                   speed: float, temp: float, n_passes: int) -> DualTrackPrediction:
        """組裝雙軌顯示所需的欄位。"""
        applied = bool(self.enabled and self.trained and
                       self._in_range(speed, temp, n_passes))
        delta = ai_value - physics_value
        pct = delta / physics_value if abs(physics_value) > 1e-12 else 0.0
        if not self.trained:
            reason = self.gate_note
        elif not self.enabled:
            reason = "殘差修正未通過驗收門檻或被使用者關閉，僅顯示物理模型結果。"
        elif not applied:
            reason = "查詢條件落在訓練資料範圍外，已自動退回純物理模式。"
        elif abs(pct) > 0.03:
            reason = f"AI 修正量 {pct:+.1%}，超過 3%，請留意兩者差異。"
        else:
            reason = f"AI 修正量 {pct:+.1%}，在正常範圍內。"
        return DualTrackPrediction(
            physics_only=float(physics_value),
            physics_plus_ai=float(ai_value if applied else physics_value),
            delta=float(delta if applied else 0.0),
            delta_pct=float(pct if applied else 0.0),
            ai_applied=applied, reason=reason,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("model", None)
        d.pop("scaler", None)
        d["x_lo"] = [float(v) for v in np.atleast_1d(self.x_lo)]
        d["x_hi"] = [float(v) for v in np.atleast_1d(self.x_hi)]
        d["feature_names"] = list(self.feature_names)
        return d
