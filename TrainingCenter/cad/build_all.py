"""一鍵建置：四台設備整機 glb（cadgen export，保留節點名稱）＋ 每個元件的 glb，並掛到資料庫。

用法（專案根目錄，需 PYTHONUTF8=1）：
  cad\\.venv\\Scripts\\python.exe cad\\build_all.py                # 全部
  cad\\.venv\\Scripts\\python.exe cad\\build_all.py --equipment aoi
  cad\\.venv\\Scripts\\python.exe cad\\build_all.py --skip-parts
  cad\\.venv\\Scripts\\python.exe cad\\build_all.py --no-attach   # 只產檔不掛載

需要：cad/.venv（cadgen）與 cad/text-to-cad（skill 的 scripts/export）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAD = ROOT / "cad"
SKILL_EXPORT = CAD / "text-to-cad" / "skills" / "cad" / "scripts" / "export"
PROJ_PY = ROOT / ".venv" / "Scripts" / "python.exe"
OUT = CAD / "out"

EQUIPMENT = {"fuel-cell": "fuel_cell", "aoi": "aoi", "transfer": "transfer", "robot-cell": "robot_cell"}

# 元件 slug → 零件庫 builder（build_parts.BUILDERS 的 key）。沒列的軟體類元件共用硬體的 glb（見 SHARE）。
COMPONENT_BUILDER: dict[str, str] = {
    # fuel-cell
    "h2-buffer-tank": "hydrogen_tank", "h2-regulator": "regulator", "h2-solenoid": "solenoid_valve", "h2-filter": "inline_filter",
    "h2-purge-valve": "solenoid_valve", "pem-stack": "fuel_cell_stack", "air-blower": "blower", "air-filter": "air_filter",
    "humidifier": "humidifier", "coolant-pump": "pump", "radiator": "radiator", "di-filter": "cartridge_housing",
    "dcdc": "power_box", "inverter": "power_box", "battery": "battery_pack", "dc-contactor": "contactor",
    "plc": "plc", "safety-plc": "relay", "h2-detector": "gas_detector", "pressure-tx": "pressure_transmitter",
    "temp-rtd": "rtd_probe", "cvm": "pcb", "estop": "estop", "hmi": "hmi_panel", "gateway": "gateway",
    "tube-fitting": "push_in_fitting", "vcr-fitting": "push_in_fitting", "coolant-quick-connect": "coolant_quick_connect",
    # aoi
    "belt-conveyor": "belt_conveyor", "conveyor-motor": "gear_motor", "stopper-cyl": "pneumatic_cylinder",
    "lift-locate": "pneumatic_cylinder", "reject-cyl": "round_cylinder", "photo-sensor": "photo_sensor",
    "x-axis": "linear_module", "y-axis": "linear_module", "servo-motor": "servo_motor", "z-axis": "linear_module",
    "cable-chain": "cable_chain", "camera": "industrial_camera", "lens": "lens", "ring-light": "ring_light",
    "light-controller": "light_controller", "encoder": "encoder", "servo-drive": "servo_drive",
    "solenoid-manifold": "valve_manifold", "frl": "frl_unit", "psu": "psu", "light-curtain": "light_curtain",
    "tower-light": "tower_light", "push-in-fitting": "push_in_fitting", "quick-coupler": "quick_coupler",
    # transfer
    "roller-conveyor": "roller_conveyor", "belt-section": "belt_conveyor", "belt-motor": "gear_motor",
    "side-guide": "side_guide", "carrier": "pallet", "stopper": "stopper", "lift-cyl": "pneumatic_cylinder",
    "cross-belt": "lift_transfer", "cross-motor": "gear_motor", "guide-shaft": "guide_shaft", "shock": "shock_absorber",
    "branch-conveyor": "roller_conveyor", "valve-manifold": "valve_manifold", "speed-controller": "speed_controller",
    "air-tube": "air_tube", "pressure-switch": "pressure_switch", "cylinder-sensor": "reed_switch",
    "rollerdrive-ctrl": "din_module", "remote-io": "din_module", "rfid": "rfid_head", "photo-sensors": "photo_sensor",
    "safety-relay": "relay", "vfd": "servo_drive", "agv-dock": "dock_module",
    # robot-cell
    "base": "pedestal", "reducer": "encoder", "joint-servo": "servo_motor", "brake": "encoder", "flange": "tool_flange",
    "pneumatic-gripper": "gripper", "vacuum-pad": "vacuum_pads", "screwdriver": "electric_screwdriver",
    "tool-changer": "tool_changer", "force-sensor": "force_sensor", "tray-feeder": "tray_feeder",
    "cell-conveyor": "belt_conveyor", "fixture": "fixture", "fixed-camera": "industrial_camera",
    "hand-camera": "industrial_camera", "3d-camera": "camera_3d", "calib-board": "calib_board", "vision-ipc": "ipc",
    "lighting": "led_bar", "robot-controller": "robot_controller", "teach-pendant": "teach_pendant",
    "master-plc": "plc", "laser-scanner": "laser_scanner", "safety-fence": "fence_panel", "switch": "net_switch",
    "rotary-union": "rotary_union",
    # 共用：接頭與水氣電
    "m12-connector": "m12_connector", "terminal-block": "terminal_block", "cable-gland": "cable_gland",
    "heavy-duty-connector": "heavy_duty_connector", "ethernet-connector": "rj45_industrial", "power-connector": "m23_connector",
    "main-breaker": "circuit_breaker", "power-inlet": "busbar", "grounding": "pe_bar", "air-inlet": "ball_valve",
    "water-inlet": "ball_valve",
}


def run(cmd, **kw):
    print("$", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def build_equipment(slug: str, attach: bool):
    name = EQUIPMENT[slug]
    src = CAD / "models" / f"{name}.step.py"
    glb = OUT / "equipment" / f"{slug}.glb"
    glb.parent.mkdir(parents=True, exist_ok=True)
    run([sys.executable, SKILL_EXPORT, src, "--glb", glb, "--mesh-tolerance", "0.5", "--mesh-angular-tolerance", "0.3"], cwd=CAD / "models")
    if attach:
        run([PROJ_PY, ROOT / "backend" / "manage.py", "attach_model", "equipment", slug, glb])


def build_parts(attach: bool, only_equipment: str | None):
    import json

    run([sys.executable, CAD / "build_parts.py", "--out", OUT / "parts"])
    if not attach:
        return
    for slug in EQUIPMENT:
        if only_equipment and slug != only_equipment:
            continue
        seed = json.loads((ROOT / "backend" / "catalog" / "seed" / f"{slug}.json").read_text(encoding="utf-8"))
        for m in seed["modules"]:
            for c in m["components"]:
                b = COMPONENT_BUILDER.get(c["slug"])
                if not b:
                    continue
                glb = OUT / "parts" / f"{b}.glb"
                if glb.exists():
                    run([PROJ_PY, ROOT / "backend" / "manage.py", "attach_model", "component", f"{slug}/{c['slug']}", glb])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--equipment", help="只建這台設備")
    ap.add_argument("--skip-parts", action="store_true")
    ap.add_argument("--skip-equipment", action="store_true")
    ap.add_argument("--no-attach", action="store_true")
    a = ap.parse_args()
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if not a.skip_equipment:
        for slug in EQUIPMENT:
            if a.equipment and slug != a.equipment:
                continue
            build_equipment(slug, attach=not a.no_attach)
    if not a.skip_parts:
        build_parts(attach=not a.no_attach, only_equipment=a.equipment)


if __name__ == "__main__":
    main()
