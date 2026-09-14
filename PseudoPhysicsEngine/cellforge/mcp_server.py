"""Read/write MCP boundary exposed to Codex Astra and engineering clients."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from cellforge.build.pipeline import build_project
from cellforge.diffing import diff_versions
from cellforge.snapshot import snapshot_project
from cellforge.validation import validate_project
from cellforge.versioning import latest_version_dir

mcp = FastMCP("CellForge")


@mcp.tool()
def cell_build(project: str, level: str = "L1") -> dict:
    """Build a project and return STEP/OCP and check summaries."""
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
    root = Path(project).resolve()
    directory = root / ".cellforge" / version if version else latest_version_dir(root)
    if directory is None or not (directory / "checks.json").is_file():
        raise FileNotFoundError("checks.json")
    return json.loads((directory / "checks.json").read_text("utf-8"))


@mcp.tool()
def cell_timeline_summary(project: str, version: str | None = None) -> dict:
    """Return timing and station spans for presentation planning."""
    root = Path(project).resolve()
    directory = root / ".cellforge" / version if version else latest_version_dir(root)
    if directory is None:
        raise FileNotFoundError("version")
    timeline = json.loads((directory / "timeline.json").read_text("utf-8"))
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
