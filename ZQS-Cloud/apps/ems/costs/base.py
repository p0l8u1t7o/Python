"""Cost model interface and registry.

The point of this package is that adding a new kind of equipment does not
require editing the settlement code. A cost model is registered under a key,
:class:`~apps.ems.models.EnergyAsset` names the key, and
:mod:`apps.ems.aggregator` calls whatever comes back. Nothing in the core
branches on equipment type.

A registry rather than an ``if/elif`` chain - unlike ``services.bus.factory``,
where two operator-chosen backends is the whole universe and a conditional is
honest about that. Here the set is explicitly meant to grow from outside.

Units are fixed and are not negotiable between caller and model: energy in
**kWh**, power in **kW**, money in the asset's own currency, fuel in **litres**
and fuel price in **currency per litre**. A model that wants other units
converts internally.

An unknown key raises :class:`UnknownCostModel`. It does not fall back to zero:
a cost that silently becomes free is the hardest kind of error to notice, and
it makes a generator look cheaper than the grid.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable, Protocol

from apps.core.errors import ValidationError


class UnknownCostModel(ValidationError):
    """Raised when an asset names a cost model that is not registered."""

    def __init__(self, key: str, available: list[str] | None = None) -> None:
        super().__init__(
            f"Unknown cost model '{key}'",
            code="unknown_cost_model",
            details={"cost_model": key, "available": sorted(available or [])},
        )


@dataclass(frozen=True, slots=True)
class CostContext:
    """Everything a cost model is allowed to see.

    Deliberately narrow. In particular there is no device declaration here and
    there never will be: a compromised unit that could declare its own fuel
    consumption could make itself look ten times cheaper than the grid, and an
    operator might dispatch on that. Every parameter comes from the asset row,
    which only an admin can write.
    """

    start: dt.datetime
    end: dt.datetime
    interval_seconds: int
    #: Energy this source moved in the interval, always positive.
    energy_kwh: float
    #: Grid price at a moment, so a battery model can value the energy it
    #: stored at what it cost to store.
    price_at: Callable[[dt.datetime], "object"]
    asset: object | None = None
    plan: object | None = None
    avg_kw: float | None = None
    peak_kw: float | None = None
    soc_start: float | None = None
    soc_end: float | None = None
    #: Hours the equipment actually ran, for per-hour maintenance terms.
    running_hours: float | None = None

    @property
    def parameters(self) -> dict:
        return dict(getattr(self.asset, "cost_parameters", None) or {})

    def parameter(self, name: str, default=None):
        return self.parameters.get(name, default)


@dataclass(frozen=True, slots=True)
class CostResult:
    """What a cost model concluded.

    ``amount`` is positive for a cost and negative for a revenue. ``basis``
    tells the reader how much to trust it, and ``unknown`` is a legitimate
    answer - see the counter-reset handling in :mod:`apps.telemetry.energy`
    for the same principle.
    """

    amount: float
    currency: str = "TWD"
    unit_cost_per_kwh: float | None = None
    breakdown: dict[str, float] = field(default_factory=dict)
    basis: str = "estimated"
    #: The key that produced this, filled in by :func:`compute`.
    cost_model: str = ""


class CostModel(Protocol):
    """Prices one source's output over one settlement interval."""

    def __call__(self, context: CostContext) -> CostResult: ...


_REGISTRY: dict[str, CostModel] = {}

#: Fallback when an asset does not name a model. Roles absent from this map
#: are simply not priced - an EV charger metered on the load side is already
#: inside the grid import figure, and pricing it again would double count.
ROLE_DEFAULTS: dict[str, str] = {
    "grid_meter": "grid_tariff",
    "battery": "battery_cycle",
    "generator": "diesel_fuel",
}


def register(key: str) -> Callable[[CostModel], CostModel]:
    """Decorator registering a cost model under ``key``."""

    def wrap(model: CostModel) -> CostModel:
        if key in _REGISTRY:
            raise RuntimeError(f"Cost model '{key}' is already registered")
        _REGISTRY[key] = model
        return model

    return wrap


def available() -> list[str]:
    return sorted(_REGISTRY)


def get(key: str) -> CostModel:
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise UnknownCostModel(key, available()) from exc


def model_for(asset, role: str = "") -> str | None:
    """The cost-model key for ``asset``: its own, else the role default."""
    explicit = (getattr(asset, "cost_model", "") or "").strip()
    if explicit:
        return explicit
    return ROLE_DEFAULTS.get(role or getattr(asset, "role", ""))


def compute(key: str, context: CostContext) -> CostResult:
    """Run the registered model, stamping the key onto the result."""
    result = get(key)(context)
    return CostResult(
        amount=result.amount,
        currency=result.currency,
        unit_cost_per_kwh=result.unit_cost_per_kwh,
        breakdown=dict(result.breakdown),
        basis=result.basis,
        cost_model=key,
    )
