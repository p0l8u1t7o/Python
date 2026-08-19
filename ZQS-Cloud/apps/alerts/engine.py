"""Threshold rule evaluation.

Called by the ingest worker once per stored reading. Three things make this
more than a simple comparison:

* **Sustained conditions** - a rule with ``for_duration_seconds`` only fires
  once the condition has held continuously, which filters out single-sample
  spikes. The pending-since state is kept in memory per worker.
* **Hysteresis** - the value has to come back past the threshold by a margin
  before the alert auto-resolves, so a signal sitting on the limit does not
  flap between firing and resolved.
* **Deduplication** - alerts are keyed by a fingerprint with a partial unique
  index, so a repeated breach bumps a counter instead of creating a new row.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import uuid
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import F

from apps.alerts.models import (
    VALUE_OPERATORS,
    Alert,
    AlertEvent,
    AlertEventType,
    AlertRule,
    AlertSource,
    AlertStatus,
    DeliveryStatus,
    NotificationDelivery,
    Operator,
    RuleScope,
    SEVERITY_RANK,
)
from apps.core.logging import get_logger

logger = get_logger("alerts.engine")


@dataclass(frozen=True, slots=True)
class CompiledRule:
    """Flattened rule; avoids touching the ORM inside the evaluation loop."""

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    severity: str
    metric_key: str
    operator: str
    threshold: float | None
    threshold_upper: float | None
    hysteresis: float
    for_duration_seconds: int
    cooldown_seconds: int
    auto_resolve: bool
    message_template: str
    scope: str
    site_id: uuid.UUID | None
    device_type_id: uuid.UUID | None
    device_ids: frozenset[uuid.UUID] = frozenset()
    channel_ids: tuple[uuid.UUID, ...] = ()

    def applies_to(self, ref) -> bool:
        if self.scope == RuleScope.ORGANIZATION:
            return True
        if self.scope == RuleScope.SITE:
            return ref.site_id is not None and ref.site_id == self.site_id
        if self.scope == RuleScope.DEVICE_TYPE:
            return ref.device_type_id is not None and ref.device_type_id == self.device_type_id
        if self.scope == RuleScope.DEVICE:
            return ref.pk in self.device_ids
        return False


def breaches(rule: CompiledRule, value: float) -> bool:
    """True when ``value`` violates the rule's condition."""
    threshold = rule.threshold
    upper = rule.threshold_upper

    if rule.operator == Operator.GT:
        return threshold is not None and value > threshold
    if rule.operator == Operator.GTE:
        return threshold is not None and value >= threshold
    if rule.operator == Operator.LT:
        return threshold is not None and value < threshold
    if rule.operator == Operator.LTE:
        return threshold is not None and value <= threshold
    if rule.operator == Operator.EQ:
        return threshold is not None and value == threshold
    if rule.operator == Operator.NEQ:
        return threshold is not None and value != threshold
    if rule.operator == Operator.OUTSIDE:
        return threshold is not None and upper is not None and not (threshold <= value <= upper)
    if rule.operator == Operator.INSIDE:
        return threshold is not None and upper is not None and threshold <= value <= upper
    return False


def clears(rule: CompiledRule, value: float) -> bool:
    """True when ``value`` is far enough back inside the safe band to resolve.

    With ``hysteresis = 0`` this is simply ``not breaches``.
    """
    margin = abs(rule.hysteresis)
    threshold = rule.threshold
    upper = rule.threshold_upper

    if threshold is None:
        return not breaches(rule, value)

    if rule.operator in (Operator.GT, Operator.GTE):
        return value <= threshold - margin
    if rule.operator in (Operator.LT, Operator.LTE):
        return value >= threshold + margin
    if rule.operator == Operator.OUTSIDE and upper is not None:
        return (threshold + margin) <= value <= (upper - margin)
    if rule.operator == Operator.INSIDE and upper is not None:
        return value < threshold - margin or value > upper + margin
    return not breaches(rule, value)


class RuleCache:
    """Enabled rules indexed by ``(organization_id, metric_key)``."""

    def __init__(self, ttl_seconds: int = 30) -> None:
        self.ttl = ttl_seconds
        self._by_org_metric: dict[tuple[uuid.UUID, str], list[CompiledRule]] = {}
        self._loaded_at = 0.0
        self._lock = threading.RLock()

    def refresh(self, *, force: bool = False) -> None:
        with self._lock:
            if not force and (time.monotonic() - self._loaded_at) < self.ttl:
                return
            self._load()

    def _load(self) -> None:
        index: dict[tuple[uuid.UUID, str], list[CompiledRule]] = {}
        queryset = (
            AlertRule.objects.filter(is_enabled=True)
            .exclude(metric_key="")
            .prefetch_related("devices", "channels")
        )
        for rule in queryset:
            if rule.operator not in VALUE_OPERATORS:
                continue  # no_data / offline are handled by the health checker
            compiled = CompiledRule(
                id=rule.id,
                organization_id=rule.organization_id,
                name=rule.name,
                severity=rule.severity,
                metric_key=rule.metric_key,
                operator=rule.operator,
                threshold=rule.threshold,
                threshold_upper=rule.threshold_upper,
                hysteresis=rule.hysteresis,
                for_duration_seconds=rule.for_duration_seconds,
                cooldown_seconds=rule.cooldown_seconds,
                auto_resolve=rule.auto_resolve,
                message_template=rule.message_template,
                scope=rule.scope,
                site_id=rule.site_id,
                device_type_id=rule.device_type_id,
                device_ids=frozenset(d.id for d in rule.devices.all()),
                channel_ids=tuple(c.id for c in rule.channels.all()),
            )
            index.setdefault((rule.organization_id, rule.metric_key), []).append(compiled)

        self._by_org_metric = index
        self._loaded_at = time.monotonic()
        logger.debug("alert rules loaded", extra={"keys": len(index)})

    def for_metric(self, organization_id: uuid.UUID, metric_key: str) -> list[CompiledRule]:
        self.refresh()
        with self._lock:
            return self._by_org_metric.get((organization_id, metric_key), [])

    def has_rules(self, organization_id: uuid.UUID, metric_key: str) -> bool:
        return bool(self.for_metric(organization_id, metric_key))

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0


@dataclass
class PendingState:
    """Tracks how long a condition has been continuously breached."""

    since: dt.datetime | None = None
    fired: bool = False
    last_fired_at: dt.datetime | None = None


class AlertEngine:
    def __init__(self, rule_cache: RuleCache | None = None) -> None:
        self.rules = rule_cache or RuleCache()
        self._pending: dict[tuple[uuid.UUID, uuid.UUID], PendingState] = {}
        self._lock = threading.Lock()

    # ---- evaluation ------------------------------------------------------
    def evaluate(
        self, ref, metric_key: str, value: float | None, ts: dt.datetime, device_name: str = ""
    ) -> list[Alert]:
        """Evaluate every rule bound to ``metric_key`` for one reading."""
        if value is None:
            return []

        fired: list[Alert] = []
        for rule in self.rules.for_metric(ref.organization_id, metric_key):
            if not rule.applies_to(ref):
                continue
            alert = self._evaluate_one(rule, ref, metric_key, value, ts, device_name)
            if alert is not None:
                fired.append(alert)
        return fired

    def _evaluate_one(
        self,
        rule: CompiledRule,
        ref,
        metric_key: str,
        value: float,
        ts: dt.datetime,
        device_name: str,
    ) -> Alert | None:
        key = (rule.id, ref.pk)
        with self._lock:
            state = self._pending.setdefault(key, PendingState())

            if breaches(rule, value):
                if state.since is None:
                    state.since = ts
                held_for = (ts - state.since).total_seconds()
                if held_for < rule.for_duration_seconds:
                    return None
                if state.fired:
                    self._retrigger(rule, ref, metric_key, value, ts)
                    return None
                if (
                    state.last_fired_at is not None
                    and rule.cooldown_seconds
                    and (ts - state.last_fired_at).total_seconds() < rule.cooldown_seconds
                ):
                    return None
                state.fired = True
                state.last_fired_at = ts
                should_fire = True
            else:
                state.since = None
                should_fire = False
                if state.fired and rule.auto_resolve and clears(rule, value):
                    state.fired = False
                    self._auto_resolve(rule, ref, metric_key, value, ts)
                return None

        if not should_fire:
            return None
        return self._fire(rule, ref, metric_key, value, ts, device_name)

    # ---- alert lifecycle -------------------------------------------------
    def _fingerprint(self, rule_id: uuid.UUID, device_pk: uuid.UUID, metric_key: str) -> str:
        return Alert.build_fingerprint("rule", rule_id, device_pk, metric_key)

    def _fire(
        self,
        rule: CompiledRule,
        ref,
        metric_key: str,
        value: float,
        ts: dt.datetime,
        device_name: str,
    ) -> Alert | None:
        fingerprint = self._fingerprint(rule.id, ref.pk, metric_key)
        message = _render(rule.message_template, device_name, metric_key, value, rule.threshold)

        # An open alert with this fingerprint already exists -> bump it instead.
        if (
            Alert.objects.filter(fingerprint=fingerprint)
            .exclude(status=AlertStatus.RESOLVED)
            .exists()
        ):
            self._retrigger(rule, ref, metric_key, value, ts)
            return None

        try:
            with transaction.atomic():
                alert = Alert.objects.create(
                    fingerprint=fingerprint,
                    organization_id=ref.organization_id,
                    device_id=ref.pk,
                    rule_id=rule.id,
                    source=AlertSource.RULE,
                    severity=rule.severity,
                    status=AlertStatus.FIRING,
                    metric_key=metric_key,
                    title=rule.name,
                    message=message,
                    trigger_value=value,
                    threshold=rule.threshold,
                    started_at=ts,
                    last_triggered_at=ts,
                    details={"operator": rule.operator, "rule": rule.name},
                )
        except IntegrityError:
            # Another worker won the race against the partial unique index.
            self._retrigger(rule, ref, metric_key, value, ts)
            return None

        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEventType.TRIGGERED,
            actor_label="rule-engine",
            message=message,
            value=value,
        )
        self._queue_notifications(alert, rule)
        logger.info(
            "alert fired",
            extra={
                "rule": rule.name,
                "device_id": ref.device_id,
                "metric": metric_key,
                "value": value,
            },
        )
        return alert

    def _retrigger(
        self, rule: CompiledRule, ref, metric_key: str, value: float, ts: dt.datetime
    ) -> None:
        fingerprint = self._fingerprint(rule.id, ref.pk, metric_key)
        Alert.objects.filter(fingerprint=fingerprint).exclude(
            status=AlertStatus.RESOLVED
        ).update(
            last_triggered_at=ts,
            trigger_value=value,
            occurrence_count=F("occurrence_count") + 1,
        )

    def _auto_resolve(
        self, rule: CompiledRule, ref, metric_key: str, value: float, ts: dt.datetime
    ) -> None:
        fingerprint = self._fingerprint(rule.id, ref.pk, metric_key)
        alert = (
            Alert.objects.filter(fingerprint=fingerprint)
            .exclude(status=AlertStatus.RESOLVED)
            .first()
        )
        if alert is None:
            return
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = ts
        alert.resolve_note = "Condition cleared"
        alert.save(update_fields=["status", "resolved_at", "resolve_note", "updated_at"])
        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEventType.AUTO_RESOLVED,
            actor_label="rule-engine",
            message=f"{metric_key} returned to {value}",
            value=value,
        )
        logger.info(
            "alert auto-resolved",
            extra={"rule": rule.name, "device_id": ref.device_id, "metric": metric_key},
        )

    def _queue_notifications(self, alert: Alert, rule: CompiledRule) -> None:
        """Create pending deliveries; the dispatcher thread sends them."""
        if not rule.channel_ids:
            return
        from apps.alerts.models import NotificationChannel

        channels = NotificationChannel.objects.filter(
            id__in=rule.channel_ids, is_enabled=True
        )
        deliveries = [
            NotificationDelivery(
                alert=alert, channel=channel, status=DeliveryStatus.PENDING
            )
            for channel in channels
            if SEVERITY_RANK.get(alert.severity, 0)
            >= SEVERITY_RANK.get(channel.min_severity, 0)
        ]
        if deliveries:
            NotificationDelivery.objects.bulk_create(deliveries, ignore_conflicts=True)

    # ---- device-reported alarms -----------------------------------------
    def raise_device_alarm(
        self,
        ref,
        *,
        code: str,
        severity: str,
        message: str,
        ts: dt.datetime,
        details: dict | None = None,
        device_name: str = "",
    ) -> Alert | None:
        """Open (or re-trigger) an alarm the device itself reported."""
        fingerprint = Alert.build_fingerprint("device", ref.pk, code)

        if (
            Alert.objects.filter(fingerprint=fingerprint)
            .exclude(status=AlertStatus.RESOLVED)
            .exists()
        ):
            self._bump_device_alarm(fingerprint, ts)
            return None

        try:
            with transaction.atomic():
                alert = Alert.objects.create(
                    fingerprint=fingerprint,
                    organization_id=ref.organization_id,
                    device_id=ref.pk,
                    source=AlertSource.DEVICE,
                    severity=severity,
                    status=AlertStatus.FIRING,
                    code=code,
                    title=(message or f"Device alarm {code}")[:200],
                    message=message,
                    started_at=ts,
                    last_triggered_at=ts,
                    details=details or {},
                )
        except IntegrityError:
            self._bump_device_alarm(fingerprint, ts)
            return None

        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEventType.TRIGGERED,
            actor_label=device_name or ref.device_id,
            message=message,
        )
        logger.info(
            "device alarm raised", extra={"device_id": ref.device_id, "code": code}
        )
        return alert

    def _bump_device_alarm(self, fingerprint: str, ts: dt.datetime) -> None:
        Alert.objects.filter(fingerprint=fingerprint).exclude(
            status=AlertStatus.RESOLVED
        ).update(last_triggered_at=ts, occurrence_count=F("occurrence_count") + 1)

    def clear_device_alarm(self, ref, *, code: str, ts: dt.datetime) -> None:
        fingerprint = Alert.build_fingerprint("device", ref.pk, code)
        alert = (
            Alert.objects.filter(fingerprint=fingerprint)
            .exclude(status=AlertStatus.RESOLVED)
            .first()
        )
        if alert is None:
            return
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = ts
        alert.resolve_note = "Cleared by device"
        alert.save(update_fields=["status", "resolved_at", "resolve_note", "updated_at"])
        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEventType.AUTO_RESOLVED,
            actor_label=ref.device_id,
            message=f"Device cleared alarm {code}",
        )

    def forget_device(self, device_pk: uuid.UUID) -> None:
        with self._lock:
            for key in [k for k in self._pending if k[1] == device_pk]:
                del self._pending[key]


def _render(
    template: str, device: str, metric: str, value: float, threshold: float | None
) -> str:
    if not template:
        limit = "" if threshold is None else f" (threshold {threshold:g})"
        return f"{device or 'Device'}: {metric} = {value:g}{limit}"
    try:
        return template.format(
            device=device, metric=metric, value=value, threshold=threshold
        )[:500]
    except (KeyError, IndexError, ValueError):
        # A bad template must not stop the alert from firing.
        return f"{device or 'Device'}: {metric} = {value:g}"
