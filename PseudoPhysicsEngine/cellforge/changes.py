"""Deterministic local engineering changes used by tests and offline mode."""

from __future__ import annotations

import re
from pathlib import Path

from cellforge.build.pipeline import build_project
from cellforge.yamlio import dump_yaml, load_yaml


def apply_local_change(project: Path, change_id: str, instruction: str) -> dict:
    normalized = instruction.lower().replace(" ", "")
    result: dict = {"change_id": change_id, "instruction": instruction, "edits": []}
    if "法蘭" in instruction and ("退" in instruction or "retract" in normalized):
        match = re.search(r"(\d+(?:\.\d+)?)\s*mm", instruction, re.IGNORECASE)
        amount = float(match.group(1)) if match else 20.0
        path = project / "cell.yaml"
        cell = load_yaml(path)
        robot = next(
            module
            for machine in cell["machines"]
            for module in machine["modules"]
            if module["id"] == "robot_1"
        )
        before = float(robot.setdefault("params", {}).get("flange_clearance_mm", -3.2))
        robot["params"]["flange_clearance_mm"] = before + amount
        dump_yaml(path, cell)
        result["edits"].append(
            {
                "path": "cell.yaml",
                "field": "robot_1.params.flange_clearance_mm",
                "before": before,
                "after": before + amount,
            }
        )
    if not result["edits"]:
        raise ValueError("Local mode cannot safely interpret this engineering change")
    build = build_project(project, "L1")
    change_path = project / "changes" / f"{change_id}.md"
    with change_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n- status: complete\n- build: v{build['version']}\n"
            f"- verification: {build.get('checks')}\n"
        )
    return {**result, "status": "ok", "mode": "local", "build": build}
