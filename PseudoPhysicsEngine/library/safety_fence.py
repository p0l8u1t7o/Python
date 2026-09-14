"""Reusable perimeter guarding segment."""

import cadquery as cq

from cellforge.schema import Frame, ModuleDef


def build(params: dict) -> cq.Assembly:
    length = float(params.get("length_mm", 2000))
    height = float(params.get("height_mm", 1800))
    assembly = cq.Assembly(name="safety_fence")
    assembly.add(
        cq.Workplane("XY").box(50, 50, height).translate((-length / 2, 0, height / 2)),
        name="post_left",
        color=cq.Color(0.95, 0.72, 0.1),
    )
    assembly.add(
        cq.Workplane("XY").box(50, 50, height).translate((length / 2, 0, height / 2)),
        name="post_right",
        color=cq.Color(0.95, 0.72, 0.1),
    )
    assembly.add(
        cq.Workplane("XY").box(length, 12, height - 100).translate((0, 0, height / 2)),
        name="mesh_panel",
        color=cq.Color(0.25, 0.28, 0.3),
    )
    return assembly


MODULE = ModuleDef(
    id="safety_fence", params_schema={"type": "object"}, frames={"base": Frame()}, collision="box"
)
