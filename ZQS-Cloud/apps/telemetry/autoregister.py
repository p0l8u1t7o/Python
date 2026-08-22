"""Plug-and-play metric registration from a Sparkplug DBIRTH.

A DBIRTH is defined as the complete set of metrics a device offers, and each
metric carries its own datatype - and, in this profile, its unit. That is
everything the catalogue needs, so a device that has never been seen before can
describe itself into existence: charts get axis labels, the plausibility check
gets a type, and the console stops showing raw keys.

**What this does not do is grant anything.** A registered metric is a label on
an axis; it is not a capability, a rating or a permission. Those still go
through :class:`~apps.devices.models.DeviceDeclaration` and wait for a human.
The trust boundary is unchanged - see docs/system-logic.md.

Two rules keep an untrusted device from making a mess of a tenant's catalogue:

* **Never overwrite.** A key an operator has already defined keeps its
  definition, always. Otherwise a firmware update could silently relabel a
  meter that a dozen alert rules depend on.
* **Organisation-scoped only.** Built-in metrics are shared by every tenant and
  are never touched.
"""

from __future__ import annotations

from typing import Any

from apps.core.logging import get_logger
from services.sparkplug.datatypes import TEXT_TYPES, DataType

logger = get_logger("telemetry.autoregister")

#: Sparkplug datatype -> (value_type, default aggregation).
_VALUE_TYPES: dict[DataType, tuple[str, str]] = {
    DataType.Boolean: ("boolean", "last"),
    DataType.Int8: ("integer", "avg"),
    DataType.Int16: ("integer", "avg"),
    DataType.Int32: ("integer", "avg"),
    DataType.Int64: ("integer", "avg"),
    DataType.UInt8: ("integer", "avg"),
    DataType.UInt16: ("integer", "avg"),
    DataType.UInt32: ("integer", "avg"),
    DataType.UInt64: ("integer", "avg"),
    DataType.Float: ("float", "avg"),
    DataType.Double: ("float", "avg"),
}

#: Units that mean the value only ever climbs, so a delta is what matters.
_COUNTER_UNITS = {"kwh", "wh", "mwh", "kvarh", "varh", "m3", "l", "litre", "liters"}

#: Sensible plausibility windows inferred from the unit alone. Deliberately
#: wide: a window that is too tight flags good data as suspect, which is worse
#: than no window at all because it teaches people to ignore the flag.
_RANGES: dict[str, tuple[float, float]] = {
    "%": (-5.0, 105.0),
    "hz": (0.0, 100.0),
    "degc": (-60.0, 200.0),
    "c": (-60.0, 200.0),
}


def _normalise_unit(unit: str) -> str:
    return (unit or "").strip()


def describe(name: str, datatype: DataType, properties: dict[str, Any]) -> dict:
    """Build the catalogue fields for one birth metric."""
    unit = _normalise_unit(str(properties.get("unit") or ""))
    value_type, aggregation = _VALUE_TYPES.get(datatype, ("float", "avg"))
    if datatype in TEXT_TYPES:
        value_type, aggregation = "string", "last"

    kind = "gauge"
    declared_kind = str(properties.get("kind") or "").strip().lower()
    if declared_kind in ("gauge", "counter", "state"):
        kind = declared_kind
    elif unit.lower() in _COUNTER_UNITS:
        # A cumulative unit with no explicit kind is almost always a counter,
        # and getting this wrong means the energy figures integrate a total
        # instead of differencing it.
        kind = "counter"
    elif value_type == "string":
        kind = "state"

    if kind == "counter":
        aggregation = "counter"

    minimum = maximum = None
    window = _RANGES.get(unit.lower())
    if window is not None:
        minimum, maximum = window

    fields: dict[str, Any] = {
        "display_name": str(properties.get("display_name") or name)[:120],
        "description": str(properties.get("description") or "")[:2000],
        "unit": unit[:24],
        "value_type": value_type,
        "kind": kind,
        "aggregation": aggregation,
        "min_value": minimum,
        "max_value": maximum,
        "category": str(properties.get("category") or "")[:40],
    }

    counter_max = properties.get("counter_max")
    if counter_max is not None:
        try:
            fields["counter_max"] = float(counter_max)
        except (TypeError, ValueError):
            pass
    return fields


def register_from_birth(organization_id, metrics: list[dict[str, Any]]) -> int:
    """Create catalogue entries for keys this tenant has never defined.

    ``metrics`` is the envelope form: dicts with ``name``, ``datatype`` and
    ``properties``. Returns how many rows were created.
    """
    from apps.devices.registry import get_registry  # noqa: F401  (import cycle guard)
    from apps.telemetry.models import Metric
    from services.sparkplug import profile

    candidates: dict[str, dict] = {}
    for metric in metrics:
        name = metric.get("name") or ""
        if not name or profile.is_reserved(name):
            continue
        key = profile.metric_key(name)
        if not key or len(key) > profile.MAX_METRIC_KEY_LENGTH:
            continue
        try:
            datatype = DataType(int(metric.get("datatype") or 0))
        except ValueError:
            datatype = DataType.Unknown
        candidates.setdefault(
            key, describe(name, datatype, metric.get("properties") or {})
        )

    if not candidates:
        return 0

    # One query for what exists, including the built-ins: a tenant row that
    # shadows a built-in key would fork the definition of a metric that charts
    # and alert rules already share.
    from django.db.models import Q

    known = set(
        Metric.objects.filter(
            Q(organization_id=organization_id) | Q(organization__isnull=True),
            key__in=list(candidates),
        ).values_list("key", flat=True)
    )
    missing = [key for key in candidates if key not in known]
    if not missing:
        return 0

    created = Metric.objects.bulk_create(
        [
            Metric(organization_id=organization_id, key=key, **candidates[key])
            for key in missing
        ],
        batch_size=200,
        ignore_conflicts=True,
    )
    logger.info(
        "metrics auto-registered from birth",
        extra={"count": len(missing), "keys": ", ".join(sorted(missing)[:10])},
    )
    return len(created)
