"""Behind-the-meter (BTM) energy management domain.

A site's energy picture is assembled from *asset roles*: each role says which
device and which metric supplies a particular flow (grid, PV, load, battery).
That indirection is what lets one dashboard serve heterogeneous hardware.

Sign convention used throughout:

* ``grid_power_kw``     > 0 importing from the utility, < 0 exporting.
* ``battery_power_kw``  > 0 discharging to the site, < 0 charging.
* ``pv_power_kw``       >= 0 always.
* ``load_power_kw``     >= 0 always.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Organization, User
from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel
from apps.devices.models import Device, Site


class AssetRole(models.TextChoices):
    GRID_METER = "grid_meter", _("Grid / point of common coupling meter")
    LOAD_METER = "load_meter", _("Load meter")
    PV = "pv", _("PV generation")
    BATTERY = "battery", _("Battery storage")
    EV_CHARGER = "ev_charger", _("EV charger")
    GENERATOR = "generator", _("Backup generator")


class EnergyAsset(UUIDPrimaryKeyModel, TimeStampedModel):
    """Binds a device (and its metric keys) to an energy role at a site."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="energy_assets"
    )
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="energy_assets")
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name="energy_assets"
    )
    role = models.CharField(max_length=16, choices=AssetRole.choices)
    name = models.CharField(max_length=120, blank=True)

    # ---- Metric bindings (metric keys on the bound device) ---------------
    power_metric = models.CharField(
        max_length=64, blank=True, help_text="Instantaneous power, kW after scaling."
    )
    energy_import_metric = models.CharField(
        max_length=64, blank=True, help_text="Cumulative imported/charged energy counter."
    )
    energy_export_metric = models.CharField(
        max_length=64, blank=True, help_text="Cumulative exported/discharged energy counter."
    )
    soc_metric = models.CharField(max_length=64, blank=True, help_text="Battery SOC, %.")
    soh_metric = models.CharField(max_length=64, blank=True, help_text="Battery SOH, %.")

    #: Multiplier applied to raw samples, e.g. 0.001 to turn W into kW.
    power_scale = models.FloatField(default=1.0)
    energy_scale = models.FloatField(default=1.0)
    #: Flip when the device reports the opposite sign to the convention above.
    invert_sign = models.BooleanField(default=False)

    #: Whether this measurement feeds the site's energy balance.
    #:
    #: Every flow must be measured exactly once. Several PV inverters or
    #: battery racks are physically distinct and correctly summed, but a main
    #: incomer plus a sub-meter measure the same electrons twice. Sub-metering
    #: an individual machine is genuinely useful - it gets its own charts,
    #: consumption figures and operating sessions - so the row stays, and this
    #: flag keeps it out of ``load_kwh``.
    include_in_balance = models.BooleanField(
        default=True,
        help_text=(
            "Off for sub-meters: still charted and still counted per device, "
            "but excluded from the site's energy balance."
        ),
    )

    # ---- Nameplate ------------------------------------------------------
    rated_power_kw = models.FloatField(null=True, blank=True)
    rated_energy_kwh = models.FloatField(
        null=True, blank=True, help_text="Battery usable capacity."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "ems_energy_asset"
        ordering = ["site", "role"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "device", "role"], name="uniq_asset_site_device_role"
            )
        ]
        indexes = [models.Index(fields=["organization", "site", "role"])]

    def __str__(self) -> str:
        return f"{self.name or self.device_id} [{self.role}]"

    def normalize_power(self, raw: float | None) -> float | None:
        if raw is None:
            return None
        value = raw * self.power_scale
        return -value if self.invert_sign else value


class DispatchStrategy(models.TextChoices):
    MANUAL = "manual", _("Manual / external control")
    SELF_CONSUMPTION = "self_consumption", _("Maximise self-consumption")
    PEAK_SHAVING = "peak_shaving", _("Peak shaving")
    TOU_ARBITRAGE = "tou_arbitrage", _("Time-of-use arbitrage")
    BACKUP_ONLY = "backup_only", _("Backup reserve only")


class StoragePlan(UUIDPrimaryKeyModel, TimeStampedModel):
    """Per-site BTM storage configuration and operating strategy."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="storage_plans"
    )
    site = models.OneToOneField(
        Site, on_delete=models.CASCADE, related_name="storage_plan"
    )
    strategy = models.CharField(
        max_length=20, choices=DispatchStrategy.choices, default=DispatchStrategy.MANUAL
    )
    is_enabled = models.BooleanField(default=True)

    # ---- Grid constraints ------------------------------------------------
    contract_capacity_kw = models.FloatField(
        null=True, blank=True, help_text="Contracted demand; the peak-shaving target."
    )
    peak_shaving_target_kw = models.FloatField(null=True, blank=True)
    export_limit_kw = models.FloatField(
        null=True, blank=True, help_text="0 disables export entirely."
    )

    # ---- Battery operating envelope -------------------------------------
    usable_capacity_kwh = models.FloatField(null=True, blank=True)
    max_charge_kw = models.FloatField(null=True, blank=True)
    max_discharge_kw = models.FloatField(null=True, blank=True)
    min_soc_percent = models.FloatField(default=10.0)
    max_soc_percent = models.FloatField(default=95.0)
    #: SOC held in reserve for outages; never discharged for arbitrage.
    backup_reserve_percent = models.FloatField(default=20.0)
    round_trip_efficiency = models.FloatField(default=0.90)

    tariff = models.ForeignKey(
        "ems.Tariff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plans",
    )
    notes = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "ems_storage_plan"

    def __str__(self) -> str:
        return f"{self.site_id} [{self.strategy}]"

    @property
    def dispatchable_capacity_kwh(self) -> float | None:
        """Energy available above the backup reserve."""
        if self.usable_capacity_kwh is None:
            return None
        span = max(self.max_soc_percent - self.backup_reserve_percent, 0.0)
        return self.usable_capacity_kwh * span / 100.0


class TariffKind(models.TextChoices):
    FLAT = "flat", _("Flat rate")
    TIME_OF_USE = "tou", _("Time of use")


class Tariff(UUIDPrimaryKeyModel, TimeStampedModel):
    """Energy pricing used for cost and savings reporting."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="tariffs"
    )
    name = models.CharField(max_length=120)
    kind = models.CharField(
        max_length=8, choices=TariffKind.choices, default=TariffKind.TIME_OF_USE
    )
    currency = models.CharField(max_length=8, default="TWD")
    timezone_name = models.CharField(max_length=64, default="Asia/Taipei")

    #: Charge per kW of monthly peak demand.
    demand_charge_per_kw = models.FloatField(default=0.0)
    #: Fallback price when no period matches, per kWh.
    default_import_price = models.FloatField(default=0.0)
    #: Feed-in / export compensation, per kWh.
    default_export_price = models.FloatField(default=0.0)

    #: [{"name": "peak", "months": [6,7,8,9], "weekdays": [0,1,2,3,4],
    #:   "start": "16:00", "end": "22:00", "import_price": 8.4,
    #:   "export_price": 1.2}, ...]
    periods = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "ems_tariff"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="uniq_tariff_org_name"
            )
        ]

    def __str__(self) -> str:
        return self.name


class EnergyInterval(models.Model):
    """Site-level energy balance for one settlement interval (15 min default).

    Written by the aggregation job from raw telemetry, then read directly by the
    dashboard - so a month of charts never touches the sample table.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="+", db_index=False
    )
    site = models.ForeignKey(
        Site, on_delete=models.CASCADE, related_name="energy_intervals"
    )
    interval_start = models.DateTimeField(db_index=True)
    interval_seconds = models.PositiveIntegerField(default=900)

    # ---- Energy (kWh) ----------------------------------------------------
    grid_import_kwh = models.FloatField(default=0.0)
    grid_export_kwh = models.FloatField(default=0.0)
    pv_kwh = models.FloatField(default=0.0)
    load_kwh = models.FloatField(default=0.0)
    battery_charge_kwh = models.FloatField(default=0.0)
    battery_discharge_kwh = models.FloatField(default=0.0)
    #: Backup generation. Deliberately separate from ``battery_discharge_kwh``:
    #: round-trip efficiency is discharge over charge, and a generator only ever
    #: discharges, so mixing them would report an efficiency above 1.
    generator_kwh = models.FloatField(default=0.0)

    # ---- Power (kW) ------------------------------------------------------
    peak_import_kw = models.FloatField(null=True, blank=True)
    peak_export_kw = models.FloatField(null=True, blank=True)
    avg_load_kw = models.FloatField(null=True, blank=True)
    peak_load_kw = models.FloatField(null=True, blank=True)

    # ---- Battery ---------------------------------------------------------
    soc_start_percent = models.FloatField(null=True, blank=True)
    soc_end_percent = models.FloatField(null=True, blank=True)
    min_soc_percent = models.FloatField(null=True, blank=True)
    max_soc_percent = models.FloatField(null=True, blank=True)

    # ---- Economics -------------------------------------------------------
    tariff_period = models.CharField(max_length=40, blank=True)
    import_price = models.FloatField(null=True, blank=True)
    export_price = models.FloatField(null=True, blank=True)
    energy_cost = models.FloatField(default=0.0)
    export_revenue = models.FloatField(default=0.0)
    #: Modelled cost of the same load with no battery, minus the actual cost.
    estimated_savings = models.FloatField(default=0.0)

    #: Fraction of the sample window that actually had data (0..1).
    coverage = models.FloatField(default=1.0)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ems_energy_interval"
        ordering = ["-interval_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "interval_start", "interval_seconds"],
                name="uniq_interval_site_start",
            )
        ]
        indexes = [
            models.Index(fields=["site", "-interval_start"], name="idx_interval_site_ts"),
            models.Index(fields=["organization", "-interval_start"]),
        ]

    def __str__(self) -> str:
        return f"{self.site_id} {self.interval_start:%Y-%m-%d %H:%M}"

    @property
    def self_consumption_ratio(self) -> float | None:
        """Share of PV generation consumed on site rather than exported."""
        if self.pv_kwh <= 0:
            return None
        return max(0.0, min(1.0, (self.pv_kwh - self.grid_export_kwh) / self.pv_kwh))

    @property
    def self_sufficiency_ratio(self) -> float | None:
        """Share of site load met without importing from the grid."""
        if self.load_kwh <= 0:
            return None
        return max(0.0, min(1.0, (self.load_kwh - self.grid_import_kwh) / self.load_kwh))


class DispatchMode(models.TextChoices):
    IDLE = "idle", _("Idle")
    CHARGE = "charge", _("Charge")
    DISCHARGE = "discharge", _("Discharge")
    AUTO = "auto", _("Follow strategy")


class DispatchWindow(UUIDPrimaryKeyModel, TimeStampedModel):
    """A scheduled battery instruction, e.g. "charge at 50 kW 01:00-05:00".

    The scheduler turns these into device commands; keeping them as data means
    the plan is auditable and survives a service restart.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="dispatch_windows"
    )
    site = models.ForeignKey(
        Site, on_delete=models.CASCADE, related_name="dispatch_windows"
    )
    mode = models.CharField(max_length=12, choices=DispatchMode.choices)
    target_power_kw = models.FloatField(null=True, blank=True)
    target_soc_percent = models.FloatField(null=True, blank=True)

    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    #: RFC 5545 style recurrence, e.g. "FREQ=DAILY". Empty means one-shot.
    recurrence = models.CharField(max_length=200, blank=True)

    is_enabled = models.BooleanField(default=True)
    priority = models.SmallIntegerField(
        default=0, help_text="Higher priority wins when windows overlap."
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "ems_dispatch_window"
        ordering = ["starts_at"]
        indexes = [models.Index(fields=["site", "starts_at", "ends_at"])]

    def __str__(self) -> str:
        return f"{self.site_id} {self.mode} {self.starts_at:%Y-%m-%d %H:%M}"
