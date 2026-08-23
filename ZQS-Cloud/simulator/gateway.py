"""One simulated gateway: a real MQTT client speaking Sparkplug B.

A ``GatewayRunner`` owns one connection to the broker - which is what a
Sparkplug edge node *is* - announces its devices, publishes their readings
on an interval, takes the platform's commands (DCMD), applies them to the
site physics and acknowledges them. Nothing here touches the platform's
database: the only path in or out is the broker.
"""

from __future__ import annotations

import queue
import random
import threading
import time
import uuid
from typing import Callable

import paho.mqtt.client as mqtt

from simulator.config import BrokerConfig, GatewayConfig
from simulator.physics import METRIC_UNITS, SimDevice, SitePhysics

from services.sparkplug import payload as sp  # noqa: E402  (settings configured by package)
from services.sparkplug import profile as sp_profile
from services.sparkplug import topics
from services.sparkplug.datatypes import DataType
from services.sparkplug.node import EdgeNodeClient, MetricSpec

Report = Callable[[str], None]


class MqttLink:
    """The thin paho wrapper ``EdgeNodeClient`` publishes through.

    Deliberately tiny: connect, subscribe, publish (waiting for QoS 1
    confirmation), disconnect, and a message callback. A vendor's firmware
    would have exactly this much.
    """

    def __init__(self, broker: BrokerConfig, client_id: str, *, username: str = "", password: str = "",
                 will: tuple[str, bytes, int, bool] | None = None) -> None:
        self.broker = broker
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv5 if str(broker.protocol) == "5" else mqtt.MQTTv311,
            clean_session=None if str(broker.protocol) == "5" else True,
        )
        user = username or broker.username
        if user:
            self._client.username_pw_set(user, password or broker.password or None)
        if will:
            self._client.will_set(*will)
        self._connected = threading.Event()
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = lambda *_a, **_k: self._connected.clear()
        self.on_message: Callable[[str, bytes, int, bool], None] | None = None
        self._client.on_message = self._dispatch
        self.subscriptions: list[tuple[str, int]] = []

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if self.subscriptions:
            client.subscribe(self.subscriptions)
        self._connected.set()

    def _dispatch(self, client, userdata, message):
        if self.on_message is not None:
            try:
                self.on_message(message.topic, message.payload, message.qos, message.retain)
            except Exception:  # noqa: BLE001 - never kill the network thread
                pass

    def connect(self, timeout: float = 10.0) -> None:
        self._client.connect(self.broker.host, int(self.broker.port), keepalive=45)
        self._client.loop_start()
        if not self._connected.wait(timeout):
            self._client.loop_stop()
            raise ConnectionError(f"no CONNACK from {self.broker.host}:{self.broker.port} within {timeout:.0f}s")

    def publish(self, topic: str, payload: bytes | str, *, qos: int | None = None,
                retain: bool = False, timeout: float = 5.0) -> bool:
        info = self._client.publish(topic, payload, qos=qos or 0, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return False
        if (qos or 0) == 0:
            return True
        try:
            info.wait_for_publish(timeout=timeout)
        except (ValueError, RuntimeError):
            return False
        return info.is_published()

    def disconnect(self) -> None:
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()


class GatewayRunner(threading.Thread):
    """One edge node, from connect to death, on its own thread."""

    def __init__(self, broker: BrokerConfig, group_id: str, spec: GatewayConfig, *,
                 interval: float = 5.0, faults: bool = False, autonomous: bool = False,
                 report: Report = print, physics: SitePhysics | None = None) -> None:
        super().__init__(name=f"gw-{spec.node_id}", daemon=True)
        self.broker = broker
        self.group_id = group_id
        self.spec = spec
        self.node_id = spec.node_id
        self.site_name = spec.site_name
        self.interval = interval
        self.faults = faults
        self.report = report
        self.physics = physics or SitePhysics(
            kind=spec.kind or "factory", timezone_name=spec.timezone or "Asia/Taipei",
            peak_load_kw=spec.peak_load_kw, pv_peak_kw=spec.pv_peak_kw,
            battery_kw_rated=spec.battery_kw, battery_kwh=spec.battery_kwh,
            autonomous=autonomous,
            watchdog_seconds=float(getattr(spec, "watchdog_seconds", 180.0) or 0.0),
            offline_policy=str(getattr(spec, "offline_policy", "reserve") or "reserve"),
            reserve_soc=float(getattr(spec, "reserve_soc", 20.0) or 20.0),
        )
        self.devices = [SimDevice(d.device_id, d.role or "controller", d.power_metric) for d in spec.devices]
        self.stop_event = threading.Event()
        self.online = threading.Event()
        self.published = 0
        self.auto_ack = True
        self.pending_commands: "queue.Queue[dict]" = queue.Queue()
        #: The newest reading set per device - what the console shows.
        self.latest: dict[str, dict] = {}
        self.latest_at: dict[str, float] = {}
        self.last_error = ""
        self._node: EdgeNodeClient | None = None
        self._publish_lock = threading.Lock()
        self._fault_due = time.monotonic() + random.uniform(180, 420)

    # ---- readings ---------------------------------------------------------
    def _birth_metrics(self, device: SimDevice) -> list[MetricSpec]:
        specs = [
            MetricSpec("Properties/Firmware", "zqs-sim-2.0", DataType.String),
            MetricSpec("Properties/Hardware", "simulator", DataType.String),
            MetricSpec("Properties/Schema Version", sp_profile.PROFILE_VERSION, DataType.Int32),
        ]
        for key, value in self._sample(device).items():
            unit = METRIC_UNITS.get(key, "")
            specs.append(MetricSpec(
                key, value, DataType.String if isinstance(value, str) else DataType.Double,
                properties={"unit": unit} if unit else None,
            ))
        return specs

    def _sample(self, device: SimDevice) -> dict:
        values = self.physics.sample(device.role, device.power_metric)
        self.latest[device.device_id] = values
        self.latest_at[device.device_id] = time.time()
        return values

    def _publish_all(self, node: EdgeNodeClient) -> None:
        for device in self.devices:
            node.publish_ddata(device.device_id, self._sample(device))
            self.published += 1

    # ---- manual injection (console test panel) ---------------------------
    def publish_event(self, device_id: str, code: str, level: str, message: str) -> None:
        node = self._node
        if node is None or not self.online.is_set() or self.stop_event.is_set():
            self.report(f"[{self.node_id}] offline, event not sent")
            return
        with self._publish_lock:
            node.publish_ddata(device_id, {f"{sp_profile.EVENT_PREFIX}{code}": message},
                               properties={f"{sp_profile.EVENT_PREFIX}{code}": {"level": level}})
        self.report(f"[{self.node_id}] TX event {device_id} {code} [{level}] {message}")

    def publish_alarm(self, device_id: str, code: str, severity: str, message: str, active: bool) -> None:
        node = self._node
        if node is None or not self.online.is_set() or self.stop_event.is_set():
            self.report(f"[{self.node_id}] offline, alarm not sent")
            return
        with self._publish_lock:
            node.publish_ddata(device_id, {f"{sp_profile.ALARM_PREFIX}{code}": active},
                               properties={f"{sp_profile.ALARM_PREFIX}{code}": {"severity": severity, "message": message}})
        self.report(f"[{self.node_id}] TX alarm {device_id} {code} [{severity}] {'raised' if active else 'cleared'}")

    def answer(self, device_id: str, command_id: str, status: str, *, name: str = "", params: dict | None = None) -> None:
        node = self._node
        if node is None or self.stop_event.is_set():
            return
        with self._publish_lock:
            if status == "succeeded" and name:
                outcome = self.physics.command(name, params or {})
                self.physics.step()
                self._publish_all(node)
                node.ack(device_id, command_id, status, message=outcome)
            else:
                node.ack(device_id, command_id, status)
        self.report(f"[{self.node_id}] TX ack {command_id} -> {status}")

    # ---- the connection ----------------------------------------------------
    def run(self) -> None:
        # The will must carry this session's bdSeq, so the node is built
        # first and the link second, then wired together.
        node = EdgeNodeClient(None, self.group_id, self.node_id)
        node.next_bd_seq()
        will_qos, will_retain = topics.publish_options(topics.MessageType.NDEATH)
        link = MqttLink(
            self.broker, client_id=f"zqs-sim-{self.node_id}-{uuid.uuid4().hex[:6]}",
            username=self.spec.username, password=self.spec.password,
            will=(topics.build(self.group_id, topics.MessageType.NDEATH, self.node_id),
                  node.death_payload(), will_qos, will_retain),
        )
        node.client = link
        self._node = node

        def announce() -> None:
            with self._publish_lock:
                if self.stop_event.is_set():
                    return
                self.physics.step()
                node.publish_nbirth()
                for device in self.devices:
                    node.publish_dbirth(device.device_id, self._birth_metrics(device))

        def on_message(topic: str, raw: bytes, qos: int, retain: bool) -> None:
            if self.stop_event.is_set():
                return
            parsed = topics.parse(topic)
            if parsed is None:
                return
            try:
                view = sp.decode(raw)
            except sp.PayloadError:
                return
            names = {metric.name: metric.value for metric in view.metrics}
            if names.get(sp.NODE_REBIRTH_METRIC) or names.get(sp.DEVICE_REBIRTH_METRIC):
                self.report(f"[{self.node_id}] RX rebirth request")
                announce()
                return
            command_id = names.get(sp_profile.COMMAND_ID)
            if not command_id or parsed.device_id not in {d.device_id for d in self.devices}:
                return
            name = str(names.get(sp_profile.COMMAND_NAME, ""))
            params = {
                key[len(sp_profile.COMMAND_PREFIX):]: value
                for key, value in names.items()
                if key.startswith(sp_profile.COMMAND_PREFIX)
                and key not in (sp_profile.COMMAND_ID, sp_profile.COMMAND_NAME, sp_profile.COMMAND_EXPIRES)
            }
            self.report(f"[{self.node_id}] RX command {parsed.device_id} {name} {params}")
            if not self.auto_ack:
                self.pending_commands.put({"node_id": self.node_id, "device_id": parsed.device_id,
                                           "command_id": str(command_id), "name": name, "params": params})
                return
            with self._publish_lock:
                if self.stop_event.is_set():
                    return
                node.ack(parsed.device_id, str(command_id), "accepted")
                outcome = self.physics.command(name, params)
                self.physics.step()
                self._publish_all(node)
                node.ack(parsed.device_id, str(command_id), "succeeded", message=outcome)
            self.report(f"[{self.node_id}] {parsed.device_id} {name} {params} -> {outcome}")

        link.on_message = on_message
        link.subscriptions = node.command_subscriptions()
        try:
            link.connect()
            announce()
        except Exception as exc:  # noqa: BLE001 - surface in the console, do not hang
            self.last_error = str(exc)
            self.report(f"[{self.node_id}] connect failed: {exc}")
            self._node = None
            return
        self.online.set()
        self.report(f"[{self.node_id}] online at {self.broker.host}:{self.broker.port} with {len(self.devices)} device(s)")

        try:
            while not self.stop_event.is_set():
                with self._publish_lock:
                    if self.stop_event.is_set():
                        break
                    # 連線狀態餵給 watchdog：broker 斷掉就是「雲端不見了」。
                    if link.connected:
                        self.physics.link_down_since = None
                    elif self.physics.link_down_since is None:
                        self.physics.link_down_since = time.monotonic()
                    self.physics.step()
                    self._publish_all(node)
                    if self.faults and time.monotonic() >= self._fault_due:
                        self._inject_fault(node)
                        self._fault_due = time.monotonic() + random.uniform(240, 600)
                self.stop_event.wait(self.interval)
        finally:
            self.online.clear()
            link.on_message = None
            with self._publish_lock:
                try:
                    for device in self.devices:
                        node.publish_ddeath(device.device_id)
                    if not node.publish_ndeath():
                        self.report(f"[{self.node_id}] NDEATH not confirmed")
                    # Let the broker take the deaths before DISCONNECT; some
                    # brokers drop a PUBLISH that a DISCONNECT follows at once.
                    time.sleep(0.5)
                    link.disconnect()
                except Exception:  # noqa: BLE001 - best effort on the way out
                    pass
            self._node = None
            self.report(f"[{self.node_id}] offline")

    def _inject_fault(self, node: EdgeNodeClient) -> None:
        battery = next((d for d in self.devices if d.role == "battery"), None)
        target = battery or self.devices[0]
        if random.random() < 0.5:
            code = random.choice(["E0101", "E0231", "W0042"])
            level = "error" if code.startswith("E") else "warning"
            node.publish_ddata(target.device_id, {f"{sp_profile.EVENT_PREFIX}{code}": "Simulated vendor event"},
                               properties={f"{sp_profile.EVENT_PREFIX}{code}": {"level": level}})
            self.report(f"[{self.node_id}] event {code} on {target.device_id}")
        else:
            code = "A0007"
            props = {f"{sp_profile.ALARM_PREFIX}{code}": {"severity": "major", "message": "PCS over-temperature (simulated)"}}
            node.publish_ddata(target.device_id, {f"{sp_profile.ALARM_PREFIX}{code}": True}, properties=props)
            self.report(f"[{self.node_id}] alarm {code} raised on {target.device_id}")
            threading.Timer(random.uniform(45, 90), lambda: self.publish_alarm(
                target.device_id, code, "major", "PCS over-temperature (simulated)", False)).start()
