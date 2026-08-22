"""Sparkplug B metric data types and the value fields they map onto.

The protobuf schema stores every scalar in one of six ``oneof`` fields, so the
``datatype`` number is the only thing that says how to read the bits back. Get
it wrong and a temperature of -5 comes back as 4294967291 - which is why the
signed types round-trip through explicit two's complement here rather than
relying on whatever the caller happened to pass in.
"""

from __future__ import annotations

from enum import IntEnum


class DataType(IntEnum):
    """Values from the Sparkplug B specification, appendix "Data Types"."""

    Unknown = 0
    Int8 = 1
    Int16 = 2
    Int32 = 3
    Int64 = 4
    UInt8 = 5
    UInt16 = 6
    UInt32 = 7
    UInt64 = 8
    Float = 9
    Double = 10
    Boolean = 11
    String = 12
    DateTime = 13
    Text = 14
    UUID = 15
    DataSet = 16
    Bytes = 17
    File = 18
    Template = 19
    PropertySet = 20
    PropertySetList = 21
    Int8Array = 22
    Int16Array = 23
    Int32Array = 24
    Int64Array = 25
    UInt8Array = 26
    UInt16Array = 27
    UInt32Array = 28
    UInt64Array = 29
    FloatArray = 30
    DoubleArray = 31
    BooleanArray = 32
    StringArray = 33
    DateTimeArray = 34


#: Signed integer types and their width in bits.
_SIGNED_WIDTH = {
    DataType.Int8: 8,
    DataType.Int16: 16,
    DataType.Int32: 32,
    DataType.Int64: 64,
}

#: Unsigned integer types and their width in bits.
_UNSIGNED_WIDTH = {
    DataType.UInt8: 8,
    DataType.UInt16: 16,
    DataType.UInt32: 32,
    DataType.UInt64: 64,
    DataType.DateTime: 64,
}

#: Types carried in the 32-bit ``int_value`` field rather than ``long_value``.
_INT32_FIELD = {
    DataType.Int8,
    DataType.Int16,
    DataType.Int32,
    DataType.UInt8,
    DataType.UInt16,
    DataType.UInt32,
}

_INT64_FIELD = {DataType.Int64, DataType.UInt64, DataType.DateTime}

#: Types this platform stores as a numeric time series.
NUMERIC_TYPES = (
    _INT32_FIELD
    | _INT64_FIELD
    | {DataType.Float, DataType.Double, DataType.Boolean}
) - {DataType.DateTime}

#: Types this platform stores as text.
TEXT_TYPES = {DataType.String, DataType.Text, DataType.UUID}


class DataTypeError(ValueError):
    """The datatype and the value present on the metric do not agree."""


def _to_unsigned(value: int, bits: int) -> int:
    """Two's complement, because protobuf has no signed field here."""
    return value & ((1 << bits) - 1)


def _to_signed(value: int, bits: int) -> int:
    limit = 1 << (bits - 1)
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >= limit else value


def set_value(metric, datatype: DataType, value) -> None:
    """Write ``value`` into the correct ``oneof`` field of a Metric.

    ``None`` sets ``is_null`` rather than a zero, so "the sensor has no reading"
    stays distinguishable from "the sensor read zero" - a distinction the whole
    energy integration depends on.
    """
    metric.datatype = int(datatype)
    if value is None:
        metric.is_null = True
        return

    if datatype in _INT32_FIELD:
        number = int(value)
        bits = _SIGNED_WIDTH.get(datatype) or _UNSIGNED_WIDTH[datatype]
        metric.int_value = _to_unsigned(number, bits) if datatype in _SIGNED_WIDTH else number & ((1 << bits) - 1)
    elif datatype in _INT64_FIELD:
        number = int(value)
        bits = 64
        metric.long_value = _to_unsigned(number, bits) if datatype in _SIGNED_WIDTH else number & ((1 << bits) - 1)
    elif datatype is DataType.Float:
        metric.float_value = float(value)
    elif datatype is DataType.Double:
        metric.double_value = float(value)
    elif datatype is DataType.Boolean:
        metric.boolean_value = bool(value)
    elif datatype in TEXT_TYPES:
        metric.string_value = str(value)
    elif datatype in (DataType.Bytes, DataType.File):
        metric.bytes_value = bytes(value)
    else:
        raise DataTypeError(f"unsupported datatype for scalar write: {datatype!r}")


def get_value(metric):
    """Read a Metric back into a Python value, honouring ``is_null``."""
    if metric.is_null:
        return None

    field = metric.WhichOneof("value")
    if field is None:
        return None

    try:
        datatype = DataType(metric.datatype)
    except ValueError:
        datatype = DataType.Unknown

    raw = getattr(metric, field)

    if datatype in _SIGNED_WIDTH and field in ("int_value", "long_value"):
        return _to_signed(int(raw), _SIGNED_WIDTH[datatype])
    if datatype is DataType.Boolean:
        return bool(raw)
    if field in ("int_value", "long_value"):
        return int(raw)
    if field in ("float_value", "double_value"):
        return float(raw)
    return raw


def infer(value) -> DataType:
    """Best datatype for a Python value, used when the platform originates one.

    Booleans are checked before integers on purpose: ``bool`` is a subclass of
    ``int``, so the obvious ordering silently turns every ``True`` into ``1``.
    """
    if isinstance(value, bool):
        return DataType.Boolean
    if isinstance(value, int):
        return DataType.Int64
    if isinstance(value, float):
        return DataType.Double
    if isinstance(value, (bytes, bytearray)):
        return DataType.Bytes
    return DataType.String
