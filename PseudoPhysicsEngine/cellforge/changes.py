"""Deterministic local engineering changes used by tests and offline mode."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cellforge.build.pipeline import build_project
from cellforge.diffing import diff_versions
from cellforge.versioning import latest_version_dir
from cellforge.yamlio import dump_yaml, load_yaml


def _robot_name(object_name: str | None, instruction: str, process: dict[str, Any]) -> str:
    if object_name:
        return object_name.partition(".")[0]
    if "法蘭" in instruction:
        named = [
            str(step.get("actor"))
            for step in process.get("steps", [])
            if str(step.get("actor", "")).startswith("robot_")
        ]
        if named:
            return named[0]
    raise ValueError("修改指令缺少可辨識的手臂物件")


def _target_step(
    process: dict[str, Any],
    timeline: dict[str, Any],
    robot: str,
    at_time: float | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    raw_steps = {str(step["id"]): step for step in process.get("steps", [])}
    timed_steps = timeline.get("steps", [])

    def belongs(timed: dict[str, Any]) -> bool:
        raw = raw_steps.get(str(timed.get("id")), {})
        return raw.get("actor") == robot or raw.get("driven_by") == robot

    if at_time is not None:
        running = [
            timed
            for timed in timed_steps
            if float(timed["t0"]) - 1e-9 <= at_time <= float(timed["t1"]) + 1e-9
            and belongs(timed)
            and (raw_steps.get(str(timed.get("id")), {}).get("target") or {}).get("frame")
        ]
        if running:
            timed = running[-1]
            return raw_steps[str(timed["id"])], timed

    candidates = [
        timed
        for timed in timed_steps
        if belongs(timed)
        and (raw_steps.get(str(timed.get("id")), {}).get("target") or {}).get("frame")
        and (at_time is None or float(timed["t1"]) <= at_time + 1e-9)
    ]
    if not candidates:
        candidates = [
            timed
            for timed in timed_steps
            if belongs(timed)
            and (raw_steps.get(str(timed.get("id")), {}).get("target") or {}).get("frame")
        ]
    if not candidates:
        raise ValueError(f"找不到手臂 {robot} 可後退的 target.frame 步驟")
    timed = max(candidates, key=lambda item: float(item["t1"]))
    return raw_steps[str(timed["id"])], timed


def _change_header(
    path: Path, change_id: str, instruction: str, object_name: str | None, t: float | None
) -> str:
    existing = path.read_text("utf-8") if path.is_file() else ""
    source = next(
        (
            line.removeprefix("- 來源：")
            for line in existing.splitlines()
            if line.startswith("- 來源：")
        ),
        "使用者",
    )
    if object_name:
        source = f"{source.split(' / 3D 右鍵', 1)[0]} / 3D 右鍵 {object_name}"
        if t is not None:
            source += f" @ t={t:g}"
    return f"# {change_id}\n- 來源：{source}\n- 原始指令：{instruction}\n"


def apply_local_change(
    project: Path,
    change_id: str,
    instruction: str,
    object_name: str | None = None,
    t: float | None = None,
) -> dict[str, Any]:
    match = re.search(r"(?:退|後退|retract)[^\d]*(\d+(?:\.\d+)?)\s*mm", instruction, re.IGNORECASE)
    if match is None:
        raise ValueError("本機模式只能套用含明確 mm 數值的退／後退／retract 指令")
    amount = float(match.group(1))
    if amount <= 0:
        raise ValueError("後退距離必須大於零")

    process_path = project / "process.yaml"
    process = load_yaml(process_path)
    timeline_path = project / "build" / "timeline.json"
    if not timeline_path.is_file():
        raise ValueError("套用修改前必須先完成一次建置，找不到 build/timeline.json")
    timeline = json.loads(timeline_path.read_text("utf-8"))
    before_dir = latest_version_dir(project)
    if before_dir is None:
        raise ValueError("套用修改前必須有可比較的建置版本")
    robot = _robot_name(object_name, instruction, process)
    step, timed = _target_step(process, timeline, robot, t)
    target = step.setdefault("target", {})
    offset = target.setdefault("offset", {})
    xyz = list(offset.get("xyz", [0.0, 0.0, 0.0]))
    while len(xyz) < 3:
        xyz.append(0.0)
    before = float(xyz[2])
    xyz[2] = before + amount
    offset["xyz"] = xyz
    dump_yaml(process_path, process)

    build = build_project(project, "L1")
    after_name = f"v{build['version']}"
    difference = diff_versions(project, before_dir.name, after_name)
    checks_path = project / ".cellforge" / after_name / "checks.json"
    checks = json.loads(checks_path.read_text("utf-8"))
    span = f"{float(timed['t0']):.3f}–{float(timed['t1']):.3f} s" if timed is not None else "未定"
    interpretation = (
        f"{step['id']} target.offset.xyz[2]：{before:g} → {xyz[2]:g} mm；沿目標 frame 的外法線後退"
    )
    diff_text = f"{difference['from']} → {difference['to']}，共 {difference['count']} 項差異"
    change_path = project / "changes" / f"{change_id}.md"
    change_path.parent.mkdir(parents=True, exist_ok=True)
    change_path.write_text(
        _change_header(change_path, change_id, instruction, object_name, t)
        + f"- 代理解讀：{interpretation}\n"
        + f"- 影響：process.yaml {step['id']}；timeline {span}；L1 checks 已重算\n"
        + f"- 差異：{diff_text}\n"
        + "- 需重跑：build ✔  模擬 ✔  渲染 ✔\n"
        + (
            f"- 結果：{after_name} checks red {checks['summary']['red']} / "
            f"yellow {checks['summary']['yellow']}\n"
        )
        + "- 狀態：applied\n",
        encoding="utf-8",
    )
    return {
        "change_id": change_id,
        "instruction": instruction,
        "edits": [
            {
                "path": "process.yaml",
                "step": step["id"],
                "field": "target.offset.xyz[2]",
                "before": before,
                "after": float(xyz[2]),
            }
        ],
        "status": "ok",
        "mode": "local",
        "build": build,
        "diff": difference,
    }
