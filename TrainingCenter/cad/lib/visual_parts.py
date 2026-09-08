"""元件圖庫補充零件。尺寸為教學示意，非原廠工程圖。"""
import math

from build123d import Axis, Box, Cone, Cylinder, Location, Pos, Rot, Sphere, Torus
import parts as P


def bearing(name="bearing", radius=35, height=18):
    outer = P.col(Cylinder(radius, height, align=P.BOT) - Cylinder(radius - 7, height, align=P.BOT), P.STEEL)
    inner = P.col(Cylinder(radius - 15, height, align=P.BOT) - Cylinder(radius - 21, height, align=P.BOT), P.STEEL)
    balls = [P.col(Pos((radius - 11) * math.cos(i * math.pi / 4), (radius - 11) * math.sin(i * math.pi / 4), height / 2) * Sphere(4.5), P.ALU) for i in range(8)]
    return P.comp(name, outer, inner, balls)


def reducer(name="reducer", height=50):
    body = P.col(Cylinder(45, height, align=P.BOT) - Cylinder(19, height, align=P.BOT), P.STEEL)
    flange = P.col(Cylinder(56, 10, align=P.BOT) - Cylinder(19, 10, align=P.BOT), P.ALU)
    holes = [(47 * math.cos(i * math.pi / 4), 47 * math.sin(i * math.pi / 4)) for i in range(8)]
    flange = P.col(P.holes_z(flange, holes, 5, 10), P.ALU)
    return P.comp(name, body, flange, P.col(Pos(0, 0, height - 8) * (Cylinder(47, 8, align=P.BOT) - Cylinder(19, 8, align=P.BOT)), P.DARK))


def joint(name="joint", length=210):
    shell = P.box(65, 60, length, P.WHITE, r=18)
    hinge = P.col(Pos(0, 0, 55) * Rot(90, 0, 0) * Cylinder(44, 78), P.DARK)
    cover = P.col(Pos(0, -41, 55) * Rot(90, 0, 0) * Cylinder(34, 5), P.STEEL)
    screws = [P.col(Pos(25 * math.cos(i * math.pi / 3), -45, 55 + 25 * math.sin(i * math.pi / 3)) * Rot(90, 0, 0) * Cylinder(3, 3), P.BLACK) for i in range(6)]
    return P.comp(name, shell, hinge, cover, screws)


def software(name="software", mode="flow"):
    """沒有實物外觀的軟體，以不同畫面內容的立體螢幕表示。"""
    body = P.box(180, 15, 120, P.DARK, r=5)
    screen = P.col(Pos(0, -8, 64) * Box(162, 1, 92), "#142838")
    parts = [body, screen, P.box(55, 55, 6, P.STEEL, z0=-30), P.box(15, 12, 30, P.DARK, z0=-25)]
    if mode == "data":
        for i in range(5):
            parts += [P.col(Pos(-42, -10, 91-i*15) * Box(40, 2, 5), P.TEAL), P.col(Pos(24, -10, 91-i*15) * Box(65, 2, 5), P.GREY)]
    elif mode == "vision":
        parts += [P.col(Pos(-25, -10, 67) * Rot(90, 0, 0) * Torus(22, 2), "#44CCAA")]
        for i in range(4):
            parts.append(P.col(Pos(43, -10, 92-i*16) * Box(36, 2, 5), "#44CCAA"))
    else:
        for i in range(3):
            parts.append(P.col(Pos(-48+i*48, -10, 68) * Box(27, 2, 22), "#2BAFB0"))
        parts.append(P.col(Pos(0, -9, 68) * Box(120, 1, 3), P.WHITE))
    return P.comp(name, parts)


def tube_fitting(name="tube_fitting"):
    """不鏽鋼雙卡套管接頭，與塑膠快插接頭分開。"""
    pieces = [P.col(Cylinder(8, 62), P.STEEL)]
    for z in (-18, 18):
        nut = Cylinder(14, 16, align=P.BOT)
        for angle in range(0, 360, 60):
            nut = nut - (Pos(18, 0, 8) * Box(12, 40, 20)).rotate(Axis.Z, angle)
        pieces.append(P.col(nut.moved(Location((0, 0, z-8))), P.STEEL))
    return P.comp(name, pieces)


def level_foot(name="level_foot"):
    return P.comp(name, P.col(Cylinder(35, 9, align=P.BOT), P.BLACK), P.col(Pos(0, 0, 9) * Cone(30, 16, 10, align=P.BOT), P.STEEL), P.col(Pos(0, 0, 19) * Cylinder(7, 65, align=P.BOT), P.STEEL), [P.col(Pos(0, 0, 25+i*4) * Torus(7, 0.65), P.GREY) for i in range(12)])


def delta_robot(name="delta_robot"):
    pieces = [P.col(Cylinder(130, 25, align=P.BOT), P.WHITE), P.col(Pos(0, 0, -250) * Cylinder(38, 20, align=P.BOT), P.STEEL)]
    for angle in (0, 120, 240):
        shoulder = P.comp('arm', P.col(Pos(100, 0, -40) * Box(35, 45, 100), P.WHITE), P.pipe_run([(100, -12, -80), (28, -12, -235)], r=5, color=P.STEEL), P.pipe_run([(100, 12, -80), (28, 12, -235)], r=5, color=P.STEEL))
        pieces.append(shoulder.rotate(Axis.Z, angle))
    return P.comp(name, pieces)


def compressor(name="compressor"):
    tank = P.col(Pos(0, 0, 50) * Rot(0, 90, 0) * Cylinder(50, 200), P.BLUE)
    return P.comp(name, tank, P.box(150, 80, 8, P.STEEL, z0=100), P.gear_motor().scale(0.5).moved(Location((-35, 0, 108))), P.col(Pos(60, 0, 130) * Box(45, 45, 45), P.STEEL), [P.col(Pos(x, y, 10) * Rot(90, 0, 0) * Cylinder(18, 12), P.BLACK) for x in (-70, 70) for y in (-38, 38)])


EXTRA_BUILDERS = {
    "bearing": (bearing, {}), "harmonic_reducer": (reducer, {}), "rv_reducer": (reducer, {"height": 80}),
    "robot_j1": (joint, {"length": 90}), "robot_j2": (joint, {"length": 240}),
    "robot_j3": (joint, {"length": 180}), "robot_wrist": (joint, {"length": 105}),
    "robot_brake": (reducer, {"height": 18}),
    "software_flow": (software, {}), "software_data": (software, {"mode": "data"}), "software_vision": (software, {"mode": "vision"}),
    "tube_fitting": (tube_fitting, {}), "level_foot": (level_foot, {}), "delta_robot": (delta_robot, {}),
    "compressor": (compressor, {}),
    "base_plate": (P.base_plate, {"w": 450, "d": 320, "t": 30}),
    "locating_pin": (P.guide_shaft, {"length": 80}),
}
