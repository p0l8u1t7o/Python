"""Thin, reconnect-safe wrapper over paho-mqtt v2.

Two behaviours matter operationally and are easy to get wrong, so they live
here rather than in every call site:

* **Reconnect with backoff.** paho's ``loop_forever`` reconnects on its own;
  we configure the delay bounds and re-subscribe from ``on_connect`` so a
  broker restart does not silently leave the client subscribed to nothing.
* **Clean-session choice.** Uplink consumers use a persistent session with a
  stable client id when shared subscriptions are off, so QoS 1 messages queue
  while the ingestor is down.
"""

from __future__ import annotations

import socket
import ssl
import threading
import uuid
from typing import Callable, Sequence

import paho.mqtt.client as mqtt
from django.conf import settings

from apps.core.logging import get_logger

logger = get_logger("mqtt.client")

MessageHandler = Callable[[str, bytes, int, bool], None]


class MqttClient:
    """Managed paho client.

    ``on_message_callback`` receives ``(topic, payload, qos, retain)``; keep it
    fast, it runs on the network thread.
    """

    def __init__(
        self,
        *,
        client_suffix: str,
        subscriptions: Sequence[tuple[str, int]] = (),
        on_message_callback: MessageHandler | None = None,
        on_connect_callback: Callable[[], None] | None = None,
        clean_session: bool = True,
        client_id: str | None = None,
    ) -> None:
        config = settings.MQTT
        self.config = config
        self.subscriptions = list(subscriptions)
        self.on_message_callback = on_message_callback
        #: Run after every successful CONNACK, including reconnects. Sparkplug
        #: needs this: the host's STATE birth has to be republished each time,
        #: or a broker restart leaves every edge node believing the primary
        #: application is still offline.
        self.on_connect_callback = on_connect_callback
        self.client_id = client_id or (
            f"{config['CLIENT_ID_PREFIX']}-{client_suffix}-{uuid.uuid4().hex[:8]}"
        )

        # MQTT 5 unless told otherwise. Under 3.1.1 the two differ in one way
        # that matters here: `clean_session` is a real flag again, where MQTT 5
        # replaced it with session expiry and paho rejects the argument.
        self._v5 = int(config.get("PROTOCOL_VERSION", 5)) != 311
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            protocol=mqtt.MQTTv5 if self._v5 else mqtt.MQTTv311,
            clean_session=None if self._v5 else clean_session,
        )
        self._connected = threading.Event()
        self._stopping = threading.Event()
        self._clean_session = clean_session
        self._configure()

    # ---- setup -----------------------------------------------------------
    def _configure(self) -> None:
        config = self.config
        if config["USERNAME"]:
            self._client.username_pw_set(config["USERNAME"], config["PASSWORD"] or None)

        if config["TLS_ENABLED"]:
            self._client.tls_set(
                ca_certs=config["TLS_CA_CERT"] or None,
                certfile=config["TLS_CERTFILE"] or None,
                keyfile=config["TLS_KEYFILE"] or None,
                cert_reqs=ssl.CERT_NONE if config["TLS_INSECURE"] else ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            if config["TLS_INSECURE"]:
                logger.warning("MQTT TLS certificate verification is DISABLED")
                self._client.tls_insecure_set(True)

        self._client.reconnect_delay_set(
            min_delay=config["RECONNECT_MIN_DELAY"],
            max_delay=config["RECONNECT_MAX_DELAY"],
        )
        # Buffer downlink publishes across a short broker outage.
        self._client.max_queued_messages_set(10_000)
        self._client.max_inflight_messages_set(100)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_subscribe = self._on_subscribe

    # ---- callbacks -------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.error("MQTT connect refused", extra={"reason": str(reason_code)})
            return
        self._connected.set()
        logger.info(
            "MQTT connected",
            extra={"client_id": self.client_id, "session_present": bool(flags.session_present)},
        )
        # Always re-subscribe: a broker restart drops server-side state even
        # when the client believes the session persisted.
        if self.subscriptions:
            client.subscribe(self.subscriptions)
        if self.on_connect_callback is not None:
            try:
                self.on_connect_callback()
            except Exception:  # noqa: BLE001 - never break the network thread
                logger.exception("on_connect callback failed")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._connected.clear()
        if self._stopping.is_set():
            return
        logger.warning("MQTT disconnected, will retry", extra={"reason": str(reason_code)})

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties=None):
        failures = [str(rc) for rc in reason_codes if getattr(rc, "is_failure", False)]
        if failures:
            logger.error("MQTT subscription rejected", extra={"reasons": failures})
        else:
            logger.info(
                "MQTT subscriptions active",
                extra={"filters": [f for f, _ in self.subscriptions]},
            )

    def _on_message(self, client, userdata, message: mqtt.MQTTMessage):
        if self.on_message_callback is None:
            return
        try:
            self.on_message_callback(
                message.topic, message.payload, message.qos, message.retain
            )
        except Exception:  # noqa: BLE001 - a bad message must not kill the loop
            logger.exception("unhandled error in MQTT message handler")

    # ---- lifecycle -------------------------------------------------------
    def set_last_will(self, topic: str, payload: bytes, qos: int = 1, retain: bool = True):
        self._client.will_set(topic, payload, qos=qos, retain=retain)

    def connect(self, *, timeout: float = 10.0) -> None:
        config = self.config
        # clean_start and CONNECT properties are MQTT 5 only; paho refuses
        # both under 3.1.1, where the equivalent was already set as
        # clean_session at construction.
        extra: dict = {}
        if self._v5:
            properties = None
            if not self._clean_session:
                from paho.mqtt.properties import Properties
                from paho.mqtt.packettypes import PacketTypes

                properties = Properties(PacketTypes.CONNECT)
                properties.SessionExpiryInterval = 86400  # keep queued QoS1 a day
            extra = {"clean_start": self._clean_session, "properties": properties}

        try:
            self._client.connect(
                config["HOST"],
                config["PORT"],
                keepalive=config["KEEPALIVE"],
                **extra,
            )
        except (socket.error, OSError) as exc:
            raise ConnectionError(
                f"Cannot reach MQTT broker at {config['HOST']}:{config['PORT']}: {exc}"
            ) from exc
        self._client.loop_start()
        if not self._connected.wait(timeout=timeout):
            logger.warning("MQTT connect not confirmed within %.1fs; continuing", timeout)

    def loop_forever(self) -> None:
        """Blocking run loop with automatic reconnect (for the ingestor)."""
        config = self.config
        self._client.connect_async(
            config["HOST"], config["PORT"], keepalive=config["KEEPALIVE"]
        )
        self._client.loop_forever(retry_first_connection=True)

    def disconnect(self) -> None:
        self._stopping.set()
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    # ---- publishing ------------------------------------------------------
    def publish(
        self,
        topic: str,
        payload: bytes | str,
        *,
        qos: int | None = None,
        retain: bool = False,
        timeout: float = 5.0,
    ) -> bool:
        """Publish and wait for broker confirmation. Returns success."""
        info = self._client.publish(
            topic,
            payload,
            qos=self.config["QOS_DOWNLINK"] if qos is None else qos,
            retain=retain,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.error(
                "MQTT publish failed",
                extra={"topic": topic, "rc": mqtt.error_string(info.rc)},
            )
            return False
        if qos == 0:
            return True
        try:
            info.wait_for_publish(timeout=timeout)
        except (ValueError, RuntimeError) as exc:
            logger.error("MQTT publish not confirmed", extra={"topic": topic, "error": str(exc)})
            return False
        return info.is_published()

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set() and self._client.is_connected()
