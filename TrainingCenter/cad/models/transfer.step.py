"""自動化搬運移載設備 — 整機組裝（text-to-cad / build123d）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from cadgen.assembly import AssemblyHelper  # noqa: E402

import parts as P  # noqa: E402
from layout import anim_datums, place, sub_compound  # noqa: E402


def gen_step():
    asm = AssemblyHelper("transfer_line")
    A = asm.add

    # 主線：滾筒段（每根滾筒各自 spin）
    A(place(P.roller_conveyor("rollers", 2200, 400, 750, legs=True, pitch=80, include_rollers=False), (-1.5, 0, 0)), "rollers")
    for i in range(int(2200 / 80)):
        x = -1.5 + (-1.1 + 0.04 + i * 0.08)
        A(sub_compound("rollers", [place(P.roller(400), (x, 0.725, 0))] + anim_datums("spin", (x, 0.725, 0), (0, 0, 1))), "rollers")
    A(place(P.side_guide("guide", 2200), (-1.5, 0.79, 0.24)), "guide")
    A(place(P.side_guide("guide", 2200), (-1.5, 0.79, -0.24)), "guide")
    # 皮帶段
    belt = P.belt_conveyor("belt", 1400, 400, 750, legs=True, with_motor=False, carrier=False)
    A(place(belt, (1.6, 0, 0)), "belt")
    A(place(P.gear_motor("beltmotor", 110, 200, gearbox=True), (2.3, 0.45, 0.35), yaw_deg=90), "beltmotor")
    # 載具（循環動畫）
    carrier = P.pallet("carrier", 300)
    A(sub_compound("carrier", [place(carrier, (-2.2, 0.76, 0))] + anim_datums("carrier", (-2.2, 0.8, 0), (1, 0, 0))), "carrier")
    A(sub_compound("stopper", [place(P.stopper("stopper"), (-0.55, 0.62, 0))] + anim_datums("rod", (-0.55, 0.7, 0), (0, 1, 0))), "stopper")

    # 移載機
    A(place(P.lift_transfer("lift", 500, 700, include_crossbelt=False), (0, 0, 0)), "lift")
    A(sub_compound("liftcyl", [place(P.pneumatic_cylinder(32, 50, "liftcyl"), (0, 0.45, 0))] + anim_datums("rod", (0, 0.5, 0), (0, 1, 0))), "liftcyl")
    A(sub_compound("crossbelt", [place(P.lift_crossbelt("crossbelt", 500, 700), (0, 0, 0))] + anim_datums("rod", (0, 0.72, 0), (0, 1, 0))), "crossbelt")
    A(place(P.gear_motor("crossmotor", 70, 120, gearbox=False), (0.35, 0.55, 0), yaw_deg=90), "crossmotor")
    for sx in (-0.2, 0.2):
        for sz in (-0.2, 0.2):
            A(place(P.guide_shaft("shaft", 300), (sx, 0.45, sz)), "shaft")
    A(place(P.shock_absorber("shock"), (0.25, 0.5, -0.25)), "shock")
    A(place(P.reed_switch("cylsensor"), (0.0, 0.6, 0.06), rot=(90, 0, 0)), "cylsensor")
    A(place(P.speed_controller("speedctl"), (0.1, 0.5, 0.2)), "speedctl")
    # 支線與 AGV
    A(place(P.roller_conveyor("branch", 1800, 400, 750, legs=True, pitch=80, include_rollers=False), (0, 0, -1.4), yaw_deg=90), "branch")
    for i in range(int(1800 / 80)):
        z = -1.4 - (-0.9 + 0.04 + i * 0.08)
        A(sub_compound("branch", [place(P.roller(400), (0, 0.725, z), yaw_deg=90)] + anim_datums("spin", (0, 0.725, z), (1, 0, 0))), "branch")
    A(sub_compound("agvdock", [place(P.dock_module("agvdock"), (0.25, 0.85, -2.1))] + anim_datums("blink", (0.25, 0.9, -2.14), (0, 1, 0))), "agvdock")
    A(place(P.agv("agv"), (0, 0, -2.9)), "agv")

    # 氣路
    A(place(P.frl_unit("frl", 0.8), (-2.6, 0.35, 0.4)), "frl")
    A(place(P.quick_coupler("fit-coupler"), (-2.8, 0.42, 0.4)), "fit-coupler")
    A(place(P.valve_manifold(8, "manifold"), (0.7, 0.4, 0.45)), "manifold")
    A(place(P.din_module(120, 80, 60, "#5A6470", 12, name="rio"), (0.7, 0.56, 0.45)), "rio")
    A(place(P.air_tube("tube", 600), (0.4, 0.5, 0.3)), "tube")
    A(sub_compound("pswitch", [place(P.pressure_switch("pswitch"), (-2.4, 0.45, 0.4))] + anim_datums("blink", (-2.4, 0.5, 0.4), (0, 1, 0))), "pswitch")
    # 感測
    A(sub_compound("rfid", [place(P.rfid_head("rfid"), (-0.8, 0.77, 0.32))] + anim_datums("blink", (-0.8, 0.8, 0.3), (0, 1, 0))), "rfid")
    A(sub_compound("psensor", [place(P.photo_sensor("psensor"), (-0.4, 0.83, 0.3))] + anim_datums("blink", (-0.4, 0.85, 0.3), (0, 1, 0))), "psensor")
    A(place(P.din_module(120, 50, 30, "#2A7F8F", 6, led=True, name="rdctrl"), (-1.5, 0.58, 0.35)), "rdctrl")
    # 電控箱
    A(place(P.cabinet("ecab", 600, 400, 1500), (2.9, 0.0, -0.6)), "ecab")
    A(place(P.plc("plc", 70, 2), (2.85, 0.95, -0.35)), "plc")
    A(place(P.relay("safety"), (2.9, 0.75, -0.35)), "safety")
    A(place(P.servo_drive("vfd", 70, 150, 180), (2.9, 0.52, -0.35)), "vfd")
    A(place(P.terminal_block("conn-terminal", 12), (2.9, 0.4, -0.32)), "conn-terminal")
    A(place(P.cable_gland("conn-gland"), (2.9, 0.05, -0.32)), "conn-gland")
    A(place(P.heavy_duty_connector("conn-hdc"), (3.32, 0.75, -0.6), rot=(0, 90, 0)), "conn-hdc")
    A(place(P.rj45_industrial("conn-rj45"), (2.9, 1.15, -0.35)), "conn-rj45")
    A(place(P.m23_connector("conn-power"), (2.4, 0.45, -0.3), rot=(90, 0, 0)), "conn-power")
    A(place(P.m12_connector("conn-m12"), (0.7, 0.68, 0.45), rot=(90, 0, 0)), "conn-m12")
    A(place(P.circuit_breaker("util-breaker"), (3.25, 1.02, -0.35)), "util-breaker")
    A(place(P.busbar("util-inlet", 300, 4), (3.25, 1.5, -0.35)), "util-inlet")
    A(place(P.pe_bar("util-pe", 200), (3.25, 0.3, -0.15)), "util-pe")
    A(place(P.ball_valve("util-airvalve"), (-2.9, 0.4, 0.4)), "util-airvalve")
    return asm.compound()
