"""DEV-008：多零件實例、唯一持有者與持有鏈連帶移動。

期望值一律由時間軸本身的初始相對位姿推得（載盤帶著板子走、手臂夾著板子走），
不寫死任何位置或時間。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pygltflib import GLTF2

from cellforge.build.pipeline import build_project
from cellforge.checks.runner import _held_by
from cellforge.project import create_project
from cellforge.sim.sampling import state_at
from cellforge.validation import ProjectValidationError, validate_project
from cellforge.yamlio import dump_yaml, load_yaml

WORKPIECE = {
    "units": "mm",
    "skus": [
        {"id": "tray", "size": {"x": 320, "y": 240, "z": 20}, "mass_kg": 0.8},
        {"id": "board", "size": {"x": 200, "y": 150, "z": 30}, "mass_kg": 0.2},
    ],
    "parts": [
        {"id": "tray", "sku": "tray", "initial": {"frame": "conveyor_1.start"}},
        {"id": "board", "sku": "board", "initial": {"frame": "tray.top"}},
    ],
}
STEPS = [
    {
        "id": "S1.convey",
        "station": "S1",
        "actor": "conveyor_1",
        "action": "transfer",
        "object": "tray",
        "target": {"frame": "vision_fixture.top"},
    },
    {
        "id": "S2.prepare",
        "station": "S2",
        "actor": "robot_2",
        "action": "move_joint",
        "value": {"joints_deg": [-14, -20, 32, -18, 24, -35]},
        "duration_s": 1.5,
    },
    {
        "id": "S2.approach",
        "station": "S2",
        "actor": "robot_2",
        "action": "move_to",
        "target": {"frame": "board.left", "offset": {"xyz": [0, 0, 50]}},
        "value": {"linear": True},
        "duration_s": 1.5,
    },
    {"id": "S2.grip", "station": "S2", "actor": "robot_2", "action": "grip", "object": "board"},
    {
        "id": "S2.lift",
        "station": "S2",
        "actor": "robot_2",
        "action": "move_to",
        "target": {"frame": "board.left", "offset": {"xyz": [0, 0, 150]}},
        "value": {"linear": True},
        "duration_s": 1.5,
    },
    {
        "id": "S2.place",
        "station": "S2",
        "actor": "robot_2",
        "action": "release",
        "object": "board",
        "target": {"frame": "tray.top"},
        "duration_s": 0.5,
    },
]


def _project(root: Path, *, workpiece: dict | None = None, steps: list | None = None) -> Path:
    project = create_project(
        root / "parts",
        {"name": "多零件", "created": date.today().isoformat()},
        seed_example="getac_qc",
    )
    dump_yaml(project / "workpiece.yaml", workpiece or WORKPIECE)
    dump_yaml(
        project / "process.yaml",
        {
            "stations": [
                {"id": "S1", "name": "進料", "modules": ["conveyor_1"]},
                {"id": "S2", "name": "取放", "modules": ["robot_2", "vision_fixture"]},
            ],
            "steps": steps or STEPS,
            "takt": {"target_s": 60},
        },
    )
    return project


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    project = _project(tmp_path_factory.mktemp("dev008_parts"))
    report = build_project(project, "L0")
    version = project / ".cellforge" / report["version_id"]
    timeline = json.loads((version / "timeline.json").read_text("utf-8"))
    return project, report, version, timeline


def _step(timeline: dict, step_id: str) -> dict:
    return next(step for step in timeline["steps"] if step["id"] == step_id)


def _times(t0: float, t1: float, count: int = 6) -> list[float]:
    return [t0 + (t1 - t0) * index / (count - 1) for index in range(count)]


def test_parts_have_their_own_tracks_and_a_single_holder_at_every_time(built):
    _project, _report, _version, timeline = built
    nodes = timeline["nodes"]
    assert nodes["tray"]["type"] == nodes["board"]["type"] == "pose"
    assert "workpiece" not in nodes
    holders = [key[1] for key in nodes["board"]["attached_to"]]
    assert holders[0] == "tray"
    assert "robot_2.tool" in holders
    assert holders[-1] == "tray"
    assert all(holder != "board" for holder in holders)
    grip = _step(timeline, "S2.grip")
    before = state_at(timeline, grip["t0"] - 1e-6)
    after = state_at(timeline, grip["t1"] + 1e-6)
    assert before.part("board").holder == "tray"
    assert after.part("board").holder == "robot_2.tool"


def test_board_rides_on_the_tray_during_transfer(built):
    _project, _report, _version, timeline = built
    convey = _step(timeline, "S1.convey")
    start = state_at(timeline, convey["t0"])
    relative = np.linalg.inv(start.part("tray").pose) @ start.part("board").pose
    moved = False
    for t in _times(convey["t0"], convey["t1"]):
        state = state_at(timeline, t)
        tray, board = state.part("tray").pose, state.part("board").pose
        assert np.allclose(np.linalg.inv(tray) @ board, relative, atol=1e-6), t
        moved |= not np.allclose(tray[:3, 3], start.part("tray").pose[:3, 3], atol=1.0)
    assert moved


def test_gripped_board_follows_the_tool_and_leaves_the_tray_behind(built):
    project, _report, _version, timeline = built
    from cellforge.build.modules import build_module, project_parts
    from cellforge.sim import SceneModel, build_parts

    _p, workpiece, cell, process = validate_project(project)
    with project_parts(project):
        modules = [build_module(i) for m in cell.machines for i in m.modules]
    scene = SceneModel(cell, modules, build_parts(workpiece, process, build_geometry=False))
    lift = _step(timeline, "S2.lift")
    start = state_at(timeline, lift["t0"])
    tool = scene.resolve_frame("robot_2.tool", start)
    relative = np.linalg.inv(tool) @ start.part("board").pose
    tray_before = start.part("tray").pose
    finish = lift["t1"]
    end = state_at(timeline, finish)
    assert not np.allclose(end.part("board").pose[:3, 3], start.part("board").pose[:3, 3], atol=1.0)
    for t in _times(lift["t0"], finish):
        state = state_at(timeline, t)
        tool = scene.resolve_frame("robot_2.tool", state)
        assert np.allclose(np.linalg.inv(tool) @ state.part("board").pose, relative, atol=1e-3), t
        assert np.allclose(state.part("tray").pose, tray_before, atol=1e-9)


def test_every_part_is_a_named_glb_node_and_step_component(built):
    _project, report, version, _timeline = built
    gltf = GLTF2().load_binary(str(version / "scene.glb"))
    nodes = {node.name: node for node in gltf.nodes if node.name}
    for part_id in ("tray", "board"):
        assert nodes[part_id].extras["part"] is True
    assert {"tray", "board"} <= set(report["step"]["expected_names"])
    manifest = json.loads((version / "manifest.json").read_text("utf-8"))
    assert [part["id"] for part in manifest["parts"]] == ["tray", "board"]


def test_payload_counts_parts_carried_on_the_gripped_part():
    scene = SimpleNamespace(
        parts={"tray": SimpleNamespace(mass_kg=0.8), "board": SimpleNamespace(mass_kg=0.2)}
    )
    carried = {
        "nodes": {
            "tray": {"type": "pose", "attached_to": [[0.0, "conveyor_1"], [1.0, "robot_1.tool"]]},
            "board": {"type": "pose", "attached_to": [[0.0, "tray"]]},
        }
    }
    held, mass = _held_by(scene, carried, "robot_1.tool")
    assert len(held) == 1
    assert mass == pytest.approx(1.0)
    carried["nodes"]["board"]["attached_to"].append([0.5, "robot_2.tool"])
    assert _held_by(scene, carried, "robot_1.tool")[1] == pytest.approx(0.8)


def _broken(tmp_path: Path, **changes) -> Path:
    workpiece = json.loads(json.dumps(WORKPIECE))
    steps = json.loads(json.dumps(STEPS))
    if "part_id" in changes:
        workpiece["parts"][1]["id"] = changes["part_id"]
    if changes.get("cycle"):
        workpiece["parts"][0]["initial"] = {"frame": "board.top"}
    if changes.get("no_object"):
        steps[3].pop("object")
    if changes.get("unknown_object"):
        steps[3]["object"] = "lid"
    return _project(tmp_path, workpiece=workpiece, steps=steps)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"no_object": True}, "必須以 object 指定"),
        ({"unknown_object": True}, "object 不是零件"),
        ({"cycle": True}, "成環"),
        ({"part_id": "robot_2"}, "不可與模組 id 相同"),
    ],
)
def test_ambiguous_or_inconsistent_part_references_are_rejected(tmp_path, changes, message):
    project = _broken(tmp_path, **changes)
    if "part_id" in changes:
        # 零件改名後流程仍引用舊 id；只檢查 id 衝突本身
        process = load_yaml(project / "process.yaml")
        for step in process["steps"]:
            if step.get("object") == "board":
                step["object"] = changes["part_id"]
            target = step.get("target") or {}
            if str(target.get("frame", "")).startswith("board."):
                target["frame"] = target["frame"].replace("board.", f"{changes['part_id']}.", 1)
        dump_yaml(project / "process.yaml", process)
    with pytest.raises(ProjectValidationError, match=message):
        validate_project(project)
