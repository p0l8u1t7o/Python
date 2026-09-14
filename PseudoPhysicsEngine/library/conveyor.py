"""Block-level conveyor module."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef


def build(params: dict) -> cq.Assembly:
    length = float(params.get("length_mm", 1600))
    width = float(params.get("width_mm", 600))
    height = float(params.get("height_mm", 760))
    result = cq.Assembly(name=params.get("name", "conveyor"))
    deck = cq.Workplane("XY").box(length, width, 70).translate((0, 0, height))
    result.add(deck, name="deck", color=cq.Color(0.18, 0.23, 0.27))
    belt = cq.Workplane("XY").box(length, width - 30, 10).translate((0, 0, height + 40))
    result.add(belt, name="belt", color=cq.Color(0.08, 0.1, 0.12))
    for x in (-length * 0.42, length * 0.42):
        for y in (-width * 0.38, width * 0.38):
            leg = cq.Workplane("XY").box(60, 60, height).translate((x, y, height / 2))
            result.add(
                leg,
                name=f"leg_{'p' if x > 0 else 'n'}x_{'p' if y > 0 else 'n'}y",
                color=cq.Color(0.32, 0.37, 0.4),
            )
    return result


def module_definition(params: dict) -> ModuleDef:
    length = float(params.get("length_mm", 1600))
    height = float(params.get("height_mm", 760))
    surface = height + 45.0
    speed = float(params.get("speed_mm_s", 300))
    return ModuleDef(
        id="conveyor",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(),
            "start": Frame(xyz=(-length / 2 + 150, 0, surface)),
            "end": Frame(xyz=(length / 2 - 150, 0, surface)),
            "stop": Frame(xyz=(0, 0, surface)),
        },
        axes=[
            {
                "id": "belt",
                "type": "prismatic",
                "parent": "base",
                "child": "belt",
                "axis": [1, 0, 0],
                "range_mm": [0, length],
                "max_speed_mm_s": speed,
            }
        ],
        collision="box",
    )


MODULE = ModuleDef(
    id="conveyor",
    params_schema={"type": "object"},
    frames={
        "mount": Frame(),
        "start": Frame(xyz=(-650, 0, 805)),
        "end": Frame(xyz=(650, 0, 805)),
        "stop": Frame(xyz=(0, 0, 805)),
    },
    axes=[
        {
            "id": "belt",
            "type": "prismatic",
            "axis": [1, 0, 0],
            "range_mm": [0, 1600],
            "max_speed_mm_s": 300,
        }
    ],
    collision="box",
)
