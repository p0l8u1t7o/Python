"""AI 助手編排：分析 → 生成（LLM 或規則）→ 驗證 → 在使用者影像上試跑 → 迭代微調／編輯／批次調參。

生成結果永遠經 validate_graph 把關、並用引擎實跑（run 的節點影像進快取，前端直接顯示 overlay）。
LLM 失敗或未設定時自動落回規則引擎，功能完全離線可用。
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any

import cv2
import numpy as np
from django.conf import settings as dj_settings

from apps.vision import engine
from apps.vision.agent import analysis as analysis_mod
from apps.vision.agent import intents, llm, providers, synth
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.models import Asset
from apps.vision.tools import base as tools
from apps.vision.tools.roi import crop as roi_crop

log = logging.getLogger("vision.agent")

#: 助手試跑用的 flow_id（影像快取的桶）；不對應任何真實流程。
AGENT_FLOW_ID = 0


def _asset_path(asset_id: str) -> str | None:
    row = Asset.objects.filter(pk=asset_id).only("path").first()
    return row.path if row else None


def trial_run(graph: dict[str, Any], image: np.ndarray) -> engine.RunReport:
    """把 graph 在一張影像上跑一遍（不落 DB、不佔流程執行緒池）。"""
    compiled = compile_graph(graph)
    return engine.execute(
        compiled, flow_id=AGENT_FLOW_ID, flow_version=0, trigger="agent",
        grab=lambda sid: None, asset_path=_asset_path,
        preview=True, input_image=image, run_id=f"agent{uuid.uuid4().hex[:12]}",
    )


def _run_all(graph: dict[str, Any], images: list[np.ndarray], main: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reports = [trial_run(graph, im).to_dict(include_node_outputs=True) for im in images]
    return reports[main], reports


def _main_image(regions: list[dict[str, Any]], intent: intents.Intent | None, count: int) -> int:
    """主影像：壞品 ROI 所在那張 → ROI 最多的那張 → 第一張。"""
    if intent is not None and intent.bad_roi is not None and intent.bad_roi < len(regions):
        idx = int(regions[intent.bad_roi].get("image", 0) or 0)
        if 0 <= idx < count:
            return idx
    votes: dict[int, int] = {}
    for r in regions:
        idx = int(r.get("image", 0) or 0)
        if 0 <= idx < count:
            votes[idx] = votes.get(idx, 0) + 1
    return max(votes, key=lambda k: votes[k]) if votes else 0


def _make_asset_factory(images: list[np.ndarray]):
    def make_asset(image_idx: int, region: dict[str, Any], name: str) -> str:
        img = images[image_idx] if 0 <= image_idx < len(images) else images[0]
        piece = roi_crop(img, region, upright=True).image
        if piece.size == 0:
            return ""
        asset_id = uuid.uuid4()
        path = os.path.join(str(dj_settings.VISION["ASSET_DIR"]), f"{asset_id.hex}.png")
        ok, buf = cv2.imencode(".png", piece)
        if not ok:
            return ""
        buf.tofile(path)
        Asset.objects.create(
            id=asset_id, name=f"{name} {asset_id.hex[:6]}", kind="image", group="AI 助手", path=path, size=int(buf.size),
            meta={"width": int(piece.shape[1]), "height": int(piece.shape[0]), "channels": int(piece.shape[2]) if piece.ndim == 3 else 1},
        )
        return str(asset_id)

    return make_asset


def _result(graph: dict[str, Any], rationale: str, provider: str, intent: str, report: dict[str, Any],
            reports: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"graph": graph, "rationale": rationale, "provider": provider, "intent": intent, "report": report, "reports": reports, **extra}


def _try_llm(settings: providers.AgentSettings, use_llm: bool | None, **kw: Any) -> tuple[dict[str, Any], str] | None:
    want = providers.available(settings) if use_llm is None else (use_llm and providers.available(settings))
    if not want:
        return None
    try:
        return llm.generate(settings, **kw)
    except Exception:  # noqa: BLE001 - LLM 掛掉一律落回規則引擎
        log.exception("LLM（%s）生成失敗，落回規則引擎", settings.provider)
        return None


def generate(images: list[np.ndarray], regions: list[dict[str, Any]], prompt: str,
             settings: providers.AgentSettings | None = None, *, use_llm: bool | None = None) -> dict[str, Any]:
    """上傳影像們＋ROI＋提示詞 → {graph, rationale, provider, intent, report, reports}。"""
    settings = settings or providers.server_settings()
    feats = analysis_mod.analyze(images, regions)
    got = _try_llm(settings, use_llm, images=images, regions=regions, prompt=prompt, analysis=feats)
    if got is not None:
        graph, rationale = got
        main = _main_image(regions, None, len(images))
        report, reports = _run_all(graph, images, main)
        return _result(graph, rationale, settings.provider, "", report, reports, main_image=main)
    intent = intents.parse(prompt, regions, feats)
    graph, rationale = synth.synthesize(intent, regions, feats, make_asset=_make_asset_factory(images))
    graph = validate_graph(graph)
    main = _main_image(regions, intent, len(images))
    report, reports = _run_all(graph, images, main)
    return _result(graph, rationale, "rules", intent.kind, report, reports, main_image=main)


# ---------------------------------------------------------------------------
# 規則式微調：把口語回饋映射到參數調整
# ---------------------------------------------------------------------------
def _scale_param(node: dict[str, Any], key: str, factor: float, minimum: float = 0.0) -> bool:
    val = node.get("params", {}).get(key)
    if isinstance(val, (int, float)) and not isinstance(val, bool):
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
            if t == "defect_diff" and _scale_param(node, "threshold", 1.3, 1) and _scale_param(node, "min_area", 2.0, 10):
                changed.append(f"良品比對門檻 {params['threshold']:.0f}、最小面積 {params['min_area']}")
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
            if t == "defect_diff" and _scale_param(node, "threshold", 0.75, 1):
                changed.append(f"良品比對門檻降到 {params['threshold']:.0f}")
            if t == "color_check" and _scale_param(node, "tolerance", 0.7, 1):
                changed.append(f"顏色容差收緊到 {params['tolerance']:.0f}")
            if t in ("find_circle", "find_line", "caliper", "wall_thickness", "chamfer_angle") and _scale_param(node, "edge_threshold", 0.6, 3):
                changed.append(f"{t} 邊緣門檻降到 {params['edge_threshold']:.0f}")
            if t == "pixel_count" and _scale_param(node, "min_count", 0.6, 1):
                changed.append(f"像素門檻降低到 {params['min_count']}")
    return out, changed


def refine(images: list[np.ndarray], regions: list[dict[str, Any]], prompt: str, graph: dict[str, Any], feedback: str,
           settings: providers.AgentSettings | None = None) -> dict[str, Any]:
    """依回饋微調：LLM 可用時整包交給 LLM 修；否則先試規則映射，沒命中就併回饋重生成。"""
    settings = settings or providers.server_settings()
    feats = analysis_mod.analyze(images, regions)
    main = _main_image(regions, None, len(images))
    got = _try_llm(settings, None, images=images, regions=regions, prompt=prompt, analysis=feats,
                   task="refine", previous_graph=graph, feedback=feedback)
    if got is not None:
        new_graph, rationale = got
        report, reports = _run_all(new_graph, images, main)
        return _result(new_graph, rationale, settings.provider, "", report, reports, main_image=main)
    new_graph, changed = refine_rules(graph, feedback)
    if not changed:
        merged = f"{prompt}\n{feedback}".strip()
        result = generate(images, regions, merged, settings, use_llm=False)
        result["rationale"] = "回饋無法對應到參數，已併入需求重新生成：" + result["rationale"]
        return result
    new_graph = validate_graph(new_graph)
    report, reports = _run_all(new_graph, images, main)
    return _result(new_graph, "已調整：" + "、".join(changed), "rules", "", report, reports, main_image=main)


# ---------------------------------------------------------------------------
# 編輯器內的指令：改參數／啟停／刪除節點
# ---------------------------------------------------------------------------
_TRUE_WORDS = ("true", "開", "开", "啟用", "启用", "是", "on", "打開", "打开")
_FALSE_WORDS = ("false", "關", "关", "停用", "否", "off", "關閉", "关闭")


def _coerce(value: str, current: Any) -> Any:
    v = value.strip().strip("「」\"'")
    if isinstance(current, bool):
        return v.lower() in _TRUE_WORDS
    try:
        if isinstance(current, int) and not isinstance(current, bool):
            return int(float(v))
        if isinstance(current, float):
            return float(v)
        return float(v) if re.fullmatch(r"-?\d+(\.\d+)?", v) else v
    except ValueError:
        return v


def _find_nodes(graph: dict[str, Any], target: str) -> list[dict[str, Any]]:
    """用節點標題／id／工具名（key 或中文 label）比對；標題優先。"""
    t = target.strip().lower()
    if not t:
        return []
    labels = {d.key: d.label.lower() for d in tools.all_types()}
    exact = [n for n in graph["nodes"] if str(n.get("label", "")).lower() == t or n["id"].lower() == t]
    if exact:
        return exact
    partial = [n for n in graph["nodes"] if t in str(n.get("label", "")).lower() or t in n["id"].lower()]
    if partial:
        return partial
    return [n for n in graph["nodes"] if n["type"].lower() == t or labels.get(n["type"], "") == t or t in labels.get(n["type"], "")]


def _param_key(node_type: str, name: str) -> str | None:
    if not tools.has(node_type):
        return None
    n = name.strip().lower()
    for p in tools.get(node_type).params:
        if p.key.lower() == n or p.label.lower() == n:
            return p.key
    for p in tools.get(node_type).params:
        if n in p.label.lower() or n in p.key.lower():
            return p.key
    return None


def edit_rules(graph: dict[str, Any], instruction: str) -> tuple[dict[str, Any], list[str]]:
    """離線指令解析：「把 <節點> 的 <參數> 改成 <值>」「停用／啟用 <節點>」「刪除 <節點>」。"""
    out = json.loads(json.dumps(graph))
    changed: list[str] = []
    text = instruction.strip()
    m = re.search(r"(?:把|將|将|set)?\s*(.+?)\s*(?:的|'s)\s*(.+?)\s*(?:改成|改為|改为|設為|设为|設成|设成|調成|调成|調到|调到|改到|=|to)\s*([^\s，,。]+)", text)
    if m:
        target, pname, value = m.group(1), m.group(2), m.group(3)
        for node in _find_nodes(out, target):
            key = _param_key(node["type"], pname)
            if key is None:
                continue
            params = node.setdefault("params", {})
            default = next((p.default for p in tools.get(node["type"]).params if p.key == key), None)
            current = params.get(key, default)
            params[key] = _coerce(value, current)
            changed.append(f"{node.get('label') or node['id']}：{key} → {params[key]}")
    m = re.search(r"(?:停用|關閉|关闭|停掉|disable)\s*(.+)$", text)
    if m and not changed:
        for node in _find_nodes(out, m.group(1)):
            node["enabled"] = False
            changed.append(f"停用 {node.get('label') or node['id']}")
    m = re.search(r"(?:啟用|启用|打開|打开|開啟|开启|enable)\s*(.+)$", text)
    if m and not changed:
        for node in _find_nodes(out, m.group(1)):
            node["enabled"] = True
            changed.append(f"啟用 {node.get('label') or node['id']}")
    m = re.search(r"(?:刪除|删除|移除|拿掉|delete|remove)\s*(.+)$", text)
    if m and not changed:
        victims = {n["id"] for n in _find_nodes(out, m.group(1)) if n["type"] != "image_source"}
        if victims:
            out["nodes"] = [n for n in out["nodes"] if n["id"] not in victims]
            out["edges"] = [e for e in out["edges"] if e["source"] not in victims and e["target"] not in victims]
            changed.append(f"刪除 {', '.join(sorted(victims))}")
    if not changed:
        out, changed = refine_rules(out, instruction)
    return out, changed


def edit(graph: dict[str, Any], instruction: str, image: np.ndarray | None,
         settings: providers.AgentSettings | None = None) -> dict[str, Any]:
    """流程頁面的 AI 指令：LLM 可用時整份交給 LLM；否則離線指令解析。有影像就順便試跑。"""
    settings = settings or providers.server_settings()
    got = _try_llm(settings, None, images=[image] if image is not None else [], regions=[], prompt="", analysis=None,
                   task="edit", previous_graph=graph, feedback=instruction)
    if got is not None:
        new_graph, rationale = got
        provider, changes = settings.provider, []
    else:
        new_graph, changes = edit_rules(graph, instruction)
        if not changes:
            return {"graph": graph, "rationale": "看不懂這個指令。離線模式支援：「把 <節點> 的 <參數> 改成 <值>」、「停用／啟用 <節點>」、「刪除 <節點>」、「太敏感／漏抓／改成 N 個／±x」；接上 LLM 供應商可用自然語言增刪節點。",
                    "provider": "rules", "changes": [], "report": None, "applied": False}
        new_graph = validate_graph(new_graph)
        provider, rationale = "rules", "已調整：" + "、".join(changes)
    report = trial_run(new_graph, image).to_dict(include_node_outputs=True) if image is not None else None
    return {"graph": new_graph, "rationale": rationale, "provider": provider, "changes": changes, "report": report, "applied": True}


# ---------------------------------------------------------------------------
# 批次測試後的調參
# ---------------------------------------------------------------------------
def _batch_summary(runs: list[dict[str, Any]]) -> str:
    lines = []
    for r in runs[:50]:
        outs = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in (r.get("outputs") or {}).items() if not isinstance(v, (dict, list))}
        exp = f"，期望 {r['expected']}" if r.get("expected") else ""
        lines.append(f"- {r.get('name', '?')}：{r.get('status', '?')}{exp}，輸出 {json.dumps(outs, ensure_ascii=False)}")
    return "\n".join(lines)


def _tally(statuses: list[str]) -> dict[str, int]:
    return {"ok": statuses.count("ok"), "ng": statuses.count("ng"), "failed": sum(s not in ("ok", "ng") for s in statuses)}


def tune(graph: dict[str, Any], instruction: str, runs: list[dict[str, Any]], images: dict[str, np.ndarray],
         settings: providers.AgentSettings | None = None) -> dict[str, Any]:
    """跑多筆影像後依提示詞調整：LLM 帶批次摘要；規則走回饋映射。調完在同一批影像重跑回報前後對比。"""
    settings = settings or providers.server_settings()
    sample = [images[r["image_ref"]] for r in runs if r.get("image_ref") in images][:4]
    got = _try_llm(settings, None, images=sample, regions=[], prompt="", analysis=None,
                   task="tune", previous_graph=graph, feedback=instruction, batch_summary=_batch_summary(runs))
    if got is not None:
        new_graph, rationale = got
        provider, changes = settings.provider, []
    else:
        new_graph, changes = edit_rules(graph, instruction)
        if not changes:
            return {"graph": graph, "rationale": "看不懂這個指令；離線模式支援「太敏感／漏抓／改成 N 個／±x」與「把 <節點> 的 <參數> 改成 <值>」。",
                    "provider": "rules", "changes": [], "before": _tally([r.get("status", "") for r in runs]), "after": None, "items": [], "applied": False}
        new_graph = validate_graph(new_graph)
        provider, rationale = "rules", "已調整：" + "、".join(changes)
    items = []
    for r in runs:
        ref = r.get("image_ref")
        if ref not in images:
            items.append({"name": r.get("name", "?"), "before": r.get("status", ""), "after": "gone"})
            continue
        rep = trial_run(new_graph, images[ref])
        items.append({"name": r.get("name", "?"), "before": r.get("status", ""), "after": rep.status, "run_id": rep.id, "outputs": rep.outputs})
    return {"graph": new_graph, "rationale": rationale, "provider": provider, "changes": changes,
            "before": _tally([r.get("status", "") for r in runs]), "after": _tally([it["after"] for it in items]), "items": items, "applied": True}
