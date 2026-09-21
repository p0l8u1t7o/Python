"""Floor-standing inspection fixture with slotted tooling plate and braced legs."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

FRAME_GREY = cq.Color(0.38, 0.43, 0.47)
PLATE_GREY = cq.Color(0.18, 0.22, 0.25)
FOOT_BLACK = cq.Color(0.08, 0.09, 0.10)

STIFFENER_SIZE_MM = 30.0
TOOLING_HOLE_DIAMETER_RATIO = 0.025
LOCATING_HOLE_DIAMETER_RATIO = 0.045

FIXTURE_STAND_BASIS = (
    "依一般檢測治具台的工作高度、四腳焊接機架與可換式工具板配置作工程推估；工具板孔陣與"
    "定位銷孔供 Getac 機殼治具鎖附，尺寸範圍保留常見人體工學站姿高度。"
)


def _parameters(
    params: dict,
) -> tuple[list[float], float, list[float], list[float]]:
    return (
        [float(value) for value in params.get("top_size", [600, 450, 20])],
        float(params.get("top_height_mm", 805)),
        [float(value) for value in params.get("column_size", [50, 50])],
        [float(value) for value in params.get("foot_size", [100, 100, 12])],
    )


def _layout(params: dict) -> tuple[list[float], float, list[float], list[float], float, float]:
    top_size, top_height, column_size, requested_foot_size = _parameters(params)
    foot_size = [
        min(requested_foot_size[0], top_size[0] * 0.42),
        min(requested_foot_size[1], top_size[1] * 0.42),
        requested_foot_size[2],
    ]
    leg_x = top_size[0] / 2 - max(foot_size[0], column_size[0]) / 2
    leg_y = top_size[1] / 2 - max(foot_size[1], column_size[1]) / 2
    return top_size, top_height, column_size, foot_size, leg_x, leg_y


def _tooling_plate(size: list[float]) -> cq.Shape:
    x_size, y_size, thickness = size
    tooling_diameter = max(min(x_size, y_size) * TOOLING_HOLE_DIAMETER_RATIO, thickness * 0.45)
    locating_diameter = max(
        min(x_size, y_size) * LOCATING_HOLE_DIAMETER_RATIO,
        tooling_diameter * 1.5,
    )
    plate = (
        cq.Workplane("XY")
        .box(x_size, y_size, thickness)
        .faces(">Z")
        .workplane()
        .rarray(x_size / 5, y_size / 4, 4, 3)
        .hole(tooling_diameter)
    )
    return (
        plate.faces(">Z")
        .workplane()
        .pushPoints(
            [
                (-x_size * 0.34, -y_size * 0.32),
                (x_size * 0.34, y_size * 0.32),
            ]
        )
        .hole(locating_diameter)
        .val()
    )


def build(params: dict) -> cq.Assembly:
    top_size, top_height, column_size, foot_size, leg_x, leg_y = _layout(params)
    top_thickness = top_size[2]
    column_bottom = foot_size[2]
    column_top = top_height - top_thickness
    if column_top <= column_bottom + STIFFENER_SIZE_MM:
        raise ValueError("治具台高度不足以容納支腳、補強梁與台面")

    assembly = cq.Assembly(name=params.get("name", "fixture_stand"))
    for suffix, x, y in (
        ("front_left", -leg_x, -leg_y),
        ("front_right", leg_x, -leg_y),
        ("rear_left", -leg_x, leg_y),
        ("rear_right", leg_x, leg_y),
    ):
        assembly.add(
            cq.Workplane("XY").box(*foot_size).translate((x, y, foot_size[2] / 2)),
            name=f"foot_{suffix}",
            color=FOOT_BLACK,
        )
        assembly.add(
            cq.Workplane("XY")
            .box(column_size[0], column_size[1], column_top - column_bottom)
            .translate((x, y, column_bottom + (column_top - column_bottom) / 2)),
            name=f"leg_{suffix}",
            color=FRAME_GREY,
        )

    stiffener_drop = max(STIFFENER_SIZE_MM * 2, top_height * 0.08)
    stiffener_z = column_top - stiffener_drop
    assembly.add(
        cq.Workplane("XY")
        .box(leg_x * 2 + column_size[0], STIFFENER_SIZE_MM, STIFFENER_SIZE_MM)
        .translate((0, -leg_y, stiffener_z)),
        name="stiffener_front",
        color=FRAME_GREY,
    )
    assembly.add(
        cq.Workplane("XY")
        .box(leg_x * 2 + column_size[0], STIFFENER_SIZE_MM, STIFFENER_SIZE_MM)
        .translate((0, leg_y, stiffener_z)),
        name="stiffener_rear",
        color=FRAME_GREY,
    )
    assembly.add(
        cq.Workplane("XY")
        .box(STIFFENER_SIZE_MM, leg_y * 2 + column_size[1], STIFFENER_SIZE_MM)
        .translate((-leg_x, 0, stiffener_z)),
        name="stiffener_left",
        color=FRAME_GREY,
    )
    assembly.add(
        cq.Workplane("XY")
        .box(STIFFENER_SIZE_MM, leg_y * 2 + column_size[1], STIFFENER_SIZE_MM)
        .translate((leg_x, 0, stiffener_z)),
        name="stiffener_right",
        color=FRAME_GREY,
    )

    assembly.add(
        _tooling_plate(top_size).translate((0, 0, top_height - top_thickness / 2)),
        name="tooling_plate",
        color=PLATE_GREY,
    )
    return assembly


def module_definition(params: dict) -> ModuleDef:
    _top_size, top_height, _column_size, _foot_size, leg_x, leg_y = _layout(params)
    return ModuleDef(
        id="fixture_stand",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(xyz=(-leg_x, -leg_y, 0), link="base"),
            "top": Frame(xyz=(0, 0, top_height), link="base"),
        },
        collision="box",
        meta=ModuleMeta(basis=FIXTURE_STAND_BASIS),
    )


MODULE = ModuleDef(
    id="fixture_stand",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "top_size": {
                "type": "array",
                "prefixItems": [
                    {"type": "number", "minimum": 300, "maximum": 1600},
                    {"type": "number", "minimum": 220, "maximum": 1000},
                    {"type": "number", "minimum": 8, "maximum": 40},
                ],
                "minItems": 3,
                "maxItems": 3,
                "default": [600, 450, 20],
            },
            "top_height_mm": {
                "type": "number",
                "minimum": 500,
                "maximum": 1200,
                "default": 805,
            },
            "column_size": {
                "type": "array",
                "prefixItems": [
                    {"type": "number", "minimum": 30, "maximum": 100},
                    {"type": "number", "minimum": 30, "maximum": 100},
                ],
                "minItems": 2,
                "maxItems": 2,
                "default": [50, 50],
            },
            "foot_size": {
                "type": "array",
                "prefixItems": [
                    {"type": "number", "minimum": 60, "maximum": 180},
                    {"type": "number", "minimum": 60, "maximum": 180},
                    {"type": "number", "minimum": 8, "maximum": 25},
                ],
                "minItems": 3,
                "maxItems": 3,
                "default": [100, 100, 12],
            },
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(), "top": Frame(link="base")},
    collision="box",
    meta=ModuleMeta(basis=FIXTURE_STAND_BASIS),
)
