"""Codex Astra presentation runner with immutable engineering-build protection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from imageio_ffmpeg import write_frames
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from cellforge.versioning import latest_version_dir, restore_build


class AstraError(RuntimeError):
    pass


class AstraAgent:
    def __init__(self, command: str = "codex", model: str = "gpt-6-astra", timeout_s: float = 900):
        self.command = command
        self.model = model
        self.timeout_s = timeout_s

    async def run(
        self,
        project: Path,
        instruction: str,
        emit: Callable[[str, dict[str, Any]], None],
    ) -> dict[str, Any]:
        executable = shutil.which(self.command)
        if not executable:
            raise AstraError(f"Codex command not found: {self.command}")
        before = build_hash(project)
        prompt = (
            "You are the CellForge presentation agent. Never edit build/, source YAML, CAD, "
            "checks, or timeline. Read build/render_brief.md and create presentation/theme.json, "
            "presentation/camera.json, and presentation/easing.json only. "
            f"Instruction: {instruction}"
        )
        args = [
            executable,
            "exec",
            "--model",
            self.model,
            "--json",
            "--cd",
            str(project),
            "--sandbox",
            "workspace-write",
            "--ephemeral",
            prompt,
        ]
        emit("agent", {"message": f"Running Codex Astra ({self.model})"})
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_s)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise AstraError(f"Astra timed out after {self.timeout_s:g}s") from error
        if process.returncode:
            raise AstraError(stderr.decode("utf-8", errors="replace")[-4000:])
        after = build_hash(project)
        protected = before == after
        if not protected:
            version = latest_version_dir(project)
            if version:
                restore_build(project, version)
            raise AstraError("Astra modified protected engineering build; files were restored")
        video = render_video(project)
        result = {
            "status": "ok",
            "mode": "codex",
            "model": self.model,
            "build_hash_before": before,
            "build_hash_after": after,
            "build_unchanged": True,
            "video": str(video.relative_to(project)),
            "events": len(stdout.splitlines()),
        }
        _write_result(project, result, instruction)
        return result


def refresh_theme_local(project: Path, instruction: str = "請 Astra 美化") -> dict[str, Any]:
    before = build_hash(project)
    presentation = project / "presentation"
    presentation.mkdir(parents=True, exist_ok=True)
    (presentation / "theme.json").write_text(
        json.dumps(
            {
                "name": "CellForge Midnight",
                "background": "#0B1118",
                "confirmed": "#4299E1",
                "inferred": "#F6AD55",
                "collision": "#F56565",
                "instruction": instruction,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (presentation / "camera.json").write_text(
        json.dumps(
            {
                "presets": {
                    "iso": {"position": [0.75, -0.9, 0.62], "fov": 38},
                    "top": {"position": [0, 0, 1.55], "fov": 38},
                    "S3": {"target": "robot_1", "position": [0.5, -1.0, 0.5]},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (presentation / "easing.json").write_text(
        json.dumps(
            {"camera": "easeInOutCubic", "timeline": "linear", "crossfade_s": 0.35}, indent=2
        ),
        encoding="utf-8",
    )
    video = render_video(project)
    after = build_hash(project)
    result = {
        "status": "ok",
        "mode": "local",
        "build_hash_before": before,
        "build_hash_after": after,
        "build_unchanged": before == after,
        "video": str(video.relative_to(project)),
        "resolution": [1920, 1080],
    }
    if not result["build_unchanged"]:
        raise AstraError("Local presentation pass modified engineering build")
    _write_result(project, result, instruction)
    return result


def build_hash(project: Path) -> str:
    digest = hashlib.sha256()
    build = project / "build"
    for path in sorted(item for item in build.rglob("*") if item.is_file()):
        digest.update(path.relative_to(build).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def render_video(project: Path, output: Path | None = None) -> Path:
    output = output or project / "presentation" / "cell_review_1080p.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    images = [
        path
        for name in ("snapshot_t0_iso.png", "snapshot_station_s3.png", "snapshot_t0_top.png")
        if (path := project / "build" / name).is_file()
    ]
    if not images:
        images = [_placeholder(project)]
    frames = []
    for index, path in enumerate(images):
        source = Image.open(path).convert("RGB")
        source.thumbnail((1760, 880), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (1920, 1080), "#0B1118")
        x = (1920 - source.width) // 2
        y = 90 + (880 - source.height) // 2
        canvas.paste(ImageEnhance.Contrast(source).enhance(1.06), (x, y))
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (80, 35),
            "CELLFORGE • ENGINEERING REVIEW",
            fill="#E6F1FF",
            font=ImageFont.load_default(size=28),
        )
        draw.text(
            (80, 1010),
            f"View {index + 1}/{len(images)}",
            fill="#F6AD55",
            font=ImageFont.load_default(size=22),
        )
        frames.append(canvas)
    writer = write_frames(
        str(output),
        (1920, 1080),
        fps=12,
        codec="libx264",
        quality=7,
        macro_block_size=1,
    )
    writer.send(None)
    try:
        for frame in frames:
            for _ in range(18):
                writer.send(frame.tobytes())
    finally:
        writer.close()
    return output


def _placeholder(project: Path) -> Path:
    path = project / "presentation" / "placeholder.png"
    image = Image.new("RGB", (1280, 720), "#0B1118")
    draw = ImageDraw.Draw(image)
    draw.text(
        (80, 80),
        "CellForge engineering scene",
        fill="#E6F1FF",
        font=ImageFont.load_default(size=32),
    )
    image.save(path)
    return path


def _write_result(project: Path, result: dict[str, Any], instruction: str) -> None:
    payload = {
        **result,
        "instruction": instruction,
        "generated": datetime.now().astimezone().isoformat(),
    }
    (project / "presentation" / "astra_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
