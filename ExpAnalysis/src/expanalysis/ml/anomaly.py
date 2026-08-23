"""L3 — 異常偵測：哪一批資料不對勁。

為什麼這一層零風險
------------------
它**不參與任何預測計算**，只是把可疑批次挑出來給人看。它只會保護準確度
（把爛資料擋在模型外），不可能傷害準確度。這是整個 AI 架構裡最先該做、
也最容易讓客戶接受的一層。

抓得到的問題
------------
  * 熱電偶飄移        → k_eff 系統性偏離 (v, T) 映射的預測
  * 取樣位置記錄錯誤  → 曲線形狀完全對不上，殘差呈現結構性正負交替
  * 分析室送錯樣品    → 單點極端殘差
  * 氧化夾帶          → 整批雜質水準抬升，C0 對不上質量守恆
  * 進料批次不同      → 擬合出的 C0 倍率遠離 1

兩種判準並用
------------
1. **規則式（可解釋）**：對每個指標設門檻，超過就標記並寫明理由。
   工程師看得懂理由才會採信，這比 anomaly score 有用得多。
2. **Isolation Forest（補漏）**：對批次層級特徵向量做無監督偵測，
   抓規則沒想到的組合型異常。它只提供補充分數，不單獨判定。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np

from ..logging_setup import get_logger

log = get_logger(__name__)

# 判定門檻。這些是可調的工程判斷，不是物理常數，故集中在此並在報告中揭露。
THRESH_MAX_RESID = 3.0        # 單點標準化殘差
THRESH_RMSE_RESID = 1.8       # 整條曲線的殘差 RMSE
THRESH_SIGMA_LOG = 0.45       # 對數殘差標準差（≈ ±57% 相對誤差）
THRESH_MAP_Z = 2.5            # k_eff 偏離 (v,T) 映射預測的標準化距離
THRESH_C0_MUL = 0.35          # 擬合 C0 倍率偏離 1 的容忍度
THRESH_SIGN_RUN = 0.85        # 殘差正負「結構性」的比例門檻
THRESH_BATCH_SHIFT = 1.2      # 批次內所有元素同方向偏移的標準差門檻


@dataclass
class AnomalyFinding:
    batch_id: str
    element: str
    severity: str                     # "high" | "medium" | "low"
    reasons: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    suggested_action: str = ""
    exclude_recommended: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _sign_structure(resid: np.ndarray) -> float:
    """殘差正負是否呈結構性（前半全正、後半全負之類）。

    回傳 0~1；接近 1 表示殘差不是隨機散布，而是有系統性形狀誤差——
    典型成因是取樣位置錯誤、熔區長度記錄錯誤、或 pass 次數對不上。
    """
    if resid.size < 4:
        return 0.0
    half = resid.size // 2
    a, b = resid[:half], resid[half:]
    if not (np.any(a) and np.any(b)):
        return 0.0
    frac_a = np.mean(np.sign(a) == np.sign(np.mean(a)))
    frac_b = np.mean(np.sign(b) == np.sign(np.mean(b)))
    opposite = 1.0 if np.sign(np.mean(a)) != np.sign(np.mean(b)) else 0.0
    return float(frac_a * frac_b * opposite)


def detect_anomalies(
    fits: dict[str, dict],
    mapping=None,
    batches: dict | None = None,
    use_isolation_forest: bool = True,
) -> list[AnomalyFinding]:
    """對所有批次/元素做異常偵測。

    Args:
        fits: {batch_id: {element: KeffFit}}。
        mapping: KeffMapping；提供時會額外檢查 k_eff 是否偏離 (v,T) 映射。
        batches: {batch_id: Batch}，取 speed/temp 用。
        use_isolation_forest: 是否加做無監督偵測。

    Returns:
        依嚴重度排序的 AnomalyFinding 清單。
    """
    findings: list[AnomalyFinding] = []
    feature_rows, feature_keys = [], []

    for bid, per_el in fits.items():
        for el, fit in per_el.items():
            resid = np.asarray(fit.residuals, dtype=np.float64)
            max_r = float(np.max(np.abs(resid))) if resid.size else 0.0
            rmse_r = float(np.sqrt(np.mean(resid ** 2))) if resid.size else 0.0
            sign_struct = _sign_structure(resid)

            reasons, metrics = [], {
                "max_abs_residual": round(max_r, 3),
                "rmse_residual": round(rmse_r, 3),
                "sigma_log": round(fit.sigma_log, 4),
                "sign_structure": round(sign_struct, 3),
                "n_censored": fit.n_censored,
                "n_points": fit.n_points,
            }

            if max_r > THRESH_MAX_RESID:
                reasons.append(
                    f"單點標準化殘差達 {max_r:.1f}（門檻 {THRESH_MAX_RESID}）——"
                    f"可能是分析室送錯樣品或該點取樣位置記錄錯誤。")
            if rmse_r > THRESH_RMSE_RESID:
                reasons.append(
                    f"整條曲線的殘差 RMSE {rmse_r:.1f}（門檻 {THRESH_RMSE_RESID}）——"
                    f"模型與資料整體對不上。")
            if fit.sigma_log > THRESH_SIGMA_LOG:
                pct = 100 * (np.exp(fit.sigma_log) - 1)
                reasons.append(
                    f"對數殘差標準差 {fit.sigma_log:.2f}（相當於 ±{pct:.0f}% 相對誤差）"
                    f"高於典型 GDMS 水準。")
            if sign_struct > THRESH_SIGN_RUN:
                reasons.append(
                    "殘差呈結構性正負分布（前段一致偏高、後段一致偏低或反之）——"
                    "典型成因是取樣位置頭尾顛倒、熔區長度或 pass 次數記錄錯誤。")
            if fit.c0_fitted:
                reasons.append("進料濃度 C0 為推估值而非實測，k_eff 的絕對值不可盡信。")
            if fit.n_censored >= fit.n_points:
                reasons.append("所有測點皆低於檢測極限，本批對此元素無有效資訊。")

            # ── 與 (v, T) 映射比對（需要 mapping）─────────────────
            map_z = None
            if mapping is not None and batches is not None and el in mapping:
                b = batches.get(bid)
                if b is not None:
                    from ..physics.bps import bps_linearize
                    z_pred, z_std = mapping[el].predict_z(b.speed_mm_hr, b.temp_c)
                    z_obs = float(bps_linearize(fit.k_eff))
                    denom = float(np.sqrt(z_std[0] ** 2 + 0.15 ** 2))
                    map_z = abs(z_obs - float(z_pred[0])) / max(denom, 1e-6)
                    metrics["mapping_z"] = round(map_z, 2)
                    if map_z > THRESH_MAP_Z:
                        direction = "好於" if z_obs < float(z_pred[0]) else "差於"
                        reasons.append(
                            f"k_eff 與 (速率 {b.speed_mm_hr:g} mm/hr、溫度 {b.temp_c:g}°C) "
                            f"的映射預測相差 {map_z:.1f} 個標準差（實際{direction}預期）——"
                            f"檢查熱電偶讀值、實際熔區長度、或該批是否有製程偏移。")

            if not reasons:
                feature_rows.append([max_r, rmse_r, fit.sigma_log,
                                     map_z if map_z is not None else 0.0,
                                     fit.n_censored / max(fit.n_points, 1)])
                feature_keys.append((bid, el))
                continue

            high = (max_r > THRESH_MAX_RESID * 1.5 or rmse_r > THRESH_RMSE_RESID * 1.5
                    or sign_struct > THRESH_SIGN_RUN
                    or (map_z is not None and map_z > THRESH_MAP_Z * 1.6))
            severity = "high" if high else ("medium" if len(reasons) > 1 else "low")
            findings.append(AnomalyFinding(
                batch_id=bid, element=el, severity=severity,
                reasons=reasons, metrics=metrics,
                exclude_recommended=high,
                suggested_action=(
                    "建議先確認原始紀錄（取樣位置、熱電偶校正、送驗單），"
                    "確認為資料問題後再從模型訓練集中排除。"
                    if high else "建議留意，暫不排除。"),
            ))
            feature_rows.append([max_r, rmse_r, fit.sigma_log,
                                 map_z if map_z is not None else 0.0,
                                 fit.n_censored / max(fit.n_points, 1)])
            feature_keys.append((bid, el))

    # ── 批次層級：多元素同向偏移 ────────────────────────────────
    # 單看一個元素，偏離 1.5 個標準差不算什麼；但如果同一批的**所有元素**
    # 都往同一個方向偏 1.5 個標準差，那就不是量測雜訊，是這一批的製程條件
    # 記錄與實際不符。熱電偶飄移、實際熔區長度與設定值不同、氣氛洩漏，
    # 都會產生這個特徵。逐元素的門檻永遠抓不到它，必須跨元素看。
    if mapping is not None and batches is not None:
        from ..physics.bps import bps_linearize
        for bid, per_el in fits.items():
            b = batches.get(bid)
            if b is None:
                continue
            signed = []
            for el, fit in per_el.items():
                if el not in mapping:
                    continue
                z_pred, z_std = mapping[el].predict_z(b.speed_mm_hr, b.temp_c)
                denom = float(np.sqrt(z_std[0] ** 2 + 0.15 ** 2))
                signed.append((float(bps_linearize(fit.k_eff)) - float(z_pred[0])) / max(denom, 1e-6))
            if len(signed) < 3:
                continue
            arr = np.asarray(signed)
            same_dir = np.all(arr > 0) or np.all(arr < 0)
            if same_dir and np.min(np.abs(arr)) > THRESH_BATCH_SHIFT:
                worse = "差於" if arr[0] > 0 else "好於"
                findings.append(AnomalyFinding(
                    batch_id=bid, element="(全部元素)", severity="medium",
                    reasons=[
                        f"本批 {len(arr)} 個元素的 k_eff **全部同方向**偏離映射預測"
                        f"（平均 {np.mean(arr):+.1f} 個標準差，實際{worse}預期）。"
                        "單一元素偏這麼多可以是雜訊，但所有元素一致同向就不是——"
                        "這是批次層級的系統性偏移。",
                        "最可能的三個原因（依投報率排序）：(1) 熱電偶讀值與實際熔體"
                        "溫度不符；(2) 實際熔區長度與設定值不同（溫度變化會直接改變 l）；"
                        "(3) 氣氛不如記錄（氧化夾帶會整體抬升雜質水準）。",
                    ],
                    metrics={"element_z_scores": {el: round(float(v), 2)
                                                 for el, v in zip(per_el, signed)},
                             "mean_z": round(float(np.mean(arr)), 2)},
                    suggested_action=(
                        "建議校驗該批當時的熱電偶，並確認是否有實測熔區長度紀錄。"
                        "若客戶尚未量測熔區長度，這是整個專案投報率最高的補量測項目——"
                        "溫度只是熔區長度的代理變數，量到 l 就不需要靠溫度推。"),
                ))

    # ── Isolation Forest 補漏 ──────────────────────────────────
    if use_isolation_forest and len(feature_rows) >= 12:
        try:
            from sklearn.ensemble import IsolationForest
            X = np.asarray(feature_rows, dtype=np.float64)
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            iso = IsolationForest(contamination=0.10, random_state=0, n_estimators=200)
            scores = iso.fit(X).score_samples(X)
            flagged = {feature_keys[i] for i in np.argsort(scores)[:max(1, len(scores) // 12)]}
            known = {(f.batch_id, f.element) for f in findings}
            for (bid, el) in flagged - known:
                findings.append(AnomalyFinding(
                    batch_id=bid, element=el, severity="low",
                    reasons=["Isolation Forest 判定此批次的指標組合與其他批次明顯不同，"
                             "但未觸發任何單項規則門檻。"],
                    metrics={"detector": "isolation_forest"},
                    suggested_action="僅供留意，無需動作；若同批多個元素同時被標記則值得追查。",
                ))
        except (ImportError, ValueError) as exc:
            log.warning("Isolation Forest 執行失敗：%s", exc)

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f.severity], f.batch_id, f.element))
    return findings
