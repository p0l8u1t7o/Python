"""驗證與驗收 — 把「不影響準確性」變成可量化、可驗收的條款。

留一批交叉驗證（Leave-One-Batch-Out, LOBO）
-------------------------------------------
白話：假裝沒看過第 7 批，用其他所有批訓練，然後預測第 7 批，比對真值。
每一批都輪一次。

為什麼是「留一**批**」而不是「留一**點**」：同一批內的取樣點高度相關
（共用同一組製程條件、同一次分析），留一點會嚴重高估模型能力。這是
製程資料最常見的資料洩漏陷阱。

兩套並跑
--------
    純物理     只用 Pfann + BPS/GP 映射
    物理 + AI  再加上 L1 殘差修正

輸出的比較表就是**驗收文件**。如果 AI 那欄沒有比較好，就誠實地只交付
純物理版——這反而會建立客戶對你的信任。

建議寫進合約的驗收條件
----------------------
  1. AI 模組之預測誤差不得高於純物理模型基準（以 LOBO 衡量）
  2. 所有預測同時提供物理基準值與不確定區間
  3. 超出訓練資料範圍之查詢，系統自動退回純物理模式並標示警告
  4. AI 不參與任何設備控制決策

第 1 條把「AI 可能變差」的風險完全消滅了——因為 AI 只有在被證明更好時
才上線。這是能給客戶最強的保證，而且做得到。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np

from ..logging_setup import get_logger
from ..physics.profile_grid import PositionSlice, get_profile_grid

log = get_logger(__name__)


@dataclass
class LOBOResult:
    n_batches: int
    n_points: int
    physics_mae_ppm: float
    physics_max_ppm: float
    physics_mae_log: float
    ai_mae_ppm: float = float("nan")
    ai_max_ppm: float = float("nan")
    ai_mae_log: float = float("nan")
    ai_better: bool = False
    improvement_pct: float = 0.0
    gate_passed: bool = False
    per_batch: list[dict] = field(default_factory=list)
    per_element: dict = field(default_factory=dict)
    verdict: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def leave_one_batch_out(
    details: list,
    fits: dict[str, dict],
    use_residual_ai: bool = True,
    min_train_batches: int = 5,
    n_cells: int = 240,
) -> LOBOResult:
    """執行留一批交叉驗證。

    Args:
        details: list[BatchDetail]。
        fits: {batch_id: {element: KeffFit}}，主擬合結果（供訓練映射用）。
        use_residual_ai: 是否同時評估「物理 + AI」路徑。

    Returns:
        LOBOResult
    """
    from .gp_map import fit_keff_mapping
    from .residual import ResidualCorrector

    by_id = {d.batch.batch_id: d for d in details}
    ids = [bid for bid in by_id if bid in fits and fits[bid]]
    if len(ids) < min_train_batches + 1:
        return LOBOResult(
            n_batches=len(ids), n_points=0,
            physics_mae_ppm=float("nan"), physics_max_ppm=float("nan"),
            physics_mae_log=float("nan"),
            verdict="批次數不足，無法執行留一批交叉驗證。",
            notes=[f"目前 {len(ids)} 批，至少需要 {min_train_batches + 1} 批。"],
        )

    rows_all = [
        {"batch_id": bid, "element": el, "k_eff": f.k_eff, "k_se": f.k_se,
         "speed_mm_hr": by_id[bid].batch.speed_mm_hr,
         "temp_c": by_id[bid].batch.temp_c}
        for bid, per_el in fits.items() if bid in by_id
        for el, f in per_el.items()
    ]

    per_batch, per_el_err = [], {}
    phys_abs, ai_abs, phys_log, ai_log = [], [], [], []

    for held in ids:
        train_rows = [r for r in rows_all if r["batch_id"] != held]
        try:
            mapping = fit_keff_mapping(train_rows, use_gp=True)
        except (ValueError, np.linalg.LinAlgError) as exc:
            log.warning("LOBO：留出 %s 時映射擬合失敗（%s），略過", held, exc)
            continue

        corrector = None
        if use_residual_ai:
            samples = _residual_samples(
                [by_id[b] for b in ids if b != held], fits, mapping, n_cells)
            corrector = ResidualCorrector().fit(samples)
            corrector.enabled = corrector.trained

        d = by_id[held]
        b = d.batch
        b_phys, b_ai, b_n = [], [], 0

        for el in d.elements:
            if el not in mapping:
                continue
            pts = [p for p in d.points(el) if not p.censored]
            if not pts:
                continue
            spec = next((s for s in d.element_specs if s.element == el), None)
            c0 = spec.c0_ppm if spec else 1.0

            k_pred = float(mapping[el].predict(b.speed_mm_hr, b.temp_c,
                                               return_ci=False)[0])
            x = np.array([p.x_norm for p in pts])
            obs = np.array([p.value_ppm for p in pts])

            grid = get_profile_grid(b.zone_len_frac, b.n_passes, n_cells)
            sl = PositionSlice(grid, x)
            log_pred = sl.predict_log(k_pred) + np.log(max(c0, 1e-12))
            pred = np.exp(log_pred)

            e_p = np.abs(pred - obs)
            phys_abs.extend(e_p.tolist())
            phys_log.extend(np.abs(np.log(np.maximum(pred, 1e-12)) -
                                   np.log(np.maximum(obs, 1e-12))).tolist())
            b_phys.extend(e_p.tolist())
            b_n += x.size
            per_el_err.setdefault(el, {"physics": [], "ai": []})["physics"].extend(e_p.tolist())

            if corrector is not None and corrector.trained:
                delta = corrector.correction(b.speed_mm_hr, b.temp_c, b.n_passes, x)
                pred_ai = np.exp(log_pred + delta)
                e_a = np.abs(pred_ai - obs)
                ai_abs.extend(e_a.tolist())
                ai_log.extend(np.abs(np.log(np.maximum(pred_ai, 1e-12)) -
                                     np.log(np.maximum(obs, 1e-12))).tolist())
                b_ai.extend(e_a.tolist())
                per_el_err[el]["ai"].extend(e_a.tolist())

        if b_n:
            per_batch.append({
                "batch_id": held, "n_points": b_n,
                "speed_mm_hr": b.speed_mm_hr, "temp_c": b.temp_c, "n_passes": b.n_passes,
                "physics_mae_ppm": float(np.mean(b_phys)) if b_phys else float("nan"),
                "physics_max_ppm": float(np.max(b_phys)) if b_phys else float("nan"),
                "ai_mae_ppm": float(np.mean(b_ai)) if b_ai else float("nan"),
            })

    if not phys_abs:
        return LOBOResult(n_batches=len(ids), n_points=0,
                          physics_mae_ppm=float("nan"), physics_max_ppm=float("nan"),
                          physics_mae_log=float("nan"),
                          verdict="沒有可用的未設限測點，無法評估。")

    p_mae = float(np.mean(phys_abs))
    a_mae = float(np.mean(ai_abs)) if ai_abs else float("nan")
    improvement = (p_mae - a_mae) / p_mae * 100 if ai_abs and p_mae > 0 else 0.0
    # 驗收門檻：AI 必須至少改善 3%，才值得承擔額外的複雜度與風險
    gate = bool(ai_abs) and np.isfinite(a_mae) and improvement >= 3.0

    verdict = (
        f"AI 修正使平均絕對誤差從 {p_mae:.4g} ppm 降到 {a_mae:.4g} ppm"
        f"（改善 {improvement:.1f}%），達到 3% 的上線門檻，建議啟用並維持雙軌顯示。"
        if gate else
        f"AI 修正未達 3% 的改善門檻"
        + (f"（{improvement:+.1f}%）" if np.isfinite(a_mae) else "（樣本不足未訓練）")
        + "。依驗收條件，本階段只交付純物理模型——這是誠實且對客戶最有利的結果。"
    )

    return LOBOResult(
        n_batches=len(per_batch), n_points=len(phys_abs),
        physics_mae_ppm=p_mae,
        physics_max_ppm=float(np.max(phys_abs)),
        physics_mae_log=float(np.mean(phys_log)),
        ai_mae_ppm=a_mae,
        ai_max_ppm=float(np.max(ai_abs)) if ai_abs else float("nan"),
        ai_mae_log=float(np.mean(ai_log)) if ai_log else float("nan"),
        ai_better=bool(ai_abs and a_mae < p_mae),
        improvement_pct=float(improvement),
        gate_passed=gate,
        per_batch=per_batch,
        per_element={
            el: {
                "physics_mae_ppm": float(np.mean(v["physics"])) if v["physics"] else float("nan"),
                "ai_mae_ppm": float(np.mean(v["ai"])) if v["ai"] else float("nan"),
                "n_points": len(v["physics"]),
            } for el, v in sorted(per_el_err.items())
        },
        verdict=verdict,
        notes=[
            "誤差以「留出批次的未設限測點」計算；設限點沒有真值，不納入。",
            "映射與殘差模型在每一折都重新訓練，留出批次完全沒有參與訓練。",
        ],
    )


def _residual_samples(details: list, fits: dict, mapping, n_cells: int) -> list[dict]:
    """建立殘差學習的訓練樣本（僅使用未設限點）。"""
    samples = []
    for d in details:
        b = d.batch
        for el in d.elements:
            if el not in mapping:
                continue
            pts = [p for p in d.points(el) if not p.censored]
            if not pts:
                continue
            spec = next((s for s in d.element_specs if s.element == el), None)
            c0 = spec.c0_ppm if spec else 1.0
            k_pred = float(mapping[el].predict(b.speed_mm_hr, b.temp_c, return_ci=False)[0])
            x = np.array([p.x_norm for p in pts])
            grid = get_profile_grid(b.zone_len_frac, b.n_passes, n_cells)
            log_pred = PositionSlice(grid, x).predict_log(k_pred) + np.log(max(c0, 1e-12))
            for i, p in enumerate(pts):
                samples.append({
                    "speed": b.speed_mm_hr, "temp": b.temp_c, "n_passes": b.n_passes,
                    "x_norm": p.x_norm, "log_pred": float(log_pred[i]),
                    "log_obs": float(np.log(max(p.value_ppm, 1e-12))),
                })
    return samples


# ─────────────────────────────────────────────────────────────────
#  設限處理的對照實驗：證明「當成 0」和「當成 LOD」都會偏
# ─────────────────────────────────────────────────────────────────

def censoring_comparison(details: list, truth: dict | None = None,
                         n_cells: int = 240) -> dict:
    """比較三種設限處理方式對 k_eff 的影響。

    這是說服客戶（與工程師自己）的最有力證據之一：同一批資料、同一個模型，
    只因為 LOD 的處理方式不同，k_eff 就會系統性偏移。

    Args:
        details: list[BatchDetail]。
        truth: 合成資料的 truth_info；提供時可算出對真值的偏差。

    Returns:
        dict：三種方法的 k_eff 統計與（有真值時）相對偏差。
    """
    from ..fitting.fit_keff import fit_keff

    methods = {
        "tobit": "正確做法：告訴模型真值落在 [0, LOD] 區間內",
        "as_zero": "把設限點當成 0",
        "as_lod": "把設限點當成 LOD 值",
    }
    out: dict[str, dict] = {m: {} for m in methods}
    truth_map = {}
    if truth:
        truth_map = {row["batch_id"]: row["true_keff"] for row in truth.get("batches", [])}

    for d in details:
        b = d.batch
        for el in d.elements:
            pts = d.points(el)
            if len(pts) < 3:
                continue
            spec = next((s for s in d.element_specs if s.element == el), None)
            c0 = spec.c0_ppm if spec else 1.0
            x = [p.x_norm for p in pts]
            lod = [p.lod_ppm for p in pts]
            cen = [p.censored for p in pts]
            base = dict(zone_len_frac=b.zone_len_frac, n_passes=b.n_passes,
                        c0_ppm=c0, batch_id=b.batch_id, element=el, n_cells=n_cells)

            variants = {
                "tobit": ([p.value_ppm for p in pts], cen),
                "as_zero": ([1e-9 if p.censored else p.value_ppm for p in pts],
                            [False] * len(pts)),
                "as_lod": ([p.lod_ppm if p.censored else p.value_ppm for p in pts],
                           [False] * len(pts)),
            }
            for name, (vals, cflags) in variants.items():
                try:
                    f = fit_keff(x, vals, lod, cflags, **base)
                except (ValueError, FloatingPointError):
                    continue
                rec = out[name].setdefault(el, {"k": [], "rel_bias": []})
                rec["k"].append(f.k_eff)
                tv = truth_map.get(b.batch_id, {}).get(el)
                if tv:
                    rec["rel_bias"].append((f.k_eff - tv) / tv)

    summary = {}
    for name, per_el in out.items():
        summary[name] = {
            "description": methods[name],
            "elements": {
                el: {
                    "k_median": float(np.median(v["k"])) if v["k"] else float("nan"),
                    "n": len(v["k"]),
                    "median_rel_bias": float(np.median(v["rel_bias"])) if v["rel_bias"] else None,
                } for el, v in sorted(per_el.items())
            },
        }
        biases = [b for v in per_el.values() for b in v["rel_bias"]]
        summary[name]["overall_median_rel_bias"] = float(np.median(biases)) if biases else None
    summary["_note"] = (
        "有真值可比時（合成資料），可以看到把設限點當成 0 會低估 k_eff、"
        "當成 LOD 會高估，而 Tobit 處理接近無偏。這三個數字就是"
        "「為什麼不能便宜行事」的證據。")
    return summary
