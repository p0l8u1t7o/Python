"""Backup generator: fuel burned plus maintenance accrued.

Units are pinned here so no caller has to guess: fuel consumption is **litres
per kWh**, fuel price is **currency per litre**, maintenance is **currency per
running hour**. The first two multiplied give currency per kWh.

The known limitation is time. ``fuel_price_per_litre`` is a single current
value, so rebuilding a three-month-old interval prices it at today's fuel
price. That is written down rather than hidden; a dated parameter set is the
correct fix and is deferred deliberately - see device-classification.md §3.12.
"""

from __future__ import annotations

from apps.ems.costs.base import CostContext, CostResult, register

#: Typical for a mid-size genset at a sensible load factor. Used only when the
#: asset says nothing, and the result is then flagged ``estimated``.
DEFAULT_LITRES_PER_KWH = 0.30


@register("diesel_fuel")
def diesel_fuel(context: CostContext) -> CostResult:
    """Cost of ``energy_kwh`` generated.

    Parameters on ``EnergyAsset.cost_parameters``:

    ``fuel_price_per_litre``   currency / litre
    ``litres_per_kwh``         flat consumption figure
    ``fuel_curve``             ``[[load_fraction, litres_per_kwh], ...]``,
                               interpolated on the interval's load factor;
                               takes precedence over the flat figure
    ``maintenance_per_hour``   currency / running hour
    """
    price_per_litre = float(context.parameter("fuel_price_per_litre", 0.0) or 0.0)
    litres_per_kwh, curve_used = _consumption(context)

    fuel = context.energy_kwh * litres_per_kwh * price_per_litre

    hours = context.running_hours
    if hours is None:
        hours = context.interval_seconds / 3600.0 if context.energy_kwh > 0 else 0.0
    maintenance = hours * float(context.parameter("maintenance_per_hour", 0.0) or 0.0)

    amount = fuel + maintenance
    declared = context.parameter("litres_per_kwh") is not None or curve_used
    return CostResult(
        amount=amount,
        currency=getattr(context.price_at(context.start), "currency", "TWD"),
        unit_cost_per_kwh=(
            amount / context.energy_kwh if context.energy_kwh > 0 else None
        ),
        breakdown={
            "fuel": round(fuel, 6),
            "maintenance": round(maintenance, 6),
            "litres": round(context.energy_kwh * litres_per_kwh, 4),
        },
        # A default consumption figure is a guess about someone else's engine.
        basis="measured" if declared and price_per_litre else "estimated",
    )


def _consumption(context: CostContext) -> tuple[float, bool]:
    """Litres per kWh, from the load curve when the asset carries one."""
    curve = context.parameter("fuel_curve")
    rating = getattr(context.asset, "rated_power_kw", None)
    if isinstance(curve, list) and curve and rating:
        avg_kw = context.avg_kw
        if avg_kw is None and context.interval_seconds:
            avg_kw = context.energy_kwh / (context.interval_seconds / 3600.0)
        if avg_kw:
            return _interpolate(curve, min(max(avg_kw / rating, 0.0), 1.0)), True

    flat = context.parameter("litres_per_kwh")
    return (float(flat) if flat is not None else DEFAULT_LITRES_PER_KWH), False


def _interpolate(curve: list, load_fraction: float) -> float:
    """Linear interpolation over ``[[load, l/kWh], ...]``, clamped at both ends."""
    points = sorted(
        (float(row[0]), float(row[1]))
        for row in curve
        if isinstance(row, (list, tuple)) and len(row) >= 2
    )
    if not points:
        return DEFAULT_LITRES_PER_KWH
    if load_fraction <= points[0][0]:
        return points[0][1]
    if load_fraction >= points[-1][0]:
        return points[-1][1]

    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= load_fraction <= x1:
            if x1 == x0:
                return y1
            return y0 + (load_fraction - x0) / (x1 - x0) * (y1 - y0)
    return points[-1][1]
