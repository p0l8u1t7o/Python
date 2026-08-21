"""A reference device that behaves correctly, on purpose.

Its job is to be the **known-good control**. When the LabVIEW client fails a
check there are always two candidate explanations - the client is wrong, or the
harness is wrong - and without a reference you cannot tell them apart. Run this
first: if it passes every check, the harness is behaving, and any later failure
is the device under test.

It is also the shortest readable statement of what a conforming client does, so
it doubles as an implementation reference for the LabVIEW side. Every step below
maps to a checklist item.

Uses paho-mqtt, which the project already depends on, so it exercises a real
MQTT client stack rather than the harness's own encoder.
"""

from __future__ import annotations

import math
import random
import threading
import time

import orjson
import paho.mqtt.client as mqtt

from apps.core.logging import get_logger
from apps.core.timeutils import now
from services.mqtt import topics

logger = get_logger("harness.simulator")


class ReferenceDevice:
    """A minimal, correct device client.

    Deliberately small. Everything here is required by the protocol; nothing
    here is decoration.
    """

    def __init__(
        self,
        *,
        device_id: str,
        username: str,
        password: str,
        host: str = "127.0.0.1",
        port: int = 1883,
        interval: float = 5.0,
        keepalive: int = 45,
        misbehave: str = "",
    ) -> None:
        self.device_id = device_id
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
        self._client = self._build_client()
        self._soc = 62.0

    # ---- setup -----------------------------------------------------------
    def _build_client(self) -> mqtt.Client:
        client_id = (
            "LabVIEW_1" if self.misbehave == "bad_client_id" else f"zqs:{self.device_id}"
        )
        clean_session = self.misbehave == "clean_session"

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=clean_session,
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(self.username, self.password)

        # The last will, declared at connect time - not after. A will set later
        # would never be delivered, because the broker only learns about it in
        # the CONNECT packet.
        if self.misbehave != "no_lwt":
            client.will_set(
                topics.device_topic(self.device_id, topics.STATUS),
                orjson.dumps({"status": "offline", "reason": "lwt"}),
                qos=1,
                retain=True,
            )

        client.on_connect = self._on_connect
        client.on_message = self._on_message
        return client

    # ---- callbacks -------------------------------------------------------
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None):
        if getattr(reason_code, "is_failure", False) or reason_code != 0:
            logger.error("連線被拒", extra={"reason": str(reason_code)})
            return

        # Subscribe before announcing: a command that arrives in the gap would
        # otherwise be missed.
        client.subscribe(topics.control_topic(self.device_id), qos=1)

        # The birth message. Retained, so a console connecting later still sees
        # the current state.
        client.publish(
            topics.device_topic(self.device_id, topics.STATUS),
            orjson.dumps(
                {
                    "status": "online",
                    "ts": _epoch_ms(),
                    "reason": "boot",
                    "firmware": "sim-1.0.0",
                    "hardware": "reference-simulator",
                }
            ),
            qos=1,
            retain=True,
        )
        logger.info("已連線並發布上線訊息", extra={"device_id": self.device_id})

    def _on_message(self, client, _userdata, message):
        """Answer a downlink command, echoing the command_id verbatim."""
        try:
            command = orjson.loads(message.payload)
        except orjson.JSONDecodeError:
            logger.warning("收到無法解析的命令")
            return

        logger.info("收到命令", extra={"name": command.get("name")})
        if self.misbehave == "no_ack":
            return

        client.publish(
            topics.device_topic(self.device_id, topics.CONTROL_ACK),
            orjson.dumps(
                {
                    "command_id": command.get("command_id"),
                    "status": "succeeded",
                    "ts": _epoch_ms(),
                    "message": "",
                    "result": {"applied": command.get("params", {})},
                }
            ),
            qos=1,
        )

    # ---- telemetry -------------------------------------------------------
    def _publish_telemetry(self) -> None:
        # A plausible battery: charging at night, discharging in the afternoon.
        minute_of_day = now().hour * 60 + now().minute
        power_w = -40_000 * math.sin(minute_of_day / 1440 * 2 * math.pi)
        self._soc = max(10.0, min(95.0, self._soc - power_w / 400_000))

        payload = {
            "ts": _epoch_ms(),
            "metrics": {
                "battery_soc": round(self._soc, 2),
                "battery_power_w": round(power_w, 1),
                "battery_temperature_c": round(28 + random.uniform(-1.5, 1.5), 2),
                "pcs_state": "charge" if power_w < 0 else "discharge",
            },
        }
        if self.misbehave == "bad_payload":
            # Missing the mandatory ts - exactly the kind of thing the harness
            # must catch, so this is how you prove that it does.
            payload.pop("ts")

        self._client.publish(
            topics.device_topic(self.device_id, topics.TELEMETRY),
            orjson.dumps(payload),
            qos=0 if self.misbehave == "bad_qos" else 1,
        )

    # ---- lifecycle -------------------------------------------------------
    def run(self, *, duration: float | None = None, abrupt_exit: bool = False) -> None:
        """Connect and publish until stopped.

        ``abrupt_exit`` kills the socket without DISCONNECT, which is how you
        make the broker deliver the will. A polite disconnect deliberately does
        not trigger it - that is the MQTT specification, not a harness quirk.
        """
        self._client.connect(self.host, self.port, keepalive=self.keepalive)
        self._client.loop_start()

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
                self._client.publish(
                    topics.device_topic(self.device_id, topics.STATUS),
                    orjson.dumps({"status": "offline", "ts": _epoch_ms(), "reason": "shutdown"}),
                    qos=1,
                    retain=True,
                )
                time.sleep(0.2)
                self._client.disconnect()
                self._client.loop_stop()

    def stop(self) -> None:
        self._stopping.set()


def _epoch_ms() -> int:
    return int(now().timestamp() * 1000)
