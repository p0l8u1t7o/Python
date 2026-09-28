"""USB 隨身碟 2×8 連板：16 片 FR-4 小板與連接筋，提供接頭安裝、壓合對位與相機 ROI 的 frame。

模組座標：原點在連板中心的板底，X 沿輸送方向、Y 橫向、Z 向上。A 排接頭在 +Y 板邊、插頭朝 +Y；
B 排在 −Y 板邊、插頭朝 −Y。版面依 TestCode RobotArmPressSSD 的照片目測配方 usb-2x8。
"""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

FR4_GREEN = cq.Color(0.10, 0.36, 0.20)
RAIL_GREEN = cq.Color(0.14, 0.42, 0.24)
CHIP_BLACK = cq.Color(0.08, 0.08, 0.09)

PITCH_MM = 21.0
BOARD_WIDTH_MM = 18.5
BOARD_LENGTH_MM = 42.0
BOARD_THICKNESS_MM = 1.0
ROW_GAP_MM = 4.0
RAIL_WIDTH_MM = 6.0
UNITS = 8
EDGE_MM = ROW_GAP_MM / 2 + BOARD_LENGTH_MM
# 接頭尺寸（與 usb_a_connector.py 相同的照片目測值）：壓點在殼體後緣外 3 mm、頂面高 3.5 mm
PRESS_OFFSET_MM = 3.0
PRESS_HEIGHT_MM = 3.5
LEAD_MID_MM = 1.75
BASIS = (
    "依 TestCode RobotArmPressSSD 照片目測的 usb-2x8 配方：片距 21 mm、小板 18.5 × 42 × 1.0 mm、"
    "兩排間隔 4 mm、接頭後緣在板邊，連接筋寬 6 mm；皆為推估值"
)
ROWS = (("A", 1.0), ("B", -1.0))


def _unit_x(index: int) -> float:
    return (index - (UNITS - 1) / 2) * PITCH_MM


def _connector_frames() -> dict[str, Frame]:
    frames = {}
    for row, side in ROWS:
        for index in range(UNITS):
            # 接頭模組 +X 指向板內（銀腳方向）：A 排轉 −90°、B 排轉 +90°
            frames[f"usb_{row}{index + 1}"] = Frame(
                xyz=(_unit_x(index), side * EDGE_MM, BOARD_THICKNESS_MM),
                rpy_deg=(0, 0, -90.0 * side),
                link="base",
            )
    return frames


def _press_frames() -> dict[str, Frame]:
    return {
        f"press_{row}": Frame(
            xyz=(0.0, side * (EDGE_MM + PRESS_OFFSET_MM), BOARD_THICKNESS_MM + PRESS_HEIGHT_MM),
            rpy_deg=(0, 0, 0),
            link="base",
        )
        for row, side in ROWS
    }


def _roi_frames() -> dict[str, Frame]:
    frames = {}
    for row, side in ROWS:
        for group, units in (("1_4", range(0, 4)), ("5_8", range(4, 8))):
            x = sum(_unit_x(index) for index in units) / 4
            frames[f"roi_{row}{group}"] = Frame(
                xyz=(x, side * (EDGE_MM - LEAD_MID_MM), BOARD_THICKNESS_MM), link="base"
            )
    return frames


def _frames() -> dict[str, Frame]:
    return {
        "mount": Frame(link="base"),
        # 全局相機的整板 ROI：連板上表面中心
        "roi_panel": Frame(xyz=(0.0, 0.0, BOARD_THICKNESS_MM), link="base"),
        **_connector_frames(),
        **_press_frames(),
        **_roi_frames(),
    }


def build(params: dict) -> cq.Assembly:
    assembly = cq.Assembly(name="usb_panel_2x8")
    for row, side in ROWS:
        for index in range(UNITS):
            center_y = side * (ROW_GAP_MM / 2 + BOARD_LENGTH_MM / 2)
            board = cq.Workplane("XY").box(
                BOARD_WIDTH_MM, BOARD_LENGTH_MM, BOARD_THICKNESS_MM, centered=(True, True, False)
            )
            assembly.add(
                board.translate((_unit_x(index), center_y, 0)).val(),
                name=f"board_{row}{index + 1}",
                color=FR4_GREEN,
                metadata={"link": "base"},
            )
            controller = cq.Workplane("XY").box(6, 6, 0.9, centered=(True, True, False))
            assembly.add(
                controller.translate(
                    (_unit_x(index), side * (ROW_GAP_MM / 2 + 12), BOARD_THICKNESS_MM)
                ).val(),
                name=f"controller_{row}{index + 1}",
                color=CHIP_BLACK,
                metadata={"link": "base"},
            )
    panel_width = UNITS * PITCH_MM + 12
    for name, x in (
        ("rail_left", -(panel_width / 2 - RAIL_WIDTH_MM / 2)),
        ("rail_right", panel_width / 2 - RAIL_WIDTH_MM / 2),
    ):
        rail = cq.Workplane("XY").box(
            RAIL_WIDTH_MM, 2 * EDGE_MM, BOARD_THICKNESS_MM, centered=(True, True, False)
        )
        assembly.add(
            rail.translate((x, 0, 0)).val(), name=name, color=RAIL_GREEN, metadata={"link": "base"}
        )
    spine = cq.Workplane("XY").box(
        panel_width, ROW_GAP_MM, BOARD_THICKNESS_MM, centered=(True, True, False)
    )
    for x in (-panel_width / 2 + 3, panel_width / 2 - 3):
        spine = spine.cut(
            cq.Workplane("XY").circle(1.5).extrude(BOARD_THICKNESS_MM).translate((x, 0, 0))
        )
    assembly.add(spine.val(), name="center_rail", color=RAIL_GREEN, metadata={"link": "base"})
    return assembly


def module_definition(params: dict) -> ModuleDef:
    return MODULE


MODULE = ModuleDef(
    id="usb_panel_2x8",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    frames=_frames(),
    collision="hull",
    meta=ModuleMeta(basis=BASIS),
)
