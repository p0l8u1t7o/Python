"""AI 助手編排：分析 → 生成（LLM 或規則）→ 驗證 → 在使用者影像上試跑 → 迭代微調。

生成結果永遠經 validate_graph 把關、並用引擎實跑一次（run 的節點影像進快取，
前端直接顯示 overlay）。LLM 失敗或未設定時自動落回規則引擎，功能完全離線可用。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import numpy as np

from apps.vision import engine
from apps.vision.agent import analysis as analysis_mod
from apps.vision.agent import intents, llm, synth
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.models import Asset

log = logging.getLogger("vision.agent")

#: 助手試跑用的 flow_id（影像快取的桶）；不對應任何真實流程。
AGENT_FLOW_ID = 0


def _asset_path(asset_id: str) -> str | None:
    row = Asset.objects.filter(pk=asset_id).only("path").first()
    return row.path if row else None


def trial_run(graph: dict[str, Any], image: np.ndarray) -> engine.RunReport:
    """把 graph 在使用者影像上跑一遍（不落 DB、不佔流程執行緒池）。"""
    compiled = compile_graph(graph)
    return engine.execute(
        compiled, flow_id=AGENT_FLOW_ID, flow_version=0, trigger="agent",
        grab=lambda sid: None, asset_path=_asset_path,
        preview=True, input_image=image, run_id=f"agent{uuid.uuid4().hex[:12]}",
    )


def generate(image: np.ndarray, regions: list[dict[str, Any]], prompt: str,
             *, use_llm: bool | None = None) -> dict[str, Any]:
    """上傳影像＋ROI＋提示詞 → {graph, rationale, provider, intent, report}。"""
    feats = analysis_mod.analyze(image, regions)
    provider = "rules"
    graph: dict[str, Any] | None = None
    rationale = ""
    intent_kind = ""
    want_llm = llm.available() if use_llm is None else (use_llm and llm.available())
    if want_llm:
        try:
            graph, rationale = llm.generate(image, regions, prompt, feats)
            provider = "llm"
        except Exception:  # noqa: BLE001 - LLM 掛掉一律落回規則引擎
            log.exception("LLM 生成失敗，落回規則引擎")
    if graph is None:
        intent = intents.parse(prompt, regions, feats)
        intent_kind = intent.kind
        graph, rationale = synth.synthesize(intent, regions, feats)
        graph = validate_graph(graph)
    report = trial_run(graph, image)
    return {
        "graph": graph,
        "rationale": rationale,
        "provider": provider,
        "intent": intent_kind,
        "report": report.to_dict(include_node_outputs=True),
    }


# ---------------------------------------------------------------------------
# 規則式微調：把口語回饋映射到參數調整
# ---------------------------------------------------------------------------
def _scale_param(node: dict[str, Any], key: str, factor: float, minimum: float = 0.0) -> bool:
    val = node.get("params", {}).get(key)
    if isinstance(val, (int, float)):
        node["params"][key] = type(val)(max(minimum, val * factor))
        return True
    return False


def refine_rules(graph: dict[str, Any], feedback: str) -> tuple[dict[str, Any], list[str]]:
    """常見回饋的參數調整。回 (新 graph, 變更說明列表)；沒改到任何東西回空列表。"""
    out = json.loads(json.dumps(graph))
    text = feedback.lower()
    changed: list[str] = []
    looser = any(w in text for w in ("太敏感", "誤判", "誤報", "误判", "误报", "抓太多", "太嚴", "太严", "false"))
    tighter = any(w in text for w in ("漏", "抓不到", "沒抓到", "没抓到", "太鬆", "太松", "miss"))
    import re

    m = re.search(r"(\d+)\s*[個个顆颗孔洞支根件]", feedback)
    new_count = int(m.group(1)) if m else None
    m = re.search(r"[±\+\-]\s*(\d+(?:\.\d+)?)", feedback)
    new_tol = float(m.group(1)) if m else None

    for node in out.get("nodes", []):
        params = node.setdefault("params", {})
        t = node.get("type")
        if new_count is not None and t == "if_number" and params.get("operator") == "eq":
            params["threshold"] = new_count
            changed.append(f"期望數量改為 {new_count}")
        if new_tol is not None and t == "tolerance_judge":
            params["upper_tol"] = new_tol
            params["lower_tol"] = -new_tol
            changed.append(f"公差改為 ±{new_tol}")
        if looser:
            if t == "blob" and _scale_param(node, "min_area", 2.0, 10):
                changed.append(f"blob 最小面積放大到 {params['min_area']}")
            if t == "color_check" and _scale_param(node, "tolerance", 1.4, 1):
                changed.append(f"顏色容差放寬到 {params['tolerance']:.0f}")
            if t == "pixel_count" and _scale_param(node, "min_count", 1.5, 1):
                changed.append(f"像素門檻提高到 {params['min_count']}")
            if t == "template_match" and isinstance(params.get("threshold"), (int, float)):
                params["threshold"] = max(0.3, float(params["threshold"]) - 0.1)
                changed.append(f"比對分數門檻降到 {params['threshold']:.2f}")
        if tighter:
            if t == "blob" and _scale_param(node, "min_area", 0.5, 5):
                changed.append(f"blob 最小面積縮小到 {params['min_area']}")
            if t == "color_check" and _scale_param(node, "tolerance", 0.7, 1):
                changed.append(f"顏色容差收緊到 {params['tolerance']:.0f}")
            if t in ("find_circle", "find_line", "caliper", "wall_thickness", "chamfer_angle") and _scale_param(node, "edge_threshold", 0.6, 3):
                changed.append(f"{t} 邊緣門檻降到 {params['edge_threshold']:.0f}")
            if t == "pixel_count" and _scale_param(node, "min_count", 0.6, 1):
                changed.append(f"像素門檻降低到 {params['min_count']}")
    return out, changed


def refine(image: np.ndarray, regions: list[dict[str, Any]], prompt: str,
           graph: dict[str, Any], feedback: str) -> dict[str, Any]:
    """依回饋微調：LLM 可用時整包交給 LLM 修；否則先試規則映射，沒命中就併回饋重生成。"""
    feats = analysis_mod.analyze(image, regions)
    provider = "rules"
    rationale = ""
    if llm.available():
        try:
            new_graph, rationale = llm.generate(image, regions, prompt, feats, previous_graph=graph, feedback=feedback)
            provider = "llm"
            report = trial_run(new_graph, image)
            return {"graph": new_graph, "rationale": rationale, "provider": provider, "intent": "",
                    "report": report.to_dict(include_node_outputs=True)}
        except Exception:  # noqa: BLE001
            log.exception("LLM 微調失敗，落回規則引擎")
    new_graph, changed = refine_rules(graph, feedback)
    if changed:
        new_graph = validate_graph(new_graph)
        rationale = "已調整：" + "、".join(changed)
    else:
        merged = f"{prompt}\n{feedback}".strip()
        result = generate(image, regions, merged, use_llm=False)
        result["rationale"] = "回饋無法對應到參數，已併入需求重新生成：" + result["rationale"]
        return result
    report = trial_run(new_graph, image)
    return {"graph": new_graph, "rationale": rationale, "provider": provider, "intent": "",
            "report": report.to_dict(include_node_outputs=True)}
