"""Parametric post-and-crossbeam bracket for an industrial camera."""

from __future__ import annotations

import math

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

ALUMINIUM = cq.Color(0.70, 0.72, 0.74)
BRACKET_DARK = cq.Color(0.14, 0.16, 0.18)
SEAT_BLUE = cq.Color(0.16, 0.34, 0.52)

PROFILE_MM = 40.0
BASE_SIZE_MM = 120.0
BASE_THICKNESS_MM = 12.0
SEAT_LENGTH_MM = 86.0
SEAT_WIDTH_MM = 110.0
SEAT_THICKNESS_MM = 16.0


def _parameters(params: dict) -> tuple[float, float, float]:
    return (
        float(params.get("height_mm", 1200)),
        float(params.get("reach_mm", 500)),
        float(params.get("tilt_deg", 15)),
    )


def _seat_layout(params: dict) -> tuple[float, float, float, tuple[float, float, float]]:
    height, reach, tilt = _parameters(params)
    pivot = (reach, 0.0, height - PROFILE_MM - SEAT_THICKNESS_MM / 2)
    angle = math.radians(tilt)
    normal_offset = SEAT_THICKNESS_MM / 2
    optical = (
        pivot[0] - normal_offset * math.sin(angle),
        pivot[1],
        pivot[2] - normal_offset * math.cos(angle),
    )
    return height, reach, tilt, optical


def build(params: dict) -> cq.Assembly:
    height, reach, tilt, _optical = _seat_layout(params)
    assembly = cq.Assembly(name="camera_bracket")
    assembly.add(
        cq.Workplane("XY")
        .box(BASE_SIZE_MM, BASE_SIZE_MM, BASE_THICKNESS_MM)
        .translate((0, 0, BASE_THICKNESS_MM / 2)),
        name="base_plate",
        color=BRACKET_DARK,
    )
    assembly.add(
        cq.Workplane("XY")
        .box(PROFILE_MM, PROFILE_MM, height - BASE_THICKNESS_MM)
        .translate((0, 0, BASE_THICKNESS_MM + (height - BASE_THICKNESS_MM) / 2)),
        name="vertical_post",
        color=ALUMINIUM,
    )
    assembly.add(
        cq.Workplane("XY")
        .box(reach, PROFILE_MM, PROFILE_MM)
        .translate((reach / 2, 0, height - PROFILE_MM / 2)),
        name="cross_beam",
        color=ALUMINIUM,
    )
    pivot = (reach, 0.0, height - PROFILE_MM - SEAT_THICKNESS_MM / 2)
    seat = (
        cq.Workplane("XY")
        .box(SEAT_LENGTH_MM, SEAT_WIDTH_MM, SEAT_THICKNESS_MM)
        .translate(pivot)
        .rotate(pivot, (pivot[0], pivot[1] + 1, pivot[2]), tilt)
    )
    assembly.add(seat, name="camera_seat", color=SEAT_BLUE)
    gusset = (
        cq.Workplane("XY")
        .box(PROFILE_MM * 1.5, PROFILE_MM * 0.65, PROFILE_MM * 1.5)
        .translate((PROFILE_MM * 0.45, 0, height - PROFILE_MM * 1.15))
    )
    assembly.add(gusset, name="beam_gusset", color=BRACKET_DARK)
    return assembly


def module_definition(params: dict) -> ModuleDef:
    _height, _reach, tilt, optical = _seat_layout(params)
    return ModuleDef(
        id="camera_bracket",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(link="base_plate"),
            "camera_mount": Frame(xyz=optical, rpy_deg=(180, tilt, 0), link="camera_seat"),
            "optical": Frame(xyz=optical, rpy_deg=(180, tilt, 0), link="camera_seat"),
        },
        collision="box",
        meta=ModuleMeta(
            basis=(
                "依一般機器視覺站鋁擠立柱、懸臂橫樑與工業相機調角座比例作工程推估，"
                "供 Getac 外觀取像配置"
            )
        ),
    )


MODULE = ModuleDef(
    id="camera_bracket",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "height_mm": {
                "type": "number",
                "minimum": 500,
                "maximum": 2500,
                "default": 1200,
            },
            "reach_mm": {
                "type": "number",
                "minimum": 200,
                "maximum": 1200,
                "default": 500,
            },
            "tilt_deg": {
                "type": "number",
                "minimum": -45,
                "maximum": 45,
                "default": 15,
            },
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(), "camera_mount": Frame(), "optical": Frame()},
    collision="box",
    meta=ModuleMeta(
        basis=(
            "依一般機器視覺站鋁擠立柱、懸臂橫樑與工業相機調角座比例作工程推估，"
            "供 Getac 外觀取像配置"
        )
    ),
)
