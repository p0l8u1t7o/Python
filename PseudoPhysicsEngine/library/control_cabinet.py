"""Parametric floor-standing electrical control cabinet."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

CABINET_GREY = cq.Color(0.62, 0.65, 0.67)
DOOR_GREY = cq.Color(0.72, 0.74, 0.75)
PLINTH_DARK = cq.Color(0.12, 0.14, 0.16)
HANDLE_BLACK = cq.Color(0.05, 0.06, 0.07)
VENT_BLUE = cq.Color(0.18, 0.31, 0.40)

CONTROL_CABINET_BASIS = (
    "依一般產線落地式電控箱的鈑金櫃體、前門、底座、門把及散熱百葉比例作工程推估；"
    "外廓尺寸供配置與安全間距檢查，不展開內部電器製造細節。"
)


def _parameters(params: dict) -> tuple[float, float, float]:
    size = params.get("size_mm", [600, 300, 1000])
    return tuple(float(value) for value in size)


def build(params: dict) -> cq.Assembly:
    width, depth, height = _parameters(params)
    assembly = cq.Assembly(name="control_cabinet")
    door_thickness = max(depth * 0.04, 8.0)
    body_depth = depth - door_thickness
    assembly.add(
        cq.Workplane("XY")
        .box(width, body_depth, height)
        .translate((0, door_thickness / 2, height / 2)),
        name="cabinet_body",
        color=CABINET_GREY,
    )
    assembly.add(
        cq.Workplane("XY")
        .box(width * 0.94, door_thickness, height * 0.92)
        .translate((0, -depth / 2 + door_thickness / 2, height * 0.52)),
        name="front_door",
        color=DOOR_GREY,
    )

    plinth_height = height * 0.08
    assembly.add(
        cq.Workplane("XY")
        .box(width * 0.88, depth * 0.82, plinth_height)
        .translate((0, 0, plinth_height / 2)),
        name="floor_plinth",
        color=PLINTH_DARK,
    )
    assembly.add(
        cq.Workplane("XY")
        .box(width * 0.035, door_thickness * 0.55, height * 0.16)
        .translate(
            (
                width * 0.38,
                -depth / 2 + door_thickness * 0.35,
                height * 0.55,
            )
        ),
        name="recessed_handle",
        color=HANDLE_BLACK,
    )

    vent_width = width * 0.42
    vent_height = height * 0.035
    for index, z in enumerate((height * 0.18, height * 0.23, height * 0.28)):
        assembly.add(
            cq.Workplane("XY")
            .box(vent_width, door_thickness * 0.32, vent_height)
            .translate((0, -depth / 2 + door_thickness * 0.18, z)),
            name=f"vent_louver_{index}",
            color=VENT_BLUE,
        )
    hinge_size = min(width, height) * 0.035
    for name, z in (("lower", height * 0.25), ("upper", height * 0.78)):
        assembly.add(
            cq.Workplane("XY")
            .box(hinge_size, door_thickness * 0.72, hinge_size * 2)
            .translate(
                (
                    -width * 0.47,
                    -depth / 2 + door_thickness * 0.42,
                    z,
                )
            ),
            name=f"door_hinge_{name}",
            color=HANDLE_BLACK,
        )
    return assembly


def module_definition(params: dict) -> ModuleDef:
    _width, depth, height = _parameters(params)
    return ModuleDef(
        id="control_cabinet",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(link="cabinet_body"),
            "front": Frame(
                xyz=(0, -depth / 2, height / 2),
                rpy_deg=(90, 0, 0),
                link="front_door",
            ),
        },
        collision="box",
        meta=ModuleMeta(basis=CONTROL_CABINET_BASIS),
    )


MODULE = ModuleDef(
    id="control_cabinet",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "size_mm": {
                "type": "array",
                "items": {"type": "number", "minimum": 300, "maximum": 2000},
                "minItems": 3,
                "maxItems": 3,
                "default": [600, 300, 1000],
            }
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(), "front": Frame(link="front_door")},
    collision="box",
    meta=ModuleMeta(basis=CONTROL_CABINET_BASIS),
)
