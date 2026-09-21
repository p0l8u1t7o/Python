from __future__ import annotations

import math
from pathlib import Path

import cadquery as cq
import pytest

from cellforge.part_catalog import load_library_catalog
from cellforge.part_check import _default_params, _parts, check_module
from library import conveyor, fixture_stand, lift_rack, safety_fence

UPGRADED_MODULES = (lift_rack, conveyor, fixture_stand, safety_fence)


def _geometric_tolerance(parts) -> float:
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


def _overall_bounds(parts):
    boxes = [part.shape.BoundingBox() for part in parts]
    return (
        min(box.xmin for box in boxes),
        max(box.xmax for box in boxes),
        min(box.ymin for box in boxes),
        max(box.ymax for box in boxes),
        min(box.zmin for box in boxes),
        max(box.zmax for box in boxes),
    )


@pytest.mark.parametrize("module", UPGRADED_MODULES)
def test_upgraded_static_module_has_no_failure_or_warning(module):
    result = check_module(module)
    assert not [item for item in result.items if item.severity in {"fail", "warn"}]


def test_lift_rack_slot_frames_follow_their_shelf_top_surfaces():
    params = _default_params(lift_rack.MODULE)
    definition = lift_rack.module_definition(params)
    parts = _parts(lift_rack.build(params))
    by_name = {part.name: part for part in parts}
    tolerance = _geometric_tolerance(parts)

    for level in range(params["levels"]):
        frame = definition.frames[f"slot_{level}"]
        shelf = by_name[f"shelf_{level}"]
        assert frame.link == "lift"
        assert math.isclose(frame.xyz[2], shelf.shape.BoundingBox().zmax, abs_tol=tolerance)
        assert by_name[f"angle_support_{level}_left"].link == "lift"
        assert by_name[f"angle_support_{level}_right"].link == "lift"
        assert by_name[f"slot_stop_{level}_left"].link == "lift"
        assert by_name[f"slot_stop_{level}_right"].link == "lift"

    assert definition.frames["top"] == definition.frames[f"slot_{params['levels'] - 1}"]
    assert {part.name for part in parts if part.name.startswith("guide_post_")}
    assert {"back_panel", "lift_screw"} <= by_name.keys()


def test_conveyor_has_drive_hardware_feet_guides_and_stopper_interface():
    params = _default_params(conveyor.MODULE)
    definition = conveyor.module_definition(params)
    parts = _parts(conveyor.build(params))
    by_name = {part.name: part for part in parts}
    tolerance = _geometric_tolerance(parts)

    assert {"drive_pulley", "idler_pulley", "drive_motor_envelope"} <= by_name.keys()
    assert {part.name for part in parts if part.name.startswith("side_guide_")}
    assert {part.name for part in parts if part.name.startswith("adjustable_foot_")}
    stopper = definition.frames["stopper_mount"]
    assert stopper.link == "base"
    point = cq.Vertex.makeVertex(*stopper.xyz)
    assert by_name["stopper_mount_plate"].shape.distance(point) <= tolerance

    xmin, xmax, ymin, ymax, _zmin, _zmax = _overall_bounds(parts)
    assert xmax - xmin <= params["length_mm"] + tolerance
    assert ymax - ymin <= params["width_mm"] + tolerance
    belt_top = definition.frames["stop"].xyz[2]
    for name in ("drive_motor_envelope", "drive_gearbox_envelope"):
        assert by_name[name].shape.BoundingBox().zmax < belt_top


def _numeric_schemas(schema: dict):
    if schema.get("type") in {"number", "integer"}:
        yield schema
    for key in ("properties",):
        child = schema.get(key)
        if isinstance(child, dict):
            for value in child.values():
                if isinstance(value, dict):
                    yield from _numeric_schemas(value)
    for key in ("items",):
        child = schema.get(key)
        if isinstance(child, dict):
            yield from _numeric_schemas(child)
    children = schema.get("prefixItems")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                yield from _numeric_schemas(child)


@pytest.mark.parametrize("module", UPGRADED_MODULES)
def test_every_numeric_parameter_declares_both_bounds_and_builds_at_them(module):
    schema = module.MODULE.params_schema
    numeric_schemas = list(_numeric_schemas(schema))
    assert numeric_schemas
    assert all("minimum" in item and "maximum" in item for item in numeric_schemas)

    defaults = _default_params(module.MODULE)
    for name, parameter in schema["properties"].items():
        if parameter.get("type") in {"number", "integer"}:
            for bound in ("minimum", "maximum"):
                module.build({**defaults, name: parameter[bound]})
        for index, item in enumerate(parameter.get("prefixItems", [])):
            for bound in ("minimum", "maximum"):
                value = list(defaults[name])
                value[index] = item[bound]
                module.build({**defaults, name: value})


def test_fixture_stand_has_four_leg_frame_and_real_tooling_holes():
    params = _default_params(fixture_stand.MODULE)
    parts = _parts(fixture_stand.build(params))
    by_name = {part.name: part for part in parts}
    leg_names = {part.name.removeprefix("leg_") for part in parts if part.name.startswith("leg_")}
    foot_names = {
        part.name.removeprefix("foot_") for part in parts if part.name.startswith("foot_")
    }
    stiffener_names = {part.name for part in parts if part.name.startswith("stiffener_")}
    plain_plate = cq.Workplane("XY").box(*params["top_size"]).val()

    assert leg_names == foot_names
    assert stiffener_names
    assert len(by_name["tooling_plate"].shape.Faces()) > len(plain_plate.Faces())
    tolerance = _geometric_tolerance(parts)
    xmin, xmax, ymin, ymax, _zmin, zmax = _overall_bounds(parts)
    assert xmax - xmin <= params["top_size"][0] + tolerance
    assert ymax - ymin <= params["top_size"][1] + tolerance
    assert zmax <= params["top_height_mm"] + tolerance
    plate_bottom = by_name["tooling_plate"].shape.BoundingBox().zmin
    assert max(by_name[name].shape.BoundingBox().zmax for name in stiffener_names) < plate_bottom


def test_safety_fence_segment_parameter_controls_panels_and_posts():
    defaults = _default_params(safety_fence.MODULE)
    segment_schema = safety_fence.MODULE.params_schema["properties"]["segments"]
    for segments in (segment_schema["minimum"], segment_schema["maximum"]):
        names = {
            part.name for part in _parts(safety_fence.build({**defaults, "segments": segments}))
        }
        panels = {name for name in names if name.startswith("mesh_panel_")}
        posts = {name for name in names if name.startswith("post_")}
        bases = {name for name in names if name.startswith("base_")}
        assert len(panels) == segments
        assert len(posts) == len(bases) == segments + 1
        parts = _parts(safety_fence.build({**defaults, "segments": segments}))
        tolerance = _geometric_tolerance(parts)
        xmin, xmax, _ymin, _ymax, _zmin, zmax = _overall_bounds(parts)
        assert xmax - xmin <= defaults["length_mm"] + tolerance
        assert zmax <= defaults["height_mm"] + tolerance


def test_lift_rack_structure_stays_inside_declared_width_and_depth():
    params = _default_params(lift_rack.MODULE)
    parts = _parts(lift_rack.build(params))
    tolerance = _geometric_tolerance(parts)
    xmin, xmax, ymin, ymax, _zmin, _zmax = _overall_bounds(parts)
    assert xmax - xmin <= params["width_mm"] + tolerance
    assert ymax - ymin <= params["depth_mm"] + tolerance


def test_upgraded_modules_are_marked_production_in_manifest():
    root = Path(__file__).resolve().parents[1]
    entries = {entry["id"]: entry for entry in load_library_catalog(root)}
    assert all(entries[module.MODULE.id]["status"] == "production" for module in UPGRADED_MODULES)
