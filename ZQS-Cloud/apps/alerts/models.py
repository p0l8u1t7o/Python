"""Threshold rules, alert lifecycle and notification fan-out."""

from __future__ import annotations

import hashlib

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Organization, User
from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel
from apps.devices.models import Device, DeviceEvent, DeviceType, EventLevel, Site


class Severity(models.TextChoices):
    INFO = "info", _("Info")
    WARNING = "warning", _("Warning")
    MAJOR = "major", _("Major")
    CRITICAL = "critical", _("Critical")


#: Used for sorting "worst first" in the console.
SEVERITY_RANK: dict[str, int] = {
    Severity.CRITICAL: 40,
    Severity.MAJOR: 30,
    Severity.WARNING: 20,
    Severity.INFO: 10,
}


class Operator(models.TextChoices):
    GT = "gt", _("Greater than")
    GTE = "gte", _("Greater than or equal")
    LT = "lt", _("Less than")
    LTE = "lte", _("Less than or equal")
    EQ = "eq", _("Equal to")
    NEQ = "neq", _("Not equal to")
    OUTSIDE = "outside", _("Outside range")
    INSIDE = "inside", _("Inside range")
    NO_DATA = "no_data", _("No data received")
    OFFLINE = "offline", _("Device offline")


#: Operators that compare a numeric sample against thresholds.
VALUE_OPERATORS = frozenset(
    {
        Operator.GT,
        Operator.GTE,
        Operator.LT,
        Operator.LTE,
        Operator.EQ,
        Operator.NEQ,
        Operator.OUTSIDE,
        Operator.INSIDE,
    }
)


class RuleScope(models.TextChoices):
    ORGANIZATION = "organization", _("All devices")
    SITE = "site", _("Devices at a site")
    DEVICE_TYPE = "device_type", _("Devices of a blueprint")
    DEVICE = "device", _("Selected devices")


class AlertRule(UUIDPrimaryKeyModel, TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="alert_rules"
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True)
    severity = models.CharField(
        max_length=12, choices=Severity.choices, default=Severity.WARNING
    )

    # ---- Scope -----------------------------------------------------------
    scope = models.CharField(
        max_length=16, choices=RuleScope.choices, default=RuleScope.ORGANIZATION
    )
    site = models.ForeignKey(
        Site, on_delete=models.CASCADE, null=True, blank=True, related_name="alert_rules"
    )
    device_type = models.ForeignKey(
        DeviceType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="alert_rules",
    )
    devices = models.ManyToManyField(Device, blank=True, related_name="alert_rules")

    # ---- Condition -------------------------------------------------------
    metric_key = models.CharField(max_length=64, blank=True)
    operator = models.CharField(max_length=12, choices=Operator.choices, default=Operator.GT)
    threshold = models.FloatField(null=True, blank=True)
    #: Upper bound for OUTSIDE / INSIDE comparisons.
    threshold_upper = models.FloatField(null=True, blank=True)
    #: Value must clear the threshold by this margin before the alert resolves,
    #: which stops a signal hovering on the limit from flapping.
    hysteresis = models.FloatField(default=0.0)
    #: Condition must hold continuously for this long before firing.
    for_duration_seconds = models.PositiveIntegerField(default=0)
    #: Suppress re-firing of the same fingerprint within this window.
    cooldown_seconds = models.PositiveIntegerField(default=300)
    auto_resolve = models.BooleanField(default=True)

    #: Message template rendered with {device}, {metric}, {value}, {threshold}.
    message_template = models.CharField(max_length=300, blank=True)
    channels = models.ManyToManyField(
        "alerts.NotificationChannel", blank=True, related_name="rules"
    )

    class Meta:
        db_table = "alerts_rule"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="uniq_rule_org_name"
            )
        ]
        indexes = [
            models.Index(fields=["organization", "is_enabled"]),
            models.Index(fields=["metric_key", "is_enabled"]),
        ]

    def __str__(self) -> str:
        return self.name

    def matches_device(self, device: Device, device_ids: set | None = None) -> bool:
        """``device_ids`` lets the worker pass a pre-fetched set for DEVICE scope."""
        if self.scope == RuleScope.ORGANIZATION:
            return True
        if self.scope == RuleScope.SITE:
            return device.site_id == self.site_id
        if self.scope == RuleScope.DEVICE_TYPE:
            return device.device_type_id == self.device_type_id
        if self.scope == RuleScope.DEVICE:
            ids = device_ids if device_ids is not None else set(
                self.devices.values_list("id", flat=True)
            )
            return device.id in ids
        return False


class AlertStatus(models.TextChoices):
    FIRING = "firing", _("Firing")
    ACKNOWLEDGED = "acknowledged", _("Acknowledged")
    RESOLVED = "resolved", _("Resolved")


class AlertSource(models.TextChoices):
    RULE = "rule", _("Server rule engine")
    DEVICE = "device", _("Reported by device")
    SYSTEM = "system", _("Platform")


class AlertQuerySet(models.QuerySet):
    def active(self) -> "AlertQuerySet":
        return self.exclude(status=AlertStatus.RESOLVED)


class Alert(UUIDPrimaryKeyModel, TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="alerts"
    )
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name="alerts", null=True, blank=True
    )
    rule = models.ForeignKey(
        AlertRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="alerts"
    )
    source = models.CharField(
        max_length=12, choices=AlertSource.choices, default=AlertSource.RULE
    )

    severity = models.CharField(
        max_length=12, choices=Severity.choices, default=Severity.WARNING
    )
    status = models.CharField(
        max_length=16, choices=AlertStatus.choices, default=AlertStatus.FIRING
    )

    metric_key = models.CharField(max_length=64, blank=True)
    #: Vendor alarm code when the device raised it.
    code = models.CharField(max_length=64, blank=True, db_index=True)
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    trigger_value = models.FloatField(null=True, blank=True)
    threshold = models.FloatField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)

    #: Stable hash of (device, rule/code, metric) used to deduplicate re-firing.
    fingerprint = models.CharField(max_length=64, db_index=True)
    occurrence_count = models.PositiveIntegerField(default=1)

    started_at = models.DateTimeField(db_index=True)
    last_triggered_at = models.DateTimeField()
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    acknowledge_note = models.CharField(max_length=500, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolve_note = models.CharField(max_length=500, blank=True)

    objects = AlertQuerySet.as_manager()

    class Meta:
        db_table = "alerts_alert"
        ordering = ["-started_at"]
        constraints = [
            # At most one open alert per fingerprint; re-triggers bump the counter.
            models.UniqueConstraint(
                fields=["fingerprint"],
                condition=~models.Q(status=AlertStatus.RESOLVED),
                name="uniq_open_alert_fingerprint",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-started_at"]),
            models.Index(fields=["device", "-started_at"]),
            models.Index(fields=["organization", "severity", "status"]),
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.title}"

    @property
    def severity_rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, 0)

    @staticmethod
    def build_fingerprint(*parts: object) -> str:
        raw = "|".join(str(part) for part in parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:64]


class AlertEventType(models.TextChoices):
    TRIGGERED = "triggered", _("Triggered")
    RETRIGGERED = "retriggered", _("Re-triggered")
    ACKNOWLEDGED = "acknowledged", _("Acknowledged")
    RESOLVED = "resolved", _("Resolved")
    AUTO_RESOLVED = "auto_resolved", _("Automatically resolved")
    NOTIFIED = "notified", _("Notification sent")
    NOTE = "note", _("Note added")


class AlertEvent(models.Model):
    """Immutable transition log so operators can reconstruct what happened."""

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=16, choices=AlertEventType.choices)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    actor_label = models.CharField(max_length=200, blank=True)
    message = models.CharField(max_length=500, blank=True)
    value = models.FloatField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "alerts_event"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["alert", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M:%S}"


class ChannelType(models.TextChoices):
    WEBHOOK = "webhook", _("HTTP webhook")
    EMAIL = "email", _("Email")
    #: LINE Messaging API push (a LINE bot). LINE Notify was retired in 2025,
    #: so the bot API is the way a message reaches a LINE chat now.
    LINE = "line", _("LINE bot")
    MQTT = "mqtt", _("MQTT publish")


class NotificationChannel(UUIDPrimaryKeyModel, TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="notification_channels"
    )
    name = models.CharField(max_length=120)
    channel_type = models.CharField(max_length=12, choices=ChannelType.choices)
    is_enabled = models.BooleanField(default=True)
    #: Shape depends on ``channel_type``; secrets are redacted on read.
    config = models.JSONField(default=dict, blank=True)
    #: Only notify at or above this severity.
    min_severity = models.CharField(
        max_length=12, choices=Severity.choices, default=Severity.WARNING
    )

    #: What this channel subscribes to. Alerts are what the rule engine
    #: concluded; device events are what the equipment itself reported. They
    #: are separate switches because the audiences differ - a LINE group that
    #: wants "battery overheated" rarely wants every vendor E-code as well.
    notify_alerts = models.BooleanField(default=True)
    notify_events = models.BooleanField(default=False)
    #: Only device events at or above this level are sent.
    min_event_level = models.CharField(
        max_length=16, choices=EventLevel.choices, default=EventLevel.ERROR
    )

    class Meta:
        db_table = "alerts_notification_channel"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="uniq_channel_org_name"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.channel_type})"


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SENT = "sent", _("Sent")
    FAILED = "failed", _("Failed")
    SKIPPED = "skipped", _("Skipped")


class NotificationDelivery(TimeStampedModel):
    """One queued message. Exactly one of ``alert`` / ``event`` is set."""

    alert = models.ForeignKey(
        Alert, on_delete=models.CASCADE, related_name="deliveries",
        null=True, blank=True,
    )
    event = models.ForeignKey(
        DeviceEvent, on_delete=models.CASCADE, related_name="deliveries",
        null=True, blank=True,
    )
    channel = models.ForeignKey(
        NotificationChannel, on_delete=models.CASCADE, related_name="deliveries"
    )
    status = models.CharField(
        max_length=12, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "alerts_notification_delivery"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["alert", "channel"]),
            models.Index(fields=["event", "channel"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(alert__isnull=False, event__isnull=True)
                    | models.Q(alert__isnull=True, event__isnull=False)
                ),
                name="delivery_alert_xor_event",
            )
        ]

    def __str__(self) -> str:
        return f"{self.channel_id} -> {self.status}"
