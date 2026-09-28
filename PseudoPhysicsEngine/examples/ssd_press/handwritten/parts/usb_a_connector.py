"""USB-A 接頭（隨身碟板邊型）：殼體、舌片、9 支銀腳與焊墊，後端可繞殼體前緣翹起。

模組座標：原點在銀腳出口（殼體後緣）與 PCB 上表面的交點；插頭朝 −X，寬度沿 Y，Z 向上。
殼體底面低於 PCB 上表面 ``sink_mm``（落在 PCB 板邊外、由載盤承托）。
翹起軸 ``tilt`` 繞殼體前緣底部的 −Y 軸，正值使後端與銀腳離開焊墊；frame 以靜止姿態的模組座標表示。
尺寸依 TestCode RobotArmPressSSD 的照片目測接頭型錄（12 × 4.5 × 14 mm、9 支、片距 1.0 mm）。
"""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import Frame, ModuleDef, ModuleMeta

SHELL_STEEL = cq.Color(0.78, 0.80, 0.82)
TONGUE_BLUE = cq.Color(0.12, 0.37, 0.66)
LEAD_SILVER = cq.Color(0.86, 0.87, 0.88)
PAD_COPPER = cq.Color(0.80, 0.52, 0.25)

WIDTH_MM = 12.0
HEIGHT_MM = 4.5
LENGTH_MM = 14.0
SINK_MM = 1.0
LEADS = 9
LEAD_PITCH_MM = 1.0
LEAD_LENGTH_MM = 3.5
LEAD_WIDTH_MM = 0.5
LEAD_THICKNESS_MM = 0.2
PRESS_FROM_TIP_MM = 11.0
SHELL_WALL_MM = 0.3
BASIS = (
    "依 TestCode RobotArmPressSSD 照片目測的 USB-A 接頭型錄：寬 12、高 4.5、長 14 mm，"
    "板邊下沉 1.0 mm，9 支銀腳、片距 1.0 mm、長 3.5 mm，壓點距插頭前緣 11 mm；皆為推估值"
)


def _pivot() -> tuple[float, float, float]:
    return (-LENGTH_MM, 0.0, -SINK_MM)


def _add(assembly: cq.Assembly, shape, name: str, color: cq.Color, link: str) -> None:
    assembly.add(shape, name=name, color=color, metadata={"link": link})


def _shell() -> cq.Shape:
    outer = cq.Workplane("XY").box(LENGTH_MM, WIDTH_MM, HEIGHT_MM, centered=(False, True, False))
    inner = cq.Workplane("XY").box(
        LENGTH_MM - SHELL_WALL_MM,
        WIDTH_MM - 2 * SHELL_WALL_MM,
        HEIGHT_MM - 2 * SHELL_WALL_MM,
        centered=(False, True, False),
    )
    shell = outer.cut(inner.translate((-SHELL_WALL_MM, 0, SHELL_WALL_MM)))
    # 殼體上的兩個卡扣孔（照片可見的方孔）
    for y in (-3.0, 3.0):
        hole = (
            cq.Workplane("XY")
            .box(2.0, 1.6, SHELL_WALL_MM * 3)
            .translate((4.0, y, HEIGHT_MM - SHELL_WALL_MM / 2))
        )
        shell = shell.cut(hole)
    return shell.translate((-LENGTH_MM, 0, -SINK_MM)).val()


def _tongue() -> cq.Shape:
    return (
        cq.Workplane("XY")
        .box(LENGTH_MM - 2.5, WIDTH_MM - 2.4, 1.8, centered=(False, True, False))
        .translate((-LENGTH_MM + 0.5, 0, -SINK_MM + 1.2))
        .val()
    )


def _lead(y: float) -> cq.Shape:
    # 彎折截面：出殼體後下彎一段，再平貼在焊墊上
    rise = cq.Workplane("XY").box(0.4, LEAD_WIDTH_MM, 1.2).translate((0.2, y, 0.6))
    flat = (
        cq.Workplane("XY")
        .box(LEAD_LENGTH_MM, LEAD_WIDTH_MM, LEAD_THICKNESS_MM)
        .translate((LEAD_LENGTH_MM / 2, y, LEAD_THICKNESS_MM / 2))
    )
    return rise.union(flat).val()


def _pad(y: float) -> cq.Shape:
    return (
        cq.Workplane("XY")
        .box(LEAD_LENGTH_MM - 0.5, LEAD_WIDTH_MM + 0.2, 0.035)
        .translate((0.5 + (LEAD_LENGTH_MM - 0.5) / 2, y, -0.0175))
        .val()
    )


def _lead_positions() -> list[float]:
    return [(index - (LEADS - 1) / 2) * LEAD_PITCH_MM for index in range(LEADS)]


def build(params: dict) -> cq.Assembly:
    assembly = cq.Assembly(name="usb_a_connector")
    for index, y in enumerate(_lead_positions(), 1):
        _add(assembly, _pad(y), f"solder_pad_{index}", PAD_COPPER, "base")
    _add(assembly, _shell(), "shell", SHELL_STEEL, "body")
    _add(assembly, _tongue(), "tongue", TONGUE_BLUE, "body")
    for index, y in enumerate(_lead_positions(), 1):
        _add(assembly, _lead(y), f"lead_{index}", LEAD_SILVER, "body")
    return assembly


def module_definition(params: dict) -> ModuleDef:
    tilt_max = float(params.get("tilt_max_deg", 6.0))
    return ModuleDef(
        id="usb_a_connector",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(link="base"),
            # 壓墊接觸點：殼體頂面、距插頭前緣 11 mm
            "press_face": Frame(
                xyz=(-LENGTH_MM + PRESS_FROM_TIP_MM, 0, HEIGHT_MM - SINK_MM), link="body"
            ),
            # 銀腳末端底面與其下方焊墊：兩者沿焊墊法向的距離即間隙
            "lead_tip": Frame(xyz=(LEAD_LENGTH_MM, 0, 0), link="body"),
            "pad": Frame(xyz=(LEAD_LENGTH_MM, 0, 0), link="base"),
            # 相機檢查區：銀腳與焊墊交界
            "roi": Frame(xyz=(LEAD_LENGTH_MM / 2, 0, 0), link="base"),
        },
        axes=[
            {
                "id": "tilt",
                "type": "revolute",
                "parent": "base",
                "child": "body",
                "origin": {"xyz": _pivot(), "rpy_deg": (0, 0, 0)},
                "axis": (0, -1, 0),
                "range_deg": (0.0, tilt_max),
                "max_speed_dps": 90.0,
            }
        ],
        collision="hull",
        meta=ModuleMeta(basis=BASIS),
    )


MODULE = ModuleDef(
    id="usb_a_connector",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "tilt_max_deg": {"type": "number", "minimum": 1, "maximum": 10, "default": 6},
            # 壓合放開後回彈的角度（示意）；0 表示壓平後保持貼合
            "rebound_deg": {"type": "number", "minimum": 0, "maximum": 5, "default": 0},
        },
        "additionalProperties": False,
    },
    frames={
        "mount": Frame(link="base"),
        "press_face": Frame(
            xyz=(-LENGTH_MM + PRESS_FROM_TIP_MM, 0, HEIGHT_MM - SINK_MM), link="body"
        ),
        "lead_tip": Frame(xyz=(LEAD_LENGTH_MM, 0, 0), link="body"),
        "pad": Frame(xyz=(LEAD_LENGTH_MM, 0, 0), link="base"),
        "roi": Frame(xyz=(LEAD_LENGTH_MM / 2, 0, 0), link="base"),
    },
    axes=[
        {
            "id": "tilt",
            "type": "revolute",
            "parent": "base",
            "child": "body",
            "origin": {"xyz": (-LENGTH_MM, 0.0, -SINK_MM), "rpy_deg": (0, 0, 0)},
            "axis": (0, -1, 0),
            "range_deg": (0.0, 6.0),
            "max_speed_dps": 90.0,
        }
    ],
    collision="hull",
    meta=ModuleMeta(basis=BASIS),
)
