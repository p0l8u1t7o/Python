"""Energy consumed or produced by *one device*, over an arbitrary window.

:mod:`apps.telemetry.energy` holds the arithmetic and knows nothing about the
database. This module is the other half: it decides *which* series answers the
question, loads it, and hands it over.

Two rules decide the method, and they are not interchangeable:

* A **counter** metric (``MetricKind.COUNTER``) is differenced. The device did
  the accumulating, so there is no sampling error. Whenever a counter exists
  for the flow being asked about, it wins - unconditionally.
* A **gauge** in kW is integrated with a zero-order hold. That is an
  approximation whose error depends on how often the device reports, so the
  result carries ``coverage`` and the caller is expected to show it.

Nothing here reads :class:`~apps.ems.models.EnergyInterval`. Those rows are
*site* level and 15 minutes wide; a single device's energy is not a slice of
them. The two answer different questions - see device-classification.md §3.11.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from apps.telemetry.energy import (
    BASIS_COUNTER,
    BASIS_INTEGRATED,
    BASIS_UNKNOWN,
    EnergyResult,
    counter_delta,
    integrate_kwh,
)
from apps.telemetry.models import Metric, MetricKind, Rollup, TelemetrySample

#: Bucket width used when differencing a counter out of the rollup table. The
#: scheduler writes 900 s buckets, so anything else would find nothing.
ROLLUP_INTERVAL_SECONDS = 900

#: Power metrics to fall back on, in preference order, when a device has no
#: energy asset binding to say which series means "this device's throughput".
_POWER_FALLBACKS = (
    "active_power_kw",
    "active_power_w",
    "power_kw",
    "power_w",
    "load_power_w",
)

#: Cumulative energy metrics, same idea. Preferred over the power fallbacks.
_COUNTER_FALLBACKS = (
    "load_energy_kwh",
    "energy_total_kwh",
    "grid_import_energy_kwh",
    "pv_energy_kwh",
)


@dataclass(frozen=True, slots=True)
class DeviceEnergy:
    """One device's energy over a window, and how it was arrived at."""

    device_id: uuid.UUID
    metric_key: str
    #: ``counter`` | ``integrated`` | ``unknown``. Never guess from the number.
    basis: str
    #: ``None`` means "cannot be determined" - never zero. A counter that went
    #: backwards with no declared ``counter_max`` lands here.
    kwh: float | None
    unit: str = "kWh"
    coverage: float = 0.0
    samples: int = 0
    counter_reset: bool = False
    #: Present when the metric is a gauge; the mean over the covered part.
    avg_kw: float | None = None
    peak_kw: float | None = None


def resolve_metric(device, metric_key: str = "") -> Metric | None:
    """The metric definition for ``metric_key``, tenant override winning.

    A tenant may redefine a built-in key - a different ``counter_max``, say -
    and the tenant's row is the one that must be used.
    """
    if not metric_key:
        return None
    own = Metric.objects.filter(
        organization_id=device.organization_id, key=metric_key
    ).first()
    if own is not None:
        return own
    return Metric.objects.filter(organization__isnull=True, key=metric_key).first()


def candidate_metrics(device) -> list[str]:
    """Metric keys that could answer "how much energy did this device move?".

    Counters first: they are exact. The device's own energy asset bindings
    outrank the generic fallbacks, because a binding is an operator saying
    *this* series is the one that means something for this device.
    """
    from apps.ems.models import EnergyAsset

    ordered: list[str] = []

    def add(key: str) -> None:
        if key and key not in ordered:
            ordered.append(key)

    for asset in EnergyAsset.objects.filter(device=device, is_active=True):
        add(asset.energy_import_metric)
        add(asset.energy_export_metric)
    for key in _COUNTER_FALLBACKS:
        add(key)

    for asset in EnergyAsset.objects.filter(device=device, is_active=True):
        add(asset.power_metric)
    for key in _POWER_FALLBACKS:
        add(key)

    # Only keep the ones this device has actually reported: offering a metric
    # that will always come back empty is worse than offering nothing.
    reported = set(
        TelemetrySample.objects.filter(device=device, metric_key__in=ordered)
        .values_list("metric_key", flat=True)
        .distinct()
    )
    return [key for key in ordered if key in reported]


def _power_scale(device, metric_key: str) -> float:
    """Multiplier turning the raw metric into kW, from the asset binding.

    A device reporting watts must not be integrated as if it reported
    kilowatts. The binding already carries that conversion (``power_scale``),
    so it is read rather than guessed. Without a binding, a ``_w`` suffix is
    the only evidence available and is used as a last resort.
    """
    from apps.ems.models import EnergyAsset

    asset = EnergyAsset.objects.filter(
        device=device, power_metric=metric_key, is_active=True
    ).first()
    if asset is not None:
        return asset.power_scale
    return 0.001 if metric_key.endswith("_w") else 1.0


def device_energy(
    device,
    *,
    start: dt.datetime,
    end: dt.datetime,
    metric_key: str = "",
) -> DeviceEnergy:
    """Energy for ``device`` over ``[start, end)``.

    With no ``metric_key`` the best available series is chosen by
    :func:`candidate_metrics`; passing one pins the answer to that series.
    """
    if not metric_key:
        candidates = candidate_metrics(device)
        if not candidates:
            return DeviceEnergy(
                device_id=device.pk,
                metric_key="",
                basis=BASIS_UNKNOWN,
                kwh=None,
            )
        metric_key = candidates[0]

    metric = resolve_metric(device, metric_key)
    if metric is not None and metric.kind == MetricKind.COUNTER:
        return _counter_energy(device, metric, start, end)
    return _gauge_energy(device, metric_key, start, end)


def _counter_energy(
    device, metric: Metric, start: dt.datetime, end: dt.datetime
) -> DeviceEnergy:
    """Difference a cumulative counter across the window.

    The edge values come from the rollup table when it covers the window -
    ``first_value`` / ``last_value`` are exactly this - and from the sample
    table otherwise, so a window narrower than a bucket still answers.
    """
    first, last = _counter_edges(device, metric.key, start, end)
    result = counter_delta(first, last, counter_max=metric.counter_max)

    scale = metric.unit.lower() in {"wh", "w·h", "w-h"}
    kwh = result.kwh / 1000.0 if (scale and result.kwh is not None) else result.kwh

    return DeviceEnergy(
        device_id=device.pk,
        metric_key=metric.key,
        basis=result.basis,
        kwh=None if kwh is None else round(kwh, 6),
        coverage=result.coverage,
        samples=result.samples,
        counter_reset=result.counter_reset,
    )


def _counter_edges(
    device, metric_key: str, start: dt.datetime, end: dt.datetime
) -> tuple[float | None, float | None]:
    buckets = list(
        Rollup.objects.filter(
            device=device,
            metric_key=metric_key,
            interval_seconds=ROLLUP_INTERVAL_SECONDS,
            bucket_start__gte=start,
            bucket_start__lt=end,
        )
        .order_by("bucket_start")
        .values_list("first_value", "last_value")
    )
    if buckets:
        first = next((value for value, _ in buckets if value is not None), None)
        last = next((value for _, value in reversed(buckets) if value is not None), None)
        if first is not None and last is not None:
            return first, last

    rows = TelemetrySample.objects.filter(
        device=device, metric_key=metric_key, ts__gte=start, ts__lt=end, value__isnull=False
    )
    first = rows.order_by("ts").values_list("value", flat=True).first()
    last = rows.order_by("-ts").values_list("value", flat=True).first()
    return first, last


def _gauge_energy(
    device, metric_key: str, start: dt.datetime, end: dt.datetime
) -> DeviceEnergy:
    """Integrate a power gauge. Approximate by construction - see ``coverage``."""
    scale = _power_scale(device, metric_key)
    rows = list(
        TelemetrySample.objects.filter(
            device=device,
            metric_key=metric_key,
            ts__gte=start,
            ts__lt=end,
            value__isnull=False,
        )
        .order_by("ts")
        .values_list("ts", "value")
    )
    points = [(ts, value * scale) for ts, value in rows]

    # The last sample before the window: a device that reports only on change
    # would otherwise contribute nothing to an interval it spent entirely at a
    # steady load.
    seed_row = (
        TelemetrySample.objects.filter(
            device=device, metric_key=metric_key, ts__lt=start, value__isnull=False
        )
        .order_by("-ts")
        .values_list("ts", "value")
        .first()
    )
    seed = (seed_row[0], seed_row[1] * scale) if seed_row else None

    result: EnergyResult = integrate_kwh(points, start, end, seed=seed)
    magnitudes = [abs(value) for _ts, value in points]
    hours = (end - start).total_seconds() / 3600.0

    return DeviceEnergy(
        device_id=device.pk,
        metric_key=metric_key,
        basis=result.basis if result.kwh is not None else BASIS_UNKNOWN,
        kwh=None if result.kwh is None else round(result.kwh, 6),
        coverage=round(result.coverage, 4),
        samples=result.samples,
        avg_kw=(
            round(result.kwh / hours, 4)
            if result.kwh is not None and hours > 0
            else None
        ),
        peak_kw=round(max(magnitudes), 4) if magnitudes else None,
    )


__all__ = [
    "BASIS_COUNTER",
    "BASIS_INTEGRATED",
    "BASIS_UNKNOWN",
    "DeviceEnergy",
    "candidate_metrics",
    "device_energy",
    "resolve_metric",
]
