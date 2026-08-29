"""把 Wikimedia Commons 搜尋關鍵字寫進每個 seed 元件的 photo_query。

格式（以 | 分隔、依序嘗試）：
  cat:<Commons 分類名> [~ 提示詞]  → incategory 直接成員；提示詞用來在成員中排序（命中多者優先）
  deep:<Commons 分類名>            → deepcategory 含子分類（容易跑題，慎用）
  <英文關鍵字>           → 全文搜尋，需所有詞命中標題／描述／分類

執行：python backend/catalog/seed/add_photo_queries.py，之後 manage.py load_seed 再 fetch_photos --force
"""

import json
from pathlib import Path

SEED_DIR = Path(__file__).parent

QUERIES: dict[str, dict[str, str]] = {
    "fuel-cell": {
        "h2-buffer-tank": "cat:Hydrogen tanks | cat:Hydrogen storage | cat:Gas cylinders",
        "h2-regulator": "cat:Pressure regulators ~ regulator gas | gas pressure regulator",
        "h2-solenoid": "cat:Solenoid valves",
        "h2-filter": "cat:Compressed air filters | inline gas filter",
        "h2-purge-valve": "cat:Solenoid valves | cat:Pneumatic valves",
        "pem-stack": "PEM fuel cell stack | cat:Fuel cells",
        "air-blower": "cat:Centrifugal fans ~ blower fan | cat:Blowers ~ blower",
        "air-filter": "cat:Air filters",
        "humidifier": "cat:Fuel cells ~ humidifier | industrial humidifier | cat:Humidifiers ~ humidifier",
        "coolant-pump": "cat:Electric pumps | cat:Water pumps",
        "radiator": "cat:Radiators ~ radiator car | automotive radiator fan | cat:Radiators ~ radiator",
        "di-filter": "cat:Water filters ~ cartridge housing | water filter housing cartridge | cat:Water filters ~ filter",
        "dcdc": "cat:Boost converters | cat:Power electronics",
        "inverter": "cat:Inverters | cat:Power electronics",
        "battery": "cat:Lithium iron phosphate batteries | cat:Battery packs",
        "dc-contactor": "cat:Contactors ~ contactor",
        "plc": "cat:Simatic | cat:Programmable logic controller",
        "safety-plc": "cat:Relays ~ relay module | safety relay module | cat:Relays ~ relay",
        "h2-detector": "cat:Gas sensors ~ detector gas",
        "pressure-tx": "cat:Pressure transducers | cat:Pressure sensors",
        "temp-rtd": "cat:Resistance thermometers | cat:Temperature probes",
        "cvm": "cat:Fuel cells",
        "estop": "cat:Emergency stop buttons",
        "hmi": "cat:Simatic ~ panel HMI | cat:Touchscreens ~ industrial panel",
        "plc-program": "ladder logic | cat:Simatic",
        "scada": "cat:SCADA",
        "bms-firmware": "battery management system | cat:Battery packs",
        "gateway": "Moxa | industrial router | cat:Ethernet switches ~ industrial",
    },
    "aoi": {
        "belt-conveyor": "conveyor belt production line | cat:Assembly lines ~ conveyor | cat:Conveyor belts ~ conveyor",
        "conveyor-motor": "cat:Brushless DC electric motors | cat:Gearmotors",
        "stopper-cyl": "cat:Pneumatic cylinders ~ cylinder pneumatic",
        "lift-locate": "cat:Pneumatic cylinders ~ cylinder compact",
        "reject-cyl": "cat:Pneumatic cylinders ~ cylinder pneumatic | pneumatic cylinder Festo",
        "photo-sensor": "cat:Photoelectric sensors",
        "x-axis": "cat:Linear actuators | cat:Ball screws",
        "y-axis": "cat:Ball screws | cat:Linear actuators",
        "servo-motor": "cat:Servomotors",
        "z-axis": "cat:Linear actuators",
        "cable-chain": "cable carrier drag chain | cable carrier",
        "camera": "cat:Industrial cameras | cat:Machine vision",
        "lens": "cat:Telecentric lenses",
        "ring-light": "ring light camera LED | cat:Ring flashes ~ ring flash | cat:Ring lights ~ ring",
        "light-controller": "LED controller | cat:LED lamps",
        "encoder": "cat:Rotary encoders | cat:Encoders",
        "plc": "cat:Programmable logic controller ~ Mitsubishi | cat:Programmable logic controller ~ PLC",
        "servo-drive": "servo drive | cat:Variable frequency drives",
        "solenoid-manifold": "cat:Manifolds | cat:Solenoid valves",
        "frl": "cat:Compressed air filters | cat:Compressed air",
        "psu": "cat:Switched-mode power supplies | cat:DIN rail",
        "light-curtain": "cat:Keyence | safety light curtain",
        "tower-light": "cat:Signal towers ~ signal tower light | stack light",
        "vision-sw": "cat:Machine vision ~ inspection camera | cat:Computer vision ~ detection",
        "plc-program": "ladder logic | cat:Simatic",
        "recipe-db": "cat:Databases | cat:Servers (computing)",
        "mes-link": "manufacturing execution system | cat:Assembly lines",
        "hmi-ui": "cat:Simatic ~ panel HMI | HMI panel industrial | cat:Touchscreens ~ industrial",
    },
    "transfer": {
        "roller-conveyor": "cat:Roller conveyors ~ pallet roller warehouse | roller conveyor warehouse | cat:Roller conveyors ~ conveyor",
        "belt-section": "conveyor belt factory | cat:Assembly lines ~ conveyor | cat:Conveyor belts ~ conveyor",
        "belt-motor": "cat:Gearmotors | cat:Electric motors",
        "side-guide": "cat:Roller conveyors ~ conveyor guide",
        "carrier": "cat:Pallets ~ plastic pallet | plastic pallet | cat:Pallets ~ pallet",
        "stopper": "cat:Pneumatic cylinders",
        "lift-cyl": "cat:Pneumatic cylinders",
        "cross-belt": "transfer conveyor | cat:Roller conveyors ~ pallet | cat:Conveyor belts ~ conveyor",
        "cross-motor": "cat:Brushless DC electric motors ~ motor",
        "guide-shaft": "linear bearing | cat:Bearings",
        "shock": "cat:Shock absorbers ~ shock absorber | cat:Dampers ~ damper",
        "branch-conveyor": "roller conveyor warehouse | cat:Roller conveyors ~ pallet | cat:Roller conveyors ~ conveyor",
        "frl": "cat:Compressed air filters | cat:Compressed air",
        "valve-manifold": "cat:Manifolds | cat:Solenoid valves",
        "speed-controller": "cat:Needle valves | cat:Pneumatics",
        "air-tube": "cat:Pneumatic hoses | cat:Pneumatics",
        "pressure-switch": "cat:Pressure switches ~ pressure switch | cat:Pressure gauges ~ digital",
        "cylinder-sensor": "cat:Reed switches",
        "plc": "cat:Programmable logic controller ~ Omron | cat:Programmable logic controller ~ PLC",
        "rollerdrive-ctrl": "cat:Interroll | cat:Roller conveyors",
        "remote-io": "remote IO module | cat:DIN rail",
        "rfid": "RFID reader device | cat:RFID ~ reader | cat:RFID ~ tag",
        "photo-sensors": "cat:Photoelectric sensors",
        "safety-relay": "cat:Relays",
        "vfd": "cat:Variable frequency drives ~ drive inverter | cat:Delta Electronics ~ drive",
        "agv-dock": "cat:Automated guided vehicles",
        "plc-program": "ladder logic | cat:Omron",
        "routing": "cat:Automated guided vehicles | cat:Assembly lines",
        "fleet": "cat:Automated guided vehicles",
        "hmi-ui": "cat:Simatic ~ panel HMI | HMI panel industrial | cat:Touchscreens ~ industrial",
    },
    "robot-cell": {
        "base": "cat:Industrial robots",
        "j1": "cat:KUKA robots | cat:Industrial robots",
        "j2": "cat:Fanuc robots | cat:Industrial robots",
        "j3": "cat:ABB robots | cat:Industrial robots",
        "j4-j6": "cat:Universal Robots | cat:Robot arms",
        "reducer": "cat:Harmonic Drive | strain wave gear",
        "joint-servo": "cat:Servomotors",
        "brake": "cat:Electromagnetic brakes",
        "flange": "cat:Robot arms | cat:Universal Robots",
        "dress-pack": "cat:KUKA robots | cat:Industrial robots",
        "pneumatic-gripper": "cat:Grippers | cat:Robot arms",
        "vacuum-pad": "cat:Vacuum grippers | cat:Suction cups",
        "screwdriver": "cat:Electric screwdrivers | cat:Screwdrivers",
        "tool-changer": "robot tool changer | cat:Grippers",
        "force-sensor": "cat:Load cells",
        "tray-feeder": "tray feeder | cat:Assembly lines",
        "cell-conveyor": "conveyor belt assembly line | cat:Assembly lines ~ conveyor",
        "fixture": "cat:Jigs | cat:Pneumatic cylinders",
        "fixed-camera": "cat:Industrial cameras | cat:Machine vision",
        "hand-camera": "cat:Machine vision ~ camera | cat:Cognex ~ camera",
        "3d-camera": "cat:Structured light ~ scanner camera | structured light 3D scanner",
        "calib-board": "camera calibration chessboard | calibration checkerboard camera | checkerboard calibration",
        "vision-ipc": "cat:Industrial PCs | cat:Advantech",
        "lighting": "LED light bar | LED strip light | cat:LED lamps ~ LED",
        "robot-controller": "robot controller | cat:Fanuc robots",
        "teach-pendant": "cat:Teach pendants",
        "master-plc": "cat:Simatic | cat:Programmable logic controller",
        "safety-plc": "cat:Simatic ~ S7 CPU | cat:Pilz ~ PNOZ",
        "laser-scanner": "SICK laser scanner | lidar sensor | cat:Laser scanners ~ scanner",
        "safety-fence": "robot safety fence | robot cell fence | cat:Machine guarding ~ guard",
        "valve-manifold": "cat:Manifolds | cat:Solenoid valves",
        "frl": "cat:Compressed air filters | cat:Compressed air",
        "switch": "cat:Ethernet switches",
        "robot-program": "cat:Teach pendants | cat:Universal Robots",
        "hand-eye-calib": "cat:Universal Robots ~ camera | robot camera calibration",
        "vision-guidance": "cat:Industrial robots ~ vision camera | cat:Machine vision ~ robot",
        "bin-picking": "cat:Industrial robots ~ picking | bin picking robot",
        "cell-plc-program": "ladder logic | cat:Simatic",
        "digital-twin": "robot simulation | cat:Industrial robots",
        "hmi-ui": "cat:Simatic ~ panel HMI | HMI panel industrial | cat:Touchscreens ~ industrial",
    },
}

if __name__ == "__main__":
    for eq_slug, mapping in QUERIES.items():
        path = SEED_DIR / f"{eq_slug}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        n = 0
        for m in data["modules"]:
            for c in m["components"]:
                q = mapping.get(c["slug"])
                if q:
                    c["photo_query"] = q
                    n += 1
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{eq_slug}: {n} components")
