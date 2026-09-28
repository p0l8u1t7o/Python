"""SSD 壓合站載盤：承載 USB 連板與板邊外的接頭殼體，兩個定位孔對應輸送站定位銷。

模組座標：原點在載盤底面中心，X 沿輸送方向、Z 向上；尺寸依 TestCode RobotArmPressSSD 配方 usb-2x8
的載盤 300 × 200 × 6 mm（盤號 29-0290）。
"""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

TRAY_DARK = cq.Color(0.12, 0.13, 0.15)
LABEL_WHITE = cq.Color(0.90, 0.90, 0.88)
BASIS = "依 TestCode RobotArmPressSSD 配方 usb-2x8 的載盤 300 × 200 × 6 mm 與盤號 29-0290 作推估"


def _size(params: dict) -> tuple[float, float, float]:
    width, depth = params.get("size_mm", [300, 200])
    return float(width), float(depth), float(params.get("thickness_mm", 6))


def build(params: dict) -> cq.Assembly:
    width, depth, thickness = _size(params)
    assembly = cq.Assembly(name="ssd_tray")
    plate = cq.Workplane("XY").box(width, depth, thickness, centered=(True, True, False))
    for x, y in ((-width / 2 + 12, -depth / 2 + 12), (width / 2 - 12, depth / 2 - 12)):
        plate = plate.cut(cq.Workplane("XY").circle(3.0).extrude(thickness).translate((x, y, 0)))
    assembly.add(plate.val(), name="pallet_plate", color=TRAY_DARK, metadata={"link": "base"})
    label = cq.Workplane("XY").box(40, 12, 0.3, centered=(True, True, False))
    assembly.add(
        label.translate((-width / 2 + 35, -depth / 2 + 10, thickness)).val(),
        name="tray_code_label",
        color=LABEL_WHITE,
        metadata={"link": "base"},
    )
    return assembly


def module_definition(params: dict) -> ModuleDef:
    _width, _depth, thickness = _size(params)
    return ModuleDef(
        id="ssd_tray",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(link="base"),
            "panel_seat": Frame(xyz=(0, 0, thickness), link="base"),
        },
        collision="hull",
        meta=ModuleMeta(basis=BASIS),
    )


MODULE = ModuleDef(
    id="ssd_tray",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "size_mm": {
                "type": "array",
                "items": {"type": "number", "minimum": 150, "maximum": 500},
                "minItems": 2,
                "maxItems": 2,
                "default": [300, 200],
            },
            "thickness_mm": {"type": "number", "minimum": 3, "maximum": 20, "default": 6},
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(link="base"), "panel_seat": Frame(link="base")},
    collision="hull",
    meta=ModuleMeta(basis=BASIS),
)
