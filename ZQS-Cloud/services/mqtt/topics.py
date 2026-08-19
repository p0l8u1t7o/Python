"""MQTT topic grammar.

All device traffic lives under a configurable root (default ``energy/devices``)::

    energy/devices/{device_id}/telemetry      uplink   measurements
    energy/devices/{device_id}/status         uplink   online/offline + LWT
    energy/devices/{device_id}/event          uplink   operation log entries
    energy/devices/{device_id}/alarm          uplink   device-raised alarms
    energy/devices/{device_id}/control/ack    uplink   command acknowledgement
    energy/devices/{device_id}/control        downlink commands

Keeping the grammar in one module means the ingestor's subscriptions, the API's
publishes and the EMQX ACL rules can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

TELEMETRY = "telemetry"
STATUS = "status"
EVENT = "event"
ALARM = "alarm"
CONTROL = "control"
CONTROL_ACK = "control/ack"

#: Uplink suffixes the ingestor subscribes to.
UPLINK_SUFFIXES = (TELEMETRY, STATUS, EVENT, ALARM, CONTROL_ACK)


def root() -> str:
    return settings.MQTT["TOPIC_ROOT"].strip("/")


def device_topic(device_id: str, suffix: str) -> str:
    return f"{root()}/{device_id}/{suffix.strip('/')}"


def control_topic(device_id: str) -> str:
    return device_topic(device_id, CONTROL)


def subscription(suffix: str, *, shared: bool | None = None) -> str:
    """Build one subscription filter, optionally as an EMQX shared subscription.

    Shared subscriptions (``$share/<group>/<filter>``) let several ingestor
    replicas load-balance a topic instead of each receiving every message.
    """
    filter_ = f"{root()}/+/{suffix.strip('/')}"
    use_shared = settings.MQTT["USE_SHARED_SUBSCRIPTION"] if shared is None else shared
    if use_shared:
        group = settings.MQTT["SHARED_SUBSCRIPTION_GROUP"]
        return f"$share/{group}/{filter_}"
    return filter_


def uplink_subscriptions(*, shared: bool | None = None) -> list[tuple[str, int]]:
    qos = settings.MQTT["QOS_UPLINK"]
    return [(subscription(suffix, shared=shared), qos) for suffix in UPLINK_SUFFIXES]


@dataclass(slots=True)
class ParsedTopic:
    device_id: str
    kind: str


def parse(topic: str) -> ParsedTopic | None:
    """Extract ``(device_id, kind)`` from an uplink topic.

    Returns ``None`` for anything outside the grammar, so unexpected traffic is
    ignored rather than crashing the ingest loop.
    """
    prefix = root()
    if not topic.startswith(prefix + "/"):
        return None

    remainder = topic[len(prefix) + 1 :]
    parts = remainder.split("/")
    if len(parts) < 2:
        return None

    device_id = parts[0]
    if not device_id or device_id in {"+", "#"}:
        return None

    kind = "/".join(parts[1:])
    if kind not in UPLINK_SUFFIXES:
        return None
    return ParsedTopic(device_id=device_id, kind=kind)


def device_id_from_client_id(client_id: str) -> str:
    """EMQX ACL helper: client ids are expected to be ``<prefix>:<device_id>``."""
    _, _, tail = client_id.rpartition(":")
    return tail or client_id
