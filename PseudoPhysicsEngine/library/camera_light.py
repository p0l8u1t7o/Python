"""Reusable AOI camera and diffuse lighting head."""

import cadquery as cq

from cellforge.schema import Frame, ModuleDef


def build(params: dict) -> cq.Assembly:
    assembly = cq.Assembly(name="camera_light")
    assembly.add(
        cq.Workplane("XY").box(140, 100, 80), name="camera", color=cq.Color(0.08, 0.1, 0.12)
    )
    assembly.add(
        cq.Workplane("XY")
        .box(300, 260, 18)
        .cut(cq.Workplane("XY").box(210, 170, 30))
        .translate((0, 0, -55)),
        name="light",
        color=cq.Color(0.88, 0.9, 0.82),
    )
    return assembly


MODULE = ModuleDef(
    id="camera_light",
    params_schema={"type": "object"},
    frames={"mount": Frame(), "optical": Frame(xyz=(0, 0, -80))},
    collision="box",
)
