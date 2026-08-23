"""L4 — 貝氏最佳化驅動的序列實驗設計。

這是整套 AI 架構裡最值錢、也最好賣的一層。

客戶真正的痛點
--------------
不是「沒有模型」，而是**每跑一批實驗都很貴、很慢**。銦是貴金屬，一批可能
好幾天、好幾十萬。所以真正該回答的問題是：

    「下一批，我該設定什麼參數，才能學到最多東西？」

運作方式
--------
1. GP 看目前所有批次，畫出「參數 → 得料率」的地圖，含不確定範圍
2. 找出兩種地方：有希望的（預測得料率高）、不確定的（灰帶很寬，沒人去過）
3. 用 Expected Improvement 在兩者之間權衡，指定下一組 (T, v, n)
4. 跑完這批，資料回填，地圖更新，再問下一批

價值主張
--------
    傳統全因子 DOE：3 溫度 × 4 速率 × 3 次數 = 36 批
    貝氏最佳化：    通常 10~15 批就找到相近的最佳點

一批成本 10 萬的話，這就是省 200 萬。``doe_comparison`` 會用模型當作
虛擬產線，把這個對比實際跑出來給客戶看，而不是只講概念。

為什麼零風險
------------
它只是**建議做什麼實驗**，最終的準確度來自真實實驗資料，不是模型猜的。
就算建議得不好，最壞情況也只是多跑幾批——不會產生錯誤的結論。

順帶一提：貝氏最佳化正是 AI 界拿來調神經網路超參數的標準工具，
說它是 AI 一點都不心虛。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np
from scipy.stats import norm
import warnings as _warnings

from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

from ..logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class BOSuggestion:
    rank: int
    speed_mm_hr: float
    temp_c: float
    n_passes: int
    predicted_yield: float
    predicted_std: float
    expected_improvement: float
    rationale: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _build_gp(X: np.ndarray, y: np.ndarray, seed: int = 0) -> GaussianProcessRegressor:
    kernel = (ConstantKernel(1.0, (1e-3, 1e3))
              * Matern(length_scale=np.ones(X.shape[1]),
                       length_scale_bounds=(0.1, 30.0), nu=2.5)
              + WhiteKernel(noise_level=1e-3, noise_level_bounds=(1e-6, 1e-1)))
    gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True,
                                  n_restarts_optimizer=4, random_state=seed)
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", ConvergenceWarning)
        gp.fit(X, y)
    return gp


def _expected_improvement(mu: np.ndarray, sigma: np.ndarray,
                          best: float, xi: float = 0.01) -> np.ndarray:
    """Expected Improvement 取得函數。

    xi 控制探索傾向：大一點會更願意去沒人去過的地方。0.01 是常用預設，
    在「只有十幾批預算」的情境下略偏開發（exploitation）是合理的。
    """
    sigma = np.maximum(sigma, 1e-9)
    imp = mu - best - xi
    z = imp / sigma
    return imp * norm.cdf(z) + sigma * norm.pdf(z)


def _candidate_grid(speed_range, temp_range, pass_choices,
                    n_speed=40, n_temp=25) -> np.ndarray:
    v = np.linspace(*speed_range, n_speed)
    t = np.linspace(*temp_range, n_temp)
    p = np.asarray(pass_choices, dtype=np.float64)
    V, T, P = np.meshgrid(v, t, p, indexing="ij")
    return np.column_stack([V.ravel(), T.ravel(), P.ravel()])


def suggest_next_batches(
    observations: list[dict],
    speed_range: tuple[float, float] = (0.5, 8.0),
    temp_range: tuple[float, float] = (160.0, 210.0),
    pass_choices: tuple[int, ...] = (4, 6, 8, 10, 12),
    n_suggest: int = 3,
    xi: float = 0.01,
    seed: int = 0,
) -> dict:
    """建議接下來該跑的幾批實驗。

    Args:
        observations: 每筆 {speed_mm_hr, temp_c, n_passes, yield_frac[, batch_id]}。
        n_suggest: 要建議幾批。批次模式用 kriging believer：把上一個建議點的
                   GP 預測值當成「假觀測」餵回去再算下一個，避免三個建議擠在
                   同一個位置。

    Returns:
        dict：suggestions / model_r2 / n_observations / notes
    """
    obs = [o for o in observations
           if o.get("yield_frac") is not None and np.isfinite(o["yield_frac"])]
    if len(obs) < 4:
        return {
            "suggestions": [],
            "n_observations": len(obs),
            "notes": [f"目前只有 {len(obs)} 批可用資料，少於 4 批時貝氏最佳化沒有意義。"
                      "建議先用涵蓋速率範圍的篩選性實驗（screening DOE）跑 5~6 批，"
                      "再切換到序列最佳化。"],
        }

    X = np.array([[o["speed_mm_hr"], o["temp_c"], float(o["n_passes"])] for o in obs])
    y = np.array([float(o["yield_frac"]) for o in obs])

    x_mean, x_std = X.mean(axis=0), np.where(X.std(axis=0) > 1e-9, X.std(axis=0), 1.0)
    Xs = (X - x_mean) / x_std

    try:
        gp = _build_gp(Xs, y, seed)
    except (ValueError, np.linalg.LinAlgError) as exc:
        log.warning("貝氏最佳化的 GP 擬合失敗：%s", exc)
        return {"suggestions": [], "n_observations": len(obs),
                "notes": [f"GP 擬合失敗（{exc}），無法給出建議。"]}

    cand = _candidate_grid(speed_range, temp_range, pass_choices)
    cand_s = (cand - x_mean) / x_std

    aug_X, aug_y = list(Xs), list(y)
    best_obs = float(np.max(y))
    suggestions: list[BOSuggestion] = []

    for rank in range(1, n_suggest + 1):
        mu, sigma = gp.predict(cand_s, return_std=True)
        ei = _expected_improvement(mu, sigma, best_obs, xi)

        # 避免建議一個與既有批次幾乎相同的條件（標準化距離 < 0.25）
        d = np.min(np.linalg.norm(cand_s[:, None, :] - np.asarray(aug_X)[None, :, :],
                                  axis=2), axis=1)
        ei = np.where(d < 0.25, 0.0, ei)
        if not np.any(ei > 0):
            ei = sigma        # EI 全零時退回純探索（挑最不確定的地方）

        idx = int(np.argmax(ei))
        v, t, p = cand[idx]
        explore = sigma[idx] > np.median(sigma)
        suggestions.append(BOSuggestion(
            rank=rank, speed_mm_hr=round(float(v), 2), temp_c=round(float(t), 1),
            n_passes=int(round(p)),
            predicted_yield=float(mu[idx]), predicted_std=float(sigma[idx]),
            expected_improvement=float(ei[idx]),
            rationale=(
                f"模型預測得料率 {mu[idx]:.1%} ± {sigma[idx]:.1%}。"
                + ("此處不確定度高於中位數，這批的主要價值在**縮小模型的未知區**，"
                   "即使結果不如預期也很有資訊量。"
                   if explore else
                   "此處模型已相對有把握，這批的主要價值在**確認最佳點**。")
            ),
        ))

        # kriging believer：把預測值當成假觀測，讓下一個建議跑去別的地方
        aug_X.append(cand_s[idx])
        aug_y.append(float(mu[idx]))
        try:
            gp = _build_gp(np.asarray(aug_X), np.asarray(aug_y), seed + rank)
        except (ValueError, np.linalg.LinAlgError):
            break

    # 用最初那個只含真實觀測的 GP 算 R²；此處的 gp 已被 kriging believer 的
    # 假觀測污染，不能拿來評估對真實資料的擬合度。
    try:
        gp0 = _build_gp(Xs, y, seed)
        y_hat = gp0.predict(Xs)
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = float(1 - np.sum((y - y_hat) ** 2) / ss_tot) if ss_tot > 1e-12 else None
    except (ValueError, np.linalg.LinAlgError):
        r2 = None

    return {
        "suggestions": [s.to_dict() for s in suggestions],
        "n_observations": len(obs),
        "best_observed_yield": best_obs,
        "model_r2": r2,
        "notes": [
            "這些建議只影響「下一批做什麼實驗」，不影響任何已完成批次的分析結果。"
            "最終準確度來自真實實驗，不是模型猜的。",
        ],
    }


# ─────────────────────────────────────────────────────────────────
#  DOE 對比模擬：把「省多少批」實際跑出來
# ─────────────────────────────────────────────────────────────────

@dataclass
class DOEComparison:
    factorial_n: int
    factorial_best: float
    factorial_trace: list[float] = field(default_factory=list)
    bo_n: int = 0
    bo_best: float = 0.0
    bo_trace: list[float] = field(default_factory=list)
    bo_batches_to_match: int | None = None
    batches_saved: int = 0
    cost_per_batch: float = 100000.0
    cost_saved: float = 0.0
    seed_n: int = 5
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def doe_comparison(
    oracle,
    speed_range: tuple[float, float] = (0.5, 8.0),
    temp_range: tuple[float, float] = (160.0, 210.0),
    pass_choices: tuple[int, ...] = (6, 8, 10),
    factorial_speeds: int = 4,
    factorial_temps: int = 3,
    bo_budget: int = 12,
    seed_n: int = 5,
    cost_per_batch: float = 100000.0,
    seed: int = 7,
) -> DOEComparison:
    """在虛擬產線上比較「全因子 DOE」與「貝氏最佳化」。

    Args:
        oracle: callable(speed, temp, n_passes) -> yield_frac。
                實務上用已擬合的映射 + 物理模擬當虛擬產線；它不是真值，
                但用**同一個** oracle 比較兩種策略是公平的。
        factorial_speeds / factorial_temps: 全因子的水準數。
        bo_budget: 貝氏最佳化總共允許跑幾批（含 seed_n 批起始實驗）。
        seed_n: 起始的篩選性實驗批數（用 Latin hypercube 式分層抽樣）。

    Returns:
        DOEComparison，含兩條「跑到第 n 批時的最佳得料率」曲線，可直接畫圖。
    """
    rng = np.random.default_rng(seed)

    # ── 策略 A：全因子 ───────────────────────────────────────────
    fv = np.linspace(*speed_range, factorial_speeds)
    ft = np.linspace(*temp_range, factorial_temps)
    fp = np.asarray(pass_choices, dtype=float)
    fact_points = [(v, t, int(p)) for v in fv for t in ft for p in fp]
    rng.shuffle(fact_points)

    fact_trace, best = [], -np.inf
    for (v, t, p) in fact_points:
        best = max(best, float(oracle(v, t, p)))
        fact_trace.append(best)
    fact_best = fact_trace[-1] if fact_trace else 0.0

    # ── 策略 B：seed + 貝氏最佳化 ────────────────────────────────
    edges = np.linspace(*speed_range, seed_n + 1)
    seed_v = rng.uniform(edges[:-1], edges[1:])
    seed_t = rng.uniform(*temp_range, seed_n)
    seed_p = rng.choice(pass_choices, seed_n)

    obs = []
    bo_trace, best_bo = [], -np.inf
    for i in range(seed_n):
        yv = float(oracle(seed_v[i], seed_t[i], int(seed_p[i])))
        obs.append({"speed_mm_hr": float(seed_v[i]), "temp_c": float(seed_t[i]),
                    "n_passes": int(seed_p[i]), "yield_frac": yv})
        best_bo = max(best_bo, yv)
        bo_trace.append(best_bo)

    for step in range(bo_budget - seed_n):
        out = suggest_next_batches(obs, speed_range, temp_range, pass_choices,
                                   n_suggest=1, seed=seed + step)
        sug = out.get("suggestions") or []
        if not sug:
            break
        s = sug[0]
        yv = float(oracle(s["speed_mm_hr"], s["temp_c"], s["n_passes"]))
        obs.append({"speed_mm_hr": s["speed_mm_hr"], "temp_c": s["temp_c"],
                    "n_passes": s["n_passes"], "yield_frac": yv})
        best_bo = max(best_bo, yv)
        bo_trace.append(best_bo)

    # 貝氏最佳化第幾批就追上全因子的最終結果（允許 1% 的差距）
    match = None
    for i, val in enumerate(bo_trace, start=1):
        if val >= fact_best * 0.99:
            match = i
            break

    saved = (len(fact_points) - match) if match else 0
    return DOEComparison(
        factorial_n=len(fact_points), factorial_best=float(fact_best),
        factorial_trace=[float(v) for v in fact_trace],
        bo_n=len(bo_trace), bo_best=float(best_bo),
        bo_trace=[float(v) for v in bo_trace],
        bo_batches_to_match=match, batches_saved=int(max(saved, 0)),
        cost_per_batch=cost_per_batch,
        cost_saved=float(max(saved, 0) * cost_per_batch),
        seed_n=seed_n,
        notes=[
            "本對比在「以既有資料擬合出的模型」作為虛擬產線上進行，"
            "用來說明兩種實驗策略的效率差異，不是對真實產線的績效承諾。",
            "全因子的順序已隨機打散，避免因為剛好先跑到最佳點而高估其效率。",
        ],
    )
