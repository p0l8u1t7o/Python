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

    # ---- Operating-session detection -------------------------------------
    #: The parameters live here rather than on the device because they are
    #: read in the *normalised* frame: ``power_scale`` and ``invert_sign``
    #: already say how this device's power reading is to be interpreted, and
    #: "is it charging" is a question about that same normalised value.
    #:
    #: ``enter`` above ``exit`` gives hysteresis. A single threshold applied to
    #: a load that idles near it produces thousands of one-sample sessions;
    #: two thresholds do not.
    session_tracking_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Detect charge / discharge / running sessions for this asset. "
            "Off by default for loads: a circuit that always draws power has "
            "one session that never ends, which carries no information."
        ),
    )
    session_enter_kw = models.FloatField(
        null=True, blank=True, help_text="Above this, a session starts. Null = 2% of rating."
    )
    session_exit_kw = models.FloatField(
        null=True, blank=True, help_text="Below this, it ends. Null = half of enter."
    )
    session_min_duration_s = models.PositiveIntegerField(
        default=60,
        help_text="Shorter sessions are discarded - a motor's inrush is not a discharge.",
    )
    session_gap_s = models.PositiveIntegerField(
        default=300,
        help_text="No samples for this long closes the session at the last sample.",
    )

    # ---- Cost model ------------------------------------------------------
    #: Which :mod:`apps.ems.costs` model prices this asset's output.
    #:
    #: Deliberately per-asset rather than per-category: two generators at one
    #: site may be priced differently - one from a measured fuel curve, one
    #: from a flat litres-per-kWh figure - and that is a commercial decision,
    #: not a property of the model of engine. Null falls back to the default
    #: for the asset's role.
    cost_model = models.CharField(
        max_length=40,
        blank=True,
        help_text="Registered cost model key; blank uses the role default.",
    )
    #: Model parameters, e.g. {"fuel_price_per_litre": 32.0,
    #: "litres_per_kwh": 0.28, "maintenance_per_hour": 40.0,
    #: "cycle_cost_per_kwh": 1.8}. Read by the cost model, never by ingest.
    #:
    #: Known limitation: a single current value, so rebuilding an old interval
    #: prices it with today's fuel price. A dated CostParameterSet is the
    #: correct fix and is deliberately deferred - see device-classification.md
    #: §3.12.
    cost_parameters = models.JSONField(default=dict, blank=True)

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


class SavingsBaseline(models.TextChoices):
    """What "savings" is measured against.

    The number is a comparison, so it is meaningless without saying to what.
    ``grid_only`` credits the whole installation; ``no_storage`` isolates what
    the battery earned, which is what a payback calculation needs.

    ``none`` exists because sometimes no baseline is honest: during an outage
    there is no counterfactual price at all, and inventing one would put a
    fabricated saving in a report.
    """

    GRID_ONLY = "grid_only", _("Everything bought from the grid")
    NO_STORAGE = "no_storage", _("Same generation, no battery")
    NONE = "none", _("Do not compute savings")


class DispatchStrategy(models.TextChoices):
    MANUAL = "manual", _("Manual / external control")
    SELF_CONSUMPTION = "self_consumption", _("Maximise self-consumption")
    PEAK_SHAVING = "peak_shaving", _("Peak shaving")
    #: Keep the 15-minute demand under the contracted capacity. In Taiwan this
    #: is usually the strategy that pays for the battery: the surcharge for
    #: exceeding contract capacity dwarfs the energy price.
    DEMAND_CAP = "demand_cap", _("Contract capacity management")
    TOU_ARBITRAGE = "tou_arbitrage", _("Time-of-use arbitrage")
    BACKUP_ONLY = "backup_only", _("Backup reserve only")
    #: Hand control to a drawn workflow. The built-in strategies each encode
    #: one policy; this is the escape hatch for a site whose rules are its own.
    WORKFLOW = "workflow", _("Run a workflow")


class StoragePlan(UUIDPrimaryKeyModel, TimeStampedModel):
    """A named storage strategy profile that sites bind to.

    A *template*, not a per-site record: one plan can drive a whole fleet of
    similar sites, and a site switches behaviour by switching plans - the
    same shape as tariffs. The binding lives on
    :attr:`apps.devices.models.Site.storage_plan`. Site-specific numbers
    (contract capacity, battery size) therefore describe the *class* of site
    the plan is written for; a site that differs enough gets its own plan.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="storage_plans"
    )
    name = models.CharField(max_length=120)
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

    # ---- Strategy parameters --------------------------------------------
    #: Demand ceiling for the demand-cap strategy. Blank falls back to 95% of
    #: ``contract_capacity_kw`` - a margin, because the engine samples on the
    #: scheduler cadence and a target equal to the contract leaves no room for
    #: the load to move between samples.
    demand_cap_target_kw = models.FloatField(null=True, blank=True)
    #: Whether demand-cap recharges during the tariff's cheapest period.
    offpeak_recharge = models.BooleanField(default=True)
    #: Arbitrage acts only when today's peak-vs-trough import price spread is
    #: at least this much (per kWh). Below it the round trip loses money.
    min_price_spread = models.FloatField(default=1.0)

    # ---- Battery health constraints (all strategies) ---------------------
    #: Full-cycle-equivalents per day; today's discharged energy divided by
    #: usable capacity. Blank disables the cap.
    max_cycles_per_day = models.FloatField(null=True, blank=True)
    #: Above this cell/pack temperature the engine stops driving the battery.
    temperature_max_c = models.FloatField(null=True, blank=True)
    #: Metric key on the battery device carrying that temperature.
    temperature_metric = models.CharField(max_length=64, blank=True)

    tariff = models.ForeignKey(
        "ems.Tariff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plans",
    )
    #: What "savings" is measured against. See :class:`SavingsBaseline`.
    savings_baseline = models.CharField(
        max_length=16,
        choices=SavingsBaseline.choices,
        default=SavingsBaseline.NO_STORAGE,
    )
    #: Turn plan limits into a hard gate on dispatch commands, not just a
    #: number on a settings page. Off leaves the previous behaviour, where the
    #: envelope was documentation.
    enforce_limits = models.BooleanField(
        default=True,
        help_text=(
            "Refuse dispatch commands that would exceed this plan's power, "
            "SOC or export limits."
        ),
    )
    #: The workflow driving this site, when :attr:`strategy` is ``workflow``.
    #:
    #: SET_NULL rather than PROTECT: deleting a workflow already stops its runs
    #: and is an explicit act, so blocking it because a plan points at it would
    #: force the operator to hunt down the reference first. The plan is left
    #: naming a strategy with nothing to run, which the engine reports rather
    #: than silently falling back to another policy.
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="storage_plans",
    )
    notes = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "ems_storage_plan"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="uniq_plan_org_name"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.strategy}]"

    @property
    def dispatchable_capacity_kwh(self) -> float | None:
        """Energy available above the backup reserve."""
        if self.usable_capacity_kwh is None:
            return None
        span = max(self.max_soc_percent - self.backup_reserve_percent, 0.0)
        return self.usable_capacity_kwh * span / 100.0


class DemandResponseEvent(UUIDPrimaryKeyModel, TimeStampedModel):
    """One committed demand-response dispatch: discharge this much, now.

    Not a strategy but an *override*: while an event is live it outranks the
    site's strategy and its scheduled windows, because DR participation is a
    commitment made to the grid operator - the one thing the battery must not
    do during the event is follow its everyday policy instead.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="dr_events"
    )
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="dr_events")
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    #: Discharge power the site committed to, kW. Clamped by the plan envelope
    #: like everything else - a commitment beyond the hardware is still a lie.
    target_power_kw = models.FloatField()
    cancelled_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    #: "manual" from the console, "api" from an external dispatch signal.
    source = models.CharField(max_length=12, default="manual")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "ems_dr_event"
        ordering = ["-starts_at"]
        indexes = [models.Index(fields=["site", "starts_at"])]

    def is_live(self, moment) -> bool:
        return (
            self.cancelled_at is None and self.starts_at <= moment < self.ends_at
        )

    def __str__(self) -> str:
        return f"DR {self.site_id} {self.target_power_kw}kW"


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
    #: Baseline cost minus actual cost, where the baseline is chosen by
    #: :attr:`StoragePlan.savings_baseline`.
    #:
    #: Two things this is deliberately not. It is **not clamped at zero**: a
    #: negative value means the dispatch cost more than doing nothing would
    #: have, and hiding that would let the report vouch for a bad decision.
    #: And it is **null, not zero, when there is no baseline** - during an
    #: outage there is no "buy it from the grid instead" alternative to
    #: compare against, so any number here would be fiction. Same principle as
    #: a counter reset in :mod:`apps.telemetry.energy`: unknown is recorded as
    #: unknown.
    estimated_savings = models.FloatField(null=True, blank=True, default=0.0)

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


class EnergyIntervalCost(models.Model):
    """One source's contribution to an interval's cost.

    Why a table rather than columns on :class:`EnergyInterval`: adding a
    ``diesel_cost`` column for every new kind of equipment is exactly the
    coupling the cost-model registry exists to remove. Why a table rather than
    a JSON field: "what did the generators cost this month" has to be a
    GROUP BY, not a full scan followed by summing in Python.

    :attr:`EnergyInterval.energy_cost` and friends stay as the totals, with
    their existing meaning, so every dashboard and roll-up keeps working. This
    is the detail underneath them, not a replacement.
    """

    class Source(models.TextChoices):
        GRID = "grid", _("Utility grid")
        BATTERY = "battery", _("Battery storage")
        GENERATOR = "generator", _("Backup generator")
        EV = "ev", _("EV charging")
        OTHER = "other", _("Other")

    class Basis(models.TextChoices):
        MEASURED = "measured", _("From measured values")
        ESTIMATED = "estimated", _("Modelled estimate")
        UNKNOWN = "unknown", _("Not determinable")

    interval = models.ForeignKey(
        EnergyInterval, on_delete=models.CASCADE, related_name="costs"
    )
    source = models.CharField(max_length=12, choices=Source.choices)
    #: The registered key actually applied, kept so a surprising number can be
    #: traced back to the model that produced it.
    cost_model = models.CharField(max_length=40, blank=True)
    energy_kwh = models.FloatField(default=0.0)
    #: Positive is a cost, negative is a revenue. Never clamped.
    amount = models.FloatField(default=0.0)
    currency = models.CharField(max_length=8, default="TWD")
    unit_cost = models.FloatField(null=True, blank=True)
    #: {"fuel": 1200.0, "maintenance": 150.0}
    breakdown = models.JSONField(default=dict, blank=True)
    basis = models.CharField(
        max_length=12, choices=Basis.choices, default=Basis.ESTIMATED
    )

    class Meta:
        db_table = "ems_energy_interval_cost"
        constraints = [
            models.UniqueConstraint(
                fields=["interval", "source"], name="uniq_interval_cost_source"
            )
        ]
        indexes = [models.Index(fields=["source", "cost_model"])]

    def __str__(self) -> str:
        return f"{self.interval_id} {self.source} {self.amount}"


class SessionKind(models.TextChoices):
    CHARGE = "charge", _("Charging")
    DISCHARGE = "discharge", _("Discharging")
    RUNNING = "running", _("Running")


class SessionEndReason(models.TextChoices):
    THRESHOLD = "threshold", _("Power fell below the exit threshold")
    OFFLINE = "offline", _("Data stopped arriving")
    RECOMPUTED = "recomputed", _("Still open at the end of the rebuild window")


class DeviceOperatingSession(models.Model):
    """One continuous stretch of a device charging, discharging or running.

    Lives here rather than in ``apps.devices`` because everything needed to
    decide where a session starts and stops - the power metric, its scale, the
    sign convention, the thresholds - is on :class:`EnergyAsset`.

    Not derivable from :class:`EnergyInterval`, and not the other way round.
    An interval is site-wide and sits on a fixed 15-minute grid; a session is
    one device's and its edges are wherever the equipment actually moved. The
    same hour appears in both, answering different questions.

    Rebuilt from data on a schedule rather than tracked live: out-of-order and
    late messages would corrupt a running state machine, and a restart would
    lose it. Recomputing is idempotent, so neither matters.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="+", db_index=False
    )
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name="operating_sessions"
    )
    asset = models.ForeignKey(
        EnergyAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operating_sessions",
    )
    kind = models.CharField(max_length=12, choices=SessionKind.choices)

    started_at = models.DateTimeField(db_index=True)
    #: Null means still in progress. For a machine that never stops this is
    #: correct and useful ("running for 37 days"), not a bug to be closed.
    ended_at = models.DateTimeField(null=True, blank=True)
    #: Redundant with the two timestamps, and filled on close so that "average
    #: session length" is one aggregate rather than a Python loop.
    duration_s = models.PositiveIntegerField(null=True, blank=True)

    energy_kwh = models.FloatField(default=0.0)
    peak_kw = models.FloatField(null=True, blank=True)
    avg_kw = models.FloatField(null=True, blank=True)
    start_soc_percent = models.FloatField(null=True, blank=True)
    end_soc_percent = models.FloatField(null=True, blank=True)
    end_reason = models.CharField(
        max_length=12, choices=SessionEndReason.choices, blank=True
    )

    class Meta:
        db_table = "ems_device_session"
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "kind", "started_at"], name="uniq_session_device_start"
            )
        ]
        indexes = [
            models.Index(fields=["device", "kind", "-started_at"]),
            models.Index(fields=["organization", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.device_id} {self.kind} @ {self.started_at:%Y-%m-%d %H:%M}"

    @property
    def is_open(self) -> bool:
        return self.ended_at is None


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


class ForecastConfidence(models.TextChoices):
    """Same vocabulary as ``EnergyIntervalCost.basis``: a reader who has seen
    one knows the other."""

    MEASURED = "measured", _("Measured")
    ESTIMATED = "estimated", _("Estimated")
    UNKNOWN = "unknown", _("Unknown")


class LoadForecast(models.Model):
    """One forecast point: what we expected a 15-minute interval to look like,
    *as of* ``made_at``.

    ``made_at`` is the whole reason this is a table and not a cache. Judging a
    forecast by "the best estimate we have now" would grade every prediction
    against hindsight; keeping the issue time lets the error statistics use
    only what was known at the time, which is what the demand-window margin
    is built on. All times UTC.
    """

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="load_forecasts")
    starts_at = models.DateTimeField(db_index=True)
    made_at = models.DateTimeField(db_index=True)
    horizon_minutes = models.PositiveIntegerField(default=0)
    load_kw = models.FloatField(null=True, blank=True)
    pv_kw = models.FloatField(null=True, blank=True)
    confidence = models.CharField(
        max_length=10, choices=ForecastConfidence.choices, default=ForecastConfidence.UNKNOWN
    )
    #: How many historical weeks the median came from; 0 for unknown.
    samples = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "ems_load_forecast"
        ordering = ["starts_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "starts_at", "made_at"], name="uniq_forecast_site_start_made"
            )
        ]
        indexes = [models.Index(fields=["site", "starts_at", "made_at"])]

    def __str__(self) -> str:
        return f"{self.site_id} @ {self.starts_at:%Y-%m-%d %H:%M} (made {self.made_at:%m-%d %H:%M})"


class SettlementBasis(models.TextChoices):
    MEASURED = "measured", _("Measured")
    ESTIMATED = "estimated", _("Estimated")
    UNKNOWN = "unknown", _("Unknown")


class MonthlySettlement(UUIDPrimaryKeyModel, TimeStampedModel):
    """一個場域一個計費月的帳：對得上台電帳單的那一張（W4）。

    需量費在儀表板上一直是「任意窗口最高需量 × 月費率」的估算；客戶會拿
    真帳單來比，所以要有一張以**當地月份**為單位、封存後不再變動的結算表。

    ``tariff_snapshot`` 是重點：電價表單上就寫著「修改電價會連帶改變這些
    場域的所有電費」。已結算的月份不能被回頭改掉，所以結算當下把電價、
    方案參數與成本參數整份抄進來；之後重算（未封存的月份）也從這份快照
    以外的現行設定重新抄一次，封存後就凍結。

    ``finalized_at`` 為 null 表示進行中、可重算；有值表示已封存，
    ``settle_month`` 會跳過它，除非操作者明確 ``--force``。
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="settlements")
    #: 當地月份的第一天（date）。
    billing_month = models.DateField()
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    currency = models.CharField(max_length=8, default="TWD")

    tariff_snapshot = models.JSONField(default=dict, blank=True)
    #: 結算當下各資產的 cost_parameters——至少把當時的油價抄下來。
    cost_parameters_snapshot = models.JSONField(default=dict, blank=True)

    peak_demand_kw = models.FloatField(null=True, blank=True)
    peak_occurred_at = models.DateTimeField(null=True, blank=True)
    baseline_peak_kw = models.FloatField(null=True, blank=True)
    contract_capacity_kw = models.FloatField(null=True, blank=True)

    energy_charge = models.FloatField(default=0.0)
    demand_charge = models.FloatField(default=0.0)
    excess_penalty = models.FloatField(default=0.0)
    export_revenue = models.FloatField(default=0.0)
    total = models.FloatField(default=0.0)
    #: 同一個月的基準線（依 StoragePlan.savings_baseline）；沒有基準線時為 null。
    baseline_total = models.FloatField(null=True, blank=True)
    #: ``baseline_total − total``；正值是省到、負值是調度反而花更多。null = 無基準線。
    savings = models.FloatField(null=True, blank=True)

    basis = models.CharField(max_length=10, choices=SettlementBasis.choices, default=SettlementBasis.UNKNOWN)
    interval_count = models.PositiveIntegerField(default=0)
    #: 月內有資料的區間比例（0–1），低於 1 表示帳是不完整的。
    coverage = models.FloatField(default=0.0)

    finalized_at = models.DateTimeField(null=True, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ems_monthly_settlement"
        ordering = ["-billing_month"]
        constraints = [
            models.UniqueConstraint(fields=["site", "billing_month"], name="uniq_settlement_site_month"),
        ]

    def __str__(self) -> str:
        return f"{self.site_id} {self.billing_month:%Y-%m} total={self.total:.0f}"
