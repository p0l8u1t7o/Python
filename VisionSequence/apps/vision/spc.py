"""量測值 SPC（WP-14）：管制圖（I-MR、X̄-R）、Cp／Cpk、Nelson 判異法則、規格界限綁定——純函式，資料由 MeasurementLog 供應。

- I-MR（個別值／移動全距）：CL = x̄、UCL/LCL = x̄ ± 2.66·MR̄（E2 = 2.66，n=2）；MR 圖 UCL = 3.267·MR̄（D4）、LCL = 0。σ 估計 = MR̄ / d2 = MR̄ / 1.128。
- X̄-R（子組 n = 2～10）：X̄ 圖 UCL/LCL = X̿ ± A2·R̄；R 圖 UCL = D4·R̄、LCL = D3·R̄；σ 估計 = R̄ / d2。常數表為 AIAG SPC 手冊附錄。
- Cp = (USL − LSL) / 6σ；Cpk = min(USL − μ, μ − LSL) / 3σ；單邊規格只給 Cpu／Cpl；σ 用管制圖的估計值（短期能力）。
- Nelson 法則（1984）：1 超出 3σ、2 連續 9 點同側、3 連續 6 點單調、4 連續 14 點交替、5 3 點中 2 點超出 2σ 同側、6 5 點中 4 點超出 1σ 同側、
  7 連續 15 點在 1σ 內、8 連續 8 點都在 1σ 外（兩側）。每條法則回被標記的點索引；區域以管制圖的 CL 與 σ 計。
- 規格界限：從流程圖裡的 tolerance_judge 抓——`name` 參數等於輸出名，或它的 value 輸入與 output 節點的 value 輸入來自同一個 (節點, 埠)。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

#: AIAG SPC 常數（子組大小 n → A2, D3, D4, d2）
CONSTANTS = {
    2: (1.880, 0.0, 3.267, 1.128), 3: (1.023, 0.0, 2.574, 1.693), 4: (0.729, 0.0, 2.282, 2.059), 5: (0.577, 0.0, 2.114, 2.326),
    6: (0.483, 0.0, 2.004, 2.534), 7: (0.419, 0.076, 1.924, 2.704), 8: (0.373, 0.136, 1.864, 2.847), 9: (0.337, 0.184, 1.816, 2.970),
    10: (0.308, 0.223, 1.777, 3.078),
}
NELSON_RULES = {
    1: "one point beyond 3σ", 2: "nine points in a row on the same side", 3: "six points in a row steadily rising or falling",
    4: "fourteen points in a row alternating up and down", 5: "two of three points beyond 2σ on the same side",
    6: "four of five points beyond 1σ on the same side", 7: "fifteen points in a row within 1σ", 8: "eight points in a row beyond 1σ on either side",
}


def imr_limits(values: list[float]) -> dict[str, Any]:
    """I-MR 管制界限；少於 2 點回空界限。"""
    x = np.asarray(values, dtype=np.float64)
    n = int(x.size)
    if n == 0:
        return {"chart": "imr", "n": 0}
    mean = float(x.mean())
    if n < 2:
        return {"chart": "imr", "n": n, "cl": mean, "ucl": None, "lcl": None, "sigma": None, "mr_bar": None, "mr_ucl": None}
    mr = np.abs(np.diff(x))
    mr_bar = float(mr.mean())
    sigma = mr_bar / 1.128
    return {"chart": "imr", "n": n, "cl": mean, "ucl": mean + 2.66 * mr_bar, "lcl": mean - 2.66 * mr_bar, "sigma": sigma,
            "mr_bar": mr_bar, "mr_ucl": 3.267 * mr_bar, "mr_lcl": 0.0, "moving_range": [None] + [float(v) for v in mr]}


def xbar_r_limits(values: list[float], subgroup: int) -> dict[str, Any]:
    """X̄-R：依序每 subgroup 個值成一組（尾端不足者丟掉）。"""
    subgroup = max(2, min(10, int(subgroup)))
    x = np.asarray(values, dtype=np.float64)
    groups = x[: (x.size // subgroup) * subgroup].reshape(-1, subgroup) if x.size >= subgroup else np.zeros((0, subgroup))
    if groups.shape[0] == 0:
        return {"chart": "xbar_r", "n": 0, "subgroup": subgroup}
    a2, d3, d4, d2 = CONSTANTS[subgroup]
    xbar = groups.mean(axis=1)
    r = groups.max(axis=1) - groups.min(axis=1)
    xbb = float(xbar.mean())
    rbar = float(r.mean())
    sigma = rbar / d2
    return {"chart": "xbar_r", "n": int(groups.shape[0]), "subgroup": subgroup, "cl": xbb, "ucl": xbb + a2 * rbar, "lcl": xbb - a2 * rbar, "sigma": sigma,
            "r_bar": rbar, "r_ucl": d4 * rbar, "r_lcl": d3 * rbar, "xbar": [float(v) for v in xbar], "r": [float(v) for v in r]}


def capability(values: list[float], sigma: float | None, usl: float | None, lsl: float | None) -> dict[str, Any]:
    """Cp／Cpk（短期，σ 來自管制圖）；單邊給 Cpu／Cpl。"""
    out: dict[str, Any] = {"usl": usl, "lsl": lsl}
    if not values or not sigma or sigma <= 0:
        return out
    mu = float(np.mean(values))
    if usl is not None:
        out["cpu"] = (usl - mu) / (3 * sigma)
    if lsl is not None:
        out["cpl"] = (mu - lsl) / (3 * sigma)
    if usl is not None and lsl is not None:
        out["cp"] = (usl - lsl) / (6 * sigma)
        out["cpk"] = min(out["cpu"], out["cpl"])
        out["out_of_spec"] = int(sum(1 for v in values if v > usl or v < lsl))
    elif usl is not None:
        out["cpk"] = out["cpu"]
        out["out_of_spec"] = int(sum(1 for v in values if v > usl))
    elif lsl is not None:
        out["cpk"] = out["cpl"]
        out["out_of_spec"] = int(sum(1 for v in values if v < lsl))
    return out


def nelson(values: list[float], cl: float, sigma: float | None) -> dict[int, list[int]]:
    """八條 Nelson 法則：每條回觸發的點索引（規則 2～8 標整段）。σ 不可用或 ≤ 0 時只可能給空結果。"""
    hits: dict[int, list[int]] = {k: [] for k in NELSON_RULES}
    if not values or not sigma or sigma <= 0:
        return hits
    x = np.asarray(values, dtype=np.float64)
    z = (x - cl) / sigma
    n = len(z)
    hits[1] = [int(i) for i in np.where(np.abs(z) > 3)[0]]
    side = np.sign(z)
    for i in range(n):
        if i >= 8 and (all(side[i - 8:i + 1] > 0) or all(side[i - 8:i + 1] < 0)):
            hits[2].extend(range(i - 8, i + 1))
        if i >= 5:
            seg = x[i - 5:i + 1]
            d = np.diff(seg)
            if all(d > 0) or all(d < 0):
                hits[3].extend(range(i - 5, i + 1))
        if i >= 13:
            d = np.diff(x[i - 13:i + 1])
            if all(d != 0) and all(d[k] * d[k + 1] < 0 for k in range(len(d) - 1)):
                hits[4].extend(range(i - 13, i + 1))
        if i >= 2:
            seg = z[i - 2:i + 1]
            if sum(1 for v in seg if v > 2) >= 2 or sum(1 for v in seg if v < -2) >= 2:
                hits[5].extend(range(i - 2, i + 1))
        if i >= 4:
            seg = z[i - 4:i + 1]
            if sum(1 for v in seg if v > 1) >= 4 or sum(1 for v in seg if v < -1) >= 4:
                hits[6].extend(range(i - 4, i + 1))
        if i >= 14 and all(np.abs(z[i - 14:i + 1]) < 1):
            hits[7].extend(range(i - 14, i + 1))
        if i >= 7:
            seg = z[i - 7:i + 1]
            if all(np.abs(seg) > 1) and (seg > 0).any() and (seg < 0).any():
                hits[8].extend(range(i - 7, i + 1))
    return {k: sorted(set(v)) for k, v in hits.items()}


def spec_limits_from_graph(graph: dict[str, Any], output_name: str) -> dict[str, Any]:
    """從 tolerance_judge 找這個具名輸出的規格界限：name 參數相同，或與 output 節點共用同一個 (來源節點, 埠)。"""
    nodes = {n.get("id"): n for n in (graph or {}).get("nodes") or []}
    edges = (graph or {}).get("edges") or []
    out_node = next((n for n in nodes.values() if n.get("type") == "output" and (n.get("params") or {}).get("name") == output_name), None)
    out_src = None
    if out_node is not None:
        for e in edges:
            if e.get("target") == out_node["id"] and (e.get("target_handle") or "value") == "value":
                out_src = (e.get("source"), e.get("source_handle"))
                break
    for n in nodes.values():
        if n.get("type") != "tolerance_judge":
            continue
        p = n.get("params") or {}
        src = None
        for e in edges:
            if e.get("target") == n["id"] and (e.get("target_handle") or "value") == "value":
                src = (e.get("source"), e.get("source_handle"))
                break
        matched = (p.get("name") and p.get("name") == output_name) or (out_src is not None and src == out_src) or ((n.get("label") or "") == output_name)
        if not matched:
            continue
        try:
            nominal = float(p.get("nominal", 0))
            usl = nominal + float(p.get("upper_tol", 0.1))
            lsl = nominal + float(p.get("lower_tol", -0.1))
        except (TypeError, ValueError):
            continue
        return {"usl": usl, "lsl": lsl, "nominal": nominal, "unit": p.get("unit") or "", "node_id": n["id"], "source": "tolerance_judge"}
    return {}


def analyse(values: list[float], chart: str = "imr", subgroup: int = 5, usl: float | None = None, lsl: float | None = None) -> dict[str, Any]:
    """一次算完：界限、能力、Nelson。values 依時間排序。"""
    limits = xbar_r_limits(values, subgroup) if chart == "xbar_r" else imr_limits(values)
    sigma = limits.get("sigma")
    cl = limits.get("cl")
    plotted = limits.get("xbar") if chart == "xbar_r" else values
    rules = nelson(plotted or [], cl, sigma) if cl is not None else {k: [] for k in NELSON_RULES}
    flagged = sorted({i for v in rules.values() for i in v})
    return {
        "limits": limits, "capability": capability(values, sigma, usl, lsl), "rules": {str(k): v for k, v in rules.items() if v},
        "rule_names": {str(k): v for k, v in NELSON_RULES.items()}, "flagged": flagged,
        "summary": {"n": len(values), "mean": float(np.mean(values)) if values else None, "std": float(np.std(values, ddof=1)) if len(values) > 1 else None,
                    "min": float(min(values)) if values else None, "max": float(max(values)) if values else None},
    }


def alerts_for(values: list[float], usl: float | None = None, lsl: float | None = None, recent: int = 30) -> list[dict[str, Any]]:
    """總覽用的告警：最近 recent 點觸發的法則（只報最後一點也在其中的那些＝「現在」失控），與規格外的點數。"""
    if len(values) < 2:
        return []
    out: list[dict[str, Any]] = []
    a = analyse(values, usl=usl, lsl=lsl)
    last = len(values) - 1
    for k, idx in a["rules"].items():
        if last in idx:
            out.append({"rule": int(k), "text": NELSON_RULES[int(k)], "points": [i for i in idx if i >= len(values) - recent]})
    cap = a["capability"]
    if cap.get("out_of_spec"):
        tail = values[-recent:]
        n_out = sum(1 for v in tail if (usl is not None and v > usl) or (lsl is not None and v < lsl))
        if n_out:
            out.append({"rule": 0, "text": f"{n_out} of the last {len(tail)} outside the specification", "points": []})
    return out


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))
