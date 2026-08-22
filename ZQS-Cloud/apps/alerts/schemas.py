from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from ninja import Field, Schema

from apps.alerts.models import (
    AlertEventType,
    AlertSource,
    AlertStatus,
    ChannelType,
    Operator,
    RuleScope,
    Severity,
)


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------
class AlertRuleIn(Schema):
    name: str = Field(max_length=160)
    description: str = ""
    is_enabled: bool = True
    severity: Severity = Severity.WARNING

    scope: RuleScope = RuleScope.ORGANIZATION
    site_id: uuid.UUID | None = None
    device_type_id: uuid.UUID | None = None
    device_ids: list[uuid.UUID] = Field(default_factory=list)

    metric_key: str = Field(max_length=64)
    operator: Operator = Operator.GT
    threshold: float | None = None
    threshold_upper: float | None = None
    hysteresis: float = Field(default=0.0, ge=0)
    for_duration_seconds: int = Field(default=0, ge=0, le=86400)
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    auto_resolve: bool = True
    message_template: str = Field(default="", max_length=300)
    channel_ids: list[uuid.UUID] = Field(default_factory=list)


class AlertRuleOut(Schema):
    id: uuid.UUID
    name: str
    description: str
    is_enabled: bool
    severity: Severity
    scope: RuleScope
    site_id: uuid.UUID | None = None
    device_type_id: uuid.UUID | None = None
    device_ids: list[uuid.UUID] = Field(default_factory=list)
    metric_key: str
    operator: Operator
    threshold: float | None
    threshold_upper: float | None
    hysteresis: float
    for_duration_seconds: int
    cooldown_seconds: int
    auto_resolve: bool
    message_template: str
    channel_ids: list[uuid.UUID] = Field(default_factory=list)
    open_alert_count: int = 0
    created_at: dt.datetime


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------
class AlertOut(Schema):
    id: uuid.UUID
    device_id: uuid.UUID | None = None
    device_external_id: str = ""
    device_name: str = ""
    site_name: str | None = None
    rule_id: uuid.UUID | None = None
    rule_name: str | None = None
    source: AlertSource
    severity: Severity
    status: AlertStatus
    metric_key: str
    code: str
    title: str
    message: str
    trigger_value: float | None
    threshold: float | None
    details: dict[str, Any]
    occurrence_count: int
    started_at: dt.datetime
    last_triggered_at: dt.datetime
    acknowledged_at: dt.datetime | None
    acknowledged_by_label: str | None = None
    acknowledge_note: str
    resolved_at: dt.datetime | None
    resolve_note: str

    @staticmethod
    def resolve_device_external_id(obj) -> str:
        return obj.device.device_id if obj.device_id else ""

    @staticmethod
    def resolve_device_name(obj) -> str:
        return obj.device.name if obj.device_id else ""

    @staticmethod
    def resolve_site_name(obj) -> str | None:
        if obj.device_id and obj.device.site_id:
            return obj.device.site.name
        return None

    @staticmethod
    def resolve_rule_name(obj) -> str | None:
        return obj.rule.name if obj.rule_id else None

    @staticmethod
    def resolve_acknowledged_by_label(obj) -> str | None:
        return obj.acknowledged_by.email if obj.acknowledged_by_id else None


class AlertEventOut(Schema):
    id: int
    event_type: AlertEventType
    actor_label: str
    message: str
    value: float | None
    details: dict[str, Any]
    created_at: dt.datetime


class AlertDetailOut(AlertOut):
    events: list[AlertEventOut] = Field(default_factory=list)

    @staticmethod
    def resolve_events(obj) -> list:
        """Cap the timeline. Without a resolver the related manager would be
        expanded whole, and a long-running alert can hold thousands of rows."""
        return list(obj.events.all()[:200])


class AcknowledgeIn(Schema):
    note: str = Field(default="", max_length=500)


class ResolveIn(Schema):
    note: str = Field(default="", max_length=500)


class BulkAlertIn(Schema):
    alert_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=500)


class AlertSummaryOut(Schema):
    """Counts for the console's alert badge and dashboard header."""

    total_open: int
    firing: int
    acknowledged: int
    by_severity: dict[str, int]
    critical_devices: int


# --------------------------------------------------------------------------
# Notification channels
# --------------------------------------------------------------------------
class NotificationChannelIn(Schema):
    name: str = Field(max_length=120)
    channel_type: ChannelType
    is_enabled: bool = True
    min_severity: Severity = Severity.WARNING
    #: Subscriptions: rule-engine alerts, device-reported events, or both.
    notify_alerts: bool = True
    notify_events: bool = False
    min_event_level: str = "error"
    config: dict[str, Any] = Field(default_factory=dict)


class NotificationChannelOut(Schema):
    id: uuid.UUID
    name: str
    channel_type: ChannelType
    is_enabled: bool
    min_severity: Severity
    notify_alerts: bool
    notify_events: bool
    min_event_level: str
    #: Secrets (auth headers, tokens) are redacted before serialisation.
    config: dict[str, Any]
    created_at: dt.datetime
