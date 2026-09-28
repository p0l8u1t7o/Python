"""工程代理只在網路或服務錯誤時重試，且受總期限約束；工程失敗不盲目重跑。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cellforge.agents import engineering
from cellforge.agents.engineering import (
    ClaudeCapabilities,
    ClaudeOutcome,
    EngineeringAgent,
    EngineeringAgentError,
)
from cellforge.version_store import BUILD_JOB_ENV, BUILD_ORIGIN_ENV

OK_JSON = json.dumps(
    {"status": "ok", "version": 3, "summary": "完成", "checks": {"red": 0, "yellow": 0}}
)


@pytest.fixture
def scripted(monkeypatch):
    calls: list[dict] = []
    outcomes: list[ClaudeOutcome] = []

    monkeypatch.setattr(
        engineering,
        "detect_claude",
        lambda *_args, **_kwargs: ClaudeCapabilities("claude", "9.9.9", True, True, True),
    )

    async def fake_run(arguments, project, environment, emit, timeout_s):
        calls.append(
            {
                "arguments": arguments,
                "job": environment.get(BUILD_JOB_ENV),
                "origin": environment.get(BUILD_ORIGIN_ENV),
                "timeout_s": timeout_s,
            }
        )
        return outcomes.pop(0)

    monkeypatch.setattr(engineering, "_run_claude", fake_run)
    return calls, outcomes


def _run(agent: EngineeringAgent, project: Path) -> dict:
    return asyncio.run(agent.run("first_build", project, lambda *_: None, job_id="job-123"))


def test_network_failures_are_retried_until_success(tmp_path: Path, scripted):
    calls, outcomes = scripted
    outcomes.extend(
        [
            ClaudeOutcome(1, "", "API Error: Connection error."),
            ClaudeOutcome(1, "", "connect ECONNREFUSED 160.79.104.10:443"),
            ClaudeOutcome(0, OK_JSON, ""),
        ]
    )
    result = _run(EngineeringAgent(timeout_s=60, retry_delays_s=(0.0,)), tmp_path)
    assert result["status"] == "ok" and result["attempts"] == 3
    assert {call["job"] for call in calls} == {"job-123"}
    assert {call["origin"] for call in calls} == {"agent:first_build"}
    budgets = [call["timeout_s"] for call in calls]
    assert all(0 < budget <= 60 for budget in budgets)
    assert budgets == sorted(budgets, reverse=True)


def test_engineering_failure_is_reported_without_retry(tmp_path: Path, scripted):
    calls, outcomes = scripted
    outcomes.append(
        ClaudeOutcome(0, json.dumps({"status": "failed", "summary": "S3 手臂碰撞無法排除"}), "")
    )
    with pytest.raises(EngineeringAgentError, match="S3 手臂碰撞無法排除"):
        _run(EngineeringAgent(timeout_s=60, retry_delays_s=(0.0,)), tmp_path)
    assert len(calls) == 1


def test_non_network_crash_is_not_retried(tmp_path: Path, scripted):
    calls, outcomes = scripted
    outcomes.append(ClaudeOutcome(1, "", "TypeError: cannot read properties of undefined"))
    with pytest.raises(EngineeringAgentError, match="退出碼 1"):
        _run(EngineeringAgent(timeout_s=60, retry_delays_s=(0.0,)), tmp_path)
    assert len(calls) == 1


def test_retries_stop_at_max_attempts(tmp_path: Path, scripted):
    calls, outcomes = scripted
    outcomes.extend(ClaudeOutcome(1, "", "fetch failed: ECONNRESET") for _ in range(5))
    with pytest.raises(EngineeringAgentError, match="共嘗試 3 次"):
        _run(EngineeringAgent(timeout_s=60, max_attempts=3, retry_delays_s=(0.0,)), tmp_path)
    assert len(calls) == 3


def test_total_deadline_bounds_retries(tmp_path: Path, scripted):
    calls, outcomes = scripted
    outcomes.extend(ClaudeOutcome(1, "", "API Error: Connection error.") for _ in range(5))
    with pytest.raises(EngineeringAgentError, match="總期限"):
        _run(EngineeringAgent(timeout_s=0.5, max_attempts=5, retry_delays_s=(5.0,)), tmp_path)
    assert len(calls) == 1


def test_timeout_is_final(tmp_path: Path, scripted):
    calls, outcomes = scripted
    outcomes.append(ClaudeOutcome(None, "", "", timed_out=True))
    with pytest.raises(EngineeringAgentError, match="總期限"):
        _run(EngineeringAgent(timeout_s=60, retry_delays_s=(0.0,)), tmp_path)
    assert len(calls) == 1


def test_agent_does_not_inherit_the_enclosing_claude_session(monkeypatch):
    for name, value in {
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "parent-session",
        "CLAUDE_CODE_CHILD_SESSION": "1",
        "CLAUDE_CODE_MESSAGING_TOKEN": "secret",
        "CLAUDE_EFFORT": "xhigh",
        "CLAUDE_CODE_GIT_BASH_PATH": "C:/Program Files/Git/bin/bash.exe",
        "ANTHROPIC_BASE_URL": "https://example.invalid",
    }.items():
        monkeypatch.setenv(name, value)
    environment = EngineeringAgent._environment(job_id="job-9", origin="agent:intake")
    for inherited in (
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "CLAUDE_EFFORT",
    ):
        assert inherited not in environment
    assert environment["CLAUDE_CODE_GIT_BASH_PATH"].endswith("bash.exe")
    assert environment["ANTHROPIC_BASE_URL"] == "https://example.invalid"
    assert environment[BUILD_JOB_ENV] == "job-9"
    assert environment[BUILD_ORIGIN_ENV] == "agent:intake"


def test_headless_agent_cannot_delegate_to_background_subagents(tmp_path: Path, scripted):
    calls, outcomes = scripted
    outcomes.append(ClaudeOutcome(0, OK_JSON, ""))
    _run(EngineeringAgent(timeout_s=60, retry_delays_s=(0.0,)), tmp_path)
    arguments = calls[0]["arguments"]
    disallowed = arguments[arguments.index("--disallowedTools") + 1].split(",")
    assert {"Agent", "Task", "Workflow", "Monitor"} <= set(disallowed)
    prompt = arguments[arguments.index("-p") + 1]
    assert "headless" in prompt and "Agent/Task" in prompt
    # 還有紅項時仍回 ok 並照實列出；只有發布不了有效版本才回 failed。
    assert "even if red or yellow checks remain" in prompt
    assert "never hide, delete, or rewrite a check" in prompt
