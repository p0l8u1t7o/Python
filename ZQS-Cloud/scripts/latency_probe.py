r"""Latency probe publisher: one DDATA / alarm / death for a probe device.

Used by ``frontend/e2e/latency.spec.ts`` to measure MQTT -> screen latency on
the running dev stack. Registers its own edge node and device on first use
so the suite is self-contained. Prints the publish timestamp (epoch ms).

    .venv\Scripts\python.exe scripts\latency_probe.py value 450000
    .venv\Scripts\python.exe scripts\latency_probe.py alarm E0001
    .venv\Scripts\python.exe scripts\latency_probe.py death
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
os.environ.setdefault("MQTT_PROTOCOL_VERSION", "311")
os.environ.setdefault("MQTT_USE_SHARED_SUBSCRIPTION", "0")
os.environ.setdefault("LOG_LEVEL", "ERROR")
import django  # noqa: E402

django.setup()
from services.mqtt.client import MqttClient  # noqa: E402
from services.sparkplug import profile as sp_profile  # noqa: E402
from services.sparkplug import topics  # noqa: E402
from services.sparkplug.datatypes import DataType  # noqa: E402
from services.sparkplug.node import EdgeNodeClient, MetricSpec  # noqa: E402
from simulator.physics import METRIC_UNITS  # noqa: E402


class Gateway:
    """一個最小的邊緣節點連線,供 ``scripts/latency_probe.py`` 量測用。

    不做物理模擬:只宣告一組電表指標、能發單筆讀值、事件與警報、能離線。
    桌面主控台本身不用這個類別,它用 ``GatewayRunner``。
    """

    PROBE_METRICS = {
        "grid_power_w": 0.0, "grid_voltage_v": 220.0, "grid_frequency_hz": 60.0,
        "grid_import_energy_kwh": 0.0,
    }

    def __init__(self, log):
        self.log = log
        self.client: MqttClient | None = None
        self.node: EdgeNodeClient | None = None
        self.devices: dict[str, str] = {}
        self.online = False

    def connect(self, group_id: str, node_id: str, devices: dict[str, str]) -> None:
        self.devices = dict(devices)
        client = MqttClient(client_suffix=f"probe-{node_id}", clean_session=True)
        node = EdgeNodeClient(client, group_id, node_id)
        node.next_bd_seq()
        will_qos, will_retain = topics.publish_options(topics.MessageType.NDEATH)
        client.set_last_will(
            topics.build(group_id, topics.MessageType.NDEATH, node_id),
            node.death_payload(), qos=will_qos, retain=will_retain,
        )
        client.subscriptions = node.command_subscriptions()
        client.connect()
        self.client, self.node = client, node
        self.log(f"已連線 broker,節點 {group_id}/{node_id}")

    def birth(self) -> None:
        if not self.node:
            return
        self.node.publish_nbirth()
        for device_id in self.devices:
            specs = [
                MetricSpec("Properties/Firmware", "probe-1.0", DataType.String),
                MetricSpec("Properties/Schema Version", sp_profile.PROFILE_VERSION, DataType.Int32),
            ]
            for key, value in self.PROBE_METRICS.items():
                unit = METRIC_UNITS.get(key, "")
                specs.append(MetricSpec(key, value, DataType.Double, properties={"unit": unit} if unit else None))
            self.node.publish_dbirth(device_id, specs)
        self.online = True

    def death(self) -> None:
        if not self.node:
            return
        for device_id in self.devices:
            self.node.publish_ddeath(device_id)
        self.node.publish_ndeath()
        # Let the broker take the death before a DISCONNECT follows (see
        # GatewayRunner.run for why the bundled broker needs this).
        time.sleep(0.5)
        self.online = False

    def publish_alarm(self, device_id: str, code: str, severity: str, message: str, active: bool) -> None:
        if not self.node:
            return
        self.node.publish_ddata(
            device_id, {f"{sp_profile.ALARM_PREFIX}{code}": active},
            properties={f"{sp_profile.ALARM_PREFIX}{code}": {"severity": severity, "message": message}},
        )

    def disconnect(self) -> None:
        if self.client:
            self.client.disconnect()
        self.client = None
        self.node = None


DEVICE_ID = "LAT-PROBE-0001"
NODE_ID = "LAT-GW"


def ensure_registered() -> None:
    """The probe's own edge node and device, created once."""
    from apps.accounts.models import Organization
    from apps.devices.models import Device, DeviceType, EdgeNode, LifecycleState, Site
    from apps.telemetry.models import RecordingPolicy

    org = Organization.objects.order_by("created_at").first()
    site = Site.objects.filter(organization=org, deleted_at__isnull=True).first()
    node, _ = EdgeNode.objects.get_or_create(
        organization=org, group_id=org.slug, node_id=NODE_ID,
        defaults={"site": site, "name": "Latency probe gateway"},
    )
    Device.objects.update_or_create(
        organization=org, device_id=DEVICE_ID,
        defaults={
            "edge_node": node, "site": site,
            "device_type": DeviceType.objects.filter(key="smart-meter").first(),
            "recording_policy": RecordingPolicy.objects.filter(organization=org).first(),
            "name": "Latency probe meter", "serial_number": DEVICE_ID,
            "is_enabled": True, "commissioning_state": LifecycleState.ACTIVE,
        },
    )
    return org.slug


group = ensure_registered()

kind = sys.argv[1]
value = sys.argv[2] if len(sys.argv) > 2 else ""

gw = Gateway(lambda m: None)
gw.connect(group, NODE_ID, {DEVICE_ID: "meter"})
gw.birth()
time.sleep(0.3)
if kind == "value":
    stamp = time.time()
    gw.node.publish_ddata(DEVICE_ID, {"grid_power_w": float(value)})
elif kind == "alarm":
    stamp = time.time()
    gw.publish_alarm(DEVICE_ID, value, "major", "web latency probe", True)
elif kind == "death":
    stamp = time.time()
    gw.death()
    print(int(stamp * 1000))
    gw.client.disconnect()
    sys.exit(0)
else:
    raise SystemExit("kind must be value|alarm|death")
print(int(stamp * 1000))
time.sleep(0.2)
# Leave the device online: disconnect without a death so the test can
# observe the value, then the next run re-births anyway.
gw.client.disconnect()
