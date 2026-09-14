"""Bounded, streaming Claude Code runner for engineering jobs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from cellforge.project import source_root

AgentKind = Literal["intake", "first_build", "apply_cr", "assumption_override"]
EventSink = Callable[[str, dict[str, Any]], None]


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
    ):
        self.command = command
        self.model = model
        self.effort = effort
        self.timeout_s = timeout_s

    async def run(
        self,
        kind: AgentKind,
        project: Path,
        emit: EventSink,
        *,
        context: str = "",
    ) -> dict[str, Any]:
        capabilities = await asyncio.to_thread(detect_claude, self.command)
        if not capabilities.supports_stream_json or not capabilities.supports_accept_edits:
            raise EngineeringAgentError(
                "Claude Code 缺少 stream-json 或 acceptEdits 支援，請更新 Claude Code。"
            )
        if kind == "intake":
            await self._prepare_vision_summary(capabilities, project, emit)
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
            "--add-dir",
            str(source_root()),
        ]
        if self.model:
            arguments.extend(["--model", self.model])
        if self.effort and capabilities.supports_effort:
            arguments.extend(["--effort", self.effort])
        emit(
            "agent",
            {
                "message": f"Claude Code {capabilities.version} 啟動：{kind}",
                "command": capabilities.executable,
            },
        )
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=project,
            env=self._environment(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        final_text = ""

        async def read_stdout() -> None:
            nonlocal final_text
            assert process.stdout is not None
            while line_bytes := await process.stdout.readline():
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    emit("log", {"message": line})
                    final_text += "\n" + line
                    continue
                event_type = str(event.get("type", "agent"))
                if event_type == "result":
                    final_text += "\n" + str(event.get("result", ""))
                message = _event_summary(event)
                if message:
                    emit("agent", {"event_type": event_type, "message": message[:2000]})

        async def read_stderr() -> None:
            assert process.stderr is not None
            while line_bytes := await process.stderr.readline():
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                if line:
                    emit("log", {"stream": "stderr", "message": line})

        readers = [asyncio.create_task(read_stdout()), asyncio.create_task(read_stderr())]
        try:
            await asyncio.wait_for(process.wait(), timeout=self.timeout_s)
            await asyncio.gather(*readers)
        except TimeoutError as error:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
            raise EngineeringAgentError(
                f"Claude 工程代理超過 {self.timeout_s:.0f} 秒，已停止。"
            ) from error
        except asyncio.CancelledError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
            raise
        finally:
            for reader in readers:
                if not reader.done():
                    reader.cancel()
        if process.returncode != 0:
            raise EngineeringAgentError(f"Claude 工程代理失敗，退出碼 {process.returncode}")
        result = _json_from_text(final_text)
        if result is None:
            raise EngineeringAgentError("Claude 工程代理未回傳規定的最終 JSON。")
        if result["status"] != "ok":
            raise EngineeringAgentError(str(result.get("summary", "工程代理回報失敗")))
        return result

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = os.environ.copy()
        scripts = source_root() / ".venv" / "Scripts"
        if scripts.is_dir():
            environment["PATH"] = str(scripts) + os.pathsep + environment.get("PATH", "")
            environment["VIRTUAL_ENV"] = str(source_root() / ".venv")
        return environment

    async def _prepare_vision_summary(
        self,
        capabilities: ClaudeCapabilities,
        project: Path,
        emit: EventSink,
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
            caption = await self._caption_image(capabilities, project, relative, source)
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
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=project,
            env=self._environment(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise EngineeringAgentError(f"Claude 視覺判讀超時：{relative}") from error
        except asyncio.CancelledError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
            raise
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise EngineeringAgentError(f"Claude 視覺判讀失敗：{relative}：{detail}")
        try:
            payload = json.loads(stdout.decode("utf-8", errors="replace"))
            caption = str(payload["result"]).strip()
        except (json.JSONDecodeError, KeyError) as error:
            raise EngineeringAgentError(f"Claude 視覺判讀回傳格式錯誤：{relative}") from error
        if not caption:
            raise EngineeringAgentError(f"Claude 視覺判讀沒有內容：{relative}")
        return caption
