"""Demand-charge benefit: what the battery did to the bill's other half.

Taiwan's industrial bill is two numbers: energy (kWh x price) and capacity
(the month's highest 15-minute demand x a per-kW rate, with a penalty when
that demand exceeds the contract). ``estimated_savings`` on the intervals
covers the first. This covers the second, which for a behind-the-meter
battery on a demand-cap plan is usually the larger of the two.

Per site over a window:

* ``peak_demand_kw`` - highest interval import demand the meter recorded.
* ``baseline_peak_kw`` - what it would have been with the battery idle, i.e.
  the highest ``load - pv`` interval. Same baseline as the energy figure.
* ``demand_savings`` - (baseline peak - actual peak) x demand charge, plus
  the excess penalty the battery avoided.

The penalty follows Taipower's rule: the part of peak demand over the
contract is billed at 2x the rate up to 10% over, 3x beyond. The window is
whatever the caller asked for; the rate is monthly, so the figure reads as
"this window's peak, priced at the monthly rate" - exact for a calendar
month, an estimate otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Taipower: excess within 10% of the contract at 2x, beyond that at 3x.
PENALTY_TIER_1 = 2.0
PENALTY_TIER_2 = 3.0
TIER_1_BAND = 0.10


def excess_charge(peak_kw: float, contract_kw: float, rate_per_kw: float) -> float:
    """The capacity penalty for one month's peak over the contract."""
    if contract_kw <= 0 or rate_per_kw <= 0:
        return 0.0
    excess = max(peak_kw - contract_kw, 0.0)
    if excess <= 0:
        return 0.0
    band = contract_kw * TIER_1_BAND
    tier_1 = min(excess, band)
    tier_2 = max(excess - band, 0.0)
    return tier_1 * rate_per_kw * PENALTY_TIER_1 + tier_2 * rate_per_kw * PENALTY_TIER_2


@dataclass(frozen=True)
class DemandBenefit:
    peak_demand_kw: float | None
    baseline_peak_kw: float | None
    contract_capacity_kw: float | None
    demand_charge_per_kw: float
    #: Demand charge avoided by the lower peak, penalty included.
    demand_savings: float
    #: The part of ``demand_savings`` that is avoided excess penalty.
    penalty_avoided: float

    def as_dict(self) -> dict:
        return {
            "peak_demand_kw": None if self.peak_demand_kw is None else round(self.peak_demand_kw, 1),
            "baseline_peak_kw": None if self.baseline_peak_kw is None else round(self.baseline_peak_kw, 1),
            "contract_capacity_kw": self.contract_capacity_kw,
            "demand_charge_per_kw": self.demand_charge_per_kw,
            "demand_savings": round(self.demand_savings, 2) + 0.0,
            "penalty_avoided": round(self.penalty_avoided, 2) + 0.0,
        }


def demand_benefit(
    *,
    peak_demand_kw: float | None,
    baseline_peak_kw: float | None,
    contract_capacity_kw: float | None,
    demand_charge_per_kw: float | None,
) -> DemandBenefit:
    rate = float(demand_charge_per_kw or 0.0)
    contract = float(contract_capacity_kw) if contract_capacity_kw else None
    if peak_demand_kw is None or baseline_peak_kw is None or rate <= 0:
        return DemandBenefit(peak_demand_kw, baseline_peak_kw, contract, rate, 0.0, 0.0)

    # The billed demand is the peak, but never below zero; an exporting site
    # has no capacity charge to save on.
    actual = max(peak_demand_kw, 0.0)
    baseline = max(baseline_peak_kw, 0.0)
    charge_saved = (baseline - actual) * rate
    penalty = 0.0
    if contract:
        penalty = excess_charge(baseline, contract, rate) - excess_charge(actual, contract, rate)
    return DemandBenefit(
        peak_demand_kw, baseline_peak_kw, contract, rate, charge_saved + penalty, penalty
    )
