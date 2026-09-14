"""Block-level conveyor module."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef


def build(params: dict) -> cq.Assembly:
    length = float(params.get("length_mm", 1600))
    width = float(params.get("width_mm", 600))
    height = float(params.get("height_mm", 760))
    result = cq.Assembly(name=params.get("name", "conveyor"))
    deck = cq.Workplane("XY").box(length, width, 80).translate((0, 0, height))
    result.add(deck, name="deck", color=cq.Color(0.18, 0.23, 0.27))
    for x in (-length * 0.42, length * 0.42):
        for y in (-width * 0.38, width * 0.38):
            leg = cq.Workplane("XY").box(60, 60, height).translate((x, y, height / 2))
            result.add(leg, name=f"leg_{'p' if x > 0 else 'n'}x_{'p' if y > 0 else 'n'}y")
    return result


MODULE = ModuleDef(
    id="conveyor",
    params_schema={"type": "object"},
    frames={"mount": Frame(), "transfer": Frame(xyz=(0, 0, 800))},
    axes=[{"id": "belt", "type": "prismatic", "range_mm": [0, 1600], "max_speed_mm_s": 500}],
    collision="box",
)
