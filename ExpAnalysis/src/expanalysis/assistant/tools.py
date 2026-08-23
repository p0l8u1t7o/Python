"""供 LLM 呼叫的工具集。

設計約束
--------
1. 每個工具都只是對服務層的薄包裝——**沒有任何計算邏輯寫在這一層**，
   確保 LLM 路徑與 UI 路徑看到的是同一份數字。
2. 回傳值一律是可 JSON 序列化的 dict，且盡量精簡：LLM 的 context 有限，
   丟 300 個格點的完整曲線進去只會稀釋注意力，所以曲線一律降採樣或改回
   摘要統計。
3. 每個回傳值都帶 ``_source``，說明這個數字是怎麼算出來的，讓 LLM 能在
   回答中誠實交代來源。
"""

from __future__ import annotations

import numpy as np

from ..config import SETTINGS
from ..logging_setup import get_logger

log = get_logger(__name__)

TOOL_SPECS: list[dict] = [
    {
        "name": "get_overview",
        "description": "取得資料集總覽：批次數、元素清單、各元素 k_eff 中位數與可去除性、"
                       "得料率統計、異常批次數量、製程參數涵蓋範圍。回答任何概括性問題前先呼叫這個。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_batches",
        "description": "列出批次及其製程參數與得料率。可用 sort_by 排序、limit 限制筆數。",
        "input_schema": {
            "type": "object",
            "properties": {
                "sort_by": {"type": "string",
                            "enum": ["batch_id", "run_date", "speed_mm_hr", "temp_c",
                                     "n_passes", "yield_frac"],
                            "description": "排序欄位，預設 batch_id"},
                "descending": {"type": "boolean", "description": "是否遞減排序"},
                "limit": {"type": "integer", "description": "最多回傳幾筆，預設 30"},
            },
            "required": [],
        },
    },
    {
        "name": "get_batch",
        "description": "取得單一批次的完整分析：製程參數、各元素 k_eff 與信賴區間、"
                       "擬合品質、6N 高純區與雜質濃縮區位置、得料率、該批的異常標記。",
        "input_schema": {
            "type": "object",
            "properties": {"batch_id": {"type": "string"}},
            "required": ["batch_id"],
        },
    },
    {
        "name": "compare_batches",
        "description": "比較兩個批次，列出製程參數差異、各元素 k_eff 差異，"
                       "並以 BPS 模型量化「速率差異預期造成多少 k_eff 變化」，"
                       "藉此判斷觀測到的差異能否被製程參數解釋。"
                       "使用者問「為什麼這批比上一批差」時用這個。",
        "input_schema": {
            "type": "object",
            "properties": {"batch_id_a": {"type": "string"}, "batch_id_b": {"type": "string"}},
            "required": ["batch_id_a", "batch_id_b"],
        },
    },
    {
        "name": "get_keff_table",
        "description": "取得各批次各元素的 k_eff 擬合表，含速率、溫度、信賴區間、設限點數。"
                       "可用 element 過濾。",
        "input_schema": {
            "type": "object",
            "properties": {"element": {"type": "string", "description": "元素符號，例如 Cu"}},
            "required": [],
        },
    },
    {
        "name": "get_parameter_mapping",
        "description": "取得某元素的 (速率, 溫度) → k_eff 映射模型：BPS 擬合出的 k0 與 delta/D、"
                       "R²、是否啟用高斯過程、線性假設是否成立。"
                       "使用者問「哪個參數最關鍵」「速率影響多大」時用這個。",
        "input_schema": {
            "type": "object",
            "properties": {"element": {"type": "string"}},
            "required": ["element"],
        },
    },
    {
        "name": "predict_profile",
        "description": "給定製程條件，預測全錠雜質分布與 6N 得料率。"
                       "回傳降採樣後的曲線、高純區與濃縮區位置、樂觀/名目/悲觀三種得料率、"
                       "以及是否落在歷史資料範圍內。",
        "input_schema": {
            "type": "object",
            "properties": {
                "speed_mm_hr": {"type": "number"},
                "temp_c": {"type": "number"},
                "n_passes": {"type": "integer"},
            },
            "required": ["speed_mm_hr", "temp_c", "n_passes"],
        },
    },
    {
        "name": "recommend_parameters",
        "description": "在製程參數空間掃描，回傳三種建議：最高得料率、"
                       "可直接執行的穩健建議（限資料範圍內、以悲觀值排序）、"
                       "產能導向建議，以及 pass 次數的飽和分析（做幾次之後就白做了）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "throughput_weight": {"type": "number",
                                      "description": "產能權重，0 表示純看得料率，"
                                                     "0.02~0.05 表示把時間成本納入"},
            },
            "required": [],
        },
    },
    {
        "name": "suggest_next_experiments",
        "description": "用貝氏最佳化建議接下來該跑哪幾批實驗，並說明每一批的目的"
                       "（縮小未知區 vs 確認最佳點）。",
        "input_schema": {
            "type": "object",
            "properties": {"n_suggest": {"type": "integer", "description": "建議批數，預設 3"}},
            "required": [],
        },
    },
    {
        "name": "get_anomalies",
        "description": "取得異常偵測結果：哪些批次的資料不對勁、理由、建議動作。"
                       "使用者問「有哪些資料有問題」「哪批要重測」時用這個。",
        "input_schema": {
            "type": "object",
            "properties": {"severity": {"type": "string", "enum": ["high", "medium", "low"]}},
            "required": [],
        },
    },
    {
        "name": "get_validation",
        "description": "取得留一批交叉驗證結果：純物理 vs 物理+AI 的誤差比較、"
                       "AI 是否通過上線門檻。使用者問「模型多準」「AI 有沒有幫助」時用這個。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def _downsample(arr: list[float], n: int = 21) -> list[float]:
    a = np.asarray(arr, dtype=np.float64)
    if a.size <= n:
        return [round(float(v), 6) for v in a]
    idx = np.linspace(0, a.size - 1, n).astype(int)
    return [round(float(v), 6) for v in a[idx]]


def dispatch_tool(name: str, args: dict, service) -> dict:
    """執行工具。任何例外都轉成 {"error": ...}，讓 LLM 能據實告知使用者。"""
    try:
        return _dispatch(name, args or {}, service)
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        log.warning("工具 %s 執行失敗：%s", name, exc)
        return {"error": f"{type(exc).__name__}: {exc}",
                "_source": "工具執行失敗，請據實告知使用者，不要自行推測數值。"}


def _dispatch(name: str, args: dict, service) -> dict:
    if name == "get_overview":
        ov = service.overview()
        ov["_source"] = "Pfann/BPS 物理擬合 + 高斯過程映射；得料率門檻為總雜質 " \
                        f"{SETTINGS.purity_threshold_ppm} ppm。"
        return ov

    if name == "list_batches":
        rows = []
        for d in service.repo.all_details():
            rows.append({
                "batch_id": d.batch.batch_id, "run_date": d.batch.run_date,
                "speed_mm_hr": d.batch.speed_mm_hr, "temp_c": d.batch.temp_c,
                "n_passes": d.batch.n_passes, "atmosphere": d.batch.atmosphere,
                "zone_len_mm": d.batch.zone_len_mm, "ingot_len_mm": d.batch.ingot_len_mm,
                "yield_frac": service.batch_yield(d.batch.batch_id),
            })
        key = args.get("sort_by", "batch_id")
        rows.sort(key=lambda r: (r.get(key) is None, r.get(key)),
                  reverse=bool(args.get("descending")))
        limit = int(args.get("limit") or 30)
        return {"n_total": len(rows), "batches": rows[:limit],
                "_source": "得料率由該批擬合出的 k_eff 經物理模擬計算。"}

    if name == "get_batch":
        payload = service.batch_payload(args["batch_id"])
        if payload is None:
            return {"error": f"找不到批次 {args['batch_id']}"}
        slim = {
            "batch": payload["batch"],
            "window": payload["window"],
            "yield_frac": service.batch_yield(args["batch_id"]),
            "anomalies": payload["anomalies"],
            "elements": {},
        }
        for el, c in payload["curves"].items():
            f = c["fit"]
            slim["elements"][el] = {
                "k_eff": round(f["k_eff"], 5),
                "k_ci": [f.get("k_lo"), f.get("k_hi")],
                "c0_ppm": round(f["c0_ppm"], 4),
                "sigma_log": round(f["sigma_log"], 4),
                "n_points": f["n_points"], "n_censored": f["n_censored"],
                "interpretation": f["interpretation"],
                "note": f["note"],
                "observed_ppm": [round(v, 6) for v in c["y_obs"]],
                "x_norm": c["x_obs"],
                "censored": c["censored"],
            }
        slim["_source"] = "k_eff 由 Tobit 設限擬合反解，信賴區間來自參數式 bootstrap。"
        return slim

    if name == "compare_batches":
        a_id, b_id = args["batch_id_a"], args["batch_id_b"]
        pa, pb = service.batch_payload(a_id), service.batch_payload(b_id)
        if pa is None or pb is None:
            return {"error": f"找不到批次 {a_id if pa is None else b_id}"}
        bundle = service.bundle()
        ba, bb = pa["batch"], pb["batch"]
        out = {
            "batch_a": {"batch_id": a_id, **{k: ba[k] for k in
                        ("speed_mm_hr", "temp_c", "n_passes", "atmosphere", "zone_len_mm")},
                        "yield_frac": service.batch_yield(a_id)},
            "batch_b": {"batch_id": b_id, **{k: bb[k] for k in
                        ("speed_mm_hr", "temp_c", "n_passes", "atmosphere", "zone_len_mm")},
                        "yield_frac": service.batch_yield(b_id)},
            "param_diff": {
                "speed_mm_hr": round(bb["speed_mm_hr"] - ba["speed_mm_hr"], 3),
                "temp_c": round(bb["temp_c"] - ba["temp_c"], 2),
                "n_passes": bb["n_passes"] - ba["n_passes"],
            },
            "elements": {},
        }
        for el in sorted(set(pa["curves"]) & set(pb["curves"])):
            ka = pa["curves"][el]["fit"]["k_eff"]
            kb = pb["curves"][el]["fit"]["k_eff"]
            expected = None
            if el in bundle.mapping:
                m = bundle.mapping[el]
                pred_a = float(m.predict(ba["speed_mm_hr"], ba["temp_c"], return_ci=False)[0])
                pred_b = float(m.predict(bb["speed_mm_hr"], bb["temp_c"], return_ci=False)[0])
                expected = round(pred_b - pred_a, 5)
            out["elements"][el] = {
                "k_eff_a": round(ka, 5), "k_eff_b": round(kb, 5),
                "k_eff_diff": round(kb - ka, 5),
                "expected_diff_from_model": expected,
                "unexplained": (round((kb - ka) - expected, 5)
                                if expected is not None else None),
            }
        out["_source"] = ("expected_diff_from_model 為 BPS/GP 映射依兩批的速率與溫度差異"
                          "預期的 k_eff 變化；unexplained 為觀測差異扣掉模型可解釋的部分。"
                          "k_eff 越低代表偏析純化效果越好。")
        return out

    if name == "get_keff_table":
        rows = service.keff_table()
        el = args.get("element")
        if el:
            rows = [r for r in rows if r["element"] == el]
        return {"n": len(rows), "rows": rows[:120],
                "_source": "每列為一個批次-元素組合的 Tobit 擬合結果。"}

    if name == "get_parameter_mapping":
        payload = service.mapping_payload()
        el = args["element"]
        if el not in payload["models"]:
            return {"error": f"沒有元素 {el} 的映射模型。可用元素：{payload['elements']}"}
        m = payload["models"][el]
        return {
            "element": el, "bps": m["bps"], "gp_used": m["gp_used"],
            "v_range_observed": m["v_range_observed"],
            "temp_used_for_curve": m["temp_used"],
            "k_at_v": [{"v": round(v, 2), "k": round(k, 5),
                        "k_lo": round(lo, 5), "k_hi": round(hi, 5)}
                       for v, k, lo, hi in list(zip(m["v_curve"], m["k_curve"],
                                                    m["k_lo"], m["k_hi"]))[::6]],
            "_source": ("BPS 線性化 ln(1/k-1) = ln(1/k0-1) - (delta/D)*v。"
                        "delta_over_d 就是斜率的絕對值，數字越大代表速率的影響越劇烈。"
                        "R² 低於 0.5 代表線性假設不成立，此時不應據此外插。"),
        }

    if name == "predict_profile":
        res = service.simulate(float(args["speed_mm_hr"]), float(args["temp_c"]),
                               int(args["n_passes"]))
        p = res["physics"]
        return {
            "conditions": {"speed_mm_hr": p["speed_mm_hr"], "temp_c": p["temp_c"],
                           "n_passes": p["n_passes"]},
            "k_eff": p["k_eff"], "k_ci": p["k_ci"],
            "yield_nominal": round(p["yield_nominal"], 4),
            "yield_optimistic": round(p["yield_optimistic"], 4),
            "yield_pessimistic": round(p["yield_pessimistic"], 4),
            "window": p["window"],
            "x_norm_sampled": _downsample(p["x_norm"]),
            "total_ppm_sampled": _downsample(p["total_ppm"]),
            "in_training_range": p["in_training_range"],
            "warnings": p["warnings"],
            "_source": "GP/BPS 映射給出 k_eff，再由 Pfann 多次 pass 離散模擬得到分布。",
        }

    if name == "recommend_parameters":
        res = service.optimize(throughput_weight=float(args.get("throughput_weight") or 0.0))
        return {
            "best": res["best"], "best_robust": res["best_robust"],
            "best_throughput": res["best_throughput"],
            "pass_advice": {k: v for k, v in (res.get("pass_advice") or {}).items()
                            if k in ("recommended_passes", "saturation_pass",
                                     "ultimate_pass", "best_yield", "note")},
            "n_evaluated": res["n_evaluated"], "notes": res["notes"],
            "_source": ("在 (溫度, 速率, 次數) 網格上逐點做物理模擬並計算 6N 得料率。"
                        "best_robust 是可以直接下給產線的建議；best 可能落在外插區。"),
        }

    if name == "suggest_next_experiments":
        from ..ml.bayesopt import suggest_next_batches
        obs = service.bo_observations()
        details = service.repo.all_details()
        sp = (max(0.3, min(d.batch.speed_mm_hr for d in details) * 0.6),
              max(d.batch.speed_mm_hr for d in details) * 1.3) if details else (0.5, 8.0)
        tp = (min(d.batch.temp_c for d in details) - 5,
              max(d.batch.temp_c for d in details) + 5) if details else (160.0, 210.0)
        pc = tuple(sorted({d.batch.n_passes for d in details})) or (8,)
        out = suggest_next_batches(obs, sp, tp, pc,
                                   n_suggest=int(args.get("n_suggest") or 3))
        out["_source"] = ("以高斯過程建模 (速率, 溫度, 次數) → 得料率，"
                          "用 Expected Improvement 取得函數挑選下一批。"
                          "這只影響「下一批做什麼」，不影響任何已完成批次的分析。")
        return out

    if name == "get_anomalies":
        rows = service.anomalies()
        sev = args.get("severity")
        if sev:
            rows = [r for r in rows if r["severity"] == sev]
        return {"n": len(rows), "findings": rows,
                "_source": "以物理模型殘差為基礎的規則式偵測 + Isolation Forest 補漏。"}

    if name == "get_validation":
        res = service.lobo()
        res["_source"] = ("留一批交叉驗證：每一折都把整個批次留出、重新訓練映射與"
                          "殘差模型後再預測。誤差以未設限測點計算。")
        return res

    return {"error": f"未知的工具：{name}"}
