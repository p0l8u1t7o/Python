"""AI 助手背景工作：代理迴圈在背景執行緒跑（LLM 來回可能數分鐘），前端輪詢步驟時間軸、可取消、可回答提問後續跑。

照 dl/jobs.py 的範式：執行緒自己用 DB 連線、結束 close_old_connections()；一個行程同時最多 MAX_RUNNING 個工作，
完成的工作保留一段時間供前端讀取結果。沒有 LLM（離線）時工作仍可建立——在執行緒內直接跑單次的 service 路徑，狀態立即完成。
本地模型不支援工具呼叫（HTTP 400／缺 tool_calls 欄位）時，退回單次 JSON 生成，再退回規則引擎。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from apps.core.errors import Conflict, NotFound, ValidationError
from apps.vision.agent import actions, loop, memory, providers

log = logging.getLogger("vision.agent")

MAX_RUNNING = 3
KEEP_FINISHED = 20
TASKS = ("generate", "edit", "tune")


@dataclass
class AgentJob:
    id: str
    task: str
    settings: providers.AgentSettings
    state: actions.AgentState
    budget: loop.Budget
    history: list[dict[str, Any]] = field(default_factory=list)
    status: str = "running"  # running | done | needs_input | budget | cancelled | error
    result: dict[str, Any] | None = None
    questions: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    turns: int = 0
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    cancel_flag: bool = False
    #: tune 專用：批次列與影像
    runs: list[dict[str, Any]] = field(default_factory=list)
    run_images: dict[str, np.ndarray] = field(default_factory=dict)
    fallback_reason: str = ""

    def to_dict(self, step_from: int = 0) -> dict[str, Any]:
        steps = self.state.steps
        return {
            "id": self.id, "task": self.task, "status": self.status, "provider": self.settings.provider, "model": providers.model_of(self.settings),
            "mode": self.settings.mode, "turns": self.turns, "trials": self.state.trials, "tool_calls": self.state.tool_calls,
            "budget": self.budget.to_dict(), "steps": steps[max(0, step_from):], "step_next": len(steps),
            "questions": self.questions, "result": self.result, "error": self.error, "fallback_reason": self.fallback_reason,
            "created_at": self.created_at, "finished_at": self.finished_at, "duration_s": round((self.finished_at or time.time()) - self.created_at, 1),
        }


_lock = threading.Lock()
_jobs: dict[str, AgentJob] = {}


def _prune_locked() -> None:
    finished = sorted((j for j in _jobs.values() if j.status != "running"), key=lambda j: j.finished_at)
    for j in finished[:-KEEP_FINISHED] if len(finished) > KEEP_FINISHED else []:
        _jobs.pop(j.id, None)


def list_jobs() -> list[dict[str, Any]]:
    with _lock:
        rows = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [{k: v for k, v in j.to_dict().items() if k not in ("steps", "result")} for j in rows]


def get(job_id: str, step_from: int = 0) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise NotFound(f"沒有工作 {job_id}", code="job_not_found")
    return job.to_dict(step_from)


def cancel(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise NotFound(f"沒有工作 {job_id}", code="job_not_found")
        if job.status in ("running", "needs_input"):
            job.cancel_flag = True
            if job.status == "needs_input":
                job.status, job.finished_at = "cancelled", time.time()
            return True
        return False


def start(task: str, settings: providers.AgentSettings, state: actions.AgentState, budget: loop.Budget | None = None, *,
          runs: list[dict[str, Any]] | None = None, run_images: dict[str, np.ndarray] | None = None) -> dict[str, Any]:
    if task not in TASKS:
        raise ValidationError(f"未知的工作類型 '{task}'", code="bad_task")
    job = AgentJob(id=uuid.uuid4().hex[:12], task=task, settings=settings, state=state, budget=budget or loop.Budget(),
                   runs=list(runs or []), run_images=dict(run_images or {}))
    with _lock:
        _prune_locked()
        if sum(1 for j in _jobs.values() if j.status == "running") >= MAX_RUNNING:
            raise Conflict(f"同時最多 {MAX_RUNNING} 個 AI 助手工作", code="agent_busy")
        _jobs[job.id] = job
    _spawn(job)
    return job.to_dict()


def answer(job_id: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise NotFound(f"沒有工作 {job_id}", code="job_not_found")
        if job.status != "needs_input":
            raise Conflict("此工作沒有在等待回答", code="not_waiting")
        job.status = "running"
        job.questions = []
        job.state.questions = None
        job.state.answers = list(job.state.answers) + list(answers)
        job.history.append(loop.answer_turn(answers))
        job.state.step("answer", "使用者回答", "；".join(f"{a.get('id')}={a.get('answer')}" for a in answers))
    _spawn(job)
    return job.to_dict()


def _spawn(job: AgentJob) -> None:
    threading.Thread(target=_run, args=(job,), name=f"agent-job-{job.id}", daemon=True).start()


def _run(job: AgentJob) -> None:
    from django.db import close_old_connections

    try:
        if not providers.available(job.settings):
            job.fallback_reason = "沒有可用的 LLM 供應商，改用規則引擎"
            job.state.step("info", "離線模式", job.fallback_reason)
            _run_single(job)
        else:
            _run_agentic(job)
    except Exception as exc:  # noqa: BLE001 - 工作失敗不影響平台
        log.exception("AI 助手工作失敗")
        job.status, job.error = "error", f"{exc.__class__.__name__}: {str(exc)[:300]}"
        job.finished_at = time.time()
    finally:
        close_old_connections()


def _run_agentic(job: AgentJob) -> None:
    try:
        res = loop.run_loop(job.settings, job.state, job.history, job.budget, cancelled=lambda: job.cancel_flag, turns_used=job.turns)
    except Exception as exc:  # noqa: BLE001 - 工具呼叫不支援／供應商失敗 → 退回單次路徑
        if job.state.graph is not None and job.turns > 0:
            job.state.step("error", "供應商失敗，以目前流程為結果", providers._explain(exc, providers.generate_timeout()))
            _finalize(job, "budget")
            return
        job.fallback_reason = f"代理模式失敗（{providers._explain(exc, providers.generate_timeout())}），改用單次生成"
        job.state.step("error", "代理模式失敗，改用單次生成", job.fallback_reason)
        _run_single(job)
        return
    job.turns = res.turns
    if res.status == "needs_input":
        job.questions = res.questions
        job.status = "needs_input"
        return
    if res.status == "error":
        job.status, job.error, job.finished_at = "error", res.error, time.time()
        return
    if res.status == "cancelled":
        job.status, job.finished_at = "cancelled", time.time()
        return
    _finalize(job, res.status)


def _run_single(job: AgentJob) -> None:
    """單次路徑（離線或代理失敗）：直接用 service 的既有函式。"""
    from apps.vision.agent import service

    st = job.state
    if job.task == "generate":
        job.result = service.generate(st.images, st.regions, st.prompt, job.settings, answers=st.answers, labels=st.expected, owner=st.owner)
    elif job.task == "edit":
        job.result = service.edit(st.graph or {"nodes": [], "edges": []}, st.feedback, st.images[0] if st.images else None, job.settings)
    else:
        job.result = service.tune(st.graph or {"nodes": [], "edges": []}, st.feedback, job.runs, job.run_images, job.settings)
    if job.fallback_reason:
        job.result.setdefault("warnings", []).insert(0, job.fallback_reason)
    job.status, job.finished_at = "done", time.time()
    job.state.step("done", "完成（單次）", str(job.result.get("rationale") or "")[:300])


def _finalize(job: AgentJob, status: str) -> None:
    """代理迴圈結束：把最終流程在影像上正式跑（保留 overlay），組成與單次路徑同形狀的結果。"""
    from apps.vision.agent import service

    st = job.state
    graph = st.graph
    if graph is None:
        job.status, job.error, job.finished_at = "error", "代理沒有產出流程", time.time()
        return
    warnings = [job.fallback_reason] if job.fallback_reason else []
    if status == "budget":
        warnings.append("代理預算用完，以目前流程為結果")
    if job.task == "generate":
        main = service._main_image(st.regions, st.intent, len(st.images))
        report, reports = service._run_all(graph, st.images, main)
        job.result = service._result(graph, st.rationale, job.settings.provider, st.intent.kind, report, reports, main_image=main,
                                     warnings=warnings, candidates=[], labels=st.expected, agentic=True, turns=job.turns)
        session = memory.remember(owner=st.owner, task="generate", prompt=st.prompt, intent_kind=st.intent.kind, images=st.images, regions=st.regions,
                                  answers=st.answers, labels=st.expected, analysis=st.analysis, graph=graph, rationale=st.rationale, candidates=[],
                                  statuses=[r.get("status", "") for r in reports], provider=job.settings.provider, mode="agentic", turns=job.turns)
        job.result["session_id"] = session.id if session else None
    elif job.task == "edit":
        report = service.trial_run(graph, st.images[0]).to_dict(include_node_outputs=True) if st.images else None
        job.result = {"graph": graph, "rationale": st.rationale, "provider": job.settings.provider, "changes": [s["detail"] for s in st.steps if s["kind"] == "tool" and s["title"] == "patch_graph"],
                      "report": report, "applied": True, "warnings": warnings, "agentic": True, "turns": job.turns}
    else:
        items = service._rerun_items(graph, job.runs, job.run_images)
        job.result = {"graph": graph, "rationale": st.rationale, "provider": job.settings.provider, "changes": [s["detail"] for s in st.steps if s["kind"] == "tool" and s["title"] == "patch_graph"],
                      "before": service._tally([r.get("status", "") for r in job.runs]), "after": service._tally([it["after"] for it in items]), "items": items,
                      "applied": True, "warnings": warnings, "agentic": True, "turns": job.turns}
    job.status, job.finished_at = status, time.time()
