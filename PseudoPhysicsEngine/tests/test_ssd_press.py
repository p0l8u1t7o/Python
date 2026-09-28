"""ACC-04：SSD USB 接頭壓合站——載盤承載 → 壓頭接近 → 受限壓合 → 撤離 → 相機取像 → 結果。

每個反例只改一個條件（壓入量、治具位置、相機支架、取像前手臂位置），斷言對應的檢查由
通過變成失敗；期望值取自範例本身（翹起角、彈簧行程、允收間隙），不寫死量測結果。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pygltflib import GLTF2

from cellforge.build.pipeline import build_project
from cellforge.yamlio import dump_yaml, load_yaml

SOURCE = Path(__file__).resolve().parents[1] / "examples" / "ssd_press" / "handwritten"
ROWS = {"A": [f"usb_A{i}" for i in range(1, 9)], "B": [f"usb_B{i}" for i in range(1, 9)]}


def _copy(root: Path, name: str) -> Path:
    project = root / name
    shutil.copytree(
        SOURCE, project, ignore=shutil.ignore_patterns("__pycache__", ".cellforge", "build")
    )
    return project


def _build(project: Path, level: str) -> dict:
    report = build_project(project, level)
    version = project / ".cellforge" / report["version_id"]
    timeline = json.loads((version / "timeline.json").read_text("utf-8"))
    checks = json.loads((version / "checks.json").read_text("utf-8")) if level == "L1" else None
    return {
        "project": project,
        "report": report,
        "version": version,
        "timeline": timeline,
        "checks": checks,
    }


def _results(build: dict) -> dict[str, dict]:
    return {item["step_id"]: item for item in build["timeline"]["action_results"]}


def _edit(path: Path, change) -> None:
    data = load_yaml(path)
    change(data)
    dump_yaml(path, data)


def _step(process: dict, step_id: str) -> dict:
    return next(step for step in process["steps"] if step["id"] == step_id)


@pytest.fixture(scope="module")
def nominal(tmp_path_factory):
    return _build(_copy(tmp_path_factory.mktemp("ssd"), "nominal"), "L1")


@pytest.fixture(scope="module")
def workpiece():
    return {part["id"]: part for part in load_yaml(SOURCE / "workpiece.yaml")["parts"]}


def test_nominal_line_completes_every_contract_without_red(nominal):
    results = _results(nominal)
    assert results and all(item["status"] == "ok" for item in results.values())
    assert nominal["timeline"]["ik_failures"] == []
    assert nominal["checks"]["summary"]["red"] == 0
    # 載盤經輸送段送到壓合位，連板與接頭沿持有鏈一起到位
    holders = {key[1] for key in nominal["timeline"]["nodes"]["tray"]["attached_to"]}
    assert "conveyor_1" in holders
    assert {key[1] for key in nominal["timeline"]["nodes"]["usb_A1"]["attached_to"]} == {"panel"}


def test_pressing_flattens_lifted_connectors_within_the_spring_stroke(nominal, workpiece):
    results = _results(nominal)
    process = load_yaml(SOURCE / "process.yaml")
    for step_id, row in (("S2.press_A", "A"), ("S2.press_B", "B")):
        spring = _step(process, step_id)["press"]["spring_mm"]
        details = results[step_id]["details"]["objects"]
        for part_id in ROWS[row]:
            before = workpiece[part_id]["state"]["tilt"]
            assert details[part_id]["tilt_before_deg"] == pytest.approx(before)
            assert details[part_id]["tilt_min_deg"] == pytest.approx(0.0, abs=1e-6)
            assert 0.0 < details[part_id]["spring_compression_mm"] <= spring
    # 翹起的接頭在時間軸上確實被壓平（壓合前後的軸值改變）
    track = nominal["timeline"]["nodes"]["usb_A2.tilt"]["value_deg"]
    assert track[0][1] > 0 and track[-1][1] == pytest.approx(0.0, abs=1e-6)


def test_rebound_is_found_by_the_camera_and_cleared_by_the_repress(nominal, workpiece):
    results = _results(nominal)
    rebound = workpiece["usb_A6"]["params"]["rebound_deg"]
    first = results["S2.press_A"]["details"]["objects"]["usb_A6"]
    assert first["tilt_after_deg"] == pytest.approx(rebound)
    process = load_yaml(SOURCE / "process.yaml")
    limit = _step(process, "S3.inspect_A5_8")["inspect"]["max_gap_mm"]
    seen = results["S3.inspect_A5_8"]["details"]["rois"]
    assert seen["usb_A6.roi"]["judgement"] == "NG" and seen["usb_A6.roi"]["gap_mm"] > limit
    assert all(seen[f"usb_A{i}.roi"]["judgement"] == "OK" for i in (5, 7, 8))
    rechecked = results["S4.recheck_A5_8"]["details"]["rois"]
    assert all(item["judgement"] == "OK" for item in rechecked.values())
    vision = [item for item in nominal["checks"]["items"] if item["type"] == "vision"]
    a6 = [item for item in vision if item["objects"] == ["usb_A6"]]
    assert {item["severity"] for item in a6} == {"yellow", "green"}
    assert all(item["severity"] != "red" for item in vision)


def test_camera_sees_every_roi_and_press_contacts_stay_declared(nominal):
    for step_id, result in _results(nominal).items():
        if result["action"] != "inspect":
            continue
        for roi, evaluation in result["details"]["rois"].items():
            assert evaluation["issues"] == [], (step_id, roi)
    contacts = [item for item in nominal["checks"]["items"] if item.get("contact_id")]
    assert {item["contact_id"] for item in contacts} == {"C-press-A", "C-press-B"}
    assert all(item["severity"] == "green" for item in contacts)


def test_pcb_leads_press_pads_and_cameras_are_identifiable_nodes(nominal):
    gltf = GLTF2().load_binary(str(nominal["version"] / "scene.glb"))
    nodes = {node.name: node for node in gltf.nodes if node.name}
    for part_id in ("tray", "panel", *ROWS["A"], *ROWS["B"]):
        assert nodes[part_id].extras["part"] is True
    # GLB 依 link 合併網格；逐支銀腳與逐個壓墊的具名幾何在 STEP 元件樹。
    step = json.loads((nominal["version"] / "step_validation.json").read_text("utf-8"))

    def names(components, path=()):
        for component in components:
            yield (*path, component["part_name"])
            yield from names(component["children"], (*path, component["part_name"]))

    paths = set(names(step["components"]))
    for part_id in (*ROWS["A"], *ROWS["B"]):
        assert {(part_id, f"lead_{index}") for index in range(1, 10)} <= paths
        assert (part_id, "shell") in paths
    assert {("panel", f"board_{row}{index}") for row in "AB" for index in range(1, 9)} <= paths
    robot = {path[-1] for path in paths if path[0] == "robot_1"}
    assert {f"tool_pad_{index}" for index in range(1, 9)} <= robot
    for camera in ("robot_1.camera", "global_camera.optical"):
        assert nodes[camera].extras["camera"]["vfov_deg"] > 0


def test_overpress_is_caught_by_the_press_contract_and_the_declared_contact(tmp_path, nominal):
    project = _copy(tmp_path, "overpress")
    process = load_yaml(project / "process.yaml")
    spring = _step(process, "S2.press_A")["press"]["spring_mm"]

    def deeper(data):
        _step(data, "S2.press_A")["path"]["depth_mm"] = spring * 1.5

    _edit(project / "process.yaml", deeper)
    build = _build(project, "L1")
    press = _results(build)["S2.press_A"]
    assert press["status"] == "failed" and press["reason_code"] == "OVERTRAVEL"
    red = [
        item
        for item in build["checks"]["items"]
        if item.get("contact_id") == "C-press-A" and item["severity"] == "red"
    ]
    assert red and all("超過容差" in item["detail"] for item in red)
    assert _results(nominal)["S2.press_A"]["status"] == "ok"


def test_wrong_fixture_misses_the_press_faces_and_the_camera_rois(tmp_path):
    project = _copy(tmp_path, "wrong_fixture")

    def shifted(data):
        panel = next(part for part in data["parts"] if part["id"] == "panel")
        panel["initial"]["offset"] = {"xyz": [0, 8, 0], "rpy_deg": [0, 0, 0]}

    _edit(project / "workpiece.yaml", shifted)
    results = _results(_build(project, "L0"))
    assert results["S2.press_A"]["reason_code"] == "OFF_TARGET"
    assert results["S2.press_B"]["reason_code"] == "OFF_TARGET"
    assert any(
        item["status"] == "failed" for item in results.values() if item["action"] == "inspect"
    )


def test_raised_camera_bracket_puts_the_leads_out_of_focus(tmp_path):
    project = _copy(tmp_path, "raised_camera")

    def raised(data):
        robot = next(
            module
            for machine in data["machines"]
            for module in machine["modules"]
            if module["id"] == "robot_1"
        )
        robot["params"]["tool"]["params"] = {"camera_raise_mm": 40}

    _edit(project / "cell.yaml", raised)
    results = _results(_build(project, "L0"))
    inspections = [item for item in results.values() if item["step_id"].startswith("S3.")]
    assert inspections and all(item["reason_code"] == "OUT_OF_FOCUS" for item in inspections)
    presses = [item for item in results.values() if item["action"] == "press"]
    assert all(item["status"] == "ok" for item in presses)


def test_robot_left_in_front_of_the_global_camera_occludes_the_panel(tmp_path):
    project = _copy(tmp_path, "occluded")

    def no_park(data):
        data["steps"] = [step for step in data["steps"] if step["id"] != "S0.park"]

    _edit(project / "process.yaml", no_park)
    locate = _results(_build(project, "L0"))["S1.locate"]
    assert locate["status"] == "failed"
    assert "OCCLUDED" in locate["details"]["rois"]["panel.roi_panel"]["issues"]
    assert locate["details"]["rois"]["panel.roi_panel"]["occluded_by"].startswith("robot_1")
