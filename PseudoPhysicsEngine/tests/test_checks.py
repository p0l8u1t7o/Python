from __future__ import annotations

from typing import Any

from cellforge.build.modules import build_module
from cellforge.checks import run_checks
from cellforge.schema import Cell, Process, Workpiece
from cellforge.sim import SceneModel, build_workpiece
from cellforge.sim.engine import Simulator
from cellforge.sim.scheduler import schedule_process


def _workpiece(mass_kg: float = 1.0) -> Workpiece:
    return Workpiece.model_validate(
        {
            "units": "mm",
            "skus": [
                {
                    "id": "part",
                    "size": {"x": 20, "y": 20, "z": 20},
                    "mass_kg": mass_kg,
                }
            ],
        }
    )


def _process(steps: list[dict[str, Any]], modules: list[str]) -> Process:
    return Process.model_validate(
        {
            "stations": [{"id": "S1", "name": "測試", "modules": modules}],
            "steps": steps,
            "takt": {"target_s": 60, "parallel_workpieces": 1},
            "workpiece_sku": "part",
        }
    )


def _scene(cell: Cell, workpiece: Workpiece, process: Process) -> SceneModel:
    modules = [
        build_module(instance, {}) for machine in cell.machines for instance in machine.modules
    ]
    return SceneModel(cell, modules, build_workpiece(workpiece, process))


def _timeline(nodes: dict[str, Any], *, failure: dict[str, Any] | None = None):
    return {
        "fps": 50,
        "duration_s": 0.0,
        "stations": [{"id": "S1", "t0": 0.0, "t1": 0.0}],
        "steps": [],
        "nodes": {
            **nodes,
            "workpiece": {
                "type": "pose",
                "pose_quat": [[0.0, 10_000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]],
                "attached_to": [[0.0, None]],
            },
        },
        "events": [],
        "ik_failures": [failure] if failure else [],
    }


def _box_case(spacing_mm: float):
    cell = Cell.model_validate(
        {
            "units": "mm",
            "plant_frame": {},
            "machines": [
                {
                    "id": "line",
                    "modules": [
                        {
                            "id": "box_a",
                            "part": "library/box.py",
                            "params": {"size": [100, 100, 100]},
                        },
                        {
                            "id": "box_b",
                            "part": "library/box.py",
                            "params": {"size": [100, 100, 100]},
                            "pose": {"xyz": [spacing_mm, 0, 0]},
                        },
                    ],
                }
            ],
        }
    )
    workpiece = _workpiece()
    process = _process([], ["box_a", "box_b"])
    report = run_checks(
        cell, workpiece, process, _timeline({}), 1, scene=_scene(cell, workpiece, process)
    )
    return next(
        item
        for item in report["items"]
        if item["type"] == "interference" and set(item["objects"]) == {"box_a", "box_b"}
    )


def test_static_collision_and_clearance_are_computed_from_geometry():
    box_size = 100.0
    overlap = 5.0
    collision = _box_case(box_size - overlap)
    clearance = _box_case(box_size + overlap)
    assert collision["severity"] == "red"
    assert collision["min_dist_mm"] < 0
    assert clearance["severity"] == "yellow"
    assert clearance["min_dist_mm"] > 0


def _support_case(*, workpiece_z: float, transfer: bool):
    spacing = 100.0
    cell = Cell.model_validate(
        {
            "units": "mm",
            "plant_frame": {},
            "machines": [
                {
                    "id": "line",
                    "modules": [
                        {
                            "id": "support_a",
                            "part": "library/box.py",
                            "params": {"size": [spacing, spacing, spacing]},
                        },
                        {
                            "id": "support_b",
                            "part": "library/box.py",
                            "params": {"size": [spacing, spacing, spacing]},
                            "pose": {"xyz": [spacing, 0, 0]},
                        },
                    ],
                }
            ],
        }
    )
    steps = (
        [
            {
                "id": "S1.handoff",
                "station": "S1",
                "actor": "support_a",
                "action": "transfer",
                "target": {"frame": "support_b.top"},
                "duration_s": 1.0,
            }
        ]
        if transfer
        else []
    )
    process = _process(steps, ["support_a", "support_b"])
    workpiece = _workpiece()
    scene = _scene(cell, workpiece, process)
    end_x = spacing if transfer else 0.0
    duration = 1.0 if transfer else 0.0
    timeline = {
        "fps": 50,
        "duration_s": duration,
        "stations": [{"id": "S1", "t0": 0.0, "t1": duration}],
        "steps": (
            [
                {
                    "id": "S1.handoff",
                    "station": "S1",
                    "actor": "support_a",
                    "action": "transfer",
                    "t0": 0.0,
                    "t1": 1.0,
                }
            ]
            if transfer
            else []
        ),
        "nodes": {
            "workpiece": {
                "type": "pose",
                "pose_quat": [
                    [0.0, 0.0, 0.0, workpiece_z, 0.0, 0.0, 0.0, 1.0],
                    [duration, end_x, 0.0, workpiece_z, 0.0, 0.0, 0.0, 1.0],
                ],
                "attached_to": (
                    [[0.0, "support_a"], [duration, "support_b"]]
                    if transfer
                    else [[0.0, "support_a"]]
                ),
            }
        },
        "events": [],
        "ik_failures": [],
    }
    return run_checks(cell, workpiece, process, timeline, 1, scene=scene)


def test_handoff_allows_contact_with_departing_and_arriving_supports():
    support_height = 100.0
    workpiece_z = support_height / 2
    report = _support_case(workpiece_z=workpiece_z, transfer=True)
    assert not any(
        item["type"] == "interference"
        and "workpiece" in item["objects"]
        and ({"support_a", "support_b"} & set(item["objects"]))
        for item in report["items"]
    )


def test_support_penetration_beyond_tolerance_is_red():
    support_height = 100.0
    penetration = 3.0
    report = _support_case(workpiece_z=support_height / 2 - penetration, transfer=False)
    item = next(
        item
        for item in report["items"]
        if item["type"] == "interference" and set(item["objects"]) == {"support_a", "workpiece"}
    )
    assert item["severity"] == "red"
    assert item["min_dist_mm"] <= -penetration


def _robot_case(*, mass_kg: float = 1.0):
    cell = Cell.model_validate(
        {
            "units": "mm",
            "plant_frame": {},
            "machines": [
                {
                    "id": "line",
                    "modules": [
                        {
                            "id": "robot_test",
                            "part": "library/robot_stub.py",
                            "params": {"reach_mm": 905, "payload_kg": 7},
                        }
                    ],
                }
            ],
        }
    )
    process = _process(
        [
            {
                "id": "S1.move",
                "station": "S1",
                "actor": "robot_test",
                "action": "move_to",
                "target": {"xyz": [10_000, 0, 0]},
            }
        ],
        ["robot_test"],
    )
    workpiece = _workpiece(mass_kg)
    scene = _scene(cell, workpiece, process)
    return cell, workpiece, process, scene


def test_unreachable_target_and_near_limit_joint_are_reported():
    cell, workpiece, process, scene = _robot_case()
    high = float(scene.robots["robot_test"].chain.limits[0, 1])
    joint_value = high * 0.95
    timeline = schedule_process(process, Simulator(scene))
    assert timeline["ik_failures"]
    timeline["nodes"]["workpiece"]["pose_quat"] = [[0.0, 10_000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]]
    joints = timeline["nodes"]["robot_test"]["joints_deg"][-1].copy()
    joints[0] = timeline["duration_s"]
    joints[1] = joint_value
    timeline["nodes"]["robot_test"]["joints_deg"].append(joints)
    report = run_checks(cell, workpiece, process, timeline, 1, scene=scene)
    assert any(
        item["type"] == "reachability" and item["severity"] == "red" for item in report["items"]
    )
    joint = next(item for item in report["items"] if item["objects"] == ["robot_test.j1"])
    assert joint["severity"] in {"yellow", "red"}


def test_payload_overload_is_reported_while_gripped():
    cell, workpiece, process, scene = _robot_case(mass_kg=8.0)
    timeline = _timeline(
        {
            "robot_test": {
                "type": "robot",
                "joint_names": list(scene.robots["robot_test"].chain.joint_names),
                "joints_deg": [[0.0, 0, 0, 0, 0, 0, 0]],
            }
        }
    )
    timeline["nodes"]["workpiece"]["attached_to"] = [[0.0, "robot_test.tool"]]
    report = run_checks(cell, workpiece, process, timeline, 1, scene=scene)
    assert any(
        item["type"] == "hardware"
        and item["objects"] == ["robot_test"]
        and item["severity"] == "red"
        for item in report["items"]
    )
