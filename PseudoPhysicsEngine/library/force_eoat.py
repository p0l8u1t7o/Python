"""Reusable force-limited cover-opening end effector."""

import cadquery as cq

from cellforge.schema import Frame, ModuleDef


def build(params: dict) -> cq.Assembly:
    stroke = float(params.get("stroke_mm", 30))
    assembly = cq.Assembly(name="force_eoat")
    assembly.add(
        cq.Workplane("XY").cylinder(45, 42), name="force_sensor", color=cq.Color(0.2, 0.25, 0.3)
    )
    assembly.add(
        cq.Workplane("XY").box(65, 45, 70).translate((0, 0, 75)),
        name="compliance",
        color=cq.Color(0.9, 0.55, 0.12),
    )
    assembly.add(
        cq.Workplane("XY").box(18, 42, stroke).translate((0, 0, 125)),
        name="soft_finger",
        color=cq.Color(0.12, 0.12, 0.14),
    )
    return assembly


MODULE = ModuleDef(
    id="force_eoat",
    params_schema={
        "type": "object",
        "properties": {
            "stroke_mm": {"type": "number", "minimum": 5},
            "force_limit_n": {"type": "number", "minimum": 0.1},
        },
    },
    frames={"flange": Frame(), "tool_center_point": Frame(xyz=(0, 0, 140))},
    axes=[{"id": "compliance", "type": "prismatic", "range_mm": [0, 30]}],
    collision="box",
    payload_kg=1.2,
)
