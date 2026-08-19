from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from ninja import Field, Schema

from apps.ems.models import AssetRole, DispatchMode, DispatchStrategy, TariffKind


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
    #: 0.001 converts a device reporting W into the kW this module works in.
    power_scale: float = 0.001
    energy_scale: float = 1.0
    invert_sign: bool = False
    rated_power_kw: float | None = None
    rated_energy_kwh: float | None = None
    is_active: bool = True


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
    rated_power_kw: float | None
    rated_energy_kwh: float | None
    is_active: bool

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
    strategy: DispatchStrategy = DispatchStrategy.MANUAL
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
    tariff_id: uuid.UUID | None = None
    notes: str = ""


class StoragePlanOut(StoragePlanIn):
    id: uuid.UUID
    site_id: uuid.UUID
    dispatchable_capacity_kwh: float | None = None
    updated_at: dt.datetime


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
    grid_import_kwh: float = 0.0
    grid_export_kwh: float = 0.0
    pv_kwh: float = 0.0
    load_kwh: float = 0.0
    battery_charge_kwh: float = 0.0
    battery_discharge_kwh: float = 0.0
    peak_import_kw: float | None = None
    energy_cost: float = 0.0
    export_revenue: float = 0.0
    estimated_savings: float = 0.0
    self_consumption_ratio: float | None = None
    self_sufficiency_ratio: float | None = None
    #: Battery energy out divided by energy in, over the window.
    round_trip_efficiency: float | None = None
    currency: str = ""


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


SiteOverviewOut.model_rebuild()
