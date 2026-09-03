"""資料驅動自動調參（座標下降）：對 graph 裡現場調機參數（teach=True）逐一試候選值，在有標記的影像上嚴格變好才採納。

用途：
- AI 助手生成時（影像帶 OK/NG 標記）小預算跑一次；
- 批次測試「自動調參」（每列填期望）；
- Golden Set「自動調參」（用案例期望值與期望輸出）。

原則：
- 只動 teach=True 的參數，不動規格（公差、期望數量、亮度範圍、校正值）——調那些等於改題目。
- 候選值＝目前值的幾何階梯（×0.5／×0.7／×1.4／×2）夾在 minimum/maximum 內；0～1 型走 ±0.1／±0.2；select 全選項；boolean 翻轉。
- 分數 = (命中數, −錯誤節點影像數, −失敗影像數)，嚴格變好才換（同分不換，抗過擬合）；命中全部即停。
- 預算：評估次數＋秒數，到了就停並回報 budget_hit。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from apps.golden.regress import evaluate_expect
from apps.vision.tools import base as tools

#: 不搜尋的參數：(工具, 參數)；參數 "*" = 整個工具。
SKIP: frozenset[tuple[str, str]] = frozenset({
    ("tolerance_judge", "*"), ("in_range", "*"), ("if_number", "threshold"), ("calibration", "*"),
    ("barcode", "*"), ("shape_align", "*"), ("fixture_roi", "*"), ("template_match", "angle_range"),
})

#: 必須是奇數的參數（核大小／區塊）。
ODD_KEYS = ("block", "ksize", "blur", "morph", "smoothing")

#: 數值參數的幾何階梯（由近到遠：小改動先試、同分不換，才不會為了命中亂跳；遠端讓離譜的初值也救得回來）。
NUMBER_FACTORS = (0.7, 1.4, 0.5, 2.0, 0.25, 4.0, 0.1, 10.0)

Trial = Callable[[dict[str, Any], np.ndarray], Any]


@dataclass
class Dim:
    node_id: str
    label: str
    key: str
    current: Any
    candidates: list[Any]
    tool_type: str = ""


@dataclass
class Labeled:
    image: np.ndarray
    expect_status: str = "any"
    expect_outputs: dict[str, Any] = field(default_factory=dict)
    name: str = ""


@dataclass(order=True)
class Score:
    matches: int
    neg_errors: int
    neg_failed: int
    total: int = field(compare=False, default=0)

    def perfect(self) -> bool:
        return self.matches == self.total and self.neg_errors == 0 and self.neg_failed == 0

    def as_dict(self) -> dict[str, int]:
        return {"match": self.matches, "total": self.total, "errors": -self.neg_errors, "failed": -self.neg_failed}


def _skip(tool_type: str, key: str) -> bool:
    return (tool_type, "*") in SKIP or (tool_type, key) in SKIP


def _visible(p: Any, params: dict[str, Any], tool: Any) -> bool:
    vw = getattr(p, "visible_when", None)
    if not vw:
        return True
    dep = str(vw.get("param", ""))
    default = next((q.default for q in tool.params if q.key == dep), None)
    return params.get(dep, default) in (vw.get("in") or [])


def _ladder(p: Any, v: Any) -> list[Any]:
    """一個參數的候選值階梯（不含目前值）。"""
    if p.kind == "boolean":
        return [not bool(v)]
    if p.kind == "select":
        return [o["value"] for o in (p.options or []) if o["value"] != v]
    if p.kind == "range":
        lo = float(p.minimum) if p.minimum is not None else 0.0
        hi = float(p.maximum) if p.maximum is not None else 1.0
        step = max((hi - lo) * 0.1, 1e-6)
        out: list[Any] = []
        try:
            cur = float(v)
        except (TypeError, ValueError):
            return []
        for k in (-2, -1, 1, 2):
            c = round(min(hi, max(lo, cur + k * step)), 4)
            if c != cur and c not in out:
                out.append(c)
        return out
    if p.kind == "number":
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v == 0:
            return []
        out = []
        for f in NUMBER_FACTORS:
            c = float(v) * f
            if p.minimum is not None:
                c = max(float(p.minimum), c)
            if p.maximum is not None:
                c = min(float(p.maximum), c)
            c = int(round(c)) if isinstance(v, int) else round(c, 4)
            if p.key in ODD_KEYS and isinstance(c, int) and c % 2 == 0:
                c += 1
                if p.maximum is not None and c > p.maximum:
                    c -= 2
            if c != v and c not in out:
                out.append(c)
        return out
    return []


def search_space(graph: dict[str, Any], priors: dict[tuple[str, str], Any] | None = None) -> list[Dim]:
    """走訪 graph，每個 teach=True 且可見的參數一個維度；priors（相似成功案例的值）排在候選最前面先試。"""
    dims: list[Dim] = []
    for n in graph.get("nodes", []):
        t = str(n.get("type", ""))
        if t == "note" or n.get("enabled", True) is False or not tools.has(t):
            continue
        tool = tools.get(t)
        params = n.get("params") or {}
        for p in tool.params:
            if not getattr(p, "teach", False) or _skip(t, p.key) or not _visible(p, params, tool):
                continue
            v = params.get(p.key, p.default)
            cands = _ladder(p, v)
            prior = (priors or {}).get((t, p.key))
            if prior is not None and prior != v:
                cands = [prior] + [c for c in cands if c != prior]
            if cands:
                dims.append(Dim(n["id"], str(n.get("label") or n["id"]), p.key, v, cands, t))
    return dims


def _default_trial() -> Trial:
    from apps.vision.agent import service

    return lambda g, im: service.trial_run(g, im, keep_images=False)


def evaluate(graph: dict[str, Any], labeled: list[Labeled], trial: Trial) -> Score:
    matches = errors = failed = 0
    for lb in labeled:
        rep = trial(graph, lb.image)
        ok, _ = evaluate_expect(lb.expect_status, lb.expect_outputs or None, rep.status, rep.outputs)
        matches += int(ok)
        if any(getattr(nr, "status", "") == "error" for nr in rep.nodes.values()):
            errors += 1
        if rep.status not in ("ok", "ng"):
            failed += 1
    return Score(matches, -errors, -failed, len(labeled))


def describe(changes: list[dict[str, Any]]) -> list[str]:
    return [f"{c['label']}.{c['key']}：{c['from']} → {c['to']}" for c in changes]


def coordinate_search(graph: dict[str, Any], labeled: list[Labeled], *, max_evals: int = 60, deadline_s: float = 25.0,
                      trial: Trial | None = None, max_passes: int = 3, priors: dict[tuple[str, str], Any] | None = None) -> dict[str, Any]:
    """座標下降：每個維度依序試候選值，嚴格變好就採納並進下一個維度；一輪沒有任何改善或預算用完即停。"""
    trial = trial or _default_trial()
    t0 = time.perf_counter()
    best = json.loads(json.dumps(graph))
    if not labeled:
        return {"graph": best, "before": Score(0, 0, 0, 0).as_dict(), "after": Score(0, 0, 0, 0).as_dict(), "changes": [], "change_text": [],
                "evals": 0, "elapsed_ms": 0, "improved": False, "budget_hit": False}
    best_score = evaluate(best, labeled, trial)
    before = best_score
    evals = 1
    changes: list[dict[str, Any]] = []
    budget_hit = False

    def out_of_budget() -> bool:
        return evals >= max_evals or (time.perf_counter() - t0) > deadline_s

    for _ in range(max_passes):
        if best_score.perfect():
            break
        improved_pass = False
        for dim in search_space(best, priors):
            if budget_hit or best_score.perfect():
                break
            for cand in dim.candidates:
                if out_of_budget():
                    budget_hit = True
                    break
                candidate = json.loads(json.dumps(best))
                node = next(n for n in candidate["nodes"] if n["id"] == dim.node_id)
                node.setdefault("params", {})[dim.key] = cand
                evals += 1
                try:
                    sc = evaluate(candidate, labeled, trial)
                except Exception:  # noqa: BLE001 - 候選參數讓工具炸掉就當作不可行
                    continue
                if sc > best_score:
                    changes.append({"node": dim.node_id, "label": dim.label, "key": dim.key, "from": dim.current, "to": cand, "match": sc.matches})
                    best, best_score = candidate, sc
                    improved_pass = True
                    break
        if not improved_pass or budget_hit:
            break
    return {
        "graph": best, "before": before.as_dict(), "after": best_score.as_dict(), "changes": changes, "change_text": describe(changes),
        "evals": evals, "elapsed_ms": round((time.perf_counter() - t0) * 1000), "improved": best_score > before, "budget_hit": budget_hit,
    }
