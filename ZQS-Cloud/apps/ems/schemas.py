from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from ninja import Field, Schema

from apps.ems.models import (
    ExpiryPolicy,
    AssetRole,
    DispatchMode,
    DispatchStrategy,
    SavingsBaseline,
    TariffKind,
)


# --------------------------------------------------------------------------
# Energy assets
# --------------------------------------------------------------------------
class EnergyAssetIn(Schema):
    site_id: uuid.UUID
    device_id: uuid.UUID
    role: AssetRole
    name: str = Field(default="", max_length=120)
    power_metric: str = Field(default="", max_length=64)
    energy_import_metric: str = Field(default="", max_length=64)
    energy_export_metric: str = Field(default="", max_length=64)
    soc_metric: str = Field(default="", max_length=64)
    soh_metric: str = Field(default="", max_length=64)
    #: W6：關口電表的電壓 metric，停電偵測讀它。
    voltage_metric: str = Field(default="", max_length=64)
    #: 0.001 converts a device reporting W into the kW this module works in.
    power_scale: float = 0.001
    energy_scale: float = 1.0
    invert_sign: bool = False
    #: False keeps the asset out of the site's energy balance (a sub-meter
    #: whose load is already inside the grid meter, for instance).
    include_in_balance: bool = True
    rated_power_kw: float | None = None
    rated_energy_kwh: float | None = None
    is_active: bool = True
    #: Operating-session detection (charge / discharge / running sessions).
    session_tracking_enabled: bool = False
    session_enter_kw: float | None = None
    session_exit_kw: float | None = None
    session_min_duration_s: int = Field(default=60, ge=0)
    session_gap_s: int = Field(default=300, ge=0)
    #: Registered cost model key; blank means the role's default.
    cost_model: str = Field(default="", max_length=40)
    cost_parameters: dict[str, Any] = Field(default_factory=dict)


class EnergyAssetOut(Schema):
    id: uuid.UUID
    site_id: uuid.UUID
    device_id: uuid.UUID
    device_external_id: str = ""
    device_name: str = ""
    role: AssetRole
    name: str
    power_metric: str
    energy_import_metric: str
    energy_export_metric: str
    soc_metric: str
    soh_metric: str
    power_scale: float
    energy_scale: float
    invert_sign: bool
    include_in_balance: bool = True
    rated_power_kw: float | None
    rated_energy_kwh: float | None
    is_active: bool
    session_tracking_enabled: bool = False
    session_enter_kw: float | None = None
    session_exit_kw: float | None = None
    session_min_duration_s: int = 60
    session_gap_s: int = 300
    cost_model: str = ""
    cost_parameters: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def resolve_device_external_id(obj) -> str:
        return obj.device.device_id

    @staticmethod
    def resolve_device_name(obj) -> str:
        return obj.device.name


# --------------------------------------------------------------------------
# Storage plan
# --------------------------------------------------------------------------
class StoragePlanIn(Schema):
    name: str = Field(max_length=120)
    strategy: DispatchStrategy = DispatchStrategy.MANUAL
    #: 疊加的策略（W5）。主策略 ``strategy`` 自動包含；只能疊加
    #: demand_cap / tou_arbitrage / self_consumption / backup_only。
    strategies: list[DispatchStrategy] = Field(default_factory=list)
    is_enabled: bool = True
    contract_capacity_kw: float | None = Field(default=None, ge=0)
    peak_shaving_target_kw: float | None = Field(default=None, ge=0)
    export_limit_kw: float | None = Field(default=None, ge=0)
    usable_capacity_kwh: float | None = Field(default=None, ge=0)
    max_charge_kw: float | None = Field(default=None, ge=0)
    max_discharge_kw: float | None = Field(default=None, ge=0)
    min_soc_percent: float = Field(default=10.0, ge=0, le=100)
    max_soc_percent: float = Field(default=95.0, ge=0, le=100)
    backup_reserve_percent: float = Field(default=20.0, ge=0, le=100)
    round_trip_efficiency: float = Field(default=0.90, gt=0, le=1)
    demand_cap_target_kw: float | None = Field(default=None, ge=0)
    offpeak_recharge: bool = True
    min_price_spread: float = Field(default=1.0, ge=0)
    max_cycles_per_day: float | None = Field(default=None, gt=0)
    temperature_max_c: float | None = Field(default=None)
    temperature_metric: str = ""
    tariff_id: uuid.UUID | None = None
    #: Required when the strategy is ``workflow``; ignored otherwise.
    workflow_id: uuid.UUID | None = None
    #: What "savings" is measured against. Absent from this schema the console
    #: could show the control but never save or read it, which is worse than
    #: not offering it at all.
    savings_baseline: SavingsBaseline = SavingsBaseline.NO_STORAGE
    #: Whether the operating envelope is a hard gate on dispatch or just a
    #: number on a settings page.
    enforce_limits: bool = True
    # ---- Edge fail-safe (W6) ------------------------------------------------
    setpoint_ttl_seconds: int = Field(default=300, ge=0, le=86400)
    on_expiry: ExpiryPolicy = ExpiryPolicy.IDLE
    heartbeat_interval_seconds: int = Field(default=60, ge=10, le=3600)
    heartbeat_miss_limit: int = Field(default=3, ge=1, le=20)
    offline_policy: ExpiryPolicy = ExpiryPolicy.RESERVE
    outage_voltage_min_v: float | None = Field(default=None, ge=0)
    outage_for_seconds: int = Field(default=5, ge=0, le=3600)
    notes: str = ""


class BoundSiteOut(Schema):
    id: uuid.UUID
    name: str


class StoragePlanOut(StoragePlanIn):
    id: uuid.UUID
    dispatchable_capacity_kwh: float | None = None
    updated_at: dt.datetime
    #: Set on the per-site endpoint when the plan comes from an ancestor:
    #: the ancestor's name. ``None`` means the site's own binding.
    inherited_from: str | None = None
    #: Sites currently driven by this plan.
    sites: list[BoundSiteOut] = Field(default_factory=list)


class StoragePlanBindIn(Schema):
    """Bind a site to a plan; ``null`` unbinds it."""

    plan_id: uuid.UUID | None = None


class DemandResponseIn(Schema):
    """Trigger a DR event: discharge ``target_power_kw`` for ``duration_minutes``."""

    target_power_kw: float = Field(gt=0)
    duration_minutes: int = Field(default=60, ge=1, le=24 * 60)
    #: Optional delayed start; default is now.
    starts_at: dt.datetime | None = None
    note: str = Field(default="", max_length=300)


class DemandResponseOut(Schema):
    id: uuid.UUID
    site_id: uuid.UUID
    starts_at: dt.datetime
    ends_at: dt.datetime
    target_power_kw: float
    cancelled_at: dt.datetime | None = None
    note: str
    source: str
    created_at: dt.datetime
    #: Live right now, resolved server-side so every client agrees.
    is_active: bool = False


# --------------------------------------------------------------------------
# Tariffs
# --------------------------------------------------------------------------
class TariffIn(Schema):
    name: str = Field(max_length=120)
    kind: TariffKind = TariffKind.TIME_OF_USE
    currency: str = Field(default="TWD", max_length=8)
    timezone_name: str = "Asia/Taipei"
    demand_charge_per_kw: float = Field(default=0.0, ge=0)
    default_import_price: float = Field(default=0.0, ge=0)
    default_export_price: float = Field(default=0.0, ge=0)
    periods: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True


class TariffOut(TariffIn):
    id: uuid.UUID
    created_at: dt.datetime


class TariffPresetOut(Schema):
    """A bundled tariff table the operator can apply and then edit."""

    key: str
    name: str
    description: str
    #: The Taipower tariff year the numbers came from - shown so a stale
    #: table is visible, not silent.
    tariff_year: str
    tariff: dict[str, Any]


# --------------------------------------------------------------------------
# Live overview
# --------------------------------------------------------------------------
class PowerFlowOut(Schema):
    """Instantaneous site power balance, in kW."""

    grid_kw: float | None = None
    pv_kw: float | None = None
    load_kw: float | None = None
    battery_kw: float | None = None
    battery_soc_percent: float | None = None
    battery_soh_percent: float | None = None
    #: Newest sample timestamp contributing to this snapshot.
    as_of: dt.datetime | None = None
    is_stale: bool = False


class SiteOverviewOut(Schema):
    site_id: uuid.UUID
    site_name: str
    strategy: DispatchStrategy | None = None
    contract_capacity_kw: float | None = None
    usable_capacity_kwh: float | None = None
    flow: PowerFlowOut
    today: "EnergyTotalsOut"
    device_count: int = 0
    online_count: int = 0
    open_alert_count: int = 0


class EnergyTotalsOut(Schema):
    start: dt.datetime
    end: dt.datetime
    #: How many sites went into these figures; 1 for a plain per-site query.
    site_count: int = 1
    grid_import_kwh: float = 0.0
    grid_export_kwh: float = 0.0
    pv_kwh: float = 0.0
    load_kwh: float = 0.0
    battery_charge_kwh: float = 0.0
    battery_discharge_kwh: float = 0.0
    peak_import_kw: float | None = None
    peak_load_kw: float | None = None
    #: ``measured`` for one site. ``coincident_estimate`` once several sites are
    #: combined: the sites are summed per interval and the largest of those sums
    #: is reported, which is an upper bound on the true simultaneous peak.
    #: Never the sum of each site's own peak, which would overstate it.
    peak_basis: str = "measured"
    energy_cost: float = 0.0
    export_revenue: float = 0.0
    estimated_savings: float = 0.0
    self_consumption_ratio: float | None = None
    self_sufficiency_ratio: float | None = None
    #: Battery energy out divided by energy in, over the window.
    round_trip_efficiency: float | None = None
    currency: str = ""


class SiteCostOut(Schema):
    """One site's line in the cost overview."""

    site_id: uuid.UUID
    site_name: str
    parent_id: uuid.UUID | None = None
    depth: int = 0
    energy_cost: float = 0.0
    export_revenue: float = 0.0
    #: Difference against the plan's baseline. Negative means the dispatch
    #: cost more than the baseline would have; it is never clamped to zero.
    estimated_savings: float = 0.0
    grid_import_kwh: float = 0.0
    load_kwh: float = 0.0
    device_count: int = 0
    currency: str = ""
    #: Capacity side of the bill. Highest interval demand in the window, as
    #: metered and as it would have been with the battery idle, and the
    #: demand charge (plus excess penalty) the difference is worth at the
    #: plan tariff's monthly rate.
    peak_demand_kw: float | None = None
    baseline_peak_kw: float | None = None
    contract_capacity_kw: float | None = None
    demand_charge_per_kw: float = 0.0
    demand_savings: float = 0.0
    penalty_avoided: float = 0.0


class CostOverviewOut(Schema):
    """Cost and savings for every site of the tenant, over one window.

    ``currency`` is the shared code when every site agrees and ``""`` when they
    do not - in which case ``total_*`` are still returned but must not be shown
    as a single money figure. Per-site rows carry their own currency.
    """

    start: dt.datetime
    end: dt.datetime
    currency: str = ""
    total_energy_cost: float = 0.0
    total_export_revenue: float = 0.0
    total_estimated_savings: float = 0.0
    total_demand_savings: float = 0.0
    #: True when the sites do not share one currency, so totals are unlabelled.
    mixed_currency: bool = False
    sites: list[SiteCostOut] = Field(default_factory=list)


class SiteLiveOut(Schema):
    """One site's current state, for the overview table."""

    site_id: uuid.UUID
    site_name: str
    parent_id: uuid.UUID | None = None
    depth: int = 0
    flow: PowerFlowOut
    device_count: int = 0
    online_count: int = 0
    open_alert_count: int = 0
    #: Today so far, in the *site's* timezone - not the reader's, because a
    #: plant's day is the plant's day.
    today_load_kwh: float = 0.0
    today_energy_cost: float = 0.0
    today_estimated_savings: float | None = None
    currency: str = ""
    #: 需量狀態（地圖著色）：over / high / watch / balanced / exporting / unknown。
    demand_status: str = "unknown"
    demand_ceiling_kw: float | None = None
    contract_capacity_kw: float | None = None
    #: True when no asset at this site has reported recently. The row still
    #: appears - a site that has gone quiet is exactly what an overview should
    #: show, rather than dropping it.
    is_stale: bool = True


class FleetLiveOut(Schema):
    """Live energy across every site the caller can see.

    ``totals`` sums the per-site flows. Power *does* add across sites at the
    same instant - unlike peak demand, which does not, and which is why this
    schema deliberately carries no peak figure.
    """

    as_of: dt.datetime | None = None
    totals: PowerFlowOut
    #: Capacity-weighted mean SOC, so a 1 MWh pack does not count the same as
    #: a 10 kWh one. Null when no battery reported.
    battery_soc_percent: float | None = None
    site_count: int = 0
    reporting_site_count: int = 0
    currency: str = ""
    mixed_currency: bool = False
    today_energy_cost: float = 0.0
    today_estimated_savings: float = 0.0
    today_load_kwh: float = 0.0
    today_pv_kwh: float = 0.0
    sites: list[SiteLiveOut] = Field(default_factory=list)


class DeviceInvestmentOut(Schema):
    device_id: uuid.UUID
    device_name: str = ""
    device_external_id: str = ""
    category: str = ""
    capital_cost: float | None = None
    annual_cost: float | None = None
    commissioned_on: dt.date | None = None
    expected_life_years: float | None = None


class SiteInvestmentOut(Schema):
    """What the equipment at a site cost, and what that works out to per year.

    Kept out of :class:`EnergyIntervalCost` on purpose. Capital is not a cost
    *of moving energy* - folding an amortised purchase price into the same
    column as a fuel bill would make "what did this interval cost" mean two
    different things at once, and double count against the battery cycle
    charge, which is already the capital cost expressed per kWh of throughput.
    """

    site_id: uuid.UUID
    start: dt.datetime
    end: dt.datetime
    currency: str = ""
    total_capital_cost: float = 0.0
    total_annual_cost: float = 0.0
    #: Annual cost apportioned to the window, so it can sit next to the energy
    #: cost for the same window without either being rescaled by the reader.
    window_amortised_cost: float = 0.0
    #: Devices at this site with no cost recorded. Reported rather than
    #: silently treated as free, which would flatter every payback figure.
    devices_without_cost: int = 0
    devices: list[DeviceInvestmentOut] = Field(default_factory=list)


class EnergyIntervalOut(Schema):
    interval_start: dt.datetime
    interval_seconds: int
    grid_import_kwh: float
    grid_export_kwh: float
    pv_kwh: float
    load_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    peak_import_kw: float | None
    avg_load_kw: float | None
    soc_start_percent: float | None
    soc_end_percent: float | None
    tariff_period: str
    import_price: float | None
    energy_cost: float
    export_revenue: float
    estimated_savings: float
    coverage: float


# --------------------------------------------------------------------------
# Operating sessions
# --------------------------------------------------------------------------
class OperatingSessionOut(Schema):
    """One stretch of a device charging, discharging or running."""

    id: int
    device_id: uuid.UUID
    device_name: str = ""
    device_external_id: str = ""
    site_id: uuid.UUID | None = None
    kind: str
    started_at: dt.datetime
    #: Null means still in progress. For equipment that runs continuously this
    #: is the correct answer, not a missing value.
    ended_at: dt.datetime | None = None
    duration_s: int | None = None
    energy_kwh: float = 0.0
    peak_kw: float | None = None
    avg_kw: float | None = None
    start_soc_percent: float | None = None
    end_soc_percent: float | None = None
    end_reason: str = ""

    @staticmethod
    def resolve_device_name(obj) -> str:
        return obj.device.name

    @staticmethod
    def resolve_device_external_id(obj) -> str:
        return obj.device.device_id

    @staticmethod
    def resolve_site_id(obj):
        return obj.device.site_id


class SessionSummaryOut(Schema):
    """How often, how long and how much - per session kind."""

    kind: str
    count: int = 0
    total_energy_kwh: float = 0.0
    total_duration_s: int = 0
    avg_duration_s: float | None = None
    max_peak_kw: float | None = None
    last_started_at: dt.datetime | None = None
    open_count: int = 0


class IntervalCostOut(Schema):
    """One source's share of an interval's cost."""

    source: str
    cost_model: str = ""
    energy_kwh: float = 0.0
    #: Positive is a cost, negative a revenue. Never clamped at zero.
    amount: float = 0.0
    currency: str = ""
    unit_cost: float | None = None
    breakdown: dict[str, Any] = Field(default_factory=dict)
    basis: str = "estimated"


class CostBreakdownRowOut(Schema):
    source: str
    cost_model: str = ""
    energy_kwh: float = 0.0
    amount: float = 0.0
    unit_cost: float | None = None
    #: Worst basis across the intervals folded in: one estimated interval
    #: makes the total an estimate.
    basis: str = "estimated"


class CostBreakdownOut(Schema):
    """Where a site's money went over a window, by source."""

    site_id: uuid.UUID
    start: dt.datetime
    end: dt.datetime
    currency: str = ""
    total_amount: float = 0.0
    rows: list[CostBreakdownRowOut] = Field(default_factory=list)
    #: Intervals whose savings could not be computed - an outage, or a plan
    #: that asks for no baseline. Counted rather than hidden.
    unknown_savings_intervals: int = 0


class CostModelOut(Schema):
    key: str
    #: The roles this key is the default for, if any.
    default_for: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Dispatch windows
# --------------------------------------------------------------------------
class DispatchWindowIn(Schema):
    site_id: uuid.UUID
    mode: DispatchMode
    target_power_kw: float | None = Field(default=None, ge=0)
    target_soc_percent: float | None = Field(default=None, ge=0, le=100)
    starts_at: dt.datetime
    ends_at: dt.datetime
    recurrence: str = Field(default="", max_length=200)
    is_enabled: bool = True
    priority: int = Field(default=0, ge=-100, le=100)
    notes: str = Field(default="", max_length=300)


class DispatchWindowOut(DispatchWindowIn):
    id: uuid.UUID
    created_at: dt.datetime


class DispatchDecisionOut(Schema):
    """What the dispatch engine would do for one site right now."""

    site_id: uuid.UUID
    site_name: str = ""
    device_id: uuid.UUID | None = None
    device_external_id: str = ""
    #: Watts. Negative charges, positive discharges. Null means the engine has
    #: nothing to say - no window, or a mode that names no setpoint.
    power_w: float | None = None
    window_id: uuid.UUID | None = None
    reason: str = ""
    #: Set when the window asked for more than the storage plan allows.
    clamped_from_w: float | None = None
    #: Why nothing was sent, when nothing was: ``unchanged``, ``no_window``,
    #: ``plan_disabled``, or the error code of a refused command.
    skipped: str = ""


SiteOverviewOut.model_rebuild()


class MonthlySettlementOut(Schema):
    """一個場域一個計費月的結算（W4）。``savings`` 可為負、無基準線時為 null。"""

    id: uuid.UUID
    site_id: uuid.UUID
    billing_month: dt.date
    period_start: dt.datetime
    period_end: dt.datetime
    currency: str
    peak_demand_kw: float | None
    peak_occurred_at: dt.datetime | None
    baseline_peak_kw: float | None
    contract_capacity_kw: float | None
    energy_charge: float
    demand_charge: float
    excess_penalty: float
    export_revenue: float
    total: float
    baseline_total: float | None
    savings: float | None
    basis: str
    interval_count: int
    coverage: float
    finalized_at: dt.datetime | None
    computed_at: dt.datetime
    tariff_snapshot: dict[str, Any]
