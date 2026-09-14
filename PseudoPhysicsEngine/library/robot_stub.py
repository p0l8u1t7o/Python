"""Block-level six-axis robot placeholder."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef


def build(params: dict) -> cq.Assembly:
    reach = float(params.get("reach_mm", 905))
    result = cq.Assembly(name=params.get("name", "robot_stub"))
    base = cq.Workplane("XY").cylinder(100, 150)
    shoulder = cq.Workplane("XY").box(180, 180, 260).translate((0, 0, 230))
    upper = cq.Workplane("YZ").cylinder(reach * 0.43, 75).translate((0, 0, 360))
    forearm = cq.Workplane("YZ").cylinder(reach * 0.42, 55).translate((reach * 0.43, 0, 360))
    result.add(base, name="base", color=cq.Color(0.82, 0.82, 0.85))
    result.add(shoulder, name="shoulder", color=cq.Color(0.73, 0.08, 0.08))
    result.add(upper, name="upper_arm", color=cq.Color(0.76, 0.1, 0.1))
    result.add(forearm, name="forearm", color=cq.Color(0.82, 0.82, 0.85))
    return result


MODULE = ModuleDef(
    id="robot_stub",
    params_schema={"type": "object"},
    frames={"base": Frame(), "flange": Frame(xyz=(905, 0, 360))},
    axes=[{"id": f"j{i}", "type": "revolute", "range_deg": [-180, 180]} for i in range(1, 7)],
    collision="hull",
    payload_kg=7,
)
