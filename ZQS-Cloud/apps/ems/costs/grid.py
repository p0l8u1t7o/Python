"""Utility grid: the time-of-use tariff, unchanged in meaning.

This is the model that already existed, moved behind the registry so the
settlement code has one shape for every source rather than one special case
plus a plug-in mechanism for the rest.
"""

from __future__ import annotations

from apps.ems.costs.base import CostContext, CostResult, register


@register("grid_tariff")
def grid_tariff(context: CostContext) -> CostResult:
    """Price imported energy at the tariff rate in force at interval start.

    The rate is taken once, at ``start``, rather than integrated across the
    interval. Settlement periods are defined on clock boundaries and the
    interval grid is aligned to them, so an interval straddling a rate change
    only happens with a non-standard interval width - the same limitation the
    aggregator has always had.
    """
    price = context.price_at(context.start)
    import_price = float(getattr(price, "import_price", 0.0))
    amount = context.energy_kwh * import_price
    return CostResult(
        amount=amount,
        currency=getattr(price, "currency", "TWD"),
        unit_cost_per_kwh=import_price,
        breakdown={"energy": round(amount, 6)},
        basis="measured",
    )


@register("grid_export")
def grid_export(context: CostContext) -> CostResult:
    """Feed-in compensation. Negative amount: it is money coming in."""
    price = context.price_at(context.start)
    export_price = float(getattr(price, "export_price", 0.0))
    amount = -(context.energy_kwh * export_price)
    return CostResult(
        amount=amount,
        currency=getattr(price, "currency", "TWD"),
        unit_cost_per_kwh=-export_price,
        breakdown={"export": round(amount, 6)},
        basis="measured",
    )
