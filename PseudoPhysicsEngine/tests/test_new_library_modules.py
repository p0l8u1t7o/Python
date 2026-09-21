from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from cellforge.build.transforms import matrix_from_pose
from cellforge.part_catalog import load_library_catalog
from cellforge.part_check import _default_params, _parts, check_module
from library import camera_station, control_cabinet, conveyor, part_stopper, signal_tower

NEW_MODULES = (camera_station, control_cabinet, part_stopper, signal_tower)


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


def _transformed_bounds(parts, transform: np.ndarray) -> tuple[float, ...]:
    points = []
    for part in parts:
        box = part.shape.BoundingBox()
        for x in (box.xmin, box.xmax):
            for y in (box.ymin, box.ymax):
                for z in (box.zmin, box.zmax):
                    points.append((transform @ np.array((x, y, z, 1.0)))[:3])
    stacked = np.stack(points)
    return (
        float(stacked[:, 0].min()),
        float(stacked[:, 0].max()),
        float(stacked[:, 1].min()),
        float(stacked[:, 1].max()),
        float(stacked[:, 2].min()),
        float(stacked[:, 2].max()),
    )


@pytest.mark.parametrize("module", NEW_MODULES)
def test_new_library_module_has_no_failure_or_warning(module):
    result = check_module(module)
    assert not [item for item in result.items if item.severity in {"fail", "warn"}]


@pytest.mark.parametrize("module", NEW_MODULES)
def test_new_module_numeric_parameters_have_bounds_that_build(module):
    defaults = _default_params(module.MODULE)
    numeric_schemas = []
    for name, parameter in module.MODULE.params_schema["properties"].items():
        candidates = [parameter]
        if isinstance(parameter.get("items"), dict):
            candidates.append(parameter["items"])
        numeric_schemas.extend(
            candidate for candidate in candidates if candidate.get("type") in {"number", "integer"}
        )
        for candidate in candidates:
            if candidate.get("type") not in {"number", "integer"}:
                continue
            assert "minimum" in candidate and "maximum" in candidate
            for bound in ("minimum", "maximum"):
                value = candidate[bound]
                if parameter.get("type") == "array":
                    value = [value] * len(defaults[name])
                module.build({**defaults, name: value})
    assert numeric_schemas


def test_camera_station_camera_parameter_drives_seats_frames_and_tilt_link():
    defaults = _default_params(camera_station.MODULE)
    camera_schema = camera_station.MODULE.params_schema["properties"]["cameras"]
    for count in (camera_schema["minimum"], camera_schema["maximum"]):
        params = {**defaults, "cameras": count}
        parts = _parts(camera_station.build(params))
        definition = camera_station.module_definition(params)
        seats = [part for part in parts if part.name.startswith("camera_seat_")]
        mounts = [name for name in definition.frames if name.startswith("cam_")]
        assert len(seats) == len(mounts) == count
        assert all(part.link == definition.axes[0].child for part in seats)
    assert camera_station.MODULE.axes[0].id == "tilt"


def test_control_cabinet_stays_inside_its_declared_size():
    params = _default_params(control_cabinet.MODULE)
    parts = _parts(control_cabinet.build(params))
    bounds = _transformed_bounds(parts, np.eye(4))
    tolerance = _geometric_tolerance(parts)
    width, depth, height = params["size_mm"]
    assert bounds[1] - bounds[0] <= width + tolerance
    assert bounds[3] - bounds[2] <= depth + tolerance
    assert bounds[4] >= -tolerance
    assert bounds[5] <= height + tolerance


def test_signal_tower_tiers_drive_lenses_in_red_amber_green_order():
    defaults = _default_params(signal_tower.MODULE)
    tiers_schema = signal_tower.MODULE.params_schema["properties"]["tiers"]
    for tiers in (tiers_schema["minimum"], tiers_schema["maximum"]):
        parts = _parts(signal_tower.build({**defaults, "tiers": tiers}))
        lenses = [part for part in parts if part.name.startswith("lens_")]
        assert len(lenses) == tiers
        assert [part.name.rsplit("_", 1)[-1] for part in lenses] == [
            name for name, _color in signal_tower.LENS_COLORS[:tiers]
        ]
        assert [part.color.toTuple() for part in lenses] == [
            color.toTuple() for _name, color in signal_tower.LENS_COLORS[:tiers]
        ]


def test_part_stopper_mates_conveyor_without_intruding_at_zero_pose():
    conveyor_params = _default_params(conveyor.MODULE)
    stopper_params = _default_params(part_stopper.MODULE)
    conveyor_definition = conveyor.module_definition(conveyor_params)
    stopper_definition = part_stopper.module_definition(stopper_params)
    conveyor_parts = _parts(conveyor.build(conveyor_params))
    stopper_parts = _parts(part_stopper.build(stopper_params))
    conveyor_by_name = {part.name: part for part in conveyor_parts}
    stopper_by_name = {part.name: part for part in stopper_parts}
    tolerance = max(
        _geometric_tolerance(conveyor_parts),
        _geometric_tolerance(stopper_parts),
    )

    target = conveyor_definition.frames["stopper_mount"]
    source = stopper_definition.frames["mount"]
    world_from_stopper = matrix_from_pose(target.xyz, target.rpy_deg) @ np.linalg.inv(
        matrix_from_pose(source.xyz, source.rpy_deg)
    )
    stop = stopper_definition.frames["stop"]
    stop_world = world_from_stopper @ matrix_from_pose(stop.xyz, stop.rpy_deg)
    belt_line = conveyor_definition.frames["stop"]
    belt_box = conveyor_by_name["belt"].shape.BoundingBox()
    stop_bounds = _transformed_bounds(stopper_parts, world_from_stopper)

    assert math.isclose(stop_world[2, 3], belt_line.xyz[2], abs_tol=tolerance)
    assert stop_bounds[2] >= belt_box.ymax - tolerance
    world_axis = world_from_stopper[:3, :3] @ np.array(stopper_definition.axes[0].axis)
    direction_to_corridor = np.array(belt_line.xyz) - stop_world[:3, 3]
    assert float(np.dot(world_axis, direction_to_corridor)) > 0

    conveyor_plate = conveyor_by_name["stopper_mount_plate"].shape.BoundingBox()
    stopper_flange = stopper_by_name["mounting_flange"].shape.BoundingBox()
    assert stopper_flange.xlen < conveyor_plate.xlen
    assert stopper_flange.zlen < conveyor_plate.zlen


def test_new_modules_are_production_catalog_entries():
    root = Path(__file__).resolve().parents[1]
    entries = {entry["id"]: entry for entry in load_library_catalog(root)}
    assert all(entries[module.MODULE.id]["status"] == "production" for module in NEW_MODULES)
