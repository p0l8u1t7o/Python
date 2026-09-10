"""LLM 生成：把工具目錄＋影像＋ROI＋提示詞交給供應商（providers.py），產出 graph JSON。

四種任務共用同一份 system（可快取）：generate（從零生成）、refine（依回饋修改）、
edit（編輯器內的指令：改參數／增刪節點）、tune（依批次測試結果調整）。
輸出一律經 validate_graph 把關；無效輸出帶錯誤重試一次。
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import cv2
import numpy as np

from apps.vision.agent import providers, skills
from apps.vision.agent.analysis import summarize_for_llm
from apps.vision.graph import validate_graph

log = logging.getLogger("vision.agent")

_MAX_SIDE = 1024


def tasklist(settings, message: str, kinds: list[dict], current: dict, history: list, lang: str) -> dict:
    """清單任務只提供核心欄位規格，不允許供應商產生節點或接線。"""
    system = (
        "Translate the request into inspection task proposals. Return JSON only: "
        '{"drafts":[{"op":"add|update|remove|answer|run","kind":"catalogue kind",'
        '"task_id":"existing id for update/remove","fields":{"field_key":"value"}}]}. '
        "Never output a graph, nodes, or edges. Use only the supplied field definitions. "
        "Preserve engineering specifications. Do not invent calibration or convert units. "
        "All inferred values require user confirmation. Field specifications:\n" + json.dumps(kinds, ensure_ascii=False)
    )
    text = json.dumps({"message": message, "current": current, "history": history[-6:], "lang": lang}, ensure_ascii=False)
    return parse_reply(providers.complete(settings, system, [], text, json_mode=True))


def system_prompt() -> str:
    """穩定的 system：平台規則＋設計原則＋精簡工具目錄（skills.py 組裝，可快取）。"""
    return "你是工業機器視覺流程設計專家，在 VisionSequence 平台上依規則設計可執行的檢測流程。\n\n" + skills.build_system(skills.epoch())


def encode_image(image: np.ndarray) -> str:
    h, w = image.shape[:2]
    scale = min(1.0, _MAX_SIDE / max(h, w))
    if scale < 1.0:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise RuntimeError("影像編碼失敗")
    return base64.standard_b64encode(buf.tobytes()).decode()


def parse_reply(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start > 0 or end < len(cleaned) - 1:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def _user_text(task: str, prompt: str, regions: list[dict[str, Any]], analysis: dict[str, Any] | None,
               previous_graph: dict[str, Any] | None, feedback: str, batch_summary: str, *, intent_kind: str = "",
               examples: str = "", user: Any = None) -> str:
    focus = skills.select_tools(f"{prompt}\n{feedback}", regions, intent_kind=intent_kind, graph=previous_graph)
    lines: list[str] = [skills.focus_text(focus, user), ""]
    if examples:
        lines += [examples, ""]
    if task == "generate":
        lines.append(f"檢測需求：{prompt or '（未填，請依 ROI 與影像判斷最合理的檢測）'}")
    elif task == "refine":
        lines.append(f"原始需求：{prompt}")
    elif task == "edit":
        lines.append("使用者在流程編輯器裡要你修改目前的流程。只做指令要求的修改，不要順手改別的節點或參數；"
                     "指令若是要某個節點的 ROI 跟著另一個節點找到的位置移動，就加一個 shape_align（a／b 接該節點的 cx／cy，或 matches 接 matches；"
                     "ref_x／ref_y 填目前找到的位置）並把它的 transform 接到那個節點的隱含輸入埠 `_transform`，不要去改它的 roi 參數。")
    elif task == "tune":
        lines.append("使用者跑了一批影像，要你依結果調整流程或參數。")
    for i, r in enumerate(regions, start=1):
        hint = f"（{r['hint']}）" if r.get("hint") else ""
        lines.append(f"ROI{i:02d}{hint}（影像 {int(r.get('image', 0) or 0) + 1}）: {json.dumps(r.get('region'), ensure_ascii=False)}")
    if analysis:
        lines.append("影像特徵摘要：\n" + summarize_for_llm(analysis))
    if previous_graph is not None:
        lines.append("目前的 graph：\n" + json.dumps(previous_graph, ensure_ascii=False))
    if batch_summary:
        lines.append("批次測試結果：\n" + batch_summary)
    if feedback:
        lines.append(f"使用者{'指令' if task in ('edit', 'tune') else '回饋'}：{feedback}")
    return "\n".join(lines)


_CLARIFY_INSTRUCTION = """你現在是「謹慎的助手」：先判斷目前的影像、ROI 與需求描述是否足以設計一個可靠的檢測流程。
- 資訊足夠（目標、位置、判定基準都明確或可合理預設）→ ready=true，不要提問。
- 資訊不足 → ready=false，提出最多 3 個最關鍵的問題；每題給 id（英數）、text（繁中一句話）、kind（choice／number／text／roi）、
  choice 要附 options [{value,label}]，可略過的題目 optional=true；kind=roi 表示需要使用者在影像上再圈選。
- 不要問已經回答過或提示詞已說明的事；不要問與檢測無關的事。
只輸出 JSON：{"ready": bool, "questions": [...], "summary": "一句話說明你目前的判讀（繁中）"}"""


def clarify(settings: providers.AgentSettings, images: list[np.ndarray], regions: list[dict[str, Any]], prompt: str,
            analysis: dict[str, Any] | None, answers: list[dict[str, Any]], *, intent_kind: str = "") -> dict[str, Any]:
    """LLM 版詢問：回 {ready, questions, summary, provider}；格式錯就 raise 讓呼叫端落回規則。"""
    encoded = [encode_image(im) for im in images[:6]]
    text = _user_text("generate", prompt, regions, analysis, None, "", "", intent_kind=intent_kind)
    if answers:
        text += "\n已回答的問題：" + json.dumps(answers, ensure_ascii=False)
    text += "\n\n" + _CLARIFY_INSTRUCTION
    reply = providers.complete(settings, system_prompt(), encoded, text, json_mode=True)
    payload = parse_reply(reply)
    questions = []
    for q in list(payload.get("questions") or [])[:3]:
        kind = str(q.get("kind") or "text")
        if kind not in ("choice", "number", "text", "roi"):
            kind = "text"
        item: dict[str, Any] = {"id": str(q.get("id") or f"q{len(questions) + 1}"), "text": str(q.get("text") or ""), "kind": kind, "optional": bool(q.get("optional"))}
        if kind == "choice":
            item["options"] = [{"value": str(o.get("value")), "label": str(o.get("label") or o.get("value"))} for o in (q.get("options") or []) if isinstance(o, dict)]
        if q.get("hint"):
            item["hint"] = str(q["hint"])
        if item["text"]:
            questions.append(item)
    ready = bool(payload.get("ready")) or not questions
    return {"ready": ready, "questions": [] if ready else questions, "summary": str(payload.get("summary") or ""), "provider": settings.provider}


def generate(settings: providers.AgentSettings, images: list[np.ndarray], regions: list[dict[str, Any]], prompt: str,
             analysis: dict[str, Any] | None, *, task: str = "generate", previous_graph: dict[str, Any] | None = None,
             feedback: str = "", batch_summary: str = "", intent_kind: str = "", examples: str = "", user: Any = None) -> tuple[dict[str, Any], str]:
    """呼叫供應商產 graph；validate 失敗會把錯誤帶回去重試一次。回 (graph, rationale)。"""
    encoded = [encode_image(im) for im in images[:6]]
    text = _user_text(task, prompt, regions, analysis, previous_graph, feedback, batch_summary, intent_kind=intent_kind, examples=examples, user=user)
    history: list[dict[str, Any]] = []
    last_error = ""
    for attempt in range(2):
        reply = providers.complete(settings, system_prompt(), encoded, text, history, json_mode=True)
        try:
            payload = parse_reply(reply)
            graph = validate_graph(payload["graph"])
            return graph, str(payload.get("rationale") or "")
        except Exception as exc:  # noqa: BLE001 - JSON 或 graph 驗證失敗都走重試
            last_error = str(exc)
            log.warning("agent LLM 第 %d 次輸出無效：%s", attempt + 1, last_error)
            history.append({"role": "assistant", "content": reply})
            history.append({"role": "user", "content": f"上面的輸出無法使用：{last_error}\n請修正後重新只輸出 JSON 物件。"})
    raise RuntimeError(f"LLM 產出的流程無法通過驗證：{last_error}")
