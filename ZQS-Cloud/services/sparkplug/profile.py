"""The ZQS metric profile: what Sparkplug metric names mean to this platform.

Sparkplug fixes the topic namespace, the payload encoding and the birth/death
state machine. It deliberately says nothing about what a metric is *called* -
that is left to the application, and this module is that decision written down
in one place.

Four namespaces carry meaning; everything else is a measurement and goes to the
time series:

===================== ==========================================================
``Properties/*``      identity and metadata (firmware, model, position)
``Capabilities/*``    what the equipment claims it can do
``Ratings/*``         nameplate limits
``Alarm/<code>``      a fault, boolean: true raises it, false clears it
``Event/<code>``      an operation-log line, string
``Command/*``         correlation for a command this platform issued
``Node Control/*``    writable node controls defined by the specification
``Device Control/*``  writable device controls
===================== ==========================================================

The first three are exactly the ``attributes`` object the JSON protocol used to
carry on the birth message. Under Sparkplug they are simply metrics in the
BIRTH, which is a better fit: a BIRTH is *defined* as the full set of metrics a
device offers, so the declaration stops being a bolted-on extra field.
"""

from __future__ import annotations

import re
from typing import Any

from services.sparkplug.datatypes import NUMERIC_TYPES, TEXT_TYPES, DataType
from services.sparkplug.payload import MetricView

#: Version of *this mapping*, not of anything the device invents. Under
#: Sparkplug the metric names are the schema, and the names are defined here, so
#: the version belongs here too. Devices may state a version in
#: ``Properties/Schema Version``; absent means "the current one".
PROFILE_VERSION = 1

PROPERTIES_PREFIX = "Properties/"
CAPABILITIES_PREFIX = "Capabilities/"
RATINGS_PREFIX = "Ratings/"
ALARM_PREFIX = "Alarm/"
EVENT_PREFIX = "Event/"
COMMAND_PREFIX = "Command/"
NODE_CONTROL_PREFIX = "Node Control/"
DEVICE_CONTROL_PREFIX = "Device Control/"

#: Prefixes that are never a measurement.
RESERVED_PREFIXES = (
    PROPERTIES_PREFIX,
    CAPABILITIES_PREFIX,
    RATINGS_PREFIX,
    ALARM_PREFIX,
    EVENT_PREFIX,
    COMMAND_PREFIX,
    NODE_CONTROL_PREFIX,
    DEVICE_CONTROL_PREFIX,
)

#: Metric names reserved by the specification itself.
RESERVED_NAMES = frozenset({"bdSeq"})

COMMAND_ID = "Command/ID"
COMMAND_NAME = "Command/Name"
COMMAND_STATUS = "Command/Status"
COMMAND_MESSAGE = "Command/Message"
COMMAND_EXPIRES = "Command/Expires"
COMMAND_RESULT_PREFIX = "Command/Result/"

MAX_METRIC_KEY_LENGTH = 64

_SEPARATORS = re.compile(r"[\s/\-.]+")
_INVALID = re.compile(r"[^a-z0-9_]+")
_COLLAPSE = re.compile(r"_{2,}")


def metric_key(name: str) -> str:
    """Normalise a Sparkplug metric name to this platform's catalogue key.

    ``Battery/SOC``, ``battery_soc`` and ``Battery SOC`` all mean the same
    reading and must land in the same series, otherwise a firmware author's
    choice of capitalisation silently forks the history of a meter.
    """
    key = _SEPARATORS.sub("_", (name or "").strip().lower())
    key = _INVALID.sub("", key)
    key = _COLLAPSE.sub("_", key).strip("_")
    return key


def is_reserved(name: str) -> bool:
    return name in RESERVED_NAMES or name.startswith(RESERVED_PREFIXES)


def _leaf(name: str, prefix: str) -> str:
    return name[len(prefix) :]


# ------------------------------------------------------------ declaration --
#: ``Properties/`` leaves that describe identity rather than runtime state.
_IDENTITY_KEYS = frozenset(
    {"category", "manufacturer", "model", "serial_number", "schema_version"}
)

#: ``Properties/`` leaves the platform stores on the device row directly.
_STATUS_KEYS = frozenset(
    {"firmware", "hardware", "ip", "rssi", "latitude", "longitude", "address"}
)


def build_declaration(metrics: list[MetricView]) -> dict[str, Any]:
    """Reassemble the ``attributes`` declaration from BIRTH metrics.

    Returns ``{}`` when the birth carries no identity metrics at all, so a
    device that only reports readings does not generate an empty review item
    every time it reconnects.
    """
    identity: dict[str, Any] = {}
    capabilities: dict[str, bool] = {}
    ratings: dict[str, float] = {}

    for metric in metrics:
        name = metric.name
        if name.startswith(PROPERTIES_PREFIX):
            key = metric_key(_leaf(name, PROPERTIES_PREFIX))
            if key in _IDENTITY_KEYS and metric.value is not None:
                identity[key] = metric.value
        elif name.startswith(CAPABILITIES_PREFIX):
            key = metric_key(_leaf(name, CAPABILITIES_PREFIX))
            if metric.value is not None:
                capabilities[key] = bool(metric.value)
        elif name.startswith(RATINGS_PREFIX):
            key = metric_key(_leaf(name, RATINGS_PREFIX))
            if metric.value is not None:
                try:
                    ratings[key] = float(metric.value)
                except (TypeError, ValueError):
                    continue

    if not identity and not capabilities and not ratings:
        return {}

    raw_version = identity.pop("schema_version", PROFILE_VERSION)
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        # Keep the unusable value rather than defaulting to the current one:
        # the caller refuses versions it does not implement, and silently
        # rewriting a nonsense claim into a valid one would defeat that.
        version = -1

    declaration: dict[str, Any] = {"schema_version": version}
    declaration.update({k: v for k, v in identity.items() if v not in ("", None)})
    if capabilities:
        declaration["capabilities"] = capabilities
    if ratings:
        declaration["ratings"] = ratings
    return declaration


def build_status_fields(metrics: list[MetricView]) -> dict[str, Any]:
    """Pull the ``Properties/`` leaves that belong on the device row itself."""
    found: dict[str, Any] = {}
    for metric in metrics:
        if not metric.name.startswith(PROPERTIES_PREFIX):
            continue
        key = metric_key(_leaf(metric.name, PROPERTIES_PREFIX))
        if key in _STATUS_KEYS and metric.value is not None:
            found[key] = metric.value
    return found


# ------------------------------------------------------- alarms and events --
def as_alarm(metric: MetricView) -> dict[str, Any] | None:
    """``Alarm/<code>`` -> the alarm payload the worker already understands."""
    if not metric.name.startswith(ALARM_PREFIX):
        return None
    code = _leaf(metric.name, ALARM_PREFIX).strip()
    if not code:
        return None
    properties = metric.properties or {}
    return {
        "code": code[:64],
        "active": bool(metric.value),
        "severity": str(properties.get("severity", "warning"))[:16],
        "message": str(properties.get("message", ""))[:500],
        "details": {
            k: v for k, v in properties.items() if k not in ("severity", "message")
        },
    }


def as_event(metric: MetricView) -> dict[str, Any] | None:
    """``Event/<code>`` -> the operation-log payload."""
    if not metric.name.startswith(EVENT_PREFIX):
        return None
    code = _leaf(metric.name, EVENT_PREFIX).strip()
    if not code:
        return None
    properties = metric.properties or {}
    return {
        "code": code[:64],
        "level": str(properties.get("level", "info"))[:16],
        "message": str(metric.value or "")[:500],
        "data": {k: v for k, v in properties.items() if k != "level"},
    }


# ---------------------------------------------------------------- commands --
def as_command_ack(metrics: list[MetricView]) -> dict[str, Any] | None:
    """Read a command acknowledgement out of a DDATA payload.

    Sparkplug has no acknowledgement message of its own - a command is a metric
    write, and the confirmation is the device reporting the metric back. This
    profile keeps the correlation explicit with ``Command/ID`` so a command that
    is never answered can still be expired and audited.
    """
    fields: dict[str, Any] = {}
    result: dict[str, Any] = {}
    for metric in metrics:
        name = metric.name
        if name == COMMAND_ID:
            fields["command_id"] = str(metric.value or "")[:64]
        elif name == COMMAND_STATUS:
            fields["status"] = str(metric.value or "").strip().lower()
        elif name == COMMAND_MESSAGE:
            fields["message"] = str(metric.value or "")[:500]
        elif name.startswith(COMMAND_RESULT_PREFIX):
            result[metric_key(_leaf(name, COMMAND_RESULT_PREFIX))] = metric.value

    if not fields.get("command_id") or not fields.get("status"):
        return None
    fields.setdefault("message", "")
    fields["result"] = result
    return fields


# ------------------------------------------------------------ measurements --
def as_reading(metric: MetricView, name: str) -> dict[str, Any] | None:
    """Turn a measurement metric into the reading shape the worker stores.

    ``None`` means "not a measurement" - a control, an alarm, a property. It is
    deliberately not an error: a BIRTH legitimately contains all of them in one
    payload.
    """
    if not name or is_reserved(name):
        return None

    key = metric_key(name)
    if not key or len(key) > MAX_METRIC_KEY_LENGTH:
        return None

    numeric: float | None = None
    text: str | None = None

    if metric.value is None:
        numeric = None
    elif metric.datatype in NUMERIC_TYPES or isinstance(metric.value, (int, float, bool)):
        numeric = 1.0 if metric.value is True else 0.0 if metric.value is False else float(metric.value)
        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            return None
    elif metric.datatype in TEXT_TYPES or isinstance(metric.value, str):
        text = str(metric.value)[:2000]
    elif metric.datatype is DataType.Unknown:
        text = str(metric.value)[:2000]
    else:
        return None

    return {"metric": key, "value": numeric, "text": text}
