"""氫燃料電池發電平台 — 整機組裝（text-to-cad / build123d）。
座標沿用前端程序化場景（公尺、Y-up），節點名稱 = seed mesh_name。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from build123d import Location  # noqa: E402
from cadgen.assembly import AssemblyHelper  # noqa: E402

import parts as P  # noqa: E402
from layout import M, anim_datums, place, scene, sub_compound  # noqa: E402


def gen_step():
    asm = AssemblyHelper("fuel_cell_platform")
    A = asm.add

    # 底座、頂棚
    A(place(P.base_plate("base", 6000, 3000, 100), (0, 0, -0.3)), "platform_base")
    A(place(P.canopy("canopy", 4000, 2500, 2200), (-0.5, 0.1, -0.3)), "canopy")

    # 氫氣供應
    A(place(P.hydrogen_tank("h2tank", 500, 1100), (-1.6, 0.1, 0)), "h2tank")
    A(place(P.inline_filter("h2filter", 15, 80), (-1.3, 0.685, 0)), "h2filter")
    A(place(P.regulator("h2reg"), (-1.05, 0.64, 0)), "h2reg")
    A(place(P.pressure_transmitter("ptx"), (-0.85, 0.72, 0)), "ptx")
    A(place(P.solenoid_valve("h2sol"), (-0.7, 0.66, 0)), "h2sol")
    A(place(P.solenoid_valve("purge", 20, 45, 35), (0.5, 0.3, 0.3)), "purge")
    A(place(P.push_in_fitting("fit-tube"), (-1.2, 0.72, 0.1), rot=(90, 0, 0)), "fit-tube")
    A(place(P.push_in_fitting("fit-vcr"), (-0.45, 0.7, 0.05), rot=(90, 0, 0)), "fit-vcr")
    # 管路（CAD mm）
    A(P.pipe_run([scene(-1.4, 0.7, 0), scene(-0.45, 0.7, 0)], r=8, name="h2_pipe"), "h2_pipe")

    # 電堆與空氣
    A(place(P.fuel_cell_stack("stack", 800, 500, 600, 9), (0, 0.3, 0)), "stack")
    A(place(P.pcb("cvm", 300, 200), (0.45, 0.45, 0.1), rot=(0, 90, 0)), "cvm")
    A(place(P.rtd_probe("rtd"), (0.3, 0.5, -0.5)), "rtd")
    blower = P.blower("blower", 200)
    A(sub_compound("blower", [place(blower, (1.1, 0.2, 0.45))] + anim_datums("spin", (1.1, 0.35, 0.45), (0, 0, 1))), "blower")
    A(place(P.air_filter("airfilter", 120, 300, 300), (1.45, 0.2, 0.45)), "airfilter")
    A(place(P.humidifier("humidifier", 160, 350), (0.7, 0.42, 0.45)), "humidifier")

    # 水熱
    A(place(P.pump("pump"), (-0.5, 0.1, -0.7)), "pump")
    A(place(P.cartridge_housing("difilter", 120, 250), (-0.9, 0.1, -0.7)), "difilter")
    A(place(P.radiator("radiator", 1200, 800, 60), (0, 0.3, -1.35)), "radiator")
    for i, x in enumerate((-0.28, 0.28)):
        fan = P.fan_unit(f"fan_{i}", 300, 80)
        A(sub_compound("radiator", [place(fan, (x, 0.55, -1.22))] + anim_datums("spin", (x, 0.7, -1.22), (0, 0, 1))), f"radiator_fan_{i}")
    A(place(P.coolant_quick_connect("fit-coolant"), (-0.2, 0.42, -0.35)), "fit-coolant")
    A(P.pipe_run([scene(-0.3, 0.4, -0.25), scene(-0.5, 0.3, -0.7), scene(-0.4, 0.5, -1.25)], r=10, color="#4AA3FF", name="coolant_pipe_cold"), "coolant_pipe_cold")
    A(P.pipe_run([scene(0.4, 0.5, -1.25), scene(0.3, 0.55, -0.5)], r=10, color="#FF6B6B", name="coolant_pipe_hot"), "coolant_pipe_hot")

    # 電力櫃
    A(place(P.cabinet("powercab", 700, 500, 1400, hmi=False, estop_=False), (1.9, 0.1, -0.8)), "powercab")
    A(place(P.power_box("dcdc", 500, 300, 350), (1.9, 0.82, -0.45)), "dcdc")
    A(place(P.power_box("inverter", 500, 300, 350, "#2A4A6A"), (1.9, 0.27, -0.45)), "inverter")
    A(place(P.contactor("contactor"), (1.5, 0.84, -0.5)), "contactor")
    A(place(P.battery_pack("battery", 500, 400, 300), (2.5, 0.15, -0.8)), "battery")

    # 控制櫃與櫃內元件
    A(place(P.cabinet("cabinet", 800, 500, 1800), (-2.2, 0.1, -0.8)), "cabinet")
    A(place(P.plc("plc", 70, 3), (-2.3, 1.04, -0.5)), "plc")
    A(place(P.relay("safetyplc"), (-1.95, 1.04, -0.5)), "safetyplc")
    A(place(P.gateway("gateway"), (-2.5, 0.85, -0.5)), "gateway")
    A(place(P.terminal_block("conn-terminal", 12), (-2.2, 0.55, -0.52)), "conn-terminal")
    A(place(P.cable_gland("conn-gland"), (-2.2, 0.2, -0.52)), "conn-gland")
    A(place(P.heavy_duty_connector("conn-hdc"), (-1.78, 0.9, -0.8), rot=(0, 90, 0)), "conn-hdc")
    A(place(P.rj45_industrial("conn-rj45"), (-2.5, 0.95, -0.55)), "conn-rj45")
    A(place(P.m23_connector("conn-power"), (-2.7, 0.6, -0.5), rot=(90, 0, 0)), "conn-power")
    A(place(P.m12_connector("conn-m12"), (-1.8, 0.75, -0.55), rot=(90, 0, 0)), "conn-m12")
    # 水氣電
    A(place(P.circuit_breaker("util-breaker"), (-2.55, 1.2, -0.55)), "util-breaker")
    A(place(P.busbar("util-inlet", 300, 4), (-2.55, 1.65, -0.55)), "util-inlet")
    A(place(P.pe_bar("util-pe", 200), (-2.55, 0.4, -0.35)), "util-pe")
    A(place(P.ball_valve("util-airvalve"), (-2.6, 0.5, 0.4)), "util-airvalve")
    A(place(P.ball_valve("util-water", handle_color="#1E5AA8"), (0.7, 0.35, -1.3)), "util-water")

    # 頂棚感測與人機
    A(sub_compound("h2det", [place(P.gas_detector("h2det"), (-0.5, 2.0, 0))] + anim_datums("blink", (-0.5, 2.05, 0), (0, 1, 0))), "h2det")
    A(place(P.hmi_panel("hmi"), (-2.2, 1.19, -0.55)), "hmi")
    A(place(P.estop("estop"), (-2.4, 1.4, -0.55), rot=(90, 0, 0)), "estop")
    return asm.compound()
