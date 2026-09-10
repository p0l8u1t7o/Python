"""代理迴圈：LLM 反覆呼叫動作（看狀態 → 起草 → 試跑 → 修 → 完成／提問），每回合檢查預算與取消。

供應商差異藏在 providers.complete_tools（Claude tools／OpenAI functions／Gemini functionDeclarations）；
對話歷史用中立格式（見 providers 模組說明）。本地模型不支援工具呼叫時由呼叫端（jobs）退回單次 JSON → 規則。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from apps.vision.agent import actions, llm, providers, skills
from apps.vision.agent.analysis import summarize_for_llm

log = logging.getLogger("vision.agent")

STATUSES = ("done", "needs_input", "budget", "cancelled", "error")
MAX_INITIAL_IMAGES = 4


@dataclass
class Budget:
    max_turns: int = 12
    max_trials: int = 8
    max_tool_calls: int = 30
    deadline_s: float = 240.0

    def to_dict(self) -> dict[str, Any]:
        return {"max_turns": self.max_turns, "max_trials": self.max_trials, "max_tool_calls": self.max_tool_calls, "deadline_s": self.deadline_s}


@dataclass
class LoopResult:
    status: str
    graph: dict[str, Any] | None = None
    rationale: str = ""
    turns: int = 0
    questions: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


def system_prompt() -> str:
    return "你是工業機器視覺流程設計專家，在 VisionSequence 平台上用提供的動作逐步設計並驗證檢測流程。\n\n" + skills.build_system_agentic(skills.epoch())


def initial_text(state: actions.AgentState) -> str:
    lines: list[str] = []
    if state.task == "generate":
        lines.append(f"檢測需求：{state.prompt or '（未填，請依 ROI 與影像判斷最合理的檢測）'}")
    elif state.task == "edit":
        lines.append("使用者在流程編輯器裡要你修改目前的流程。")
        lines.append(f"指令：{state.feedback}")
    elif state.task == "tune":
        lines.append("使用者跑了一批影像，要你依結果調整流程或參數。")
        lines.append(f"指令：{state.feedback}")
    for i, r in enumerate(state.regions, start=1):
        hint = f"（{r['hint']}）" if r.get("hint") else ""
        lines.append(f"ROI{i:02d}{hint}（影像 {int(r.get('image', 0) or 0) + 1}）: {json.dumps(r.get('region'), ensure_ascii=False)}")
    marks = [f"影像 {i + 1} 應判 {e.upper()}" for i, e in enumerate(state.expected) if e]
    if marks:
        lines.append("影像期望判定：" + "、".join(marks))
    lines.append("樣本分組（按影像順序）：" + json.dumps(state.groups or ["tune"] * len(state.images)))
    if state.answers:
        lines.append("使用者已回答：" + json.dumps(state.answers, ensure_ascii=False))
    if state.analysis:
        lines.append("影像特徵摘要：\n" + summarize_for_llm(state.analysis))
    if state.graph is not None:
        lines.append("目前的 graph：\n" + json.dumps(state.graph, ensure_ascii=False))
    if state.batch_summary:
        lines.append("批次測試結果：\n" + state.batch_summary)
    focus = skills.select_tools(f"{state.prompt}\n{state.feedback}", state.regions, intent_kind=state.intent.kind, graph=state.graph, limit=12)
    lines.append(skills.focus_text(focus, state.owner))
    if state.examples:
        lines.append(state.examples)
    lines.append("請先呼叫 get_state 確認狀態，再依「代理工作方式」進行；完成時呼叫 finish。")
    return "\n".join(lines)


def initial_history(state: actions.AgentState) -> list[dict[str, Any]]:
    count = min(MAX_INITIAL_IMAGES, actions.MAX_PICTURES - state.pictures)
    parts: list[dict[str, Any]] = [{"type": "image", "data": llm.encode_image(im)} for im in state.images[:count]]
    state.pictures += len(parts)
    parts.append({"type": "text", "text": initial_text(state)})
    return [{"role": "user", "content": parts}]


def answer_turn(answers: list[dict[str, Any]]) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": "使用者回答：" + json.dumps(answers, ensure_ascii=False) + "\n請依回答繼續；完成時呼叫 finish。"}]}


def run_loop(settings: providers.AgentSettings, state: actions.AgentState, history: list[dict[str, Any]], budget: Budget | None = None, *,
             cancelled: Callable[[], bool] = lambda: False, turns_used: int = 0) -> LoopResult:
    budget = budget or Budget()
    if not history:
        history.extend(initial_history(state))
    system = system_prompt()
    specs = [spec.schema() for spec in actions.specs_for(state.task)]
    t0 = time.perf_counter()
    turns = turns_used
    nudged = False
    while True:
        if cancelled():
            return LoopResult("cancelled", state.graph, state.rationale, turns)
        if turns >= budget.max_turns or (time.perf_counter() - t0) > budget.deadline_s:
            state.step("budget", "預算用完", f"回合 {turns}／試跑 {state.trials}／動作 {state.tool_calls}")
            return LoopResult("budget", state.graph, state.rationale or "代理預算用完，以目前流程為結果", turns)
        turns += 1
        reply = providers.complete_tools(settings, system, history, specs, timeout=providers.generate_timeout())
        history.append({"role": "assistant", "content": reply.text, "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in reply.calls],
                        **({"raw": reply.raw} if reply.raw else {})})
        if reply.text.strip():
            state.step("assistant", reply.text.strip()[:200], reply.text.strip()[:600], turn=turns)
        if not reply.calls:
            if state.graph is not None:
                state.rationale = reply.text.strip() or state.rationale
                state.finished = True
                return LoopResult("done", state.graph, state.rationale, turns)
            if nudged:
                return LoopResult("error", None, "", turns, error="模型沒有使用動作產出流程")
            nudged = True
            history.append({"role": "user", "content": [{"type": "text", "text": "請使用動作繼續（例如 draft_from_rules 或 replace_graph），完成時呼叫 finish。"}]})
            continue
        for call in reply.calls:
            if cancelled():
                result = {"error": "使用者已取消"}
            elif state.tool_calls >= budget.max_tool_calls:
                result = {"error": "動作次數預算已用完，請立即呼叫 finish"}
            elif state.trials >= budget.max_trials and call.name in ("run_trial", "inspect_node", "auto_tune"):
                result = {"error": "試跑預算已用完，請依既有結果決定並呼叫 finish"}
            else:
                result = actions.dispatch(state, call.name, call.args)
            picture = result.get("picture")
            has_image = isinstance(picture, dict) and "data_base64" in picture
            text_result = {k: v for k, v in result.items() if k != "picture"} if has_image else result
            history.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": actions.serialize_result(text_result),
                            **({"picture": picture} if has_image else {})})
            if state.questions:
                state.step("question", "向使用者提問", "；".join(q["text"] for q in state.questions))
                return LoopResult("needs_input", state.graph, state.rationale, turns, questions=list(state.questions))
            if state.finished:
                state.step("done", "完成", state.rationale[:300])
                return LoopResult("done", state.graph, state.rationale, turns)
        if cancelled():
            return LoopResult("cancelled", state.graph, state.rationale, turns)
