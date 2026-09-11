"""AI 助手編排：分析 → 生成（LLM 或規則）→ 驗證 → 在使用者影像上試跑 → 迭代微調／編輯／批次調參。

生成結果永遠經 validate_graph 把關、並用引擎實跑（run 的節點影像進快取，前端直接顯示 overlay）。
LLM 失敗或未設定時自動落回規則引擎，功能完全離線可用。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

import numpy as np

from apps.vision import engine, fixed_images, graphdiff
from apps.vision.agent import analysis as analysis_mod
from apps.vision.agent import clarify as clarify_mod
from apps.vision.agent import actions, autotune, intents, llm, memory, providers, synth
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.images import store
from apps.vision.models import Asset
from apps.vision.tools import base as tools
from apps.vision.tools.roi import crop as roi_crop
from apps.vision.tools.roi import extent as roi_extent

log = logging.getLogger("vision.agent")

#: 助手試跑用的 flow_id（影像快取的桶）；不對應任何真實流程。
AGENT_FLOW_ID = 0

#: 生成時（影像帶 OK/NG 標記）自動調參的小預算。
GENERATE_AUTOTUNE_EVALS = 24
GENERATE_AUTOTUNE_DEADLINE_S = 10.0


def _asset_path(asset_id: str) -> str | None:
    row = Asset.objects.filter(pk=asset_id).only("path").first()
    return row.path if row else None


def trial_run(graph: dict[str, Any], image: np.ndarray, *, keep_images: bool = True) -> engine.RunReport:
    """把 graph 在一張影像上跑一遍（不落 DB、不佔流程執行緒池）。keep_images=False：跑完立刻把節點影像從快取丟掉（候選排名／自動調參用，不擠掉使用者要看的）。"""
    compiled = compile_graph(graph)
    report = engine.execute(
        compiled, flow_id=AGENT_FLOW_ID, flow_version=0, trigger="agent",
        grab=lambda sid: None, asset_path=_asset_path,
        preview=True, input_image=image, run_id=f"agent{uuid.uuid4().hex[:12]}",
    )
    if not keep_images:
        store.drop_run(report.id)
    return report


def _run_all(graph: dict[str, Any], images: list[np.ndarray], main: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reports = [trial_run(graph, im).to_dict(include_node_outputs=True) for im in images]
    return reports[main], reports


def _quiet_trial(graph: dict[str, Any], image: np.ndarray) -> engine.RunReport:
    return trial_run(graph, image, keep_images=False)


def run_graph(images: list[np.ndarray], graph: dict[str, Any], main: int = 0) -> dict[str, Any]:
    """把一份 graph（例如使用者切換的候選方案）在上傳影像上實跑。"""
    graph = validate_graph(graph)
    main = main if 0 <= main < len(images) else 0
    report, reports = _run_all(graph, images, main)
    return _result(graph, "", "", "", report, reports, main_image=main)


def expected_labels(regions: list[dict[str, Any]], labels: list[str] | None, count: int) -> list[str]:
    """每張影像的期望判定（"ok"／"ng"／""）：明確標記優先；否則 ROI 提示寫「好品」的影像＝OK、「壞品」＝NG。"""
    out = [""] * count
    for r in regions:
        idx = int(r.get("image", 0) or 0)
        hint = str(r.get("hint") or "").lower()
        if not (0 <= idx < count) or any(w in hint for w in intents._LOCATOR_WORDS):
            continue
        if any(w in hint for w in intents._GOOD_WORDS):
            out[idx] = "ok"
        elif any(w in hint for w in intents._BAD_WORDS):
            out[idx] = "ng"
    for i, lb in enumerate(labels or []):
        if isinstance(lb, dict):
            lb = lb.get("expected", lb.get("label", ""))
        if i < count and str(lb).lower() in ("ok", "ng"):
            out[i] = str(lb).lower()
    return out


def _score(statuses: list[str], errors: list[bool], expected: list[str]) -> int:
    """候選方案分數：標記命中 +10、有錯誤節點 −5、失敗（非 ok/ng）−3。"""
    score = 0
    for st, err, exp in zip(statuses, errors, expected):
        if exp in ("ok", "ng"):
            score += 10 if st == exp else 0
        score -= 5 if err else 0
        score -= 3 if st not in ("ok", "ng") else 0
    return score


def _rank_candidates(cands: list[dict[str, Any]], images: list[np.ndarray], expected: list[str], groups: list[str] | None = None) -> tuple[list[dict[str, Any]], int]:
    """每個候選 graph 在全部影像上靜默試跑打分；回 (帶 statuses/score 的候選列表, 勝者索引)。主要方案驗證失敗會照舊 raise。"""
    ranked: list[dict[str, Any]] = []
    for i, c in enumerate(cands):
        try:
            graph = validate_graph(c["graph"])
        except Exception:  # noqa: BLE001 - 變體無效就略過；主要方案要讓錯誤浮出來
            if i == 0:
                raise
            log.warning("候選方案 %s 無效，略過", c.get("key"))
            continue
        statuses, errors = [], []
        for index, im in enumerate(images):
            if groups and groups[index] == "accept":
                statuses.append("")
                errors.append(False)
                continue
            rep = _quiet_trial(graph, im)
            statuses.append(rep.status)
            errors.append(any(getattr(nr, "status", "") == "error" for nr in rep.nodes.values()))
        selected = [i for i in range(len(images)) if not groups or groups[i] == "tune"]
        ranked.append({**c, "graph": graph, "statuses": statuses, "score": _score([statuses[i] for i in selected], [errors[i] for i in selected], [expected[i] for i in selected])})
    win = max(range(len(ranked)), key=lambda k: (ranked[k]["score"], -k))
    return ranked, win


def _broken_nodes(reports: list[dict[str, Any]]) -> str:
    """試跑報告裡的錯誤節點摘要（節點：訊息），沒有回空字串。"""
    seen: dict[str, str] = {}
    for r in reports:
        for nid, nr in (r.get("nodes") or {}).items():
            if nr.get("status") == "error" and nid not in seen:
                seen[nid] = str(nr.get("message") or "")[:80]
    return "；".join(f"{k}：{v}" if v else k for k, v in list(seen.items())[:3])


def _labels_text(expected: list[str]) -> str:
    marks = [f"影像 {i + 1} 應判 {e.upper()}" for i, e in enumerate(expected) if e]
    return ("影像期望判定：" + "、".join(marks)) if marks else ""


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


def _make_picture_factory(images: list[np.ndarray]):
    """把 ROI 裁下來存成**固定影像**（跟著流程走），不再在資產庫留一堆「AI 助手：…範本」。

    回傳描述子（`Param(kind="images")` 的元素），合成器把它放進 fixed_image 節點接到工具的圖片輸入埠。
    """

    def make_picture(image_idx: int, region: dict[str, Any], name: str) -> dict[str, Any] | None:
        img = images[image_idx] if 0 <= image_idx < len(images) else images[0]
        piece = roi_crop(img, region, upright=True).image
        if piece.size == 0:
            return None
        try:
            return fixed_images.store(np.ascontiguousarray(piece), f"{name}.png")
        except Exception:  # noqa: BLE001 - 存不下去就當作沒有範本圖（合成器會給提示）
            log.warning("AI 助手的範本圖存檔失敗", exc_info=True)
            return None

    return make_picture


def _result(graph: dict[str, Any], rationale: str, provider: str, intent: str, report: dict[str, Any],
            reports: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"graph": graph, "rationale": rationale, "provider": provider, "intent": intent, "report": report, "reports": reports, **extra}


def recall(intent_kind: str, feats: dict[str, Any] | None) -> tuple[list[tuple[Any, float]], dict[tuple[str, str], Any], str]:
    """相似成功案例 → (列表, 參數先驗, 給 LLM 的文字)。"""
    similar = memory.find_similar(intent_kind, feats, include_failures=True)
    return similar, memory.priors_from_sessions(similar), memory.examples_text(similar)


def _try_llm(settings: providers.AgentSettings, use_llm: bool | None, **kw: Any) -> tuple[tuple[dict[str, Any], str] | None, str]:
    """回 ((graph, rationale) | None, 失敗原因)。沒設定 LLM 時原因為空字串；失敗原因會寫進回應讓使用者知道改用了規則引擎。"""
    want = providers.available(settings) if use_llm is None else (use_llm and providers.available(settings))
    if not want:
        return None, ""
    try:
        return llm.generate(settings, **kw), ""
    except Exception as exc:  # noqa: BLE001 - LLM 掛掉一律落回規則引擎
        log.exception("LLM（%s）生成失敗，落回規則引擎", settings.provider)
        return None, f"LLM（{settings.provider}）失敗，已改用規則引擎：{providers._explain(exc, providers.generate_timeout())}"


def effective_prompt(prompt: str, answers: list[dict[str, Any]] | None) -> str:
    """提示詞＋問答補充句（詢問機制的答案就這樣併進去，規則與 LLM 都讀得到）。"""
    extra = clarify_mod.answers_to_text(answers or [])
    return f"{prompt.strip()}\n{extra}".strip() if extra else prompt.strip()


def clarify(images: list[np.ndarray], regions: list[dict[str, Any]], prompt: str, answers: list[dict[str, Any]] | None = None,
            settings: providers.AgentSettings | None = None) -> dict[str, Any]:
    """生成前的確認：資訊足夠回 ready=True；否則回最多 3 個問題。LLM 可用時由它提問，失敗落回規則。"""
    settings = settings or providers.server_settings()
    feats = analysis_mod.analyze(images, regions)
    text = effective_prompt(prompt, answers)
    intent = intents.parse(text, regions, feats)
    if providers.available(settings):
        try:
            out = llm.clarify(settings, images, regions, text, feats, answers or [], intent_kind=intent.kind)
            out["intent"] = intent.kind
            return out
        except Exception:  # noqa: BLE001
            log.exception("LLM（%s）提問失敗，落回規則", settings.provider)
    return clarify_mod.clarify(intent, regions, feats, answers or [])


def generate(images: list[np.ndarray], regions: list[dict[str, Any]], prompt: str,
             settings: providers.AgentSettings | None = None, *, use_llm: bool | None = None,
             answers: list[dict[str, Any]] | None = None, labels: list[str] | None = None, owner: Any = None,
             remember: bool = True, groups: list[str] | None = None) -> dict[str, Any]:
    """上傳影像們＋ROI＋提示詞（＋每張影像的 OK/NG 標記）→ {graph, rationale, provider, intent, report, reports, candidates, labels, session_id, similar}。

    規則引擎會產 1～3 個候選方案（相似成功案例的參數先驗版排第一），全部在影像上靜默試跑後依標記命中打分，勝者才正式跑（保留 overlay）；
    有 2 張以上標記時再對勝者做小預算自動調參。結束後存成工作階段（記憶）。"""
    settings = settings or providers.server_settings()
    prompt = effective_prompt(prompt, answers)
    feats = analysis_mod.analyze(images, regions)
    intent = intents.parse(prompt, regions, feats)  # 規則引擎的意圖也拿來幫 LLM 挑相關工具技能
    expected = expected_labels(regions, labels, len(images))
    groups = autotune.label_groups(labels or [], len(images), groups)
    similar, priors, examples = recall(intent.kind, feats) if remember else ([], {}, "")  # remember=False：評測基準等不讀也不寫記憶
    similar_out = [{"id": s.id, "prompt": s.prompt[:80], "distance": d} for s, d in similar if memory.is_prior(s)]
    llm_prompt = f"{prompt}\n{_labels_text(expected)}".strip()
    got, llm_reason = _try_llm(settings, use_llm, images=images, regions=regions, prompt=llm_prompt, analysis=feats, intent_kind=intent.kind,
                               examples=examples, user=owner)
    if got is not None:
        graph, rationale = got
        main = _main_image(regions, intent, len(images))
        report, reports = _run_all(graph, images, main)
        broken = _broken_nodes(reports)
        if broken and all(r.get("status") not in ("ok", "ng") for r in reports):
            # LLM 的流程驗證過但實跑就炸（例如範本資產 id 亂填、埠接錯）：不把失敗結果丟給使用者，改用規則引擎並說明
            llm_reason = f"LLM（{settings.provider}）產出的流程試執行失敗（{broken}），已改用規則引擎"
            log.warning(llm_reason)
            got = None
    if got is not None:
        result = _result(graph, rationale, settings.provider, intent.kind, report, reports, main_image=main, candidates=[], labels=expected, similar=similar_out)
    else:
        cands = synth.candidates(intent, regions, feats, make_asset=_make_picture_factory(images), priors=priors)
        ranked, win = _rank_candidates(cands, images, expected, groups)
        graph, rationale = ranked[win]["graph"], ranked[win]["rationale"]
        extra: dict[str, Any] = {}
        labeled = [autotune.Labeled(im, e) for im, e, group in zip(images, expected, groups) if e and group == "tune"]
        if len(labeled) >= 2 and not all(s == e for s, e, group in zip(ranked[win]["statuses"], expected, groups) if e and group == "tune"):
            tuned = autotune.coordinate_search(graph, labeled, max_evals=GENERATE_AUTOTUNE_EVALS, deadline_s=GENERATE_AUTOTUNE_DEADLINE_S, trial=_quiet_trial, priors=priors)
            if tuned["improved"]:
                graph = tuned["graph"]
                rationale += "；自動調參：" + "、".join(tuned["change_text"])
                extra["autotune"] = {k: tuned[k] for k in ("before", "after", "changes", "change_text", "evals", "elapsed_ms", "budget_hit")}
        main = _main_image(regions, intent, len(images))
        report, reports = _run_all(graph, images, main)
        open_qs = clarify_mod.build_questions(intent, regions, feats, {str(a.get("id", "")) for a in (answers or [])})
        warnings = ([llm_reason] if llm_reason else []) + [f"未提供「{q['text']}」，已用預設值" for q in open_qs]
        candidates = [{"key": c["key"], "label": c["label"], "rationale": c["rationale"], "statuses": c["statuses"], "score": c["score"],
                       "graph": c["graph"], "chosen": i == win} for i, c in enumerate(ranked)]
        result = _result(graph, rationale, "rules", intent.kind, report, reports, main_image=main, warnings=warnings, candidates=candidates,
                         labels=expected, similar=similar_out, **extra)
    result["groups"] = groups
    result["avoided"] = [{"id": s.id, "lessons": s.lessons} for s, _ in similar if not memory.is_prior(s)]
    result["acceptance"] = autotune.acceptance_rows([{**r, "expected": expected[i], "group": groups[i]} for i, r in enumerate(result["reports"])])
    result["acceptance_note"] = autotune.acceptance_text(result["acceptance"])
    if remember:
        session = memory.remember(owner=owner, task="generate", prompt=prompt, intent_kind=intent.kind, images=images, regions=regions, answers=list(answers or []),
                                  labels=expected, analysis=feats, graph=result["graph"], rationale=result["rationale"], candidates=result.get("candidates") or [],
                                  statuses=[r.get("status", "") for r in result["reports"]], provider=result["provider"], mode=settings.mode, groups=groups)
        result["session_id"] = session.id if session else None
    return result


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
    got, llm_reason = _try_llm(settings, None, images=images, regions=regions, prompt=prompt, analysis=feats,
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
        if llm_reason:
            result.setdefault("warnings", []).insert(0, llm_reason)
        return result
    new_graph = validate_graph(new_graph)
    report, reports = _run_all(new_graph, images, main)
    return _result(new_graph, "已調整：" + "、".join(changed), "rules", "", report, reports, main_image=main,
                   warnings=[llm_reason] if llm_reason else [])


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


#: 「<B>（的 ROI）跟著 <A>（位移）」：B 是要跟著走的節點、A 是找位置的節點；一句話可能有好幾個子句，逐句試
_FOLLOW = re.compile(
    r"(?:讓|让|把|使)?\s*(?P<b>[^，,。；;：:]+?)\s*(?:的)?\s*(?:ROI|roi|區域|区域|範圍|范围|檢測區|检测区|量測區|量测区)?\s*(?:再|就|要|也|都)?\s*"
    r"(?:跟著|跟着|跟隨|跟随|follows?|track)\s*(?P<a>[^，,。；;：:]+?)\s*(?:的)?\s*(?:位移|移動|移动|位置|中心|圓心|圆心|走|平移|偏移|動|动)*\s*$",
)
#: 「幫我直接修改」這種沒有內容的指令：內容在對話前一句
_DO_IT = re.compile(r"^(?:請|请|麻煩|麻烦|那|那就|好)?\s*(?:(?:幫我|帮我|直接|就|開始|开始|來|来|現在|现在)\s*)*(?:修改|改|做|套用|執行|执行|處理|处理|動手|动手|apply|do it|go ahead|proceed|make the changes?)"
                    r"\s*(?:畫布|画布|流程|吧|一下|它|這個|这个|這些|这些|it|them|the flow|the canvas)?\s*[。！!.]*$", re.I)
_NAME_TAIL = re.compile(r"(?:圓心|圆心|中心|圓|圆|節點|节点|步驟|步骤|工具|的)+$")


def _roi_param(node: dict[str, Any]) -> dict[str, Any] | None:
    roi = (node.get("params") or {}).get("roi")
    return roi if isinstance(roi, dict) and roi.get("shape") else None


def _resolve_follow_target(graph: dict[str, Any], name: str) -> dict[str, Any] | None:
    """「外圓心」「內圓」這種說法對不到節點標題時，在畫得出 ROI 的節點裡依 ROI 大小挑：外／大＝最大、內／小＝最小。"""
    name = name.strip()
    found = _find_nodes(graph, name) or _find_nodes(graph, _NAME_TAIL.sub("", name))
    found = [n for n in found if n.get("type") != "note"]
    if found:
        return found[0]
    sized: list[tuple[float, dict[str, Any]]] = []
    for n in graph["nodes"]:
        roi = _roi_param(n)
        if roi is None:
            continue
        try:
            x0, y0, x1, y1 = roi_extent(roi)
        except Exception:  # noqa: BLE001 - 畫壞的區域不擋整條規則
            continue
        sized.append(((x1 - x0) * (y1 - y0), n))
    if len(sized) < 2:
        return None
    sized.sort(key=lambda item: item[0])
    if any(w in name for w in ("外", "大", "outer", "big", "large")):
        return sized[-1][1]
    if any(w in name for w in ("內", "内", "小", "inner", "small")):
        return sized[0][1]
    return None


def _follow_rule(out: dict[str, Any], text: str) -> list[str]:
    """「<B> 的 ROI 跟著 <A> 位移」→ shape_align（a／b 接 A 的 cx／cy，或 matches）→ B 的 `_transform` 隱含埠。"""
    for clause in re.split(r"[，,。；;]", text):
        m = _FOLLOW.search(clause.strip())
        if not m:
            continue
        a = _resolve_follow_target(out, m.group("a"))
        b = _resolve_follow_target(out, m.group("b"))
        if a is None or b is None or a["id"] == b["id"]:
            continue
        if not (tools.has(a["type"]) and tools.has(b["type"])):
            continue
        if not tools._has_roi_param(tools.get(b["type"])):
            continue
        outs = {p.key for p in tools.get(a["type"]).outputs}
        if "matches" in outs:
            feeds = [("matches", "matches")]
        elif {"cx", "cy"} <= outs:
            feeds = [("cx", "a"), ("cy", "b")]
        else:
            continue
        aid = f"align_{a['id']}"
        ref_x = ref_y = 0.0
        roi = _roi_param(a)
        if roi is not None:
            try:
                x0, y0, x1, y1 = roi_extent(roi)
                ref_x, ref_y = round((x0 + x1) / 2, 1), round((y0 + y1) / 2, 1)
            except Exception:  # noqa: BLE001
                pass
        pos_b = b.get("position") or {}
        align = next((n for n in out["nodes"] if n["id"] == aid), None)
        if align is None:
            align = {"id": aid, "type": "shape_align", "label": f"Align: {a.get('label') or a['id']}", "enabled": True,
                     "params": {"ref_x": ref_x, "ref_y": ref_y, "ref_angle": 0, "use_angle": False},
                     "position": {"x": float(pos_b.get("x", 0)) - 60, "y": float(pos_b.get("y", 0)) - 150}}
            out["nodes"].append(align)
            out["edges"] = [e for e in out["edges"] if e.get("target") != aid]
            for sh, th in feeds:
                out["edges"].append({"id": f"e-{a['id']}-{sh}-{aid}-{th}", "source": a["id"], "source_handle": sh, "target": aid, "target_handle": th})
        # B 原本接的位置修正（若有）換成這一條
        out["edges"] = [e for e in out["edges"] if not (e.get("target") == b["id"] and e.get("target_handle") == "_transform")]
        out["edges"].append({"id": f"e-{aid}-transform-{b['id']}-_transform", "source": aid, "source_handle": "transform", "target": b["id"], "target_handle": "_transform"})
        return [f"{b.get('label') or b['id']} 的 ROI 跟著 {a.get('label') or a['id']} 位移（{aid}.transform → {b['id']}._transform）"]
    return []


def teach_alignment(graph: dict[str, Any], report: dict[str, Any] | None, new_ids: set[str]) -> bool:
    """試執行過後，把這次新加的 shape_align 的參考位置改成這張影像實際找到的位置（教導＝目前姿態）。回有沒有改。"""
    if not report:
        return False
    nodes = report.get("nodes") or {}
    by_id = {n["id"]: n for n in graph["nodes"]}
    changed = False
    for n in graph["nodes"]:
        if n.get("type") != "shape_align" or n["id"] not in new_ids:
            continue
        src = next((e for e in graph["edges"] if e.get("target") == n["id"] and e.get("target_handle") in ("a", "matches")), None)
        if src is None or src["source"] not in by_id:
            continue
        outs = (nodes.get(src["source"]) or {}).get("outputs") or {}
        if src.get("target_handle") == "matches":
            first = next(iter(outs.get("matches") or []), None)
            cx, cy = (first or {}).get("x"), (first or {}).get("y")
        else:
            cx, cy = outs.get("cx"), outs.get("cy")
        if isinstance(cx, (int, float)) and isinstance(cy, (int, float)) and np.isfinite(cx) and np.isfinite(cy):
            n["params"]["ref_x"], n["params"]["ref_y"] = round(float(cx), 2), round(float(cy), 2)
            changed = True
    return changed


def edit_rules(graph: dict[str, Any], instruction: str) -> tuple[dict[str, Any], list[str]]:
    """離線指令解析：「把 <節點> 的 <參數> 改成 <值>」「停用／啟用 <節點>」「刪除 <節點>」「<B> 的 ROI 跟著 <A>」。"""
    out = json.loads(json.dumps(graph))
    changed: list[str] = []
    text = instruction.strip()
    changed += _follow_rule(out, text)
    if changed:
        return out, changed
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


def describe_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """LLM 改完的圖沒有 changes 清單，使用者看不出畫布哪裡變了：用 graphdiff 逐條列出（新增／刪除／換工具／參數／停用／連線）。"""
    d = graphdiff.diff(old, new)
    old_nodes = {n["id"]: n for n in old.get("nodes") or []}
    new_nodes = {n["id"]: n for n in new.get("nodes") or []}
    names = {nid: (n.get("label") or nid) for nid, n in {**old_nodes, **new_nodes}.items()}
    out = [f"新增 {names[nid]}（{new_nodes[nid].get('type')}）" for nid in d["added"]]
    out += [f"刪除 {names[nid]}" for nid in d["removed"]]
    out += [f"{names[e['node']]}：{e['before']} → {e['after']}" for e in d["retyped"]]
    out += [f"{names[e['node']]}：{e['param']} {json.dumps(e['before'], ensure_ascii=False)} → {json.dumps(e['after'], ensure_ascii=False)}" for e in d["params"]]
    for nid in sorted(set(old_nodes) & set(new_nodes)):
        before, after = old_nodes[nid].get("enabled", True), new_nodes[nid].get("enabled", True)
        if before != after:
            out.append(f"{'啟用' if after else '停用'} {names[nid]}")
    if d["edges_added"] or d["edges_removed"]:
        out.append(f"連線 +{d['edges_added']} / -{d['edges_removed']}")
    return out


def _history_texts(history: list[dict[str, Any]] | None, instruction: str) -> list[tuple[str, str]]:
    """對話紀錄壓成 (role, text)，去掉尾端與這次指令相同的那一則（前端有時會先推進去）。"""
    rows = [(str(h.get("role") or "user"), str(h.get("text") or "").strip()) for h in (history or []) if isinstance(h, dict)]
    rows = [(r, t) for r, t in rows if t]
    if rows and rows[-1][0] == "user" and rows[-1][1] == instruction.strip():
        rows.pop()
    return rows[-6:]


def _edit_feedback(instruction: str, history: list[tuple[str, str]]) -> str:
    """給 LLM 的指令：附上最近幾句對話，「請幫我直接修改」才知道要修什麼。"""
    if not history:
        return instruction
    lines = ["對話脈絡（由舊到新，助手的話只是它先前的說明，不一定已經做了）："]
    for role, text in history:
        who = "使用者" if role == "user" else "助手"
        lines.append(f"{who}：{text[:400]}")
    lines.append(f"最新指令：{instruction}")
    return "\n".join(lines)


def edit(graph: dict[str, Any], instruction: str, image: np.ndarray | None,
         settings: providers.AgentSettings | None = None, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """流程頁面的 AI 指令：LLM 可用時整份交給 LLM（附對話脈絡）；否則離線指令解析。有影像就順便試跑。
    「幫我直接修改」這種沒有內容的指令，規則引擎會回頭拿對話裡上一句真正的需求。"""
    settings = settings or providers.server_settings()
    turns = _history_texts(history, instruction)
    got, llm_reason = _try_llm(settings, None, images=[image] if image is not None else [], regions=[], prompt="", analysis=None,
                               task="edit", previous_graph=graph, feedback=_edit_feedback(instruction, turns))
    if got is not None:
        new_graph, rationale = got
        provider, changes = settings.provider, describe_changes(graph, new_graph)
        if not changes:
            return {"graph": graph, "rationale": rationale + "\n（沒有改動任何節點、參數或連線，所以沒有東西可套用。）",
                    "provider": provider, "changes": [], "report": None, "applied": False}
    else:
        new_graph, changes = edit_rules(graph, instruction)
        if not changes and _DO_IT.match(instruction.strip()):
            for role, text in reversed(turns):
                if role == "user":
                    new_graph, changes = edit_rules(graph, text)
                    if changes:
                        break
        if not changes:
            return {"graph": graph, "rationale": "看不懂這個指令。離線模式支援：「把 <節點> 的 <參數> 改成 <值>」、「停用／啟用 <節點>」、「刪除 <節點>」、「<節點> 的 ROI 跟著 <節點> 位移」、「太敏感／漏抓／改成 N 個／±x」；接上 LLM 供應商可用自然語言增刪節點。",
                    "provider": "rules", "changes": [], "report": None, "applied": False}
        new_graph = validate_graph(new_graph)
        provider, rationale = "rules", (llm_reason + "\n" if llm_reason else "") + "已調整：" + "、".join(changes)
    report = trial_run(new_graph, image).to_dict(include_node_outputs=True) if image is not None else None
    # 這次新加的定位補正：參考位置改成這張影像實際找到的位置（教導＝目前姿態），再跑一次讓報告反映最終的圖
    new_ids = {n["id"] for n in new_graph["nodes"]} - {n["id"] for n in graph["nodes"]}
    if report is not None and new_ids and teach_alignment(new_graph, report, new_ids):
        report = trial_run(new_graph, image).to_dict(include_node_outputs=True)
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


_AUTOTUNE_WORDS = ("自動調參", "自动调参", "自動調", "自动调", "自動優化", "自动优化", "autotune", "auto tune", "auto-tune")


def wants_autotune(instruction: str) -> bool:
    low = (instruction or "").lower()
    return any(w in low for w in _AUTOTUNE_WORDS)


def _rerun_items(graph: dict[str, Any], runs: list[dict[str, Any]], images: dict[str, np.ndarray], *, keep_images: bool = True,
                 detail: bool = False) -> list[dict[str, Any]]:
    """同一批影像用新 graph 重跑；detail=True 多回逐節點純量輸出（持久化批次要落成新執行時用）。"""
    from apps.vision.batch.store import compact_row

    items = []
    for r in runs:
        ref = r.get("image_ref")
        if ref not in images:
            items.append({"name": r.get("name", "?"), "before": r.get("status", ""), "after": "gone"})
            continue
        rep = trial_run(graph, images[ref], keep_images=keep_images)
        row = {"name": r.get("name", "?"), "before": r.get("status", ""), "after": rep.status, "run_id": rep.id, "outputs": rep.outputs, "expected": r.get("expected", ""),
               "group": autotune.group_of(r), "expect_outputs": r.get("expect_outputs") or {}}
        if detail and r.get("index") is not None:
            row = {**compact_row(int(r["index"]), rep), **row}
        items.append(row)
    return items


def autotune_runs(graph: dict[str, Any], runs: list[dict[str, Any]], images: dict[str, np.ndarray], *,
                  max_evals: int = 60, deadline_s: float = 25.0, detail: bool = False) -> dict[str, Any]:
    """批次測試的自動調參：每列的 expected（ok／ng）當標記，座標下降找更好的現場參數；回與 tune 相同形狀＋autotune 摘要。"""
    labeled = [autotune.Labeled(images[r["image_ref"]], str(r.get("expected", "")).lower(), r.get("expect_outputs") or {}, str(r.get("name", "")))
               for r in runs if autotune.group_of(r) == "tune" and r.get("image_ref") in images and str(r.get("expected", "")).lower() in ("ok", "ng")]
    before = _tally([r.get("status", "") for r in runs])
    if not labeled:
        return {"graph": graph, "rationale": "沒有可用的期望標記：請在結果表為至少一列填 OK／NG 期望（影像須仍在快取中）。",
                "provider": "autotune", "changes": [], "before": before, "after": None, "items": [], "applied": False,
                "acceptance": {"ok": 0, "ng": 0, "matches": 0, "labeled": 0}}
    graph = validate_graph(graph)
    res = autotune.coordinate_search(graph, labeled, max_evals=max_evals, deadline_s=deadline_s, trial=_quiet_trial)
    items = _rerun_items(res["graph"], runs, images, keep_images=not detail, detail=detail)
    b, a = res["before"], res["after"]
    accepted = autotune.acceptance_rows(items)
    rationale = ("自動調參：" + ("、".join(res["change_text"]) if res["improved"] else "在預算內找不到更好的參數，維持原參數")
                 + f"; Tune group: {b['match']}/{b['total']} → {a['match']}/{a['total']}, {res['evals']} evaluations, {res['elapsed_ms']} ms. " + autotune.acceptance_text(accepted)
                 + ("（預算用盡）" if res["budget_hit"] else ""))
    return {"graph": res["graph"], "rationale": rationale, "provider": "autotune", "changes": res["change_text"],
            "before": before, "after": _tally([it["after"] for it in items]), "items": items, "applied": True, "acceptance": accepted,
            "autotune": {k: res[k] for k in ("before", "after", "changes", "change_text", "evals", "elapsed_ms", "improved", "budget_hit")}}


def tune(graph: dict[str, Any], instruction: str, runs: list[dict[str, Any]], images: dict[str, np.ndarray],
         settings: providers.AgentSettings | None = None, *, extra_summary: str = "", detail: bool = False) -> dict[str, Any]:
    """跑多筆影像後依提示詞調整：指令要求自動調參（或離線且有期望標記）就走資料驅動搜尋；否則 LLM 帶批次摘要（extra_summary＝資料洞察）、
    規則走回饋映射。調完在同一批影像重跑回報前後對比；detail=True 多回逐節點資料（持久化批次落成新執行）。"""
    settings = settings or providers.server_settings()
    labeled_n = sum(1 for r in runs if str(r.get("expected", "")).lower() in ("ok", "ng") and r.get("image_ref") in images)
    if wants_autotune(instruction):
        return autotune_runs(graph, runs, images, detail=detail)
    sample = [images[r["image_ref"]] for r in runs if r.get("image_ref") in images][:4]
    summary = (extra_summary.strip() + "\n" if extra_summary.strip() else "") + _batch_summary(runs)
    got, llm_reason = _try_llm(settings, None, images=sample, regions=[], prompt="", analysis=None,
                               task="tune", previous_graph=graph, feedback=instruction, batch_summary=summary)
    if got is not None:
        new_graph, rationale = got
        provider, changes = settings.provider, []
    else:
        new_graph, changes = edit_rules(graph, instruction)
        if not changes and labeled_n >= 2:  # 指令對不上規則但有期望標記：退而用資料驅動自動調參
            return autotune_runs(graph, runs, images, detail=detail)
        if not changes:
            return {"graph": graph, "rationale": "看不懂這個指令；離線模式支援「太敏感／漏抓／改成 N 個／±x」與「把 <節點> 的 <參數> 改成 <值>」。",
                    "provider": "rules", "changes": [], "before": _tally([r.get("status", "") for r in runs]), "after": None, "items": [], "applied": False}
        new_graph = validate_graph(new_graph)
        provider, rationale = "rules", (llm_reason + "\n" if llm_reason else "") + "已調整：" + "、".join(changes)
    items = _rerun_items(new_graph, runs, images, keep_images=not detail, detail=detail)
    return {"graph": new_graph, "rationale": rationale, "provider": provider, "changes": changes,
            "before": _tally([r.get("status", "") for r in runs]), "after": _tally([it["after"] for it in items]), "items": items, "applied": True}



# ---------------------------------------------------------------------------
# 代理模式：組工作階段狀態（給 jobs／loop）
# ---------------------------------------------------------------------------
def build_state(task: str, images: list[np.ndarray], regions: list[dict[str, Any]], prompt: str, *,
                answers: list[dict[str, Any]] | None = None, labels: list[str] | None = None,
                graph: dict[str, Any] | None = None, instruction: str = "", runs: list[dict[str, Any]] | None = None,
                owner: Any = None, extra_summary: str = "", groups: list[str] | None = None) -> actions.AgentState:
    """代理迴圈的初始狀態：分析、意圖、期望標記、make_asset、相似成功案例的先驗；edit／tune 帶既有 graph 與指令。"""
    text = effective_prompt(prompt, answers)
    feats = analysis_mod.analyze(images, regions) if images else None
    intent = intents.parse(text, regions, feats) if feats else intents.Intent()
    _, priors, examples = recall(intent.kind, feats) if (feats and task == "generate") else ([], {}, "")
    state = actions.AgentState(
        task=task, images=images, regions=regions, prompt=text, analysis=feats, intent=intent,
        expected=expected_labels(regions, labels, len(images)), make_asset=_make_picture_factory(images) if images else None,
        graph=validate_graph(graph) if graph else None, feedback=instruction, answers=list(answers or []),
        batch_summary=((extra_summary.strip() + "\n") if extra_summary.strip() else "") + (_batch_summary(runs) if runs else ""),
        owner=owner, priors=priors, examples=examples, groups=autotune.label_groups(labels or [], len(images), groups),
    )
    from apps.accounts.security import Principal

    # 內部離線入口沿用首次啟動身分；HTTP 入口必須以已驗證的呼叫者覆寫。
    state.principal = Principal("user", user=owner) if owner is not None else Principal("bootstrap")
    return state


def has_llm(settings: providers.AgentSettings | None) -> bool:
    """有沒有可用的 LLM 供應商（離線規則引擎＝沒有）。"""
    return bool(settings and settings.provider and settings.provider != "offline")


def agentic(settings: providers.AgentSettings) -> bool:
    return settings.mode == "agentic" and providers.available(settings)
