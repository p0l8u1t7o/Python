"""Parametric vertical lift rack with individually modelled structural members."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

STEEL_BLUE = cq.Color(0.35, 0.43, 0.49)
SHELF_GREY = cq.Color(0.58, 0.62, 0.65)
SUPPORT_GREY = cq.Color(0.25, 0.29, 0.32)
SAFETY_YELLOW = cq.Color(0.95, 0.72, 0.08)
SCREW_GREY = cq.Color(0.44, 0.46, 0.48)

SHELF_BASE_Z_MM = 120.0
SHELF_THICKNESS_MM = 20.0
BASE_THICKNESS_MM = 12.0
POST_SIZE_MM = 40.0

LIFT_RACK_BASIS = (
    "依一般升降料架的層距、鈑金層板與四柱導引配置作工程推估；尺寸範圍涵蓋 Getac "
    "機殼暫存需求，角鋼托架、背板及螺桿保留可辨識功能但省略製造細節。"
)


def _parameters(params: dict) -> tuple[int, float, float, float, float]:
    return (
        int(params.get("levels", 6)),
        float(params.get("pitch_mm", 90)),
        float(params.get("width_mm", 650)),
        float(params.get("depth_mm", 500)),
        float(params.get("max_speed_mm_s", 200)),
    )


def _add(
    assembly: cq.Assembly,
    shape: cq.Shape | cq.Workplane,
    name: str,
    color: cq.Color,
    link: str = "base",
) -> None:
    assembly.add(shape, name=name, color=color, metadata={"link": link})


def _angle_support(width: float, depth: float, side: float, z: float) -> cq.Shape:
    lip = max(width * 0.055, SHELF_THICKNESS_MM)
    gauge = max(SHELF_THICKNESS_MM * 0.35, 6.0)
    horizontal = (
        cq.Workplane("XY")
        .box(lip, depth, gauge)
        .translate((side * (width - lip) / 2, 0, z - SHELF_THICKNESS_MM / 2 - gauge / 2))
        .val()
    )
    vertical = (
        cq.Workplane("XY")
        .box(gauge, depth, SHELF_THICKNESS_MM * 1.6)
        .translate(
            (
                side * (width - gauge) / 2,
                0,
                z - SHELF_THICKNESS_MM / 2 - SHELF_THICKNESS_MM * 0.8,
            )
        )
        .val()
    )
    return cq.Compound.makeCompound([horizontal, vertical])


def build(params: dict) -> cq.Assembly:
    levels, pitch, width, depth, _speed = _parameters(params)
    result = cq.Assembly(name=params.get("name", "lift_rack"))
    top_shelf_z = SHELF_BASE_Z_MM + (levels - 1) * pitch
    structure_height = top_shelf_z + pitch * 0.75
    base_width = width
    base_depth = depth

    _add(
        result,
        cq.Workplane("XY")
        .box(base_width, base_depth, BASE_THICKNESS_MM)
        .translate((0, 0, BASE_THICKNESS_MM / 2)),
        "base_plate",
        SUPPORT_GREY,
    )

    post_x = (width - POST_SIZE_MM) / 2
    post_y = (depth - POST_SIZE_MM) / 2
    for suffix, x, y in (
        ("front_left", -post_x, -post_y),
        ("front_right", post_x, -post_y),
        ("rear_left", -post_x, post_y),
        ("rear_right", post_x, post_y),
    ):
        post_height = structure_height - BASE_THICKNESS_MM
        _add(
            result,
            cq.Workplane("XY")
            .box(POST_SIZE_MM, POST_SIZE_MM, post_height)
            .translate((x, y, BASE_THICKNESS_MM + post_height / 2)),
            f"guide_post_{suffix}",
            STEEL_BLUE,
        )

    back_panel_thickness = max(SHELF_THICKNESS_MM * 0.3, 6.0)
    panel_bottom = SHELF_BASE_Z_MM / 2
    panel_height = structure_height - panel_bottom
    _add(
        result,
        cq.Workplane("XY")
        .box(width, back_panel_thickness, panel_height)
        .translate((0, post_y, panel_bottom + panel_height / 2)),
        "back_panel",
        STEEL_BLUE,
    )

    screw_height = structure_height - BASE_THICKNESS_MM
    _add(
        result,
        cq.Solid.makeCylinder(
            POST_SIZE_MM * 0.18,
            screw_height,
            cq.Vector(0, post_y - POST_SIZE_MM, BASE_THICKNESS_MM),
            cq.Vector(0, 0, 1),
        ),
        "lift_screw",
        SCREW_GREY,
    )

    stop_size = max(SHELF_THICKNESS_MM * 0.7, 12.0)
    for level in range(levels):
        z = SHELF_BASE_Z_MM + level * pitch
        _add(
            result,
            cq.Workplane("XY").box(width, depth, SHELF_THICKNESS_MM).translate((0, 0, z)),
            f"shelf_{level}",
            SHELF_GREY,
            "lift",
        )
        for side_name, side in (("left", -1.0), ("right", 1.0)):
            _add(
                result,
                _angle_support(width, depth, side, z),
                f"angle_support_{level}_{side_name}",
                SUPPORT_GREY,
                "lift",
            )
            _add(
                result,
                cq.Workplane("XY")
                .box(stop_size, stop_size, stop_size)
                .translate(
                    (
                        side * (width / 2 - stop_size / 2),
                        -depth / 2 + stop_size / 2,
                        z + SHELF_THICKNESS_MM / 2 + stop_size / 2,
                    )
                ),
                f"slot_stop_{level}_{side_name}",
                SAFETY_YELLOW,
                "lift",
            )
    return result


def module_definition(params: dict) -> ModuleDef:
    levels, pitch, _width, _depth, speed = _parameters(params)
    slots = {
        f"slot_{index}": Frame(
            xyz=(0, 0, SHELF_BASE_Z_MM + index * pitch + SHELF_THICKNESS_MM / 2),
            link="lift",
        )
        for index in range(levels)
    }
    return ModuleDef(
        id="lift_rack",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(xyz=(0, 0, 0), link="base"),
            **slots,
            "top": slots[f"slot_{levels - 1}"],
        },
        axes=[
            {
                "id": "lift",
                "type": "prismatic",
                "parent": "base",
                "child": "lift",
                "axis": [0, 0, 1],
                "range_mm": [0, (levels - 1) * pitch],
                "max_speed_mm_s": speed,
            }
        ],
        collision="box",
        meta=ModuleMeta(basis=LIFT_RACK_BASIS),
    )


MODULE = ModuleDef(
    id="lift_rack",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "levels": {"type": "integer", "minimum": 2, "maximum": 12, "default": 6},
            "pitch_mm": {"type": "number", "minimum": 60, "maximum": 300, "default": 90},
            "width_mm": {"type": "number", "minimum": 300, "maximum": 1500, "default": 650},
            "depth_mm": {"type": "number", "minimum": 250, "maximum": 1200, "default": 500},
            "max_speed_mm_s": {
                "type": "number",
                "minimum": 20,
                "maximum": 500,
                "default": 200,
            },
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(), "slot_0": Frame(link="lift"), "top": Frame(link="lift")},
    axes=[
        {
            "id": "lift",
            "type": "prismatic",
            "parent": "base",
            "child": "lift",
            "axis": [0, 0, 1],
            "range_mm": [0, 450],
            "max_speed_mm_s": 200,
        }
    ],
    collision="box",
    meta=ModuleMeta(basis=LIFT_RACK_BASIS),
)
