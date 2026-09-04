"""資料諮詢：針對一次批次執行的資料回答問題（「為什麼第 3 張 NG？」「哪個門檻該調？」）。

一律先算規則洞察（apps/vision/batch/insights），建議參數由洞察提供；LLM 可用時以洞察文字＋逐張資料＋流程 graph 當上下文回答，
回答尾端可附 SUGGESTIONS: {"suggestions":[{node,key,value,reason}]}，伺服器驗證（節點存在、參數存在、graph 仍有效）後才回前端；
沒有 LLM 或失敗時用離線模板回答並在 warnings 說明。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import numpy as np

from apps.vision.agent import llm, providers, skills
from apps.vision.batch import insights as insights_mod
from apps.vision.batch import store
from apps.vision.graph import validate_graph
from apps.vision.tools import base as tools

log = logging.getLogger("vision.agent")

MAX_ROWS = 50
MAX_IMAGES = 4

CONSULT_INSTRUCTION = """你現在是現場調機顧問。只依下面提供的批次資料、洞察與流程回答使用者的問題：
- 用提問的語言回答（資料與流程是英文）；先給結論再給理由，條列為主，不超過 250 字；引用資料時寫出影像編號與數值。
- 不得更改規格（公差、期望數量、亮度範圍）；可調的是門檻、最小面積、邊緣門檻這類現場參數。
- 若有具體參數建議，在回答最後另起一行輸出：SUGGESTIONS: {"suggestions":[{"node":"節點id","key":"參數","value":數值或字串,"reason":"一句話"}]}；沒有建議就輸出 SUGGESTIONS: {"suggestions":[]}。"""


def _rows_text(run_items: list[dict[str, Any]], images: list[dict[str, Any]], ins: dict[str, Any]) -> str:
    """逐張資料（未命中優先、最多 50 列）：狀態、期望、具名輸出與判定節點的輸入值。"""
    by_index = {int(im.get("index", -1)): im for im in images}
    judge_src = {(j["value_from"]["node"], j["value_from"]["port"]): j["label"] for j in ins.get("judges") or []}

    def row_line(it: dict[str, Any]) -> str:
        idx = int(it.get("index", -1))
        im = by_index.get(idx, {})
        m, _ = store.row_match(it, im)
        outs = {k: v for k, v in (it.get("outputs") or {}).items() if isinstance(v, (int, float, str)) and not isinstance(v, bool)}
        judge_vals = {label: ((it.get("nodes") or {}).get(node) or {}).get("outputs", {}).get(port) for (node, port), label in judge_src.items()}
        judge_vals = {k: v for k, v in judge_vals.items() if v is not None}
        bits = [f"#{idx + 1} {im.get('name', '')}: {str(it.get('status', '')).upper()}"]
        if im.get("expected"):
            bits.append(f"expected {str(im['expected']).upper()}" + (" (missed)" if m is False else ""))
        if outs:
            bits.append("outputs " + json.dumps(outs, ensure_ascii=False))
        if judge_vals:
            bits.append("judging input " + json.dumps(judge_vals, ensure_ascii=False))
        if it.get("error"):
            bits.append(f"error {it['error'][:80]}")
        return "- " + ", ".join(bits)

    ordered = sorted(run_items, key=lambda it: 0 if store.row_match(it, by_index.get(int(it.get("index", -1)), {}))[0] is False else 1)
    lines = [row_line(it) for it in ordered[:MAX_ROWS]]
    if len(run_items) > MAX_ROWS:
        lines.append(f"… ({len(run_items) - MAX_ROWS} more images not listed)")
    return "\n".join(lines)


def _pick_images(run_items: list[dict[str, Any]], images: list[dict[str, Any]]) -> list[np.ndarray]:
    """未命中的影像優先，最多 4 張。"""
    by_index = {int(im.get("index", -1)): im for im in images}
    mism = [it for it in run_items if store.row_match(it, by_index.get(int(it.get("index", -1)), {}))[0] is False]
    rest = [it for it in run_items if it not in mism]
    out: list[np.ndarray] = []
    for it in [*mism, *rest][:MAX_IMAGES]:
        img = store.load_image(by_index.get(int(it.get("index", -1))))
        if img is not None:
            out.append(img)
    return out


def _validate_suggestions(graph: dict[str, Any], raw: Any) -> tuple[list[dict[str, Any]], list[str]]:
    by_id = {n["id"]: n for n in graph.get("nodes", [])}
    good: list[dict[str, Any]] = []
    warnings: list[str] = []
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        node, key = str(s.get("node", "")), str(s.get("key", ""))
        n = by_id.get(node)
        if n is None or not tools.has(str(n.get("type", ""))):
            warnings.append(f"Suggestion skipped: node {node} does not exist")
            continue
        param = next((p for p in tools.get(str(n["type"])).params if p.key == key), None)
        if param is None:
            warnings.append(f"Suggestion skipped: {node} has no parameter {key}")
            continue
        value = s.get("value")
        if param.kind in ("number", "range") and isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                warnings.append(f"Suggestion skipped: the value of {node}.{key} is not a number")
                continue
        try:
            validate_graph(insights_mod.apply_suggestions(graph, [{"node": node, "key": key, "value": value}]))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Suggestion skipped: {node}.{key}={value!r} fails validation ({str(exc)[:80]})")
            continue
        good.append({"node": node, "label": n.get("label") or node, "key": key, "value": value, "reason": str(s.get("reason") or "")[:200]})
    return good, warnings


def parse_reply(text: str) -> tuple[str, Any]:
    """把回答與尾端的 SUGGESTIONS JSON 分開。"""
    m = re.search(r"SUGGESTIONS\s*[:：]\s*(\{.*\})\s*$", text, re.DOTALL)
    if not m:
        return text.strip(), None
    answer = text[: m.start()].strip()
    try:
        payload = json.loads(m.group(1))
    except ValueError:
        return answer, None
    return answer, payload.get("suggestions") if isinstance(payload, dict) else None


def offline_answer(question: str, ins: dict[str, Any]) -> str:
    """離線模板：依問題關鍵詞挑洞察段落。"""
    text = list(ins.get("text") or [])
    q = (question or "").lower()
    picked: list[str] = []
    # 洞察句子已是英文；提問可能是中文或英文，兩邊關鍵詞都比對
    if any(w in q for w in ("門檻", "threshold", "參數", "param", "調", "tune", "建議", "suggest")):
        picked += [t for t in text if "Consider changing" in t or "judging node" in t]
    if any(w in q for w in ("為什麼", "为什么", "why", "哪些", "which", "未命中", "miss", "ng", "錯", "error", "fail")):
        picked += [t for t in text if "Missed:" in t or "errored" in t or "matched" in t]
    if any(w in q for w in ("慢", "slow", "耗時", "時間", "time", "ms")):
        picked += [t for t in text if "ms" in t]
    if any(w in q for w in ("上一次", "previous", "比較", "compare", "差異", "diff", "改善", "improve")):
        picked += [t for t in text if "previous run" in t or "Parameters changed" in t]
    lines = picked or text
    seen: list[str] = []
    for line in lines:
        if line not in seen:
            seen.append(line)
    if not any("Consider changing" in line for line in seen) and ins.get("labeled"):
        seen.append("The data does not point to a better threshold yet. Check that the missed images are labelled correctly, or add more OK and NG images.")
    return "(offline rule analysis)\n" + "\n".join(f"- {line}" for line in seen)


def consult(run: Any, batch_set: Any, question: str, settings: providers.AgentSettings, *, graph: dict[str, Any] | None = None, user: Any = None) -> dict[str, Any]:
    graph = validate_graph(graph) if graph else run.graph
    images = batch_set.images or []
    items = run.items or []
    parent = None
    if run.parent_id:
        from apps.vision.models import BatchRun

        parent = BatchRun.objects.filter(pk=run.parent_id).only("items", "graph").first()
    ins = insights_mod.compute(graph, items, images, parent_items=parent.items if parent else None, parent_graph=parent.graph if parent else None)
    rule_suggestions = insights_mod.suggestions_of(ins)
    warnings: list[str] = []
    if providers.available(settings):
        try:
            focus = skills.select_tools(question, graph=graph, limit=8)
            text = "\n".join([
                f"Question: {question}", "",
                "The current flow graph:\n" + json.dumps(graph, ensure_ascii=False),
                "Insights from the rule engine:\n" + "\n".join(f"- {t}" for t in ins.get("text") or []),
                "Per-image data:\n" + _rows_text(items, images, ins),
                skills.focus_text(focus, user), "", CONSULT_INSTRUCTION,
            ])
            reply = providers.complete(settings, llm.system_prompt(), [llm.encode_image(im) for im in _pick_images(items, images)], text)
            answer, raw = parse_reply(reply)
            suggestions, sug_warnings = _validate_suggestions(graph, raw)
            warnings += sug_warnings
            if not suggestions:
                suggestions = rule_suggestions
            return {"answer": answer or "(the model returned nothing)", "provider": settings.provider, "insights": ins, "suggestions": suggestions, "warnings": warnings}
        except Exception as exc:  # noqa: BLE001 - LLM 失敗落回離線模板
            log.warning("諮詢 LLM 失敗：%s", exc)
            warnings.append(f"LLM（{settings.provider}）失敗，已改用規則分析：{providers._explain(exc, providers.generate_timeout())}")
    return {"answer": offline_answer(question, ins), "provider": "rules", "insights": ins, "suggestions": rule_suggestions, "warnings": warnings}
