"""Parametric red-amber-green industrial signal tower."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

BASE_DARK = cq.Color(0.08, 0.09, 0.10)
POLE_GREY = cq.Color(0.48, 0.51, 0.54)
LENS_COLORS = (
    ("red", cq.Color(0.90, 0.05, 0.04, 0.82)),
    ("amber", cq.Color(1.00, 0.55, 0.02, 0.82)),
    ("green", cq.Color(0.08, 0.72, 0.18, 0.82)),
)

BASE_RADIUS_MM = 45.0
BASE_HEIGHT_MM = 14.0
POLE_RADIUS_MM = 11.0
POLE_HEIGHT_MM = 110.0
LENS_RADIUS_MM = 32.0
LENS_HEIGHT_MM = 44.0
SEPARATOR_HEIGHT_MM = 5.0

SIGNAL_TOWER_BASIS = (
    "依一般產線三色警示燈的四十五毫米級底座、支桿與層疊透光罩比例作工程推估；"
    "燈罩由下而上固定採紅、黃、綠的常用機台狀態順序。"
)


def _parameters(params: dict) -> int:
    return int(params.get("tiers", 3))


def build(params: dict) -> cq.Assembly:
    tiers = _parameters(params)
    assembly = cq.Assembly(name="signal_tower")
    assembly.add(
        cq.Solid.makeCylinder(BASE_RADIUS_MM, BASE_HEIGHT_MM),
        name="mounting_base",
        color=BASE_DARK,
    )
    assembly.add(
        cq.Solid.makeCylinder(
            POLE_RADIUS_MM,
            POLE_HEIGHT_MM,
            cq.Vector(0, 0, BASE_HEIGHT_MM),
            cq.Vector(0, 0, 1),
        ),
        name="support_pole",
        color=POLE_GREY,
    )
    lens_start = BASE_HEIGHT_MM + POLE_HEIGHT_MM
    for index, (color_name, color) in enumerate(LENS_COLORS[:tiers]):
        z = lens_start + index * (LENS_HEIGHT_MM + SEPARATOR_HEIGHT_MM)
        assembly.add(
            cq.Solid.makeCylinder(
                LENS_RADIUS_MM,
                LENS_HEIGHT_MM,
                cq.Vector(0, 0, z),
                cq.Vector(0, 0, 1),
            ),
            name=f"lens_{index}_{color_name}",
            color=color,
        )
        assembly.add(
            cq.Solid.makeCylinder(
                LENS_RADIUS_MM * 1.04,
                SEPARATOR_HEIGHT_MM,
                cq.Vector(0, 0, z + LENS_HEIGHT_MM),
                cq.Vector(0, 0, 1),
            ),
            name=f"separator_{index}",
            color=BASE_DARK,
        )
    cap_z = lens_start + tiers * (LENS_HEIGHT_MM + SEPARATOR_HEIGHT_MM)
    assembly.add(
        cq.Solid.makeCylinder(
            LENS_RADIUS_MM * 1.04,
            SEPARATOR_HEIGHT_MM,
            cq.Vector(0, 0, cap_z),
            cq.Vector(0, 0, 1),
        ),
        name="top_cap",
        color=BASE_DARK,
    )
    return assembly


MODULE = ModuleDef(
    id="signal_tower",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "tiers": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
                "default": 3,
            }
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(link="mounting_base")},
    collision="hull",
    meta=ModuleMeta(basis=SIGNAL_TOWER_BASIS),
)
