"""Encoding and decoding of Sparkplug B protobuf payloads.

Everything above this module works in plain Python values; everything below it
is protobuf. Keeping the boundary here means the ingestor and the worker never
touch a generated class, and swapping the generated binding (a protobuf major
version, say) touches one file.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from google.protobuf.message import DecodeError

from services.sparkplug import sparkplug_b_pb2 as pb
from services.sparkplug.datatypes import DataType, get_value, infer, set_value

#: Sparkplug sequence numbers roll over at 256.
SEQ_MODULUS = 256

#: Metric name every edge node must include in NBIRTH and NDEATH so a death can
#: be matched to the birth it ends.
BDSEQ_METRIC = "bdSeq"

#: Metrics the host writes to ask a node or device to re-announce itself.
NODE_REBIRTH_METRIC = "Node Control/Rebirth"
DEVICE_REBIRTH_METRIC = "Device Control/Rebirth"


class PayloadError(ValueError):
    """Payload rejected. ``reason`` is a stable code for metrics and logs."""

    def __init__(self, message: str, *, reason: str = "invalid_payload") -> None:
        super().__init__(message)
        self.reason = reason


# ---------------------------------------------------------------- decoding --
@dataclass(slots=True)
class MetricView:
    """One metric, flattened into Python types.

    ``name`` is empty when the publisher used an alias alone - which is legal
    after a BIRTH and is the main reason Sparkplug is compact on the wire. The
    caller resolves it against the alias table the BIRTH established.
    """

    name: str
    alias: int | None
    datatype: DataType
    value: Any
    timestamp: dt.datetime | None
    is_null: bool = False
    is_historical: bool = False
    is_transient: bool = False
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PayloadView:
    timestamp: dt.datetime | None
    seq: int | None
    metrics: list[MetricView]
    uuid: str = ""
    body: bytes = b""


def _epoch_ms_to_datetime(value: int | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromtimestamp(value / 1000.0, tz=dt.UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise PayloadError(
            f"timestamp {value} is not a representable epoch-millisecond value",
            reason="bad_timestamp",
        ) from exc


def datetime_to_epoch_ms(moment: dt.datetime) -> int:
    return int(moment.timestamp() * 1000)


def _properties_to_dict(propertyset) -> dict[str, Any]:
    """Flatten a PropertySet. Nested sets become plain dicts."""
    result: dict[str, Any] = {}
    for key, value in zip(propertyset.keys, propertyset.values, strict=False):
        if value.is_null:
            result[key] = None
            continue
        which = value.WhichOneof("value")
        if which is None:
            result[key] = None
        elif which == "propertyset_value":
            result[key] = _properties_to_dict(value.propertyset_value)
        elif which == "propertysets_value":
            result[key] = [
                _properties_to_dict(item)
                for item in value.propertysets_value.propertyset
            ]
        else:
            result[key] = getattr(value, which)
    return result


def decode(raw: bytes) -> PayloadView:
    """Parse a protobuf payload, enforcing the size limit before doing so."""
    limit = settings.INGEST["MAX_PAYLOAD_BYTES"]
    if len(raw) > limit:
        raise PayloadError(
            f"payload of {len(raw)} bytes exceeds the {limit} byte limit",
            reason="payload_too_large",
        )

    message = pb.Payload()
    if raw:
        try:
            message.ParseFromString(raw)
        except (DecodeError, ValueError) as exc:
            raise PayloadError(
                f"payload is not a valid Sparkplug B protobuf: {exc}",
                reason="invalid_protobuf",
            ) from exc

    limit_metrics = settings.INGEST["MAX_METRICS_PER_MESSAGE"]
    if len(message.metrics) > limit_metrics:
        raise PayloadError(
            f"{len(message.metrics)} metrics exceed the {limit_metrics} "
            "per-message limit",
            reason="too_many_metrics",
        )

    metrics: list[MetricView] = []
    for metric in message.metrics:
        try:
            datatype = DataType(metric.datatype)
        except ValueError:
            datatype = DataType.Unknown
        metrics.append(
            MetricView(
                name=metric.name or "",
                alias=metric.alias if metric.HasField("alias") else None,
                datatype=datatype,
                value=get_value(metric),
                timestamp=_epoch_ms_to_datetime(
                    metric.timestamp if metric.HasField("timestamp") else None
                ),
                is_null=metric.is_null,
                is_historical=metric.is_historical,
                is_transient=metric.is_transient,
                properties=(
                    _properties_to_dict(metric.properties)
                    if metric.HasField("properties")
                    else {}
                ),
            )
        )

    return PayloadView(
        timestamp=_epoch_ms_to_datetime(
            message.timestamp if message.HasField("timestamp") else None
        ),
        seq=message.seq if message.HasField("seq") else None,
        metrics=metrics,
        uuid=message.uuid or "",
        body=message.body or b"",
    )


# ---------------------------------------------------------------- encoding --
def _set_property(propertyset, key: str, value: Any) -> None:
    propertyset.keys.append(key)
    entry = propertyset.values.add()
    if value is None:
        entry.type = int(DataType.String)
        entry.is_null = True
    elif isinstance(value, bool):
        entry.type = int(DataType.Boolean)
        entry.boolean_value = value
    elif isinstance(value, int):
        entry.type = int(DataType.Int64)
        entry.long_value = value & 0xFFFFFFFFFFFFFFFF
    elif isinstance(value, float):
        entry.type = int(DataType.Double)
        entry.double_value = value
    else:
        entry.type = int(DataType.String)
        entry.string_value = str(value)


def new_payload(*, timestamp: dt.datetime | None = None, seq: int | None = None):
    message = pb.Payload()
    if timestamp is not None:
        message.timestamp = datetime_to_epoch_ms(timestamp)
    if seq is not None:
        message.seq = seq % SEQ_MODULUS
    return message


def add_metric(
    message,
    name: str,
    value: Any,
    *,
    datatype: DataType | None = None,
    alias: int | None = None,
    timestamp: dt.datetime | None = None,
    properties: dict[str, Any] | None = None,
    is_transient: bool = False,
    is_historical: bool = False,
):
    metric = message.metrics.add()
    if name:
        metric.name = name
    if alias is not None:
        metric.alias = alias
    if timestamp is not None:
        metric.timestamp = datetime_to_epoch_ms(timestamp)
    if is_transient:
        metric.is_transient = True
    if is_historical:
        metric.is_historical = True

    set_value(metric, datatype or infer(value), value)

    if properties:
        for key, item in properties.items():
            _set_property(metric.properties, key, item)
    return metric


def encode(message) -> bytes:
    return message.SerializeToString()


# ----------------------------------------------------------------- helpers --
def next_seq(current: int | None) -> int:
    """The sequence number that must follow ``current``."""
    return 0 if current is None else (current + 1) % SEQ_MODULUS


def bd_seq_of(view: PayloadView) -> int | None:
    """Read the ``bdSeq`` metric out of an NBIRTH or NDEATH payload."""
    for metric in view.metrics:
        if metric.name == BDSEQ_METRIC:
            return None if metric.value is None else int(metric.value)
    return None
