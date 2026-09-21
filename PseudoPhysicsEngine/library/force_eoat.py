"""Parametric force-limited cover-opening end effector."""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

ADAPTER_GREY = cq.Color(0.48, 0.51, 0.54)
SENSOR_BLUE = cq.Color(0.10, 0.34, 0.58)
HOUSING_DARK = cq.Color(0.10, 0.12, 0.14)
LEVER_STEEL = cq.Color(0.72, 0.74, 0.76)
TIP_ORANGE = cq.Color(0.92, 0.36, 0.08)

TOOL_LENGTH_MM = 140.0
ADAPTER_THICKNESS_MM = 10.0
SENSOR_HEIGHT_MM = 36.0
SENSOR_RADIUS_MM = 34.0
LEVER_WIDTH_MM = 12.0
TIP_WIDTH_MM = 18.0
TIP_DEPTH_MM = 42.0
TIP_HEIGHT_MM = 20.0
TIP_CORNER_RADIUS_MM = 4.0


def _parameters(params: dict) -> tuple[float, float]:
    return float(params.get("stroke_mm", 30)), float(params.get("force_limit_n", 35))


def _add(
    assembly: cq.Assembly,
    shape: cq.Shape | cq.Workplane,
    name: str,
    color: cq.Color,
    link: str,
) -> None:
    assembly.add(shape, name=name, color=color, metadata={"link": link})


def _adapter_plate() -> cq.Shape:
    plate = cq.Workplane("XY").circle(42).extrude(ADAPTER_THICKNESS_MM)
    bolt_circle = 31.5
    for x, y in ((bolt_circle, 0), (-bolt_circle, 0), (0, bolt_circle), (0, -bolt_circle)):
        plate = plate.cut(cq.Workplane("XY").center(x, y).circle(3.2).extrude(ADAPTER_THICKNESS_MM))
    return plate.val()


def build(params: dict) -> cq.Assembly:
    stroke, _force_limit = _parameters(params)
    assembly = cq.Assembly(name="force_eoat")
    _add(assembly, _adapter_plate(), "flange_adapter", ADAPTER_GREY, "base")

    sensor_start = ADAPTER_THICKNESS_MM
    sensor = cq.Solid.makeCylinder(
        SENSOR_RADIUS_MM,
        SENSOR_HEIGHT_MM,
        cq.Vector(0, 0, sensor_start),
        cq.Vector(0, 0, 1),
    )
    _add(assembly, sensor, "force_sensor", SENSOR_BLUE, "base")
    band_height = SENSOR_HEIGHT_MM * 0.16
    band = cq.Solid.makeCylinder(
        SENSOR_RADIUS_MM * 1.04,
        band_height,
        cq.Vector(0, 0, sensor_start + (SENSOR_HEIGHT_MM - band_height) / 2),
        cq.Vector(0, 0, 1),
    )
    _add(assembly, band, "sensor_band", HOUSING_DARK, "base")

    housing_start = sensor_start + SENSOR_HEIGHT_MM
    housing_height = max(stroke, SENSOR_HEIGHT_MM * 0.72)
    housing = (
        cq.Workplane("XY")
        .box(SENSOR_RADIUS_MM * 1.25, SENSOR_RADIUS_MM, housing_height)
        .translate((0, 0, housing_start + housing_height / 2))
    )
    _add(assembly, housing, "compliance_housing", HOUSING_DARK, "compliance")

    lever_start = housing_start + housing_height * 0.72
    lever_end = TOOL_LENGTH_MM - TIP_HEIGHT_MM
    lever_height = lever_end - lever_start
    lever = (
        cq.Workplane("XY")
        .box(LEVER_WIDTH_MM, LEVER_WIDTH_MM * 0.72, lever_height)
        .translate((0, 0, lever_start + lever_height / 2))
    )
    _add(assembly, lever, "cover_lever", LEVER_STEEL, "compliance")
    tip = (
        cq.Workplane("XY", origin=(0, 0, lever_end))
        .rect(TIP_WIDTH_MM, TIP_DEPTH_MM)
        .extrude(TIP_HEIGHT_MM)
        .edges("|Z")
        .fillet(TIP_CORNER_RADIUS_MM)
    )
    _add(assembly, tip, "rounded_tip", TIP_ORANGE, "compliance")
    return assembly


def module_definition(params: dict) -> ModuleDef:
    stroke, _force_limit = _parameters(params)
    return ModuleDef(
        id="force_eoat",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(link="base"),
            "flange": Frame(link="base"),
            # Keep the established TCP frame while publishing the mechanism-specific alias.
            "tool_center_point": Frame(xyz=(0, 0, TOOL_LENGTH_MM), link="compliance"),
            "tip": Frame(xyz=(0, 0, TOOL_LENGTH_MM), link="compliance"),
        },
        axes=[
            {
                "id": "compliance",
                "type": "prismatic",
                "parent": "base",
                "child": "compliance",
                "axis": (0, 0, 1),
                "range_mm": (0, stroke),
                "max_speed_mm_s": 50,
            }
        ],
        collision="hull",
        payload_kg=1.2,
        meta=ModuleMeta(
            basis="依 Getac 護蓋開合檢測需求與一般 ISO 法蘭、力覺感測器及順應撥桿尺寸作工程推估"
        ),
    )


MODULE = ModuleDef(
    id="force_eoat",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "stroke_mm": {
                "type": "number",
                "minimum": 10,
                "maximum": 50,
                "default": 30,
            },
            "force_limit_n": {
                "type": "number",
                "minimum": 5,
                "maximum": 120,
                "default": 35,
            },
        },
    },
    frames={
        "mount": Frame(link="base"),
        "flange": Frame(link="base"),
        "tool_center_point": Frame(xyz=(0, 0, TOOL_LENGTH_MM), link="compliance"),
        "tip": Frame(xyz=(0, 0, TOOL_LENGTH_MM), link="compliance"),
    },
    axes=[
        {
            "id": "compliance",
            "type": "prismatic",
            "parent": "base",
            "child": "compliance",
            "axis": (0, 0, 1),
            "range_mm": (0, 30),
            "max_speed_mm_s": 50,
        }
    ],
    collision="hull",
    payload_kg=1.2,
    meta=ModuleMeta(
        basis="依 Getac 護蓋開合檢測需求與一般 ISO 法蘭、力覺感測器及順應撥桿尺寸作工程推估"
    ),
)
