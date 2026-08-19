"""Builds site-level :class:`~apps.ems.models.EnergyInterval` rows.

Turns raw per-device power samples into the settlement-interval energy balance
the behind-the-meter dashboard reads. Doing this once, on a schedule, is what
keeps a month-long chart from scanning millions of sample rows.

Integration is **step-wise (zero-order hold)**: each sample's value is assumed
to hold until the next one. That matches how meters and PCS controllers report
- a value is the state since the last update, not a point on a smooth curve -
and it is stable when samples arrive irregularly.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from django.db import transaction

from apps.core.logging import get_logger
from apps.core.timeutils import floor_to_interval, now
from apps.ems.models import AssetRole, EnergyAsset, EnergyInterval, StoragePlan
from apps.ems.tariffs import resolve_price
from apps.telemetry.models import TelemetrySample

logger = get_logger("ems.aggregator")

DEFAULT_INTERVAL_SECONDS = 900  # 15 minutes, the common settlement period
SECONDS_PER_HOUR = 3600.0


@dataclass
class Integral:
    """Result of integrating one power series over a window."""

    positive_kwh: float = 0.0
    negative_kwh: float = 0.0
    peak_positive_kw: float | None = None
    peak_negative_kw: float | None = None
    average_kw: float | None = None
    #: Fraction of the window actually covered by samples (0..1).
    coverage: float = 0.0
    samples: int = 0

    @property
    def net_kwh(self) -> float:
        return self.positive_kwh - self.negative_kwh


@dataclass
class Stats:
    first: float | None = None
    last: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    values: list[float] = field(default_factory=list)


def integrate_power(
    points: list[tuple[dt.datetime, float]],
    start: dt.datetime,
    end: dt.datetime,
    *,
    seed: tuple[dt.datetime, float] | None = None,
) -> Integral:
    """Step-wise integrate a kW series into kWh over ``[start, end)``.

    ``seed`` is the last sample *before* the window; supplying it lets a device
    that reports only on change still contribute a full interval.
    """
    result = Integral()
    window_seconds = (end - start).total_seconds()
    if window_seconds <= 0:
        return result

    timeline: list[tuple[dt.datetime, float]] = []
    if seed is not None:
        timeline.append((start, seed[1]))
    for ts, value in points:
        if ts < start:
            # Later pre-window sample than the seed.
            if timeline and timeline[0][0] == start:
                timeline[0] = (start, value)
            else:
                timeline.insert(0, (start, value))
        elif ts < end:
            timeline.append((ts, value))

    if not timeline:
        return result

    result.samples = len(timeline)
    covered = 0.0

    for index, (ts, value) in enumerate(timeline):
        segment_end = timeline[index + 1][0] if index + 1 < len(timeline) else end
        duration = (segment_end - ts).total_seconds()
        if duration <= 0:
            continue
        covered += duration
        energy = value * duration / SECONDS_PER_HOUR
        if value >= 0:
            result.positive_kwh += energy
            result.peak_positive_kw = (
                value if result.peak_positive_kw is None else max(result.peak_positive_kw, value)
            )
        else:
            result.negative_kwh += -energy
            result.peak_negative_kw = (
                -value
                if result.peak_negative_kw is None
                else max(result.peak_negative_kw, -value)
            )

    result.coverage = min(covered / window_seconds, 1.0)
    if covered > 0:
        result.average_kw = (
            (result.positive_kwh - result.negative_kwh) * SECONDS_PER_HOUR / covered
        )
    return result


def summarize(points: list[tuple[dt.datetime, float]]) -> Stats:
    stats = Stats()
    for _ts, value in points:
        if stats.first is None:
            stats.first = value
        stats.last = value
        stats.minimum = value if stats.minimum is None else min(stats.minimum, value)
        stats.maximum = value if stats.maximum is None else max(stats.maximum, value)
    return stats


class SiteAggregator:
    """Computes energy intervals for one site."""

    def __init__(self, site, *, interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
        self.site = site
        self.interval_seconds = interval_seconds
        self.assets = list(
            EnergyAsset.objects.filter(site=site, is_active=True).select_related("device")
        )
        self.plan = StoragePlan.objects.filter(site=site).select_related("tariff").first()

    # ---- sample loading --------------------------------------------------
    def _series(
        self, asset: EnergyAsset, metric_key: str, start: dt.datetime, end: dt.datetime
    ) -> tuple[list[tuple[dt.datetime, float]], tuple[dt.datetime, float] | None]:
        """Samples inside the window plus the last one before it."""
        if not metric_key:
            return [], None

        rows = list(
            TelemetrySample.objects.filter(
                device_id=asset.device_id,
                metric_key=metric_key,
                ts__gte=start,
                ts__lt=end,
                value__isnull=False,
            )
            .order_by("ts")
            .values_list("ts", "value")
        )
        seed_row = (
            TelemetrySample.objects.filter(
                device_id=asset.device_id,
                metric_key=metric_key,
                ts__lt=start,
                value__isnull=False,
            )
            .order_by("-ts")
            .values_list("ts", "value")
            .first()
        )
        return list(rows), seed_row

    def _power_series(
        self, asset: EnergyAsset, start: dt.datetime, end: dt.datetime
    ) -> tuple[list[tuple[dt.datetime, float]], tuple[dt.datetime, float] | None]:
        """Power samples normalised to kW with the asset's sign convention."""
        rows, seed = self._series(asset, asset.power_metric, start, end)
        scaled = [(ts, asset.normalize_power(value)) for ts, value in rows]
        scaled_seed = (seed[0], asset.normalize_power(seed[1])) if seed else None
        return scaled, scaled_seed

    # ---- interval computation -------------------------------------------
    def compute_interval(self, start: dt.datetime) -> EnergyInterval | None:
        end = start + dt.timedelta(seconds=self.interval_seconds)

        grid = Integral()
        pv = Integral()
        battery = Integral()
        load_metered = Integral()
        soc = Stats()
        coverage_samples: list[float] = []

        for asset in self.assets:
            points, seed = self._power_series(asset, start, end)
            integral = integrate_power(points, start, end, seed=seed)

            if asset.role == AssetRole.GRID_METER:
                grid = _merge(grid, integral)
            elif asset.role == AssetRole.PV:
                pv = _merge(pv, integral)
            elif asset.role == AssetRole.BATTERY:
                battery = _merge(battery, integral)
                soc_points, _ = self._series(asset, asset.soc_metric, start, end)
                if soc_points:
                    soc = summarize(soc_points)
            elif asset.role in (AssetRole.LOAD_METER, AssetRole.EV_CHARGER):
                load_metered = _merge(load_metered, integral)
            else:
                continue

            # Only assets that actually reported count towards coverage; an
            # empty integral would otherwise make a silent window look measured.
            if integral.samples:
                coverage_samples.append(integral.coverage)

        if not coverage_samples:
            return None  # nothing reported in this window

        grid_import = grid.positive_kwh
        grid_export = grid.negative_kwh
        battery_discharge = battery.positive_kwh
        battery_charge = battery.negative_kwh

        if load_metered.samples:
            load_kwh = load_metered.positive_kwh
            peak_load_kw = load_metered.peak_positive_kw
            avg_load_kw = load_metered.average_kw
        else:
            # Derive load from the node balance when no load meter exists:
            #   load = grid_import - grid_export + pv + discharge - charge
            load_kwh = max(
                0.0,
                grid_import - grid_export + pv.positive_kwh + battery_discharge - battery_charge,
            )
            hours = self.interval_seconds / SECONDS_PER_HOUR
            avg_load_kw = load_kwh / hours if hours else None
            peak_load_kw = None

        price = resolve_price(self.plan.tariff if self.plan else None, start)
        energy_cost = grid_import * price.import_price
        export_revenue = grid_export * price.export_price

        # Counterfactual: the same load and PV with no battery installed.
        baseline_net = load_kwh - pv.positive_kwh
        baseline_cost = (
            max(baseline_net, 0.0) * price.import_price
            - max(-baseline_net, 0.0) * price.export_price
        )
        actual_cost = energy_cost - export_revenue

        return EnergyInterval(
            organization_id=self.site.organization_id,
            site=self.site,
            interval_start=start,
            interval_seconds=self.interval_seconds,
            grid_import_kwh=round(grid_import, 6),
            grid_export_kwh=round(grid_export, 6),
            pv_kwh=round(pv.positive_kwh, 6),
            load_kwh=round(load_kwh, 6),
            battery_charge_kwh=round(battery_charge, 6),
            battery_discharge_kwh=round(battery_discharge, 6),
            peak_import_kw=grid.peak_positive_kw,
            peak_export_kw=grid.peak_negative_kw,
            avg_load_kw=avg_load_kw,
            peak_load_kw=peak_load_kw,
            soc_start_percent=soc.first,
            soc_end_percent=soc.last,
            min_soc_percent=soc.minimum,
            max_soc_percent=soc.maximum,
            tariff_period=price.period_name,
            import_price=price.import_price,
            export_price=price.export_price,
            energy_cost=round(energy_cost, 6),
            export_revenue=round(export_revenue, 6),
            estimated_savings=round(baseline_cost - actual_cost, 6),
            coverage=round(
                sum(coverage_samples) / len(coverage_samples) if coverage_samples else 0.0,
                4,
            ),
        )

    def run(self, start: dt.datetime, end: dt.datetime) -> int:
        """Compute and upsert every interval in ``[start, end)``."""
        if not self.assets:
            return 0

        cursor = floor_to_interval(start, self.interval_seconds)
        rows: list[EnergyInterval] = []
        while cursor < end:
            interval = self.compute_interval(cursor)
            if interval is not None:
                rows.append(interval)
            cursor += dt.timedelta(seconds=self.interval_seconds)

        if not rows:
            return 0

        with transaction.atomic():
            EnergyInterval.objects.bulk_create(
                rows,
                batch_size=500,
                update_conflicts=True,
                unique_fields=["site", "interval_start", "interval_seconds"],
                update_fields=[
                    "organization",
                    "grid_import_kwh",
                    "grid_export_kwh",
                    "pv_kwh",
                    "load_kwh",
                    "battery_charge_kwh",
                    "battery_discharge_kwh",
                    "peak_import_kw",
                    "peak_export_kw",
                    "avg_load_kw",
                    "peak_load_kw",
                    "soc_start_percent",
                    "soc_end_percent",
                    "min_soc_percent",
                    "max_soc_percent",
                    "tariff_period",
                    "import_price",
                    "export_price",
                    "energy_cost",
                    "export_revenue",
                    "estimated_savings",
                    "coverage",
                ],
            )
        logger.info(
            "energy intervals rebuilt",
            extra={"site": self.site.name, "count": len(rows)},
        )
        return len(rows)


def _merge(left: Integral, right: Integral) -> Integral:
    """Combine two integrals, e.g. several PV inverters at one site."""
    if right.samples == 0:
        return left
    if left.samples == 0:
        return right
    merged = Integral(
        positive_kwh=left.positive_kwh + right.positive_kwh,
        negative_kwh=left.negative_kwh + right.negative_kwh,
        samples=left.samples + right.samples,
        coverage=max(left.coverage, right.coverage),
    )
    merged.peak_positive_kw = _max_optional(left.peak_positive_kw, right.peak_positive_kw)
    merged.peak_negative_kw = _max_optional(left.peak_negative_kw, right.peak_negative_kw)
    if left.average_kw is not None or right.average_kw is not None:
        merged.average_kw = (left.average_kw or 0.0) + (right.average_kw or 0.0)
    return merged


def _max_optional(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def aggregate_organization(
    organization,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
) -> dict[str, int]:
    """Rebuild intervals for every site of a tenant. Safe to re-run."""
    from apps.devices.models import Site

    until = until or now()
    since = since or (until - dt.timedelta(hours=2))
    summary: dict[str, int] = {}

    sites = Site.objects.filter(
        organization=organization, deleted_at__isnull=True, is_active=True
    )
    for site in sites:
        aggregator = SiteAggregator(site, interval_seconds=interval_seconds)
        summary[site.code] = aggregator.run(since, until)
    return summary
