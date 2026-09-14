"""Generic block-level module."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef


def build(params: dict) -> cq.Assembly:
    size = params.get("size", [500, 500, 500])
    color = cq.Color(*params.get("color", [0.55, 0.62, 0.68]))
    solid = cq.Workplane("XY").box(float(size[0]), float(size[1]), float(size[2]))
    result = cq.Assembly(name=params.get("name", "box"))
    result.add(solid, name="body", color=color)
    return result


MODULE = ModuleDef(
    id="box",
    params_schema={
        "type": "object",
        "properties": {
            "size": {"type": "array", "minItems": 3, "maxItems": 3},
            "color": {"type": "array", "minItems": 3, "maxItems": 3},
        },
    },
    frames={"mount": Frame()},
    collision="box",
)
