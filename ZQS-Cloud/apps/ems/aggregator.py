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
from apps.ems import costs
from apps.ems.models import (
    AssetRole,
    EnergyAsset,
    EnergyInterval,
    EnergyIntervalCost,
)
from apps.ems.outage import overlaps_outage
from apps.ems.tariffs import resolve_price
from apps.telemetry.energy import build_timeline
from apps.telemetry.models import TelemetrySample

logger = get_logger("ems.aggregator")

#: A reading above this many times the asset's rated power is treated as bad
#: data rather than a record. Generous on purpose: short overloads are real,
#: an order of magnitude is not.
PLAUSIBILITY_FACTOR = 5.0

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

    # Shared with per-device energy: deciding what the value was at ``start``
    # is the subtle part, and it should have one implementation.
    timeline = build_timeline(points, start, end, seed=seed)

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
        from apps.ems.plans import effective_plan

        self.plan = effective_plan(site)[0]

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

        # Physically impossible readings are dropped before they reach the
        # balance. A load meter rated 1,200 kW reporting 45 MW is a scaling
        # error, a test override or a wiring fault - not a peak, and letting
        # it in made the demand "baseline" (and so the demand benefit) absurd.
        limit = self._plausible_kw(asset)
        if limit is not None:
            kept = [(ts, kw) for ts, kw in scaled if kw is None or abs(kw) <= limit]
            dropped = len(scaled) - len(kept)
            if dropped:
                logger.warning(
                    "implausible power readings ignored",
                    extra={"device_id": str(asset.device_id), "metric": asset.power_metric,
                           "dropped": dropped, "limit_kw": limit},
                )
                scaled = kept
            if scaled_seed and scaled_seed[1] is not None and abs(scaled_seed[1]) > limit:
                scaled_seed = None
        return scaled, scaled_seed

    @staticmethod
    def _plausible_kw(asset: EnergyAsset) -> float | None:
        """Largest |kW| this asset can plausibly report, or None when unrated."""
        rated = asset.rated_power_kw
        if not rated or rated <= 0:
            return None
        return float(rated) * PLAUSIBILITY_FACTOR

    # ---- interval computation -------------------------------------------
    def compute_interval(self, start: dt.datetime) -> EnergyInterval | None:
        end = start + dt.timedelta(seconds=self.interval_seconds)

        grid = Integral()
        pv = Integral()
        battery = Integral()
        generator = Integral()
        load_metered = Integral()
        soc = Stats()
        coverage_samples: list[float] = []

        for asset in self.assets:
            points, seed = self._power_series(asset, start, end)
            integral = integrate_power(points, start, end, seed=seed)

            # Sub-meters are measured, charted and counted per device, but they
            # duplicate a flow that another asset already reports - folding them
            # in would count the same electrons twice.
            if not asset.include_in_balance:
                continue

            if asset.role == AssetRole.GRID_METER:
                grid = _merge(grid, integral)
            elif asset.role == AssetRole.PV:
                pv = _merge(pv, integral)
            elif asset.role == AssetRole.BATTERY:
                battery = _merge(battery, integral)
                soc_points, _ = self._series(asset, asset.soc_metric, start, end)
                if soc_points:
                    soc = summarize(soc_points)
            elif asset.role == AssetRole.GENERATOR:
                # Kept out of battery_*: round-trip efficiency is
                # discharge / charge, and a generator only ever discharges -
                # folding it in would produce an efficiency above 1.
                generator = _merge(generator, integral)
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
        generator_kwh = generator.positive_kwh

        if load_metered.samples:
            load_kwh = load_metered.positive_kwh
            peak_load_kw = load_metered.peak_positive_kw
            avg_load_kw = load_metered.average_kw
        else:
            # Derive load from the node balance when no load meter exists:
            #   load = grid_import - grid_export + pv + discharge - charge + gen
            load_kwh = max(
                0.0,
                grid_import
                - grid_export
                + pv.positive_kwh
                + battery_discharge
                - battery_charge
                + generator_kwh,
            )
            hours = self.interval_seconds / SECONDS_PER_HOUR
            avg_load_kw = load_kwh / hours if hours else None
            peak_load_kw = None

        tariff = self.plan.tariff if self.plan else None
        price = resolve_price(tariff, start)
        energy_cost = grid_import * price.import_price
        export_revenue = grid_export * price.export_price

        actual_cost = energy_cost - export_revenue
        savings = self._savings(
            price=price,
            load_kwh=load_kwh,
            pv_kwh=pv.positive_kwh,
            generator_kwh=generator_kwh,
            actual_cost=actual_cost,
        )
        # W6：真正的停電訊號。停電期間沒有「改跟台電買」的對照，節省記 null
        # （既有規則），柴發近似保留為後備。
        if savings is not None and overlaps_outage(self.site.pk, start, end):
            savings = None

        interval = EnergyInterval(
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
            generator_kwh=round(generator_kwh, 6),
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
            estimated_savings=None if savings is None else round(savings, 6),
            coverage=round(
                sum(coverage_samples) / len(coverage_samples) if coverage_samples else 0.0,
                4,
            ),
        )
        # Carried on the unsaved instance; ``run`` writes them once the row
        # has a primary key. Kept off the model so nothing can mistake them
        # for stored fields.
        interval.pending_costs = self._breakdown(
            start,
            tariff,
            grid_import=grid_import,
            grid_export=grid_export,
            battery_discharge=battery_discharge,
            generator_kwh=generator_kwh,
            battery_avg_kw=battery.average_kw,
            generator_avg_kw=generator.average_kw,
            soc_start=soc.first,
            soc_end=soc.last,
        )
        return interval

    # ---- Savings and cost breakdown --------------------------------------
    def _savings(
        self,
        *,
        price,
        load_kwh: float,
        pv_kwh: float,
        generator_kwh: float,
        actual_cost: float,
    ) -> float | None:
        """Cost difference against the plan's chosen baseline.

        ``None`` when there is no meaningful baseline, which happens in two
        cases and is an honest answer in both: the plan asks for no savings
        figure at all, or the generator ran. While a generator is carrying the
        site there is no "buy it from the utility instead" to compare against,
        so any number here would be invented.

        Using generator output as the stand-in for "outage" is an
        approximation kept as a fallback; the real signal is the grid-meter
        voltage rule (W6, :mod:`apps.ems.outage`), applied by the caller.
        """
        baseline = getattr(self.plan, "savings_baseline", "no_storage") or "no_storage"
        if baseline == "none" or generator_kwh > 0:
            return None

        if baseline == "grid_only":
            # Nothing installed at all: the whole load bought from the utility.
            baseline_net = load_kwh
        else:
            # Same PV, no battery.
            baseline_net = load_kwh - pv_kwh

        baseline_cost = (
            max(baseline_net, 0.0) * price.import_price
            - max(-baseline_net, 0.0) * price.export_price
        )
        return baseline_cost - actual_cost

    def _breakdown(
        self,
        start: dt.datetime,
        tariff,
        *,
        grid_import: float,
        grid_export: float,
        battery_discharge: float,
        generator_kwh: float,
        battery_avg_kw: float | None,
        generator_avg_kw: float | None,
        soc_start: float | None,
        soc_end: float | None,
    ) -> list[EnergyIntervalCost]:
        """Price each source through its registered cost model.

        The totals on :class:`EnergyInterval` keep their old meaning - grid
        only - so every existing dashboard and roll-up is unaffected. This is
        the detail layer underneath them, and the only place that knows a
        generator burns fuel.

        A source with no configured model is skipped rather than priced at
        zero. A source naming a model that is not registered is a different
        matter and raises: silently free energy is the error nobody notices.
        """

        def price_at(moment: dt.datetime):
            return resolve_price(tariff, moment)

        end = start + dt.timedelta(seconds=self.interval_seconds)
        hours = self.interval_seconds / SECONDS_PER_HOUR
        rows: list[EnergyIntervalCost] = []

        sources = [
            (
                EnergyIntervalCost.Source.GRID,
                AssetRole.GRID_METER,
                grid_import,
                None,
                None,
            ),
            (
                EnergyIntervalCost.Source.BATTERY,
                AssetRole.BATTERY,
                battery_discharge,
                battery_avg_kw,
                None,
            ),
            (
                EnergyIntervalCost.Source.GENERATOR,
                AssetRole.GENERATOR,
                generator_kwh,
                generator_avg_kw,
                hours if generator_kwh > 0 else 0.0,
            ),
        ]

        for source, role, energy_kwh, avg_kw, running_hours in sources:
            if energy_kwh <= 0:
                continue
            asset = next((item for item in self.assets if item.role == role), None)
            if asset is None:
                continue
            key = costs.model_for(asset, role)
            if not key:
                continue

            result = costs.compute(
                key,
                costs.CostContext(
                    start=start,
                    end=end,
                    interval_seconds=self.interval_seconds,
                    energy_kwh=energy_kwh,
                    price_at=price_at,
                    asset=asset,
                    plan=self.plan,
                    avg_kw=avg_kw,
                    soc_start=soc_start,
                    soc_end=soc_end,
                    running_hours=running_hours,
                ),
            )
            rows.append(
                EnergyIntervalCost(
                    source=source,
                    cost_model=result.cost_model,
                    energy_kwh=round(energy_kwh, 6),
                    amount=round(result.amount, 6),
                    currency=result.currency,
                    unit_cost=result.unit_cost_per_kwh,
                    breakdown=result.breakdown,
                    basis=result.basis,
                )
            )

        if grid_export > 0:
            asset = next(
                (item for item in self.assets if item.role == AssetRole.GRID_METER),
                None,
            )
            if asset is not None:
                result = costs.compute(
                    "grid_export",
                    costs.CostContext(
                        start=start,
                        end=end,
                        interval_seconds=self.interval_seconds,
                        energy_kwh=grid_export,
                        price_at=price_at,
                        asset=asset,
                        plan=self.plan,
                    ),
                )
                # Folded into the grid row rather than added as a second one:
                # the unique constraint is (interval, source), and two grid
                # lines would also read as double counting.
                existing = next(
                    (row for row in rows if row.source == EnergyIntervalCost.Source.GRID),
                    None,
                )
                if existing is None:
                    rows.append(
                        EnergyIntervalCost(
                            source=EnergyIntervalCost.Source.GRID,
                            cost_model=result.cost_model,
                            energy_kwh=round(grid_export, 6),
                            amount=round(result.amount, 6),
                            currency=result.currency,
                            unit_cost=result.unit_cost_per_kwh,
                            breakdown=result.breakdown,
                            basis=result.basis,
                        )
                    )
                else:
                    existing.amount = round(existing.amount + result.amount, 6)
                    existing.breakdown = {**existing.breakdown, **result.breakdown}

        return rows

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
                    "generator_kwh",
                ],
            )
            self._write_costs(rows)
        logger.info(
            "energy intervals rebuilt",
            extra={"site": self.site.name, "count": len(rows)},
        )
        return len(rows)

    def _write_costs(self, rows: list[EnergyInterval]) -> None:
        """Replace the cost breakdown for the intervals just written.

        Delete-then-insert rather than upsert: a source can *stop* applying
        between two rebuilds - an asset unbound, a cost model cleared - and an
        upsert would leave the stale row behind, still counted in every
        "what did the generators cost" query.

        ``bulk_create`` does not return primary keys on every backend, so the
        rows are re-read by their natural key. That is one extra query per
        rebuild, not per interval.
        """
        starts = [row.interval_start for row in rows]
        stored = {
            (interval.interval_start, interval.interval_seconds): interval.pk
            for interval in EnergyInterval.objects.filter(
                site=self.site,
                interval_seconds=self.interval_seconds,
                interval_start__in=starts,
            ).only("pk", "interval_start", "interval_seconds")
        }
        EnergyIntervalCost.objects.filter(interval_id__in=stored.values()).delete()

        pending: list[EnergyIntervalCost] = []
        for row in rows:
            interval_pk = stored.get((row.interval_start, row.interval_seconds))
            if interval_pk is None:
                continue
            for cost in getattr(row, "pending_costs", None) or []:
                cost.interval_id = interval_pk
                pending.append(cost)

        if pending:
            EnergyIntervalCost.objects.bulk_create(pending, batch_size=500)


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
