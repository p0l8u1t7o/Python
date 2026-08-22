"""The simulator's own description of the fleet - a JSON file.

This is the contract between platform and simulator, and the only thing
they share besides the wire format. ``manage.py export_fleet_config``
writes it from the registry; anyone can write it by hand, which is also how
a vendor would describe a site they are about to commission.

::

    {
      "broker": {"host": "127.0.0.1", "port": 1883, "username": "", "password": ""},
      "group_id": "zqs-demo",
      "gateways": [
        {
          "node_id": "GW-TAICHUNG", "site_name": "台中工業區廠房",
          "kind": "factory", "timezone": "Asia/Taipei",
          "peak_load_kw": 1200, "pv_peak_kw": 300,
          "battery_kw": 1000, "battery_kwh": 2000,
          "username": "node-zqs-demo-GW-TAICHUNG", "password": "",
          "devices": [
            {"device_id": "TAICHUNG-BESS-01", "role": "battery", "power_metric": "battery_power_w", "name": "..."},
            ...
          ]
        }
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROLES = ("grid_meter", "load_meter", "pv", "battery", "ev_charger", "generator", "controller")


@dataclass
class BrokerConfig:
    host: str = "127.0.0.1"
    port: int = 1883
    username: str = ""
    password: str = ""
    #: MQTT 3.1.1 by default: the bundled dev broker speaks only that, and
    #: EMQX accepts it too.
    protocol: str = "311"


@dataclass
class DeviceConfig:
    device_id: str
    role: str = "controller"
    power_metric: str = ""
    name: str = ""


@dataclass
class GatewayConfig:
    node_id: str
    site_name: str = ""
    kind: str = "factory"
    timezone: str = "Asia/Taipei"
    peak_load_kw: float = 500.0
    pv_peak_kw: float = 300.0
    battery_kw: float = 250.0
    battery_kwh: float = 500.0
    #: Per-node MQTT credential, when the broker enforces one (EMQX).
    username: str = ""
    password: str = ""
    devices: list[DeviceConfig] = field(default_factory=list)


@dataclass
class FleetConfig:
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    group_id: str = "zqs-demo"
    gateways: list[GatewayConfig] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "FleetConfig":
        broker = BrokerConfig(**{k: v for k, v in (raw.get("broker") or {}).items() if k in BrokerConfig.__dataclass_fields__})
        gateways = []
        for g in raw.get("gateways") or []:
            devices = [
                DeviceConfig(**{k: v for k, v in d.items() if k in DeviceConfig.__dataclass_fields__})
                for d in g.get("devices") or []
            ]
            fields = {k: v for k, v in g.items() if k in GatewayConfig.__dataclass_fields__ and k != "devices"}
            gateways.append(GatewayConfig(devices=devices, **fields))
        return cls(broker=broker, group_id=str(raw.get("group_id") or "zqs-demo"), gateways=gateways)


DEFAULT_PATH = Path(__file__).resolve().parent / "fleet.json"


def load(path: str | Path = DEFAULT_PATH) -> FleetConfig:
    with open(path, encoding="utf-8") as handle:
        return FleetConfig.from_dict(json.load(handle))


def save(config: FleetConfig, path: str | Path = DEFAULT_PATH) -> Path:
    path = Path(path)
    path.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
