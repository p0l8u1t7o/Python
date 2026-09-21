from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from cellforge.build.transforms import matrix_from_pose
from cellforge.kinematics import Chain
from cellforge.kinematics.stub import write_stub_urdf
from cellforge.part_catalog import load_library_catalog
from cellforge.part_check import _default_params, _parts, check_module
from library import (
    camera_bracket,
    flip_fixture,
    force_eoat,
    light_bar,
    light_ring,
    robot_stub,
)

UPGRADED_MODULES = (
    robot_stub,
    force_eoat,
    flip_fixture,
    camera_bracket,
    light_ring,
    light_bar,
)


def _geometry_tolerance(parts) -> float:
    scale = max(
        dimension
        for part in parts
        for dimension in (
            part.shape.BoundingBox().xlen,
            part.shape.BoundingBox().ylen,
            part.shape.BoundingBox().zlen,
        )
    )
    return scale * math.sqrt(math.ulp(1.0))


def _bounds(parts) -> tuple[float, float, float, float, float, float]:
    boxes = [part.shape.BoundingBox() for part in parts]
    return (
        min(box.xmin for box in boxes),
        max(box.xmax for box in boxes),
        min(box.ymin for box in boxes),
        max(box.ymax for box in boxes),
        min(box.zmin for box in boxes),
        max(box.zmax for box in boxes),
    )


def _assert_transforms_close(actual: np.ndarray, expected: np.ndarray) -> None:
    scale = max(float(np.linalg.norm(actual)), float(np.linalg.norm(expected)), 1.0)
    tolerance = scale * math.sqrt(math.ulp(1.0))
    np.testing.assert_allclose(actual, expected, rtol=0, atol=tolerance)


@pytest.mark.parametrize("module", UPGRADED_MODULES)
def test_upgraded_dynamic_and_vision_module_has_no_failure_or_warning(module):
    result = check_module(module)
    assert not [item for item in result.items if item.severity in {"fail", "warn"}]


@pytest.mark.parametrize("module", UPGRADED_MODULES)
def test_every_numeric_parameter_bound_builds(module):
    schema = module.MODULE.params_schema
    defaults = _default_params(module.MODULE)
    numeric = {
        name: parameter
        for name, parameter in schema["properties"].items()
        if parameter.get("type") in {"number", "integer"}
    }
    assert numeric
    assert all("minimum" in parameter and "maximum" in parameter for parameter in numeric.values())
    for name, parameter in numeric.items():
        for bound in ("minimum", "maximum"):
            module.build({**defaults, name: parameter[bound]})


def test_robot_stub_chain_and_tcp_match_the_canonical_urdf_at_several_poses(tmp_path):
    params = _default_params(robot_stub.MODULE)
    module_chain = robot_stub.chain_from_params(params)
    urdf_path = tmp_path / "robot_stub.urdf"
    write_stub_urdf(
        urdf_path,
        name="robot_stub_reference",
        reach_mm=params["reach_mm"],
        payload_kg=params["payload_kg"],
    )
    urdf_chain = Chain.from_urdf(urdf_path, tip_link="tool")
    limits = module_chain.limits
    configurations = (
        np.zeros(len(module_chain.active_joints)),
        limits.mean(axis=1),
        limits[:, 0],
        limits[:, 1],
    )
    for joints in configurations:
        module_transforms = module_chain.link_transforms(joints)
        urdf_transforms = urdf_chain.link_transforms(joints)
        assert module_transforms.keys() == urdf_transforms.keys()
        for link in module_transforms:
            _assert_transforms_close(module_transforms[link], urdf_transforms[link])
        _assert_transforms_close(module_chain.fk(joints), urdf_chain.fk(joints))

    definition = robot_stub.module_definition(params)
    tcp = definition.frames["tool"]
    _assert_transforms_close(
        matrix_from_pose(tcp.xyz, tcp.rpy_deg),
        module_chain.fk(np.zeros(len(module_chain.active_joints))),
    )
    assert [axis.model_dump() for axis in definition.axes] == [
        {
            "id": joint.id,
            "type": joint.type,
            "parent": joint.parent,
            "child": joint.child,
            "origin": {"xyz": joint.origin_xyz, "rpy_deg": joint.origin_rpy_deg},
            "axis": joint.axis,
            "range_deg": joint.limit,
            "range_mm": None,
            "max_speed_dps": joint.max_speed,
            "max_speed_mm_s": None,
        }
        for joint in module_chain.active_joints
    ]


def test_robot_shell_preserves_link_names_and_adds_a_detailed_flange():
    parts = _parts(robot_stub.build(_default_params(robot_stub.MODULE)))
    by_name = {part.name: part for part in parts}
    expected_links = {*(f"link{index}" for index in range(len(robot_stub.MODULE.axes) + 1)), "tool"}
    assert set(by_name) == expected_links
    assert len(by_name["link6"].shape.Faces()) > len(by_name["tool"].shape.Faces())


def test_force_eoat_tip_frame_is_on_the_rounded_lever_tip():
    params = _default_params(force_eoat.MODULE)
    definition = force_eoat.module_definition(params)
    parts = _parts(force_eoat.build(params))
    by_name = {part.name: part for part in parts}
    tolerance = _geometry_tolerance(parts)
    assert {"flange_adapter", "force_sensor", "cover_lever", "rounded_tip"} <= by_name.keys()
    assert definition.frames["tip"] == definition.frames["tool_center_point"]
    assert math.isclose(
        definition.frames["tip"].xyz[2],
        by_name["rounded_tip"].shape.BoundingBox().zmax,
        abs_tol=tolerance,
    )


def test_flip_fixture_mechanism_stays_inside_its_declared_footprint():
    params = _default_params(flip_fixture.MODULE)
    definition = flip_fixture.module_definition(params)
    parts = _parts(flip_fixture.build(params))
    names = {part.name for part in parts}
    assert {"rotary_shaft", "drive_cylinder", "clamp_arm_left", "clamp_arm_right"} <= names
    axis = definition.axes[0]
    assert axis.range_deg == (0, 180)
    tolerance = _geometry_tolerance(parts)
    xmin, xmax, ymin, ymax, zmin, zmax = _bounds(parts)
    assert xmax - xmin <= params["width_mm"] + tolerance
    assert ymax - ymin <= params["depth_mm"] + tolerance
    assert zmin >= -tolerance
    assert zmax <= params["height_mm"] + tolerance


@pytest.mark.parametrize(
    ("module", "required_parts", "required_frames"),
    (
        (camera_bracket, {"vertical_post", "cross_beam", "camera_seat"}, {"mount", "optical"}),
        (light_ring, {"ring_housing", "annular_diffuser"}, {"mount", "emit"}),
        (light_bar, {"bar_housing", "linear_diffuser"}, {"mount", "emit"}),
    ),
)
def test_split_vision_modules_have_independent_structure(module, required_parts, required_frames):
    params = _default_params(module.MODULE)
    definition = module.module_definition(params)
    assert required_parts <= {part.name for part in _parts(module.build(params))}
    assert required_frames <= definition.frames.keys()


def test_upgraded_and_split_modules_are_production_catalog_entries():
    root = Path(__file__).resolve().parents[1]
    entries = {entry["id"]: entry for entry in load_library_catalog(root)}
    assert all(entries[module.MODULE.id]["status"] == "production" for module in UPGRADED_MODULES)
    assert "camera_light" not in entries
