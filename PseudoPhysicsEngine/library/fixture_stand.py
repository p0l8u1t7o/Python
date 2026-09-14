"""Floor-standing inspection fixture with a workpiece-height top plate."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef


def build(params: dict) -> cq.Assembly:
    top_size = [float(value) for value in params.get("top_size", [300, 220, 10])]
    top_height = float(params.get("top_height_mm", 805))
    column_size = [float(value) for value in params.get("column_size", [90, 90])]
    foot_size = [float(value) for value in params.get("foot_size", [180, 160, 12])]
    top_thickness = top_size[2]
    column_bottom = foot_size[2]
    column_top = top_height - top_thickness
    if column_top <= column_bottom:
        raise ValueError("治具頂面高度必須高於底座與頂板厚度")

    assembly = cq.Assembly(name=params.get("name", "fixture_stand"))
    assembly.add(
        cq.Workplane("XY").box(*foot_size).translate((0, 0, foot_size[2] / 2)),
        name="foot",
        color=cq.Color(0.22, 0.27, 0.31),
    )
    assembly.add(
        cq.Workplane("XY")
        .box(column_size[0], column_size[1], column_top - column_bottom)
        .translate((0, 0, (column_bottom + column_top) / 2)),
        name="column",
        color=cq.Color(0.42, 0.48, 0.53),
    )
    assembly.add(
        cq.Workplane("XY").box(*top_size).translate((0, 0, top_height - top_thickness / 2)),
        name="top_plate",
        color=cq.Color(0.16, 0.2, 0.23),
    )
    return assembly


def module_definition(params: dict) -> ModuleDef:
    top_height = float(params.get("top_height_mm", 805))
    return ModuleDef(
        id="fixture_stand",
        params_schema=MODULE.params_schema,
        frames={"mount": Frame(), "top": Frame(xyz=(0, 0, top_height))},
        collision="hull",
    )


MODULE = ModuleDef(
    id="fixture_stand",
    params_schema={
        "type": "object",
        "properties": {
            "top_size": {
                "type": "array",
                "prefixItems": [{"type": "number"}] * 3,
                "minItems": 3,
                "maxItems": 3,
            },
            "top_height_mm": {"type": "number", "exclusiveMinimum": 0},
            "column_size": {
                "type": "array",
                "prefixItems": [{"type": "number"}] * 2,
                "minItems": 2,
                "maxItems": 2,
            },
            "foot_size": {
                "type": "array",
                "prefixItems": [{"type": "number"}] * 3,
                "minItems": 3,
                "maxItems": 3,
            },
        },
    },
    frames={"mount": Frame(), "top": Frame(xyz=(0, 0, 805))},
    collision="hull",
)
