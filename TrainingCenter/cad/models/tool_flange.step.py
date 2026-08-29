"""ISO 9409-1-50-4-M6 機械手臂末端法蘭（含定位銷孔）。
Origin: 法蘭安裝面中心；+Z 朝工具側。單位 mm。
"""
from build123d import *
from cadgen import srgb

flange_d = 63.0
flange_t = 8.0
pcd = 50.0            # 螺栓孔節圓
bolt_hole_d = 6.6     # M6 貫穿
n_bolts = 4
pilot_d = 31.5        # 中心定位凸台（H7）
pilot_h = 6.0
pin_hole_d = 6.0      # 定位銷孔
pin_pcd = 50.0
hub_d = 40.0
hub_h = 10.0


def gen_step():
    body = Cylinder(flange_d / 2, flange_t, align=(Align.CENTER, Align.CENTER, Align.MIN))
    hub = Pos(0, 0, -hub_h) * Cylinder(hub_d / 2, hub_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    pilot = Pos(0, 0, flange_t) * Cylinder(pilot_d / 2, pilot_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = body + hub + pilot
    # 注意：.rotate 要套在「已定位」的形狀上，所以整個 Pos * Cylinder 要加括號
    holes = [(Pos(pcd / 2, 0, -hub_h - 1) * Cylinder(bolt_hole_d / 2, hub_h + flange_t + pilot_h + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)))
             .rotate(Axis.Z, 45 + i * 360 / n_bolts) for i in range(n_bolts)]
    pin_hole = (Pos(pin_pcd / 2, 0, flange_t - 4) * Cylinder(pin_hole_d / 2, pilot_h + 6, align=(Align.CENTER, Align.CENTER, Align.MIN))).rotate(Axis.Z, 0)
    center = Pos(0, 0, -hub_h - 1) * Cylinder(10.0, hub_h + flange_t + pilot_h + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = part - (holes + [pin_hole, center])  # 所有刀具一次傳入單一清單
    part = chamfer(part.faces().sort_by(Axis.Z)[-1].edges().filter_by(GeomType.CIRCLE).sort_by(Edge.length)[-1], 0.8)
    part.color = srgb("#9A9A9A")
    part.label = "tool_flange_iso9409_50_4_m6"
    return part
