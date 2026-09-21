"""Side-mounted pneumatic conveyor stop and positioning cylinder."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta
from library.conveyor import FRAME_DEPTH_MM

CYLINDER_BLUE = cq.Color(0.12, 0.34, 0.54)
FLANGE_GREY = cq.Color(0.48, 0.51, 0.54)
ROD_STEEL = cq.Color(0.74, 0.76, 0.78)
STOP_YELLOW = cq.Color(0.95, 0.72, 0.08)
SENSOR_DARK = cq.Color(0.09, 0.11, 0.13)

MOUNT_FLANGE_WIDTH_MM = FRAME_DEPTH_MM * 2.0
MOUNT_FLANGE_HEIGHT_MM = FRAME_DEPTH_MM * 2.25
MOUNT_FLANGE_DEPTH_MM = 8.0
CYLINDER_RADIUS_MM = 18.0
ROD_RADIUS_MM = 6.0
STOP_PAD_WIDTH_MM = 42.0
STOP_PAD_HEIGHT_MM = 40.0
STOP_PAD_DEPTH_MM = 8.0

PART_STOPPER_BASIS = (
    "依 conveyor.stopper_mount 的六十一點六乘七十毫米安裝板，採五十六乘六十三毫米"
    "四孔法蘭與一般側推式氣缸比例；"
    "零位擋面位於皮帶線外，伸出時沿負 Y 方向進入輸送區定位產品。"
)


def _parameters(params: dict) -> float:
    return float(params.get("stroke_mm", 180))


def _mounting_flange() -> cq.Shape:
    plate = (
        cq.Workplane("XY")
        .box(MOUNT_FLANGE_WIDTH_MM, MOUNT_FLANGE_DEPTH_MM, MOUNT_FLANGE_HEIGHT_MM)
        .translate((0, MOUNT_FLANGE_DEPTH_MM / 2, 0))
        .val()
    )
    hole_x = MOUNT_FLANGE_WIDTH_MM * 0.32
    hole_z = MOUNT_FLANGE_HEIGHT_MM * 0.32
    holes = (
        (-hole_x, -hole_z),
        (-hole_x, hole_z),
        (hole_x, -hole_z),
        (hole_x, hole_z),
    )
    for x, z in holes:
        cutter = cq.Solid.makeCylinder(
            3.2,
            MOUNT_FLANGE_DEPTH_MM * 2,
            cq.Vector(x, -MOUNT_FLANGE_DEPTH_MM / 2, z),
            cq.Vector(0, 1, 0),
        )
        plate = plate.cut(cutter)
    return plate


def _add(
    assembly: cq.Assembly,
    shape: cq.Shape | cq.Workplane,
    name: str,
    color: cq.Color,
    link: str = "base",
) -> None:
    assembly.add(shape, name=name, color=color, metadata={"link": link})


def build(params: dict) -> cq.Assembly:
    stroke = _parameters(params)
    body_length = max(stroke * 0.55, 70.0)
    assembly = cq.Assembly(name="part_stopper")
    _add(assembly, _mounting_flange(), "mounting_flange", FLANGE_GREY)
    body = cq.Solid.makeCylinder(
        CYLINDER_RADIUS_MM,
        body_length,
        cq.Vector(0, MOUNT_FLANGE_DEPTH_MM, 0),
        cq.Vector(0, 1, 0),
    )
    _add(assembly, body, "cylinder_body", CYLINDER_BLUE)
    rear_cap = cq.Solid.makeCylinder(
        CYLINDER_RADIUS_MM * 1.08,
        MOUNT_FLANGE_DEPTH_MM,
        cq.Vector(0, MOUNT_FLANGE_DEPTH_MM + body_length, 0),
        cq.Vector(0, 1, 0),
    )
    _add(assembly, rear_cap, "rear_cap", SENSOR_DARK)
    sensor = (
        cq.Workplane("XY")
        .box(CYLINDER_RADIUS_MM * 0.72, body_length * 0.28, CYLINDER_RADIUS_MM * 0.42)
        .translate(
            (
                CYLINDER_RADIUS_MM * 0.78,
                MOUNT_FLANGE_DEPTH_MM + body_length * 0.62,
                -CYLINDER_RADIUS_MM * 0.58,
            )
        )
    )
    _add(assembly, sensor, "position_sensor", SENSOR_DARK)

    rod = cq.Solid.makeCylinder(
        ROD_RADIUS_MM,
        MOUNT_FLANGE_DEPTH_MM + body_length * 0.35,
        cq.Vector(0, 0, 0),
        cq.Vector(0, 1, 0),
    )
    _add(assembly, rod, "piston_rod", ROD_STEEL, "stop")
    stop_pad = (
        cq.Workplane("XY")
        .box(STOP_PAD_WIDTH_MM, STOP_PAD_DEPTH_MM, STOP_PAD_HEIGHT_MM)
        .translate((0, STOP_PAD_DEPTH_MM / 2, 0))
    )
    _add(assembly, stop_pad, "stop_face", STOP_YELLOW, "stop")
    return assembly


def module_definition(params: dict) -> ModuleDef:
    stroke = _parameters(params)
    return ModuleDef(
        id="part_stopper",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(link="mounting_flange"),
            "stop": Frame(link="stop"),
        },
        axes=[
            {
                "id": "stop",
                "type": "prismatic",
                "parent": "base",
                "child": "stop",
                "axis": (0, -1, 0),
                "range_mm": (0, stroke),
                "max_speed_mm_s": 350,
            }
        ],
        collision="box",
        meta=ModuleMeta(basis=PART_STOPPER_BASIS),
    )


MODULE = ModuleDef(
    id="part_stopper",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "stroke_mm": {
                "type": "number",
                "minimum": 80,
                "maximum": 240,
                "default": 180,
            }
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(), "stop": Frame(link="stop")},
    axes=[
        {
            "id": "stop",
            "type": "prismatic",
            "parent": "base",
            "child": "stop",
            "axis": (0, -1, 0),
            "range_mm": (0, 180),
            "max_speed_mm_s": 350,
        }
    ],
    collision="box",
    meta=ModuleMeta(basis=PART_STOPPER_BASIS),
)
