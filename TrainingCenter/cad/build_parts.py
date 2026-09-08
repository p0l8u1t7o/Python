"""把零件庫中每個 builder 各自建一次並匯出 glb（元件詳細面板用），同時當作零件庫的煙霧測試。

用法：cad\\.venv\\Scripts\\python.exe cad\\build_parts.py [--only name,name] [--out cad/out/parts]
需要 PYTHONUTF8=1。
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))

from build123d import Unit, export_gltf  # noqa: E402

import parts  # noqa: E402
from visual_parts import EXTRA_BUILDERS  # noqa: E402

# builder 名稱 → 呼叫方式（無參數即用預設）
BUILDERS: dict[str, tuple] = {
    "plc": (parts.plc, {}),
    "din_module": (parts.din_module, {}),
    "servo_drive": (parts.servo_drive, {}),
    "psu": (parts.psu, {}),
    "relay": (parts.relay, {}),
    "contactor": (parts.contactor, {}),
    "circuit_breaker": (parts.circuit_breaker, {}),
    "busbar": (parts.busbar, {}),
    "pe_bar": (parts.pe_bar, {}),
    "terminal_block": (parts.terminal_block, {}),
    "cable_gland": (parts.cable_gland, {}),
    "heavy_duty_connector": (parts.heavy_duty_connector, {}),
    "rj45_industrial": (parts.rj45_industrial, {}),
    "m23_connector": (parts.m23_connector, {}),
    "m12_connector": (parts.m12_connector, {}),
    "pneumatic_cylinder": (parts.pneumatic_cylinder, {}),
    "round_cylinder": (parts.round_cylinder, {}),
    "valve_manifold": (parts.valve_manifold, {}),
    "solenoid_valve": (parts.solenoid_valve, {}),
    "frl_unit": (parts.frl_unit, {}),
    "regulator": (parts.regulator, {}),
    "inline_filter": (parts.inline_filter, {}),
    "push_in_fitting": (parts.push_in_fitting, {}),
    "quick_coupler": (parts.quick_coupler, {}),
    "speed_controller": (parts.speed_controller, {}),
    "air_tube": (parts.air_tube, {}),
    "pressure_switch": (parts.pressure_switch, {}),
    "reed_switch": (parts.reed_switch, {}),
    "ball_valve": (parts.ball_valve, {}),
    "rotary_union": (parts.rotary_union, {}),
    "coolant_quick_connect": (parts.coolant_quick_connect, {}),
    "gripper": (parts.gripper, {}),
    "vacuum_pads": (parts.vacuum_pads, {}),
    "electric_screwdriver": (parts.electric_screwdriver, {}),
    "tool_changer": (parts.tool_changer, {}),
    "force_sensor": (parts.force_sensor, {}),
    "tool_flange": (parts.tool_flange, {}),
    "photo_sensor": (parts.photo_sensor, {}),
    "pressure_transmitter": (parts.pressure_transmitter, {}),
    "rtd_probe": (parts.rtd_probe, {}),
    "gas_detector": (parts.gas_detector, {}),
    "encoder": (parts.encoder, {}),
    "rfid_head": (parts.rfid_head, {}),
    "laser_scanner": (parts.laser_scanner, {}),
    "light_curtain": (parts.light_curtain, {}),
    "tower_light": (parts.tower_light, {}),
    "estop": (parts.estop, {}),
    "hmi_panel": (parts.hmi_panel, {}),
    "industrial_camera": (parts.industrial_camera, {}),
    "lens": (parts.lens, {}),
    "ring_light": (parts.ring_light, {}),
    "led_bar": (parts.led_bar, {}),
    "light_controller": (parts.light_controller, {}),
    "camera_3d": (parts.camera_3d, {}),
    "calib_board": (parts.calib_board, {}),
    "ipc": (parts.ipc, {}),
    "net_switch": (parts.net_switch, {}),
    "gateway": (parts.gateway, {}),
    "pcb": (parts.pcb, {}),
    "teach_pendant": (parts.teach_pendant, {}),
    "robot_controller": (parts.robot_controller, {}),
    "gear_motor": (parts.gear_motor, {}),
    "servo_motor": (parts.servo_motor, {}),
    "fan_unit": (parts.fan_unit, {}),
    "blower": (parts.blower, {}),
    "pump": (parts.pump, {}),
    "radiator": (parts.radiator, {}),
    "hydrogen_tank": (parts.hydrogen_tank, {}),
    "fuel_cell_stack": (parts.fuel_cell_stack, {}),
    "humidifier": (parts.humidifier, {}),
    "air_filter": (parts.air_filter, {}),
    "cartridge_housing": (parts.cartridge_housing, {}),
    "power_box": (parts.power_box, {}),
    "battery_pack": (parts.battery_pack, {}),
    "belt_conveyor": (parts.belt_conveyor, {}),
    "roller_conveyor": (parts.roller_conveyor, {}),
    "frame_structure": (parts.frame_structure, {"w": 1000, "d": 400, "h": 700}),
    "side_guide": (parts.side_guide, {}),
    "pallet": (parts.pallet, {}),
    "stopper": (parts.stopper, {}),
    "lift_transfer": (parts.lift_transfer, {}),
    "linear_module": (parts.linear_module, {}),
    "cable_chain": (parts.cable_chain, {}),
    "guide_shaft": (parts.guide_shaft, {}),
    "shock_absorber": (parts.shock_absorber, {}),
    "tray_feeder": (parts.tray_feeder, {}),
    "fixture": (parts.fixture, {}),
    "agv": (parts.agv, {}),
    "dock_module": (parts.dock_module, {}),
    "cabinet": (parts.cabinet, {}),
    "fence_panel": (parts.fence_panel, {}),
    "pedestal": (parts.pedestal, {}),
    "canopy": (parts.canopy, {}),
    "scara_arm": (parts.scara_arm, {}),
    "articulated_arm": (parts.articulated_arm, {}),
}


BUILDERS.update(EXTRA_BUILDERS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=str(HERE / "out" / "parts"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    names = [n for n in a.only.split(",") if n] or list(BUILDERS)
    ok = fail = 0
    for n in names:
        fn, kw = BUILDERS[n]
        try:
            shape = fn(**kw)
            bb = shape.bounding_box()
            # Display meshes: sub-millimetre tessellation retains mounting holes
            # without hundreds of thousands of triangles in tiny screw heads.
            export_gltf(shape, str(out / f"{n}.glb"), unit=Unit.MM, binary=True,
                        linear_deflection=0.15, angular_deflection=0.22)
            print(f"[OK] {n:24s} bbox {bb.size.X:7.1f} x {bb.size.Y:7.1f} x {bb.size.Z:7.1f} mm")
            ok += 1
        except Exception:  # noqa: BLE001
            fail += 1
            print(f"[ERR] {n}")
            traceback.print_exc(limit=2)
    print(f"done: {ok} ok, {fail} failed")
    if fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
