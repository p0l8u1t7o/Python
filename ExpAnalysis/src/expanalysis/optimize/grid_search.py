"""正向模擬與 (T, v, n) 網格掃描。

流程
----
    (T, v)  --GP/BPS 映射-->  各元素 k_eff  --物理模擬-->  全錠雜質分布
            --純度視窗-->  6N 得料率

回答客戶需求 2（預測雜質分布、判斷高純區與雜質濃縮區位置）與需求 3
（參數最佳化建議）。

不確定性怎麼帶進來
------------------
GP 對每個 k_eff 都給出信賴區間。本模組同時計算三條路徑：

    optimistic   用 k_lo（每個元素都在區間下界，最順利的情況）
    nominal      用 k 的中位數估計
    pessimistic  用 k_hi（最不順利的情況）

回報時三個都給。**只給一個數字的最佳化建議是不負責任的**——尤其是在
外插區，pessimistic 與 nominal 的差距會自己把「這裡不可信」講出來。

外插保護
--------
查詢點若落在訓練資料範圍外，回傳結果會標記 ``in_training_range=False``，
UI 上以警示色顯示，且不套用 L1 殘差修正。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np

from ..logging_setup import get_logger
from ..physics.multipass import find_ultimate_pass
from ..physics.profile_grid import get_profile_grid
from ..physics.yield_calc import compute_purity_window, total_impurity

log = get_logger(__name__)


@dataclass
class ForwardPrediction:
    """單一組 (T, v, n) 的正向模擬結果。"""

    speed_mm_hr: float
    temp_c: float
    n_passes: int
    zone_len_frac: float
    x_norm: list[float]
    profiles: dict[str, list[float]]          # 各元素的分布 [ppm]
    total_ppm: list[float]
    k_eff: dict[str, float]
    k_ci: dict[str, list[float]]              # {元素: [lo, hi]}
    yield_nominal: float = 0.0
    yield_optimistic: float = 0.0
    yield_pessimistic: float = 0.0
    window: dict = field(default_factory=dict)
    in_training_range: bool = True
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _yield_for_ks(grid, ks: dict[str, float], c0: dict[str, float],
                  threshold: float, head_crop: float,
                  per_element_spec: dict[str, float] | None = None):
    profiles = {el: grid.profile_at_k(k, c0.get(el, 1.0)) for el, k in ks.items()}
    win = compute_purity_window(grid.x_norm, profiles, threshold,
                                per_element_ppm=per_element_spec,
                                head_crop_frac=head_crop)
    return win, profiles


def forward_predict(
    mapping,
    speed_mm_hr: float,
    temp_c: float,
    n_passes: int,
    zone_len_frac: float,
    c0_ppm: dict[str, float],
    threshold_ppm: float = 1.0,
    head_crop_frac: float = 0.03,
    per_element_spec: dict[str, float] | None = None,
    n_cells: int = 240,
    corrector=None,
) -> ForwardPrediction:
    """給定製程條件，預測全錠雜質分布與 6N 得料率。

    Args:
        mapping: KeffMapping。
        c0_ppm: {元素: 進料濃度}。
        corrector: 選配的 L1 ResidualCorrector；None 表示純物理。

    Returns:
        ForwardPrediction
    """
    grid = get_profile_grid(zone_len_frac, n_passes, n_cells)
    elements = [el for el in mapping.elements if el in c0_ppm]
    if not elements:
        raise ValueError("mapping 與 c0_ppm 沒有共同的元素")

    k_nom, k_lo, k_hi, in_range = {}, {}, {}, True
    for el in elements:
        k, lo, hi = mapping[el].predict(speed_mm_hr, temp_c)
        k_nom[el] = float(k[0])
        k_lo[el] = float(lo[0])
        k_hi[el] = float(hi[0])
        in_range = in_range and bool(mapping[el].in_training_range(speed_mm_hr, temp_c)[0])

    win_nom, profiles = _yield_for_ks(grid, k_nom, c0_ppm, threshold_ppm,
                                      head_crop_frac, per_element_spec)
    win_opt, _ = _yield_for_ks(grid, k_lo, c0_ppm, threshold_ppm,
                               head_crop_frac, per_element_spec)
    win_pes, _ = _yield_for_ks(grid, k_hi, c0_ppm, threshold_ppm,
                               head_crop_frac, per_element_spec)

    warnings: list[str] = []
    if not in_range:
        warnings.append(
            "查詢條件落在歷史批次涵蓋範圍之外。此處為外插，模型不確定度大幅上升；"
            "已自動停用 AI 修正、僅顯示物理模型結果。建議先安排一批實驗驗證。")

    if corrector is not None and in_range:
        try:
            profiles = corrector.apply(profiles, speed_mm_hr, temp_c, n_passes)
            win_nom = compute_purity_window(grid.x_norm, profiles, threshold_ppm,
                                            per_element_ppm=per_element_spec,
                                            head_crop_frac=head_crop_frac)
        except (ValueError, RuntimeError) as exc:
            log.warning("殘差修正套用失敗（%s），退回純物理", exc)
            warnings.append("殘差修正套用失敗，已退回純物理模型。")

    return ForwardPrediction(
        speed_mm_hr=float(speed_mm_hr), temp_c=float(temp_c),
        n_passes=int(n_passes), zone_len_frac=float(zone_len_frac),
        x_norm=[round(float(v), 5) for v in grid.x_norm],
        profiles={el: [float(v) for v in profiles[el]] for el in elements},
        total_ppm=[float(v) for v in total_impurity(profiles)],
        k_eff={el: round(k_nom[el], 5) for el in elements},
        k_ci={el: [round(k_lo[el], 5), round(k_hi[el], 5)] for el in elements},
        yield_nominal=win_nom.yield_frac,
        yield_optimistic=win_opt.yield_frac,
        yield_pessimistic=win_pes.yield_frac,
        window=win_nom.to_dict(),
        in_training_range=in_range,
        warnings=warnings,
    )


@dataclass
class OptimizationSuggestion:
    speed_mm_hr: float
    temp_c: float
    n_passes: int
    yield_nominal: float
    yield_pessimistic: float
    yield_optimistic: float
    in_training_range: bool
    throughput_mm_hr: float                # 速率 / 次數 的等效產能指標
    limiting_element: str = ""
    rationale: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GridScanResult:
    speeds: list[float]
    temps: list[float]
    passes: list[int]
    # heatmap[p][t][v] = 得料率；前端畫熱圖用
    yield_grid: list = field(default_factory=list)
    in_range_grid: list = field(default_factory=list)
    best: OptimizationSuggestion | None = None
    best_robust: OptimizationSuggestion | None = None
    best_throughput: OptimizationSuggestion | None = None
    pass_advice: dict = field(default_factory=dict)
    n_evaluated: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("best", "best_robust", "best_throughput"):
            d[key] = getattr(self, key).to_dict() if getattr(self, key) else None
        return d


def scan_parameter_grid(
    mapping,
    c0_ppm: dict[str, float],
    zone_len_frac: float,
    speed_range: tuple[float, float] = (0.5, 8.0),
    temp_range: tuple[float, float] = (160.0, 210.0),
    pass_choices: tuple[int, ...] = (6, 8, 10, 12),
    n_speed: int = 24,
    n_temp: int = 16,
    threshold_ppm: float = 1.0,
    head_crop_frac: float = 0.03,
    per_element_spec: dict[str, float] | None = None,
    n_cells: int = 200,
    throughput_weight: float = 0.0,
) -> GridScanResult:
    """在 (T, v, n) 網格上掃描得料率，並給出三種建議。

    三種建議的意義不同，都要給客戶看：
      best             純粹追求最高得料率（可能落在外插區或很慢的速率）
      best_robust      只在訓練資料範圍內，且以**悲觀值**排序——這是可以
                       直接下給產線的建議
      best_throughput  在得料率不低於最佳值 95% 的前提下，速率最快的組合
                       ——這是真正省錢的那一組

    Args:
        throughput_weight: >0 時，目標改為 yield - w * (n_passes / speed)，
                           把產能成本納入。預設 0（純看得料率）。
    """
    elements = [el for el in mapping.elements if el in c0_ppm]
    if not elements:
        raise ValueError("mapping 與 c0_ppm 沒有共同的元素")

    speeds = np.linspace(*speed_range, n_speed)
    temps = np.linspace(*temp_range, n_temp)

    # 先把每個 (v,T) 的 k_eff 與範圍旗標算好，避免在三層迴圈裡重複呼叫 GP
    VV, TT = np.meshgrid(speeds, temps, indexing="ij")
    flat_v, flat_t = VV.ravel(), TT.ravel()
    k_nom_map, k_hi_map, k_lo_map, in_range = {}, {}, {}, np.ones(flat_v.size, dtype=bool)
    for el in elements:
        k, lo, hi = mapping[el].predict(flat_v, flat_t)
        k_nom_map[el], k_lo_map[el], k_hi_map[el] = np.asarray(k), np.asarray(lo), np.asarray(hi)
        in_range &= mapping[el].in_training_range(flat_v, flat_t)

    in_range_plane = in_range.reshape(n_speed, n_temp).tolist()
    yield_grid, in_range_grid = [], []
    best = best_robust = None
    best_score = best_robust_score = -np.inf
    records = []

    for npass in pass_choices:
        grid = get_profile_grid(zone_len_frac, npass, n_cells)
        plane = np.zeros((n_speed, n_temp))
        for idx in range(flat_v.size):
            i, j = divmod(idx, n_temp)
            ks = {el: float(k_nom_map[el][idx]) for el in elements}
            win, _ = _yield_for_ks(grid, ks, c0_ppm, threshold_ppm,
                                   head_crop_frac, per_element_spec)
            plane[i, j] = win.yield_frac

            score = win.yield_frac - throughput_weight * (npass / max(flat_v[idx], 1e-6))
            if score > best_score:
                ks_p = {el: float(k_hi_map[el][idx]) for el in elements}
                ks_o = {el: float(k_lo_map[el][idx]) for el in elements}
                win_p, _ = _yield_for_ks(grid, ks_p, c0_ppm, threshold_ppm, head_crop_frac, per_element_spec)
                win_o, _ = _yield_for_ks(grid, ks_o, c0_ppm, threshold_ppm, head_crop_frac, per_element_spec)
                best_score = score
                best = OptimizationSuggestion(
                    speed_mm_hr=round(float(flat_v[idx]), 2), temp_c=round(float(flat_t[idx]), 1),
                    n_passes=npass, yield_nominal=win.yield_frac,
                    yield_pessimistic=win_p.yield_frac, yield_optimistic=win_o.yield_frac,
                    in_training_range=bool(in_range[idx]),
                    throughput_mm_hr=float(flat_v[idx]) / npass,
                    limiting_element=win.limiting_element,
                )

            if in_range[idx]:
                ks_p = {el: float(k_hi_map[el][idx]) for el in elements}
                win_p, _ = _yield_for_ks(grid, ks_p, c0_ppm, threshold_ppm,
                                         head_crop_frac, per_element_spec)
                rscore = win_p.yield_frac - throughput_weight * (npass / max(flat_v[idx], 1e-6))
                if rscore > best_robust_score:
                    best_robust_score = rscore
                    ks_o = {el: float(k_lo_map[el][idx]) for el in elements}
                    win_o, _ = _yield_for_ks(grid, ks_o, c0_ppm, threshold_ppm,
                                             head_crop_frac, per_element_spec)
                    best_robust = OptimizationSuggestion(
                        speed_mm_hr=round(float(flat_v[idx]), 2), temp_c=round(float(flat_t[idx]), 1),
                        n_passes=npass, yield_nominal=win.yield_frac,
                        yield_pessimistic=win_p.yield_frac,
                        yield_optimistic=win_o.yield_frac,
                        in_training_range=True,
                        throughput_mm_hr=float(flat_v[idx]) / npass,
                        limiting_element=win.limiting_element,
                    )
                records.append((win.yield_frac, float(flat_v[idx]), float(flat_t[idx]),
                                npass, win.limiting_element, win_p.yield_frac))

        yield_grid.append(plane.tolist())
        # 外插旗標只跟 (v, T) 有關、與 pass 次數無關，各層共用同一份即可
        in_range_grid.append(in_range_plane)

    # ── 產能導向建議：得料率不低於最佳值 95% 中，等效產能最高者 ─────
    best_throughput = None
    if records:
        top = max(r[0] for r in records)
        cands = [r for r in records if r[0] >= 0.95 * top]
        y, v, t, p, lim, y_pes = max(cands, key=lambda r: r[1] / r[3])
        best_throughput = OptimizationSuggestion(
            speed_mm_hr=round(v, 2), temp_c=round(t, 1), n_passes=p, yield_nominal=y,
            yield_pessimistic=y_pes, yield_optimistic=y, in_training_range=True,
            throughput_mm_hr=v / p, limiting_element=lim,
            rationale=(f"在得料率不低於最佳值 95%（{top:.1%}）的所有組合中，"
                       f"等效產能（速率/次數）最高的一組。"),
        )

    # ── pass 次數建議（用最佳條件的 k_eff）────────────────────────
    pass_advice = {}
    if best_robust is not None:
        ks = {el: float(mapping[el].predict(best_robust.speed_mm_hr,
                                            best_robust.temp_c, return_ci=False)[0])
              for el in elements}
        pass_advice = find_ultimate_pass(
            np.array([ks[el] for el in elements]), zone_len_frac,
            c0=np.array([c0_ppm[el] for el in elements]),
            max_passes=max(20, max(pass_choices)), n_cells=n_cells,
            threshold_ppm=threshold_ppm, head_crop_frac=head_crop_frac,
            elements=elements,
        )

    notes = []
    if best is not None and not best.in_training_range:
        notes.append("最高得料率的組合落在歷史資料範圍之外，屬於外插預測。"
                     "請以 best_robust 作為可直接執行的建議，並把 best 當成"
                     "「值得安排一批實驗去驗證」的方向。")
    if best_robust is None:
        notes.append("沒有任何網格點落在歷史資料涵蓋範圍內——"
                     "請確認掃描範圍是否設得離歷史條件太遠。")

    return GridScanResult(
        speeds=[float(v) for v in speeds],
        temps=[float(v) for v in temps],
        passes=list(pass_choices),
        yield_grid=yield_grid,
        in_range_grid=in_range_grid,
        best=best, best_robust=best_robust, best_throughput=best_throughput,
        pass_advice=pass_advice,
        n_evaluated=int(flat_v.size * len(pass_choices)),
        notes=notes,
    )
