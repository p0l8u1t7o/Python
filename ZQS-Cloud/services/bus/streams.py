"""Canonical stream names.

Kept in one place so the ingestor, the worker and the ops tooling cannot drift
apart on naming. Streams are separated by message kind so a burst of telemetry
never delays a status change or a command acknowledgement.
"""

from __future__ import annotations

from django.conf import settings

TELEMETRY = "telemetry"
STATUS = "status"
EVENT = "event"
ALARM = "alarm"
COMMAND_ACK = "command_ack"
DEAD_LETTER = "dead_letter"

#: Consumed by the worker, in priority order.
ALL_INGEST_STREAMS = (COMMAND_ACK, STATUS, ALARM, EVENT, TELEMETRY)


def qualified(name: str) -> str:
    """Prefix a logical name so several environments can share one broker."""
    prefix = settings.BUS["STREAM_PREFIX"].rstrip(".:")
    return f"{prefix}.{name}" if prefix else name


def all_qualified() -> tuple[str, ...]:
    return tuple(qualified(name) for name in ALL_INGEST_STREAMS)


def logical(qualified_name: str) -> str:
    """Inverse of :func:`qualified`."""
    prefix = settings.BUS["STREAM_PREFIX"].rstrip(".:")
    if prefix and qualified_name.startswith(f"{prefix}."):
        return qualified_name[len(prefix) + 1 :]
    return qualified_name
