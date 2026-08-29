"""SMC CDQ2B25-20 薄型氣缸（示意 CAD）。
Origin: 缸體底面中心；+Z 為活塞桿伸出方向。單位 mm。
"""
from build123d import *
from cadgen import srgb
from cadgen.assembly import AssemblyHelper

bore = 25.0
stroke = 20.0
body_w = 40.0          # 方形缸體寬
body_h = 40.0
body_len = 42.0 + stroke  # 缸體總長（含行程）
rod_d = 10.0
rod_len = stroke + 12.0
port_d = 5.0           # M5 氣口
mount_hole_d = 5.5     # 貫穿安裝孔 x4
mount_pitch = 30.0
boss_d = 20.0
boss_h = 4.0


def make_body():
    body = Box(body_w, body_h, body_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body = fillet(body.edges().filter_by(Axis.Z), 3.0)
    # 四角安裝貫穿孔
    holes = [Pos(x, y, -1) * Cylinder(mount_hole_d / 2, body_len + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
             for x in (-mount_pitch / 2, mount_pitch / 2) for y in (-mount_pitch / 2, mount_pitch / 2)]
    body = body - holes
    # 兩側氣口（前後蓋各一）
    ports = [Pos(body_w / 2 - 3, 0, z) * Rot(0, 90, 0) * Cylinder(port_d / 2, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))
             for z in (8.0, body_len - 8.0)]
    body = body - ports
    # 桿端凸台
    boss = Pos(0, 0, body_len) * Cylinder(boss_d / 2, boss_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body = body + boss
    body = body - Pos(0, 0, body_len - 1) * Cylinder(rod_d / 2 + 0.2, boss_h + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body.color = srgb("#3B4048")
    return body


def make_rod():
    rod = Pos(0, 0, body_len - 2) * Cylinder(rod_d / 2, rod_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
    # 桿端內牙（M8）示意：端面倒角
    rod = chamfer(rod.faces().sort_by(Axis.Z)[-1].edges(), 0.8)
    rod.color = srgb("#D0D4D8")
    return rod


def make_switch_slot_covers():
    # 兩側磁簧感測器溝槽（以淺槽表示）
    covers = []
    for y in (-body_h / 2, body_h / 2):
        c = Pos(0, y, body_len / 2) * Box(4.0, 1.0, body_len - 10, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        c.color = srgb("#1E5AA8")
        covers.append(c)
    return covers


def gen_step():
    asm = AssemblyHelper("compact_cylinder_cdq2b25_20")
    asm.add(make_body(), "body")
    asm.add(make_rod(), "piston_rod")
    for i, c in enumerate(make_switch_slot_covers()):
        asm.add(c, f"sensor_slot:{'left' if i == 0 else 'right'}")
    return asm.compound()
