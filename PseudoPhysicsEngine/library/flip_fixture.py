"""Parametric guarded 180-degree product turnover fixture."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

BASE_GREY = cq.Color(0.22, 0.28, 0.33)
MECHANISM_BLUE = cq.Color(0.20, 0.43, 0.57)
SHAFT_STEEL = cq.Color(0.70, 0.72, 0.74)
CLAMP_ORANGE = cq.Color(0.92, 0.38, 0.08)
CYLINDER_DARK = cq.Color(0.10, 0.12, 0.14)


def _parameters(params: dict) -> tuple[float, float, float]:
    return (
        float(params.get("width_mm", 630)),
        float(params.get("depth_mm", 500)),
        float(params.get("height_mm", 320)),
    )


def _layout(params: dict) -> tuple[float, float, float, float, float, float, float]:
    width, depth, height = _parameters(params)
    base_thickness = max(height * 0.10, 24.0)
    shaft_z = height * 0.75
    post_width = width * 0.10
    arm_x = width * 0.28
    return width, depth, height, base_thickness, shaft_z, post_width, arm_x


def _add(
    assembly: cq.Assembly,
    shape: cq.Shape | cq.Workplane,
    name: str,
    color: cq.Color,
    link: str,
) -> None:
    assembly.add(shape, name=name, color=color, metadata={"link": link})


def build(params: dict) -> cq.Assembly:
    width, depth, height, base_thickness, shaft_z, post_width, arm_x = _layout(params)
    assembly = cq.Assembly(name="flip_fixture")
    _add(
        assembly,
        cq.Workplane("XY").box(width, depth, base_thickness).translate((0, 0, base_thickness / 2)),
        "base_plate",
        BASE_GREY,
        "base",
    )

    bearing_depth = depth * 0.18
    bearing_height = shaft_z - base_thickness
    bearing_x = (width - post_width) / 2
    for side, x in (("left", -bearing_x), ("right", bearing_x)):
        pedestal = (
            cq.Workplane("XY")
            .box(post_width, bearing_depth, bearing_height)
            .translate((x, 0, base_thickness + bearing_height / 2))
        )
        _add(assembly, pedestal, f"bearing_pedestal_{side}", MECHANISM_BLUE, "base")
        bearing = cq.Solid.makeCylinder(
            post_width * 0.34,
            post_width,
            cq.Vector(x - post_width / 2, 0, shaft_z),
            cq.Vector(1, 0, 0),
        )
        _add(assembly, bearing, f"shaft_bearing_{side}", CYLINDER_DARK, "base")

    shaft_length = width - 2 * post_width
    shaft = cq.Solid.makeCylinder(
        post_width * 0.16,
        shaft_length,
        cq.Vector(-shaft_length / 2, 0, shaft_z),
        cq.Vector(1, 0, 0),
    )
    _add(assembly, shaft, "rotary_shaft", SHAFT_STEEL, "nest")

    arm_depth = depth * 0.58
    arm_width = post_width * 0.34
    arm_height = max(height * 0.055, 16.0)
    for side, x in (("left", -arm_x), ("right", arm_x)):
        arm = cq.Workplane("XY").box(arm_width, arm_depth, arm_height).translate((x, 0, shaft_z))
        _add(assembly, arm, f"clamp_arm_{side}", MECHANISM_BLUE, "nest")
        pad_depth = arm_depth * 0.16
        pad_positions = (
            ("front", -arm_depth / 2 + pad_depth / 2),
            ("rear", arm_depth / 2 - pad_depth / 2),
        )
        for end, y in pad_positions:
            pad = (
                cq.Workplane("XY")
                .box(arm_width * 1.35, pad_depth, arm_height * 0.45)
                .translate((x, y, shaft_z + arm_height * 0.72))
            )
            _add(assembly, pad, f"clamp_pad_{side}_{end}", CLAMP_ORANGE, "nest")

    cylinder_radius = post_width * 0.20
    cylinder_height = shaft_z - base_thickness * 1.4
    cylinder_x = bearing_x
    cylinder_y = -(depth - 2 * cylinder_radius) / 2
    cylinder = cq.Solid.makeCylinder(
        cylinder_radius,
        cylinder_height,
        cq.Vector(cylinder_x, cylinder_y, base_thickness),
        cq.Vector(0, 0, 1),
    )
    _add(assembly, cylinder, "drive_cylinder", CYLINDER_DARK, "base")
    rod = cq.Solid.makeCylinder(
        cylinder_radius * 0.34,
        base_thickness * 1.2,
        cq.Vector(cylinder_x, cylinder_y, base_thickness + cylinder_height),
        cq.Vector(0, 0, 1),
    )
    _add(assembly, rod, "drive_rod", SHAFT_STEEL, "base")
    return assembly


def module_definition(params: dict) -> ModuleDef:
    _width, _depth, _height, _base_thickness, shaft_z, _post_width, _arm_x = _layout(params)
    return ModuleDef(
        id="flip_fixture",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(link="base"),
            "base": Frame(link="base"),
            "nest": Frame(xyz=(0, 0, shaft_z), link="nest"),
        },
        axes=[
            {
                "id": "flip",
                "type": "revolute",
                "parent": "base",
                "child": "nest",
                "origin": {"xyz": (0, 0, shaft_z)},
                "axis": (1, 0, 0),
                "range_deg": (0, 180),
                "max_speed_dps": 90,
            }
        ],
        collision="box",
        payload_kg=15,
        meta=ModuleMeta(
            basis=(
                "依 Getac 產品翻面檢測需求及一般雙側軸承、氣缸驅動翻轉治具比例作工程推估，"
                "額定承載十五公斤"
            )
        ),
    )


MODULE = ModuleDef(
    id="flip_fixture",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "width_mm": {
                "type": "number",
                "minimum": 450,
                "maximum": 1200,
                "default": 630,
            },
            "depth_mm": {
                "type": "number",
                "minimum": 320,
                "maximum": 900,
                "default": 500,
            },
            "height_mm": {
                "type": "number",
                "minimum": 240,
                "maximum": 700,
                "default": 320,
            },
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(), "base": Frame(), "nest": Frame(link="nest")},
    axes=[
        {
            "id": "flip",
            "type": "revolute",
            "parent": "base",
            "child": "nest",
            "axis": (1, 0, 0),
            "range_deg": (0, 180),
            "max_speed_dps": 90,
        }
    ],
    collision="box",
    payload_kg=15,
    meta=ModuleMeta(
        basis=(
            "依 Getac 產品翻面檢測需求及一般雙側軸承、氣缸驅動翻轉治具比例作工程推估，"
            "額定承載十五公斤"
        )
    ),
)
