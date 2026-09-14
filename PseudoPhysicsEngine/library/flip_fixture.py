"""Reusable guarded 180-degree product turnover fixture."""

import cadquery as cq

from cellforge.schema import Frame, ModuleDef


def build(params: dict) -> cq.Assembly:
    width = float(params.get("width_mm", 450))
    assembly = cq.Assembly(name="flip_fixture")
    assembly.add(
        cq.Workplane("XY").box(width + 180, 500, 50), name="base", color=cq.Color(0.22, 0.28, 0.33)
    )
    moving = cq.Compound.makeCompound(
        [
            cq.Workplane("YZ").cylinder(width, 35).translate((-width / 2, 0, 240)).val(),
            cq.Workplane("XY").box(width, 340, 24).translate((0, 0, 240)).val(),
        ]
    )
    assembly.add(
        moving,
        name="nest",
        color=cq.Color(0.25, 0.45, 0.55),
    )
    return assembly


MODULE = ModuleDef(
    id="flip_fixture",
    params_schema={"type": "object"},
    frames={"base": Frame(), "nest": Frame(link="nest")},
    axes=[
        {
            "id": "flip",
            "type": "revolute",
            "parent": "base",
            "child": "nest",
            "origin": {"xyz": [0, 0, 240]},
            "axis": [1, 0, 0],
            "range_deg": [0, 180],
        }
    ],
    collision="hull",
    payload_kg=15,
)
