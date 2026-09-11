"""代理迴圈的動作層：LLM 可呼叫的工具（看狀態、讀技能、分析區域、規則草稿、改 graph、試跑、檢視節點、裁範本、自動調參、提問、完成）。

每個動作＝ActionSpec(name, description, input_schema, handler)；handler(state, args) -> dict（序列化後回給 LLM）。
改 graph 一律「複本套用 → validate_graph → 才提交」，並拒絕 dl_*／write_modbus／save_image、多個 image_source。
試跑走 service.trial_run(keep_images=False)：不佔影像快取；結果只回精簡文字（狀態、輸出、節點訊息），不塞影像。
"""

from __future__ import annotations

import base64
import copy
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import cv2
import numpy as np

from apps.vision.agent import analysis as analysis_mod
from apps.vision.agent import autotune, skills, synth
from apps.vision.agent.intents import Intent
from apps.vision.demo import GX, GY
from apps.vision.graph import validate_graph
from apps.vision.tools import base as tools

FORBIDDEN_PREFIX = ("dl_",)
FORBIDDEN_TYPES = frozenset({"write_modbus", "save_image"})
MAX_RESULT_CHARS = 12000
MAX_PICTURES = 12


@dataclass
class AgentState:
    task: str  # generate | edit | tune
    images: list[np.ndarray]
    regions: list[dict[str, Any]]
    prompt: str
    analysis: dict[str, Any] | None
    intent: Intent
    expected: list[str]
    #: 把某張影像的 ROI 裁成固定影像描述子（不是資產）；synth 與 crop_template 共用
    make_asset: Callable[[int, dict[str, Any], str], "dict[str, Any] | None"] | None = None
    graph: dict[str, Any] | None = None
    rationale: str = ""
    feedback: str = ""
    batch_summary: str = ""
    answers: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    trials: int = 0
    tool_calls: int = 0
    questions: list[dict[str, Any]] | None = None
    finished: bool = False
    last_trial: list[dict[str, Any]] = field(default_factory=list)
    #: 記憶：擁有者（個人技能補充）、相似成功案例的參數先驗與文字說明。
    owner: Any = None
    priors: dict[tuple[str, str], Any] = field(default_factory=dict)
    examples: str = ""
    pictures: int = 0
    groups: list[str] = field(default_factory=list)
    lessons: dict[str, Any] = field(default_factory=dict)
    flow_id: int | None = None
    engineering_notes: str = ""

    def step(self, kind: str, title: str, detail: str = "", **extra: Any) -> None:
        self.steps.append({"n": len(self.steps) + 1, "kind": kind, "title": title[:200], "detail": detail[:600], "at": time.time(), **extra})


@dataclass
class ActionSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[AgentState, dict[str, Any]], dict[str, Any]]
    terminal: bool = False

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


def check_graph(graph: Any) -> dict[str, Any]:
    """validate_graph ＋ 代理專屬限制。"""
    g = validate_graph(graph)
    for n in g["nodes"]:
        t = str(n.get("type", ""))
        if t.startswith(FORBIDDEN_PREFIX) or t in FORBIDDEN_TYPES:
            raise ValueError(f"代理不得使用 {t} 工具（深度學習模型與外部輸出由使用者自行加入）")
    if sum(1 for n in g["nodes"] if n.get("type") == "image_source") != 1:
        raise ValueError("流程必須恰有一個 image_source")
    return g


def _scalar_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in (outputs or {}).items():
        if isinstance(v, bool) or isinstance(v, (int, str)):
            out[k] = v
        elif isinstance(v, float):
            out[k] = round(v, 4)
    return out


def compact_report(rep: Any) -> dict[str, Any]:
    nodes = {}
    for nid, nr in rep.nodes.items():
        item: dict[str, Any] = {"status": nr.status}
        if nr.message:
            item["message"] = str(nr.message)[:160]
        if nr.branch:
            item["branch"] = nr.branch
        outs = _scalar_outputs(nr.outputs)
        if outs:
            item["outputs"] = outs
        nodes[nid] = item
    return {"status": rep.status, "outputs": _scalar_outputs(rep.outputs), "error": str(rep.error or "")[:300], "nodes": nodes}


def _coerce(value: Any) -> Any:
    if isinstance(value, str):
        s = value.strip()
        if s and (s[0] in "[{" or s in ("true", "false", "null") or _looks_number(s)):
            try:
                return json.loads(s)
            except ValueError:
                return value
    return value


def _looks_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _node_or_raise(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    for n in graph.get("nodes", []):
        if n.get("id") == node_id:
            return n
    raise ValueError(f"沒有節點 '{node_id}'")


def apply_ops(graph: dict[str, Any], ops: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """在複本上套用 patch_graph 的操作；回 (新 graph, 說明列表)。呼叫端負責 check_graph。"""
    g = json.loads(json.dumps(graph))
    done: list[str] = []
    for op in ops:
        kind = str(op.get("op", ""))
        if kind == "set_param" and not any(op.get(k) for k in ("key", "param", "name", "field")) and isinstance(op.get("params"), dict):
            kind = "set_params"  # 模型把 set_params 的寫法配上 set_param：照 params 處理
        if kind == "set_param":
            n = _node_or_raise(g, str(op.get("node", "")))
            key = str(op.get("key") or op.get("param") or op.get("name") or op.get("field") or "")
            if not key:
                raise ValueError("set_param 需要 key（參數名）")
            if "value" not in op:
                raise ValueError(f"set_param {n['id']}.{key} 需要 value")
            n.setdefault("params", {})[key] = _coerce(op.get("value"))
            done.append(f"{n['id']}.{key} = {n['params'][key]!r}")
        elif kind == "set_params":
            n = _node_or_raise(g, str(op.get("node", "")))
            params = op.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("set_params 的 params 必須是物件")
            for k, v in params.items():
                n.setdefault("params", {})[str(k)] = _coerce(v)
            done.append(f"{n['id']} 參數 {sorted(params)}")
        elif kind in ("enable", "disable"):
            n = _node_or_raise(g, str(op.get("node", "")))
            n["enabled"] = kind == "enable"
            done.append(f"{'啟用' if kind == 'enable' else '停用'} {n['id']}")
        elif kind == "remove_node":
            nid = str(op.get("node", ""))
            n = _node_or_raise(g, nid)
            if n.get("type") == "image_source":
                raise ValueError("不得刪除 image_source")
            g["nodes"] = [x for x in g["nodes"] if x["id"] != nid]
            g["edges"] = [e for e in g.get("edges", []) if e.get("source") != nid and e.get("target") != nid]
            done.append(f"刪除 {nid}")
        elif kind == "add_node":
            nid, ntype = str(op.get("node") or op.get("id") or ""), str(op.get("type", ""))
            if not nid or not ntype:
                raise ValueError("add_node 需要 node（id）與 type")
            if any(x.get("id") == nid for x in g["nodes"]):
                raise ValueError(f"節點 id '{nid}' 已存在")
            if ntype != "note" and not tools.has(ntype):
                raise ValueError(f"未知的工具型別 '{ntype}'")
            pos = op.get("position")
            if not isinstance(pos, dict):
                max_x = max((float((x.get("position") or {}).get("x", 0)) for x in g["nodes"]), default=0.0)
                pos = {"x": max_x + GX, "y": 40 + GY}
            params = op.get("params") or {}
            g["nodes"].append({"id": nid, "type": ntype, "label": str(op.get("label") or ""), "enabled": True,
                               "params": {str(k): _coerce(v) for k, v in params.items()} if isinstance(params, dict) else {}, "position": pos})
            done.append(f"新增 {nid}（{ntype}）")
        elif kind == "add_edge":
            src, tgt = str(op.get("source", "")), str(op.get("target", ""))
            _node_or_raise(g, src)
            _node_or_raise(g, tgt)
            sh, th = str(op.get("source_handle") or ""), str(op.get("target_handle") or "")
            g.setdefault("edges", []).append({"id": f"e-{src}-{sh}-{tgt}-{th}", "source": src, "target": tgt, "source_handle": sh, "target_handle": th})
            done.append(f"連線 {src}.{sh or 'image'} → {tgt}.{th or 'image'}")
        elif kind == "remove_edge":
            src, tgt = str(op.get("source", "")), str(op.get("target", ""))
            sh, th = op.get("source_handle"), op.get("target_handle")
            before = len(g.get("edges", []))
            g["edges"] = [e for e in g.get("edges", []) if not (e.get("source") == src and e.get("target") == tgt
                                                             and (sh is None or (e.get("source_handle") or "") == sh)
                                                             and (th is None or (e.get("target_handle") or "") == th))]
            done.append(f"移除 {before - len(g['edges'])} 條 {src} → {tgt} 的連線")
        elif kind == "set_label":
            n = _node_or_raise(g, str(op.get("node", "")))
            n["label"] = str(op.get("label") or "")
            done.append(f"{n['id']} 標題 → {n['label']}")
        else:
            raise ValueError(f"不支援的操作 '{kind}'")
    return g, done


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------
def _labeled(state: AgentState) -> list[autotune.Labeled]:
    return [autotune.Labeled(im, e, group=state.groups[i] if i < len(state.groups) else "tune") for i, (im, e) in enumerate(zip(state.images, state.expected)) if e]


def h_get_state(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    regions = [{"tag": f"ROI{i + 1:02d}", "image": int(r.get("image", 0) or 0) + 1, "shape": str((r.get("region") or {}).get("shape", "")),
                "hint": str(r.get("hint") or ""), "region": r.get("region")} for i, r in enumerate(state.regions)]
    return {
        "task": state.task, "prompt": state.prompt, "instruction": state.feedback, "image_count": len(state.images),
        "expected": [{"image": i + 1, "expected": e} for i, e in enumerate(state.expected) if e],
        "regions": regions, "intent_guess": state.intent.kind,
        "analysis": analysis_mod.summarize_for_llm(state.analysis) if state.analysis else "",
        "batch_summary": state.batch_summary, "answers": state.answers,
        "graph": state.graph, "last_trial": state.last_trial, "trials_used": state.trials, "tool_calls_used": state.tool_calls,
        "groups": state.groups or ["tune"] * len(state.images),
    }


def h_get_tool_skill(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    key = str(args.get("key", ""))
    try:
        return {"key": key, "markdown": skills.skill_text(key)}
    except KeyError:
        return {"error": f"沒有 '{key}' 這個工具；可用型別見 list_tools"}


def h_list_tools(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    return {"catalogue": skills.brief_catalogue()}


def h_analyze_region(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    idx = int(args.get("image", 1) or 1) - 1
    if not (0 <= idx < len(state.images)):
        return {"error": f"影像編號要在 1～{len(state.images)}"}
    region = args.get("region")
    info = analysis_mod.analyze_region(state.images[idx], region if isinstance(region, dict) and region.get("shape") else None)
    return {"image": idx + 1, "features": info}


def h_draft_from_rules(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    if state.analysis is None:
        state.analysis = analysis_mod.analyze(state.images, state.regions)
    cands = synth.candidates(state.intent, state.regions, state.analysis, make_asset=state.make_asset, priors=state.priors)
    primary = check_graph(cands[0]["graph"])
    if state.graph is None or bool(args.get("replace")):
        state.graph = primary
        state.rationale = cands[0]["rationale"]
    return {"graph": primary, "rationale": cands[0]["rationale"], "adopted": state.graph is primary,
            "alternatives": [{"key": c["key"], "label": c["label"]} for c in cands[1:]]}


def h_use_candidate(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    if state.analysis is None:
        state.analysis = analysis_mod.analyze(state.images, state.regions)
    key = str(args.get("key", ""))
    cands = synth.candidates(state.intent, state.regions, state.analysis, make_asset=state.make_asset)
    hit = next((c for c in cands if c["key"] == key), None)
    if hit is None:
        return {"error": f"沒有候選 '{key}'", "available": [c["key"] for c in cands]}
    state.graph = check_graph(hit["graph"])
    state.rationale = hit["rationale"]
    return {"graph": state.graph, "rationale": hit["rationale"]}


def h_replace_graph(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    graph = args.get("graph")
    if isinstance(graph, str):
        graph = json.loads(graph)
    state.graph = check_graph(graph)
    if args.get("rationale"):
        state.rationale = str(args["rationale"])
    return {"ok": True, "nodes": len(state.graph["nodes"]), "edges": len(state.graph["edges"])}


def h_patch_graph(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    if state.graph is None:
        return {"error": "還沒有流程：先 draft_from_rules 或 replace_graph"}
    ops = args.get("ops")
    if isinstance(ops, str):
        ops = json.loads(ops)
    if not isinstance(ops, list) or not ops:
        return {"error": "ops 必須是非空陣列"}
    new_graph, done = apply_ops(state.graph, ops)
    state.graph = check_graph(new_graph)
    return {"ok": True, "applied": done}


def _trial(state: AgentState, image: np.ndarray) -> Any:
    from apps.vision.agent import service

    return service.trial_run(state.graph, image, keep_images=False)


def h_run_trial(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    if state.graph is None:
        return {"error": "還沒有流程：先 draft_from_rules 或 replace_graph"}
    wanted = args.get("images")
    idxs = list(range(len(state.images)))
    if isinstance(wanted, list) and wanted:
        idxs = [int(i) - 1 for i in wanted if 0 < int(i) <= len(state.images)]
    state.trials += 1
    results = []
    for i in idxs:
        rep = _trial(state, state.images[i])
        row = {"image": i + 1, "expected": state.expected[i] if i < len(state.expected) else "", "group": state.groups[i] if i < len(state.groups) else "tune", **compact_report(rep)}
        results.append(row)
    labeled = [(r["status"], r["expected"]) for r in results if r["expected"]]
    summary = {"ok": sum(r["status"] == "ok" for r in results), "ng": sum(r["status"] == "ng" for r in results),
               "failed": sum(r["status"] not in ("ok", "ng") for r in results),
               "matches": sum(s == e for s, e in labeled), "labeled": len(labeled),
               "error_nodes": sorted({nid for r in results for nid, n in r["nodes"].items() if n["status"] == "error"})}
    state.last_trial = [{"image": r["image"], "status": r["status"], "expected": r["expected"], "outputs": r["outputs"]} for r in results]
    accepted = autotune.acceptance_rows(results)
    tune = [r for r in results if r["group"] == "tune" and r["expected"]]
    return {"results": results, "summary": summary, "tuning": {"matches": sum(r["status"] == r["expected"] for r in tune), "labeled": len(tune)},
            "acceptance": accepted, "acceptance_note": autotune.acceptance_text(accepted)}


def h_inspect_node(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    from apps.vision.agent import service
    from apps.vision.images import store

    if state.pictures >= MAX_PICTURES:
        return {"error": "picture budget exhausted"}
    if state.graph is None:
        return {"error": "還沒有流程"}
    node = str(args.get("node", ""))
    _node_or_raise(state.graph, node)
    idx = int(args.get("image", 1) or 1) - 1
    if not (0 <= idx < len(state.images)):
        return {"error": f"影像編號要在 1～{len(state.images)}"}
    state.trials += 1
    rep = service.trial_run(state.graph, state.images[idx], keep_images=True)
    try:
        nr = rep.nodes.get(node)
        if nr is None:
            return {"error": f"Node {node} did not run", "run_status": rep.status}
        port = args.get("image_port")
        if port:
            ref = (nr.outputs.get(port) or {}).get("ref") if isinstance(nr.outputs.get(port), dict) else None
        else:
            ref = next((v["ref"] for k, v in nr.outputs.items() if k != "_image" and isinstance(v, dict) and v.get("ref")), None)
            ref = ref or nr.detail.get("_input_ref") or (nr.outputs.get("_image") or {}).get("ref")
        image = store.get(ref) if ref else None
        result = {"node": node, "image": idx + 1, "status": nr.status, "message": str(nr.message)[:300], "branch": nr.branch,
                  "outputs": _scalar_outputs(nr.outputs), "overlay_count": len(nr.overlays or []), "detail": nr.detail, "logs": nr.logs[-10:]}
        if image is None:
            return {**result, "error": "No image is available for this node or port"}
        result.update(evidence_picture(image, nr.overlays or [], args.get("crop"), args.get("max_side", 512), nr.status))
        state.pictures += 1
        return result
    finally:
        store.drop_run(rep.id)


def evidence_picture(image, overlays, region=None, max_side=512, status="ok") -> dict[str, Any]:
    """只在顯示複本畫標記；座標依裁切偏移與最終縮圖尺寸換算。"""
    from apps.vision.images import encode_image
    from apps.vision.tools import roi
    from apps.vision.tools.builtin.output import draw_overlay

    limit = max(1, min(1024, int(max_side)))
    canvas = image.copy()
    if canvas.dtype != np.uint8:
        canvas = cv2.normalize(canvas, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    elif canvas.shape[2] == 4:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_BGRA2BGR)
    colored = copy.deepcopy(overlays)
    for ov in colored:
        color = str(ov.get("color", "")).lower()
        ov["color"] = "#ef4444" if status == "ng" or color in ("red", "#ef4444", "#ff0000", "#f43f5e") else "#22c55e"
        draw_overlay(canvas, ov)
    cut = roi.crop(canvas, region)
    if not cut.image.size:
        raise ValueError("The crop does not intersect the image")
    canvas = cut.image.copy()
    if cut.mask is not None:
        canvas[cut.mask == 0] = 0
    h, w = canvas.shape[:2]
    while True:
        scale = min(1.0, limit / max(h, w))
        width, height = max(1, round(w * scale)), max(1, round(h * scale))
        thumb = cv2.resize(canvas, (width, height), interpolation=cv2.INTER_AREA)
        data = encode_image(thumb, quality=80)
        if len(data) <= 200 * 1024:
            break
        limit = max(1, int(limit * .8))
    sx, sy = width / w, height / h
    summary = []
    for ov in colored[:20]:
        out = copy.deepcopy(ov)
        for key in ("x", "x1", "x2", "cx"):
            if key in out:
                out[key] = (out[key] - cut.x0) * sx
        for key in ("y", "y1", "y2", "cy"):
            if key in out:
                out[key] = (out[key] - cut.y0) * sy
        for key in ("w", "r", "r_inner", "r_outer", "rx"):
            if key in out:
                out[key] *= sx
        for key in ("h", "ry"):
            if key in out:
                out[key] *= sy
        if out.get("points"):
            out["points"] = ((np.asarray(out["points"], dtype=float) - [cut.x0, cut.y0]) * [sx, sy]).tolist()
        if out.get("contours"):
            out["contours"] = [((np.asarray(c, dtype=float) - [cut.x0, cut.y0]) * [sx, sy]).tolist() for c in out["contours"]]
        summary.append(out)
    return {"picture": {"mime": "image/jpeg", "width": width, "height": height, "data_base64": base64.b64encode(data).decode("ascii")},
            "overlay_summary": summary}


def h_crop_template(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    """把 ROI 裁成固定影像，加一個 fixed_image 節點（role=reference）接到 target 的圖片輸入埠。

    圖片跟著流程走（匯出會一起帶），不再在資產庫留檔；沒給 target 就只回描述子。
    """
    if state.make_asset is None:
        return {"error": "此工作階段沒有影像可以裁"}
    idx = int(args.get("image", 1) or 1) - 1
    region = args.get("region")
    if isinstance(region, str):
        region = json.loads(region)
    if not (0 <= idx < len(state.images)) or not isinstance(region, dict) or not region.get("shape"):
        return {"error": "需要 image（1 起算）與 region（ROI dict）"}
    picture = state.make_asset(idx, region, str(args.get("name") or "AI 助手：範本"))
    if not picture:
        return {"error": "裁切結果為空，請檢查 region"}
    target = str(args.get("target") or "").strip()
    if not target:
        return {"picture": picture, "image": idx + 1,
                "hint": "把它放進 fixed_image 節點的 images 參數（mode=fixed、role=reference），再接到工具的圖片輸入埠；或重呼叫本動作並帶 target"}
    if state.graph is None:
        return {"error": "目前沒有流程可以接"}
    graph = json.loads(json.dumps(state.graph))
    if not any(n.get("id") == target for n in graph.get("nodes") or []):
        return {"error": f"沒有節點 {target}"}
    port = str(args.get("port") or "template_image")
    node_id = f"pic_{target}"
    graph["nodes"] = [n for n in graph["nodes"] if n.get("id") != node_id]
    graph["edges"] = [e for e in graph["edges"] if e.get("source") != node_id and not (e.get("target") == target and e.get("target_handle") == port)]
    graph["nodes"].append({"id": node_id, "type": "fixed_image", "label": str(args.get("name") or "範本圖"), "x": 0, "y": 320,
                           "params": {"images": [picture], "mode": "fixed", "index": 1, "role": "reference"}})
    graph["edges"].append({"source": node_id, "source_handle": "image", "target": target, "target_handle": port})
    state.graph = check_graph(graph)  # 失敗會拋，dispatch 會翻成 {"error"} 回給模型
    return {"picture_node": node_id, "target": target, "port": port, "image": idx + 1, "size": [picture["width"], picture["height"]]}


def h_auto_tune(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    if state.graph is None:
        return {"error": "還沒有流程"}
    samples = _labeled(state)
    labeled = [lb for lb in samples if lb.group == "tune"]
    if len(labeled) < 1:
        return {"error": "沒有影像標記（expected），無法自動調參；可先請使用者標記或用 run_trial 自行判斷"}
    state.trials += 1
    res = autotune.coordinate_search(state.graph, labeled, max_evals=int(args.get("max_evals") or 30), deadline_s=float(args.get("deadline_s") or 15.0),
                                     trial=lambda g, im: _trial_graph(g, im), priors=state.priors)
    if res["improved"]:
        state.graph = res["graph"]
    accepted = autotune.acceptance(state.graph, samples, _trial_graph)
    return {"improved": res["improved"], "before": res["before"], "after": res["after"], "changes": res["change_text"], "evals": res["evals"], "budget_hit": res["budget_hit"],
            "acceptance": accepted, "message": f"Tune group: {res['after']['match']}/{res['after']['total']} matched. " + autotune.acceptance_text(accepted)}


def _trial_graph(graph: dict[str, Any], image: np.ndarray) -> Any:
    from apps.vision.agent import service

    return service.trial_run(graph, image, keep_images=False)


def h_ask_user(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    qs = args.get("questions")
    if isinstance(qs, str):
        qs = json.loads(qs)
    questions: list[dict[str, Any]] = []
    for i, q in enumerate(qs if isinstance(qs, list) else []):
        if not isinstance(q, dict) or not q.get("text"):
            continue
        kind = str(q.get("kind") or "text")
        if kind not in ("choice", "number", "text", "roi"):
            kind = "text"
        item: dict[str, Any] = {"id": str(q.get("id") or f"q{i + 1}"), "text": str(q["text"]), "kind": kind, "optional": bool(q.get("optional"))}
        if kind == "choice":
            item["options"] = [{"value": str(o.get("value")), "label": str(o.get("label") or o.get("value"))} for o in (q.get("options") or []) if isinstance(o, dict)]
        if q.get("hint"):
            item["hint"] = str(q["hint"])
        questions.append(item)
    if not questions:
        return {"error": "questions 需要至少一題（含 text）"}
    state.questions = questions[:3]
    return {"ok": True, "waiting_for_user": True}


def h_finish(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    from apps.vision.agent import memory

    if state.graph is None:
        return {"error": "還沒有流程，不能完成：先 draft_from_rules 或 replace_graph"}
    if args.get("lessons") is not None:
        state.lessons = memory.clean_lessons(args["lessons"])
    state.rationale = str(args.get("rationale") or state.rationale)
    state.finished = True
    return {"ok": True}


_REGION_SCHEMA = {"type": "object", "description": "標準 ROI dict（rect: x,y,w,h；circle: cx,cy,r；annulus: cx,cy,r_inner,r_outer；rotated_rect: cx,cy,w,h,angle）",
                  "properties": {"shape": {"type": "string"}}, "required": ["shape"]}

def h_propose_note(state: AgentState, args: dict[str, Any]) -> dict[str, Any]:
    """代理只能提出草稿；權限每次重新核對，不接受狀態或確認者。"""
    from apps.accounts.security import Principal
    from apps.core.errors import ValidationError
    from apps.vision import notes

    values = dict(args)
    if set(values) - {"title", "body", "kind", "project", "part_number", "flow"}:
        raise ValidationError("Draft proposals only accept title, body, kind, project, part number and flow")
    if "flow" not in values and state.flow_id:
        values["flow"] = state.flow_id
    row = notes.create(Principal(kind="user", user=state.owner), values)
    return {"id": row.pk, "status": row.status, "title": row.title, "url": f"/notes?note={row.pk}"}


ACTIONS: list[ActionSpec] = [
    ActionSpec("propose_note", "Propose an engineering note draft for human review. This never confirms a note or changes inspection specifications.",
               _obj({"title": {"type": "string"}, "body": {"type": "string"}, "kind": {"type": "string", "enum": ["decision", "lesson", "constraint", "lighting", "calibration", "tolerance_rationale", "known_issue"]},
                     "project": {"type": "string"}, "part_number": {"type": "string"}, "flow": {"type": "integer"}}, ["title", "body"]), h_propose_note),
    ActionSpec("get_state", "取得目前狀態：需求、指令、ROI、影像特徵摘要、期望標記、目前流程與最近試跑結果。開始時先呼叫。", _obj({}), h_get_state),
    ActionSpec("list_tools", "列出所有可用工具型別（一行一個）。", _obj({}), h_list_tools),
    ActionSpec("get_tool_skill", "讀取某個工具的完整技能（參數表、埠、使用要領）。", _obj({"key": {"type": "string", "description": "工具型別，例如 blob"}}, ["key"]), h_get_tool_skill),
    ActionSpec("analyze_region", "分析某張影像某個區域的特徵（灰階統計、Otsu、暗亮粒子、圓形試探、主色）。", _obj({"image": {"type": "integer", "description": "影像編號，1 起算"}, "region": _REGION_SCHEMA}, ["image"]), h_analyze_region),
    ActionSpec("draft_from_rules", "用規則引擎依需求產生一份標準流程草稿（會成為目前流程，除非已有流程）。通常先呼叫它再微調。", _obj({"replace": {"type": "boolean", "description": "已有流程時是否覆蓋"}}), h_draft_from_rules),
    ActionSpec("use_candidate", "改用規則引擎的另一個候選方案（key 來自 draft_from_rules 的 alternatives）。", _obj({"key": {"type": "string"}}, ["key"]), h_use_candidate),
    ActionSpec("replace_graph", "用你自己設計的完整 graph 取代目前流程（會做驗證；不得含 dl_*／write_modbus／save_image）。", _obj({"graph": {"type": "object", "description": "{nodes:[...], edges:[...]}"}, "rationale": {"type": "string"}}, ["graph"]), h_replace_graph),
    ActionSpec("patch_graph", "對目前流程做局部修改：set_param／set_params／enable／disable／remove_node／add_node／add_edge／remove_edge／set_label。全部套用後驗證，失敗則整批不採用。",
               _obj({"ops": {"type": "array", "items": _obj({
                   "op": {"type": "string", "enum": ["set_param", "set_params", "enable", "disable", "remove_node", "add_node", "add_edge", "remove_edge", "set_label"]},
                   "node": {"type": "string", "description": "節點 id"}, "key": {"type": "string"}, "value": {"type": "string", "description": "新值；數字／布林／JSON 物件可直接以字串給，系統會轉型"},
                   "params": {"type": "object"}, "type": {"type": "string", "description": "add_node 的工具型別"}, "label": {"type": "string"},
                   "source": {"type": "string"}, "source_handle": {"type": "string"}, "target": {"type": "string"}, "target_handle": {"type": "string"},
               }, ["op"])}}, ["ops"]), h_patch_graph),
    ActionSpec("run_trial", "把目前流程在影像上試跑，回每張的狀態、具名輸出、各節點訊息與命中摘要。", _obj({"images": {"type": "array", "items": {"type": "integer"}, "description": "影像編號清單（1 起算）；省略＝全部"}}), h_run_trial),
    ActionSpec("inspect_node", "在一張影像上試跑並回節點輸出、標記縮圖與縮圖座標。", _obj({"node": {"type": "string"}, "image": {"type": "integer"}, "image_port": {"type": "string"}, "crop": _REGION_SCHEMA, "max_side": {"type": "integer"}}, ["node"]), h_inspect_node),
    ActionSpec("crop_template", "把某張影像的區域裁成範本圖，並加一個固定影像節點接到 target 節點的圖片輸入埠（template_match 的 template_image、defect_diff 的 template_image、shading_correct 的 flat_image）。圖片跟著流程走，不進資產庫。",
               _obj({"image": {"type": "integer"}, "region": _REGION_SCHEMA, "name": {"type": "string"},
                     "target": {"type": "string", "description": "要接的節點 id；省略＝只裁不接"},
                     "port": {"type": "string", "description": "圖片輸入埠，預設 template_image"}}, ["image", "region"]), h_crop_template),
    ActionSpec("auto_tune", "用影像標記做資料驅動自動調參（只動現場調機參數，嚴格變好才採納）。", _obj({"max_evals": {"type": "integer"}, "deadline_s": {"type": "number"}}), h_auto_tune),
    ActionSpec("ask_user", "資訊不足時向使用者提問（最多 3 題），迴圈會暫停等待回答。只在關鍵資訊缺失時使用。",
               _obj({"questions": {"type": "array", "items": _obj({"id": {"type": "string"}, "text": {"type": "string"}, "kind": {"type": "string", "enum": ["choice", "number", "text", "roi"]},
                                                                    "options": {"type": "array", "items": _obj({"value": {"type": "string"}, "label": {"type": "string"}})},
                                                                    "optional": {"type": "boolean"}, "hint": {"type": "string"}}, ["text"])}}, ["questions"]), h_ask_user, terminal=True),
    ActionSpec("finish", "完成：目前流程就是最終結果。說明調參與驗收結果，可附 lessons 記錄失敗原因與適用條件。", _obj({"rationale": {"type": "string"}, "lessons": {"type": "object"}}, ["rationale"]), h_finish, terminal=True),
]
ACTION_MAP: dict[str, ActionSpec] = {a.name: a for a in ACTIONS}


def specs_for(task: str) -> list[ActionSpec]:
    return list(ACTIONS)


def dispatch(state: AgentState, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """執行一個動作；例外翻成 {"error": ...} 回給模型（不中斷迴圈）。"""
    spec = ACTION_MAP.get(name)
    state.tool_calls += 1
    if spec is None:
        state.step("error", f"未知動作 {name}")
        return {"error": f"沒有 '{name}' 這個動作", "available": list(ACTION_MAP)}
    t0 = time.perf_counter()
    try:
        result = spec.handler(state, dict(args or {}))
    except Exception as exc:  # noqa: BLE001 - 錯誤回給模型自己修
        result = {"error": f"{exc.__class__.__name__}: {str(exc)[:400]}"}
    ms = round((time.perf_counter() - t0) * 1000)
    detail = _step_detail(name, args or {}, result)
    state.step("error" if "error" in result else "tool", name, detail, ms=ms)
    return result


def _step_detail(name: str, args: dict[str, Any], result: dict[str, Any]) -> str:
    if "error" in result:
        return str(result["error"])
    if name == "run_trial":
        s = result.get("summary") or {}
        return f"OK {s.get('ok', 0)}／NG {s.get('ng', 0)}／失敗 {s.get('failed', 0)}" + (f"，命中 {s.get('matches')}/{s.get('labeled')}" if s.get("labeled") else "")
    if name == "patch_graph":
        return "、".join(result.get("applied") or [])
    if name == "auto_tune":
        return ("改善：" + "、".join(result.get("changes") or [])) if result.get("improved") else "沒有更好的參數"
    if name in ("draft_from_rules", "use_candidate"):
        return str(result.get("rationale") or "")[:200]
    if name == "get_tool_skill":
        return str(args.get("key", ""))
    if name == "ask_user":
        return "等待使用者回答"
    if name == "finish":
        return "完成"
    return json.dumps({k: v for k, v in args.items() if k != "graph"}, ensure_ascii=False)[:200]


def serialize_result(result: dict[str, Any]) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "…（已截斷）"
    return text
