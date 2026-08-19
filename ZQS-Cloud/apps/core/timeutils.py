"""Timestamp parsing and validation shared by ingest and API layers.

Devices in the field disagree about time formats, so accept the common ones and
normalise everything to timezone-aware UTC datetimes.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

UTC = dt.timezone.utc

# Heuristic boundaries used to tell epoch seconds from ms / us / ns.
_SECONDS_MAX = 10_000_000_000  # ~ year 2286
_MILLIS_MAX = 10_000_000_000_000
_MICROS_MAX = 10_000_000_000_000_000


class TimestampError(ValueError):
    """Raised when a device timestamp cannot be interpreted."""


def parse_timestamp(value: Any) -> dt.datetime:
    """Convert a device supplied timestamp into an aware UTC datetime.

    Accepts epoch numbers (s / ms / us / ns) and ISO-8601 strings. A naive ISO
    string is assumed to be UTC, which matches the device protocol spec.
    """
    if value is None:
        raise TimestampError("timestamp is required")

    if isinstance(value, dt.datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    if isinstance(value, bool):
        raise TimestampError("timestamp must not be a boolean")

    if isinstance(value, (int, float)):
        return _from_epoch(float(value))

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise TimestampError("timestamp is empty")
        # Numeric string -> epoch
        try:
            return _from_epoch(float(text))
        except ValueError:
            pass
        iso = text.replace("Z", "+00:00").replace("z", "+00:00")
        try:
            parsed = dt.datetime.fromisoformat(iso)
        except ValueError as exc:
            raise TimestampError(f"unparseable timestamp: {value!r}") from exc
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    raise TimestampError(f"unsupported timestamp type: {type(value).__name__}")


def _from_epoch(number: float) -> dt.datetime:
    magnitude = abs(number)
    if magnitude >= _MICROS_MAX:
        number /= 1_000_000_000  # nanoseconds
    elif magnitude >= _MILLIS_MAX:
        number /= 1_000_000  # microseconds
    elif magnitude >= _SECONDS_MAX:
        number /= 1_000  # milliseconds
    try:
        return dt.datetime.fromtimestamp(number, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise TimestampError(f"epoch out of range: {number!r}") from exc


def now() -> dt.datetime:
    return dt.datetime.now(tz=UTC)


def to_epoch_ms(value: dt.datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


def check_clock_skew(
    ts: dt.datetime,
    *,
    max_future_s: int,
    max_past_s: int,
    reference: dt.datetime | None = None,
) -> None:
    """Guard against devices with a wildly wrong RTC poisoning the series."""
    reference = reference or now()
    delta = (ts - reference).total_seconds()
    if delta > max_future_s:
        raise TimestampError(
            f"timestamp is {int(delta)}s in the future (limit {max_future_s}s)"
        )
    if -delta > max_past_s:
        raise TimestampError(
            f"timestamp is {int(-delta)}s in the past (limit {max_past_s}s)"
        )


def floor_to_interval(value: dt.datetime, interval_seconds: int) -> dt.datetime:
    """Round down to the start of the containing interval bucket (UTC)."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    epoch = int(value.timestamp())
    return dt.datetime.fromtimestamp(
        epoch - (epoch % interval_seconds), tz=UTC
    )
