"""Metric catalogue, recording policy and the time-series tables.

Samples are stored in *long* (narrow) form - one row per device/metric/timestamp
- which keeps the schema stable as device blueprints evolve and maps cleanly
onto a hypertable if the deployment later moves to TimescaleDB.
"""

from __future__ import annotations

from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Organization
from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel
from apps.devices.models import Device, DeviceType

METRIC_KEY_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_]{0,63}$",
    message=_("Metric keys are lowercase snake_case, max 64 characters."),
)


class ValueType(models.TextChoices):
    FLOAT = "float", _("Float")
    INTEGER = "integer", _("Integer")
    BOOLEAN = "boolean", _("Boolean")
    STRING = "string", _("String")
    JSON = "json", _("JSON")


class Aggregation(models.TextChoices):
    """How a metric collapses when downsampled into a coarser bucket."""

    AVG = "avg", _("Average")
    SUM = "sum", _("Sum")
    MIN = "min", _("Minimum")
    MAX = "max", _("Maximum")
    LAST = "last", _("Last value")
    COUNTER = "counter", _("Counter delta")


class MetricKind(models.TextChoices):
    GAUGE = "gauge", _("Gauge")
    COUNTER = "counter", _("Cumulative counter")
    STATE = "state", _("State / enum")


class Metric(UUIDPrimaryKeyModel, TimeStampedModel):
    """Definition of one measurable quantity.

    The catalogue is flat per tenant: ``battery_soc`` means the same thing no
    matter which blueprint reports it, so charts and rules stay portable.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="metrics",
        null=True,
        blank=True,
        help_text="Null means a built-in metric available to every tenant.",
    )
    key = models.CharField(max_length=64, validators=[METRIC_KEY_VALIDATOR])
    display_name = models.CharField(max_length=120)
    #: {"en": "Battery SOC", "zh-hant": "電池電量"} - UI labels.
    translations = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)

    unit = models.CharField(max_length=24, blank=True, help_text="W, kWh, V, A, degC, %")
    value_type = models.CharField(
        max_length=12, choices=ValueType.choices, default=ValueType.FLOAT
    )
    kind = models.CharField(
        max_length=12, choices=MetricKind.choices, default=MetricKind.GAUGE
    )
    aggregation = models.CharField(
        max_length=12, choices=Aggregation.choices, default=Aggregation.AVG
    )
    decimals = models.PositiveSmallIntegerField(default=2)

    # Plausibility window: samples outside are stored but flagged as suspect.
    min_value = models.FloatField(null=True, blank=True)
    max_value = models.FloatField(null=True, blank=True)
    #: Mapping for STATE metrics, e.g. {"0": "idle", "1": "charging"}.
    state_map = models.JSONField(default=dict, blank=True)

    category = models.CharField(max_length=40, blank=True, help_text="power, energy, ...")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "telemetry_metric"
        ordering = ["key"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key"], name="uniq_metric_org_key"
            ),
            models.UniqueConstraint(
                fields=["key"],
                condition=models.Q(organization__isnull=True),
                name="uniq_metric_global_key",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.key} ({self.unit})" if self.unit else self.key

    def label(self, language: str = "en") -> str:
        return (self.translations or {}).get(language) or self.display_name or self.key


class RecordingPolicy(UUIDPrimaryKeyModel, TimeStampedModel):
    """Named set of rules deciding which metrics are persisted, and how often.

    Devices point at a policy; unassigned devices fall back to the tenant
    default. This is what backs "choose which time series to record".
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="recording_policies"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    device_type = models.ForeignKey(
        DeviceType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recording_policies",
        help_text="Applied automatically to devices of this blueprint.",
    )

    #: When false, metrics with no explicit rule are dropped (allow-list mode).
    record_unlisted_metrics = models.BooleanField(default=True)
    #: Default retention for metrics without an explicit override; 0 = forever.
    default_retention_days = models.PositiveIntegerField(default=365)
    #: Minimum spacing applied to unlisted metrics; 0 = keep every sample.
    default_min_interval_seconds = models.PositiveIntegerField(default=0)
    #: Heartbeat: store a sample at least this often even if nothing changed,
    #: so a deadband can never suppress a series indefinitely. 0 disables.
    default_max_interval_seconds = models.PositiveIntegerField(default=3600)

    class Meta:
        db_table = "telemetry_recording_policy"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="uniq_policy_org_name"
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(is_default=True),
                name="uniq_policy_org_default",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class RecordingRule(TimeStampedModel):
    """Per-metric override inside a :class:`RecordingPolicy`."""

    policy = models.ForeignKey(
        RecordingPolicy, on_delete=models.CASCADE, related_name="rules"
    )
    metric_key = models.CharField(max_length=64, validators=[METRIC_KEY_VALIDATOR])
    enabled = models.BooleanField(default=True)

    #: Drop samples arriving sooner than this after the last stored one.
    min_interval_seconds = models.PositiveIntegerField(default=0)
    #: Heartbeat - force a sample after this long regardless of the deadband.
    max_interval_seconds = models.PositiveIntegerField(default=3600)
    #: Drop samples whose absolute change from the last stored value is smaller.
    deadband_absolute = models.FloatField(null=True, blank=True)
    #: Same, expressed as a percentage of the last stored value.
    deadband_percent = models.FloatField(null=True, blank=True)
    #: 0 keeps data forever.
    retention_days = models.PositiveIntegerField(null=True, blank=True)
    #: Keep only rollups after ``retention_days``; drop the raw rows.
    keep_rollups = models.BooleanField(default=True)

    class Meta:
        db_table = "telemetry_recording_rule"
        ordering = ["metric_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "metric_key"], name="uniq_rule_policy_metric"
            )
        ]

    def __str__(self) -> str:
        return f"{self.policy_id}:{self.metric_key}"


class Quality(models.IntegerChoices):
    """Sample trust level, loosely following OPC-UA conventions."""

    GOOD = 0, _("Good")
    SUSPECT = 1, _("Out of plausible range")
    SUBSTITUTED = 2, _("Substituted / interpolated")
    BAD = 3, _("Bad")


class TelemetrySample(models.Model):
    """One measurement.

    ``organization`` is denormalised so tenant-scoped queries never need to
    join the device table, which matters once this table is the largest one.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="+", db_index=False
    )
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="samples")
    metric_key = models.CharField(max_length=64)
    ts = models.DateTimeField()

    value = models.FloatField(null=True, blank=True)
    #: Populated for STRING / JSON / BOOLEAN metrics that have no float form.
    value_text = models.TextField(null=True, blank=True)
    quality = models.SmallIntegerField(choices=Quality.choices, default=Quality.GOOD)

    class Meta:
        db_table = "telemetry_sample"
        constraints = [
            # Idempotent ingest: an at-least-once redelivery collapses to one row.
            models.UniqueConstraint(
                fields=["device", "metric_key", "ts"], name="uniq_sample_device_metric_ts"
            )
        ]
        indexes = [
            models.Index(
                fields=["device", "metric_key", "-ts"], name="idx_sample_dev_metric_ts"
            ),
            models.Index(fields=["organization", "-ts"], name="idx_sample_org_ts"),
        ]

    def __str__(self) -> str:
        return f"{self.metric_key}={self.value} @ {self.ts:%Y-%m-%d %H:%M:%S}"


class LatestSample(models.Model):
    """Current value per device/metric - the dashboard's hot path.

    Maintained by the worker with an upsert so the console never scans the
    sample table to render "now".
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="+"
    )
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name="latest_samples"
    )
    metric_key = models.CharField(max_length=64)
    ts = models.DateTimeField()
    value = models.FloatField(null=True, blank=True)
    value_text = models.TextField(null=True, blank=True)
    quality = models.SmallIntegerField(choices=Quality.choices, default=Quality.GOOD)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "telemetry_latest_sample"
        constraints = [
            models.UniqueConstraint(
                fields=["device", "metric_key"], name="uniq_latest_device_metric"
            )
        ]
        indexes = [models.Index(fields=["organization", "metric_key"])]

    def __str__(self) -> str:
        return f"{self.device_id}:{self.metric_key}={self.value}"


class Rollup(models.Model):
    """Pre-aggregated bucket used for long-range charts and EMS interval math."""

    INTERVAL_CHOICES = [
        (60, _("1 minute")),
        (300, _("5 minutes")),
        (900, _("15 minutes")),
        (3600, _("1 hour")),
        (86400, _("1 day")),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="+", db_index=False
    )
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="rollups")
    metric_key = models.CharField(max_length=64)
    interval_seconds = models.PositiveIntegerField()
    bucket_start = models.DateTimeField()

    count = models.PositiveIntegerField(default=0)
    avg_value = models.FloatField(null=True, blank=True)
    min_value = models.FloatField(null=True, blank=True)
    max_value = models.FloatField(null=True, blank=True)
    sum_value = models.FloatField(null=True, blank=True)
    first_value = models.FloatField(null=True, blank=True)
    last_value = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "telemetry_rollup"
        constraints = [
            models.UniqueConstraint(
                fields=["device", "metric_key", "interval_seconds", "bucket_start"],
                name="uniq_rollup_bucket",
            )
        ]
        indexes = [
            models.Index(
                fields=["device", "metric_key", "interval_seconds", "-bucket_start"],
                name="idx_rollup_lookup",
            )
        ]

    def __str__(self) -> str:
        return f"{self.metric_key}@{self.interval_seconds}s {self.bucket_start:%Y-%m-%d %H:%M}"
