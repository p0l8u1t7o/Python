"""Basler ace 系列 GigE 工業相機（29×29×42 mm，C-mount）。
Origin: 相機前面板中心；+Z 為鏡頭方向。單位 mm。
"""
from build123d import *
from cadgen import srgb
from cadgen.assembly import AssemblyHelper

body_w = 29.0
body_h = 29.0
body_len = 42.0
cmount_d = 25.4        # 1"-32 C-mount
cmount_len = 4.0
mount_hole_d = 2.5     # M2 x4（側面）
rj45_w = 16.0
rj45_h = 13.5
led_d = 2.0


def make_body():
    body = Pos(0, 0, -body_len) * Box(body_w, body_h, body_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body = fillet(body.edges().filter_by(Axis.Z), 1.5)
    # 側面 M2 安裝孔（兩側各四）
    holes = []
    for sx in (-1, 1):
        for z in (-8, -34):
            for y in (-10, 10):
                holes.append(Pos(sx * (body_w / 2 - 2), y, z) * Rot(0, 90, 0) * Cylinder(mount_hole_d / 2, 6))
    # 後面板：RJ45 口、電源 6-pin 口、LED
    rj45 = Pos(-4, 4, -body_len - 1) * Box(rj45_w, rj45_h, 6, align=(Align.CENTER, Align.CENTER, Align.MIN))
    power = Pos(8, -8, -body_len - 1) * Cylinder(4.0, 6, align=(Align.CENTER, Align.CENTER, Align.MIN))
    led = Pos(11, 9, -body_len - 1) * Cylinder(led_d / 2, 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body = body - holes - [rj45, power, led]
    body.color = srgb("#1B2430")
    return body


def make_cmount():
    ring = Cylinder(cmount_d / 2 + 1.5, cmount_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ring = ring - Pos(0, 0, -1) * Cylinder(cmount_d / 2, cmount_len + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ring.color = srgb("#8A9096")
    return ring


def make_sensor_window():
    glass = Pos(0, 0, -0.5) * Cylinder(cmount_d / 2 - 0.5, 0.5, align=(Align.CENTER, Align.CENTER, Align.MIN))
    glass.color = srgb("#38414D", 0.5)
    return glass


def gen_step():
    asm = AssemblyHelper("industrial_camera_gige_29x29x42")
    asm.add(make_body(), "housing")
    asm.add(make_cmount(), "c_mount_ring")
    asm.add(make_sensor_window(), "filter_glass")
    return asm.compound()
