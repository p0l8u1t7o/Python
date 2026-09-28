"""Bounded, streaming Claude Code runner for engineering jobs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from cellforge.procutil import ProcessTimeoutError, run_streaming
from cellforge.project import source_root
from cellforge.version_store import BUILD_JOB_ENV, BUILD_ORIGIN_ENV

AgentKind = Literal["intake", "first_build", "apply_cr", "assumption_override"]
EventSink = Callable[[str, dict[str, Any]], None]

# 只有網路或服務端錯誤才重試；代理回報的工程失敗與逾時都直接回報，不盲目重跑。
RETRY_DELAYS_S = (10.0, 30.0)
CAPTION_TIMEOUT_S = 60.0
PARENT_SESSION_VARIABLES = frozenset(
    {
        "CLAUDECODE",
        "CLAUDE_PID",
        "CLAUDE_EFFORT",
        "CLAUDE_AGENT_SDK_VERSION",
        "CLAUDE_PLUGIN_DATA",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_EXECPATH",
        "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING",
        "CLAUDE_CODE_ENABLE_TASKS",
    }
)
PARENT_SESSION_PREFIXES = ("CLAUDE_CODE_SESSION", "CLAUDE_CODE_CHILD", "CLAUDE_CODE_MESSAGING")
# headless 執行在最後一則訊息後就結束，子代理與背景等待的工作會被一併終止；
# DEV-006 實測代理把修正交給背景子代理後結束回合，沒有回傳最終 JSON。
HEADLESS_DISALLOWED_TOOLS = (
    "Agent,Task,TaskOutput,TaskStop,Workflow,Monitor,ScheduleWakeup,CronCreate,RemoteTrigger"
)
CAPTION_ATTEMPTS = 2
NETWORK_ERROR = re.compile(
    r"(ECONNREFUSED|ConnectionRefused|ECONNRESET|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|getaddrinfo"
    r"|socket hang up|fetch failed|Connection error|APIConnectionError|network error"
    r"|overloaded_error|Overloaded|rate_limit_error|\b529\b|\b503 Service)",
    re.IGNORECASE,
)


class EngineeringAgentError(RuntimeError):
    """Raised when Claude cannot run or returns an invalid result."""


@dataclass(frozen=True)
class ClaudeCapabilities:
    executable: str
    version: str
    supports_stream_json: bool
    supports_accept_edits: bool
    supports_effort: bool


def detect_claude(command: str = "claude", *, timeout_s: float = 10) -> ClaudeCapabilities:
    candidates: list[str] = []
    if Path(command).is_file():
        candidates.append(str(Path(command).resolve()))
    else:
        if resolved := shutil.which(command):
            candidates.append(resolved)
        if command.lower() in {"claude", "claude.exe"}:
            for extensions_root in (
                Path.home() / ".vscode" / "extensions",
                Path.home() / ".cursor" / "extensions",
            ):
                candidates.extend(
                    str(path)
                    for path in extensions_root.glob(
                        "anthropic.claude-code-*-win32-x64/resources/native-binary/claude.exe"
                    )
                )
    if not candidates:
        raise EngineeringAgentError(f"找不到 Claude Code 指令：{command}")
    detected: list[tuple[tuple[int, ...], str, str]] = []
    for candidate in dict.fromkeys(candidates):
        try:
            version = subprocess.run(
                [candidate, "--version"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            ).stdout.strip()
            match = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
            version_key = tuple(int(value) for value in match.groups()) if match else (0,)
            detected.append((version_key, candidate, version))
        except (OSError, subprocess.SubprocessError):
            continue
    if not detected:
        raise EngineeringAgentError(f"無法執行 Claude Code：{command}")
    _, executable, version = max(detected)
    try:
        help_text = subprocess.run(
            [executable, "--help"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise EngineeringAgentError(f"無法檢查 Claude Code：{error}") from error
    return ClaudeCapabilities(
        executable=executable,
        version=version,
        supports_stream_json="stream-json" in help_text,
        supports_accept_edits="acceptEdits" in help_text,
        supports_effort="--effort" in help_text,
    )


def _read_prompt(kind: AgentKind) -> str:
    prompts = Path(__file__).with_name("prompts")
    chunks = [
        (prompts / "common.md").read_text("utf-8"),
        (prompts / f"{kind}.md").read_text("utf-8"),
    ]
    skill_names = {
        "intake": ["cell-intake", "cell-process-planning"],
        "first_build": ["cell-process-planning"],
        "apply_cr": [],
        "assumption_override": [],
    }[kind]
    for skill_name in skill_names:
        skill = source_root() / "skills" / skill_name / "SKILL.md"
        chunks.append(f"\n## Required skill: {skill_name}\n\n{skill.read_text('utf-8')}")
    return "\n\n---\n\n".join(chunks)


def _json_from_text(text: str) -> dict[str, Any] | None:
    candidates = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, flags=re.DOTALL)
    for candidate in reversed(candidates):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("status") in {"ok", "failed"}:
            return value
    return None


def _event_summary(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type", "agent"))
    if event_type == "result":
        return str(event.get("result") or "Claude 工程代理完成")
    message = event.get("message")
    if not isinstance(message, dict):
        return str(message) if message else None
    if message.get("role") == "user":
        return None
    summaries: list[str] = []
    for content in message.get("content", []):
        if not isinstance(content, dict):
            continue
        if content.get("type") == "text" and content.get("text"):
            summaries.append(str(content["text"]))
        elif content.get("type") == "tool_use":
            name = str(content.get("name", "tool"))
            tool_input = content.get("input", {})
            detail = ""
            if isinstance(tool_input, dict):
                detail = str(tool_input.get("file_path") or tool_input.get("command") or "")
            summaries.append(f"{name}: {detail}".rstrip())
    return " | ".join(summaries) or None


class EngineeringAgent:
    def __init__(
        self,
        command: str = "claude",
        *,
        model: str | None = None,
        effort: str | None = "low",
        timeout_s: float = 1800,
        max_attempts: int = 3,
        retry_delays_s: tuple[float, ...] = RETRY_DELAYS_S,
    ):
        self.command = command
        self.model = model
        self.effort = effort
        self.timeout_s = timeout_s
        self.max_attempts = max(1, max_attempts)
        self.retry_delays_s = retry_delays_s

    async def run(
        self,
        kind: AgentKind,
        project: Path,
        emit: EventSink,
        *,
        context: str = "",
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Run one agent task within ``timeout_s`` in total, retrying only network failures."""

        deadline = time.monotonic() + self.timeout_s
        capabilities = await asyncio.to_thread(detect_claude, self.command)
        if not capabilities.supports_stream_json or not capabilities.supports_accept_edits:
            raise EngineeringAgentError(
                "Claude Code 缺少 stream-json 或 acceptEdits 支援，請更新 Claude Code。"
            )
        environment = self._environment(job_id=job_id, origin=f"agent:{kind}")
        if kind == "intake":
            await self._prepare_vision_summary(capabilities, project, emit, deadline, environment)
        prompt = _read_prompt(kind)
        if context:
            prompt += f"\n\n## Job context\n\n{context.strip()}\n"
        arguments = [
            capabilities.executable,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            "Read,Write,Edit,Bash(cell *),Bash(git *),Bash(python *),Bash(python3 *)",
            "--disallowedTools",
            HEADLESS_DISALLOWED_TOOLS,
            "--add-dir",
            str(source_root()),
        ]
        if self.model:
            arguments.extend(["--model", self.model])
        if self.effort and capabilities.supports_effort:
            arguments.extend(["--effort", self.effort])
        failures: list[str] = []
        for attempt in range(1, self.max_attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineeringAgentError(
                    f"Claude 工程代理已用完 {self.timeout_s:.0f} 秒總期限"
                    f"（已嘗試 {attempt - 1} 次）：" + "；".join(failures)
                )
            emit(
                "agent",
                {
                    "message": f"Claude Code {capabilities.version} 啟動：{kind}"
                    f"（第 {attempt}/{self.max_attempts} 次，剩餘 {remaining:.0f} 秒）",
                    "command": capabilities.executable,
                },
            )
            outcome = await _run_claude(arguments, project, environment, emit, remaining)
            if outcome.timed_out:
                raise EngineeringAgentError(
                    f"Claude 工程代理超過 {self.timeout_s:.0f} 秒總期限，已連同子程序一併停止。"
                )
            if outcome.returncode == 0:
                result = _json_from_text(outcome.final_text)
                if result is None:
                    raise EngineeringAgentError("Claude 工程代理未回傳規定的最終 JSON。")
                if result["status"] != "ok":
                    # 代理自己判定失敗（例如幾何或驗證錯誤）是工程結論，不盲目重試。
                    raise EngineeringAgentError(str(result.get("summary", "工程代理回報失敗")))
                return {**result, "attempts": attempt}
            reason = network_failure(outcome.diagnostics)
            failures.append(
                f"第 {attempt} 次退出碼 {outcome.returncode}" + (f"（{reason}）" if reason else "")
            )
            if reason is None or attempt == self.max_attempts:
                detail = f"：{reason}" if reason else ""
                raise EngineeringAgentError(
                    f"Claude 工程代理失敗，退出碼 {outcome.returncode}{detail}"
                    f"（共嘗試 {attempt} 次）"
                )
            delay = min(
                self.retry_delays_s[min(attempt - 1, len(self.retry_delays_s) - 1)],
                max(deadline - time.monotonic(), 0),
            )
            emit(
                "agent",
                {"message": f"偵測到網路或服務錯誤（{reason}），{delay:.0f} 秒後重試"},
            )
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _environment(job_id: str | None = None, origin: str | None = None) -> dict[str, str]:
        environment = {
            name: value
            for name, value in os.environ.items()
            if not is_parent_session_variable(name)
        }
        scripts = source_root() / ".venv" / "Scripts"
        if scripts.is_dir():
            environment["PATH"] = str(scripts) + os.pathsep + environment.get("PATH", "")
            environment["VIRTUAL_ENV"] = str(source_root() / ".venv")
        # 代理在工作階段內執行的 cell build 會把這兩個值寫進版本 manifest。
        if job_id:
            environment[BUILD_JOB_ENV] = job_id
        if origin:
            environment[BUILD_ORIGIN_ENV] = origin
        return environment

    async def _prepare_vision_summary(
        self,
        capabilities: ClaudeCapabilities,
        project: Path,
        emit: EventSink,
        deadline: float,
        environment: dict[str, str],
    ) -> None:
        extraction_path = project / "analysis" / "extraction.json"
        extraction = json.loads(extraction_path.read_text("utf-8"))
        images: list[tuple[str, str]] = []
        for record in extraction.get("files", []):
            source = str(record["source"])
            if record.get("kind") == "product_photo":
                images.extend((str(path), source) for path in record.get("artifacts", []))
            elif source.lower().endswith(".pdf"):
                images.extend(
                    (str(item["image"]), f"{source} page {item['page']}")
                    for item in record.get("artifacts", [])
                    if isinstance(item, dict) and int(item.get("characters", 0)) < 200
                )
        cache_path = project / "analysis" / "extracted" / "vision.json"
        cache: dict[str, dict[str, str]] = {}
        if cache_path.is_file():
            try:
                cache = json.loads(cache_path.read_text("utf-8"))
            except json.JSONDecodeError:
                cache = {}
        for index, (relative, source) in enumerate(images, 1):
            image_path = project / relative
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            cached = cache.get(relative)
            if cached and cached.get("sha256") == digest:
                emit(
                    "agent",
                    {"message": f"沿用視覺快取 {index}/{len(images)}：{Path(relative).name}"},
                )
                continue
            emit(
                "agent",
                {"message": f"Claude 視覺判讀 {index}/{len(images)}：{Path(relative).name}"},
            )
            caption = await self._caption_image(
                capabilities, project, relative, source, deadline, environment, emit
            )
            cache[relative] = {"sha256": digest, "source": source, "caption": caption}
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        lines = ["# Claude 視覺逐圖判讀", ""]
        for relative, source in images:
            item = cache[relative]
            lines.extend(
                [
                    f"## {source}",
                    f"- 判讀檔：`{relative}`",
                    f"- 結果：{item['caption']}",
                    "",
                ]
            )
        (project / "analysis" / "extracted" / "vision.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )

    async def _caption_image(
        self,
        capabilities: ClaudeCapabilities,
        project: Path,
        relative: str,
        source: str,
        deadline: float,
        environment: dict[str, str],
        emit: EventSink,
    ) -> str:
        prompt = (
            f"Use the Read tool on `{relative}`. This is a review copy of `{source}`. "
            "Describe only visible engineering evidence in Traditional Chinese: product face, "
            "covers, ports, hinges, labels, geometry, and uncertainty. Do not infer hidden facts. "
            "Reply with one compact paragraph and no markdown."
        )
        arguments = [
            capabilities.executable,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            "Read",
        ]
        if self.model:
            arguments.extend(["--model", self.model])
        if self.effort and capabilities.supports_effort:
            arguments.extend(["--effort", self.effort])
        for attempt in range(1, CAPTION_ATTEMPTS + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineeringAgentError(f"Claude 視覺判讀已用完工作總期限：{relative}")
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            try:
                code = await run_streaming(
                    arguments,
                    cwd=project,
                    env=environment,
                    timeout_s=min(CAPTION_TIMEOUT_S, remaining),
                    on_stdout=stdout_lines.append,
                    on_stderr=stderr_lines.append,
                )
            except ProcessTimeoutError as error:
                if attempt < CAPTION_ATTEMPTS:
                    emit("agent", {"message": f"視覺判讀逾時，重試一次：{relative}"})
                    continue
                raise EngineeringAgentError(
                    f"Claude 視覺判讀超時（每次 {CAPTION_TIMEOUT_S:.0f} 秒，共嘗試 {attempt} 次）："
                    f"{relative}"
                ) from error
            stdout = "\n".join(stdout_lines)
            stderr = "\n".join(stderr_lines).strip()
            if code != 0:
                reason = network_failure(f"{stderr}\n{stdout}")
                if reason and attempt < CAPTION_ATTEMPTS:
                    emit("agent", {"message": f"視覺判讀遇到{reason}，重試一次：{relative}"})
                    continue
                raise EngineeringAgentError(
                    f"Claude 視覺判讀失敗：{relative}：{stderr or reason or f'退出碼 {code}'}"
                )
            try:
                payload = json.loads(stdout)
                caption = str(payload["result"]).strip()
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise EngineeringAgentError(f"Claude 視覺判讀回傳格式錯誤：{relative}") from error
            if not caption:
                raise EngineeringAgentError(f"Claude 視覺判讀沒有內容：{relative}")
            return caption
        raise AssertionError("unreachable")


@dataclass(frozen=True)
class ClaudeOutcome:
    returncode: int | None
    final_text: str
    diagnostics: str
    timed_out: bool = False


async def _run_claude(
    arguments: list[str],
    project: Path,
    environment: dict[str, str],
    emit: EventSink,
    timeout_s: float,
) -> ClaudeOutcome:
    final_parts: list[str] = []
    diagnostics: list[str] = []

    def on_stdout(line: str) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            emit("log", {"message": line})
            final_parts.append(line)
            diagnostics.append(line)
            return
        if not isinstance(event, dict):
            return
        event_type = str(event.get("type", "agent"))
        if event_type == "result":
            text = str(event.get("result", ""))
            final_parts.append(text)
            diagnostics.append(text)
        message = _event_summary(event)
        if message:
            emit("agent", {"event_type": event_type, "message": message[:2000]})

    def on_stderr(line: str) -> None:
        diagnostics.append(line)
        emit("log", {"stream": "stderr", "message": line})

    try:
        code = await run_streaming(
            arguments,
            cwd=project,
            env=environment,
            timeout_s=timeout_s,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
        )
    except ProcessTimeoutError:
        return ClaudeOutcome(None, "\n".join(final_parts), "\n".join(diagnostics[-200:]), True)
    return ClaudeOutcome(code, "\n".join(final_parts), "\n".join(diagnostics[-200:]))


def is_parent_session_variable(name: str) -> bool:
    """Markers of an enclosing Claude Code session that a spawned agent must not inherit.

    伺服器若是從另一個 Claude Code 工作階段內啟動，工程代理會繼承父工作階段的 id、訊息通道
    與 effort，把自己當成子工作階段；授權與一般設定（例如 CLAUDE_CODE_GIT_BASH_PATH）保留。
    """

    upper = name.upper()
    return upper in PARENT_SESSION_VARIABLES or upper.startswith(PARENT_SESSION_PREFIXES)


def network_failure(text: str) -> str | None:
    """Return a short reason when ``text`` shows a network or service failure worth retrying."""

    match = NETWORK_ERROR.search(text)
    return f"網路或服務錯誤 {match.group(1)}" if match else None
