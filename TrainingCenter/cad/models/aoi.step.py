"""AOI 檢測機 — 整機組裝（text-to-cad / build123d）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from cadgen.assembly import AssemblyHelper  # noqa: E402

import parts as P  # noqa: E402
from layout import anim_datums, place, sub_compound  # noqa: E402


def gen_step():
    asm = AssemblyHelper("aoi_machine")
    A = asm.add

    # 機台底座、立柱、頂板
    A(place(P.base_plate("base", 3200, 1600, 500), (0, 0, 0)), "machine_base")
    for x in (-1.4, 1.4):
        for z in (-0.6, 0.6):
            A(place(P.box(80, 80, 1200, P.FRAME), (x, 0.5, z)), f"column_{x}_{z}")
    A(place(P.box(3000, 1400, 50, "#4A525C"), (0, 1.7, 0)), "top_plate")

    # 輸送與定位
    belt = P.belt_conveyor("belt", 3000, 300, 750, legs=False, with_motor=False, carrier=False)
    carrier = P.col(P.Box(220, 210, 30).moved(P.Location((-1300, 0, 765))), P.YELLOW)
    A(sub_compound("belt", [place(belt, (0, 0, 0)), sub_compound("belt_carrier", [place(carrier, (0, 0, 0))] + anim_datums("carrier", (0, 0.77, 0), (1, 0, 0)))]), "belt")
    A(place(P.gear_motor("beltmotor", 90, 140, gearbox=False), (1.2, 0.5, 0.35), yaw_deg=90), "beltmotor")
    A(place(P.encoder("encoder"), (-1.35, 0.58, 0.3), rot=(0, -90, 0)), "encoder")
    A(sub_compound("stopper", [place(P.pneumatic_cylinder(20, 15, "stopper"), (0.2, 0.56, 0))] + anim_datums("rod", (0.2, 0.62, 0), (0, 1, 0))), "stopper")
    for z in (0.1, -0.1):
        A(sub_compound("lift", [place(P.pneumatic_cylinder(20, 30, "lift"), (-0.2, 0.55, z))] + anim_datums("rod", (-0.2, 0.6, z), (0, 1, 0))), "lift")
    A(sub_compound("reject", [place(P.round_cylinder(25, 100, "reject"), (1.0, 0.85, -0.5), rot=(-90, 0, 0))] + anim_datums("rod", (1.0, 0.85, -0.35), (0, 0, 1))), "reject")
    A(sub_compound("psensor", [place(P.photo_sensor("psensor"), (0.35, 0.78, 0.2))] + anim_datums("blink", (0.35, 0.8, 0.2), (0, 1, 0))), "psensor")
    A(place(P.push_in_fitting("fit-pushin"), (0.9, 0.42, 0.55)), "fit-pushin")
    A(place(P.quick_coupler("fit-coupler"), (-1.6, 0.42, 0.5)), "fit-coupler")

    # 龍門
    for z in (-0.45, 0.45):
        A(place(P.linear_module("yaxis", 1600, 60, 60, carriage=False), (0, 1.27, z)), "yaxis")
    xmod = P.linear_module("xaxis", 1400, 80, 80, carriage=False)
    zaxis = P.comp("zaxis", P.box(120, 100, 300, "#5A6470", r=4))
    cam = P.industrial_camera("camera")
    lens_ = P.lens("lens", 30, 60)
    ring = P.ring_light("ring", 100, 50, 15)
    A(sub_compound("gantry", [
        place(xmod, (0, 1.31, 0)),
        place(P.cable_chain("chain", 1200, 50), (0, 1.4, 0.15)),
        sub_compound("xcarriage", [
            place(zaxis, (0, 1.05, 0)),
            place(P.servo_motor("servo", 60, 120), (0.7, 1.31, 0), yaw_deg=0),
            place(cam, (0, 1.1, 0), rot=(180, 0, 0)),
            place(lens_, (0, 1.06, 0), rot=(180, 0, 0)),
            place(ring, (0, 0.96, 0)),
        ] + anim_datums("carrier", (0, 1.2, 0), (1, 0, 0))),
    ]), "gantry")
    # 讓 camera/lens/ring/zaxis/servo 可被個別點選：再各放一次極薄的標籤代理是多餘的，
    # 前端以最近的已知節點名稱為準（xcarriage 內各零件本身即有名稱）。

    # 光柵、警示燈、螢幕
    for x in (-1.3, 1.3):
        A(place(P.light_curtain("curtain", 600), (x, 0.7, 0.75)), "curtain")
    A(sub_compound("tower", [place(P.tower_light("tower"), (1.3, 1.75, -0.5))] + anim_datums("blink", (1.3, 2.0, -0.5), (0, 1, 0))), "tower")
    A(place(P.hmi_panel("screen", 350, 250, 40), (1.5, 1.18, 0.6)), "screen")

    # 電控箱與元件
    A(place(P.cabinet("ecab", 600, 350, 1200, hmi=False), (-1.2, 0.0, -0.9)), "ecab")
    A(place(P.plc("plc", 60, 2), (-1.25, 0.75, -0.65)), "plc")
    A(place(P.servo_drive("drive", 60, 150, 170), (-1.2, 0.55, -0.65)), "drive")
    A(place(P.light_controller("lightctrl"), (-1.2, 0.47, -0.65)), "lightctrl")
    A(place(P.psu("psu"), (-1.2, 0.3, -0.65)), "psu")
    A(place(P.ipc("ipc", 300, 250, 100), (-1.6, 0.85, -0.6)), "ipc")
    A(place(P.valve_manifold(5, "manifold"), (1.0, 0.36, 0.5)), "manifold")
    A(place(P.frl_unit("frl", 0.8), (-1.4, 0.3, 0.5)), "frl")
    A(place(P.terminal_block("conn-terminal", 12), (-1.2, 0.25, -0.62)), "conn-terminal")
    A(place(P.cable_gland("conn-gland"), (-1.2, -0.1, -0.62)), "conn-gland")
    A(place(P.heavy_duty_connector("conn-hdc"), (-0.78, 0.6, -0.9), rot=(0, 90, 0)), "conn-hdc")
    A(place(P.rj45_industrial("conn-rj45"), (-1.55, 1.0, -0.6)), "conn-rj45")
    A(place(P.m23_connector("conn-power"), (-1.7, 0.3, -0.6), rot=(90, 0, 0)), "conn-power")
    A(place(P.m12_connector("conn-m12"), (1.0, 0.55, 0.5), rot=(90, 0, 0)), "conn-m12")
    A(place(P.circuit_breaker("util-breaker"), (-1.45, 1.05, -0.7)), "util-breaker")
    A(place(P.busbar("util-inlet", 300, 4), (-1.45, 1.5, -0.7)), "util-inlet")
    A(place(P.pe_bar("util-pe", 200), (-1.45, 0.25, -0.5)), "util-pe")
    A(place(P.ball_valve("util-airvalve"), (-1.7, 0.4, 0.5)), "util-airvalve")
    return asm.compound()
