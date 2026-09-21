import xml.etree.ElementTree as ET

import numpy as np

from cellforge.kinematics import Chain, make_stub_chain, solve_ik, transform_error
from cellforge.kinematics.stub import DEFAULT_JOINT_LIMITS_DEG, write_stub_urdf
from cellforge.schema import ModuleDef
from library import box, camera_bracket, conveyor, flip_fixture, lift_rack


def test_fk_to_ik_recovers_fifty_random_reachable_poses_within_limits():
    chain = make_stub_chain()
    rng = np.random.default_rng(20260914)
    limits = chain.limits
    for joints in rng.uniform(limits[:, 0], limits[:, 1], size=(50, 6)):
        target = chain.fk(joints)
        result = solve_ik(chain, target)
        position_error, orientation_error = transform_error(chain.fk(result.joints), target)
        assert result.success, result.message
        assert position_error < 0.5
        assert orientation_error < 0.5
        assert np.all(result.joints >= limits[:, 0] - 1e-9)
        assert np.all(result.joints <= limits[:, 1] + 1e-9)


def test_unreachable_target_returns_bounded_nearest_pose_and_positive_error():
    chain = make_stub_chain()
    target = np.eye(4)
    target[:3, 3] = [chain.fk(np.zeros(6))[0, 3] + 10 * 905, 0, 0]
    result = solve_ik(chain, target)
    assert result.success is False
    assert result.nearest_distance_mm > 0
    assert np.all(result.joints >= chain.limits[:, 0] - 1e-9)
    assert np.all(result.joints <= chain.limits[:, 1] + 1e-9)


def test_module_axis_legacy_syntax_gets_articulated_defaults():
    definition = ModuleDef(
        id="legacy",
        axes=[{"id": "spin", "type": "revolute", "range_deg": [-90, 90]}],
    )
    axis = definition.axes[0]
    assert axis.parent == "base"
    assert axis.child == "spin"
    assert axis.origin.xyz == (0, 0, 0)
    assert axis.axis == (0, 0, 1)


def test_library_modules_publish_required_dynamic_frames_and_links():
    conveyor_definition = conveyor.module_definition(
        {"length_mm": 1300, "height_mm": 760, "speed_mm_s": 300}
    )
    assert {"start", "end", "stop"} <= conveyor_definition.frames.keys()
    assert conveyor_definition.frames["start"].xyz[0] == -500
    assert conveyor_definition.frames["end"].xyz[0] == 500
    assert conveyor_definition.axes[0].max_speed_mm_s == 300

    rack_definition = lift_rack.module_definition({"levels": 6, "pitch_mm": 80})
    assert {*(f"slot_{index}" for index in range(6)), "top"} <= rack_definition.frames.keys()
    assert rack_definition.axes[0].child == "lift"
    assert box.module_definition({"size": [900, 700, 850]}).frames["top"].xyz[2] == 425
    assert flip_fixture.MODULE.axes[0].child == "nest"
    camera_definition = camera_bracket.module_definition({"tilt_deg": 0})
    assert camera_definition.frames["optical"].rpy_deg == (180, 0, 0)


def test_stub_urdf_has_dimensioned_metre_origins_axes_and_manifest_limits(tmp_path):
    path = tmp_path / "stub.urdf"
    limits = write_stub_urdf(path, name="stub", reach_mm=1000, payload_kg=8)
    root = ET.parse(path).getroot()
    joints = {joint.get("name"): joint for joint in root.findall("joint")}
    assert joints["j2"].find("origin").get("xyz") == "0 0 0.43"
    assert joints["j3"].find("origin").get("xyz") == "0 0 0.5"
    assert joints["j4"].find("origin").get("xyz") == "0.25 0 0"
    assert [joints[f"j{i}"].find("axis").get("xyz") for i in range(1, 7)] == [
        "0 0 1",
        "0 1 0",
        "0 1 0",
        "1 0 0",
        "0 1 0",
        "1 0 0",
    ]
    assert limits["joints_deg"] == [list(pair) for pair in DEFAULT_JOINT_LIMITS_DEG]
    loaded = Chain.from_urdf(path, tip_link="tool")
    assert np.allclose(loaded.fk(np.zeros(6)), make_stub_chain(1000, 8).fk(np.zeros(6)))
