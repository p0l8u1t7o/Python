"""M12 A-code 4 pin 感測器圓形接頭（公頭，直式，含線纜）。
Origin: 接頭端面中心；+Z 為插入方向的反向（線纜往 -Z）。單位 mm。
"""
from build123d import *
from cadgen import srgb
from cadgen.assembly import AssemblyHelper

thread_d = 12.0
thread_len = 8.0
nut_d = 14.5          # 鎖緊螺帽（滾花）
nut_len = 7.0
grip_d = 14.5
grip_len = 30.0
cable_d = 5.0
cable_len = 40.0
pin_d = 1.0
pin_pcd = 7.0
n_pins = 4


def make_metal():
    thread = Cylinder(thread_d / 2, thread_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
    nut = Pos(0, 0, -nut_len) * Cylinder(nut_d / 2, nut_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
    # 滾花：等分淺槽
    grooves = [(Pos(nut_d / 2, 0, -nut_len / 2) * Box(1.2, 0.8, nut_len + 2)).rotate(Axis.Z, i * 15) for i in range(24)]
    nut = nut - grooves
    metal = thread + nut
    # 插芯絕緣體凹槽
    metal = metal - Pos(0, 0, 1.0) * Cylinder(4.6, thread_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
    metal.color = srgb("#B8BEC5")
    return metal


def make_insert_and_pins():
    insert = Pos(0, 0, 1.0) * Cylinder(4.5, thread_len - 2.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    insert.color = srgb("#222222")
    pins = []
    for i in range(n_pins):
        p = (Pos(pin_pcd / 2, 0, thread_len - 1.5) * Cylinder(pin_d / 2, 0.8 + 1.5, align=(Align.CENTER, Align.CENTER, Align.MIN))).rotate(Axis.Z, 45 + i * 90)
        p.color = srgb("#D4A017")
        pins.append(p)
    return insert, pins


def make_grip_and_cable():
    grip = Pos(0, 0, -nut_len - grip_len) * Cylinder(grip_d / 2, grip_len, align=(Align.CENTER, Align.CENTER, Align.MIN))
    grip = chamfer(grip.faces().sort_by(Axis.Z)[0].edges(), 2.0)
    grip.color = srgb("#1B2430")
    cable = Pos(0, 0, -nut_len - grip_len - cable_len) * Cylinder(cable_d / 2, cable_len + 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
    cable.color = srgb("#2B2B2B")
    return grip, cable


def gen_step():
    asm = AssemblyHelper("m12_connector_a_code_4pin")
    asm.add(make_metal(), "coupling_nut_and_thread")
    insert, pins = make_insert_and_pins()
    asm.add(insert, "insert")
    for i, p in enumerate(pins):
        asm.add(p, f"pin:{i + 1}")
    grip, cable = make_grip_and_cable()
    asm.add(grip, "overmold_grip")
    asm.add(cable, "cable")
    return asm.compound()
