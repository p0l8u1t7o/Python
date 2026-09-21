"""Floor-standing multi-camera station for S2, S3 and S4 inspection."""

from __future__ import annotations

import math

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

ALUMINIUM = cq.Color(0.70, 0.72, 0.74)
BASE_DARK = cq.Color(0.13, 0.15, 0.17)
HEAD_BLUE = cq.Color(0.14, 0.34, 0.52)
SEAT_GREY = cq.Color(0.34, 0.38, 0.42)

PROFILE_MM = 50.0
BASE_SIZE_MM = 220.0
BASE_THICKNESS_MM = 16.0
CAMERA_SPACING_MM = 130.0
SEAT_LENGTH_MM = 86.0
SEAT_WIDTH_MM = 82.0
SEAT_THICKNESS_MM = 16.0

CAMERA_STATION_BASIS = (
    "依 S2、S3、S4 外觀取像站所需的落地剛性，採一般鋁擠立柱、懸臂橫樑與"
    "多相機調角橫軌比例作工程推估；"
    "此模組用於完整落地站，局部加裝單一相機時改用 camera_bracket。"
)


def _parameters(params: dict) -> tuple[float, float, float, int]:
    return (
        float(params.get("height_mm", 1600)),
        float(params.get("reach_mm", 650)),
        float(params.get("tilt_deg", 20)),
        int(params.get("cameras", 2)),
    )


def _rotate_y(point: tuple[float, float, float], angle_deg: float) -> tuple[float, float, float]:
    angle = math.radians(angle_deg)
    x, y, z = point
    return (
        x * math.cos(angle) + z * math.sin(angle),
        y,
        -x * math.sin(angle) + z * math.cos(angle),
    )


def _layout(
    params: dict,
) -> tuple[
    float,
    float,
    float,
    int,
    tuple[float, float, float],
    float,
    list[tuple[float, float, float]],
]:
    height, reach, tilt, cameras = _parameters(params)
    pivot = (reach, 0.0, height - PROFILE_MM * 2)
    rail_span = max(PROFILE_MM * 3, (cameras - 1) * CAMERA_SPACING_MM + SEAT_WIDTH_MM)
    y_positions = [(index - (cameras - 1) / 2) * CAMERA_SPACING_MM for index in range(cameras)]
    mount_local_x = PROFILE_MM * 0.72
    mount_local_z = -PROFILE_MM / 2 - SEAT_THICKNESS_MM
    mounts = []
    for y in y_positions:
        offset = _rotate_y((mount_local_x, y, mount_local_z), tilt)
        mounts.append(tuple(pivot[index] + offset[index] for index in range(3)))
    return height, reach, tilt, cameras, pivot, rail_span, mounts


def _add(
    assembly: cq.Assembly,
    shape: cq.Shape | cq.Workplane,
    name: str,
    color: cq.Color,
    link: str = "base",
) -> None:
    assembly.add(shape, name=name, color=color, metadata={"link": link})


def build(params: dict) -> cq.Assembly:
    height, reach, tilt, cameras, pivot, rail_span, _mounts = _layout(params)
    assembly = cq.Assembly(name="camera_station")
    _add(
        assembly,
        cq.Workplane("XY")
        .box(BASE_SIZE_MM, BASE_SIZE_MM, BASE_THICKNESS_MM)
        .translate((0, 0, BASE_THICKNESS_MM / 2)),
        "floor_base",
        BASE_DARK,
    )
    _add(
        assembly,
        cq.Workplane("XY")
        .box(PROFILE_MM, PROFILE_MM, height - BASE_THICKNESS_MM)
        .translate((0, 0, BASE_THICKNESS_MM + (height - BASE_THICKNESS_MM) / 2)),
        "vertical_post",
        ALUMINIUM,
    )
    _add(
        assembly,
        cq.Workplane("XY")
        .box(reach, PROFILE_MM, PROFILE_MM)
        .translate((reach / 2, 0, height - PROFILE_MM / 2)),
        "reach_beam",
        ALUMINIUM,
    )
    _add(
        assembly,
        cq.Workplane("XY")
        .box(PROFILE_MM, PROFILE_MM * 1.4, PROFILE_MM * 2)
        .translate((reach - PROFILE_MM / 2, 0, height - PROFILE_MM * 1.5)),
        "head_drop_bracket",
        BASE_DARK,
    )

    rail = (
        cq.Workplane("XY")
        .box(PROFILE_MM, rail_span, PROFILE_MM)
        .translate(pivot)
        .rotate(pivot, (pivot[0], pivot[1] + 1, pivot[2]), tilt)
    )
    _add(assembly, rail, "tilt_camera_rail", HEAD_BLUE, "camera_head")
    shaft = cq.Solid.makeCylinder(
        PROFILE_MM * 0.30,
        rail_span + PROFILE_MM * 0.25,
        cq.Vector(pivot[0], pivot[1] - rail_span / 2 - PROFILE_MM * 0.125, pivot[2]),
        cq.Vector(0, 1, 0),
    )
    _add(assembly, shaft, "tilt_shaft", SEAT_GREY, "camera_head")

    y_positions = [(index - (cameras - 1) / 2) * CAMERA_SPACING_MM for index in range(cameras)]
    local_x = PROFILE_MM * 0.72
    local_z = -PROFILE_MM / 2 - SEAT_THICKNESS_MM / 2
    for index, y in enumerate(y_positions):
        center = (pivot[0] + local_x, pivot[1] + y, pivot[2] + local_z)
        seat = (
            cq.Workplane("XY")
            .box(SEAT_LENGTH_MM, SEAT_WIDTH_MM, SEAT_THICKNESS_MM)
            .translate(center)
            .rotate(pivot, (pivot[0], pivot[1] + 1, pivot[2]), tilt)
        )
        _add(assembly, seat, f"camera_seat_{index}", SEAT_GREY, "camera_head")
    return assembly


def module_definition(params: dict) -> ModuleDef:
    _height, _reach, tilt, _cameras, pivot, _rail_span, mounts = _layout(params)
    frames = {"mount": Frame(link="floor_base")}
    frames.update(
        {
            f"cam_{index}.mount": Frame(
                xyz=position,
                rpy_deg=(180, tilt, 0),
                link="camera_head",
            )
            for index, position in enumerate(mounts)
        }
    )
    return ModuleDef(
        id="camera_station",
        params_schema=MODULE.params_schema,
        frames=frames,
        axes=[
            {
                "id": "tilt",
                "type": "revolute",
                "parent": "base",
                "child": "camera_head",
                "origin": {"xyz": pivot, "rpy_deg": (0, tilt, 0)},
                "axis": (0, 1, 0),
                "range_deg": (-45, 45),
                "max_speed_dps": 45,
            }
        ],
        collision="hull",
        meta=ModuleMeta(basis=CAMERA_STATION_BASIS),
    )


MODULE = ModuleDef(
    id="camera_station",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "height_mm": {
                "type": "number",
                "minimum": 900,
                "maximum": 2800,
                "default": 1600,
            },
            "reach_mm": {
                "type": "number",
                "minimum": 300,
                "maximum": 1400,
                "default": 650,
            },
            "tilt_deg": {
                "type": "number",
                "minimum": -45,
                "maximum": 45,
                "default": 20,
            },
            "cameras": {
                "type": "integer",
                "minimum": 1,
                "maximum": 4,
                "default": 2,
            },
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(), "cam_0.mount": Frame(link="camera_head")},
    axes=[
        {
            "id": "tilt",
            "type": "revolute",
            "parent": "base",
            "child": "camera_head",
            "axis": (0, 1, 0),
            "range_deg": (-45, 45),
            "max_speed_dps": 45,
        }
    ],
    collision="hull",
    meta=ModuleMeta(basis=CAMERA_STATION_BASIS),
)
