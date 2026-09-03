"""資料洞察（純函式）：從一次批次執行的逐張結果與影像集的期望標記，算出命中率／混淆矩陣、未命中清單、
出錯節點、最慢影像、具名輸出分佈，以及判定節點的門檻建議（沿 value 輸入邊找上游數值，依期望 OK／NG 兩群找最佳切點），
有父執行時另給前後差異。text 欄是繁中條列句，離線諮詢與 LLM 上下文共用。"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from apps.vision.batch.store import graph_param_diff, row_match
from apps.vision.tools import base as tools

#: 判定節點：value 輸入埠 → 可建議的參數。
JUDGE_TYPES = ("if_number", "in_range", "tolerance_judge")
MAX_MISMATCHES = 20
MAX_SLOWEST = 5


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    n = len(values)
    mean = sum(values) / n
    std = (sum((x - mean) ** 2 for x in values) / n) ** 0.5
    return {"n": n, "min": round(min(values), 4), "max": round(max(values), 4), "mean": round(mean, 4), "std": round(std, 4)}


def _port_defaults(node_type: str) -> tuple[str, str]:
    if not tools.has(node_type):
        return "", ""
    t = tools.get(node_type)
    return (t.inputs[0].key if t.inputs else ""), (t.outputs[0].key if t.outputs else "")


def _inbound(graph: dict[str, Any]) -> dict[tuple[str, str], tuple[str, str]]:
    by_id = {n["id"]: n for n in graph.get("nodes", [])}
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for e in graph.get("edges", []):
        src, tgt = by_id.get(e.get("source")), by_id.get(e.get("target"))
        if not src or not tgt:
            continue
        th = e.get("target_handle") or _port_defaults(str(tgt.get("type", "")))[0]
        sh = e.get("source_handle") or _port_defaults(str(src.get("type", "")))[1]
        out[(tgt["id"], th)] = (src["id"], sh)
    return out


def _flow_verdicts(graph: dict[str, Any], node_id: str) -> dict[str, str]:
    """判定節點各分支直接接到的 judge 判定：{"true": "ok", "false": "ng"} 之類；接不到就空。"""
    by_id = {n["id"]: n for n in graph.get("nodes", [])}
    out: dict[str, str] = {}
    for e in graph.get("edges", []):
        if e.get("source") != node_id or (e.get("target_handle") or "") != "_flow":
            continue
        tgt = by_id.get(e.get("target"))
        if tgt and tgt.get("type") == "judge":
            verdict = str((tgt.get("params") or {}).get("verdict", ""))
            if verdict in ("ok", "ng"):
                out[str(e.get("source_handle") or "")] = verdict
    return out


def _cond(v: float, t: float, op: str) -> bool:
    return {"gt": v > t, "ge": v >= t, "lt": v < t, "le": v <= t, "eq": v == t, "ne": v != t}.get(op, v > t)


def _accuracy(values: list[tuple[float, bool]], predict_ok) -> float:
    if not values:
        return 0.0
    return sum(1 for v, is_ok in values if predict_ok(v) == is_ok) / len(values)


def _candidates(xs: list[float]) -> list[float]:
    s = sorted(set(xs))
    if not s:
        return []
    mids = [(s[i] + s[i + 1]) / 2 for i in range(len(s) - 1)]
    return [s[0] - 1.0, *mids, s[-1] + 1.0]


def _judges(graph: dict[str, Any], items: list[dict[str, Any]], by_index: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    inbound = _inbound(graph)
    by_id = {n["id"]: n for n in graph.get("nodes", [])}
    out: list[dict[str, Any]] = []
    for n in graph.get("nodes", []):
        ntype = str(n.get("type", ""))
        if ntype not in JUDGE_TYPES or n.get("enabled", True) is False:
            continue
        src = inbound.get((n["id"], "value"))
        if not src:
            continue
        s_id, s_port = src
        params = n.get("params") or {}
        rows: list[dict[str, Any]] = []
        for it in items:
            v = _num(((it.get("nodes") or {}).get(s_id) or {}).get("outputs", {}).get(s_port))
            if v is None:
                continue
            image = by_index.get(int(it.get("index", -1)), {})
            rows.append({"index": it.get("index"), "value": v, "expected": image.get("expected") or "", "status": it.get("status")})
        if not rows:
            continue
        entry: dict[str, Any] = {
            "node": n["id"], "label": n.get("label") or n["id"], "type": ntype, "value_from": {"node": s_id, "port": s_port, "label": (by_id.get(s_id) or {}).get("label") or s_id},
            "current": {k: params.get(k) for k in ("operator", "threshold", "low", "high", "nominal", "upper_tol", "lower_tol") if k in params},
            "values": {"expected_ok": _stats([r["value"] for r in rows if r["expected"] == "ok"]), "expected_ng": _stats([r["value"] for r in rows if r["expected"] == "ng"]),
                       "status_ok": _stats([r["value"] for r in rows if r["status"] == "ok"]), "status_ng": _stats([r["value"] for r in rows if r["status"] == "ng"])},
            "suggestion": None, "acc_now": None, "acc_suggested": None, "separable": None,
        }
        labeled = [(r["value"], r["expected"] == "ok") for r in rows if r["expected"] in ("ok", "ng")]
        ok_vals = [v for v, is_ok in labeled if is_ok]
        ng_vals = [v for v, is_ok in labeled if not is_ok]
        if ok_vals and ng_vals:
            entry["separable"] = max(ok_vals) < min(ng_vals) or max(ng_vals) < min(ok_vals)
            verdicts = _flow_verdicts(graph, n["id"])
            if ntype == "if_number":
                op = str(params.get("operator", "gt"))
                if op in ("gt", "ge", "lt", "le"):
                    true_ok = verdicts.get("true") == "ok" or (verdicts.get("false") == "ng" and "true" not in verdicts)
                    if not verdicts:  # 沒接 judge：以目前資料推斷方向
                        cur = float(_num(params.get("threshold")) or 0)
                        true_ok = _accuracy(labeled, lambda v: _cond(v, cur, op)) >= 0.5
                    cur_t = _num(params.get("threshold"))
                    acc_now = _accuracy(labeled, lambda v: _cond(v, cur_t, op) == true_ok) if cur_t is not None else None
                    best_t, best_acc = None, acc_now or 0.0
                    for t in _candidates([v for v, _ in labeled]):
                        acc = _accuracy(labeled, lambda v, t=t: _cond(v, t, op) == true_ok)
                        if acc > best_acc + 1e-9 or (best_t is not None and abs(acc - best_acc) < 1e-9 and cur_t is not None and abs(t - cur_t) < abs(best_t - cur_t)):
                            best_t, best_acc = t, acc
                    entry["acc_now"] = round(acc_now, 4) if acc_now is not None else None
                    if best_t is not None and (acc_now is None or best_acc > acc_now + 1e-9):
                        entry["suggestion"] = {"threshold": round(best_t, 4)}
                        entry["acc_suggested"] = round(best_acc, 4)
            elif ntype == "in_range":
                inside_ok = verdicts.get("inside", "ok") == "ok"
                lo, hi = _num(params.get("low")), _num(params.get("high"))
                if inside_ok and lo is not None and hi is not None:
                    acc_now = _accuracy(labeled, lambda v: lo <= v <= hi)
                    below = [v for v in ng_vals if v < min(ok_vals)]
                    above = [v for v in ng_vals if v > max(ok_vals)]
                    # 只在該側有 NG 值時才移動邊界（放在 NG 與 OK 之間的中點）；沒有 NG 的那側維持現值
                    new_lo = (max(below) + min(ok_vals)) / 2 if below else lo
                    new_hi = (min(above) + max(ok_vals)) / 2 if above else hi
                    acc_new = _accuracy(labeled, lambda v: new_lo <= v <= new_hi)
                    entry["acc_now"] = round(acc_now, 4)
                    if acc_new > acc_now + 1e-9:
                        entry["suggestion"] = {k: round(v, 4) for k, v in (("low", new_lo), ("high", new_hi)) if v != (lo if k == "low" else hi)}
                        entry["acc_suggested"] = round(acc_new, 4)
            elif ntype == "tolerance_judge":
                nominal = _num(params.get("nominal"))
                if nominal is not None:
                    entry["deviation"] = {"expected_ok": _stats([v - nominal for v in ok_vals]), "expected_ng": _stats([v - nominal for v in ng_vals])}
        out.append(entry)
    return out


def _vs_parent(items: list[dict[str, Any]], parent_items: list[dict[str, Any]] | None, by_index: dict[int, dict[str, Any]],
               graph: dict[str, Any], parent_graph: dict[str, Any] | None) -> dict[str, Any] | None:
    if parent_items is None:
        return None
    prev = {int(it.get("index", -1)): it for it in parent_items}
    changed, improved, regressed = [], [], []
    for it in items:
        idx = int(it.get("index", -1))
        p = prev.get(idx)
        if p is None:
            continue
        if p.get("status") != it.get("status"):
            changed.append({"index": idx, "name": by_index.get(idx, {}).get("name", ""), "from": p.get("status"), "to": it.get("status")})
        m_new, _ = row_match(it, by_index.get(idx))
        m_old, _ = row_match(p, by_index.get(idx))
        if m_old is False and m_new is True:
            improved.append(idx)
        elif m_old is True and m_new is False:
            regressed.append(idx)
    return {"changed": changed, "improved": improved, "regressed": regressed, "same": len(items) - len(changed),
            "param_diff": graph_param_diff(parent_graph or {}, graph) if parent_graph is not None else None}


def compute(graph: dict[str, Any], items: list[dict[str, Any]], images: list[dict[str, Any]], *, parent_items: list[dict[str, Any]] | None = None,
            parent_graph: dict[str, Any] | None = None) -> dict[str, Any]:
    by_index = {int(im.get("index", -1)): im for im in images}
    labeled = match = 0
    tp = fp = tn = fn = 0
    mismatches: list[dict[str, Any]] = []
    for it in items:
        image = by_index.get(int(it.get("index", -1)), {})
        m, reasons = row_match(it, image)
        if m is None:
            continue
        labeled += 1
        match += int(m)
        exp, st = str(image.get("expected")), str(it.get("status", ""))
        if exp == "ng":
            tp += int(st == "ng")
            fn += int(st != "ng")
        else:
            tn += int(st == "ok")
            fp += int(st != "ok")
        if not m and len(mismatches) < MAX_MISMATCHES:
            mismatches.append({"index": it.get("index"), "name": image.get("name", ""), "expected": exp, "status": st,
                               "error_node": it.get("error_node"), "reasons": reasons, "outputs": it.get("outputs") or {}})
    errors = Counter(str(it.get("error_node")) for it in items if it.get("error_node"))
    by_id = {n["id"]: n for n in graph.get("nodes", [])}
    error_nodes = []
    for nid, count in errors.most_common(5):
        msg = next((str(((it.get("nodes") or {}).get(nid) or {}).get("message") or it.get("error") or "") for it in items if it.get("error_node") == nid), "")
        error_nodes.append({"node": nid, "label": (by_id.get(nid) or {}).get("label") or nid, "count": count, "message": msg[:160]})
    slowest = sorted(({"index": it.get("index"), "name": by_index.get(int(it.get("index", -1)), {}).get("name", ""), "duration_ms": float(it.get("duration_ms") or 0)} for it in items),
                     key=lambda r: -r["duration_ms"])[:MAX_SLOWEST]
    node_time: dict[str, list[float]] = {}
    for it in items:
        for nid, nr in (it.get("nodes") or {}).items():
            node_time.setdefault(nid, []).append(float(nr.get("duration_ms") or 0))
    node_avg = sorted(({"node": nid, "label": (by_id.get(nid) or {}).get("label") or nid, "avg_ms": round(sum(v) / len(v), 2)} for nid, v in node_time.items() if v),
                      key=lambda r: -r["avg_ms"])[:MAX_SLOWEST]
    keys = sorted({k for it in items for k, v in (it.get("outputs") or {}).items() if _num(v) is not None})
    outputs = []
    for key in keys:
        vals = [(it, _num((it.get("outputs") or {}).get(key))) for it in items]
        vals = [(it, v) for it, v in vals if v is not None]
        outputs.append({
            "key": key, "all": _stats([v for _, v in vals]),
            "by_expected": {e: _stats([v for it, v in vals if by_index.get(int(it.get("index", -1)), {}).get("expected") == e]) for e in ("ok", "ng")},
            "by_status": {s: _stats([v for it, v in vals if it.get("status") == s]) for s in ("ok", "ng")},
        })
    judges = _judges(graph, items, by_index)
    vs_parent = _vs_parent(items, parent_items, by_index, graph, parent_graph)
    total = len(items)
    counts = Counter(str(it.get("status")) for it in items)
    text: list[str] = [f"共 {total} 張：OK {counts.get('ok', 0)}、NG {counts.get('ng', 0)}、失敗 {total - counts.get('ok', 0) - counts.get('ng', 0)}。"]
    if labeled:
        text.append(f"有期望標記 {labeled} 張，命中 {match} 張（{match / labeled:.0%}）；期望 NG 抓到 {tp}、漏檢 {fn}、期望 OK 誤判 {fp}。")
        if mismatches:
            text.append("未命中：" + "、".join(f"#{m['index'] + 1} {m['name']}（期望 {m['expected'].upper()} 實際 {m['status'].upper()}）" for m in mismatches[:8]) + ("…" if len(mismatches) > 8 else ""))
    else:
        text.append("尚未標記任何影像的期望判定；標記後才能計算命中率與建議門檻。")
    for e in error_nodes:
        text.append(f"節點「{e['label']}」出錯 {e['count']} 次：{e['message']}")
    for j in judges:
        vo, vn = j["values"]["expected_ok"], j["values"]["expected_ng"]
        if vo.get("n") and vn.get("n"):
            text.append(f"判定「{j['label']}」的輸入值（{j['value_from']['label']}.{j['value_from']['port']}）：期望 OK 落在 {vo['min']}～{vo['max']}、期望 NG 落在 {vn['min']}～{vn['max']}"
                        + ("（可完全分開）" if j.get("separable") else "（有重疊）") + "。")
        if j.get("suggestion"):
            sug = "、".join(f"{k}={v}" for k, v in j["suggestion"].items())
            cur = "、".join(f"{k}={v}" for k, v in (j.get("current") or {}).items() if k in j["suggestion"])
            text.append(f"建議把「{j['label']}」的 {cur} 改為 {sug}：命中率 {j['acc_now']:.0%} → {j['acc_suggested']:.0%}。")
    if vs_parent:
        text.append(f"與上一次執行相比：{len(vs_parent['changed'])} 張判定改變，改善 {len(vs_parent['improved'])} 張、退步 {len(vs_parent['regressed'])} 張。")
        if vs_parent.get("param_diff") and vs_parent["param_diff"]["rows"]:
            text.append("參數變動：" + "、".join(f"{r['label']}.{r['key']} {r['from']} → {r['to']}" for r in vs_parent["param_diff"]["rows"][:8]))
    if slowest:
        text.append(f"最慢的影像 #{slowest[0]['index'] + 1} {slowest[0]['name']} 花 {slowest[0]['duration_ms']:.0f} ms" + (f"；最耗時節點「{node_avg[0]['label']}」平均 {node_avg[0]['avg_ms']:.0f} ms" if node_avg else "") + "。")
    return {
        "labeled": labeled, "match": match, "match_rate": round(match / labeled, 4) if labeled else None,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn}, "mismatches": mismatches, "error_nodes": error_nodes,
        "slowest": slowest, "node_time": node_avg, "outputs": outputs, "judges": judges, "vs_parent": vs_parent, "text": text,
    }


def suggestions_of(insights: dict[str, Any]) -> list[dict[str, Any]]:
    """洞察裡可直接套用的參數建議（給諮詢回覆與前端「套用建議」）。"""
    out = []
    for j in insights.get("judges") or []:
        for key, value in (j.get("suggestion") or {}).items():
            out.append({"node": j["node"], "label": j["label"], "key": key, "value": value,
                        "reason": f"命中率 {j.get('acc_now') or 0:.0%} → {j.get('acc_suggested') or 0:.0%}"})
    return out


def apply_suggestions(graph: dict[str, Any], suggestions: list[dict[str, Any]]) -> dict[str, Any]:
    g = json.loads(json.dumps(graph))
    by_id = {n["id"]: n for n in g.get("nodes", [])}
    for s in suggestions:
        n = by_id.get(str(s.get("node", "")))
        if n is not None and s.get("key"):
            n.setdefault("params", {})[str(s["key"])] = s.get("value")
    return g
