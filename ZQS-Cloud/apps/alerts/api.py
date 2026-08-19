"""Alert rules, alert lifecycle and notification channels."""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from ninja import Query, Router

from apps.accounts.models import Role
from apps.accounts.security import AuthContext, role_required
from apps.alerts import schemas as s
from apps.alerts.engine import RuleCache
from apps.alerts.models import (
    VALUE_OPERATORS,
    Alert,
    AlertEvent,
    AlertEventType,
    AlertRule,
    AlertStatus,
    ChannelType,
    NotificationChannel,
    Operator,
    RuleScope,
    Severity,
)
from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.core.errors import Conflict, NotFound, ValidationError
from apps.core.schemas import OkResponse, Page, PageParams, TimeRangeParams, paginate
from apps.devices.models import Device, DeviceType, Site

rules_router = Router(tags=["alert-rules"])
alerts_router = Router(tags=["alerts"])
channels_router = Router(tags=["notification-channels"])

_rule_cache = RuleCache()

#: Config keys never returned to the client once stored.
_SECRET_CONFIG_KEYS = {"headers", "token", "password", "secret", "api_key"}


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------
@rules_router.get("", response=list[s.AlertRuleOut])
def list_rules(request, is_enabled: bool | None = None):
    ctx: AuthContext = request.auth
    queryset = (
        AlertRule.objects.filter(organization=ctx.organization)
        .prefetch_related("devices", "channels")
        .annotate(
            open_alert_count=Count(
                "alerts", filter=~Q(alerts__status=AlertStatus.RESOLVED)
            )
        )
        .order_by("name")
    )
    if is_enabled is not None:
        queryset = queryset.filter(is_enabled=is_enabled)
    return [_rule_out(rule) for rule in queryset]


@rules_router.post("", response={201: s.AlertRuleOut}, auth=role_required(Role.ADMIN))
def create_rule(request, payload: s.AlertRuleIn):
    ctx: AuthContext = request.auth
    scope_objects = _validate_rule(ctx, payload)

    with transaction.atomic():
        try:
            rule = AlertRule.objects.create(
                organization=ctx.organization,
                name=payload.name,
                description=payload.description,
                is_enabled=payload.is_enabled,
                severity=payload.severity,
                scope=payload.scope,
                site=scope_objects["site"],
                device_type=scope_objects["device_type"],
                metric_key=payload.metric_key,
                operator=payload.operator,
                threshold=payload.threshold,
                threshold_upper=payload.threshold_upper,
                hysteresis=payload.hysteresis,
                for_duration_seconds=payload.for_duration_seconds,
                cooldown_seconds=payload.cooldown_seconds,
                auto_resolve=payload.auto_resolve,
                message_template=payload.message_template,
            )
        except IntegrityError as exc:
            raise Conflict(
                f"A rule named '{payload.name}' already exists", code="name_taken"
            ) from exc
        rule.devices.set(scope_objects["devices"])
        rule.channels.set(scope_objects["channels"])

    _rule_cache.invalidate()
    record(AuditAction.ALERT_RULE_CREATED, ctx=ctx, target=rule, payload=payload.dict())
    return 201, _rule_out(rule)


@rules_router.get("/{rule_id}", response=s.AlertRuleOut)
def get_rule(request, rule_id: uuid.UUID):
    return _rule_out(_get_rule(request.auth, rule_id))


@rules_router.put("/{rule_id}", response=s.AlertRuleOut, auth=role_required(Role.ADMIN))
def update_rule(request, rule_id: uuid.UUID, payload: s.AlertRuleIn):
    ctx: AuthContext = request.auth
    rule = _get_rule(ctx, rule_id)
    scope_objects = _validate_rule(ctx, payload)

    with transaction.atomic():
        for field in (
            "name",
            "description",
            "is_enabled",
            "severity",
            "scope",
            "metric_key",
            "operator",
            "threshold",
            "threshold_upper",
            "hysteresis",
            "for_duration_seconds",
            "cooldown_seconds",
            "auto_resolve",
            "message_template",
        ):
            setattr(rule, field, getattr(payload, field))
        rule.site = scope_objects["site"]
        rule.device_type = scope_objects["device_type"]
        try:
            rule.save()
        except IntegrityError as exc:
            raise Conflict(
                f"A rule named '{payload.name}' already exists", code="name_taken"
            ) from exc
        rule.devices.set(scope_objects["devices"])
        rule.channels.set(scope_objects["channels"])

    _rule_cache.invalidate()
    record(AuditAction.ALERT_RULE_UPDATED, ctx=ctx, target=rule, payload=payload.dict())
    return _rule_out(rule)


@rules_router.delete("/{rule_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_rule(request, rule_id: uuid.UUID):
    """Alerts raised by the rule are kept; their ``rule`` link becomes null."""
    ctx: AuthContext = request.auth
    rule = _get_rule(ctx, rule_id)
    name = rule.name
    rule.delete()
    _rule_cache.invalidate()
    record(
        AuditAction.ALERT_RULE_DELETED,
        ctx=ctx,
        target_type="alertrule",
        target_id=str(rule_id),
        target_label=name,
    )
    return {"ok": True, "message": "rule_deleted"}


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------
@alerts_router.get("", response=Page[s.AlertOut])
def list_alerts(
    request,
    params: Query[PageParams],
    window: Query[TimeRangeParams],
    status: str | None = None,
    severity: str | None = None,
    device_pk: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    open_only: bool = False,
):
    ctx: AuthContext = request.auth
    queryset = Alert.objects.filter(organization=ctx.organization).select_related(
        "device", "device__site", "rule", "acknowledged_by"
    )

    if open_only:
        queryset = queryset.exclude(status=AlertStatus.RESOLVED)
    elif status:
        queryset = queryset.filter(status=status)
    if severity:
        queryset = queryset.filter(severity=severity)
    if device_pk:
        queryset = queryset.filter(device_id=device_pk)
    if site_id:
        queryset = queryset.filter(device__site_id=site_id)
    if window.start or window.end:
        start, end = window.normalized(default_window_seconds=30 * 24 * 3600)
        queryset = queryset.filter(started_at__gte=start, started_at__lt=end)

    return paginate(queryset.order_by("-started_at"), params)


@alerts_router.get("/summary", response=s.AlertSummaryOut)
def alert_summary(request):
    ctx: AuthContext = request.auth
    open_alerts = Alert.objects.filter(organization=ctx.organization).exclude(
        status=AlertStatus.RESOLVED
    )
    by_severity = {
        row["severity"]: row["count"]
        for row in open_alerts.values("severity").annotate(count=Count("id"))
    }
    return {
        "total_open": open_alerts.count(),
        "firing": open_alerts.filter(status=AlertStatus.FIRING).count(),
        "acknowledged": open_alerts.filter(status=AlertStatus.ACKNOWLEDGED).count(),
        "by_severity": {level: by_severity.get(level, 0) for level in Severity.values},
        "critical_devices": open_alerts.filter(severity=Severity.CRITICAL)
        .values("device_id")
        .distinct()
        .count(),
    }


@alerts_router.get("/{alert_id}", response=s.AlertDetailOut)
def get_alert(request, alert_id: uuid.UUID):
    ctx: AuthContext = request.auth
    alert = _get_alert(ctx, alert_id)
    payload = s.AlertDetailOut.from_orm(alert).dict()
    payload["events"] = list(alert.events.all()[:200])
    return payload


@alerts_router.post("/{alert_id}/acknowledge", response=s.AlertOut, auth=role_required(Role.OPERATOR))
def acknowledge_alert(request, alert_id: uuid.UUID, payload: s.AcknowledgeIn):
    ctx: AuthContext = request.auth
    alert = _get_alert(ctx, alert_id)
    if alert.status == AlertStatus.RESOLVED:
        raise Conflict("Alert is already resolved", code="alert_resolved")
    if alert.status == AlertStatus.ACKNOWLEDGED:
        return alert

    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = timezone.now()
    alert.acknowledged_by = ctx.user
    alert.acknowledge_note = payload.note
    alert.save(
        update_fields=[
            "status",
            "acknowledged_at",
            "acknowledged_by",
            "acknowledge_note",
            "updated_at",
        ]
    )
    AlertEvent.objects.create(
        alert=alert,
        event_type=AlertEventType.ACKNOWLEDGED,
        actor=ctx.user,
        actor_label=ctx.principal_label,
        message=payload.note,
    )
    record(AuditAction.ALERT_ACKNOWLEDGED, ctx=ctx, target=alert, payload={"note": payload.note})
    return alert


@alerts_router.post("/{alert_id}/resolve", response=s.AlertOut, auth=role_required(Role.OPERATOR))
def resolve_alert(request, alert_id: uuid.UUID, payload: s.ResolveIn):
    ctx: AuthContext = request.auth
    alert = _get_alert(ctx, alert_id)
    if alert.status == AlertStatus.RESOLVED:
        return alert

    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = timezone.now()
    alert.resolved_by = ctx.user
    alert.resolve_note = payload.note
    alert.save(
        update_fields=["status", "resolved_at", "resolved_by", "resolve_note", "updated_at"]
    )
    AlertEvent.objects.create(
        alert=alert,
        event_type=AlertEventType.RESOLVED,
        actor=ctx.user,
        actor_label=ctx.principal_label,
        message=payload.note,
    )
    record(AuditAction.ALERT_RESOLVED, ctx=ctx, target=alert, payload={"note": payload.note})
    return alert


@alerts_router.post("/bulk/acknowledge", response=OkResponse, auth=role_required(Role.OPERATOR))
def bulk_acknowledge(request, payload: s.BulkAlertIn):
    ctx: AuthContext = request.auth
    queryset = Alert.objects.filter(
        organization=ctx.organization, id__in=payload.alert_ids, status=AlertStatus.FIRING
    )
    alerts = list(queryset)
    if not alerts:
        return {"ok": True, "message": "no_alerts_updated"}

    now = timezone.now()
    queryset.update(
        status=AlertStatus.ACKNOWLEDGED,
        acknowledged_at=now,
        acknowledged_by=ctx.user,
        acknowledge_note=payload.note,
    )
    AlertEvent.objects.bulk_create(
        [
            AlertEvent(
                alert=alert,
                event_type=AlertEventType.ACKNOWLEDGED,
                actor=ctx.user,
                actor_label=ctx.principal_label,
                message=payload.note,
            )
            for alert in alerts
        ]
    )
    record(
        AuditAction.ALERT_ACKNOWLEDGED,
        ctx=ctx,
        target_type="alert",
        target_label=f"{len(alerts)} alerts",
        payload={"count": len(alerts), "note": payload.note},
    )
    return {"ok": True, "message": f"acknowledged_{len(alerts)}"}


# --------------------------------------------------------------------------
# Notification channels
# --------------------------------------------------------------------------
@channels_router.get("", response=list[s.NotificationChannelOut], auth=role_required(Role.ADMIN))
def list_channels(request):
    ctx: AuthContext = request.auth
    channels = NotificationChannel.objects.filter(
        organization=ctx.organization
    ).order_by("name")
    return [_channel_out(channel) for channel in channels]


@channels_router.post("", response={201: s.NotificationChannelOut}, auth=role_required(Role.ADMIN))
def create_channel(request, payload: s.NotificationChannelIn):
    ctx: AuthContext = request.auth
    _validate_channel_config(payload.channel_type, payload.config)
    try:
        channel = NotificationChannel.objects.create(
            organization=ctx.organization, **payload.dict()
        )
    except IntegrityError as exc:
        raise Conflict(
            f"A channel named '{payload.name}' already exists", code="name_taken"
        ) from exc
    return 201, _channel_out(channel)


@channels_router.put("/{channel_id}", response=s.NotificationChannelOut, auth=role_required(Role.ADMIN))
def update_channel(request, channel_id: uuid.UUID, payload: s.NotificationChannelIn):
    ctx: AuthContext = request.auth
    channel = NotificationChannel.objects.filter(
        organization=ctx.organization, pk=channel_id
    ).first()
    if channel is None:
        raise NotFound("Notification channel not found")

    _validate_channel_config(payload.channel_type, payload.config)
    changes = payload.dict()
    # An empty config on update means "keep the stored secrets".
    if not changes["config"]:
        changes.pop("config")
    for field, value in changes.items():
        setattr(channel, field, value)
    channel.save()
    return _channel_out(channel)


@channels_router.delete("/{channel_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def delete_channel(request, channel_id: uuid.UUID):
    ctx: AuthContext = request.auth
    deleted, _ = NotificationChannel.objects.filter(
        organization=ctx.organization, pk=channel_id
    ).delete()
    if not deleted:
        raise NotFound("Notification channel not found")
    return {"ok": True, "message": "channel_deleted"}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _get_rule(ctx: AuthContext, rule_id: uuid.UUID) -> AlertRule:
    rule = (
        AlertRule.objects.filter(organization=ctx.organization, pk=rule_id)
        .prefetch_related("devices", "channels")
        .first()
    )
    if rule is None:
        raise NotFound("Alert rule not found")
    return rule


def _get_alert(ctx: AuthContext, alert_id: uuid.UUID) -> Alert:
    alert = (
        Alert.objects.filter(organization=ctx.organization, pk=alert_id)
        .select_related("device", "device__site", "rule", "acknowledged_by")
        .first()
    )
    if alert is None:
        raise NotFound("Alert not found")
    return alert


def _rule_out(rule: AlertRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "is_enabled": rule.is_enabled,
        "severity": rule.severity,
        "scope": rule.scope,
        "site_id": rule.site_id,
        "device_type_id": rule.device_type_id,
        "device_ids": [device.id for device in rule.devices.all()],
        "metric_key": rule.metric_key,
        "operator": rule.operator,
        "threshold": rule.threshold,
        "threshold_upper": rule.threshold_upper,
        "hysteresis": rule.hysteresis,
        "for_duration_seconds": rule.for_duration_seconds,
        "cooldown_seconds": rule.cooldown_seconds,
        "auto_resolve": rule.auto_resolve,
        "message_template": rule.message_template,
        "channel_ids": [channel.id for channel in rule.channels.all()],
        "open_alert_count": getattr(rule, "open_alert_count", 0),
        "created_at": rule.created_at,
    }


def _channel_out(channel: NotificationChannel) -> dict:
    config = dict(channel.config or {})
    for key in list(config):
        if key.lower() in _SECRET_CONFIG_KEYS:
            config[key] = "***"
    return {
        "id": channel.id,
        "name": channel.name,
        "channel_type": channel.channel_type,
        "is_enabled": channel.is_enabled,
        "min_severity": channel.min_severity,
        "config": config,
        "created_at": channel.created_at,
    }


def _validate_rule(ctx: AuthContext, payload: s.AlertRuleIn) -> dict:
    if payload.operator in VALUE_OPERATORS and payload.threshold is None:
        raise ValidationError(
            f"Operator '{payload.operator}' requires a threshold", code="missing_threshold"
        )
    if payload.operator in (Operator.OUTSIDE, Operator.INSIDE):
        if payload.threshold_upper is None:
            raise ValidationError(
                f"Operator '{payload.operator}' requires threshold_upper",
                code="missing_threshold_upper",
            )
        if payload.threshold_upper <= payload.threshold:
            raise ValidationError(
                "threshold_upper must be greater than threshold",
                code="invalid_range",
            )

    site = device_type = None
    devices: list[Device] = []

    if payload.scope == RuleScope.SITE:
        if payload.site_id is None:
            raise ValidationError("scope 'site' requires site_id", code="missing_site")
        site = Site.objects.filter(
            organization=ctx.organization, pk=payload.site_id, deleted_at__isnull=True
        ).first()
        if site is None:
            raise NotFound("Site not found")
    elif payload.scope == RuleScope.DEVICE_TYPE:
        if payload.device_type_id is None:
            raise ValidationError(
                "scope 'device_type' requires device_type_id", code="missing_device_type"
            )
        device_type = DeviceType.objects.filter(
            Q(organization=ctx.organization) | Q(organization__isnull=True),
            pk=payload.device_type_id,
        ).first()
        if device_type is None:
            raise NotFound("Blueprint not found")
    elif payload.scope == RuleScope.DEVICE:
        if not payload.device_ids:
            raise ValidationError(
                "scope 'device' requires at least one device id", code="missing_devices"
            )
        devices = list(
            Device.objects.for_organization(ctx.organization).filter(
                pk__in=payload.device_ids
            )
        )
        if len(devices) != len(set(payload.device_ids)):
            raise NotFound("One or more devices were not found", code="device_not_found")

    channels = []
    if payload.channel_ids:
        channels = list(
            NotificationChannel.objects.filter(
                organization=ctx.organization, id__in=payload.channel_ids
            )
        )
        if len(channels) != len(set(payload.channel_ids)):
            raise NotFound("One or more channels were not found", code="channel_not_found")

    return {
        "site": site,
        "device_type": device_type,
        "devices": devices,
        "channels": channels,
    }


def _validate_channel_config(channel_type: str, config: dict) -> None:
    if channel_type == ChannelType.WEBHOOK:
        url = config.get("url", "")
        if not url:
            raise ValidationError("Webhook channels require a 'url'", code="missing_url")
        if not str(url).startswith(("http://", "https://")):
            raise ValidationError("Webhook url must be http(s)", code="invalid_url")
    elif channel_type == ChannelType.MQTT:
        if not config.get("topic"):
            raise ValidationError("MQTT channels require a 'topic'", code="missing_topic")
    elif channel_type == ChannelType.EMAIL:
        recipients = config.get("recipients") or []
        if not isinstance(recipients, list) or not recipients:
            raise ValidationError(
                "Email channels require a non-empty 'recipients' list",
                code="missing_recipients",
            )
