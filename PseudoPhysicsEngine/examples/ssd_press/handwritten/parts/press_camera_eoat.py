"""SSD 壓合站末端工具：力覺感測器、8 頭獨立彈簧壓墊（片距 21 mm）與 45° 斜視相機、條形光。

工具座標：原點在手臂法蘭面中心，+Z 沿工具軸指向壓墊。相機光學 frame 的 +Z 為視線，
斜向工具軸下方、從 +Y 側往 −Y 看。尺寸與相機參數依 TestCode RobotArmPressSSD 的多機種
重新設計（ATI Axia80、IDS GV-5800 20MP＋25 mm 鏡頭、工作距離約 175 mm）作工程推估。
"""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import CameraSpec, Frame, ModuleDef, ModuleMeta

ALUMINIUM = cq.Color(0.66, 0.68, 0.70)
SENSOR_BLUE = cq.Color(0.10, 0.34, 0.58)
PAD_ORANGE = cq.Color(0.93, 0.47, 0.12)
SPRING_STEEL = cq.Color(0.55, 0.57, 0.60)
CAMERA_BLACK = cq.Color(0.08, 0.09, 0.10)
LIGHT_WHITE = cq.Color(0.92, 0.93, 0.95)

# 手臂末端工具零件拆成獨立碰撞體：8 個壓墊要各自判定與各接頭的接觸。
SEPARATE_COLLISION = True

PADS = 8
PITCH_MM = 21.0
PAD_SIZE_MM = (7.0, 9.0)
PAD_HEIGHT_MM = 6.0
TCP_Z_MM = 155.0
CAMERA_XYZ = (0.0, 70.0, 110.0)
CAMERA_RPY = (45.0, 0.0, 0.0)
BASIS = (
    "依 TestCode RobotArmPressSSD 多機種重新設計：ATI Axia80 力覺感測器、8 頭 PU 壓墊 7×9 mm、"
    "片距 21 mm、彈簧行程 3 mm，IDS GV-5800 20MP＋25 mm 鏡頭 45° 斜裝、工作距離約 175 mm；"
    "外形尺寸為工程推估"
)


def _pad_x(index: int) -> float:
    return (index - (PADS - 1) / 2) * PITCH_MM


def _camera_xyz(params: dict) -> tuple[float, float, float]:
    # 相機支架沿工具軸往法蘭方向上移（camera_raise_mm）：用來檢查支架位置改變時相機是否仍對焦。
    raise_mm = float(params.get("camera_raise_mm", 0))
    return (CAMERA_XYZ[0], CAMERA_XYZ[1], CAMERA_XYZ[2] - raise_mm)


def _camera_location(params: dict) -> cq.Location:
    return cq.Location(cq.Vector(*_camera_xyz(params)), cq.Vector(1, 0, 0), CAMERA_RPY[0])


def build(params: dict) -> cq.Assembly:
    assembly = cq.Assembly(name="press_camera_eoat")
    adapter = cq.Workplane("XY").circle(31.5).extrude(10)
    for x, y in ((25, 0), (-25, 0), (0, 25), (0, -25)):
        adapter = adapter.cut(cq.Workplane("XY").center(x, y).circle(3.3).extrude(10))
    assembly.add(adapter.val(), name="flange_adapter", color=ALUMINIUM)
    sensor = cq.Workplane("XY").circle(40).extrude(25).translate((0, 0, 10))
    assembly.add(sensor.val(), name="force_sensor", color=SENSOR_BLUE)
    body = cq.Workplane("XY").box(60, 40, 80, centered=(True, True, False)).translate((0, 0, 35))
    assembly.add(body.val(), name="tool_body", color=ALUMINIUM)
    beam = cq.Workplane("XY").box(PADS * PITCH_MM + 10, 20, 12, centered=(True, True, False))
    assembly.add(beam.translate((0, 0, 115)).val(), name="pad_beam", color=ALUMINIUM)
    for index in range(PADS):
        x = _pad_x(index)
        spring = cq.Workplane("XY").circle(3.5).extrude(22).translate((x, 0, 127))
        assembly.add(spring.val(), name=f"spring_{index + 1}", color=SPRING_STEEL)
        pad = cq.Workplane("XY").box(*PAD_SIZE_MM, PAD_HEIGHT_MM, centered=(True, True, False))
        assembly.add(
            pad.translate((x, 0, TCP_Z_MM - PAD_HEIGHT_MM)).val(),
            name=f"pad_{index + 1}",
            color=PAD_ORANGE,
        )
    raise_mm = float(params.get("camera_raise_mm", 0))
    bracket = (
        cq.Workplane("XY")
        .box(30, 40, 10, centered=(True, False, False))
        .translate((0, 20, 70 - raise_mm))
    )
    assembly.add(bracket.val(), name="camera_bracket", color=ALUMINIUM)
    # 相機座標：+Z 為視線，鏡頭前緣在光學 frame 原點
    lens = cq.Workplane("XY").circle(15).extrude(35).translate((0, 0, -35))
    camera = cq.Workplane("XY").box(29, 29, 55, centered=(True, True, False)).translate((0, 0, -90))
    location = _camera_location(params)
    assembly.add(lens.val(), name="camera_lens", color=CAMERA_BLACK, loc=location)
    assembly.add(camera.val(), name="camera_body", color=CAMERA_BLACK, loc=location)
    light = cq.Workplane("XY").box(100, 12, 12).translate((0, 18, -10))
    assembly.add(light.val(), name="light_bar", color=LIGHT_WHITE, loc=location)
    return assembly


def _camera_spec(params: dict) -> CameraSpec:
    return CameraSpec(
        sensor_px=(5472, 3648),
        pixel_um=2.4,
        focal_mm=float(params.get("focal_mm", 25)),
        working_distance_mm=float(params.get("working_distance_mm", 175)),
        f_number=float(params.get("f_number", 11)),
        source="IDS GV-5800 20MP 1 吋感光元件（2.4 µm）＋25 mm 鏡頭；光圈為推估",
    )


def module_definition(params: dict) -> ModuleDef:
    frames = {
        "mount": Frame(),
        "flange": Frame(),
        "tool_center_point": Frame(xyz=(0, 0, TCP_Z_MM)),
        **{f"pad_{index + 1}": Frame(xyz=(_pad_x(index), 0, TCP_Z_MM)) for index in range(PADS)},
        "camera": Frame(xyz=_camera_xyz(params), rpy_deg=CAMERA_RPY),
    }
    return ModuleDef(
        id="press_camera_eoat",
        params_schema=MODULE.params_schema,
        frames=frames,
        collision="hull",
        payload_kg=1.8,
        meta=ModuleMeta(basis=BASIS),
        cameras={"camera": _camera_spec(params)},
    )


MODULE = ModuleDef(
    id="press_camera_eoat",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "focal_mm": {"type": "number", "minimum": 8, "maximum": 75, "default": 25},
            "working_distance_mm": {
                "type": "number",
                "minimum": 80,
                "maximum": 400,
                "default": 175,
            },
            "f_number": {"type": "number", "minimum": 1.4, "maximum": 22, "default": 11},
            "camera_raise_mm": {"type": "number", "minimum": 0, "maximum": 60, "default": 0},
        },
        "additionalProperties": False,
    },
    frames={
        "mount": Frame(),
        "flange": Frame(),
        "tool_center_point": Frame(xyz=(0, 0, TCP_Z_MM)),
        **{f"pad_{index + 1}": Frame(xyz=(_pad_x(index), 0, TCP_Z_MM)) for index in range(PADS)},
        "camera": Frame(xyz=CAMERA_XYZ, rpy_deg=CAMERA_RPY),
    },
    collision="hull",
    payload_kg=1.8,
    meta=ModuleMeta(basis=BASIS),
)
