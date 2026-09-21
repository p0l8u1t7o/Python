"""Parametric belt conveyor with recognisable conveying and support hardware."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

FRAME_GREY = cq.Color(0.32, 0.37, 0.40)
BELT_BLACK = cq.Color(0.06, 0.07, 0.08)
GUIDE_BLUE = cq.Color(0.12, 0.32, 0.48)
MOTOR_BLUE = cq.Color(0.16, 0.38, 0.56)
METAL_GREY = cq.Color(0.52, 0.55, 0.57)
FOOT_BLACK = cq.Color(0.08, 0.09, 0.10)
SAFETY_YELLOW = cq.Color(0.95, 0.72, 0.08)

BELT_TOP_OFFSET_MM = 45.0
BELT_THICKNESS_MM = 10.0
FRAME_DEPTH_MM = 28.0
LEG_SIZE_MM = 50.0
FOOT_HEIGHT_MM = 16.0

CONVEYOR_BASIS = (
    "依一般小型裝配線皮帶輸送機的滾筒比例、側導引、可調腳與減速馬達包絡作工程推估；"
    "台面高度與寬度範圍涵蓋 Getac 機殼輸送及擋停氣缸安裝需求。"
)


def _parameters(params: dict) -> tuple[float, float, float, float]:
    return (
        float(params.get("length_mm", 1600)),
        float(params.get("width_mm", 600)),
        float(params.get("height_mm", 760)),
        float(params.get("speed_mm_s", 300)),
    )


def _add(
    assembly: cq.Assembly,
    shape: cq.Shape | cq.Workplane,
    name: str,
    color: cq.Color,
    link: str = "base",
) -> None:
    assembly.add(shape, name=name, color=color, metadata={"link": link})


def build(params: dict) -> cq.Assembly:
    length, width, height, _speed = _parameters(params)
    result = cq.Assembly(name=params.get("name", "conveyor"))
    belt_top = height + BELT_TOP_OFFSET_MM
    pulley_radius = min(width * 0.08, BELT_TOP_OFFSET_MM * 0.55)
    pulley_x = length / 2 - pulley_radius
    belt_width = width - FRAME_DEPTH_MM * 2
    bed_length = length - pulley_radius * 2

    frame_y = width / 2 - FRAME_DEPTH_MM / 2
    guide_depth = FRAME_DEPTH_MM * 0.65
    guide_y = width / 2 - guide_depth / 2
    for side_name, side in (("left", -1.0), ("right", 1.0)):
        _add(
            result,
            cq.Workplane("XY")
            .box(length, FRAME_DEPTH_MM, FRAME_DEPTH_MM * 2)
            .translate((0, side * frame_y, height)),
            f"side_frame_{side_name}",
            FRAME_GREY,
        )
        _add(
            result,
            cq.Workplane("XY")
            .box(length, guide_depth, FRAME_DEPTH_MM * 1.8)
            .translate((0, side * guide_y, belt_top + FRAME_DEPTH_MM * 0.75)),
            f"side_guide_{side_name}",
            GUIDE_BLUE,
        )

    _add(
        result,
        cq.Workplane("XY")
        .box(bed_length, belt_width, FRAME_DEPTH_MM)
        .translate((0, 0, height + FRAME_DEPTH_MM * 0.15)),
        "slider_bed",
        METAL_GREY,
    )
    _add(
        result,
        cq.Workplane("XY")
        .box(bed_length, belt_width, BELT_THICKNESS_MM)
        .translate((0, 0, belt_top - BELT_THICKNESS_MM / 2)),
        "belt",
        BELT_BLACK,
        "belt",
    )

    pulley_center_z = belt_top - pulley_radius
    for name, x in (("idler_pulley", -pulley_x), ("drive_pulley", pulley_x)):
        _add(
            result,
            cq.Solid.makeCylinder(
                pulley_radius,
                belt_width,
                cq.Vector(x, -belt_width / 2, pulley_center_z),
                cq.Vector(0, 1, 0),
            ),
            name,
            METAL_GREY,
        )

    leg_x = length * 0.38
    leg_y = width * 0.38
    leg_top = height - FRAME_DEPTH_MM
    foot_size = LEG_SIZE_MM * 1.8
    for suffix, x, y in (
        ("front_left", -leg_x, -leg_y),
        ("front_right", leg_x, -leg_y),
        ("rear_left", -leg_x, leg_y),
        ("rear_right", leg_x, leg_y),
    ):
        _add(
            result,
            cq.Workplane("XY")
            .box(LEG_SIZE_MM, LEG_SIZE_MM, leg_top - FOOT_HEIGHT_MM)
            .translate((x, y, FOOT_HEIGHT_MM + (leg_top - FOOT_HEIGHT_MM) / 2)),
            f"leg_{suffix}",
            FRAME_GREY,
        )
        pad = (
            cq.Workplane("XY")
            .box(foot_size, foot_size, FOOT_HEIGHT_MM * 0.45)
            .translate((x, y, FOOT_HEIGHT_MM * 0.225))
            .val()
        )
        stem = (
            cq.Workplane("XY")
            .box(LEG_SIZE_MM * 0.45, LEG_SIZE_MM * 0.45, FOOT_HEIGHT_MM * 0.55)
            .translate((x, y, FOOT_HEIGHT_MM * 0.725))
            .val()
        )
        _add(
            result,
            cq.Compound.makeCompound([pad, stem]),
            f"adjustable_foot_{suffix}",
            FOOT_BLACK,
        )

    motor_length = max(pulley_radius * 2.2, LEG_SIZE_MM * 1.6)
    motor_width = max(width * 0.20, LEG_SIZE_MM * 1.8)
    motor_height = max(pulley_radius * 1.8, LEG_SIZE_MM * 1.5)
    # The gearmotor is underslung inside the declared footprint.  Keeping its
    # top below the deck preserves the product corridor above the belt.
    motor_x = length / 2 - motor_length / 2
    motor_y = width * 0.30
    motor_top = height - FRAME_DEPTH_MM
    motor_z = motor_top - motor_height / 2
    _add(
        result,
        cq.Workplane("XY")
        .box(motor_length, motor_width, motor_height)
        .translate((motor_x, motor_y, motor_z)),
        "drive_motor_envelope",
        MOTOR_BLUE,
    )
    _add(
        result,
        cq.Workplane("XY")
        .box(FRAME_DEPTH_MM, motor_width * 0.8, motor_height * 0.75)
        .translate(
            (
                length / 2 - motor_length - FRAME_DEPTH_MM / 2,
                motor_y,
                motor_top - motor_height * 0.75 / 2,
            )
        ),
        "drive_gearbox_envelope",
        METAL_GREY,
    )

    stopper_y = width / 2 - FRAME_DEPTH_MM / 2
    _add(
        result,
        cq.Workplane("XY")
        .box(FRAME_DEPTH_MM * 2.2, FRAME_DEPTH_MM, FRAME_DEPTH_MM * 2.5)
        .translate((0, stopper_y, belt_top)),
        "stopper_mount_plate",
        SAFETY_YELLOW,
    )
    return result


def module_definition(params: dict) -> ModuleDef:
    length, width, height, speed = _parameters(params)
    surface = height + BELT_TOP_OFFSET_MM
    leg_x = length * 0.38
    leg_y = width * 0.38
    stopper_y = width / 2
    return ModuleDef(
        id="conveyor",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(xyz=(-leg_x, -leg_y, 0), link="base"),
            "start": Frame(xyz=(-length / 2 + 150, 0, surface), link="belt"),
            "end": Frame(xyz=(length / 2 - 150, 0, surface), link="belt"),
            "stop": Frame(xyz=(0, 0, surface), link="belt"),
            "stopper_mount": Frame(xyz=(0, stopper_y, surface), link="base"),
        },
        axes=[
            {
                "id": "belt",
                "type": "prismatic",
                "parent": "base",
                "child": "belt",
                "axis": [1, 0, 0],
                "range_mm": [0, length],
                "max_speed_mm_s": speed,
            }
        ],
        collision="box",
        meta=ModuleMeta(basis=CONVEYOR_BASIS),
    )


MODULE = ModuleDef(
    id="conveyor",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "length_mm": {"type": "number", "minimum": 600, "maximum": 6000, "default": 1600},
            "width_mm": {"type": "number", "minimum": 300, "maximum": 1200, "default": 600},
            "height_mm": {"type": "number", "minimum": 400, "maximum": 1500, "default": 760},
            "speed_mm_s": {"type": "number", "minimum": 50, "maximum": 1500, "default": 300},
        },
        "additionalProperties": False,
    },
    frames={
        "mount": Frame(),
        "start": Frame(link="belt"),
        "end": Frame(link="belt"),
        "stop": Frame(link="belt"),
        "stopper_mount": Frame(link="base"),
    },
    axes=[
        {
            "id": "belt",
            "type": "prismatic",
            "parent": "base",
            "child": "belt",
            "axis": [1, 0, 0],
            "range_mm": [0, 1600],
            "max_speed_mm_s": 300,
        }
    ],
    collision="box",
    meta=ModuleMeta(basis=CONVEYOR_BASIS),
)
