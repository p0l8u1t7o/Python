"""多站機械手臂協作與視覺手眼協調 — 整機組裝（text-to-cad / build123d）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from cadgen.assembly import AssemblyHelper  # noqa: E402

import parts as P  # noqa: E402
from layout import anim_datums, place, sub_compound  # noqa: E402
from robot import robot_arm  # noqa: E402


def gen_step():
    asm = AssemblyHelper("robot_cell")
    A = asm.add

    # 台座與手臂
    for name, pos, yaw, color, tool, prefix in [
        ("pedestal_r1", (-1.6, 0, 0), 45, "#E8E8E8", "gripper", "r1-"),
        ("pedestal_r2", (0, 0, -1.5), 90, "#F2C744", "screwdriver", "r2-"),
        ("pedestal_r3", (1.0, 0, 0), 180, "#DFE3E6", "vacuum", "r3-"),
    ]:
        A(place(P.pedestal(name, 500, 800), pos), name)
        base_c, j1 = robot_arm(prefix, (pos[0], 0.82, pos[2]), yaw_deg=yaw, color=color, tool=tool)
        A(base_c, f"{prefix}base")
        A(j1, f"{prefix}j1")

    # 站間輸送帶與治具
    belt = P.belt_conveyor("belt", 2400, 250, 750, legs=True, with_motor=True, carrier=False)
    A(place(belt, (0, 0, -0.6)), "belt")
    A(sub_compound("belt_carrier", [place(P.col(P.Box(220, 175, 30).moved(P.Location((0, 0, 765))), P.YELLOW), (-1.0, 0, -0.6))] + anim_datums("carrier", (0, 0.77, -0.6), (1, 0, 0))), "belt_carrier")
    A(sub_compound("fixture", [place(P.fixture("fixture"), (0, 0.77, -0.6))] + anim_datums("rod", (0, 0.8, -0.75), (0, 1, 0))), "fixture")
    # 料盤供料機、料箱、3D 相機支架、固定相機龍門
    A(place(P.tray_feeder("tray"), (-2.4, 0, 0.8)), "tray")
    A(place(P.box(500, 500, 600, "#6B6B6B"), (-2.4, 0, -0.3)), "bin")
    for x in (-2.65, -2.15):
        A(place(P.box(50, 50, 1600, P.FRAME), (x, 0.7, 0.8)), f"gantry_post_{x}")
    A(place(P.box(600, 50, 50, P.FRAME), (-2.4, 2.3, 0.8)), "gantry_beam")
    A(sub_compound("cam-fixed", [place(P.industrial_camera("cam-fixed"), (-2.4, 2.22, 0.8), rot=(180, 0, 0)), place(P.ring_light("lighting", 200, 100, 20), (-2.4, 2.14, 0.8))] + anim_datums("blink", (-2.4, 2.13, 0.8), (0, 1, 0))), "cam-fixed")
    A(place(P.box(50, 50, 1600, P.FRAME), (-2.4, 0.7, -0.3)), "cam3d_post")
    A(sub_compound("cam-3d", [place(P.camera_3d("cam-3d"), (-2.4, 2.26, -0.3), rot=(180, 0, 0))] + anim_datums("blink", (-2.3, 2.25, -0.3), (0, 1, 0))), "cam-3d")
    A(place(P.calib_board("calib", 7, 5, 25), (-2.6, 0.9, -0.6)), "calib")
    A(place(P.push_in_fitting("fit-pushin"), (-1.05, 1.5, 0.08)), "fit-pushin")
    A(place(P.rotary_union("fit-rotary"), (-1.05, 1.52, -0.06)), "fit-rotary")

    # 氣路
    A(place(P.valve_manifold(4, "manifold"), (-1.9, 0.7, -0.4)), "manifold")
    A(place(P.frl_unit("frl", 0.8), (2.6, 0.4, 0.9)), "frl")
    A(place(P.ball_valve("util-airvalve"), (2.6, 0.45, 1.2)), "util-airvalve")

    # 安全
    A(sub_compound("scanner", [place(P.laser_scanner("scanner"), (1.5, 0.2, 1.3))] + anim_datums("blink", (1.5, 0.3, 1.3), (0, 1, 0))), "scanner")
    for x in (-2.25, -0.75, 0.75, 2.25):
        A(place(P.fence_panel("fence", 1500, 2000), (x, 0, 1.8)), "fence")

    # 電控櫃與元件
    A(place(P.cabinet("ecab", 1200, 500, 1800), (2.8, 0.0, -1.2)), "ecab")
    A(place(P.robot_controller("rc", 1000, 300, 300), (2.8, 0.25, -0.9)), "rc")
    A(place(P.ipc("ipc", 400, 300, 150), (2.8, 0.92, -0.9)), "ipc")
    A(place(P.net_switch("switch", 300, 100, 60), (2.8, 0.82, -0.9)), "switch")
    A(place(P.plc("plc", 70, 2), (2.7, 1.25, -0.9)), "plc")
    A(place(P.relay("safety"), (2.95, 1.1, -0.9)), "safety")
    A(place(P.teach_pendant("pendant"), (3.1, 1.05, -0.6), yaw_deg=-90), "pendant")
    A(place(P.terminal_block("conn-terminal", 16), (2.8, 0.55, -0.92)), "conn-terminal")
    A(place(P.cable_gland("conn-gland"), (2.8, 0.2, -0.92)), "conn-gland")
    A(place(P.heavy_duty_connector("conn-hdc"), (3.42, 0.9, -1.2), rot=(0, 90, 0)), "conn-hdc")
    A(place(P.rj45_industrial("conn-rj45"), (2.55, 0.85, -0.9)), "conn-rj45")
    A(place(P.m23_connector("conn-power"), (2.3, 0.6, -0.9), rot=(90, 0, 0)), "conn-power")
    A(place(P.m12_connector("conn-m12"), (-1.9, 0.9, -0.4), rot=(90, 0, 0)), "conn-m12")
    A(place(P.circuit_breaker("util-breaker"), (3.4, 1.32, -1.0)), "util-breaker")
    A(place(P.busbar("util-inlet", 300, 4), (3.4, 1.8, -1.0)), "util-inlet")
    A(place(P.pe_bar("util-pe", 200), (3.4, 0.6, -0.8)), "util-pe")
    return asm.compound()
