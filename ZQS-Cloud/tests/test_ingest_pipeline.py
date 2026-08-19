"""End-to-end: MQTT payload -> validation -> bus -> worker -> database."""

from __future__ import annotations

import datetime as dt

import orjson
from django.test import TestCase

from apps.core.timeutils import now
from apps.devices.models import (
    Command,
    CommandStatus,
    ConnectionStatus,
    Device,
    DeviceEvent,
)
from apps.devices.registry import get_registry
from apps.telemetry.models import LatestSample, TelemetrySample
from services.bus import streams
from services.bus.memory import InMemoryBus
from services.ingestor.main import Ingestor
from services.mqtt import topics
from services.worker.processors import (
    CommandAckProcessor,
    EventProcessor,
    Shared,
    StatusProcessor,
    TelemetryProcessor,
)
from tests import factories


class PipelineTestCase(TestCase):
    """Drives the real ingestor and worker code over an in-memory bus."""

    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org)
        self.device = factories.device(
            self.org, "ZQS-TEST-0001", site_obj=self.site
        )
        get_registry().invalidate()

        self.bus = InMemoryBus()
        self.bus.connect()
        self.ingestor = Ingestor(bus=self.bus, forwarders=1)

        self.shared = Shared()
        self.processors = {
            streams.TELEMETRY: TelemetryProcessor(self.shared),
            streams.STATUS: StatusProcessor(self.shared),
            streams.EVENT: EventProcessor(self.shared),
            streams.ALARM: EventProcessor(self.shared),
            streams.COMMAND_ACK: CommandAckProcessor(self.shared),
        }

    def tearDown(self) -> None:
        self.bus.close()
        get_registry().invalidate()

    # ---- helpers ---------------------------------------------------------
    def publish(self, kind: str, payload: dict, *, device_id: str | None = None,
                retain: bool = False) -> None:
        topic = topics.device_topic(device_id or self.device.device_id, kind)
        self.ingestor.on_message(topic, orjson.dumps(payload), 1, retain)

    def drain(self) -> dict[str, int]:
        """Move everything the ingestor queued through the worker processors."""
        pending: list[tuple[str, dict]] = []
        while not self.ingestor.inbound.empty():
            pending.append(self.ingestor.inbound.get_nowait())

        grouped: dict[str, list[dict]] = {}
        for stream, envelope in pending:
            grouped.setdefault(streams.logical(stream), []).append(envelope)

        totals: dict[str, int] = {}
        for logical, envelopes in grouped.items():
            stats = self.processors[logical].process(envelopes)
            for key, value in (stats or {}).items():
                totals[key] = totals.get(key, 0) + value
        return totals

    # ---- tests -----------------------------------------------------------
    def test_telemetry_is_stored_and_latest_updated(self):
        timestamp = now().replace(microsecond=0)
        self.publish(
            topics.TELEMETRY,
            {
                "ts": int(timestamp.timestamp() * 1000),
                "seq": 1,
                "metrics": {"battery_soc": 78.5, "battery_power_w": -125000},
            },
        )
        stats = self.drain()

        self.assertEqual(stats.get("inserted"), 2)
        self.assertEqual(TelemetrySample.objects.count(), 2)

        soc = TelemetrySample.objects.get(metric_key="battery_soc")
        self.assertAlmostEqual(soc.value, 78.5)
        self.assertEqual(soc.ts, timestamp)
        self.assertEqual(soc.organization_id, self.org.id)

        latest = LatestSample.objects.get(metric_key="battery_soc")
        self.assertAlmostEqual(latest.value, 78.5)

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, ConnectionStatus.ONLINE)
        self.assertIsNotNone(self.device.last_telemetry_at)

    def test_redelivery_does_not_duplicate_samples(self):
        payload = {"ts": int(now().timestamp() * 1000), "metrics": {"battery_soc": 50.0}}
        self.publish(topics.TELEMETRY, payload)
        self.drain()

        # Same envelope again, as an at-least-once redelivery would produce.
        self.publish(topics.TELEMETRY, payload)
        self.drain()

        self.assertEqual(TelemetrySample.objects.filter(metric_key="battery_soc").count(), 1)

    def test_list_form_readings_are_accepted(self):
        base = now().replace(microsecond=0)
        self.publish(
            topics.TELEMETRY,
            {
                "ts": base.isoformat(),
                "readings": [
                    {"metric": "grid_power_w", "value": 1000},
                    {
                        "metric": "grid_power_w",
                        "value": 1200,
                        "ts": (base + dt.timedelta(seconds=10)).isoformat(),
                    },
                ],
            },
        )
        self.drain()
        self.assertEqual(TelemetrySample.objects.filter(metric_key="grid_power_w").count(), 2)

    def test_malformed_payload_is_rejected_at_the_edge(self):
        topic = topics.device_topic(self.device.device_id, topics.TELEMETRY)
        self.ingestor.on_message(topic, b"{not json", 1, False)
        self.ingestor.on_message(topic, orjson.dumps({"metrics": {"a": 1}}), 1, False)  # no ts

        self.assertTrue(self.ingestor.inbound.empty())
        self.assertEqual(TelemetrySample.objects.count(), 0)

    def test_unregistered_device_is_dropped(self):
        topic = topics.device_topic("NOT-REGISTERED", topics.TELEMETRY)
        self.ingestor.on_message(
            topic, orjson.dumps({"ts": int(now().timestamp()), "metrics": {"x": 1}}), 1, False
        )
        self.assertTrue(self.ingestor.inbound.empty())

    def test_timestamp_far_in_the_future_is_rejected(self):
        future = now() + dt.timedelta(days=2)
        self.publish(
            topics.TELEMETRY,
            {"ts": int(future.timestamp() * 1000), "metrics": {"battery_soc": 10}},
        )
        self.assertTrue(self.ingestor.inbound.empty())

    def test_status_offline_via_last_will(self):
        self.publish(topics.STATUS, {"status": "online", "firmware": "1.4.2", "ip": "10.0.0.9"})
        self.drain()
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, ConnectionStatus.ONLINE)
        self.assertEqual(self.device.firmware_version, "1.4.2")

        self.publish(topics.STATUS, {"status": "offline", "reason": "lwt"})
        self.drain()
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, ConnectionStatus.OFFLINE)
        self.assertEqual(self.device.status_events.count(), 2)

    def test_status_reports_device_location(self):
        self.publish(
            topics.STATUS,
            {
                "status": "online",
                "location": {
                    "latitude": 24.1477,
                    "longitude": 120.6736,
                    "address": "Taichung",
                },
            },
        )
        self.drain()
        self.device.refresh_from_db()
        self.assertAlmostEqual(self.device.latitude, 24.1477)
        self.assertEqual(self.device.location_source, "device")

    def test_device_event_is_recorded(self):
        self.publish(
            topics.EVENT,
            {"level": "warning", "code": "E0231", "message": "Fan speed low"},
        )
        self.drain()
        event = DeviceEvent.objects.get()
        self.assertEqual(event.code, "E0231")
        self.assertEqual(event.level, "warning")

    def test_command_ack_updates_the_command(self):
        command = Command.objects.create(
            organization=self.org,
            device=self.device,
            name="set_power_limit",
            params={"limit_w": 500},
            status=CommandStatus.SENT,
            expires_at=now() + dt.timedelta(minutes=5),
        )
        self.publish(
            topics.CONTROL_ACK,
            {"command_id": str(command.id), "status": "succeeded", "result": {"applied": 500}},
        )
        self.drain()

        command.refresh_from_db()
        self.assertEqual(command.status, CommandStatus.SUCCEEDED)
        self.assertEqual(command.response, {"applied": 500})
        self.assertIsNotNone(command.completed_at)

    def test_late_ack_does_not_regress_a_terminal_command(self):
        command = Command.objects.create(
            organization=self.org,
            device=self.device,
            name="set_power_limit",
            status=CommandStatus.SUCCEEDED,
            expires_at=now() + dt.timedelta(minutes=5),
        )
        self.publish(
            topics.CONTROL_ACK, {"command_id": str(command.id), "status": "accepted"}
        )
        self.drain()
        command.refresh_from_db()
        self.assertEqual(command.status, CommandStatus.SUCCEEDED)

    def test_disabled_device_is_ignored(self):
        Device.objects.filter(pk=self.device.pk).update(is_enabled=False)
        get_registry().invalidate()
        self.publish(
            topics.TELEMETRY,
            {"ts": int(now().timestamp() * 1000), "metrics": {"battery_soc": 1}},
        )
        self.assertTrue(self.ingestor.inbound.empty())
