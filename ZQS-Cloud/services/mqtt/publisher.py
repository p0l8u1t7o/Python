"""Downlink publisher shared by the API process.

One long-lived MQTT connection per web worker, created lazily so that a broker
outage degrades command dispatch instead of breaking process start-up.
"""

from __future__ import annotations

import threading
from typing import Any

import orjson

from apps.core.logging import get_logger
from services.mqtt.client import MqttClient

logger = get_logger("mqtt.publisher")

_client: MqttClient | None = None
_lock = threading.Lock()


class PublishError(RuntimeError):
    """Raised when a downlink message could not be handed to the broker."""


class BrokerDisabled(PublishError):
    """Raised when this deployment is configured without a broker.

    A distinct type so callers can tell "the broker is down" from "there is no
    broker here on purpose" - the first is an incident, the second is a
    configuration the operator chose.
    """


def get_publisher() -> MqttClient:
    from django.conf import settings

    if not settings.MQTT.get("ENABLED", True):
        raise BrokerDisabled(
            "MQTT is disabled for this deployment (MQTT_ENABLED=0)"
        )

    global _client
    if _client is None or not _client.is_connected:
        with _lock:
            if _client is None:
                _client = MqttClient(client_suffix="api", clean_session=True)
                _client.connect()
            elif not _client.is_connected:
                # paho reconnects on its own; surface the state for the caller.
                logger.warning("MQTT publisher is currently disconnected")
    return _client


def publish_bytes(
    topic: str, body: bytes, *, qos: int | None = None, retain: bool = False
) -> None:
    """Publish an already-encoded payload, raising :class:`PublishError`.

    Sparkplug payloads are protobuf, so the encoding decision belongs to the
    caller that built the message - this layer only owns the connection.
    """
    try:
        client = get_publisher()
    except BrokerDisabled:
        raise
    except ConnectionError as exc:
        raise PublishError(str(exc)) from exc

    if not client.publish(topic, body, qos=qos, retain=retain):
        raise PublishError(f"Broker did not confirm publish to {topic}")
    logger.info("downlink published", extra={"topic": topic, "bytes": len(body)})


def publish_json(
    topic: str, payload: dict[str, Any], *, qos: int | None = None, retain: bool = False
) -> None:
    """Publish a JSON payload.

    Retained for the host STATE topic, which the Sparkplug specification
    defines as a UTF-8 JSON document rather than a protobuf payload - the one
    place in the namespace where that is true.
    """
    publish_bytes(topic, orjson.dumps(payload), qos=qos, retain=retain)


def shutdown() -> None:
    global _client
    with _lock:
        if _client is not None:
            _client.disconnect()
            _client = None
