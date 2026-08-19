"""Batch processors consuming envelopes from the message bus.

One processor per message kind. Each receives the whole batch so it can collapse
work into set-based database operations - a batch of 500 telemetry envelopes
becomes a handful of statements, not 500 round trips.

Every processor is idempotent: at-least-once redelivery must not double-count.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from typing import Any, Iterable

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.alerts.engine import AlertEngine
from apps.core.logging import get_logger
from apps.core.timeutils import parse_timestamp
from apps.devices.models import (
    Command,
    CommandStatus,
    ConnectionStatus,
    Device,
    DeviceEvent,
    DeviceStatusEvent,
    EventLevel,
)
from apps.devices.registry import DeviceRef, get_registry
from apps.telemetry.catalog import get_catalog
from apps.telemetry.models import Quality
from apps.telemetry.policy import PolicyResolver, SampleGate
from apps.telemetry.repository import SampleRow, insert_samples, upsert_latest

logger = get_logger("worker.processors")


class Shared:
    """Caches shared by every processor in a worker process."""

    def __init__(self) -> None:
        self.registry = get_registry()
        self.catalog = get_catalog()
        self.policies = PolicyResolver()
        self.gate = SampleGate()
        self.alerts = AlertEngine()
        self._device_names: dict[uuid.UUID, str] = {}

    def resolve(self, envelope: dict[str, Any]) -> DeviceRef | None:
        """Map an envelope to a registered device, provisioning if configured."""
        device_id = envelope.get("device_id")
        if not device_id:
            return None
        ref = self.registry.get(device_id)
        if ref is not None:
            return ref
        if not settings.INGEST["AUTO_PROVISION"]:
            return None
        return self._auto_provision(device_id)

    def _auto_provision(self, device_id: str) -> DeviceRef | None:
        from apps.accounts.models import Organization

        slug = settings.INGEST["AUTO_PROVISION_ORG_SLUG"]
        organization = Organization.objects.filter(slug=slug, is_active=True).first()
        if organization is None:
            logger.error(
                "auto-provision organization missing",
                extra={"slug": slug, "device_id": device_id},
            )
            return None

        device, created = Device.objects.get_or_create(
            device_id=device_id,
            defaults={
                "organization": organization,
                "name": device_id,
                "description": "Auto-provisioned on first uplink",
                "status": ConnectionStatus.UNKNOWN,
            },
        )
        if created:
            logger.info("auto-provisioned device", extra={"device_id": device_id})
        self.registry.invalidate()
        return self.registry.get(device_id)

    def device_name(self, ref: DeviceRef) -> str:
        name = self._device_names.get(ref.pk)
        if name is None:
            name = (
                Device.objects.filter(pk=ref.pk)
                .values_list("name", flat=True)
                .first()
                or ref.device_id
            )
            self._device_names[ref.pk] = name
        return name

    def invalidate(self) -> None:
        self.registry.invalidate()
        self.policies.invalidate()
        self.catalog.invalidate()
        self.alerts.rules.invalidate()
        self._device_names.clear()


def _ts(value: Any, fallback: dt.datetime) -> dt.datetime:
    try:
        return parse_timestamp(value)
    except Exception:  # noqa: BLE001 - the ingestor already validated this
        return fallback


# --------------------------------------------------------------------------
# Telemetry
# --------------------------------------------------------------------------
class TelemetryProcessor:
    def __init__(self, shared: Shared) -> None:
        self.shared = shared

    def process(self, envelopes: list[dict[str, Any]]) -> dict[str, int]:
        received_at = timezone.now()
        rows: list[SampleRow] = []
        last_seen: dict[uuid.UUID, dt.datetime] = {}
        alert_inputs: list[tuple[DeviceRef, str, float | None, dt.datetime]] = []
        stats = defaultdict(int)

        for envelope in envelopes:
            ref = self.shared.resolve(envelope)
            if ref is None:
                stats["skipped_unknown_device"] += 1
                continue
            if not ref.is_enabled:
                stats["skipped_disabled"] += 1
                continue

            policy = self.shared.policies.for_device(ref)
            self.shared.gate.seed_device(ref.pk)

            for reading in envelope.get("data", {}).get("readings", []):
                metric_key = reading["metric"]
                ts = _ts(reading.get("ts"), received_at)
                value = reading.get("value")
                text = reading.get("text")

                # Alerts see every reading. A deadband is a storage decision;
                # letting it hide a threshold breach would be a safety bug.
                alert_inputs.append((ref, metric_key, value, ts))

                rule = policy.rule_for(metric_key)
                if rule is None:
                    stats["filtered_by_policy"] += 1
                    continue
                if not self.shared.gate.should_store(
                    ref.pk, metric_key, ts, value, text, rule
                ):
                    stats["filtered_by_deadband"] += 1
                    continue

                quality = reading.get("quality")
                if quality is None:
                    definition = self.shared.catalog.get(ref.organization_id, metric_key)
                    quality = (
                        Quality.GOOD
                        if definition is None or definition.is_plausible(value)
                        else Quality.SUSPECT
                    )
                    if quality == Quality.SUSPECT:
                        stats["suspect"] += 1

                rows.append(
                    SampleRow(
                        organization_id=ref.organization_id,
                        device_id=ref.pk,
                        metric_key=metric_key,
                        ts=ts,
                        value=value,
                        value_text=text,
                        quality=int(quality),
                    )
                )
                self.shared.gate.mark_stored(ref.pk, metric_key, ts, value, text)

                current = last_seen.get(ref.pk)
                if current is None or ts > current:
                    last_seen[ref.pk] = ts

        if rows:
            with transaction.atomic():
                stats["inserted"] = insert_samples(rows)
                upsert_latest(rows, updated_at=received_at)

        self._touch_devices(last_seen, received_at)
        self._evaluate_alerts(alert_inputs, stats)
        return dict(stats)

    def _touch_devices(
        self, last_seen: dict[uuid.UUID, dt.datetime], received_at: dt.datetime
    ) -> None:
        """One UPDATE per distinct telemetry timestamp, not per device."""
        if not last_seen:
            return
        by_timestamp: dict[dt.datetime, list[uuid.UUID]] = defaultdict(list)
        for device_pk, ts in last_seen.items():
            by_timestamp[ts].append(device_pk)

        for ts, device_pks in by_timestamp.items():
            Device.objects.filter(pk__in=device_pks).update(
                last_seen_at=received_at, last_telemetry_at=ts
            )

        # A device that is sending data is online, whatever its stored state.
        stale = Device.objects.filter(pk__in=list(last_seen)).exclude(
            status=ConnectionStatus.ONLINE
        )
        transitioned = list(stale.values_list("pk", flat=True))
        if transitioned:
            stale.update(status=ConnectionStatus.ONLINE, status_changed_at=received_at)
            DeviceStatusEvent.objects.bulk_create(
                [
                    DeviceStatusEvent(
                        device_id=pk,
                        status=ConnectionStatus.ONLINE,
                        reason="telemetry",
                        ts=received_at,
                    )
                    for pk in transitioned
                ]
            )

    def _evaluate_alerts(self, inputs: Iterable[tuple], stats: dict) -> None:
        for ref, metric_key, value, ts in inputs:
            if value is None:
                continue
            if not self.shared.alerts.rules.for_metric(ref.organization_id, metric_key):
                continue
            try:
                fired = self.shared.alerts.evaluate(
                    ref, metric_key, value, ts, device_name=self.shared.device_name(ref)
                )
            except Exception:  # noqa: BLE001 - one bad rule must not stop ingest
                logger.exception(
                    "alert evaluation failed",
                    extra={"device_id": ref.device_id, "metric": metric_key},
                )
                continue
            stats["alerts_fired"] += len(fired)


# --------------------------------------------------------------------------
# Connection status (including MQTT last will)
# --------------------------------------------------------------------------
class StatusProcessor:
    def __init__(self, shared: Shared) -> None:
        self.shared = shared

    def process(self, envelopes: list[dict[str, Any]]) -> dict[str, int]:
        received_at = timezone.now()
        stats: dict[str, int] = defaultdict(int)

        for envelope in envelopes:
            ref = self.shared.resolve(envelope)
            if ref is None:
                stats["skipped_unknown_device"] += 1
                continue

            data = envelope.get("data", {})
            status = data.get("status")
            if status not in {ConnectionStatus.ONLINE, ConnectionStatus.OFFLINE}:
                stats["skipped_bad_status"] += 1
                continue

            ts = _ts(data.get("ts"), received_at)
            device = Device.objects.filter(pk=ref.pk).first()
            if device is None:
                continue

            # A retained LWT replayed on reconnect must not knock a live device
            # offline; ignore anything older than the last transition.
            if (
                envelope.get("retained")
                and device.status_changed_at is not None
                and ts <= device.status_changed_at
            ):
                stats["ignored_stale_retained"] += 1
                continue

            previous = device.status
            updates: dict[str, Any] = {"last_seen_at": received_at}
            if previous != status:
                updates["status"] = status
                updates["status_changed_at"] = ts

            for field, key in (
                ("firmware_version", "firmware"),
                ("hardware_version", "hardware"),
            ):
                value = data.get(key)
                if value:
                    updates[field] = value[:64]
            if data.get("ip"):
                updates["ip_address"] = data["ip"]
            if data.get("rssi") is not None:
                updates["rssi"] = data["rssi"]

            location = data.get("location") or {}
            if location.get("latitude") is not None and location.get("longitude") is not None:
                updates["latitude"] = location["latitude"]
                updates["longitude"] = location["longitude"]
                updates["address"] = (location.get("address") or "")[:400]
                updates["location_source"] = "device"
                updates["location_updated_at"] = ts

            Device.objects.filter(pk=ref.pk).update(**updates)

            if previous != status:
                DeviceStatusEvent.objects.create(
                    device_id=ref.pk,
                    status=status,
                    previous_status=previous,
                    reason=(data.get("reason") or "report")[:64],
                    ts=ts,
                    payload=data,
                )
                stats[f"transition_{status}"] += 1
                logger.info(
                    "device status changed",
                    extra={
                        "device_id": ref.device_id,
                        "from": previous,
                        "to": status,
                        "reason": data.get("reason", ""),
                    },
                )
            stats["processed"] += 1
        return dict(stats)


# --------------------------------------------------------------------------
# Device operation log and device-raised alarms
# --------------------------------------------------------------------------
class EventProcessor:
    """Handles both ``event`` (operation log) and ``alarm`` envelopes."""

    _SEVERITY_TO_LEVEL = {
        "info": EventLevel.INFO,
        "warning": EventLevel.WARNING,
        "major": EventLevel.ERROR,
        "critical": EventLevel.CRITICAL,
    }

    def __init__(self, shared: Shared) -> None:
        self.shared = shared

    def process(self, envelopes: list[dict[str, Any]]) -> dict[str, int]:
        received_at = timezone.now()
        stats: dict[str, int] = defaultdict(int)
        pending: list[DeviceEvent] = []
        touched: list[uuid.UUID] = []

        for envelope in envelopes:
            ref = self.shared.resolve(envelope)
            if ref is None:
                stats["skipped_unknown_device"] += 1
                continue

            data = envelope.get("data", {})
            ts = _ts(data.get("ts"), received_at)
            touched.append(ref.pk)

            if envelope.get("kind") == "alarm":
                level = self._SEVERITY_TO_LEVEL.get(
                    data.get("severity", "warning"), EventLevel.WARNING
                )
                pending.append(
                    DeviceEvent(
                        organization_id=ref.organization_id,
                        device_id=ref.pk,
                        ts=ts,
                        level=level,
                        code=(data.get("code") or "")[:64],
                        message=(data.get("message") or "")[:500],
                        payload=data.get("details") or {},
                    )
                )
                try:
                    if data.get("active", True):
                        self.shared.alerts.raise_device_alarm(
                            ref,
                            code=data.get("code", ""),
                            severity=data.get("severity", "warning"),
                            message=data.get("message", ""),
                            ts=ts,
                            details=data.get("details") or {},
                            device_name=self.shared.device_name(ref),
                        )
                        stats["alarms_raised"] += 1
                    else:
                        self.shared.alerts.clear_device_alarm(
                            ref, code=data.get("code", ""), ts=ts
                        )
                        stats["alarms_cleared"] += 1
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "device alarm handling failed",
                        extra={"device_id": ref.device_id},
                    )
            else:
                pending.append(
                    DeviceEvent(
                        organization_id=ref.organization_id,
                        device_id=ref.pk,
                        ts=ts,
                        level=data.get("level", EventLevel.INFO),
                        code=(data.get("code") or "")[:64],
                        message=(data.get("message") or "")[:500],
                        payload=data.get("data") or {},
                    )
                )
                stats["events"] += 1

        if pending:
            DeviceEvent.objects.bulk_create(pending, batch_size=500)
        if touched:
            Device.objects.filter(pk__in=touched).update(last_seen_at=received_at)
        return dict(stats)


# --------------------------------------------------------------------------
# Command acknowledgements
# --------------------------------------------------------------------------
class CommandAckProcessor:
    _STATUS_MAP = {
        "accepted": CommandStatus.ACCEPTED,
        "rejected": CommandStatus.REJECTED,
        "succeeded": CommandStatus.SUCCEEDED,
        "failed": CommandStatus.FAILED,
    }

    def __init__(self, shared: Shared) -> None:
        self.shared = shared

    def process(self, envelopes: list[dict[str, Any]]) -> dict[str, int]:
        received_at = timezone.now()
        stats: dict[str, int] = defaultdict(int)

        for envelope in envelopes:
            ref = self.shared.resolve(envelope)
            if ref is None:
                stats["skipped_unknown_device"] += 1
                continue

            data = envelope.get("data", {})
            raw_id = data.get("command_id", "")
            try:
                command_pk = uuid.UUID(str(raw_id))
            except (ValueError, TypeError):
                stats["bad_command_id"] += 1
                continue

            new_status = self._STATUS_MAP.get(data.get("status", ""))
            if new_status is None:
                stats["bad_status"] += 1
                continue

            ts = _ts(data.get("ts"), received_at)
            command = Command.objects.filter(pk=command_pk, device_id=ref.pk).first()
            if command is None:
                stats["unknown_command"] += 1
                logger.warning(
                    "ack for unknown command",
                    extra={"device_id": ref.device_id, "command_id": str(raw_id)},
                )
                continue

            # A late ACCEPTED must not overwrite a terminal SUCCEEDED.
            if command.is_terminal:
                stats["already_terminal"] += 1
                continue

            command.status = new_status
            command.response = data.get("result") or {}
            command.error = (data.get("message") or "")[:500] if new_status in (
                CommandStatus.REJECTED,
                CommandStatus.FAILED,
            ) else ""
            command.acked_at = command.acked_at or ts
            if new_status in (
                CommandStatus.SUCCEEDED,
                CommandStatus.REJECTED,
                CommandStatus.FAILED,
            ):
                command.completed_at = ts
            command.save(
                update_fields=[
                    "status",
                    "response",
                    "error",
                    "acked_at",
                    "completed_at",
                    "updated_at",
                ]
            )
            stats[f"ack_{new_status}"] += 1

        return dict(stats)
