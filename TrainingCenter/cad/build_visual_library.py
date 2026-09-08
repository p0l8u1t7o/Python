"""建置並發布前端共用的元件 GLB 圖庫與精確對應表。

cad/.venv/Scripts/python.exe cad/build_visual_library.py [--skip-build]
接著執行 frontend 的 npm run render:icons 生成 PNG 縮圖。
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from build_all import COMPONENT_BUILDER

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {
    **COMPONENT_BUILDER,
    "safety-plc": "plc", "reducer": "harmonic_reducer", "brake": "robot_brake",
    "tube-fitting": "tube_fitting", "vcr-fitting": "tube_fitting",
    "j1": "robot_j1", "j2": "robot_j2", "j3": "robot_j3", "j4-j6": "robot_wrist", "dress-pack": "air_tube",
    "vision-sw": "software_vision", "plc-program": "software_flow", "recipe-db": "software_data",
    "mes-link": "software_data", "hmi-ui": "software_flow", "scada": "software_data",
    "bms-firmware": "software_flow", "robot-program": "software_flow", "hand-eye-calib": "software_vision",
    "vision-guidance": "software_vision", "bin-picking": "software_vision", "cell-plc-program": "software_flow",
    "digital-twin": "software_vision", "routing": "software_flow", "fleet": "software_data",
}

# 依知識卡料號明確對應，不靠英文關鍵字猜測。軟體與維護主題用相關設備的概念圖。
CARD_MODELS = {
    "MEC": "frame_structure base_plate level_foot linear_module linear_module bearing bearing belt_conveyor harmonic_reducer pneumatic_cylinder reed_switch speed_controller frl_unit vacuum_pads valve_manifold gripper fixture locating_pin rv_reducer belt_conveyor lift_transfer shock_absorber cable_chain bearing fence_panel linear_module",
    "ELE": "cabinet circuit_breaker circuit_breaker contactor power_box psu plc din_module din_module din_module servo_drive servo_motor encoder servo_motor servo_drive relay solenoid_valve photo_sensor photo_sensor photo_sensor reed_switch pressure_switch rtd_probe force_sensor estop relay reed_switch light_curtain tower_light hmi_panel terminal_block fan_unit pe_bar ipc industrial_camera",
    "SFT": "software_flow software_flow software_flow software_flow software_flow software_data software_data software_data software_flow software_flow software_data software_data software_data software_data software_data software_data software_data software_data software_data software_data software_vision software_data",
    "PNE": "compressor hydrogen_tank cabinet air_tube ball_valve solenoid_valve ball_valve inline_filter air_filter regulator humidifier pressure_switch solenoid_valve solenoid_valve valve_manifold quick_coupler air_tube push_in_fitting solenoid_valve solenoid_valve inline_filter regulator inline_filter pressure_switch",
    "CNV": "belt_conveyor roller_conveyor roller_conveyor cable_chain gear_motor roller_conveyor belt_conveyor frame_structure side_guide stopper lift_transfer pallet rfid_head photo_sensor lift_transfer lift_transfer fence_panel belt_conveyor",
    "ARM": "articulated_arm scara_arm delta_robot articulated_arm robot_controller teach_pendant servo_motor harmonic_reducer rv_reducer robot_j2 robot_wrist gripper tool_changer air_tube force_sensor software_vision tool_flange software_vision software_flow software_vision articulated_arm linear_module pneumatic_cylinder fence_panel software_data software_flow",
    "AOI": "industrial_camera industrial_camera lens ring_light light_controller software_flow rj45_industrial linear_module linear_module calib_board software_vision software_vision software_vision software_vision",
    "FCS": "fuel_cell_stack hydrogen_tank regulator solenoid_valve pressure_transmitter solenoid_valve gas_detector fan_unit blower humidifier pump rtd_probe power_box power_box battery_pack power_box plc software_data relay pe_bar",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-build", action="store_true")
    opts = ap.parse_args()
    if not opts.skip_build:
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        subprocess.run([sys.executable, str(ROOT / "cad/build_parts.py")], check=True, env=env)
    cards = {f"{prefix}-{i:02}": model for prefix, models in CARD_MODELS.items() for i, model in enumerate(models.split(), 1)}
    seeds = ROOT / "backend/catalog/seed"
    rows = [c for slug in ("aoi", "fuel-cell", "transfer", "robot-cell") for m in json.loads((seeds / f"{slug}.json").read_text(encoding="utf-8"))["modules"] for c in m["components"]]
    knowledge = json.loads((ROOT / "backend/training/seed/knowledge_cards.json").read_text(encoding="utf-8"))
    missing = [c["slug"] for c in rows if c["slug"] not in COMPONENTS] + [c["code"] for c in knowledge if c["code"] not in cards]
    if missing:
        raise SystemExit(f"Missing visual mappings: {missing}")
    used = set(COMPONENTS.values()) | set(cards.values())
    source = ROOT / "cad/out/parts"
    absent = [m for m in used if not (source / f"{m}.glb").is_file()]
    if absent:
        raise SystemExit(f"Missing models: {absent}")
    public = ROOT / "frontend/public/component-visuals"
    public.mkdir(parents=True, exist_ok=True)
    for model in sorted(used):
        shutil.copyfile(source / f"{model}.glb", public / f"{model}.glb")
    manifest = {"components": COMPONENTS, "cards": cards, "models": sorted(used)}
    (ROOT / "frontend/src/assets/component-visuals.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Published {len(used)} models: {len(rows)}/{len(rows)} components, {len(knowledge)}/{len(knowledge)} cards")


if __name__ == "__main__":
    main()
