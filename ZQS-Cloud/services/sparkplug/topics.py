"""Sparkplug B topic grammar.

::

    spBv1.0/{group_id}/{message_type}/{edge_node_id}            node level
    spBv1.0/{group_id}/{message_type}/{edge_node_id}/{device_id} device level
    spBv1.0/STATE/{host_id}                                      host state

``group_id`` is the organisation slug, so one broker can carry several tenants
and the ACL can confine each credential to its own group.

Keeping the grammar in one module means the ingestor's subscriptions, the API's
publishes and the EMQX ACL rules cannot disagree with each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings

NAMESPACE = "spBv1.0"

#: The spec reserves these for the topic structure itself.
FORBIDDEN_IN_ID = ("+", "#", "/")


class MessageType(StrEnum):
    NBIRTH = "NBIRTH"
    NDEATH = "NDEATH"
    NDATA = "NDATA"
    NCMD = "NCMD"
    DBIRTH = "DBIRTH"
    DDEATH = "DDEATH"
    DDATA = "DDATA"
    DCMD = "DCMD"
    STATE = "STATE"


#: Message types that carry a device id as a fifth topic level.
DEVICE_LEVEL = frozenset(
    {MessageType.DBIRTH, MessageType.DDEATH, MessageType.DDATA, MessageType.DCMD}
)

#: What an edge node publishes. The host subscribes to exactly these, rather
#: than to a wildcard message type, so it never consumes its own NCMD/DCMD.
UPLINK_TYPES = (
    MessageType.NBIRTH,
    MessageType.NDEATH,
    MessageType.NDATA,
    MessageType.DBIRTH,
    MessageType.DDEATH,
    MessageType.DDATA,
)

#: Types that announce metric names and aliases; everything after one of these
#: may legally use aliases alone.
BIRTH_TYPES = frozenset({MessageType.NBIRTH, MessageType.DBIRTH})
DEATH_TYPES = frozenset({MessageType.NDEATH, MessageType.DDEATH})
DATA_TYPES = frozenset({MessageType.NDATA, MessageType.DDATA})


class TopicError(ValueError):
    """Topic outside the Sparkplug grammar."""


def valid_id(value: str) -> bool:
    return bool(value) and not any(char in value for char in FORBIDDEN_IN_ID)


def _check(value: str, label: str) -> str:
    if not valid_id(value):
        raise TopicError(f"{label} '{value}' contains a reserved character or is empty")
    return value


def host_id() -> str:
    return settings.SPARKPLUG["HOST_ID"]


def build(
    group_id: str,
    message_type: MessageType,
    edge_node_id: str,
    device_id: str = "",
) -> str:
    """Assemble one topic, validating every id against the reserved set."""
    _check(group_id, "group_id")
    _check(edge_node_id, "edge_node_id")
    parts = [NAMESPACE, group_id, str(message_type), edge_node_id]
    if device_id:
        _check(device_id, "device_id")
        parts.append(device_id)
    return "/".join(parts)


def state_topic(host: str = "") -> str:
    """The primary host application's own birth/death topic."""
    return f"{NAMESPACE}/{MessageType.STATE}/{_check(host or host_id(), 'host_id')}"


def node_command(group_id: str, edge_node_id: str) -> str:
    return build(group_id, MessageType.NCMD, edge_node_id)


def device_command(group_id: str, edge_node_id: str, device_id: str) -> str:
    return build(group_id, MessageType.DCMD, edge_node_id, device_id)


@dataclass(frozen=True, slots=True)
class ParsedTopic:
    group_id: str
    message_type: MessageType
    edge_node_id: str
    device_id: str = ""

    @property
    def is_device_level(self) -> bool:
        return bool(self.device_id)


def parse(topic: str) -> ParsedTopic | None:
    """Split an uplink topic, or return ``None`` for anything off-grammar.

    Returning ``None`` rather than raising keeps unexpected broker traffic -
    another tenant's tooling, a mistyped manual publish - from stopping the
    ingest loop.
    """
    parts = topic.split("/")
    if len(parts) not in (4, 5) or parts[0] != NAMESPACE:
        return None

    group_id, raw_type, edge_node_id = parts[1], parts[2], parts[3]
    device_id = parts[4] if len(parts) == 5 else ""

    try:
        message_type = MessageType(raw_type)
    except ValueError:
        return None

    # A device id where the message type does not allow one (or the reverse) is
    # not a topic we can interpret, so treat it as foreign traffic.
    if (message_type in DEVICE_LEVEL) != bool(device_id):
        return None
    if not valid_id(group_id) or not valid_id(edge_node_id):
        return None

    return ParsedTopic(
        group_id=group_id,
        message_type=message_type,
        edge_node_id=edge_node_id,
        device_id=device_id,
    )


def parse_subscription(filter_: str) -> ParsedTopic | None:
    """Parse a *subscription filter*, which may end in a wildcard.

    A node subscribes to its commands with something like
    ``spBv1.0/acme/DCMD/GW-01/#`` - a perfectly ordinary filter that
    :func:`parse` refuses, because a wildcard is not a legal device id.

    The wildcard is tolerated only at the device level. Allowing it any higher
    would let one node subscribe to ``spBv1.0/acme/DCMD/+/#`` and receive every
    command meant for its neighbours.
    """
    parts = filter_.split("/")
    if len(parts) not in (4, 5) or parts[0] != NAMESPACE:
        return None

    group_id, raw_type, edge_node_id = parts[1], parts[2], parts[3]
    if not valid_id(group_id) or not valid_id(edge_node_id):
        return None

    try:
        message_type = MessageType(raw_type)
    except ValueError:
        return None

    device_id = parts[4] if len(parts) == 5 else ""
    if device_id in ("+", "#"):
        # Any device on this node, which is the node's own subtree.
        device_id = "*"
    elif device_id and not valid_id(device_id):
        return None
    elif (message_type in DEVICE_LEVEL) != bool(device_id):
        return None

    return ParsedTopic(
        group_id=group_id,
        message_type=message_type,
        edge_node_id=edge_node_id,
        device_id=device_id,
    )


def subscription(message_type: MessageType, *, shared: bool | None = None) -> str:
    """One subscription filter, optionally as an EMQX shared subscription.

    Shared subscriptions (``$share/<group>/<filter>``) let several ingestor
    replicas load-balance a topic instead of each receiving every message.
    """
    levels = 5 if message_type in DEVICE_LEVEL else 4
    filter_ = "/".join([NAMESPACE, "+", str(message_type), *["+"] * (levels - 3)])
    use_shared = settings.MQTT["USE_SHARED_SUBSCRIPTION"] if shared is None else shared
    if use_shared:
        return f"$share/{settings.MQTT['SHARED_SUBSCRIPTION_GROUP']}/{filter_}"
    return filter_


def uplink_subscriptions(*, shared: bool | None = None) -> list[tuple[str, int]]:
    qos = settings.MQTT["QOS_UPLINK"]
    return [(subscription(t, shared=shared), qos) for t in UPLINK_TYPES]


def edge_node_id_from_client_id(client_id: str) -> str:
    """EMQX ACL helper: client ids are expected to be ``<prefix>:<edge_node_id>``."""
    _, _, tail = client_id.rpartition(":")
    return tail or client_id


#: Publish QoS and retain flag, fixed by the specification rather than by this
#: deployment's preferences. Two of these look surprising and are not:
#:
#: * everything is QoS 0, because Sparkplug's ordering guarantee comes from the
#:   ``seq`` counter and a missed message is recovered by asking for a rebirth,
#:   not by the broker retrying. QoS 1 would buy duplicates, not safety.
#: * NDEATH is QoS 1 because it is the Will, and a will the broker drops leaves
#:   a dead node showing as online until the timeout sweep notices.
#: * STATE is the only retained topic, so a host that reconnects learns at once
#:   whether the primary application is up.
_QOS_RETAIN: dict[MessageType, tuple[int, bool]] = {
    MessageType.NBIRTH: (0, False),
    MessageType.NDEATH: (1, False),
    MessageType.NDATA: (0, False),
    MessageType.NCMD: (0, False),
    MessageType.DBIRTH: (0, False),
    MessageType.DDEATH: (0, False),
    MessageType.DDATA: (0, False),
    MessageType.DCMD: (0, False),
    MessageType.STATE: (1, True),
}


def publish_options(message_type: MessageType) -> tuple[int, bool]:
    """``(qos, retain)`` the specification mandates for this message type."""
    return _QOS_RETAIN[message_type]
