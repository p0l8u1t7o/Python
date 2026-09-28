import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from cellforge.build.modules import build_module
from cellforge.cli import app
from cellforge.schema import VendorManifest
from cellforge.schema.models import Process
from cellforge.sim import SceneModel, build_workpiece
from cellforge.sim.engine import Simulator
from cellforge.sim.sampling import state_at, world_transforms
from cellforge.sim.scheduler import schedule_process
from cellforge.validation import validate_project
from cellforge.yamlio import dump_yaml, load_yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "getac_qc" / "handwritten"


def _cell_build(project: Path) -> dict:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "cellforge.cli",
            "build",
            "--project",
            str(project),
            "--level",
            "L0",
            "--json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout.splitlines()[-1])


def _scene(project_dir: Path):
    _project, workpiece, cell, process = validate_project(project_dir)
    manifest = VendorManifest.model_validate(
        load_yaml(project_dir / "vendor" / "manifest.yaml") or {"vendors": []}
    )
    vendor_items = {item.id: item.model_dump(mode="json") for item in manifest.vendors}
    modules = [
        build_module(instance, vendor_items)
        for machine in cell.machines
        for instance in machine.modules
    ]
    scene = SceneModel(cell, modules, build_workpiece(workpiece, process))
    return scene, process


@pytest.fixture(scope="module")
def handwritten(tmp_path_factory):
    project = tmp_path_factory.mktemp("wp2-handwritten") / "project"
    shutil.copytree(SOURCE, project, ignore=shutil.ignore_patterns("build", ".cellforge"))
    started = time.perf_counter()
    _cell_build(project)
    elapsed = time.perf_counter() - started
    timeline = json.loads((project / "build" / "timeline.json").read_text("utf-8"))
    scene, process = _scene(project)
    return project, timeline, scene, process, elapsed


def test_handwritten_first_article_motion_and_articulation(handwritten):
    _project, timeline, scene, _process, elapsed = handwritten
    assert elapsed < 60.0
    first = timeline["steps"][0]
    last = timeline["steps"][-1]
    start = state_at(timeline, first["t0"])
    finish = state_at(timeline, last["t1"])
    assert finish.workpiece_pose[0, 3] - start.workpiece_pose[0, 3] > 5000.0

    flip = next(step for step in timeline["steps"] if step["id"] == "S4.flip")
    flipped = state_at(timeline, flip["t1"])
    assert flipped.workpiece_pose[2, 2] < -0.9
    transforms = world_transforms(scene, flipped)
    assert "robot_1.tool" in transforms
    assert "workpiece.cover_lan" in transforms
    robot_joints = flipped.joints["robot_2"]
    expected_tool = scene.module_poses["robot_2"] @ scene.robots["robot_2"].chain.fk(robot_joints)
    assert np.allclose(transforms["robot_2.tool"], expected_tool)

    cover = np.asarray(timeline["nodes"]["workpiece.cover_lan"]["value_deg"])
    assert cover[0, 1] == pytest.approx(0.0)
    assert cover[:, 1].max() == pytest.approx(scene.workpiece.definition.axes[0].range_deg[1])
    assert cover[-1, 1] == pytest.approx(0.0)
    for robot in ("robot_1", "robot_2"):
        joints = np.asarray(timeline["nodes"][robot]["joints_deg"])[:, 1:]
        assert joints.shape[1] == 6
        assert np.all(np.ptp(joints, axis=0) > 1e-3)


def test_cover_edge_tracking_stays_within_five_mm(handwritten):
    _project, timeline, scene, _process, _elapsed = handwritten
    opening = next(step for step in timeline["steps"] if step["id"] == "S3.open")
    keys = timeline["nodes"]["workpiece.cover_lan"]["value_deg"]
    samples = [float(key[0]) for key in keys if opening["t0"] <= key[0] <= opening["t1"]]
    for sample_time in samples:
        state = state_at(timeline, sample_time)
        if state.axes["workpiece.cover_lan"] <= 0:
            continue
        tool = scene.resolve_frame("robot_1.tool", state)
        edge = scene.resolve_frame("workpiece.cover_lan.edge", state)
        assert np.linalg.norm(tool[:3, 3] - edge[:3, 3]) < 5.0


def test_scheduler_parallelizes_stations_but_serializes_actor(handwritten):
    _project, _timeline, scene, _process, _elapsed = handwritten
    process = Process.model_validate(
        {
            "stations": [
                {"id": "S1", "name": "起點", "modules": []},
                {"id": "S2", "name": "平行甲", "modules": ["robot_1"]},
                {"id": "S3", "name": "平行乙", "modules": ["robot_2"]},
            ],
            "steps": [
                {
                    "id": "seed",
                    "station": "S1",
                    "actor": "system",
                    "action": "wait",
                    "duration_s": 1,
                },
                {
                    "id": "a1",
                    "station": "S2",
                    "actor": "robot_1",
                    "action": "capture",
                    "duration_s": 2,
                    "requires": ["S1.done"],
                },
                {
                    "id": "a2",
                    "station": "S2",
                    "actor": "robot_1",
                    "action": "capture",
                    "duration_s": 1,
                },
                {
                    "id": "b1",
                    "station": "S3",
                    "actor": "robot_2",
                    "action": "capture",
                    "duration_s": 3,
                    "requires": ["S1.done"],
                },
            ],
            "takt": {"target_s": 10},
        }
    )
    timeline = schedule_process(process, Simulator(scene))
    steps = {step["id"]: step for step in timeline["steps"]}
    assert steps["a1"]["t0"] < steps["b1"]["t1"]
    assert steps["b1"]["t0"] < steps["a1"]["t1"]
    assert steps["a2"]["t0"] >= steps["a1"]["t1"]


def test_cyclic_requires_fails_validate_with_traditional_chinese(tmp_path):
    project = tmp_path / "cyclic"
    shutil.copytree(SOURCE, project, ignore=shutil.ignore_patterns("build", ".cellforge"))
    data = load_yaml(project / "process.yaml")
    data["steps"] = [
        {
            "id": "cycle.a",
            "station": "S1",
            "actor": "system",
            "action": "wait",
            "requires": ["cycle.b.done"],
        },
        {
            "id": "cycle.b",
            "station": "S2",
            "actor": "system",
            "action": "wait",
            "requires": ["cycle.a.done"],
        },
    ]
    dump_yaml(project / "process.yaml", data)
    result = CliRunner().invoke(app, ["validate", "--project", str(project)])
    assert result.exit_code == 2
    assert "循環" in result.output


def test_unreachable_move_records_ik_failure(handwritten):
    _project, _timeline, scene, _process, _elapsed = handwritten
    process = Process.model_validate(
        {
            "stations": [{"id": "S1", "name": "IK", "modules": ["robot_1"]}],
            "steps": [
                {
                    "id": "unreachable",
                    "station": "S1",
                    "actor": "robot_1",
                    "action": "move_to",
                    "target": {"xyz": [10000, 0, 10000], "rpy_deg": [0, 0, 0]},
                    "duration_s": 0.1,
                }
            ],
            "takt": {"target_s": 10},
        }
    )
    timeline = schedule_process(process, Simulator(scene))
    assert timeline["ik_failures"]
    failure = timeline["ik_failures"][0]
    assert failure["step_id"] == "unreachable"
    assert failure["nearest_distance_mm"] > 0


def test_legacy_sequence_api_still_builds(tmp_path):
    project = tmp_path / "legacy"
    shutil.copytree(SOURCE, project, ignore=shutil.ignore_patterns("build", ".cellforge"))
    (project / "animation" / "sequence.py").write_text(
        "from cellforge.build.seq import actuate, capture, emit, move_joint, wait_for\n\n"
        "def build():\n"
        "    move_joint('robot_1', [5, -10, 15, 20, -25, 30], 0.2, 'S3')\n"
        "    actuate('workpiece.cover_lan', 30, 0.2, 'S3', unit='deg')\n"
        "    capture('vision_fixture', 'S2', 0.1)\n"
        "    emit('legacy.done')\n"
        "    wait_for(0.1, 'S5')\n",
        encoding="utf-8",
    )
    report = _cell_build(project)
    timeline = json.loads((project / "build" / "timeline.json").read_text("utf-8"))
    assert report["duration_s"] > 0
    assert any(event["id"] == "legacy.done" for event in timeline["events"])


def _linear_process() -> Process:
    return Process.model_validate(
        {
            "stations": [{"id": "S1", "name": "直線", "modules": ["robot_1"]}],
            "steps": [
                {
                    "id": "straight",
                    "station": "S1",
                    "actor": "robot_1",
                    "action": "move_to",
                    "target": {"xyz": [400, 650, 900], "rpy_deg": [180, 0, 0]},
                    "value": {"linear": True},
                }
            ],
            "takt": {"target_s": 10},
        }
    )


def _scripted_ik(monkeypatch, simulator: Simulator, joints_at_ratio):
    """以直線進度（目標位置投影）決定回傳的關節值，模擬連續或跳解的 IK 解支。"""
    from cellforge.kinematics.ik import IKResult

    start = simulator.scene.resolve_frame("robot_1.tool", simulator.state)[:3, 3]
    calls = {"count": 0}

    def fake(step_id, actor, target):
        calls["count"] += 1
        end = np.asarray([400.0, 650.0, 900.0])
        span = end - start
        ratio = float(np.clip(np.dot(target[:3, 3] - start, span) / np.dot(span, span), 0, 1))
        return IKResult(True, joints_at_ratio(ratio), 0.0, 0.0, 0.0, 1, "IK 求解成功")

    monkeypatch.setattr(simulator, "_solve_result", fake)
    return calls


def test_linear_move_with_ik_branch_jump_stays_bounded_and_is_reported(handwritten, monkeypatch):
    from cellforge.checks.runner import _reachability
    from cellforge.sim import engine

    _project, _timeline, scene, _process, _elapsed = handwritten
    simulator = Simulator(scene)
    chain = scene.robots["robot_1"].chain
    jump = 170.0

    def branch_flip(ratio: float) -> np.ndarray:
        joints = np.zeros(len(chain.active_joints))
        joints[1] = 20.0 * ratio
        joints[0] = jump if ratio > 0.5 else 0.0
        return joints

    calls = _scripted_ik(monkeypatch, simulator, branch_flip)
    process = _linear_process()
    timeline = schedule_process(process, simulator)
    [discontinuity] = timeline["path_discontinuities"]
    assert discontinuity["step_id"] == "straight"
    assert discontinuity["joint"] == chain.joint_names[0]
    assert abs(discontinuity["jump_deg"] - jump) < 1e-9
    speeds = np.asarray([joint.max_speed for joint in chain.active_joints])
    initial = float(np.max(np.abs(branch_flip(1.0)) / (speeds * 0.5)))
    [step] = timeline["steps"]
    # 至多放大一輪就判定跳解：時長與 IK 次數都不再隨取樣無限增長。
    assert step["t1"] - step["t0"] <= initial * engine.LINEAR_DURATION_GROWTH + 1e-9
    max_samples = (initial * engine.LINEAR_DURATION_GROWTH) / engine.SAMPLE_PERIOD_S + 2
    assert calls["count"] <= 1 + 2 * max_samples
    assert step["ik"] == "failed"
    [item] = _reachability(process, timeline)
    assert item["severity"] == "red" and "跳解" in item["detail"]


def test_linear_move_on_continuous_path_still_derives_a_feasible_duration(handwritten, monkeypatch):
    _project, _timeline, scene, _process, _elapsed = handwritten
    simulator = Simulator(scene)
    chain = scene.robots["robot_1"].chain

    def smooth_but_fast_middle(ratio: float) -> np.ndarray:
        # 中段集中轉動：以端點推得的初始時長不夠，必須依關節速度拉長。
        joints = np.zeros(len(chain.active_joints))
        joints[0] = 90.0 * (ratio - np.sin(2 * np.pi * ratio) / (2 * np.pi)) * 2
        return joints

    _scripted_ik(monkeypatch, simulator, smooth_but_fast_middle)
    timeline = schedule_process(_linear_process(), simulator)
    assert timeline["path_discontinuities"] == []
    track = np.asarray(timeline["nodes"]["robot_1"]["joints_deg"], dtype=float)
    speeds = np.asarray([joint.max_speed for joint in chain.active_joints])
    elapsed = np.diff(track[:, 0])
    moving = elapsed > 1e-12
    rates = np.abs(np.diff(track[:, 1:], axis=0))[moving] / elapsed[moving, None]
    assert np.all(rates <= speeds * 0.5 * (1 + 1e-6))
    initial = float(np.max(np.abs(smooth_but_fast_middle(1.0)) / (speeds * 0.5)))
    [step] = timeline["steps"]
    assert step["t1"] - step["t0"] > initial
