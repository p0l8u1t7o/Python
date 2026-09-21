"""Generic block-level module."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

BOX_BASIS = "依案內尚未定義的外形包絡需求建立通用佔位體，僅供早期配置與空間預留"


def build(params: dict) -> cq.Assembly:
    size = params.get("size", [500, 500, 500])
    color = cq.Color(*params.get("color", [0.55, 0.62, 0.68]))
    solid = cq.Workplane("XY").box(float(size[0]), float(size[1]), float(size[2]))
    result = cq.Assembly(name=params.get("name", "box"))
    result.add(solid, name="body", color=color)
    return result


def module_definition(params: dict) -> ModuleDef:
    size = params.get("size", [500, 500, 500])
    return ModuleDef(
        id="box",
        params_schema=MODULE.params_schema,
        frames={"mount": Frame(), "top": Frame(xyz=(0, 0, float(size[2]) / 2))},
        collision="box",
        meta=ModuleMeta(basis=BOX_BASIS, placeholder=True),
    )


MODULE = ModuleDef(
    id="box",
    params_schema={
        "type": "object",
        "properties": {
            "size": {"type": "array", "minItems": 3, "maxItems": 3},
            "color": {"type": "array", "minItems": 3, "maxItems": 3},
        },
    },
    frames={"mount": Frame(), "top": Frame(xyz=(0, 0, 250))},
    collision="box",
    meta=ModuleMeta(basis=BOX_BASIS, placeholder=True),
)
