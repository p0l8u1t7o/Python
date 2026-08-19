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


def get_publisher() -> MqttClient:
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


def publish_json(
    topic: str, payload: dict[str, Any], *, qos: int | None = None, retain: bool = False
) -> None:
    """Publish a JSON payload, raising :class:`PublishError` on failure."""
    try:
        client = get_publisher()
    except ConnectionError as exc:
        raise PublishError(str(exc)) from exc

    body = orjson.dumps(payload)
    if not client.publish(topic, body, qos=qos, retain=retain):
        raise PublishError(f"Broker did not confirm publish to {topic}")
    logger.info("downlink published", extra={"topic": topic, "bytes": len(body)})


def shutdown() -> None:
    global _client
    with _lock:
        if _client is not None:
            _client.disconnect()
            _client = None
