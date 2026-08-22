"""A reference edge node that behaves correctly, on purpose.

Its job is to be the **known-good control**. When the device under test fails a
check there are always two candidate explanations - the client is wrong, or the
harness is wrong - and without a reference you cannot tell them apart. Run this
first: if it passes every check, the harness is behaving, and any later failure
is the device under test.

It is also the shortest readable statement of what a conforming Sparkplug edge
node does, so it doubles as an implementation reference. Every step below maps
to a checklist item.

Uses paho-mqtt, which the project already depends on, so it exercises a real
MQTT client stack rather than the harness's own encoder.
"""

from __future__ import annotations

import math
import random
import threading
import time

import paho.mqtt.client as mqtt

from apps.core.logging import get_logger
from apps.core.timeutils import now
from services.sparkplug import payload as sp
from services.sparkplug import profile as sp_profile
from services.sparkplug import topics
from services.sparkplug.datatypes import DataType
from services.sparkplug.node import EdgeNodeClient, MetricSpec
from services.sparkplug.topics import MessageType

logger = get_logger("harness.simulator")

#: Everything this reference device offers, which is exactly what its DBIRTH
#: must list - a birth is defined as the complete set, not a sample of it.
BIRTH_METRICS = [
    MetricSpec("Properties/Firmware", "sim-2.0.0", DataType.String),
    MetricSpec("Properties/Hardware", "reference-simulator", DataType.String),
    MetricSpec("Properties/Category", "battery", DataType.String),
    MetricSpec("Properties/Manufacturer", "ZQS", DataType.String),
    MetricSpec("Properties/Model", "REF-BESS", DataType.String),
    MetricSpec("Capabilities/Can Charge", True, DataType.Boolean),
    MetricSpec("Capabilities/Can Discharge", True, DataType.Boolean),
    MetricSpec("Ratings/Rated Power kW", 400.0, DataType.Double),
    # Units travel with the reading, which is what lets a platform build its
    # catalogue from the birth alone.
    MetricSpec("battery_soc", 62.0, DataType.Double, {"unit": "%"}),
    MetricSpec("battery_power_w", 0.0, DataType.Double, {"unit": "W"}),
    MetricSpec("battery_temperature_c", 28.0, DataType.Double, {"unit": "degC"}),
    MetricSpec("pcs_state", "idle", DataType.String),
]


class _PahoAdapter:
    """Gives paho the ``publish(topic, body, qos, retain) -> bool`` shape.

    :class:`~services.sparkplug.node.EdgeNodeClient` is written against the
    platform's own MQTT wrapper. Adapting here keeps the reference device on
    the same sequencing and aliasing code the simulator and the docs describe -
    a second implementation would be a second place for the seq counter to be
    wrong.
    """

    def __init__(self, client: mqtt.Client, force_qos: int | None = None) -> None:
        self._client = client
        #: Override the QoS the specification mandates, to prove the harness
        #: notices. Everything else about the message stays correct, so the
        #: fault under test is the only thing that can fail.
        self._force_qos = force_qos

    def publish(self, topic: str, payload: bytes, *, qos: int = 0, retain: bool = False) -> bool:
        info = self._client.publish(
            topic,
            payload,
            qos=self._force_qos if self._force_qos is not None else qos,
            retain=retain,
        )
        return info.rc == mqtt.MQTT_ERR_SUCCESS


class ReferenceDevice:
    """A minimal, correct edge node client.

    Deliberately small. Everything here is required by the specification;
    nothing here is decoration.
    """

    def __init__(
        self,
        *,
        device_id: str,
        username: str,
        password: str,
        group_id: str = "",
        node_id: str = "",
        host: str = "127.0.0.1",
        port: int = 1883,
        interval: float = 5.0,
        keepalive: int = 45,
        misbehave: str = "",
    ) -> None:
        self.device_id = device_id
        self.node_id = node_id or device_id
        self.group_id = group_id
        self.username = username
        self.password = password
        self.host = host
        self.port = port
        self.interval = interval
        self.keepalive = keepalive
        #: Name of a deliberate fault, for checking that the harness *catches*
        #: things. A test tool that never fails anything proves nothing.
        self.misbehave = misbehave

        self._stopping = threading.Event()
        #: Set once NBIRTH and DBIRTH are out. The run loop waits on it,
        #: because paho delivers CONNACK on its own thread: without the wait,
        #: the first DDATA races the birth onto the wire and the host sees a
        #: reading for a device that has not been announced - and a seq that
        #: goes 0, 0, 1.
        self._born = threading.Event()
        self._client = self._build_client()
        self._node = EdgeNodeClient(
            _PahoAdapter(self._client, force_qos=1 if misbehave == "bad_qos" else None),
            self.group_id,
            self.node_id,
        )
        self._node.next_bd_seq()
        self._soc = 62.0
        self._apply_will()

    # ---- setup -----------------------------------------------------------
    def _build_client(self) -> mqtt.Client:
        client_id = (
            "LabVIEW_1" if self.misbehave == "bad_client_id" else f"zqs:{self.node_id}"
        )
        # Sparkplug requires a clean session, so the fault worth simulating
        # is a client that keeps one.
        clean_session = self.misbehave != "clean_session"

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=clean_session,
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(self.username, self.password)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        return client

    def _apply_will(self) -> None:
        """Register NDEATH as the will, at connect time - not after.

        A will set later would never be delivered, because the broker only
        learns about it in the CONNECT packet.
        """
        if self.misbehave == "no_lwt":
            return
        qos, retain = topics.publish_options(MessageType.NDEATH)
        self._client.will_set(
            topics.build(self.group_id, MessageType.NDEATH, self.node_id),
            self._node.death_payload(),
            qos=qos,
            # A retained NDEATH would outlive the session it describes.
            retain=True if self.misbehave == "retained_will" else retain,
        )

    # ---- callbacks -------------------------------------------------------
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None):
        if getattr(reason_code, "is_failure", False) or reason_code != 0:
            logger.error("連線被拒", extra={"reason": str(reason_code)})
            return

        # Subscribe before announcing: a command that arrives in the gap would
        # otherwise be missed.
        for topic, qos in self._node.command_subscriptions():
            client.subscribe(topic, qos=qos)

        self._announce()
        logger.info("已連線並發布 BIRTH", extra={"node": self.node_id})

    def _announce(self) -> None:
        self._node.publish_nbirth()
        self._node.publish_dbirth(self.device_id, BIRTH_METRICS)
        self._born.set()

    def _on_message(self, client, _userdata, message):
        """Answer a downlink command, echoing the Command/ID verbatim."""
        try:
            view = sp.decode(message.payload)
        except sp.PayloadError:
            logger.warning("收到無法解析的命令")
            return

        names = {metric.name: metric.value for metric in view.metrics}

        # Honouring a rebirth is not optional: it is the only way the host can
        # recover after a lost message, and a node that ignores it will be
        # asked again forever.
        if names.get(sp.NODE_REBIRTH_METRIC) or names.get(sp.DEVICE_REBIRTH_METRIC):
            if self.misbehave != "ignore_rebirth":
                self._announce()
            return

        command_id = names.get(sp_profile.COMMAND_ID)
        if not command_id:
            return

        # Not 'name': logging reserves it on LogRecord, and passing it via
        # extra raises inside the paho callback thread - which swallows the
        # ack and leaves the command hanging.
        logger.info("收到命令", extra={"command": names.get(sp_profile.COMMAND_NAME)})
        if self.misbehave == "no_ack":
            return

        self._node.ack(
            self.device_id,
            str(command_id),
            "succeeded",
            result={
                key[len(sp_profile.COMMAND_PREFIX) :]: value
                for key, value in names.items()
                if key.startswith(sp_profile.COMMAND_PREFIX)
                and key
                not in (
                    sp_profile.COMMAND_ID,
                    sp_profile.COMMAND_NAME,
                    sp_profile.COMMAND_EXPIRES,
                )
            },
        )

    # ---- telemetry -------------------------------------------------------
    def _publish_telemetry(self) -> None:
        # A plausible battery: charging at night, discharging in the afternoon.
        minute_of_day = now().hour * 60 + now().minute
        power_w = -40_000 * math.sin(minute_of_day / 1440 * 2 * math.pi)
        self._soc = max(10.0, min(95.0, self._soc - power_w / 400_000))

        values = {
            "battery_soc": round(self._soc, 2),
            "battery_power_w": round(power_w, 1),
            "battery_temperature_c": round(28 + random.uniform(-1.5, 1.5), 2),
            "pcs_state": "charge" if power_w < 0 else "discharge",
        }

        if self.misbehave == "bad_payload":
            # Not a Sparkplug payload at all - exactly the kind of thing the
            # harness must catch, so this is how you prove that it does.
            self._client.publish(
                topics.build(
                    self.group_id, MessageType.DDATA, self.node_id, self.device_id
                ),
                b"{not protobuf}",
                qos=0,
            )
            return

        self._node.publish_ddata(self.device_id, values)

    # ---- lifecycle -------------------------------------------------------
    def run(self, *, duration: float | None = None, abrupt_exit: bool = False) -> None:
        """Connect and publish until stopped.

        ``abrupt_exit`` kills the socket without DISCONNECT, which is how you
        make the broker deliver the will. A polite disconnect deliberately does
        not trigger it - that is the MQTT specification, not a harness quirk,
        and it is why the tidy path below publishes NDEATH itself.
        """
        self._client.connect(self.host, self.port, keepalive=self.keepalive)
        self._client.loop_start()

        # Publishing before the birth is out would violate the specification
        # and, more practically, produce a sequence gap on the very first
        # message. Five seconds is long enough for a local CONNACK and short
        # enough that a refused connection still ends the run.
        self._born.wait(timeout=5.0)

        started = time.monotonic()
        try:
            while not self._stopping.is_set():
                self._publish_telemetry()
                if duration is not None and time.monotonic() - started >= duration:
                    break
                self._stopping.wait(self.interval)
        finally:
            if abrupt_exit:
                # Drop the TCP connection without a DISCONNECT packet.
                self._client.loop_stop()
                try:
                    self._client.socket().close()
                except Exception:  # noqa: BLE001 - already gone is fine
                    pass
            else:
                self._node.publish_ddeath(self.device_id)
                self._node.publish_ndeath()
                time.sleep(0.2)
                self._client.disconnect()
                self._client.loop_stop()

    def stop(self) -> None:
        self._stopping.set()
