"""Read/write MCP boundary exposed to Codex Astra and engineering clients."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from cellforge.build.pipeline import build_project
from cellforge.diffing import diff_versions
from cellforge.snapshot import snapshot_project
from cellforge.validation import validate_project
from cellforge.version_store import BUILD_ORIGIN_ENV
from cellforge.versioning import VersionContext

mcp = FastMCP("CellForge")


@mcp.tool()
def cell_build(project: str, level: str = "L1") -> dict:
    """Build a project and return STEP/OCP and check summaries."""
    os.environ.setdefault(BUILD_ORIGIN_ENV, "mcp")
    return build_project(Path(project).resolve(), level)


@mcp.tool()
def cell_snapshot(
    project: str, time_s: float, camera: str = "iso", include_base64: bool = False
) -> dict:
    """Render a version-aware browser snapshot."""
    path = snapshot_project(Path(project).resolve(), time_s, camera)
    result = {"path": str(path)}
    if include_base64:
        result["base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
    return result


@mcp.tool()
def cell_validate(project: str) -> dict:
    """Validate project schemas, references, source hashes, and module params."""
    validate_project(Path(project).resolve())
    return {"status": "ok"}


@mcp.tool()
def cell_checks(project: str, version: str | None = None) -> dict:
    """Read check details without mutating the engineering model."""
    context = VersionContext.open(Path(project).resolve(), version)
    return context.artifact_json("checks.json", "讀取檢查結果（L0 版本沒有 L1 檢查）")


@mcp.tool()
def cell_timeline_summary(project: str, version: str | None = None) -> dict:
    """Return timing and station spans for presentation planning."""
    context = VersionContext.open(Path(project).resolve(), version)
    timeline = context.artifact_json("timeline.json", "讀取時間軸摘要")
    return {
        "duration_s": timeline["duration_s"],
        "fps": timeline["fps"],
        "stations": timeline["stations"],
    }


@mcp.tool()
def cell_diff(project: str, before: str, after: str) -> dict:
    """Return semantic model/check/timeline changes between versions."""
    return diff_versions(Path(project).resolve(), before, after)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
