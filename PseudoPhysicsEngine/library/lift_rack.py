"""Block-level lift rack module."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef


def build(params: dict) -> cq.Assembly:
    levels = int(params.get("levels", 6))
    pitch = float(params.get("pitch_mm", 90))
    width = float(params.get("width_mm", 650))
    depth = float(params.get("depth_mm", 500))
    result = cq.Assembly(name=params.get("name", "lift_rack"))
    shelves = []
    for level in range(levels):
        z = 120 + level * pitch
        shelves.append(cq.Workplane("XY").box(width, depth, 20).translate((0, 0, z)).val())
    result.add(cq.Compound.makeCompound(shelves), name="lift", color=cq.Color(0.32, 0.38, 0.43))
    height = 240 + (levels - 1) * pitch
    for x in (-width / 2, width / 2):
        for y in (-depth / 2, depth / 2):
            post = cq.Workplane("XY").box(40, 40, height).translate((x, y, height / 2))
            result.add(post, name=f"post_{len(result.objects)}")
    return result


def module_definition(params: dict) -> ModuleDef:
    levels = int(params.get("levels", 6))
    pitch = float(params.get("pitch_mm", 90))
    slots = {
        f"slot_{index}": Frame(xyz=(0, 0, 130 + index * pitch), link="lift")
        for index in range(levels)
    }
    return ModuleDef(
        id="lift_rack",
        params_schema=MODULE.params_schema,
        frames={"mount": Frame(), **slots, "top": slots[f"slot_{levels - 1}"]},
        axes=[
            {
                "id": "lift",
                "type": "prismatic",
                "parent": "base",
                "child": "lift",
                "axis": [0, 0, 1],
                "range_mm": [0, max(0.0, (levels - 1) * pitch)],
                "max_speed_mm_s": float(params.get("max_speed_mm_s", 200)),
            }
        ],
        collision="box",
    )


MODULE = ModuleDef(
    id="lift_rack",
    params_schema={"type": "object"},
    frames={"mount": Frame(), "slot_0": Frame(xyz=(0, 0, 130)), "top": Frame(xyz=(0, 0, 580))},
    axes=[{"id": "lift", "type": "prismatic", "range_mm": [0, 480], "max_speed_mm_s": 200}],
    collision="box",
)
