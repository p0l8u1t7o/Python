"""Recording policy resolution and the keep/drop decision.

"Choose which time series to record" is implemented here. For every incoming
reading the worker asks: does this device's policy want this metric, has enough
time passed, and did the value move enough to be worth a row?

The resolver caches policies in-process (TTL from ``WORKER["REGISTRY_CACHE_TTL_S"]``)
and keeps the last stored sample per device/metric in memory, so the common case
costs no database access at all.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import uuid
from dataclasses import dataclass, field

from django.conf import settings

from apps.core.logging import get_logger

logger = get_logger("telemetry.policy")


@dataclass(frozen=True, slots=True)
class MetricRule:
    enabled: bool = True
    min_interval_seconds: int = 0
    max_interval_seconds: int = 3600
    deadband_absolute: float | None = None
    deadband_percent: float | None = None
    retention_days: int | None = None


@dataclass(frozen=True, slots=True)
class ResolvedPolicy:
    policy_id: uuid.UUID | None
    record_unlisted: bool = True
    default_min_interval_seconds: int = 0
    default_max_interval_seconds: int = 3600
    default_retention_days: int = 365
    rules: dict[str, MetricRule] = field(default_factory=dict)

    def rule_for(self, metric_key: str) -> MetricRule | None:
        """``None`` means "this metric is not recorded"."""
        rule = self.rules.get(metric_key)
        if rule is not None:
            return rule if rule.enabled else None
        if not self.record_unlisted:
            return None
        return MetricRule(
            min_interval_seconds=self.default_min_interval_seconds,
            max_interval_seconds=self.default_max_interval_seconds,
            retention_days=self.default_retention_days,
        )


#: Applied when a device has no policy at all: keep everything.
PASSTHROUGH = ResolvedPolicy(policy_id=None)


@dataclass(slots=True)
class LastStored:
    ts: dt.datetime
    value: float | None
    text: str | None


class PolicyResolver:
    """Resolves and caches the effective policy for each device."""

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self.ttl = ttl_seconds or settings.WORKER["REGISTRY_CACHE_TTL_S"]
        self._policies: dict[uuid.UUID, ResolvedPolicy] = {}
        self._org_default: dict[uuid.UUID, uuid.UUID | None] = {}
        self._device_type_policy: dict[uuid.UUID, uuid.UUID | None] = {}
        self._loaded_at = 0.0
        self._lock = threading.RLock()

    def refresh(self, *, force: bool = False) -> None:
        with self._lock:
            if not force and (time.monotonic() - self._loaded_at) < self.ttl:
                return
            self._load()

    def _load(self) -> None:
        from apps.telemetry.models import RecordingPolicy, RecordingRule

        policies: dict[uuid.UUID, ResolvedPolicy] = {}
        rules_by_policy: dict[uuid.UUID, dict[str, MetricRule]] = {}

        for row in RecordingRule.objects.values(
            "policy_id",
            "metric_key",
            "enabled",
            "min_interval_seconds",
            "max_interval_seconds",
            "deadband_absolute",
            "deadband_percent",
            "retention_days",
        ):
            rules_by_policy.setdefault(row["policy_id"], {})[row["metric_key"]] = MetricRule(
                enabled=row["enabled"],
                min_interval_seconds=row["min_interval_seconds"],
                max_interval_seconds=row["max_interval_seconds"],
                deadband_absolute=row["deadband_absolute"],
                deadband_percent=row["deadband_percent"],
                retention_days=row["retention_days"],
            )

        org_default: dict[uuid.UUID, uuid.UUID | None] = {}
        device_type_policy: dict[uuid.UUID, uuid.UUID | None] = {}

        for row in RecordingPolicy.objects.values(
            "id",
            "organization_id",
            "device_type_id",
            "is_default",
            "record_unlisted_metrics",
            "default_min_interval_seconds",
            "default_max_interval_seconds",
            "default_retention_days",
        ):
            policies[row["id"]] = ResolvedPolicy(
                policy_id=row["id"],
                record_unlisted=row["record_unlisted_metrics"],
                default_min_interval_seconds=row["default_min_interval_seconds"],
                default_max_interval_seconds=row["default_max_interval_seconds"],
                default_retention_days=row["default_retention_days"],
                rules=rules_by_policy.get(row["id"], {}),
            )
            if row["is_default"]:
                org_default[row["organization_id"]] = row["id"]
            if row["device_type_id"]:
                device_type_policy[row["device_type_id"]] = row["id"]

        self._policies = policies
        self._org_default = org_default
        self._device_type_policy = device_type_policy
        self._loaded_at = time.monotonic()
        logger.debug("recording policies loaded", extra={"count": len(policies)})

    def for_device(self, ref) -> ResolvedPolicy:
        """Resolution order: device override, blueprint, organisation default."""
        self.refresh()
        with self._lock:
            policy_id = ref.recording_policy_id
            if policy_id is None and ref.device_type_id is not None:
                policy_id = self._device_type_policy.get(ref.device_type_id)
            if policy_id is None:
                policy_id = self._org_default.get(ref.organization_id)
            if policy_id is None:
                return PASSTHROUGH
            return self._policies.get(policy_id, PASSTHROUGH)

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0


class SampleGate:
    """Applies min-interval, deadband and heartbeat rules to a reading stream.

    Holds the last *stored* sample per (device, metric) in memory. The map is
    seeded lazily from ``LatestSample`` so a worker restart does not double-write
    the current value of every series.
    """

    def __init__(self, max_entries: int = 500_000) -> None:
        self._last: dict[tuple[uuid.UUID, str], LastStored] = {}
        self._seeded: set[uuid.UUID] = set()
        self._max_entries = max_entries

    def seed_device(self, device_pk: uuid.UUID) -> None:
        if device_pk in self._seeded:
            return
        from apps.telemetry.models import LatestSample

        for row in LatestSample.objects.filter(device_id=device_pk).values(
            "metric_key", "ts", "value", "value_text"
        ):
            self._last[(device_pk, row["metric_key"])] = LastStored(
                ts=row["ts"], value=row["value"], text=row["value_text"]
            )
        self._seeded.add(device_pk)

    def should_store(
        self,
        device_pk: uuid.UUID,
        metric_key: str,
        ts: dt.datetime,
        value: float | None,
        text: str | None,
        rule: MetricRule,
    ) -> bool:
        key = (device_pk, metric_key)
        last = self._last.get(key)
        if last is None:
            return True

        # Out-of-order or duplicate sample: store it (the unique constraint
        # collapses exact duplicates) but do not let it move the gate state.
        if ts <= last.ts:
            return True

        elapsed = (ts - last.ts).total_seconds()
        if rule.min_interval_seconds and elapsed < rule.min_interval_seconds:
            return False

        # Heartbeat wins over any deadband.
        if rule.max_interval_seconds and elapsed >= rule.max_interval_seconds:
            return True

        if text is not None or last.text is not None:
            return text != last.text

        if value is None or last.value is None:
            return value != last.value

        delta = abs(value - last.value)
        if rule.deadband_absolute is not None and delta < rule.deadband_absolute:
            return False
        if rule.deadband_percent is not None and last.value != 0:
            if (delta / abs(last.value)) * 100.0 < rule.deadband_percent:
                return False
        return True

    def mark_stored(
        self,
        device_pk: uuid.UUID,
        metric_key: str,
        ts: dt.datetime,
        value: float | None,
        text: str | None,
    ) -> None:
        key = (device_pk, metric_key)
        previous = self._last.get(key)
        if previous is not None and ts <= previous.ts:
            return  # never let a late sample rewind the gate
        if len(self._last) >= self._max_entries and key not in self._last:
            # Pathological cardinality; drop the gate rather than the process.
            logger.warning("sample gate at capacity, clearing", extra={"entries": len(self._last)})
            self._last.clear()
            self._seeded.clear()
        self._last[key] = LastStored(ts=ts, value=value, text=text)

    def forget_device(self, device_pk: uuid.UUID) -> None:
        self._seeded.discard(device_pk)
        for key in [k for k in self._last if k[0] == device_pk]:
            del self._last[key]
