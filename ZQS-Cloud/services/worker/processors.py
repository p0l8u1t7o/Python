"""Batch processor consuming Sparkplug envelopes from the message bus.

One processor, not one per message kind. A Sparkplug DDATA says only that
something reported; what it reported is decided metric by metric after the
alias table is applied. So the fan-out happens here, below the alias lookup,
rather than in the ingestor above it - up there the names may not exist yet.

The batch is still processed as a batch: 500 envelopes become a handful of
statements, not 500 round trips. And every path is idempotent, because
at-least-once redelivery must not double-count.
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
from apps.ems.outage import OUTAGE_CODE, OutageDetector
from apps.devices.models import (
    CapabilitySource,
    Command,
    CommandStatus,
    ConnectionStatus,
    DeclarationState,
    Device,
    DeviceDeclaration,
    DeviceEvent,
    DeviceStatusEvent,
    EdgeNode,
    EventLevel,
    LifecycleState,
    MetricAlias,
    declaration_diff,
)
from apps.devices.registry import DeviceRef, EdgeNodeRef, get_registry
from apps.telemetry import autoregister
from apps.telemetry.catalog import get_catalog
from apps.telemetry.models import Quality
from apps.telemetry.policy import PolicyResolver, SampleGate
from apps.telemetry.repository import SampleRow, insert_samples, upsert_latest
from services.sparkplug import profile
from services.sparkplug.payload import SEQ_MODULUS, next_seq
from services.sparkplug.topics import MessageType

logger = get_logger("worker.processors")

def _ts(value: Any, fallback: dt.datetime) -> dt.datetime:
    try:
        return parse_timestamp(value)
    except Exception:  # noqa: BLE001 - the ingestor already validated this
        return fallback


class AliasTable:
    """In-process cache over :class:`MetricAlias`, loaded lazily per owner.

    An owner is ``(edge_node_pk, device_pk_or_None)``, matching the scope
    Sparkplug gives aliases: they are unique within a node for node metrics and
    within a device for device metrics, and nothing says the two cannot collide.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[uuid.UUID, uuid.UUID | None], dict[int, str]] = {}

    def names(
        self, edge_node_pk: uuid.UUID, device_pk: uuid.UUID | None
    ) -> dict[int, str]:
        key = (edge_node_pk, device_pk)
        table = self._cache.get(key)
        if table is None:
            rows = MetricAlias.objects.filter(
                edge_node_id=edge_node_pk, device_id=device_pk
            ).values_list("alias", "name")
            table = {int(alias): name for alias, name in rows}
            self._cache[key] = table
        return table

    def replace(
        self,
        edge_node_pk: uuid.UUID,
        device_pk: uuid.UUID | None,
        metrics: list[dict[str, Any]],
    ) -> int:
        """Rewrite the table from a BIRTH. Aliases dropped by the birth go away.

        A full replace rather than an upsert on purpose: a birth is defined as
        the *complete* set of metrics the publisher offers, so an alias missing
        from it has been retired. Leaving it behind would let a stale mapping
        decode a future message into a metric the device no longer reports.
        """
        entries = [
            (int(m["alias"]), m["name"], int(m.get("datatype") or 0))
            for m in metrics
            if m.get("alias") is not None and m.get("name")
        ]
        with transaction.atomic():
            MetricAlias.objects.filter(
                edge_node_id=edge_node_pk, device_id=device_pk
            ).delete()
            if entries:
                MetricAlias.objects.bulk_create(
                    [
                        MetricAlias(
                            edge_node_id=edge_node_pk,
                            device_id=device_pk,
                            alias=alias,
                            name=name,
                            datatype=datatype,
                        )
                        for alias, name, datatype in entries
                    ],
                    batch_size=500,
                )
        self._cache[(edge_node_pk, device_pk)] = {a: n for a, n, _ in entries}
        return len(entries)

    def forget(self, edge_node_pk: uuid.UUID, device_pk: uuid.UUID | None) -> None:
        self._cache.pop((edge_node_pk, device_pk), None)

    def invalidate(self) -> None:
        self._cache.clear()


class Shared:
    """Caches shared by every processor in a worker process."""

    def __init__(self) -> None:
        self.registry = get_registry()
        self.catalog = get_catalog()
        self.policies = PolicyResolver()
        self.gate = SampleGate()
        self.alerts = AlertEngine()
        self.aliases = AliasTable()
        self.outages = OutageDetector()
        self._device_names: dict[uuid.UUID, str] = {}

    # ---- resolution ------------------------------------------------------
    def resolve_node(self, envelope: dict[str, Any]) -> EdgeNodeRef | None:
        group_id = envelope.get("group_id") or ""
        node_id = envelope.get("edge_node_id") or ""
        if not group_id or not node_id:
            return None
        ref = self.registry.get_node(group_id, node_id)
        if ref is not None:
            return ref
        if not settings.INGEST["AUTO_PROVISION"]:
            return None
        return self._provision_node(group_id, node_id)

    def resolve_device(
        self, node: EdgeNodeRef, envelope: dict[str, Any]
    ) -> DeviceRef | None:
        device_id = envelope.get("device_id") or ""
        if not device_id:
            return None
        ref = self.registry.get_device(node.pk, device_id)
        if ref is not None:
            return ref
        if not settings.INGEST["AUTO_PROVISION"]:
            return None
        return self._provision_device(node, device_id)

    def _provision_node(self, group_id: str, node_id: str) -> EdgeNodeRef | None:
        from apps.accounts.models import Organization

        organization = Organization.objects.filter(slug=group_id, is_active=True).first()
        if organization is None:
            # The group id is the organisation slug, so an unknown group is not
            # a device to adopt - it is traffic for a tenant that is not here.
            logger.error(
                "auto-provision skipped: no organization for group",
                extra={"group_id": group_id, "node_id": node_id},
            )
            return None

        node, created = EdgeNode.objects.get_or_create(
            group_id=group_id,
            node_id=node_id,
            deleted_at__isnull=True,
            defaults={
                "organization": organization,
                "name": node_id,
                "description": "Auto-provisioned on first uplink",
            },
        )
        if created:
            logger.info(
                "auto-provisioned edge node",
                extra={"group_id": group_id, "node_id": node_id},
            )
        self.registry.invalidate()
        return self.registry.get_node(group_id, node_id)

    def _provision_device(self, node: EdgeNodeRef, device_id: str) -> DeviceRef | None:
        # Quarantined, not trusted: telemetry is accepted so an operator can
        # see what the thing reports, but every capability is off and the
        # device is marked pending, so dispatch commands are refused until
        # someone confirms it. is_enabled stays True on purpose - disabling it
        # would drop the very data needed to judge what it is.
        device, created = Device.objects.get_or_create(
            edge_node_id=node.pk,
            device_id=device_id,
            defaults={
                "organization_id": node.organization_id,
                "site_id": node.site_id,
                "name": device_id,
                "description": "Auto-provisioned on first uplink",
                "status": ConnectionStatus.UNKNOWN,
                "commissioning_state": LifecycleState.PENDING,
                "can_charge": False,
                "can_discharge": False,
                "can_export": False,
                "is_dispatchable": False,
                "capability_source": CapabilitySource.MANUAL,
            },
        )
        if created:
            logger.info("auto-provisioned device", extra={"device_id": device_id})
        self.registry.invalidate()
        return self.registry.get_device(node.pk, device_id)

    def device_name(self, ref: DeviceRef) -> str:
        name = self._device_names.get(ref.pk)
        if name is None:
            name = (
                Device.objects.filter(pk=ref.pk).values_list("name", flat=True).first()
                or ref.device_id
            )
            self._device_names[ref.pk] = name
        return name

    def invalidate(self) -> None:
        self.outages.invalidate()
        self.registry.invalidate()
        self.policies.invalidate()
        self.catalog.invalidate()
        self.alerts.rules.invalidate()
        self.aliases.invalidate()
        self._device_names.clear()


# --------------------------------------------------------------------------
# The processor
# --------------------------------------------------------------------------
class SparkplugProcessor:
    _ACK_STATUS = {
        "accepted": CommandStatus.ACCEPTED,
        "rejected": CommandStatus.REJECTED,
        "succeeded": CommandStatus.SUCCEEDED,
        "failed": CommandStatus.FAILED,
    }

    _SEVERITY_TO_LEVEL = {
        "info": EventLevel.INFO,
        "warning": EventLevel.WARNING,
        "major": EventLevel.ERROR,
        "critical": EventLevel.CRITICAL,
    }

    def __init__(self, shared: Shared) -> None:
        self.shared = shared

    # ---- entry point -----------------------------------------------------
    def process(self, envelopes: list[dict[str, Any]]) -> dict[str, int]:
        received_at = timezone.now()
        stats: dict[str, int] = defaultdict(int)

        rows: list[SampleRow] = []
        latest_rows: list[SampleRow] = []
        alert_inputs: list[tuple[DeviceRef, str, float | None, dt.datetime]] = []
        events: list[DeviceEvent] = []
        last_seen: dict[uuid.UUID, dt.datetime] = {}
        node_seen: dict[uuid.UUID, dt.datetime] = {}
        rebirth_needed: dict[uuid.UUID, str] = {}

        for envelope in envelopes:
            node = self.shared.resolve_node(envelope)
            if node is None:
                stats["skipped_unknown_node"] += 1
                continue

            try:
                kind = MessageType(envelope.get("kind", ""))
            except ValueError:
                stats["skipped_unknown_kind"] += 1
                continue
            data = envelope.get("data") or {}
            node_seen[node.pk] = received_at

            if kind is MessageType.NDEATH:
                self._handle_node_death(node, data, received_at, stats)
                # Data from this node earlier in the same batch must not put
                # its devices back online at the end of the batch: the death
                # came later and wins. Data *after* the death re-adds them.
                for ref in self.shared.registry.devices_of(node.pk):
                    last_seen.pop(ref.pk, None)
                continue

            gap = self._check_sequence(node, kind, data, stats)
            if gap:
                rebirth_needed[node.pk] = gap

            if kind is MessageType.NBIRTH:
                self._handle_node_birth(node, data, received_at, stats)
                continue

            # Advance the counter for every remaining type. Doing this only
            # where readings are stored would make an NDATA or a DDEATH look
            # like a lost message to the next check.
            self._store_seq(node.pk, data)

            device = self.shared.resolve_device(node, envelope) if envelope.get(
                "device_id"
            ) else None

            if kind is MessageType.DDEATH:
                if device is not None:
                    self._handle_device_death(device, data, received_at, stats)
                    last_seen.pop(device.pk, None)
                continue

            if kind is MessageType.DBIRTH:
                if device is None:
                    stats["skipped_unknown_device"] += 1
                    continue
                self._handle_device_birth(node, device, data, received_at, stats)
                # A birth also reports values, so fall through to the metric
                # handling below rather than returning here.

            if kind is MessageType.NDATA:
                # Node-level readings have no device to attach to. They are
                # accepted and counted, but nothing in this platform's data
                # model stores a metric that belongs to a connection rather
                # than to equipment, so they stop here.
                stats["node_data_ignored"] += 1
                continue

            if device is None:
                stats["skipped_unknown_device"] += 1
                continue
            if not device.is_enabled:
                stats["skipped_disabled"] += 1
                continue

            self._handle_metrics(
                node=node,
                device=device,
                data=data,
                received_at=received_at,
                rows=rows,
                latest_rows=latest_rows,
                alert_inputs=alert_inputs,
                events=events,
                last_seen=last_seen,
                rebirth_needed=rebirth_needed,
                stats=stats,
            )

        if rows or latest_rows:
            with transaction.atomic():
                if rows:
                    stats["inserted"] = insert_samples(rows)
                if latest_rows:
                    upsert_latest(latest_rows, updated_at=received_at)
        if events:
            DeviceEvent.objects.bulk_create(events, batch_size=500)
            # Channels can subscribe to device events directly (not only to
            # rule-engine alerts); queue those deliveries now that the events
            # have primary keys.
            from services.worker.notifications import queue_event_notifications

            queue_event_notifications(events)

        self._touch(node_seen, last_seen, received_at)
        self._evaluate_alerts(alert_inputs, stats)
        self._request_rebirths(rebirth_needed, stats)
        return dict(stats)

    # ---- sequence --------------------------------------------------------
    def _check_sequence(
        self, node: EdgeNodeRef, kind: MessageType, data: dict[str, Any], stats: dict
    ) -> str:
        """Compare the payload ``seq`` with what should have followed.

        A gap means messages were lost, which matters far more under Sparkplug
        than it looks: the alias table may no longer describe what the publisher
        thinks it published, so later readings could be filed under the wrong
        metric. The only sanctioned recovery is to ask for a rebirth.

        A spurious request is cheap - the node simply re-announces - so this
        errs towards asking. With several worker replicas sharing a consumer
        group, messages from one node can genuinely be examined out of order,
        and asking is still the right answer.
        """
        seq = data.get("seq")
        if seq is None:
            stats["seq_missing"] += 1
            return ""

        if kind is MessageType.NBIRTH:
            # The specification pins NBIRTH to zero; anything else means the
            # publisher's own counter is broken.
            if seq != 0:
                stats["seq_birth_not_zero"] += 1
                return "nbirth_seq_not_zero"
            return ""

        stored = EdgeNode.objects.filter(pk=node.pk).values_list(
            "last_seq", flat=True
        ).first()
        expected = next_seq(stored)
        if stored is not None and seq != expected:
            stats["seq_gap"] += 1
            logger.warning(
                "sparkplug sequence gap",
                extra={"node_id": node.node_id, "expected": expected, "got": seq},
            )
            return f"seq_gap:{expected}!={seq}"
        return ""

    def _store_seq(self, node_pk: uuid.UUID, data: dict[str, Any]) -> None:
        seq = data.get("seq")
        if seq is not None:
            EdgeNode.objects.filter(pk=node_pk).update(last_seq=int(seq) % SEQ_MODULUS)

    def _request_rebirths(self, needed: dict[uuid.UUID, str], stats: dict) -> None:
        if not needed:
            return
        from apps.devices.edge_nodes import request_rebirth

        for node_pk, reason in needed.items():
            node = EdgeNode.objects.filter(pk=node_pk).first()
            if node is None:
                continue
            try:
                if request_rebirth(node, reason=reason):
                    stats["rebirth_requested"] += 1
            except Exception:  # noqa: BLE001 - never stop ingest for this
                logger.exception("rebirth request failed", extra={"node": node.node_id})

    # ---- births and deaths ----------------------------------------------
    def _handle_node_birth(
        self,
        node: EdgeNodeRef,
        data: dict[str, Any],
        received_at: dt.datetime,
        stats: dict,
    ) -> None:
        ts = _ts(data.get("timestamp"), received_at)
        metrics = data.get("metrics") or []
        status_fields = profile.build_status_fields(
            [_as_metric_view(m, m.get("name") or "") for m in metrics]
        )

        updates: dict[str, Any] = {
            "status": ConnectionStatus.ONLINE,
            "status_changed_at": ts,
            "last_seen_at": received_at,
            "birth_at": ts,
            "bd_seq": _clamp_bd_seq(data.get("bd_seq")),
            "last_seq": 0,
            "rebirth_requested_at": None,
        }
        for field, key in (
            ("firmware_version", "firmware"),
            ("hardware_version", "hardware"),
        ):
            if status_fields.get(key):
                updates[field] = str(status_fields[key])[:64]
        if status_fields.get("ip"):
            updates["ip_address"] = status_fields["ip"]
        if status_fields.get("rssi") is not None:
            updates["rssi"] = int(status_fields["rssi"])

        EdgeNode.objects.filter(pk=node.pk).update(**updates)
        self.shared.aliases.replace(node.pk, None, metrics)
        stats["node_births"] += 1
        logger.info("edge node birth", extra={"node_id": node.node_id})

    def _handle_node_death(
        self,
        node: EdgeNodeRef,
        data: dict[str, Any],
        received_at: dt.datetime,
        stats: dict,
    ) -> None:
        """A node death takes every device on it offline too.

        Sparkplug is explicit that a node's devices are unreachable once the
        node is, and the devices themselves cannot say so - the connection that
        would carry their DDEATH is the one that just ended.
        """
        ts = _ts(data.get("timestamp"), received_at)
        declared = _clamp_bd_seq(data.get("bd_seq"))
        current = (
            EdgeNode.objects.filter(pk=node.pk).values_list("bd_seq", flat=True).first()
        )

        # ``bdSeq`` is what makes a death safe to act on. A death carrying an
        # older value belongs to a session that has already been replaced, and
        # obeying it would knock a node that has just reconnected offline.
        if declared is not None and current is not None and declared != current:
            stats["ndeath_stale"] += 1
            logger.info(
                "ignoring NDEATH from a superseded session",
                extra={"node_id": node.node_id, "declared": declared, "current": current},
            )
            return

        EdgeNode.objects.filter(pk=node.pk).update(
            status=ConnectionStatus.OFFLINE,
            status_changed_at=ts,
            last_seen_at=received_at,
            last_seq=None,
        )

        device_pks = [ref.pk for ref in self.shared.registry.devices_of(node.pk)]
        if device_pks:
            offline = Device.objects.filter(pk__in=device_pks).exclude(
                status=ConnectionStatus.OFFLINE
            )
            transitioned = list(offline.values_list("pk", flat=True))
            offline.update(status=ConnectionStatus.OFFLINE, status_changed_at=ts)
            DeviceStatusEvent.objects.bulk_create(
                [
                    DeviceStatusEvent(
                        device_id=pk,
                        status=ConnectionStatus.OFFLINE,
                        previous_status=ConnectionStatus.ONLINE,
                        reason="node_death",
                        ts=ts,
                        payload={"edge_node": node.node_id},
                    )
                    for pk in transitioned
                ]
            )
            stats["devices_offline_by_node_death"] += len(transitioned)

        stats["node_deaths"] += 1
        logger.info("edge node death", extra={"node_id": node.node_id})

    def _handle_device_birth(
        self,
        node: EdgeNodeRef,
        device: DeviceRef,
        data: dict[str, Any],
        received_at: dt.datetime,
        stats: dict,
    ) -> None:
        ts = _ts(data.get("timestamp"), received_at)
        metrics = data.get("metrics") or []
        views = [_as_metric_view(m, m.get("name") or "") for m in metrics]

        previous = (
            Device.objects.filter(pk=device.pk).values_list("status", flat=True).first()
        )
        updates: dict[str, Any] = {
            "status": ConnectionStatus.ONLINE,
            "last_seen_at": received_at,
        }
        if previous != ConnectionStatus.ONLINE:
            updates["status_changed_at"] = ts

        status_fields = profile.build_status_fields(views)
        for field, key in (
            ("firmware_version", "firmware"),
            ("hardware_version", "hardware"),
        ):
            if status_fields.get(key):
                updates[field] = str(status_fields[key])[:64]
        if status_fields.get("ip"):
            updates["ip_address"] = status_fields["ip"]
        if status_fields.get("rssi") is not None:
            updates["rssi"] = int(status_fields["rssi"])
        if (
            status_fields.get("latitude") is not None
            and status_fields.get("longitude") is not None
        ):
            updates["latitude"] = float(status_fields["latitude"])
            updates["longitude"] = float(status_fields["longitude"])
            updates["address"] = str(status_fields.get("address") or "")[:400]
            updates["location_source"] = "device"
            updates["location_updated_at"] = ts

        Device.objects.filter(pk=device.pk).update(**updates)
        self.shared.aliases.replace(node.pk, device.pk, metrics)

        # Plug and play: the birth already names every metric and states its
        # datatype and unit, so a device nobody has configured can describe
        # itself into the catalogue and its charts come up labelled.
        #
        # This registers *labels*, never permissions. Capabilities and ratings
        # still go through DeviceDeclaration and wait for a human.
        try:
            added = autoregister.register_from_birth(device.organization_id, metrics)
            if added:
                stats["metrics_registered"] += added
                self.shared.catalog.invalidate()
        except Exception:  # noqa: BLE001 - a bad birth must not stop ingest
            logger.exception(
                "metric auto-registration failed",
                extra={"device_id": device.device_id},
            )

        if previous != ConnectionStatus.ONLINE:
            DeviceStatusEvent.objects.create(
                device_id=device.pk,
                status=ConnectionStatus.ONLINE,
                previous_status=previous or ConnectionStatus.UNKNOWN,
                reason="dbirth",
                ts=ts,
            )

        declaration = profile.build_declaration(views)
        if declaration:
            try:
                self._record_declaration(device, declaration, ts)
            except Exception:  # noqa: BLE001 - a bad claim must not stop ingest
                logger.exception(
                    "declaration handling failed",
                    extra={"device_id": device.device_id},
                )
                stats["declaration_failed"] += 1

        stats["device_births"] += 1

    def _handle_device_death(
        self,
        device: DeviceRef,
        data: dict[str, Any],
        received_at: dt.datetime,
        stats: dict,
    ) -> None:
        ts = _ts(data.get("timestamp"), received_at)
        previous = (
            Device.objects.filter(pk=device.pk).values_list("status", flat=True).first()
        )
        Device.objects.filter(pk=device.pk).update(
            status=ConnectionStatus.OFFLINE,
            status_changed_at=ts,
            last_seen_at=received_at,
        )
        if previous != ConnectionStatus.OFFLINE:
            DeviceStatusEvent.objects.create(
                device_id=device.pk,
                status=ConnectionStatus.OFFLINE,
                previous_status=previous or ConnectionStatus.UNKNOWN,
                reason="ddeath",
                ts=ts,
            )
        stats["device_deaths"] += 1

    # ---- metrics ---------------------------------------------------------
    def _handle_metrics(
        self,
        *,
        node: EdgeNodeRef,
        device: DeviceRef,
        data: dict[str, Any],
        received_at: dt.datetime,
        rows: list[SampleRow],
        latest_rows: list[SampleRow],
        alert_inputs: list,
        events: list[DeviceEvent],
        last_seen: dict[uuid.UUID, dt.datetime],
        rebirth_needed: dict[uuid.UUID, str],
        stats: dict,
    ) -> None:
        aliases = self.shared.aliases.names(node.pk, device.pk)
        policy = self.shared.policies.for_device(device)
        self.shared.gate.seed_device(device.pk)

        payload_ts = _ts(data.get("timestamp"), received_at)
        resolved: list[tuple[str, dict[str, Any]]] = []
        unresolved = 0

        for metric in data.get("metrics") or []:
            name = metric.get("name") or ""
            if not name and metric.get("alias") is not None:
                name = aliases.get(int(metric["alias"]), "")
            if not name:
                unresolved += 1
                continue
            resolved.append((name, metric))

        if unresolved:
            stats["unresolved_aliases"] += unresolved
            # An alias with no entry means this host never saw the birth that
            # defined it - a worker started after the device, or an alias table
            # lost with the database. Asking for a rebirth is the only way to
            # learn what it meant; discarding it silently would drop real
            # measurements and the stream would never recover on its own.
            rebirth_needed.setdefault(node.pk, f"unresolved_alias:{unresolved}")

        ack = profile.as_command_ack(
            [
                _as_metric_view(m, name)
                for name, m in resolved
                if name.startswith(profile.COMMAND_PREFIX)
            ]
        )
        if ack:
            self._apply_command_ack(device, ack, payload_ts, stats)

        for name, metric in resolved:
            view = _as_metric_view(metric, name)
            ts = _ts(metric.get("ts"), payload_ts)

            if name.startswith(profile.ALARM_PREFIX):
                alarm = profile.as_alarm(view)
                if alarm:
                    self._apply_alarm(device, alarm, ts, events, stats)
                continue

            if name.startswith(profile.EVENT_PREFIX):
                event = profile.as_event(view)
                if event:
                    events.append(
                        DeviceEvent(
                            organization_id=device.organization_id,
                            device_id=device.pk,
                            ts=ts,
                            level=event["level"],
                            code=event["code"],
                            message=event["message"],
                            payload=event["data"],
                        )
                    )
                    stats["events"] += 1
                continue

            reading = profile.as_reading(view, name)
            if reading is None:
                continue

            metric_key = reading["metric"]
            value = reading["value"]
            text = reading["text"]

            # Alerts see every reading. A deadband is a storage decision;
            # letting it hide a threshold breach would be a safety bug.
            alert_inputs.append((device, metric_key, value, ts))
            self._observe_outage(device, metric_key, value, ts, events, stats)

            current = last_seen.get(device.pk)
            if current is None or ts > current:
                last_seen[device.pk] = ts

            # ``is_transient`` is the publisher saying "show this, do not keep
            # it". Honouring it is the difference between a time series and a
            # log of every momentary blip.
            if metric.get("is_transient"):
                stats["transient"] += 1
                continue

            rule = policy.rule_for(metric_key)
            if rule is None:
                stats["filtered_by_policy"] += 1
                continue

            definition = self.shared.catalog.get(device.organization_id, metric_key)
            quality = (
                Quality.GOOD
                if definition is None or definition.is_plausible(value)
                else Quality.SUSPECT
            )
            if quality == Quality.SUSPECT:
                stats["suspect"] += 1

            row = SampleRow(
                organization_id=device.organization_id,
                device_id=device.pk,
                metric_key=metric_key,
                ts=ts,
                value=value,
                value_text=text,
                quality=int(quality),
            )

            # The latest-value table tracks *every* reading. The deadband
            # below decides how densely history is stored; it must not decide
            # whether the device "reported" - a steady SOC that never crosses
            # the deadband used to stop refreshing its timestamp and then read
            # as stale, and the control engine refused to act on it.
            latest_rows.append(row)

            if not self.shared.gate.should_store(
                device.pk, metric_key, ts, value, text, rule
            ):
                stats["filtered_by_deadband"] += 1
                continue

            rows.append(row)
            self.shared.gate.mark_stored(device.pk, metric_key, ts, value, text)

    # ---- grid outage (W6) ------------------------------------------------
    def _observe_outage(
        self, device: DeviceRef, metric_key: str, value: float | None, ts: dt.datetime,
        events: list[DeviceEvent], stats: dict,
    ) -> None:
        """關口電壓餵給停電偵測；狀態改變時發事件與告警。"""
        try:
            transition = self.shared.outages.observe(device.pk, metric_key, value, ts)
        except Exception:  # noqa: BLE001 - 偵測失敗不能擋住遙測入庫
            logger.exception("outage detection failed", extra={"device_id": device.device_id})
            return
        if not (transition.started or transition.ended):
            return
        outage = transition.outage
        if transition.started:
            message = f"Grid outage: voltage {outage.voltage_v:g} V below {outage.threshold_v:g} V"
            events.append(DeviceEvent(
                organization_id=device.organization_id, device_id=device.pk, ts=ts,
                level=EventLevel.CRITICAL, code=OUTAGE_CODE, message=message,
                payload={"alarm_state": "active", "alarm_level": EventLevel.CRITICAL,
                         "site_id": str(outage.site_id), "started_at": outage.started_at.isoformat()},
            ))
            self.shared.alerts.raise_device_alarm(
                device, code=OUTAGE_CODE, severity="critical", message=message, ts=ts,
                details={"site_id": str(outage.site_id), "voltage_v": outage.voltage_v},
                device_name=self.shared.device_name(device),
            )
            stats["outages_started"] += 1
        else:
            events.append(DeviceEvent(
                organization_id=device.organization_id, device_id=device.pk, ts=ts,
                level=EventLevel.INFO, code=OUTAGE_CODE, message="Grid restored",
                payload={"alarm_state": "cleared", "alarm_level": EventLevel.CRITICAL,
                         "site_id": str(outage.site_id), "ended_at": ts.isoformat()},
            ))
            self.shared.alerts.clear_device_alarm(device, code=OUTAGE_CODE, ts=ts)
            stats["outages_ended"] += 1

    # ---- alarms and acknowledgements -------------------------------------
    def _apply_alarm(
        self,
        device: DeviceRef,
        alarm: dict[str, Any],
        ts: dt.datetime,
        events: list[DeviceEvent],
        stats: dict,
    ) -> None:
        # Set and clear are both logged, but they must not read the same: a
        # clear is an "info" line that says so, and carries the level it was
        # raised at so the notification gate still lets it through.
        raised_level = self._SEVERITY_TO_LEVEL.get(alarm["severity"], EventLevel.WARNING)
        events.append(
            DeviceEvent(
                organization_id=device.organization_id,
                device_id=device.pk,
                ts=ts,
                level=raised_level if alarm["active"] else EventLevel.INFO,
                code=alarm["code"],
                message=alarm["message"],
                payload={
                    **(alarm["details"] or {}),
                    "alarm_state": "active" if alarm["active"] else "cleared",
                    "alarm_level": raised_level,
                },
            )
        )
        try:
            if alarm["active"]:
                self.shared.alerts.raise_device_alarm(
                    device,
                    code=alarm["code"],
                    severity=alarm["severity"],
                    message=alarm["message"],
                    ts=ts,
                    details=alarm["details"],
                    device_name=self.shared.device_name(device),
                )
                stats["alarms_raised"] += 1
            else:
                self.shared.alerts.clear_device_alarm(
                    device, code=alarm["code"], ts=ts
                )
                stats["alarms_cleared"] += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "device alarm handling failed", extra={"device_id": device.device_id}
            )

    def _apply_command_ack(
        self,
        device: DeviceRef,
        ack: dict[str, Any],
        ts: dt.datetime,
        stats: dict,
    ) -> None:
        try:
            command_pk = uuid.UUID(str(ack["command_id"]))
        except (ValueError, TypeError):
            stats["bad_command_id"] += 1
            return

        new_status = self._ACK_STATUS.get(ack["status"])
        if new_status is None:
            stats["bad_status"] += 1
            return

        command = Command.objects.filter(pk=command_pk, device_id=device.pk).first()
        if command is None:
            stats["unknown_command"] += 1
            logger.warning(
                "ack for unknown command",
                extra={"device_id": device.device_id, "command_id": ack["command_id"]},
            )
            return

        # A late ACCEPTED must not overwrite a terminal SUCCEEDED.
        if command.is_terminal:
            stats["already_terminal"] += 1
            return

        command.status = new_status
        command.response = ack.get("result") or {}
        command.error = (
            (ack.get("message") or "")[:500]
            if new_status in (CommandStatus.REJECTED, CommandStatus.FAILED)
            else ""
        )
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

    # ---- declarations ----------------------------------------------------
    def _record_declaration(
        self, device: DeviceRef, attributes: dict[str, Any], ts: dt.datetime
    ) -> None:
        """Store what the device claims. Never act on it.

        Nothing here writes a capability, a rating or a cost model. The values
        land in ``DeviceDeclaration`` and wait for an operator, because a unit
        that has been tampered with would otherwise be able to grant itself the
        very permission the capability check exists to withhold.

        The declaration is simply the identity metrics of the DBIRTH. A birth
        is *defined* as everything the device offers, so there is no second,
        optional place for a device to describe itself - and therefore no way
        for the two to disagree.
        """
        model = Device.objects.filter(pk=device.pk).first()
        if model is None:
            return

        # Under Sparkplug the metric *names* are the schema, and the names are
        # defined by this profile - so a device claiming a version this host
        # does not implement may be using the same names for different things.
        # Recording it anyway would put an unreadable claim in front of an
        # operator as if it were understood.
        version = attributes.get("schema_version")
        if version != profile.PROFILE_VERSION:
            DeviceEvent.objects.create(
                organization_id=model.organization_id,
                device=model,
                ts=ts,
                level=EventLevel.WARNING,
                code="declaration.unsupported_version",
                message=f"Unsupported declaration schema_version {version!r}",
                payload={"schema_version": version},
            )
            return

        existing = DeviceDeclaration.objects.filter(device=model).first()
        # Devices republish their birth on every reconnect. Re-raising an
        # identical claim each time would bury the operator in noise and train
        # them to ignore it.
        if existing is not None and existing.payload == attributes:
            DeviceDeclaration.objects.filter(pk=existing.pk).update(received_at=ts)
            return

        diff = declaration_diff(model, attributes)
        identity_mismatch = "category" in diff
        if existing is not None:
            DeviceDeclaration.objects.filter(pk=existing.pk).delete()

        DeviceDeclaration.objects.create(
            device=model,
            payload=attributes,
            schema_version=profile.PROFILE_VERSION,
            received_at=ts,
            state=DeclarationState.MISMATCHED if diff else DeclarationState.MATCHED,
            diff_summary=diff,
            identity_mismatch=identity_mismatch,
        )

        if identity_mismatch:
            # The equipment on the wire says it is a different kind of thing
            # than the register says. Under the "category never changes" policy
            # that means the hardware was probably swapped without registering
            # a replacement - so the data keeps flowing, but commands stop.
            DeviceEvent.objects.create(
                organization_id=model.organization_id,
                device=model,
                ts=ts,
                level=EventLevel.ERROR,
                code="declaration.identity_mismatch",
                message=(
                    f"Device declares category {diff['category']['declared']!r} "
                    f"but is registered as {diff['category']['effective']!r}"
                ),
                payload={"diff": diff},
            )
        elif diff:
            DeviceEvent.objects.create(
                organization_id=model.organization_id,
                device=model,
                ts=ts,
                level=EventLevel.WARNING,
                code="declaration.changed",
                message="Device declaration differs from the confirmed configuration",
                payload={"diff": diff},
            )
        else:
            DeviceEvent.objects.create(
                organization_id=model.organization_id,
                device=model,
                ts=ts,
                level=EventLevel.NOTICE,
                code="declaration.changed",
                message="Device declaration received",
                payload={"diff": {}},
            )

    # ---- bookkeeping -----------------------------------------------------
    def _touch(
        self,
        node_seen: dict[uuid.UUID, dt.datetime],
        last_seen: dict[uuid.UUID, dt.datetime],
        received_at: dt.datetime,
    ) -> None:
        if node_seen:
            EdgeNode.objects.filter(pk__in=list(node_seen)).update(
                last_seen_at=received_at
            )
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
                        reason="ddata",
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
# Helpers
# --------------------------------------------------------------------------
def _clamp_bd_seq(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value) % SEQ_MODULUS
    except (TypeError, ValueError):
        return None


def _as_metric_view(metric: dict[str, Any], name: str = ""):
    """Rebuild the codec's view from the JSON envelope the bus carried.

    The envelope crosses a process boundary as JSON, so the dataclass has to be
    reconstructed rather than passed through. Cheap, and it keeps the profile
    module working on one type whether it is called from the ingestor or here.

    ``name`` overrides what the payload carried, because after an alias lookup
    the resolved name is the real one - and a view built without it would have
    an empty name, which every classifier reads as "an ordinary measurement".
    """
    from services.sparkplug.datatypes import DataType
    from services.sparkplug.payload import MetricView

    try:
        datatype = DataType(int(metric.get("datatype") or 0))
    except ValueError:
        datatype = DataType.Unknown

    return MetricView(
        name=name or metric.get("name") or "",
        alias=metric.get("alias"),
        datatype=datatype,
        value=metric.get("value"),
        timestamp=None,
        is_null=bool(metric.get("is_null")),
        is_historical=bool(metric.get("is_historical")),
        is_transient=bool(metric.get("is_transient")),
        properties=metric.get("properties") or {},
    )
