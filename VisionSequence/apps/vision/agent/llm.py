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


def system_prompt() -> str:
    """穩定的 system：平台規則＋設計原則＋精簡工具目錄（skills.py 組裝，可快取）。"""
    return "你是工業機器視覺流程設計專家，在 VisionSequence 平台上依規則設計可執行的檢測流程。\n\n" + skills.build_system()


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
               previous_graph: dict[str, Any] | None, feedback: str, batch_summary: str, *, intent_kind: str = "") -> str:
    focus = skills.select_tools(f"{prompt}\n{feedback}", regions, intent_kind=intent_kind, graph=previous_graph)
    lines: list[str] = [skills.focus_text(focus), ""]
    if task == "generate":
        lines.append(f"檢測需求：{prompt or '（未填，請依 ROI 與影像判斷最合理的檢測）'}")
    elif task == "refine":
        lines.append(f"原始需求：{prompt}")
    elif task == "edit":
        lines.append("使用者在流程編輯器裡要你修改目前的流程。")
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


def generate(settings: providers.AgentSettings, images: list[np.ndarray], regions: list[dict[str, Any]], prompt: str,
             analysis: dict[str, Any] | None, *, task: str = "generate", previous_graph: dict[str, Any] | None = None,
             feedback: str = "", batch_summary: str = "", intent_kind: str = "") -> tuple[dict[str, Any], str]:
    """呼叫供應商產 graph；validate 失敗會把錯誤帶回去重試一次。回 (graph, rationale)。"""
    encoded = [encode_image(im) for im in images[:6]]
    text = _user_text(task, prompt, regions, analysis, previous_graph, feedback, batch_summary, intent_kind=intent_kind)
    history: list[dict[str, Any]] = []
    last_error = ""
    for attempt in range(2):
        reply = providers.complete(settings, system_prompt(), encoded, text, history)
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
