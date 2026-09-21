"""Parametric framed safety door with a revolute hinge."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

SAFETY_YELLOW = cq.Color(0.95, 0.75, 0.10)
MESH_GREY = cq.Color(0.16, 0.18, 0.20, 0.62)
METAL_GREY = cq.Color(0.48, 0.51, 0.54)


def _parameters(params: dict) -> tuple[float, float, str, float, float]:
    return (
        float(params.get("width_mm", 900)),
        float(params.get("height_mm", 1800)),
        str(params.get("hinge_side", "left")),
        float(params.get("profile_mm", 30)),
        float(params.get("open_angle_deg", 110)),
    )


def _layout(params: dict) -> tuple[float, float, float, float, float, float, str, float]:
    width, height, hinge_side, profile, open_angle = _parameters(params)
    direction = 1.0 if hinge_side == "left" else -1.0
    hinge_x = -direction * width / 2
    latch_x = hinge_x + direction * width
    return width, height, profile, open_angle, direction, hinge_x, hinge_side, latch_x


def _add(
    assembly: cq.Assembly,
    shape: cq.Shape | cq.Workplane,
    name: str,
    color: cq.Color,
    link: str,
) -> None:
    assembly.add(shape, name=name, color=color, metadata={"link": link})


def build(params: dict) -> cq.Assembly:
    width, height, profile, _open_angle, direction, hinge_x, _hinge_side, latch_x = _layout(params)
    result = cq.Assembly(name=params.get("name", "safety_door"))

    frame_offset = direction * profile / 2
    _add(
        result,
        cq.Workplane("XY")
        .box(profile, profile, height)
        .translate((hinge_x - frame_offset, 0, height / 2)),
        "frame_post_hinge",
        SAFETY_YELLOW,
        "base",
    )
    _add(
        result,
        cq.Workplane("XY")
        .box(profile, profile, height)
        .translate((latch_x + frame_offset, 0, height / 2)),
        "frame_post_latch",
        SAFETY_YELLOW,
        "base",
    )
    hinge_radius = profile * 0.20
    hinge_length = profile * 1.8
    for name, z in (("hinge_lower", height * 0.25), ("hinge_upper", height * 0.75)):
        hinge = cq.Solid.makeCylinder(
            hinge_radius,
            hinge_length,
            cq.Vector(hinge_x, 0, z - hinge_length / 2),
            cq.Vector(0, 0, 1),
        )
        _add(result, hinge, name, METAL_GREY, "base")

    door_hinge_center = hinge_x + direction * profile / 2
    door_latch_center = latch_x - direction * profile / 2
    _add(
        result,
        cq.Workplane("XY")
        .box(profile, profile, height)
        .translate((door_hinge_center, 0, height / 2)),
        "door_stile_hinge",
        SAFETY_YELLOW,
        "door",
    )
    _add(
        result,
        cq.Workplane("XY")
        .box(profile, profile, height)
        .translate((door_latch_center, 0, height / 2)),
        "door_stile_latch",
        SAFETY_YELLOW,
        "door",
    )
    rail_length = width - 2 * profile
    rail_center = (hinge_x + latch_x) / 2
    for name, z in (("door_rail_bottom", profile / 2), ("door_rail_top", height - profile / 2)):
        _add(
            result,
            cq.Workplane("XY").box(rail_length, profile, profile).translate((rail_center, 0, z)),
            name,
            SAFETY_YELLOW,
            "door",
        )

    mesh_width = width - 2 * profile
    mesh_height = height - 2 * profile
    _add(
        result,
        cq.Workplane("XY").box(mesh_width, 2, mesh_height).translate((rail_center, 0, height / 2)),
        "door_mesh",
        MESH_GREY,
        "door",
    )

    handle_radius = profile * 0.12
    handle_depth = profile * 1.1
    handle_length = min(height * 0.18, width * 0.24)
    handle_x = latch_x - direction * profile * 1.8
    handle_z = height / 2
    handle_y = -profile / 2
    supports = [
        cq.Solid.makeCylinder(
            handle_radius,
            handle_depth,
            cq.Vector(handle_x, handle_y, handle_z + offset),
            cq.Vector(0, -1, 0),
        )
        for offset in (-handle_length / 2, handle_length / 2)
    ]
    grip = cq.Solid.makeCylinder(
        handle_radius,
        handle_length,
        cq.Vector(handle_x, handle_y - handle_depth, handle_z - handle_length / 2),
        cq.Vector(0, 0, 1),
    )
    _add(
        result,
        cq.Compound.makeCompound([*supports, grip]),
        "door_handle",
        METAL_GREY,
        "door",
    )
    return result


def module_definition(params: dict) -> ModuleDef:
    width, height, _profile, open_angle, _direction, hinge_x, _hinge_side, latch_x = _layout(params)
    return ModuleDef(
        id="safety_door",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(xyz=(hinge_x, 0, 0), link="base"),
            "hinge": Frame(xyz=(hinge_x, 0, height / 2), link="base"),
            "latch": Frame(xyz=(latch_x, 0, height / 2), link="door"),
        },
        axes=[
            {
                "id": "swing",
                "type": "revolute",
                "parent": "base",
                "child": "door",
                "origin": {"xyz": (hinge_x, 0, 0)},
                "axis": (0, 0, 1),
                "range_deg": (0, open_angle),
                "max_speed_dps": 90,
            }
        ],
        collision="box",
        meta=ModuleMeta(
            basis="依一般工業安全圍籬單扇門比例與鋁框配置作工程推估，網片簡化為半透明薄板"
        ),
    )


MODULE = ModuleDef(
    id="safety_door",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "width_mm": {
                "type": "number",
                "minimum": 400,
                "maximum": 1500,
                "default": 900,
            },
            "height_mm": {
                "type": "number",
                "minimum": 800,
                "maximum": 2500,
                "default": 1800,
            },
            "hinge_side": {"type": "string", "enum": ["left", "right"], "default": "left"},
            "profile_mm": {
                "type": "integer",
                "enum": [30, 40],
                "minimum": 30,
                "maximum": 40,
                "default": 30,
            },
            "open_angle_deg": {
                "type": "number",
                "minimum": 60,
                "maximum": 170,
                "default": 110,
            },
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(), "hinge": Frame(link="base"), "latch": Frame(link="door")},
    axes=[
        {
            "id": "swing",
            "type": "revolute",
            "parent": "base",
            "child": "door",
            "axis": (0, 0, 1),
            "range_deg": (0, 110),
            "max_speed_dps": 90,
        }
    ],
    collision="box",
    meta=ModuleMeta(basis="依一般工業安全圍籬單扇門比例與鋁框配置作工程推估，網片簡化為半透明薄板"),
)
