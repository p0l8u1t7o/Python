"""參數化零件庫（build123d）。

慣例：單位 mm、+Z 向上、原點在零件「底面中心」（放到場景時給底面中心座標）。
每個 builder 回傳單一 Part 或帶標籤的 Compound；顏色用 cadgen.srgb。
尺寸為型錄等級的示意（標「範例」品牌的元件），不是原廠 CAD。
"""
from __future__ import annotations

import math

from build123d import (
    Align, Axis, Box, Compound, Cone, Cylinder, GeomType, Location, Part, Plane, Pos, Rot, Sphere, Torus,
    chamfer, fillet,
)
from cadgen import srgb
from cadgen.assembly import label_shape

BOT = (Align.CENTER, Align.CENTER, Align.MIN)
C = Align.CENTER

# ---- 顏色 ----
STEEL = "#B8BEC5"
ALU = "#C9CED3"
DARK = "#3B4048"
BLACK = "#1B2430"
BLUE = "#1E5AA8"
SMC_BLUE = "#2A5CAA"
YELLOW = "#D4A017"
RED = "#C8102E"
GREEN = "#2F6B3A"
TEAL = "#2A7F8F"
GREY = "#8A9096"
WHITE = "#E8E8E8"
FRAME = "#7A828C"


def col(shape, hexcolor, alpha=None):
    """指定顏色：hexcolor 可以是 "#RRGGBB" 字串，也可以直接是 build123d Color（例如 srgb() 的結果）。"""
    if isinstance(hexcolor, str):
        shape.color = srgb(hexcolor, alpha) if alpha is not None else srgb(hexcolor)
    else:
        shape.color = hexcolor
    return shape


def _flatten(items):
    for c in items:
        if isinstance(c, (list, tuple)):
            yield from _flatten(c)
        elif c is not None:
            yield c


def comp(name: str, *children) -> Compound:
    """帶標籤的 Compound；children 可任意巢狀清單。"""
    cp = Compound(children=list(_flatten(children)))
    cp.label = name
    return cp


def box(w, d, h, color=GREY, r=0.0, z0=0.0):
    b = Box(w, d, h, align=BOT)
    if r > 0:
        b = fillet(b.edges().filter_by(Axis.Z), min(r, min(w, d) / 2 - 0.1))
    if z0:
        b = b.moved(Location((0, 0, z0)))
    return col(b, color)


def cyl(r, h, color=GREY, z0=0.0, axis="z"):
    """axis: 'z' 直立；'x' 沿 X（原點在底部→軸中心）；'y' 沿 Y。"""
    c = Cylinder(r, h, align=BOT)
    if axis == "x":
        c = Cylinder(r, h).moved(Location((0, 0, r), (0, 90, 0)))
    elif axis == "y":
        c = Cylinder(r, h).moved(Location((0, 0, r), (90, 0, 0)))
    if z0:
        c = c.moved(Location((0, 0, z0)))
    return col(c, color)


def holes_z(shape, pts, d, depth):
    tools = [Pos(x, y, -1) * Cylinder(d / 2, depth + 2, align=BOT) for x, y in pts]
    return shape - tools


# =====================================================================
# 通用箱體類：電控元件、控制器、電力電子
# =====================================================================
def din_module(w=70, d=100, h=120, color="#5A6470", terminals=8, led=True, name="din_module"):
    """DIN 軌模組（PLC／I/O／驅動器）：本體 + 前面端子排 + 指示燈。"""
    body = box(w, d, h, color, r=2)
    tb = box(w - 10, 8, 12, "#2B2B2B", z0=h - 30).moved(Location((0, -d / 2 - 2, 0)))
    pitch = (w - 14) / max(terminals - 1, 1)
    screws = [col(Pos(-(w - 14) / 2 + i * pitch, -d / 2 - 6, h - 24) * Sphere(1.5), STEEL) for i in range(terminals)]
    leds = [col(Pos(-w / 2 + 8 + i * 6, -d / 2 - 0.5, h - 12) * Box(3, 1, 3), "#33CC66") for i in range(min(6, terminals))] if led else []
    # Front service covers, terminal recesses and ventilation distinguish molded
    # controller housings from plain blocks. No vendor branding is reproduced.
    covers = [col(Pos(0, -d / 2 - 0.8, z) * Box(w - 6, 1.5, 25), "#737D85") for z in (18, 50)]
    vents = [col(Pos(-w / 2 + 8 + i * 5, 0, h + 0.2) * Box(1.8, d - 22, 0.5), BLACK) for i in range(max(1, int((w - 16) / 5)))]
    port = col(Pos(w / 2 - 12, -d / 2 - 1.6, 38) * Box(12, 2, 9), BLACK)
    label = col(Pos(0, -d / 2 - 1.7, 57) * Box(w - 12, 0.4, 5), "#AFB8BF")
    return comp(name, body, tb, screws, leds, covers, vents, port, label)


def plc(name="plc", cpu_w=70, io_modules=3):
    parts = [din_module(cpu_w, 100, 120, "#5A6470", 8, name="cpu")]
    for i in range(io_modules):
        m = din_module(35, 100, 120, "#6B7480", 8, name=f"io_{i + 1}")
        parts.append(m.moved(Location((cpu_w / 2 + 35 / 2 + i * 35, 0, 0))))
    rail = box(cpu_w + io_modules * 35 + 20, 35, 7.5, STEEL, z0=-7.5).moved(Location(((io_modules * 35) / 2, 0, 0)))
    return comp(name, parts, rail)


def servo_drive(name="drive", w=60, d=150, h=170):
    body = box(w, d, h, "#3B4048", r=2)
    panel = box(w - 8, 2, 40, "#1B2430", z0=h - 60).moved(Location((0, -d / 2 - 1, 0)))
    disp = col(Pos(0, -d / 2 - 2.5, h - 40) * Box(30, 1, 10), "#33CC66")
    fins = [box(w, 4, h - 20, DARK, z0=10).moved(Location((0, d / 2 - 8 - i * 8, 0))) for i in range(3)]
    return comp(name, body, panel, disp, fins)


def psu(name="psu", w=60, d=110, h=125):
    body = box(w, d, h, STEEL, r=1.5)
    vents = [box(w - 10, 1, 1.2, "#555", z0=20 + i * 6).moved(Location((0, -d / 2 - 0.5, 0))) for i in range(12)]
    return comp(name, body, vents, col(Pos(-w / 2 + 10, -d / 2 - 1, h - 15) * Box(3, 1, 3), "#33CC66"))


def relay(name="relay", w=22.5, d=100, h=110, color=YELLOW):
    body = box(w, d, h, color, r=1)
    leds = [col(Pos(0, -d / 2 - 0.5, h - 15 - i * 8) * Box(3, 1, 3), "#33CC66") for i in range(3)]
    return comp(name, body, leds)


def contactor(name="contactor", w=45, d=80, h=90):
    body = box(w, d, h, "#2B3038", r=1.5)
    top = box(w - 6, d - 10, 8, "#5A6470", z0=h)
    terms = [col(Pos(-15 + i * 15, -d / 2 - 3, h - 12) * Box(8, 6, 8), STEEL) for i in range(3)]
    return comp(name, body, top, terms)


def circuit_breaker(name="breaker", w=105, d=90, h=160):
    body = box(w, d, h, "#2B3038", r=2)
    knob = col(Pos(0, -d / 2 - 12, h / 2) * Rot(90, 0, 0) * Cylinder(22, 24), RED)
    handle = col(Pos(0, -d / 2 - 25, h / 2) * Box(12, 6, 50), YELLOW)
    ring = col(Pos(0, -d / 2 - 1, h / 2) * Rot(90, 0, 0) * Cylinder(30, 2), YELLOW)
    return comp(name, body, ring, knob, handle)


def busbar(name="busbar", w=300, bars=4):
    parts = []
    for i in range(bars):
        c = ["#B87333", "#B87333", "#B87333", "#1E5AA8", "#7CB342"][i % 5]
        parts.append(col(Pos(0, -i * 25, 20) * Box(w, 10, 5), c))
        parts.append(col(Pos(-w / 3, -i * 25, 10) * Box(15, 10, 20), "#333"))
        parts.append(col(Pos(w / 3, -i * 25, 10) * Box(15, 10, 20), "#333"))
    return comp(name, parts)


def pe_bar(name="pe_bar", w=200):
    bar = col(Box(w, 12, 6, align=BOT), "#B87333")
    lugs = [col(Pos(-w / 2 + 15 + i * 25, 0, 6) * Cylinder(3, 4, align=BOT), "#7CB342") for i in range(int((w - 20) / 25))]
    return comp(name, bar, lugs)


def terminal_block(name="terminal_block", n=12, pitch=6.2):
    parts = [box(n * pitch + 10, 35, 7.5, STEEL)]
    for i in range(n):
        c = "#7CB342" if i == n - 1 else ("#1E5AA8" if i == n - 2 else "#8A9096")
        parts.append(box(pitch - 0.4, 42, 45, c, z0=7.5).moved(Location((-(n - 1) * pitch / 2 + i * pitch, 0, 0))))
    return comp(name, parts)


def cable_gland(name="cable_gland", d=20):
    body = col(Cylinder(d / 2 + 4, 10, align=BOT), "#2B2B2B")
    nut = col(Cylinder(d / 2 + 5, 8, align=BOT).moved(Location((0, 0, 10))), "#3B3B3B")
    nut = nut - [(Pos(d / 2 + 5, 0, 14) * Box(1.5, 1, 10)).rotate(Axis.Z, i * 20) for i in range(18)]
    thread = col(Cylinder(d / 2 + 1, 12, align=BOT).moved(Location((0, 0, -12))), STEEL)
    cable = col(Cylinder(d / 2 - 3, 60, align=BOT).moved(Location((0, 0, 18))), "#2B2B2B")
    return comp(name, body, nut, thread, cable)


def heavy_duty_connector(name="hdc", w=110, d=55, h=70):
    hood = box(w, d, h, "#8A9096", r=3)
    levers = [col(Pos(sx * (w / 2 + 3), 0, h * 0.45) * Box(4, d - 10, 30), "#3B4048") for sx in (-1, 1)]
    gland = col(Pos(0, 0, h) * Cylinder(14, 18, align=BOT), "#3B3B3B")
    cable = col(Pos(0, 0, h + 18) * Cylinder(9, 60, align=BOT), "#2B2B2B")
    return comp(name, hood, levers, gland, cable)


def rj45_industrial(name="rj45", ):
    plug = box(16, 45, 12, "#2B2B2B", r=1)
    latch = col(Pos(0, -5, 12) * Box(8, 20, 3), "#4A4A4A")
    boot = box(18, 25, 14, "#1E5AA8", r=2).moved(Location((0, 35, -1)))
    cable = col(Pos(0, 47.5 + 30, 6) * Rot(90, 0, 0) * Cylinder(3.2, 60), "#1E5AA8")
    return comp(name, plug, latch, boot, cable)


def m23_connector(name="m23"):
    shell = col(Cylinder(12.5, 40, align=BOT), STEEL)
    nut = col(Cylinder(14, 12, align=BOT).moved(Location((0, 0, 28))), "#3B3B3B")
    nut = nut - [(Pos(14, 0, 34) * Box(1.5, 1.2, 14)).rotate(Axis.Z, i * 15) for i in range(24)]
    cable = col(Cylinder(5, 60, align=BOT).moved(Location((0, 0, -60))), "#2B2B2B")
    return comp(name, shell, nut, cable)


def m12_connector(name="m12"):
    thread = col(Cylinder(6, 8, align=BOT), STEEL)
    nut = col(Cylinder(7.25, 7, align=BOT).moved(Location((0, 0, -7))), STEEL)
    nut = nut - [(Pos(7.25, 0, -3.5) * Box(1.2, 0.8, 9)).rotate(Axis.Z, i * 15) for i in range(24)]
    grip = col(Cylinder(7.25, 30, align=BOT).moved(Location((0, 0, -37))), BLACK)
    cable = col(Cylinder(2.5, 40, align=BOT).moved(Location((0, 0, -77))), "#2B2B2B")
    insert = col(Cylinder(4.5, 6, align=BOT).moved(Location((0, 0, 1))), "#222")
    pins = [col((Pos(3.5, 0, 6.5) * Cylinder(0.5, 2.3, align=BOT)).rotate(Axis.Z, 45 + i * 90), YELLOW) for i in range(4)]
    return comp(name, thread, nut, grip, cable, insert, pins)


# =====================================================================
# 氣路元件
# =====================================================================
def pneumatic_cylinder(bore=25, stroke=20, name="cylinder", body_color=ALU, rod_out=0.0):
    """薄型／方型氣缸；原點在缸體底面中心，+Z 為桿伸出方向。rod_out：桿伸出量（動畫初始）。"""
    w = bore + 15
    length = bore * 1.6 + stroke
    body = box(w, w, length, body_color, r=3)
    body = holes_z(body, [(sx * (w / 2 - 5), sy * (w / 2 - 5)) for sx in (-1, 1) for sy in (-1, 1)], 5.5, length)
    ports = [Pos(w / 2 - 3, 0, z) * Rot(0, 90, 0) * Cylinder(2.5, 8, align=BOT) for z in (8, length - 8)]
    body = col(body - ports, body_color)
    boss = col(Pos(0, 0, length) * Cylinder(bore * 0.4, 4, align=BOT), GREY)
    slot = col(Pos(-w / 2, 0, length / 2) * Box(1, 4, length - 10), BLUE)
    rod = col(Pos(0, 0, length + 2 + rod_out) * Cylinder(bore * 0.2, stroke + 12, align=BOT), "#D0D4D8")
    nut = col(Pos(0, 0, length + 2 + rod_out + stroke + 12) * Cylinder(bore * 0.3, 5, align=BOT), STEEL)
    return comp(name, body, boss, slot, label_shape(comp("rod", rod, nut), "rod"))


def round_cylinder(bore=20, stroke=100, name="cylinder"):
    """圓形缸（DSNU 型）。"""
    length = stroke + 60
    body = col(Cylinder(bore / 2 + 3, length, align=BOT), STEEL)
    caps = [col(Pos(0, 0, z) * Cylinder(bore / 2 + 5, 10, align=BOT), DARK) for z in (0, length - 10)]
    rod = col(Pos(0, 0, length) * Cylinder(bore * 0.2, stroke + 10, align=BOT), "#D0D4D8")
    return comp(name, body, caps, label_shape(comp("rod", rod), "rod"))


def valve_manifold(stations=5, name="manifold", w_station=10.0):
    base = box(stations * w_station + 30, 70, 30, ALU, r=2)
    valves = []
    for i in range(stations):
        x = -(stations - 1) * w_station / 2 + i * w_station
        valves.append(box(w_station - 1, 60, 40, SMC_BLUE, z0=30).moved(Location((x, 0, 0))))
        valves.append(col(Pos(x, -28, 75) * Box(6, 6, 10), "#222"))  # 線圈
        valves.append(col(Pos(x, 28, 75) * Box(6, 6, 10), "#222"))
        valves.append(col(Pos(x, 0, 75) * Box(3, 3, 2), "#33CC66"))
    ports = [col(Pos(-(stations - 1) * w_station / 2 + i * w_station, -35, 12) * Rot(90, 0, 0) * Cylinder(3.5, 6), "#4AA3FF") for i in range(stations)]
    return comp(name, base, valves, ports)


def solenoid_valve(name="solenoid_valve", w=25, d=60, h=45):
    body = box(w, d, h * 0.5, DARK, r=1)
    coil = box(w * 0.8, d * 0.4, h * 0.5, BLUE, z0=h * 0.5)
    ports = [col(Pos(0, sy * d / 2, 10) * Rot(90, 0, 0) * Cylinder(4, 8), STEEL) for sy in (-1, 1)]
    return comp(name, body, coil, ports, col(Pos(0, 0, h + 2) * Box(w * 0.6, 3, 4), "#222"))


def frl_unit(name="frl", size=1.0):
    parts = []
    for i, (color, bowl) in enumerate([(ALU, True), (ALU, False), (ALU, True)]):
        x = (i - 1) * 60 * size
        parts.append(box(50 * size, 50 * size, 60 * size, color, r=4, z0=80 * size).moved(Location((x, 0, 0))))
        if bowl:
            parts.append(col(Pos(x, 0, 10 * size) * Cylinder(22 * size, 70 * size, align=BOT), "#38414D", 0.5))
        else:
            parts.append(col(Pos(x, 0, 140 * size) * Cylinder(18 * size, 20 * size, align=BOT), "#222"))  # 調壓旋鈕
            parts.append(col(Pos(x, -26 * size, 110 * size) * Rot(90, 0, 0) * Cylinder(20 * size, 6), WHITE))  # 壓力表
    parts.append(col(Pos(0, 0, 100 * size) * Rot(0, 90, 0) * Cylinder(8 * size, 200 * size), STEEL))
    return comp(name, parts)


def regulator(name="regulator"):
    body = col(Cylinder(18, 30, align=BOT), STEEL)
    knob = col(Pos(0, 0, 30) * Cylinder(14, 25, align=BOT), DARK)
    gauge = col(Pos(0, -22, 15) * Rot(90, 0, 0) * Cylinder(16, 6), WHITE)
    ports = [col(Pos(sx * 28, 0, 15) * Rot(0, 90, 0) * Cylinder(6, 20), STEEL) for sx in (-1, 1)]
    return comp(name, body, knob, gauge, ports)


def inline_filter(name="filter", r=15, length=80):
    body = col(Pos(0, 0, r) * Rot(0, 90, 0) * Cylinder(r, length), STEEL)
    ends = [col(Pos(sx * (length / 2 + 8), 0, r) * Rot(0, 90, 0) * Cylinder(r * 0.4, 16), STEEL) for sx in (-1, 1)]
    return comp(name, body, ends)


def push_in_fitting(name="fitting"):
    body = col(Cylinder(5, 10, align=BOT), STEEL)
    hexnut = col(Cylinder(6, 5, align=BOT), STEEL)
    collar = col(Pos(0, 0, 10) * Cylinder(5.5, 4, align=BOT), "#2B2B2B")
    tube = col(Pos(0, 0, 14) * Cylinder(3, 40, align=BOT), "#4AA3FF")
    return comp(name, body, hexnut, collar, tube)


def quick_coupler(name="coupler"):
    body = col(Cylinder(9, 30, align=BOT), STEEL)
    sleeve = col(Pos(0, 0, 30) * Cylinder(11, 14, align=BOT), "#3B3B3B")
    plug = col(Pos(0, 0, 44) * Cylinder(6, 20, align=BOT), STEEL)
    return comp(name, body, sleeve, plug)


def speed_controller(name="speed_ctl"):
    body = col(Cylinder(5, 22, align=BOT), STEEL)
    knob = col(Pos(0, 0, 22) * Cylinder(6, 8, align=BOT), "#2B2B2B")
    elbow = col(Pos(6, 0, 4) * Rot(0, 90, 0) * Cylinder(4, 12), STEEL)
    tube = col(Pos(16, 0, 4) * Rot(0, 90, 0) * Cylinder(3, 40), "#4AA3FF")
    return comp(name, body, knob, elbow, tube)


def air_tube(name="tube", length=400, r=3, color="#4AA3FF"):
    return comp(name, col(Pos(0, 0, r) * Rot(0, 90, 0) * Cylinder(r, length), color))


def pressure_switch(name="pressure_switch"):
    body = box(30, 30, 30, "#2B3038", r=2, z0=20)
    disp = col(Pos(0, -15.5, 38) * Box(22, 1, 9), "#33CC66")
    stem = col(Cylinder(5, 20, align=BOT), STEEL)
    return comp(name, body, disp, stem)


def reed_switch(name="reed_switch"):
    body = box(6, 22, 5, "#2B2B2B", r=1)
    led = col(Pos(0, -8, 5) * Box(2, 2, 0.5), "#FF8800")
    cable = col(Pos(0, 11, 2.5) * Rot(90, 0, 0) * Cylinder(1.5, 60), "#2B2B2B")
    return comp(name, body, led, cable)


def ball_valve(name="ball_valve", size=1.0, handle_color=YELLOW):
    body = col(Pos(0, 0, 20 * size) * Rot(0, 90, 0) * Cylinder(20 * size, 70 * size), "#B5A642")
    hexes = [col(Pos(sx * 45 * size, 0, 20 * size) * Rot(0, 90, 0) * Cylinder(16 * size, 20 * size), "#B5A642") for sx in (-1, 1)]
    stem = col(Pos(0, 0, 40 * size) * Cylinder(6 * size, 20 * size, align=BOT), STEEL)
    handle = col(Pos(50 * size, 0, 60 * size) * Box(120 * size, 12 * size, 6 * size), handle_color)
    return comp(name, body, hexes, stem, handle)


def rotary_union(name="rotary_union"):
    body = col(Cylinder(12, 30, align=BOT), STEEL)
    rot_part = col(Pos(0, 0, 30) * Cylinder(10, 15, align=BOT), DARK)
    ports = [col(Pos(12, 0, z) * Rot(0, 90, 0) * Cylinder(3, 10), "#4AA3FF") for z in (8, 20)]
    return comp(name, body, rot_part, ports)


def coolant_quick_connect(name="quick_connect"):
    body = col(Cylinder(8, 40, align=BOT), "#DDDDDD")
    latch = col(Pos(8, 0, 25) * Box(6, 12, 8), "#2B2B2B")
    hose = col(Pos(0, 0, 40) * Cylinder(6, 50, align=BOT), "#4AA3FF")
    return comp(name, body, latch, hose)


def gripper(name="gripper", open_mm=10.0):
    body = box(40, 30, 50, DARK, r=2)
    body = holes_z(body, [(sx * 14, sy * 9) for sx in (-1, 1) for sy in (-1, 1)], 4.5, 12)
    body = col(body, DARK)
    fingers = [col(Pos(sx * (open_mm / 2 + 2.5), 0, 48) * Box(5, 12, 20, align=BOT), "#C0C0C0") for sx in (-1, 1)]
    rail = col(Pos(0, 0, 47) * Box(36, 15, 4), STEEL)
    screws = [col(Pos(x, -15.5, z) * Rot(90, 0, 0) * Cylinder(2, 1.5), STEEL) for x in (-12, 12) for z in (10, 37)]
    return comp(name, body, rail, screws, label_shape(fingers[0], "finger_left"), label_shape(fingers[1], "finger_right"))


def vacuum_pads(name="vacuum_pads", n=4, pad_d=20):
    plate = box(60, 60, 8, TEAL, r=2, z0=30)
    ejector = box(20, 40, 25, SMC_BLUE, z0=38)
    pads = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            pads.append(col(Pos(sx * 20, sy * 20, 8) * Cylinder(3, 22, align=BOT), STEEL))
            pads.append(col(Pos(sx * 20, sy * 20, 0) * Cone(pad_d / 2, pad_d / 4, 8, align=BOT), "#222"))
    return comp(name, plate, ejector, pads)


def electric_screwdriver(name="screwdriver"):
    body = col(Pos(0, 0, 0) * Cylinder(18, 120, align=BOT), TEAL)
    grip = col(Pos(0, 0, 120) * Cylinder(16, 60, align=BOT), "#2B2B2B")
    bit = col(Pos(0, 0, -50) * Cylinder(3, 50, align=BOT), STEEL)
    return comp(name, body, grip, bit)


def tool_changer(name="tool_changer"):
    master = col(Cylinder(30, 20, align=BOT), STEEL)
    tool = col(Pos(0, 0, -18) * Cylinder(30, 18, align=BOT), DARK)
    ports = [col((Pos(30, 0, 8) * Rot(0, 90, 0) * Cylinder(3, 8)).rotate(Axis.Z, i * 60), "#4AA3FF") for i in range(6)]
    return comp(name, master, tool, ports)


def force_sensor(name="force_sensor"):
    body = col(Cylinder(22, 16, align=BOT), "#2B3038")
    ring = col(Pos(0, 0, 16) * Cylinder(20, 3, align=BOT), STEEL)
    cable = col(Pos(22, 0, 8) * Rot(0, 90, 0) * Cylinder(2, 30), "#2B2B2B")
    return comp(name, body, ring, cable)


def tool_flange(name="flange"):
    body = col(Cylinder(31.5, 8, align=BOT), "#9A9A9A")
    pilot = col(Pos(0, 0, 8) * Cylinder(15.75, 6, align=BOT), "#9A9A9A")
    part = body + pilot
    tools = [(Pos(25, 0, -1) * Cylinder(3.3, 20, align=BOT)).rotate(Axis.Z, 45 + i * 90) for i in range(4)]
    tools += [Pos(25, 0, 4) * Cylinder(3, 20, align=BOT), Pos(0, 0, -1) * Cylinder(10, 20, align=BOT)]
    return comp(name, col(part - tools, "#9A9A9A"))


# =====================================================================
# 感測器／視覺／人機
# =====================================================================
def photo_sensor(name="photo_sensor", color="#1E5AA8"):
    body = box(11, 31, 20, color, r=1)
    lens = col(Pos(0, -15.6, 12) * Box(6, 1, 6), "#111")
    led = col(Pos(0, 0, 20) * Box(3, 3, 1), "#FF8800")
    cable = col(Pos(0, 15.5, 8) * Rot(-90, 0, 0) * Cylinder(2, 40), "#2B2B2B")
    bracket = col(Pos(-8, 0, 10) * Box(3, 20, 20), STEEL)
    return comp(name, body, lens, led, cable, bracket)


def pressure_transmitter(name="pressure_tx"):
    stem = col(Cylinder(6, 15, align=BOT), STEEL)
    hexa = col(Pos(0, 0, 15) * Cylinder(11, 8, align=BOT), STEEL)
    body = col(Pos(0, 0, 23) * Cylinder(9, 40, align=BOT), STEEL)
    m12 = col(Pos(0, 0, 63) * Cylinder(6.5, 10, align=BOT), "#2B2B2B")
    return comp(name, stem, hexa, body, m12)


def rtd_probe(name="rtd"):
    probe = col(Cylinder(3, 60, align=BOT), STEEL)
    hexa = col(Pos(0, 0, 60) * Cylinder(9, 10, align=BOT), STEEL)
    head = col(Pos(0, 0, 70) * Cylinder(14, 22, align=BOT), "#2B6B4F")
    return comp(name, probe, hexa, head)


def gas_detector(name="gas_detector"):
    body = box(120, 60, 120, ALU, r=4)
    disp = col(Pos(0, -30.5, 80) * Box(60, 1, 25), "#33CC66")
    sensor = col(Pos(0, 0, -30) * Cylinder(20, 30, align=BOT), STEEL)
    led = col(Pos(35, -30.5, 100) * Sphere(4), "#FF3030")
    return comp(name, body, disp, sensor, led)


def encoder(name="encoder", d=40):
    body = col(Cylinder(d / 2, 30, align=BOT), "#2B2B2B")
    shaft = col(Pos(0, 0, 30) * Cylinder(3, 15, align=BOT), STEEL)
    flange = col(Cylinder(d / 2 + 5, 3, align=BOT), STEEL)
    cable = col(Pos(0, d / 2, 12) * Rot(-90, 0, 0) * Cylinder(3, 40), "#2B2B2B")
    return comp(name, body, shaft, flange, cable)


def rfid_head(name="rfid"):
    body = box(60, 20, 60, "#2B3038", r=3)
    face = col(Pos(0, -10.5, 30) * Box(50, 1, 50), "#4AA3FF")
    m12 = col(Pos(0, 10, 30) * Rot(-90, 0, 0) * Cylinder(6.5, 12), "#2B2B2B")
    return comp(name, body, face, m12)


def laser_scanner(name="laser_scanner"):
    base = box(110, 110, 40, YELLOW, r=6)
    dome = col(Pos(0, 0, 40) * Cylinder(50, 50, align=BOT), "#222")
    window = col(Pos(0, 0, 50) * Cylinder(51, 30, align=BOT), "#38414D", 0.55)
    return comp(name, base, dome, window)


def light_curtain(name="light_curtain", length=600):
    bar = box(30, 30, length, YELLOW, r=3)
    strip = col(Pos(0, -15.5, length / 2) * Box(12, 1, length - 20), "#222")
    leds = [col(Pos(0, -16, 30 + i * 60) * Box(4, 1, 4), "#FF3030") for i in range(int((length - 40) / 60))]
    return comp(name, bar, strip, leds)


def tower_light(name="tower_light"):
    pole = col(Cylinder(8, 120, align=BOT), STEEL)
    base = col(Cylinder(30, 10, align=BOT), "#2B2B2B")
    tiers = []
    for i, c in enumerate(["#33CC66", "#FFB100", "#FF3030"]):
        tiers.append(col(Pos(0, 0, 120 + i * 45) * Cylinder(28, 45, align=BOT), c, 0.85))
    cap = col(Pos(0, 0, 255) * Cylinder(28, 8, align=BOT), "#2B2B2B")
    return comp(name, pole, base, tiers, cap)


def estop(name="estop"):
    ring = col(Cylinder(30, 3, align=BOT), YELLOW)
    collar = col(Pos(0, 0, 3) * Cylinder(15, 10, align=BOT), "#2B2B2B")
    button = col(Pos(0, 0, 13) * Cylinder(20, 14, align=BOT), RED)
    return comp(name, ring, collar, button)


def hmi_panel(name="hmi", w=310, h=230, d=60):
    body = box(w, d, h, "#3B4048", r=3)
    bezel = box(w - 4, 2, h - 4, "#1B2430", z0=2).moved(Location((0, -d / 2 - 1, 0)))
    screen = col(Pos(0, -d / 2 - 2.5, h / 2) * Box(w - 40, 1, h - 40), "#1F5F8F")
    logo = col(Pos(-w / 2 + 40, -d / 2 - 2.5, h - 12) * Box(40, 1, 6), "#33CC66")
    return comp(name, body, bezel, screen, logo)


def industrial_camera(name="camera", size=29, length=42):
    body = box(size, size, length - 4, ALU, r=1.5, z0=2)
    mount = col(Pos(0, 0, -4) * Cylinder(14.2, 4, align=BOT), GREY)
    mount = col(mount - Pos(0, 0, -5) * Cylinder(12.7, 6, align=BOT), GREY)
    glass = col(Pos(0, 0, -0.5) * Cylinder(12.2, 0.5, align=BOT), "#38414D", 0.5)
    rj45 = col(Pos(-4, 4, length) * Box(16, 13.5, 2), "#111")
    caps = [box(size, size, 2, BLACK, r=1, z0=z) for z in (0, length - 2)]
    screws = [col(Pos(x, y, -0.5) * Cylinder(1.1, 1, align=BOT), STEEL) for x in (-size/2+3, size/2-3) for y in (-size/2+3, size/2-3)]
    plate = col(Pos(size/2+0.1, 0, length/2) * Box(0.4, size-6, 12), GREY)
    return comp(name, body, caps, mount, glass, rj45, screws, plate)


def lens(name="lens", d=30, length=60):
    barrel = col(Pos(0, 0, -length) * Cylinder(d / 2, length, align=BOT), "#111")
    rings = [col(Pos(0, 0, -length + 10 + i * 18) * Cylinder(d / 2 + 1.5, 6, align=BOT), "#333") for i in range(2)]
    front = col(Pos(0, 0, -length - 1) * Cylinder(d / 2 - 3, 1, align=BOT), "#2A3A5A")
    return comp(name, barrel, rings, front)


def ring_light(name="ring_light", od=100, id_=50, h=15):
    body = col(Cylinder(od / 2, h, align=BOT) - Pos(0, 0, -1) * Cylinder(id_ / 2, h + 2, align=BOT), "#2B2B2B")
    leds = col(Pos(0, 0, -0.5) * (Cylinder(od / 2 - 5, 0.5, align=BOT) - Pos(0, 0, -1) * Cylinder(id_ / 2 + 5, 3, align=BOT)), "#FFFFFF")
    cable = col(Pos(od / 2, 0, h / 2) * Rot(0, 90, 0) * Cylinder(2.5, 40), "#2B2B2B")
    return comp(name, body, leds, cable)


def led_bar(name="led_bar", length=200):
    body = box(length, 30, 25, "#2B2B2B", r=2)
    strip = col(Pos(0, 0, -0.5) * Box(length - 10, 20, 0.5), "#FFFFFF")
    return comp(name, body, strip)


def light_controller(name="light_ctl"):
    body = box(100, 120, 40, "#2B3038", r=2)
    knobs = [col(Pos(-30 + i * 20, -61, 30) * Rot(90, 0, 0) * Cylinder(6, 6), "#555") for i in range(4)]
    return comp(name, body, knobs)


def camera_3d(name="camera_3d", w=250, d=80, h=80):
    body = box(w, d, h, "#2B3038", r=6)
    eyes = [col(Pos(sx * 90, -d / 2 - 1, h / 2) * Rot(90, 0, 0) * Cylinder(18, 4), "#111") for sx in (-1, 1)]
    proj = col(Pos(0, -d / 2 - 1, h / 2) * Rot(90, 0, 0) * Cylinder(14, 4), "#4AA3FF")
    return comp(name, body, eyes, proj)


def calib_board(name="calib_board", cols=7, rows=5, sq=25):
    plate = box(cols * sq + 20, rows * sq + 20, 6, "#FAFAFA")
    squares = []
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                squares.append(col(Pos(-(cols - 1) * sq / 2 + c * sq, -(rows - 1) * sq / 2 + r * sq, 6) * Box(sq, sq, 0.5), "#111"))
    return comp(name, plate, squares)


def ipc(name="ipc", w=300, d=250, h=100):
    body = box(w, d, h, "#2B3038", r=3)
    fins = [box(w - 20, 3, 20, "#3B4048", z0=h).moved(Location((0, -d / 2 + 15 + i * 10, 0))) for i in range(int((d - 30) / 10))]
    ports = [col(Pos(-w / 2 + 30 + i * 22, -d / 2 - 1, 25) * Box(16, 1, 14), "#111") for i in range(6)]
    return comp(name, body, fins, ports)


def net_switch(name="switch", w=130, d=110, h=40):
    body = box(w, d, h, TEAL, r=2)
    ports = [col(Pos(-w / 2 + 12 + i * 15, -d / 2 - 1, 20) * Box(12, 1, 11), "#111") for i in range(8)]
    leds = [col(Pos(-w / 2 + 12 + i * 15, -d / 2 - 1, 33) * Box(3, 1, 3), "#33CC66") for i in range(8)]
    return comp(name, body, ports, leds)


def gateway(name="gateway"):
    body = box(45, 100, 110, TEAL, r=2)
    ant = col(Pos(0, 0, 110) * Cylinder(4, 90, align=BOT), "#111")
    leds = [col(Pos(0, -50.5, 90 - i * 8) * Box(3, 1, 3), "#33CC66") for i in range(4)]
    return comp(name, body, ant, leds)


def pcb(name="pcb", w=100, d=60):
    board = box(w, d, 1.6, "#1E6B3A")
    chips = [col(Pos(-w / 4 + i * 20, 0, 1.6) * Box(10, 10, 2), "#111") for i in range(3)]
    header = col(Pos(w / 2 - 8, 0, 1.6) * Box(6, d - 20, 8), "#222")
    return comp(name, board, chips, header)


def teach_pendant(name="pendant"):
    body = box(200, 40, 290, WHITE, r=15)
    screen = col(Pos(0, -20.5, 160) * Box(150, 1, 110), "#1F5F8F")
    keys = [col(Pos(-60 + i * 30, -20.5, 60) * Box(20, 1, 15), "#555") for i in range(5)]
    estop_ = col(Pos(0, -20, 270) * Rot(90, 0, 0) * Cylinder(16, 10), RED)
    cable = col(Pos(0, 20, 30) * Rot(-90, 0, 0) * Cylinder(4, 200), "#2B2B2B")
    return comp(name, body, screen, keys, estop_, cable)


def robot_controller(name="controller", w=430, d=350, h=250):
    body = box(w, d, h, "#3B4048", r=4)
    handles = [col(Pos(sx * (w / 2 - 30), -d / 2 - 12, h / 2) * Box(15, 20, 80), "#222") for sx in (-1, 1)]
    vents = [box(w - 100, 1, 1.5, "#222", z0=30 + i * 8).moved(Location((0, -d / 2 - 0.5, 0))) for i in range(10)]
    return comp(name, body, handles, vents)


# =====================================================================
# 動力／熱流
# =====================================================================
def gear_motor(name="motor", d=90, length=160, gearbox=True):
    body = col(Pos(0, 0, d / 2) * Rot(0, 90, 0) * Cylinder(d / 2, length), DARK)
    fins = [col(Pos(-length / 2 + 20 + i * 12, 0, d / 2) * Rot(0, 90, 0) * (Cylinder(d / 2 + 4, 4) - Cylinder(d / 2 - 1, 6)), DARK) for i in range(int((length - 40) / 12))]
    fancover = col(Pos(-length / 2 - 8, 0, d / 2) * Rot(0, 90, 0) * Cylinder(d / 2 + 2, 16), "#222")
    jbox = box(d * 0.5, d * 0.5, d * 0.35, "#5A6470", z0=d).moved(Location((10, 0, 0))) if True else None
    parts = [body, fins, fancover, jbox]
    if gearbox:
        parts.append(box(d * 0.9, d * 0.9, d * 0.9, "#4A525C", r=8).moved(Location((length / 2 + d * 0.45, 0, d * 0.05))))
        parts.append(col(Pos(length / 2 + d * 0.9 + 10, 0, d / 2) * Rot(0, 90, 0) * Cylinder(d * 0.12, 40), STEEL))
    return comp(name, parts)


def servo_motor(name="servo", size=60, length=120):
    body = box(size, size, length, DARK, r=6).moved(Location((0, 0, 0)))
    body = body.rotate(Axis.Y, 90).moved(Location((-length / 2 + 0, 0, size / 2)))
    flange = col(Pos(length / 2, 0, size / 2) * Rot(0, 90, 0) * Cylinder(size * 0.6, 6), STEEL)
    shaft = col(Pos(length / 2 + 6, 0, size / 2) * Rot(0, 90, 0) * Cylinder(size * 0.12, 30), STEEL)
    enc = col(Pos(-length / 2 - 12, 0, size / 2) * Rot(0, 90, 0) * Cylinder(size * 0.4, 24), "#222")
    conns = [col(Pos(-length / 2 + 25, 0, size + 4) * Box(20, 16, 8), "#222"), col(Pos(-length / 2 + 25, 20, size + 4) * Box(20, 14, 8), "#222")]
    return comp(name, col(body, DARK), flange, shaft, enc, conns)


def fan_unit(name="fan", d=300, depth=80):
    """軸流風扇（含護網），軸向沿 Y（面朝 -Y）。"""
    frame = box(d, depth, d, "#222", r=10)
    frame = col(frame - Pos(0, 0, d / 2) * Rot(90, 0, 0) * Cylinder(d / 2 - 8, depth + 2), "#222")
    hub = col(Pos(0, 0, d / 2) * Rot(90, 0, 0) * Cylinder(d * 0.15, depth * 0.6), "#555")
    blades = []
    for i in range(7):
        b = Box(d * 0.34, 6, d * 0.14).moved(Location((d * 0.28, 0, 0), (35, 0, 0)))
        blades.append(col(b.rotate(Axis.Y, i * 360 / 7).moved(Location((0, 0, d / 2))), "#6A7078"))
    grille = [col(Pos(0, -depth / 2 - 2, d / 2) * Box(d - 10, 2, 2).rotate(Axis.Y, i * 30), "#999") for i in range(6)]
    return comp(name, frame, grille, label_shape(comp("impeller", hub, blades), "impeller"))


def blower(name="blower", d=200):
    scroll = col(Pos(0, 0, d / 2) * Rot(90, 0, 0) * Cylinder(d / 2, d * 0.5), "#3B4048")
    inlet = col(Pos(0, -d * 0.25 - 10, d / 2) * Rot(90, 0, 0) * Cylinder(d * 0.25, 20), "#222")
    outlet = box(d * 0.3, d * 0.5, d * 0.25, "#3B4048").moved(Location((d * 0.5, 0, d * 0.75)))
    motor = col(Pos(0, d * 0.25 + 30, d / 2) * Rot(90, 0, 0) * Cylinder(d * 0.2, 60), DARK)
    return comp(name, scroll, inlet, outlet, motor)


def pump(name="pump"):
    body = col(Cylinder(50, 90, align=BOT), DARK)
    head = col(Pos(0, 0, 90) * Cylinder(55, 30, align=BOT), "#5A6470")
    ports = [col(Pos(55, 0, 105) * Rot(0, 90, 0) * Cylinder(12, 30), STEEL), col(Pos(0, 0, 120) * Cylinder(12, 25, align=BOT), STEEL)]
    return comp(name, body, head, ports)


def radiator(name="radiator", w=1200, h=800, t=60):
    core = box(w - 80, t, h - 80, "#1B1F24", z0=40)
    tanks = [box(40, t + 10, h, DARK).moved(Location((sx * (w / 2 - 20), 0, 0))) for sx in (-1, 1)]
    fins = [box(3, t - 4, h - 90, "#2F343A", z0=45).moved(Location((-w / 2 + 50 + i * 16, 0, 0))) for i in range(int((w - 100) / 16))]
    return comp(name, core, tanks, fins)


def hydrogen_tank(name="tank", d=500, length=1100):
    cylr = d / 2
    body = col(Pos(0, 0, cylr + 50) * Rot(0, 90, 0) * Cylinder(cylr, length - d), RED)
    domes = [col(Pos(sx * (length - d) / 2, 0, cylr + 50) * Sphere(cylr), RED) for sx in (-1, 1)]
    valve = col(Pos(length / 2 - 20, 0, cylr + 50) * Rot(0, 90, 0) * Cylinder(25, 60), "#B5A642")
    saddles = [box(120, d * 0.7, 60, DARK).moved(Location((sx * length * 0.3, 0, 0))) for sx in (-1, 1)]
    return comp(name, body, domes, valve, saddles)


def fuel_cell_stack(name="stack", w=800, d=500, h=600, cells=9):
    endplates = [box(w, d, h, ALU, r=6).moved(Location((0, 0, 0)))]  # 外殼
    plates = [box(20, d + 10, h - 40, "#3B4048", z0=20).moved(Location((-w / 2 + 50 + i * (w - 100) / (cells - 1), 0, 0))) for i in range(cells)]
    rods = [col(Pos(sx * (w / 2 - 30), sy * (d / 2 - 30), -10) * Cylinder(8, h + 20, align=BOT), STEEL) for sx in (-1, 1) for sy in (-1, 1)]
    ports = [col(Pos(-w / 2 - 30, -100 + i * 100, h * 0.6) * Rot(0, 90, 0) * Cylinder(18, 60), STEEL) for i in range(3)]
    return comp(name, endplates, plates, rods, ports)


def humidifier(name="humidifier", d=160, length=350):
    body = col(Pos(0, 0, d / 2) * Rot(0, 90, 0) * Cylinder(d / 2, length), "#D8DCE0")
    flanges = [col(Pos(sx * length / 2, 0, d / 2) * Rot(0, 90, 0) * Cylinder(d / 2 + 15, 12), DARK) for sx in (-1, 1)]
    ports = [col(Pos(sx * length * 0.3, 0, d) * Cylinder(25, 40, align=BOT), STEEL) for sx in (-1, 1)]
    return comp(name, body, flanges, ports)


def air_filter(name="air_filter", w=120, d=300, h=300):
    housing = box(w, d, h, "#E0E4E8", r=4)
    pleats = [box(2, d - 20, h - 20, "#BBBBBB", z0=10).moved(Location((-w / 2 + 10 + i * 8, 0, 0))) for i in range(int((w - 20) / 8))]
    return comp(name, housing, pleats)


def cartridge_housing(name="di_filter", d=120, h=250):
    bowl = col(Cylinder(d / 2, h - 40, align=BOT), BLUE)
    head = col(Pos(0, 0, h - 40) * Cylinder(d / 2 + 8, 40, align=BOT), "#2B2B2B")
    ports = [col(Pos(sx * (d / 2 + 20), 0, h - 20) * Rot(0, 90, 0) * Cylinder(10, 30), STEEL) for sx in (-1, 1)]
    return comp(name, bowl, head, ports)


def power_box(name="power_box", w=500, d=300, h=350, color="#3B4048", heatsink=True):
    body = box(w, d, h, color, r=4)
    parts = [body]
    if heatsink:
        parts += [box(w - 40, 4, h - 40, "#2B3038", z0=20).moved(Location((0, d / 2 + 2 + i * 8, 0))) for i in range(4)]
    parts.append(col(Pos(-w / 2 + 40, -d / 2 - 1, h - 40) * Box(50, 1, 20), "#33CC66"))
    parts += [col(Pos(w / 2 - 40 - i * 30, -d / 2 - 10, 30) * Rot(90, 0, 0) * Cylinder(10, 20), "#222") for i in range(3)]
    return comp(name, parts)


def battery_pack(name="battery", w=500, d=400, h=300):
    case = box(w, d, h, "#2D5F2D", r=6)
    lid = box(w - 20, d - 20, 10, "#3B7A3B", z0=h)
    terms = [col(Pos(sx * 60, 0, h + 10) * Cylinder(10, 20, align=BOT), "#B87333" if sx < 0 else "#333") for sx in (-1, 1)]
    label = col(Pos(0, -d / 2 - 0.5, h / 2) * Box(200, 1, 80), "#FFFFFF")
    return comp(name, case, lid, terms, label)


# =====================================================================
# 輸送／運動
# =====================================================================
def belt_conveyor(name="belt", length=1500, width=300, height=750, legs=True, with_motor=True, carrier=True):
    """皮帶輸送機；原點在地面、皮帶中心線下方。皮帶面在 z=height。"""
    pr = 40
    top = col(Pos(0, 0, height - 6) * Box(length, width, 12), GREEN)
    ret = col(Pos(0, 0, height - 2 * pr - 6) * Box(length, width, 12), "#245530")
    pulleys = [col(Pos(sx * length / 2, 0, height - pr) * Rot(90, 0, 0) * Cylinder(pr, width), STEEL) for sx in (-1, 1)]
    sides = [col(Pos(0, sy * (width / 2 + 20), height - pr) * Box(length + 100, 30, 2 * pr + 40), FRAME) for sy in (-1, 1)]
    bed = col(Pos(0, 0, height - pr) * Box(length, width, 20), "#555C66")
    parts = [top, ret, pulleys, sides, bed]
    if legs:
        parts.append(frame_structure(length - 300, width, height - 2 * pr - 30))
    if with_motor:
        parts.append(gear_motor("motor", 90, 140, gearbox=False).moved(Location((length / 2 - 60, width / 2 + 120, height - 100), (0, 0, 90))))
    if carrier:
        parts.append(label_shape(col(Pos(-length / 2 + 200, 0, height + 15) * Box(220, width * 0.7, 30), YELLOW), "carrier"))
    return comp(name, parts)


def roller(width=400, r=25, name="roller"):
    """單根滾筒，原點在軸心中點（供組裝時各自加動畫節點）。"""
    return comp(name, col(Rot(90, 0, 0) * Cylinder(r, width), STEEL))


def roller_conveyor(name="rollers", length=2000, width=400, height=750, legs=True, pitch=80, include_rollers=True):
    n = int(length / pitch)
    rollers = [label_shape(col(Pos(-length / 2 + pitch / 2 + i * pitch, 0, height - 25) * Rot(90, 0, 0) * Cylinder(25, width), STEEL), f"roller_{i + 1}") for i in range(n)] if include_rollers else []
    sides = [col(Pos(0, sy * (width / 2 + 20), height - 60) * Box(length, 30, 120), FRAME) for sy in (-1, 1)]
    parts = [rollers, sides]
    if legs:
        parts.append(frame_structure(length - 300, width, height - 120))
    return comp(name, parts)


def frame_structure(w, d, h, name="frame", leg=40):
    """鋁擠型機架：四支腳 + 上下橫樑，原點在地面中心。"""
    legs = [col(Pos(sx * w / 2, sy * d / 2, 0) * Box(leg, leg, h, align=BOT), FRAME) for sx in (-1, 1) for sy in (-1, 1)]
    beams = [col(Pos(0, sy * d / 2, h - leg / 2) * Box(w, leg, leg), FRAME) for sy in (-1, 1)]
    beams += [col(Pos(sx * w / 2, 0, h - leg / 2) * Box(leg, d, leg), FRAME) for sx in (-1, 1)]
    beams += [col(Pos(0, sy * d / 2, 120) * Box(w, leg, leg), FRAME) for sy in (-1, 1)]
    feet = [col(Pos(sx * w / 2, sy * d / 2, 0) * Cylinder(50, 15, align=BOT), "#222") for sx in (-1, 1) for sy in (-1, 1)]
    return comp(name, legs, beams, feet)


def side_guide(name="guide", length=2000):
    rail = col(Pos(0, 0, 60) * Box(length, 20, 60), "#E8E8E8")
    brackets = [col(Pos(-length / 2 + 200 + i * 400, 0, 15) * Box(30, 20, 30), STEEL) for i in range(int((length - 300) / 400) + 1)]
    return comp(name, rail, brackets)


def pallet(name="pallet", size=300):
    base = box(size, size, 15, "#2B2B2B", r=6)
    frame = box(size, size, 25, ALU, z0=15)
    frame = col(frame - Pos(0, 0, 14) * Box(size - 40, size - 40, 30, align=BOT), ALU)
    pins = [col(Pos(sx * (size / 2 - 30), sy * (size / 2 - 30), 40) * Cylinder(5, 10, align=BOT), STEEL) for sx in (-1, 1) for sy in (-1, 1)]
    tag = col(Pos(0, size / 2 - 5, 20) * Box(40, 3, 15), "#FFFFFF")
    return comp(name, base, frame, pins, tag)


def stopper(name="stopper"):
    cylb = pneumatic_cylinder(20, 15, "cylinder", body_color=DARK)
    block = col(Pos(0, 0, 70) * Box(40, 60, 20), "#2B2B2B")
    return comp(name, cylb, block)


def lift_crossbelt(name="crossbelt", w=500, h=700):
    plate = col(Pos(0, 0, h + 20) * Box(w - 40, w - 40, 12), ALU)
    belts = [col(Pos(-150 + i * 100, 0, h + 36) * Box(20, w - 20, 20), GREEN) for i in range(4)]
    return comp(name, plate, belts)


def lift_transfer(name="lift", w=500, h=700, include_crossbelt=True):
    base = box(w, w, h - 50, "#3D4650", r=6)
    shafts = [col(Pos(sx * 200, sy * 200, h - 50) * Cylinder(12, 300, align=BOT), "#D0D4D8") for sx in (-1, 1) for sy in (-1, 1)]
    motor = gear_motor("cross_motor", 70, 120, gearbox=False).moved(Location((0, w / 2 + 80, h - 60), (0, 0, 90)))
    return comp(name, base, shafts, lift_crossbelt("crossbelt", w, h) if include_crossbelt else None, motor)


def linear_module(name="linear", length=500, w=60, h=60, carriage=True):
    rail = box(length, w, h, ALU, r=3)
    screw = col(Pos(0, 0, h / 2) * Rot(0, 90, 0) * Cylinder(6, length + 40), STEEL)
    motor = servo_motor("motor", w, 100).moved(Location((length / 2 + 70, 0, 0)))
    parts = [rail, screw, motor]
    if carriage:
        parts.append(label_shape(box(120, w + 20, 25, DARK, r=2, z0=h).moved(Location((0, 0, 0))), "carriage"))
    return comp(name, parts)


def cable_chain(name="chain", length=1200, w=50):
    links = [col(Pos(-length / 2 + 15 + i * 30, 0, 20) * (Box(28, w, 40) - Box(20, w + 2, 32)), "#222") for i in range(int(length / 30))]
    return comp(name, links)


def guide_shaft(name="shaft", length=300):
    return comp(name, col(Cylinder(10, length, align=BOT), "#D0D4D8"), col(Cylinder(20, 30, align=BOT), STEEL))


def shock_absorber(name="shock"):
    body = col(Cylinder(10, 70, align=BOT), YELLOW)
    rod = col(Pos(0, 0, 70) * Cylinder(4, 25, align=BOT), STEEL)
    nuts = [col(Pos(0, 0, z) * Cylinder(14, 6, align=BOT), STEEL) for z in (10, 50)]
    return comp(name, body, rod, nuts)


def tray_feeder(name="tray_feeder"):
    base = box(500, 500, 800, "#4A525C", r=6)
    trays = [box(450, 450, 15, BLUE, z0=800 + i * 20).moved(Location((0, 0, 0))) for i in range(5)]
    return comp(name, base, trays)


def fixture(name="fixture"):
    plate = box(250, 250, 15, ALU, r=4)
    pins = [col(Pos(sx * 80, sy * 80, 15) * Cylinder(6, 20, align=BOT), STEEL) for sx in (-1, 1) for sy in (-1, 1)]
    clamp = pneumatic_cylinder(25, 20, "clamp_cylinder").moved(Location((0, -150, 0)))
    return comp(name, plate, pins, clamp)


def agv(name="agv"):
    body = box(900, 900, 350, "#E07B00", r=40)
    top = box(600, 600, 100, "#3D4650", z0=350)
    lidar = col(Pos(400, -400, 350) * Cylinder(40, 60, align=BOT), "#222")
    wheels = [col(Pos(sx * 300, sy * 380, 60) * Rot(90, 0, 0) * Cylinder(60, 40), "#222") for sx in (-1, 1) for sy in (-1, 1)]
    return comp(name, body, top, lidar, wheels)


def dock_module(name="agvdock"):
    body = box(100, 50, 100, "#2B3038", r=3)
    window = col(Pos(0, -26, 50) * Box(60, 1, 40), "#FF3030", 0.8)
    return comp(name, body, window)


# =====================================================================
# 結構：電控櫃、圍籬、頂棚、底座
# =====================================================================
def cabinet(name="cabinet", w=800, d=500, h=1800, hmi=True, estop_=True):
    body = box(w, d, h, ALU, r=4)
    door = box(w * 0.9, 10, h * 0.94, "#B5BBC1", z0=h * 0.03).moved(Location((0, -d / 2 - 5, 0)))
    handle = col(Pos(w * 0.38, -d / 2 - 22, h * 0.5) * Box(20, 20, 180), "#222")
    hinges = [col(Pos(-w * 0.46, -d / 2 - 12, h * f) * Box(20, 12, 60), "#555") for f in (0.2, 0.5, 0.8)]
    base = box(w, d, 100, "#2B3038").moved(Location((0, 0, -100))) if False else col(Pos(0, 0, 50) * Box(w, d, 100), "#2B3038")
    vents = [col(Pos(0, -d / 2 - 11, h * f) * Box(w * 0.5, 2, 60), FRAME) for f in (0.15, 0.85)]
    parts = [body, door, handle, hinges, vents]
    if hmi:
        parts.append(hmi_panel("hmi").moved(Location((0, -d / 2 - 12, h * 0.66))))
    if estop_:
        parts.append(estop("estop").moved(Location((w * 0.3, -d / 2 - 12, h * 0.78), (90, 0, 0))))
    return comp(name, parts)


def fence_panel(name="fence", length=1500, h=2000):
    posts = [col(Pos(sx * length / 2, 0, 0) * Box(40, 40, h, align=BOT), YELLOW) for sx in (-1, 1)]
    frame = [col(Pos(0, 0, z) * Box(length - 40, 30, 30), YELLOW) for z in (100, h - 30)]
    mesh = col(Pos(0, 0, h / 2 + 35) * Box(length - 60, 4, h - 200), "#FFB100", 0.15)
    return comp(name, posts, frame, mesh)


def pedestal(name="pedestal", w=500, h=800):
    body = box(w, w, h, "#3D4650", r=6)
    top = box(w + 40, w + 40, 20, STEEL, z0=h)
    return comp(name, body, top)


def canopy(name="canopy", w=4000, d=2500, h=2200, posts=4):
    roof = col(Pos(0, 0, h - 25) * Box(w, d, 50), "#4A525C")
    cols_ = [col(Pos(sx * (w / 2 - 100), sy * (d / 2 - 100), 0) * Box(60, 60, h - 50, align=BOT), FRAME) for sx in (-1, 1) for sy in (-1, 1)]
    return comp(name, roof, cols_)


def base_plate(name="base", w=6000, d=3000, t=100):
    return comp(name, box(w, d, t, "#3D4650", r=20))


def pipe_run(points_mm, r=20, color=STEEL, name="pipe"):
    """依折線點列生成管段（mm，CAD 座標）。"""
    segs = []
    for (a, b) in zip(points_mm[:-1], points_mm[1:]):
        ax, ay, az = a
        bx, by, bz = b
        dx, dy, dz = bx - ax, by - ay, bz - az
        L = math.sqrt(dx * dx + dy * dy + dz * dz)
        if L < 1e-6:
            continue
        seg = Cylinder(r, L)
        # 由 +Z 對齊到方向向量
        from build123d import Vector
        from OCP.gp import gp_Quaternion, gp_Vec
        q = gp_Quaternion(gp_Vec(0, 0, 1), gp_Vec(dx, dy, dz))
        seg = seg.moved(Location(Vector((ax + bx) / 2, (ay + by) / 2, (az + bz) / 2), Vector(0, 0, 1), 0)) if False else seg
        seg = _align_z_to(seg, (dx, dy, dz)).moved(Location(((ax + bx) / 2, (ay + by) / 2, (az + bz) / 2)))
        segs.append(col(seg, color))
        segs.append(col(Sphere(r).moved(Location((bx, by, bz))), color))
    return comp(name, segs)


def _align_z_to(shape, d):
    dx, dy, dz = d
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    ux, uy, uz = dx / L, dy / L, dz / L
    # 先繞 Y 轉到與 XZ 平面夾角，再繞 Z
    yaw = math.degrees(math.atan2(uy, ux))
    pitch = math.degrees(math.acos(max(-1.0, min(1.0, uz))))
    return shape.rotate(Axis.Y, pitch).rotate(Axis.Z, yaw)


# =====================================================================
# 機械手臂（獨立零件版，供 CAD Studio／AI 直接呼叫）
# =====================================================================
def scara_arm(name="scara", reach1=250.0, reach2=230.0, z_stroke=200.0, base_d=180.0, column_h=400.0, color=WHITE, theta1=20.0, theta2=-40.0):
    """四軸 SCARA 手臂（例：DENSO HSR-048 臂長 480 = reach1 250 + reach2 230）。原點在底座底面中心，+Z 向上。
    J1/J2 為水平旋轉、J3 為 Z 軸升降、J4 為末端旋轉；theta1/theta2 為靜態姿態（度）。"""
    base = col(Cylinder(base_d / 2, 40, align=BOT), DARK)
    bolts = [col((Pos(base_d / 2 - 15, 0, 40) * Cylinder(6, 8, align=BOT)).rotate(Axis.Z, 45 + i * 90), "#222") for i in range(4)]
    column = col(Cylinder(base_d * 0.42, column_h - 40, align=BOT).moved(Location((0, 0, 40))), color)
    # 第一臂（J1 在柱頂）
    a1_h = 70.0
    z1 = column_h
    j1_housing = col(Cylinder(base_d * 0.4, a1_h, align=BOT).moved(Location((0, 0, z1))), color)
    arm1 = col(Box(reach1, base_d * 0.7, a1_h, align=(Align.MIN, Align.CENTER, Align.MIN)).moved(Location((0, 0, z1))), color)
    arm1 = fillet(arm1.edges().filter_by(Axis.Z), base_d * 0.3)
    arm1 = col(arm1, color)
    seg1 = comp("j1_arm1", j1_housing, arm1)
    seg1 = seg1.rotate(Axis.Z, theta1)
    # 第二臂（J2 在第一臂末端，位於第一臂上方）
    a2_h = 60.0
    z2 = z1 + a1_h
    import math as _m
    e1 = (reach1 * _m.cos(_m.radians(theta1)), reach1 * _m.sin(_m.radians(theta1)))
    j2_housing = col(Cylinder(base_d * 0.32, a2_h, align=BOT), color)
    arm2 = col(Box(reach2, base_d * 0.5, a2_h, align=(Align.MIN, Align.CENTER, Align.MIN)), color)
    arm2 = col(fillet(arm2.edges().filter_by(Axis.Z), base_d * 0.2), color)
    # 末端 Z 軸滾珠花鍵（J3/J4）
    e2_local = reach2
    spline_len = z_stroke + 120
    spline = col(Cylinder(12, spline_len, align=BOT).moved(Location((e2_local, 0, -z_stroke))), "#D0D4D8")
    spline_housing = col(Cylinder(28, a2_h + 60, align=BOT).moved(Location((e2_local, 0, 0))), DARK)
    flange = col(Cylinder(25, 8, align=BOT).moved(Location((e2_local, 0, -z_stroke))), "#9A9A9A")
    seg2 = comp("j2_arm2", j2_housing, arm2, spline_housing, label_shape(comp("j3_spline", spline, flange), "j3_spline"))
    seg2 = seg2.rotate(Axis.Z, theta1 + theta2).moved(Location((e1[0], e1[1], z2)))
    # 線纜管
    duct = col(Cylinder(14, 90, align=BOT).moved(Location((-base_d * 0.2, 0, z1 + a1_h))), "#222")
    return comp(name, base, bolts, column, seg1, seg2, duct)


def articulated_arm(name="arm6", reach=900.0, color=WHITE, pose=(0.0, -25.0, 60.0, -35.0)):
    """六軸垂直多關節手臂（獨立零件版，不需場景座標）。reach≈下臂+上臂長度；pose=(J1,J2,J3,J5) 度。
    原點在底座底面中心，+Z 向上。"""
    import math as _m
    L2 = reach * 0.55
    L3 = reach * 0.45
    q1, q2, q3, q5 = (_m.radians(v) for v in pose)
    base = comp("base", col(Cylinder(reach * 0.2, 30, align=BOT), DARK), col(Cylinder(reach * 0.16, 110, align=BOT).moved(Location((0, 0, 30))), DARK))
    j1 = comp("j1", col(Cylinder(reach * 0.13, 220, align=BOT).moved(Location((0, 0, 140))), color),
              col(Box(reach * 0.2, reach * 0.26, 160, align=BOT).moved(Location((0, 0, 340))), color))
    p2 = (0.0, 0.0, 440.0)

    def seg(p_from, ang, length, r, colr):
        c = Cylinder(r, length, align=BOT).rotate(Axis.Y, _m.degrees(ang))
        return col(c.moved(Location(p_from)), colr)

    d2 = (_m.sin(q2), 0.0, _m.cos(q2))
    p3 = (p2[0] + d2[0] * L2, 0.0, p2[2] + d2[2] * L2)
    d3 = (_m.sin(q2 + q3), 0.0, _m.cos(q2 + q3))
    p4 = (p3[0] + d3[0] * L3, 0.0, p3[2] + d3[2] * L3)
    d5 = (_m.sin(q2 + q3 + q5), 0.0, _m.cos(q2 + q3 + q5))
    p6 = (p4[0] + d5[0] * 150, 0.0, p4[2] + d5[2] * 150)
    j2 = comp("j2", col(Cylinder(reach * 0.13, reach * 0.33).rotate(Axis.X, 90).moved(Location(p2)), DARK), seg(p2, q2, L2, reach * 0.09, color))
    j3 = comp("j3", col(Cylinder(reach * 0.11, reach * 0.28).rotate(Axis.X, 90).moved(Location(p3)), DARK), seg(p3, q2 + q3, L3, reach * 0.08, color))
    wrist = comp("wrist", seg(p4, q2 + q3 + q5, 90, reach * 0.08, DARK), seg((p4[0] + d5[0] * 90, 0, p4[2] + d5[2] * 90), q2 + q3 + q5, 60, reach * 0.065, color))
    fl = tool_flange("flange").rotate(Axis.Y, _m.degrees(q2 + q3 + q5)).moved(Location(p6))
    arm = comp(name, base, j1, j2, j3, wrist, fl)
    return arm.rotate(Axis.Z, _m.degrees(q1))
