"""Energy roll-up across one or more sites.

Every figure the console shows for a *group* of sites is computed here, so the
two things that are easy to get wrong are wrong in at most one place.

**Peaks do not add.** A site's ``peak_import_kw`` is its highest demand inside
one settlement interval. Two plants that each peak at 300 kW do not put 600 kW
on a shared meter unless they peak at the same moment. Summing each site's
window maximum would therefore overstate the group. Instead the sites are
summed *per interval* first and the maximum is taken over those sums - the
coincident peak, resolved to the interval width.

That is an estimate, not a measurement: within a 15-minute interval the sites'
instantaneous peaks may still fall at different seconds, so the result remains
an upper bound on the true coincident peak. The response says so
(``peak_basis``) rather than pretending otherwise. A group whose members sit
behind one physical meter should be modelled as one site, and then the figure
is exact.

**Ratios do not average.** Self-consumption is PV kept on site divided by PV
generated. Averaging two sites' percentages weights a 5 kW rooftop the same as
a 5 MW array. Numerator and denominator are summed separately, then divided.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Sequence

from django.db.models import Max, Sum

from apps.ems.models import EnergyInterval, StoragePlan

#: What ``peak_import_kw`` / ``peak_load_kw`` in a roll-up mean.
PEAK_BASIS_MEASURED = "measured"
PEAK_BASIS_COINCIDENT = "coincident_estimate"


def energy_totals(
    site_ids: Sequence[Any], start: dt.datetime, end: dt.datetime
) -> dict:
    """Totals for ``site_ids`` over ``[start, end)``.

    A single id gives exactly what the per-site endpoint always gave; the
    grouped peak collapses to the plain maximum when there is only one site.
    """
    ids = [pk for pk in site_ids if pk is not None]
    intervals = EnergyInterval.objects.filter(
        site_id__in=ids, interval_start__gte=start, interval_start__lt=end
    )

    sums = intervals.aggregate(
        grid_import=Sum("grid_import_kwh"),
        grid_export=Sum("grid_export_kwh"),
        pv=Sum("pv_kwh"),
        load=Sum("load_kwh"),
        charge=Sum("battery_charge_kwh"),
        discharge=Sum("battery_discharge_kwh"),
        cost=Sum("energy_cost"),
        revenue=Sum("export_revenue"),
        savings=Sum("estimated_savings"),
    )

    peaks = coincident_peaks(intervals)

    pv_kwh = sums["pv"] or 0.0
    load_kwh = sums["load"] or 0.0
    grid_import = sums["grid_import"] or 0.0
    grid_export = sums["grid_export"] or 0.0
    charge = sums["charge"] or 0.0
    discharge = sums["discharge"] or 0.0

    return {
        "start": start,
        "end": end,
        "site_count": len(ids),
        "grid_import_kwh": round(grid_import, 3),
        "grid_export_kwh": round(grid_export, 3),
        "pv_kwh": round(pv_kwh, 3),
        "load_kwh": round(load_kwh, 3),
        "battery_charge_kwh": round(charge, 3),
        "battery_discharge_kwh": round(discharge, 3),
        "peak_import_kw": peaks["peak_import_kw"],
        "peak_load_kw": peaks["peak_load_kw"],
        "peak_basis": (
            PEAK_BASIS_MEASURED if len(ids) <= 1 else PEAK_BASIS_COINCIDENT
        ),
        "energy_cost": round(sums["cost"] or 0.0, 2),
        "export_revenue": round(sums["revenue"] or 0.0, 2),
        "estimated_savings": round(sums["savings"] or 0.0, 2),
        # Ratios: summed numerator over summed denominator, never an average
        # of per-site ratios.
        "self_consumption_ratio": _ratio(pv_kwh - grid_export, pv_kwh),
        "self_sufficiency_ratio": _ratio(load_kwh - grid_import, load_kwh),
        "round_trip_efficiency": round(discharge / charge, 4) if charge > 0 else None,
        "currency": currency_for(ids),
    }


def coincident_peaks(intervals) -> dict:
    """Highest simultaneous demand across the sites in ``intervals``.

    Sum the sites sharing an ``interval_start``, then take the largest of those
    sums. With one site this is the same number ``Max`` would have produced.
    """
    grouped = (
        intervals.values("interval_start")
        .annotate(
            import_kw=Sum("peak_import_kw"),
            load_kw=Sum("peak_load_kw"),
        )
        .aggregate(peak_import=Max("import_kw"), peak_load=Max("load_kw"))
    )
    return {
        "peak_import_kw": grouped["peak_import"],
        "peak_load_kw": grouped["peak_load"],
    }


def currency_for(site_ids: Sequence[Any]) -> str:
    """Currency shared by these sites' tariffs, or ``""`` when they disagree.

    Mixing currencies would make the cost total meaningless, so the figures are
    still returned but left unlabelled rather than silently added up as if they
    were the same money.
    """
    currencies = {
        code
        for code in StoragePlan.objects.filter(
            site_id__in=list(site_ids), tariff__isnull=False
        ).values_list("tariff__currency", flat=True)
        if code
    }
    return currencies.pop() if len(currencies) == 1 else ""


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(max(0.0, min(1.0, numerator / denominator)), 4)
