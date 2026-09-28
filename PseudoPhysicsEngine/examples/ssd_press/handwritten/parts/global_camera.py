"""SSD 壓合站固定全局相機：鋁擠立柱、懸臂與向下的 20MP 相機，進板後先拍整盤定位。

模組座標：原點在立柱底板中心；懸臂沿 +X 伸出，相機光學 frame 在懸臂末端、+Z 朝下。
依 TestCode RobotArmPressSSD 重新設計：IDS GV-5800 20MP＋25 mm 鏡頭、站位正上方約 750 mm。
"""

from __future__ import annotations

import cadquery as cq

from cellforge.schema import CameraSpec, Frame, ModuleDef, ModuleMeta

EXTRUSION = cq.Color(0.70, 0.72, 0.74)
CAMERA_BLACK = cq.Color(0.08, 0.09, 0.10)
BASIS = (
    "依 TestCode RobotArmPressSSD 重新設計的全局相機：IDS GV-5800 20MP＋25 mm 鏡頭、"
    "裝在站位正上方約 750 mm；立柱與懸臂為 40 mm 鋁擠的工程推估"
)


def _layout(params: dict) -> tuple[float, float]:
    return float(params.get("lens_height_mm", 1650)), float(params.get("reach_mm", 450))


def build(params: dict) -> cq.Assembly:
    height, reach = _layout(params)
    assembly = cq.Assembly(name="global_camera")
    base = cq.Workplane("XY").box(160, 160, 12, centered=(True, True, False))
    for x in (-60, 60):
        for y in (-60, 60):
            base = base.cut(cq.Workplane("XY").circle(5).extrude(12).translate((x, y, 0)))
    assembly.add(base.val(), name="floor_plate", color=EXTRUSION)
    post_top = height + 120
    post = cq.Workplane("XY").box(40, 40, post_top - 12, centered=(True, True, False))
    assembly.add(post.translate((0, 0, 12)).val(), name="post", color=EXTRUSION)
    arm = cq.Workplane("XY").box(reach + 40, 40, 40, centered=(False, True, False))
    assembly.add(arm.translate((-20, 0, post_top - 40)).val(), name="arm", color=EXTRUSION)
    body = cq.Workplane("XY").box(29, 29, 55, centered=(True, True, False))
    assembly.add(
        body.translate((reach, 0, height + 35)).val(), name="camera_body", color=CAMERA_BLACK
    )
    lens = cq.Workplane("XY").circle(15).extrude(35)
    assembly.add(lens.translate((reach, 0, height)).val(), name="camera_lens", color=CAMERA_BLACK)
    return assembly


def module_definition(params: dict) -> ModuleDef:
    height, reach = _layout(params)
    return ModuleDef(
        id="global_camera",
        params_schema=MODULE.params_schema,
        frames={
            "mount": Frame(link="base"),
            "optical": Frame(xyz=(reach, 0, height), rpy_deg=(180, 0, 0), link="base"),
        },
        collision="hull",
        meta=ModuleMeta(basis=BASIS),
        cameras={
            "optical": CameraSpec(
                sensor_px=(5472, 3648),
                pixel_um=2.4,
                focal_mm=25,
                working_distance_mm=float(params.get("working_distance_mm", 750)),
                f_number=8,
                source="IDS GV-5800 20MP＋25 mm 鏡頭；工作距離與光圈為推估",
            )
        },
    )


MODULE = ModuleDef(
    id="global_camera",
    params_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "lens_height_mm": {"type": "number", "minimum": 800, "maximum": 2500, "default": 1650},
            "reach_mm": {"type": "number", "minimum": 200, "maximum": 900, "default": 450},
            "working_distance_mm": {
                "type": "number",
                "minimum": 300,
                "maximum": 1500,
                "default": 750,
            },
        },
        "additionalProperties": False,
    },
    frames={"mount": Frame(link="base"), "optical": Frame(link="base")},
    collision="hull",
    meta=ModuleMeta(basis=BASIS),
)
