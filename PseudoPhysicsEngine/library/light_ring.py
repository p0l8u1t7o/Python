"""Parametric coaxial ring light for machine-vision imaging."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

HOUSING_BLACK = cq.Color(0.08, 0.09, 0.10)
DIFFUSER_WHITE = cq.Color(0.92, 0.94, 0.90)
CONNECTOR_GREY = cq.Color(0.34, 0.37, 0.40)

HOUSING_DEPTH_MM = 22.0
DIFFUSER_DEPTH_MM = 3.0


def _parameters(params: dict) -> tuple[float, float]:
    return float(params.get("outer_d_mm", 220)), float(params.get("inner_d_mm", 120))


def build(params: dict) -> cq.Assembly:
    outer_d, inner_d = _parameters(params)
    if inner_d >= outer_d:
        raise ValueError("inner_d_mm 必須小於 outer_d_mm")
    assembly = cq.Assembly(name="light_ring")
    housing = cq.Workplane("XY").circle(outer_d / 2).circle(inner_d / 2).extrude(HOUSING_DEPTH_MM)
    assembly.add(housing, name="ring_housing", color=HOUSING_BLACK)
    diffuser = (
        cq.Workplane("XY", origin=(0, 0, HOUSING_DEPTH_MM - DIFFUSER_DEPTH_MM))
        .circle(outer_d * 0.46)
        .circle(inner_d * 0.54)
        .extrude(DIFFUSER_DEPTH_MM)
    )
    assembly.add(diffuser, name="annular_diffuser", color=DIFFUSER_WHITE)
    connector_size = min((outer_d - inner_d) * 0.28, HOUSING_DEPTH_MM * 0.9)
    connector = (
        cq.Workplane("XY")
        .box(connector_size, connector_size, HOUSING_DEPTH_MM * 0.68)
        .translate((0, outer_d / 2 - connector_size / 2, HOUSING_DEPTH_MM * 0.34))
    )
    assembly.add(connector, name="power_connector", color=CONNECTOR_GREY)
    return assembly


def module_definition(params: dict) -> ModuleDef:
    _outer_d, _inner_d = _parameters(params)
    return ModuleDef(
        id="light_ring",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(link="ring_housing", free_space=True),
            "emit": Frame(
                xyz=(0, 0, HOUSING_DEPTH_MM),
                rpy_deg=(180, 0, 0),
                link="annular_diffuser",
                free_space=True,
            ),
        },
        collision="mesh",
        meta=ModuleMeta(
            basis="依一般同軸機器視覺環形光源的外徑、中央通光孔與薄型散光罩比例作工程推估"
        ),
    )


MODULE = ModuleDef(
    id="light_ring",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "outer_d_mm": {
                "type": "number",
                "minimum": 160,
                "maximum": 400,
                "default": 220,
            },
            "inner_d_mm": {
                "type": "number",
                "minimum": 50,
                "maximum": 140,
                "default": 120,
            },
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(free_space=True), "emit": Frame(free_space=True)},
    collision="mesh",
    meta=ModuleMeta(basis="依一般同軸機器視覺環形光源的外徑、中央通光孔與薄型散光罩比例作工程推估"),
)
