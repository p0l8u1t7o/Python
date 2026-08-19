"""Device protocol payload schemas and validation.

This is the contract the LabVIEW device code has to satisfy. Validation runs in
the ingestor - before anything reaches the queue - so malformed traffic is
rejected at the edge and never costs a database round trip.

See ``docs/device-protocol.md`` for the human-readable specification.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

import orjson
from django.conf import settings
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from apps.core.timeutils import TimestampError, check_clock_skew, parse_timestamp

MAX_METRIC_KEY_LENGTH = 64


class ProtocolError(ValueError):
    """Payload rejected. ``reason`` is a stable code for metrics/dead letters."""

    def __init__(self, message: str, *, reason: str = "invalid_payload") -> None:
        super().__init__(message)
        self.reason = reason


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class Reading(_Base):
    """One measurement in the list-form telemetry payload."""

    metric: str = Field(max_length=MAX_METRIC_KEY_LENGTH)
    value: float | int | bool | str | None = None
    ts: Any | None = None
    quality: int | None = None


class TelemetryPayload(_Base):
    """Uplink on ``.../telemetry``.

    Two equivalent shapes are accepted, because both are natural to produce
    from LabVIEW:

    * dictionary form - ``{"ts": ..., "metrics": {"battery_soc": 78.2}}``
    * list form - ``{"ts": ..., "readings": [{"metric": "battery_soc", ...}]}``
    """

    ts: Any
    seq: int | None = None
    metrics: dict[str, float | int | bool | str | None] | None = None
    readings: list[Reading] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metrics")
    @classmethod
    def _check_metrics(cls, value):
        if value is not None:
            limit = settings.INGEST["MAX_METRICS_PER_MESSAGE"]
            if len(value) > limit:
                raise ValueError(f"too many metrics in one message (limit {limit})")
        return value


class LocationPayload(_Base):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str = Field(default="", max_length=400)


class StatusPayload(_Base):
    """Uplink on ``.../status``. Also used as the MQTT last-will message."""

    status: Literal["online", "offline"]
    ts: Any | None = None
    reason: str = Field(default="", max_length=64)
    firmware: str = Field(default="", max_length=64)
    hardware: str = Field(default="", max_length=64)
    ip: str = Field(default="", max_length=45)
    rssi: int | None = None
    location: LocationPayload | None = None


class EventPayload(_Base):
    """Uplink on ``.../event`` - the device's own operation log."""

    ts: Any | None = None
    level: Literal["debug", "info", "notice", "warning", "error", "critical"] = "info"
    code: str = Field(default="", max_length=64)
    message: str = Field(default="", max_length=500)
    data: dict[str, Any] = Field(default_factory=dict)


class AlarmPayload(_Base):
    """Uplink on ``.../alarm`` - a fault the device itself detected."""

    ts: Any | None = None
    code: str = Field(max_length=64)
    severity: Literal["info", "warning", "major", "critical"] = "warning"
    message: str = Field(default="", max_length=500)
    #: False clears a previously raised alarm with the same code.
    active: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class CommandAckPayload(_Base):
    """Uplink on ``.../control/ack``."""

    command_id: str = Field(max_length=64)
    status: Literal["accepted", "rejected", "succeeded", "failed"]
    ts: Any | None = None
    message: str = Field(default="", max_length=500)
    result: dict[str, Any] = Field(default_factory=dict)


_SCHEMAS: dict[str, type[_Base]] = {
    "telemetry": TelemetryPayload,
    "status": StatusPayload,
    "event": EventPayload,
    "alarm": AlarmPayload,
    "control/ack": CommandAckPayload,
}


def decode(raw: bytes) -> dict[str, Any]:
    """Parse the MQTT payload, enforcing the size limit first."""
    limit = settings.INGEST["MAX_PAYLOAD_BYTES"]
    if len(raw) > limit:
        raise ProtocolError(
            f"payload of {len(raw)} bytes exceeds the {limit} byte limit",
            reason="payload_too_large",
        )
    if not raw.strip():
        raise ProtocolError("empty payload", reason="empty_payload")
    try:
        document = orjson.loads(raw)
    except orjson.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}", reason="invalid_json") from exc
    if not isinstance(document, dict):
        raise ProtocolError("payload must be a JSON object", reason="not_an_object")
    return document


def validate(kind: str, document: dict[str, Any]) -> _Base:
    schema = _SCHEMAS.get(kind)
    if schema is None:
        raise ProtocolError(f"unsupported message kind: {kind}", reason="unknown_kind")
    try:
        return schema.model_validate(document)
    except ValidationError as exc:
        raise ProtocolError(
            f"schema validation failed: {exc.errors(include_url=False)}",
            reason="schema_invalid",
        ) from exc


def resolve_timestamp(value: Any, *, received_at: dt.datetime) -> dt.datetime:
    """Normalise a device timestamp and reject implausible clock drift.

    A missing timestamp falls back to server receive time; a *wrong* one does
    not, because silently accepting it would corrupt the series ordering.
    """
    if value is None:
        return received_at
    try:
        ts = parse_timestamp(value)
        check_clock_skew(
            ts,
            max_future_s=settings.INGEST["MAX_CLOCK_SKEW_FUTURE_S"],
            max_past_s=settings.INGEST["MAX_CLOCK_SKEW_PAST_S"],
            reference=received_at,
        )
    except TimestampError as exc:
        raise ProtocolError(str(exc), reason="bad_timestamp") from exc
    return ts


def normalize_readings(
    payload: TelemetryPayload, *, received_at: dt.datetime
) -> list[dict[str, Any]]:
    """Flatten either telemetry shape into a uniform list of readings."""
    default_ts = resolve_timestamp(payload.ts, received_at=received_at)
    readings: list[dict[str, Any]] = []

    if payload.metrics:
        for key, value in payload.metrics.items():
            readings.append(_reading(key, value, default_ts, None))

    if payload.readings:
        for item in payload.readings:
            ts = (
                resolve_timestamp(item.ts, received_at=received_at)
                if item.ts is not None
                else default_ts
            )
            readings.append(_reading(item.metric, item.value, ts, item.quality))

    if not readings:
        raise ProtocolError(
            "telemetry message carries no metrics or readings", reason="no_readings"
        )

    limit = settings.INGEST["MAX_METRICS_PER_MESSAGE"]
    if len(readings) > limit:
        raise ProtocolError(
            f"{len(readings)} readings exceed the {limit} per-message limit",
            reason="too_many_readings",
        )
    return readings


def _reading(key: str, value: Any, ts: dt.datetime, quality: int | None) -> dict[str, Any]:
    key = (key or "").strip().lower()
    if not key:
        raise ProtocolError("metric key is empty", reason="bad_metric_key")
    if len(key) > MAX_METRIC_KEY_LENGTH:
        raise ProtocolError(
            f"metric key '{key[:20]}...' exceeds {MAX_METRIC_KEY_LENGTH} characters",
            reason="bad_metric_key",
        )

    numeric: float | None = None
    text: str | None = None
    if isinstance(value, bool):
        numeric = 1.0 if value else 0.0
    elif isinstance(value, (int, float)):
        numeric = float(value)
        # NaN/Inf survive JSON parsing in some encoders but break aggregation.
        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            raise ProtocolError(
                f"metric '{key}' has a non-finite value", reason="non_finite_value"
            )
    elif value is None:
        numeric = None
    else:
        text = str(value)[:2000]

    return {
        "metric": key,
        "value": numeric,
        "text": text,
        "ts": ts.isoformat(),
        "quality": quality,
    }
