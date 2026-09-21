"""Configurable perimeter guarding made from posts, mesh panels and base plates."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

SAFETY_YELLOW = cq.Color(0.95, 0.72, 0.08)
MESH_GREY = cq.Color(0.18, 0.20, 0.22, 0.62)
BASE_GREY = cq.Color(0.30, 0.32, 0.34)

POST_SIZE_MM = 50.0
BASE_SIZE_MM = 110.0
BASE_THICKNESS_MM = 12.0
MESH_THICKNESS_MM = 8.0
PANEL_CLEARANCE_MM = 100.0

SAFETY_FENCE_BASIS = (
    "依一般工業安全圍籬的五十毫米級立柱、落地底板與分段鋼網比例作工程推估；高度及分段"
    "數可依產線邊界調整，網孔細節以半透明薄板表示以控制模型複雜度。"
)


def _parameters(params: dict) -> tuple[float, int, float]:
    return (
        float(params.get("length_mm", 2000)),
        int(params.get("segments", 2)),
        float(params.get("height_mm", 1800)),
    )


def build(params: dict) -> cq.Assembly:
    length, segments, height = _parameters(params)
    assembly = cq.Assembly(name=params.get("name", "safety_fence"))
    post_span = length - BASE_SIZE_MM
    segment_width = post_span / segments

    for index in range(segments + 1):
        x = -post_span / 2 + index * segment_width
        assembly.add(
            cq.Workplane("XY")
            .box(BASE_SIZE_MM, BASE_SIZE_MM, BASE_THICKNESS_MM)
            .translate((x, 0, BASE_THICKNESS_MM / 2)),
            name=f"base_{index}",
            color=BASE_GREY,
        )
        assembly.add(
            cq.Workplane("XY")
            .box(POST_SIZE_MM, POST_SIZE_MM, height - BASE_THICKNESS_MM)
            .translate((x, 0, BASE_THICKNESS_MM + (height - BASE_THICKNESS_MM) / 2)),
            name=f"post_{index}",
            color=SAFETY_YELLOW,
        )

    panel_bottom = max(PANEL_CLEARANCE_MM, BASE_THICKNESS_MM)
    panel_height = height - panel_bottom - POST_SIZE_MM / 2
    panel_width = max(segment_width - POST_SIZE_MM, POST_SIZE_MM * 0.25)
    for index in range(segments):
        x = -post_span / 2 + (index + 0.5) * segment_width
        assembly.add(
            cq.Workplane("XY")
            .box(panel_width, MESH_THICKNESS_MM, panel_height)
            .translate((x, 0, panel_bottom + panel_height / 2)),
            name=f"mesh_panel_{index}",
            color=MESH_GREY,
        )
        for rail_name, z in (
            ("bottom", panel_bottom),
            ("top", panel_bottom + panel_height),
        ):
            assembly.add(
                cq.Workplane("XY")
                .box(panel_width, POST_SIZE_MM * 0.55, POST_SIZE_MM * 0.55)
                .translate((x, 0, z)),
                name=f"panel_rail_{index}_{rail_name}",
                color=SAFETY_YELLOW,
            )
    return assembly


def module_definition(params: dict) -> ModuleDef:
    length, _segments, _height = _parameters(params)
    left_x = -(length - BASE_SIZE_MM) / 2
    return ModuleDef(
        id="safety_fence",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(xyz=(left_x, 0, 0), link="base"),
            "base": Frame(xyz=(left_x, 0, 0), link="base"),
        },
        collision="box",
        meta=ModuleMeta(basis=SAFETY_FENCE_BASIS),
    )


MODULE = ModuleDef(
    id="safety_fence",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "length_mm": {
                "type": "number",
                "minimum": 500,
                "maximum": 12000,
                "default": 2000,
            },
            "segments": {"type": "integer", "minimum": 1, "maximum": 12, "default": 2},
            "height_mm": {
                "type": "number",
                "minimum": 1000,
                "maximum": 3000,
                "default": 1800,
            },
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(link="base"), "base": Frame(link="base")},
    collision="box",
    meta=ModuleMeta(basis=SAFETY_FENCE_BASIS),
)
