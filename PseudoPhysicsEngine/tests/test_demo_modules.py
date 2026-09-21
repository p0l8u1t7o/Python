from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import trimesh
from pygltflib import GLTF2
from scipy.spatial.transform import Rotation

from cellforge.part_artifacts import preview_part
from cellforge.part_check import _check_frames, _default_params, _parts, check_module
from library import extrusion_frame, safety_door

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("module", [extrusion_frame, safety_door])
def test_demonstration_module_has_no_failure_or_warning(module):
    result = check_module(module)
    assert not [item for item in result.items if item.severity in {"fail", "warn"}]
    assert not [item for item in result.items if item.index == "6.8"]


def test_extrusion_beam_level_bound_tracks_frame_height():
    params = _default_params(extrusion_frame.MODULE)
    height = params["size_mm"][2]
    schema = extrusion_frame.module_definition(params).params_schema
    assert schema["properties"]["beam_levels_mm"]["items"]["maximum"] == height


def _rotate_about_axis(
    point: np.ndarray,
    origin: np.ndarray,
    axis: np.ndarray,
    angle_deg: float,
) -> np.ndarray:
    rest = np.eye(4)
    rest[:3, 3] = origin
    local_point = np.append(point, 1.0)
    local_point = np.linalg.inv(rest) @ local_point
    rotation = np.eye(4)
    rotation[:3, :3] = Rotation.from_rotvec(
        axis / np.linalg.norm(axis) * math.radians(angle_deg)
    ).as_matrix()
    return (rest @ rotation @ local_point)[:3]


@pytest.mark.parametrize(
    "hinge_side",
    safety_door.MODULE.params_schema["properties"]["hinge_side"]["enum"],
)
def test_safety_door_rotates_about_hinge_without_translation_error(hinge_side):
    params = _default_params(safety_door.MODULE)
    params["hinge_side"] = hinge_side
    definition = safety_door.module_definition(params)
    parts = {part.name: part.shape for part in _parts(safety_door.build(params))}
    axis = next(axis for axis in definition.axes if axis.id == "swing")
    hinge = np.asarray(axis.origin.xyz, dtype=float)
    latch = np.asarray(definition.frames["latch"].xyz, dtype=float)
    direction = float(np.sign(latch[0] - hinge[0]))
    hinge_box = parts["door_stile_hinge"].BoundingBox()
    latch_box = parts["door_stile_latch"].BoundingBox()
    hinge_edge_x = hinge_box.xmin if direction > 0 else hinge_box.xmax
    latch_edge_x = latch_box.xmax if direction > 0 else latch_box.xmin
    hinge_edge = np.asarray((hinge_edge_x, latch[1], latch[2]))
    latch_edge = np.asarray((latch_edge_x, latch[1], latch[2]))
    limits = axis.range_deg
    assert limits is not None
    closed_angle, open_angle = limits
    closed_hinge = _rotate_about_axis(hinge_edge, hinge, np.asarray(axis.axis), closed_angle)
    open_hinge = _rotate_about_axis(hinge_edge, hinge, np.asarray(axis.axis), open_angle)
    closed_latch = _rotate_about_axis(latch_edge, hinge, np.asarray(axis.axis), closed_angle)
    open_latch = _rotate_about_axis(latch_edge, hinge, np.asarray(axis.axis), open_angle)

    width = float(params["width_mm"])
    tolerance = width * math.sqrt(np.finfo(float).eps)
    np.testing.assert_allclose(closed_hinge, hinge_edge, atol=tolerance, rtol=0)
    np.testing.assert_allclose(open_hinge, hinge_edge, atol=tolerance, rtol=0)
    np.testing.assert_allclose(closed_latch, latch, atol=tolerance, rtol=0)
    assert math.isclose(np.linalg.norm((closed_latch - hinge)[:2]), width, abs_tol=tolerance)
    assert math.isclose(np.linalg.norm((open_latch - hinge)[:2]), width, abs_tol=tolerance)
    expected_sweep = 2 * width * math.sin(math.radians(open_angle - closed_angle) / 2)
    assert math.isclose(
        np.linalg.norm(open_latch - closed_latch), expected_sweep, abs_tol=tolerance
    )


def test_safety_door_named_parts_bind_to_the_declared_links():
    params = _default_params(safety_door.MODULE)
    parts = _parts(safety_door.build(params))
    base_names = {
        "frame_post_hinge",
        "frame_post_latch",
        "hinge_upper",
        "hinge_lower",
    }
    door_names = {
        "door_stile_hinge",
        "door_stile_latch",
        "door_rail_top",
        "door_rail_bottom",
        "door_mesh",
        "door_handle",
    }
    assert {part.name for part in parts if part.link == "base"} == base_names
    assert {part.name for part in parts if part.link == "door"} == door_names


def test_free_space_marker_only_suppresses_the_surface_distance_proxy():
    params = _default_params(extrusion_frame.MODULE)
    definition = extrusion_frame.module_definition(params)
    parts = _parts(extrusion_frame.build(params))
    inner = definition.frames["inner_center"]
    ordinary = definition.model_copy(deep=True)
    ordinary.frames["inner_center"] = inner.model_copy(update={"free_space": False})
    assert {(item.index, item.severity) for item in _check_frames(ordinary, parts)} == {
        ("6.4", "warn")
    }
    outside = definition.model_copy(deep=True)
    boxes = [part.shape.BoundingBox() for part in parts]
    minimum_x = min(box.xmin for box in boxes)
    maximum_x = max(box.xmax for box in boxes)
    outside.frames["inner_center"] = inner.model_copy(
        update={"xyz": (maximum_x + maximum_x - minimum_x, inner.xyz[1], inner.xyz[2])}
    )
    assert {(item.index, item.severity) for item in _check_frames(outside, parts)} == {
        ("6.4", "fail")
    }


def test_safety_door_preview_places_geometry_under_swing_joint(tmp_path):
    output = tmp_path / "safety-door.glb"
    preview_part(ROOT, "safety_door", output)
    gltf = GLTF2().load_binary(str(output))
    nodes = gltf.nodes or []
    joint = next(node for node in nodes if node.name == "safety_door.swing")
    child_names = {nodes[index].name for index in joint.children or []}
    assert {"visual", "collision"} <= child_names


def test_extrusion_frame_preview_keeps_per_member_collision_boxes(tmp_path):
    output = tmp_path / "extrusion-frame.glb"
    preview_part(ROOT, "extrusion_frame", output)
    scene = trimesh.load_scene(output)
    collision = scene.geometry["__cf__extrusion_frame__base__collision"]
    assert len(collision.split(only_watertight=False)) > 1
