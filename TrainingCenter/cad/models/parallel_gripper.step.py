"""SMC MHZ2-20D 氣動平行夾爪（示意 CAD）。
Origin: 本體安裝面中心；+Z 朝夾指方向。單位 mm。
"""
from build123d import *
from cadgen import srgb
from cadgen.assembly import AssemblyHelper

body_w = 40.0
body_d = 30.0
body_h = 50.0
finger_w = 12.0
finger_t = 5.0
finger_len = 20.0
finger_gap = 10.0       # 開啟行程
mount_hole_d = 4.5
port_d = 4.0


def make_body():
    body = Box(body_w, body_d, body_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body = fillet(body.edges().filter_by(Axis.Z), 2.0)
    # 安裝孔（底面）與側面氣口
    holes = [Pos(x, y, -1) * Cylinder(mount_hole_d / 2, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
             for x in (-14, 14) for y in (-9, 9)]
    ports = [Pos(0, body_d / 2 - 3, z) * Rot(-90, 0, 0) * Cylinder(port_d / 2, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))
             for z in (12.0, 38.0)]
    body = body - holes - ports
    # 頂面導槽
    slot = Pos(0, 0, body_h - 3) * Box(body_w - 4, 8, 4, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body = body - slot
    body.color = srgb("#2A7F8F")
    return body


def make_finger(side: float):
    x = side * (finger_gap / 2 + finger_t / 2)
    f = Pos(x, 0, body_h - 2) * Box(finger_t, finger_w, finger_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
    # 夾指上的鎖固孔
    f = f - Pos(x, 0, body_h + 10) * Rot(0, 90, 0) * Cylinder(1.6, finger_t + 2)
    f.color = srgb("#C0C0C0")
    return f


def gen_step():
    asm = AssemblyHelper("parallel_gripper_mhz2_20d")
    asm.add(make_body(), "body")
    asm.add(make_finger(-1), "finger:left")
    asm.add(make_finger(+1), "finger:right")
    return asm.compound()
