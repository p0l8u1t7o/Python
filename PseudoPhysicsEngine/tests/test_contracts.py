"""DEV-008：取料／放置／插入動作契約與合法接觸宣告。

期望值取自時間軸本身（持有者變化、動作結果、碰撞項目），不寫死位置、時間或距離。
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from cellforge.build.pipeline import build_project
from cellforge.checks.runner import _process_contracts
from cellforge.project import create_project
from cellforge.sim.sampling import state_at
from cellforge.yamlio import dump_yaml

PREPARE = {
    "id": "S2.prepare",
    "station": "S2",
    "actor": "robot_2",
    "action": "move_joint",
    "value": {"joints_deg": [-14, -20, 32, -18, 24, -35]},
    "duration_s": 1.5,
}
WORKPIECE = {
    "units": "mm",
    "skus": [
        {"id": "tray", "size": {"x": 320, "y": 240, "z": 20}, "mass_kg": 0.8},
        {"id": "board", "size": {"x": 200, "y": 150, "z": 30}, "mass_kg": 0.2},
        {"id": "shim", "size": {"x": 40, "y": 40, "z": 2}, "mass_kg": 0.01},
    ],
    "parts": [
        {"id": "tray", "sku": "tray", "initial": {"frame": "vision_fixture.top"}},
        {"id": "board", "sku": "board", "initial": {"frame": "tray.top"}},
    ],
}


def _pick(step_id: str = "S2.pick", **extra) -> dict:
    return {
        "id": step_id,
        "station": "S2",
        "actor": "robot_2",
        "action": "pick",
        "object": "board",
        "target": {"frame": "board.left", "offset": {"xyz": [0, 0, 50]}},
        "path": {"approach_mm": 40},
        **extra,
    }


def _place(step_id: str = "S2.place", **extra) -> dict:
    return {
        "id": step_id,
        "station": "S2",
        "actor": "robot_2",
        "action": "place",
        "object": "board",
        "target": {"frame": "tray.top"},
        "path": {"approach_mm": 40},
        **extra,
    }


def _build(root: Path, name: str, steps: list, *, contacts=None, extra_parts=(), level="L0"):
    project = create_project(
        root / name, {"name": name, "created": date.today().isoformat()}, seed_example="getac_qc"
    )
    workpiece = copy.deepcopy(WORKPIECE)
    workpiece["parts"].extend(extra_parts)
    dump_yaml(project / "workpiece.yaml", workpiece)
    dump_yaml(
        project / "process.yaml",
        {
            "stations": [{"id": "S2", "name": "取放", "modules": ["robot_2", "vision_fixture"]}],
            "steps": [PREPARE, *steps],
            "takt": {"target_s": 60},
            "contacts": contacts or [],
        },
    )
    report = build_project(project, level)
    version = project / ".cellforge" / report["version_id"]
    timeline = json.loads((version / "timeline.json").read_text("utf-8"))
    checks = json.loads((version / "checks.json").read_text("utf-8")) if level == "L1" else None
    return timeline, checks


def _result(timeline: dict, step_id: str) -> dict:
    return next(item for item in timeline["action_results"] if item["step_id"] == step_id)


def test_pick_and_place_hand_the_part_over_and_report_completion(tmp_path):
    timeline, _ = _build(tmp_path, "ok", [_pick(), _place()])
    pick, place = _result(timeline, "S2.pick"), _result(timeline, "S2.place")
    assert pick["status"] == place["status"] == "ok"
    assert pick["t1"] > pick["t0"] and place["t1"] > place["t0"]
    holders = [key[1] for key in timeline["nodes"]["board"]["attached_to"]]
    assert holders[0] == "tray" and "robot_2.tool" in holders and holders[-1] == "tray"
    during = state_at(timeline, (pick["t1"] + place["t0"]) / 2)
    assert during.part("board").holder == "robot_2.tool"
    assert state_at(timeline, place["t1"]).part("board").holder == "tray"
    assert place["details"]["position_error_mm"] <= 1.0
    items = _process_contracts(timeline)
    assert [item["severity"] for item in items] == ["green", "green"]


@pytest.mark.parametrize(
    ("name", "steps", "extra_parts", "failing", "code"),
    [
        ("not_held", [_place("S2.place_first")], (), "S2.place_first", "NOT_HELD"),
        (
            "occupied",
            [_pick(), _pick("S2.pick_again", object="tray", target={"frame": "tray.left"})],
            (),
            "S2.pick_again",
            "TOOL_OCCUPIED",
        ),
        ("wrong_tool", [_pick(tool="library/force_eoat.py")], (), "S2.pick", "WRONG_TOOL"),
        (
            "target_taken",
            [_pick(), _place()],
            ({"id": "shim", "sku": "shim", "initial": {"frame": "tray.top"}},),
            "S2.place",
            "TARGET_OCCUPIED",
        ),
        (
            "unreachable",
            [_pick(target={"frame": "conveyor_2.end"})],
            (),
            "S2.pick",
            "UNREACHABLE",
        ),
    ],
)
def test_failed_preconditions_are_reported_with_a_reason(
    tmp_path, name, steps, extra_parts, failing, code
):
    timeline, _ = _build(tmp_path, name, steps, extra_parts=extra_parts)
    result = _result(timeline, failing)
    assert result["status"] == "failed"
    assert result["reason_code"] == code
    assert result["reason"]
    if code != "UNREACHABLE":
        # 前置條件不成立時不移動
        assert result["t1"] == result["t0"]
    item = next(item for item in _process_contracts(timeline) if item["detail"].startswith(failing))
    assert item["severity"] == "red" and code in item["detail"]


def _push(step_id: str, depth: float, *, x: float = 0.0) -> dict:
    return {
        "id": step_id,
        "station": "S2",
        "actor": "robot_2",
        "action": "move_to",
        "target": {"frame": "board.left", "offset": {"xyz": [x, 0, -depth]}},
        "value": {"linear": True},
        "duration_s": 0.6,
    }


def _retreat(step_id: str) -> dict:
    return {
        "id": step_id,
        "station": "S2",
        "actor": "robot_2",
        "action": "move_to",
        "target": {"frame": "board.left", "offset": {"xyz": [0, 0, 60]}},
        "value": {"linear": True},
        "duration_s": 0.6,
    }


PUSH_STEPS = [_retreat("S2.approach"), _push("S2.push", 2.0), _retreat("S2.back")]


def _contact(**changes) -> dict:
    contact = {
        "id": "C-push",
        "pair": ["robot_2.tool", "board"],
        "window": ["S2.push"],
        "tolerance_mm": 3.0,
        "region": {"frame": "board.left", "size_mm": [30, 30]},
        "direction": [0, 0, -1],
    }
    contact.update(changes)
    return contact


def _pair_items(checks: dict) -> list[dict]:
    return [
        item
        for item in checks["items"]
        if item["type"] == "interference"
        and any(name.startswith("robot_2.tool") for name in item["objects"])
        and "board" in item["objects"]
    ]


@pytest.fixture(scope="module")
def contact_builds(tmp_path_factory):
    root = tmp_path_factory.mktemp("dev008_contacts")
    again = [_push("S2.push_again", 2.0), _retreat("S2.back_again")]
    return {
        "declared": _build(
            root, "declared", [*PUSH_STEPS, *again], contacts=[_contact()], level="L1"
        )[1],
        "undeclared": _build(root, "undeclared", PUSH_STEPS, level="L1")[1],
        "tight": _build(
            root, "tight", PUSH_STEPS, contacts=[_contact(tolerance_mm=0.5)], level="L1"
        )[1],
        "direction": _build(
            root, "direction", PUSH_STEPS, contacts=[_contact(direction=[1, 0, 0])], level="L1"
        )[1],
        "region": _build(
            root,
            "region",
            [_retreat("S2.approach"), _push("S2.push", 2.0, x=40.0), _retreat("S2.back")],
            contacts=[_contact()],
            level="L1",
        )[1],
    }


def test_declared_contact_inside_its_window_is_allowed_but_the_same_contact_later_is_not(
    contact_builds,
):
    items = _pair_items(contact_builds["declared"])
    declared = [item for item in items if item.get("contact_id") == "C-push"]
    assert declared and all(item["severity"] == "green" for item in declared)
    later = [item for item in items if item.get("contact_id") is None]
    assert any(item["severity"] == "red" for item in later)
    assert min(item["t"] for item in later) > max(item["t"] for item in declared)


def test_without_declaration_the_push_is_an_interference(contact_builds):
    items = _pair_items(contact_builds["undeclared"])
    assert any(item["severity"] == "red" and item.get("contact_id") is None for item in items)


@pytest.mark.parametrize(
    ("build", "phrase"),
    [("tight", "超過容差"), ("direction", "接近方向"), ("region", "不在宣告區域")],
)
def test_contact_outside_its_declaration_is_red_with_the_reason(contact_builds, build, phrase):
    declared = [
        item for item in _pair_items(contact_builds[build]) if item.get("contact_id") == "C-push"
    ]
    assert declared
    assert any(item["severity"] == "red" and phrase in item["detail"] for item in declared)
