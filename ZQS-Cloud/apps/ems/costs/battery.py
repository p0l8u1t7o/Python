"""Battery: cycle wear plus the cost of the energy that went in.

Discharging is not free even though nothing is burned. Two things are spent:

* **Cycle life.** A pack has a warranted throughput; every kWh through it uses
  a slice of that. The unit figure is purchase price divided by warranted
  throughput - a commercial number off the supply contract, which is why it
  lives on the asset and not on the blueprint.
* **The energy itself.** A kWh discharged was bought earlier, at whatever the
  tariff was then, and lost some of itself to round-trip inefficiency on the
  way in. Ignoring that makes arbitrage look free.
"""

from __future__ import annotations

import datetime as dt

from apps.ems.costs.base import CostContext, CostResult, register

#: Assumed when neither the asset nor the storage plan says otherwise.
DEFAULT_ROUND_TRIP = 0.90

#: How far back to look for the price the stored energy was bought at. Half a
#: day covers the overnight-charge / afternoon-discharge cycle that
#: time-of-use arbitrage is built around.
CHARGE_LOOKBACK_HOURS = 12


def _cycle_cost(context: CostContext) -> float:
    """Currency per kWh of throughput.

    Taken from ``cycle_cost_per_kwh`` when an operator has worked it out. When
    they have not, it is derived from what the pack actually cost: purchase
    price divided by warranted throughput is the same number, and the device
    row already carries the price.

    Deriving it rather than defaulting to zero matters. Zero says discharging
    wears nothing out, which makes arbitrage look free and is the reason a
    payback figure comes out too good. Both inputs have to be present, though
    - guessing a warranty from a nameplate would be inventing the contract.
    """
    explicit = context.parameter("cycle_cost_per_kwh")
    if explicit is not None:
        return float(explicit)

    throughput = context.parameter("warranted_throughput_kwh")
    device = getattr(context.asset, "device", None)
    capital = getattr(device, "capital_cost", None)
    if throughput and capital:
        return float(capital) / float(throughput)
    return 0.0


@register("battery_cycle")
def battery_cycle(context: CostContext) -> CostResult:
    """Cost of discharging ``energy_kwh`` from this battery.

    Parameters, all on ``EnergyAsset.cost_parameters``:

    ``cycle_cost_per_kwh``
        Currency per kWh of throughput: pack price / warranted throughput.
    ``warranted_throughput_kwh``
        Total kWh the supplier warrants. With it, ``cycle_cost_per_kwh`` is
        derived from the device's own ``capital_cost`` and need not be
        computed by hand.
    ``round_trip_efficiency``
        Overrides the storage plan's figure for this particular pack.
    ``charge_price_per_kwh``
        Fixed price for the stored energy. Without it, the tariff rate
        ``CHARGE_LOOKBACK_HOURS`` before the interval stands in - an estimate,
        and reported as one.
    """
    cycle_cost = _cycle_cost(context)
    efficiency = float(
        context.parameter("round_trip_efficiency", None)
        or getattr(context.plan, "round_trip_efficiency", None)
        or DEFAULT_ROUND_TRIP
    )
    efficiency = min(max(efficiency, 0.05), 1.0)

    wear = context.energy_kwh * cycle_cost

    fixed_price = context.parameter("charge_price_per_kwh", None)
    if fixed_price is not None:
        charge_price = float(fixed_price)
        basis = "measured"
    else:
        moment = context.start - dt.timedelta(hours=CHARGE_LOOKBACK_HOURS)
        charge_price = float(getattr(context.price_at(moment), "import_price", 0.0))
        basis = "estimated"

    # Discharging one kWh took 1/efficiency kWh at the meter to store.
    energy_cost = context.energy_kwh / efficiency * charge_price
    amount = wear + energy_cost

    return CostResult(
        amount=amount,
        currency=getattr(context.price_at(context.start), "currency", "TWD"),
        unit_cost_per_kwh=(
            amount / context.energy_kwh if context.energy_kwh > 0 else None
        ),
        breakdown={
            "cycle_wear": round(wear, 6),
            "stored_energy": round(energy_cost, 6),
        },
        basis=basis,
    )
