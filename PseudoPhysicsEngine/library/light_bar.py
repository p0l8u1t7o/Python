"""Parametric adjustable bar light for machine-vision imaging."""

from __future__ import annotations

import math

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

HOUSING_BLACK = cq.Color(0.08, 0.09, 0.10)
DIFFUSER_WHITE = cq.Color(0.94, 0.95, 0.90)
END_CAP_GREY = cq.Color(0.32, 0.35, 0.38)
BRACKET_BLUE = cq.Color(0.16, 0.34, 0.52)

BAR_WIDTH_MM = 48.0
BAR_DEPTH_MM = 28.0
DIFFUSER_DEPTH_MM = 3.0
END_CAP_LENGTH_MM = 12.0


def _parameters(params: dict) -> tuple[float, float]:
    return float(params.get("length_mm", 400)), float(params.get("angle_deg", 20))


def _rotate(shape: cq.Workplane, angle_deg: float) -> cq.Workplane:
    return shape.rotate((0, 0, 0), (0, 1, 0), angle_deg)


def build(params: dict) -> cq.Assembly:
    length, angle = _parameters(params)
    assembly = cq.Assembly(name="light_bar")
    housing = (
        cq.Workplane("XY")
        .box(length, BAR_WIDTH_MM, BAR_DEPTH_MM)
        .translate((0, 0, -BAR_DEPTH_MM / 2))
    )
    assembly.add(_rotate(housing, angle), name="bar_housing", color=HOUSING_BLACK)
    diffuser = (
        cq.Workplane("XY")
        .box(length - 2 * END_CAP_LENGTH_MM, BAR_WIDTH_MM * 0.76, DIFFUSER_DEPTH_MM)
        .translate((0, 0, -BAR_DEPTH_MM + DIFFUSER_DEPTH_MM / 2))
    )
    assembly.add(_rotate(diffuser, angle), name="linear_diffuser", color=DIFFUSER_WHITE)
    for side, x in (
        ("left", -(length - END_CAP_LENGTH_MM) / 2),
        ("right", (length - END_CAP_LENGTH_MM) / 2),
    ):
        cap = (
            cq.Workplane("XY")
            .box(END_CAP_LENGTH_MM, BAR_WIDTH_MM, BAR_DEPTH_MM)
            .translate((x, 0, -BAR_DEPTH_MM / 2))
        )
        assembly.add(_rotate(cap, angle), name=f"end_cap_{side}", color=END_CAP_GREY)
    bracket = (
        cq.Workplane("XY")
        .box(BAR_WIDTH_MM, BAR_WIDTH_MM * 0.45, BAR_DEPTH_MM * 0.32)
        .translate((0, 0, BAR_DEPTH_MM * 0.16))
    )
    assembly.add(bracket, name="mounting_bracket", color=BRACKET_BLUE)
    return assembly


def module_definition(params: dict) -> ModuleDef:
    _length, angle = _parameters(params)
    angle_rad = math.radians(angle)
    emit = (-BAR_DEPTH_MM * math.sin(angle_rad), 0.0, -BAR_DEPTH_MM * math.cos(angle_rad))
    return ModuleDef(
        id="light_bar",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(link="mounting_bracket"),
            "emit": Frame(xyz=emit, rpy_deg=(180, angle, 0), link="linear_diffuser"),
        },
        collision="hull",
        meta=ModuleMeta(
            basis="依一般 AOI 條形 LED 光源鋁殼、線性散光面與可調角安裝座比例作工程推估"
        ),
    )


MODULE = ModuleDef(
    id="light_bar",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "length_mm": {
                "type": "number",
                "minimum": 120,
                "maximum": 1200,
                "default": 400,
            },
            "angle_deg": {
                "type": "number",
                "minimum": -60,
                "maximum": 60,
                "default": 20,
            },
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(), "emit": Frame()},
    collision="hull",
    meta=ModuleMeta(basis="依一般 AOI 條形 LED 光源鋁殼、線性散光面與可調角安裝座比例作工程推估"),
)
