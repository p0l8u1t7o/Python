"""End-to-end: Sparkplug payload -> validation -> bus -> worker -> database.

Drives the real ingestor and the real worker over an in-memory bus, publishing
genuine protobuf. Nothing here hand-builds an envelope: if the encoder and the
decoder disagree, these tests are supposed to notice.
"""

from __future__ import annotations

import datetime as dt
from unittest import mock

from django.test import TestCase

from apps.core.timeutils import now
from apps.devices.models import (
    Command,
    CommandStatus,
    ConnectionStatus,
    Device,
    DeviceEvent,
    MetricAlias,
)
from apps.devices.registry import get_registry
from apps.telemetry.models import LatestSample, TelemetrySample
from services.bus import streams
from services.bus.memory import InMemoryBus
from services.ingestor.main import Ingestor
from services.sparkplug import payload as sp
from services.sparkplug import topics
from services.sparkplug.datatypes import DataType
from services.sparkplug.topics import MessageType
from services.worker.processors import Shared, SparkplugProcessor
from tests import factories


class PipelineTestCase(TestCase):
    """Drives the real ingestor and worker code over an in-memory bus."""

    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org)
        self.node = factories.edge_node(self.org, "GW-0001", site=self.site)
        self.device = factories.device(
            self.org, "ZQS-TEST-0001", site_obj=self.site, node=self.node
        )
        get_registry().invalidate()

        self.bus = InMemoryBus()
        self.bus.connect()
        self.ingestor = Ingestor(bus=self.bus, forwarders=1)

        self.shared = Shared()
        self.processor = SparkplugProcessor(self.shared)
        self._seq = 0

    def tearDown(self) -> None:
        self.bus.close()
        get_registry().invalidate()

    # ---- helpers ---------------------------------------------------------
    def next_seq(self) -> int:
        value = self._seq
        self._seq = (self._seq + 1) % 256
        return value

    def publish(
        self,
        message_type: MessageType,
        metrics: list[tuple] | None = None,
        *,
        device_id: str | None = None,
        node_id: str | None = None,
        timestamp: dt.datetime | None = None,
        seq: int | None = None,
        raw: bytes | None = None,
        retain: bool = False,
    ) -> None:
        """Encode a real payload and hand it to the ingestor's MQTT callback."""
        if message_type is MessageType.NBIRTH:
            self._seq = 0

        if raw is None:
            message = sp.new_payload(
                timestamp=timestamp or now(),
                seq=self.next_seq() if seq is None else seq,
            )
            for entry in metrics or []:
                name, value = entry[0], entry[1]
                datatype = entry[2] if len(entry) > 2 else None
                alias = entry[3] if len(entry) > 3 else None
                properties = entry[4] if len(entry) > 4 else None
                sp.add_metric(
                    message,
                    name,
                    value,
                    datatype=datatype,
                    alias=alias,
                    properties=properties,
                )
            raw = sp.encode(message)

        target_device = ""
        if message_type in topics.DEVICE_LEVEL:
            target_device = device_id or self.device.device_id
        topic = topics.build(
            self.org.slug,
            message_type,
            node_id or self.node.node_id,
            target_device,
        )
        self.ingestor.on_message(topic, raw, 0, retain)

    def drain(self) -> dict[str, int]:
        """Move everything the ingestor queued through the worker."""
        pending: list[dict] = []
        while not self.ingestor.inbound.empty():
            _stream, envelope = self.ingestor.inbound.get_nowait()
            pending.append(envelope)
        return self.processor.process(pending) if pending else {}

    def birth(self) -> None:
        """The births a node must send before any data means anything.

        A DBIRTH carries *current values*, not just a schema, and the worker
        stores them like any other reading. That is deliberate - discarding
        them would leave the console showing stale numbers from before the
        reconnect until the next DDATA happened along - so the tests below
        measure what a message *adds* rather than the table total.
        """
        self.publish(
            MessageType.NBIRTH,
            [("bdSeq", 1, DataType.Int64), (sp.NODE_REBIRTH_METRIC, False)],
        )
        self.publish(
            MessageType.DBIRTH,
            [
                ("battery_soc", 50.0, DataType.Double, 1),
                ("battery_power_w", 0.0, DataType.Double, 2),
                ("pcs_state", "idle", DataType.String, 3),
            ],
        )
        self.drain()

    # ---- tests -----------------------------------------------------------
    def test_data_is_stored_and_latest_updated(self):
        self.birth()
        # Later than the birth, or "latest" correctly keeps the birth's value:
        # truncating microseconds alone would put this *before* it.
        timestamp = now().replace(microsecond=0) + dt.timedelta(seconds=1)
        self.publish(
            MessageType.DDATA,
            [
                ("battery_soc", 78.5, DataType.Double),
                ("battery_power_w", -125000.0, DataType.Double),
            ],
            timestamp=timestamp,
        )
        stats = self.drain()

        self.assertEqual(stats.get("inserted"), 2)

        soc = TelemetrySample.objects.get(metric_key="battery_soc", ts=timestamp)
        self.assertAlmostEqual(soc.value, 78.5)
        self.assertEqual(soc.organization_id, self.org.id)

        latest = LatestSample.objects.get(metric_key="battery_soc")
        self.assertAlmostEqual(latest.value, 78.5)

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, ConnectionStatus.ONLINE)
        self.assertIsNotNone(self.device.last_telemetry_at)

    def test_a_birth_records_the_alias_table(self):
        self.birth()
        aliases = dict(
            MetricAlias.objects.filter(device=self.device).values_list("alias", "name")
        )
        self.assertEqual(aliases, {1: "battery_soc", 2: "battery_power_w", 3: "pcs_state"})

    def test_data_by_alias_alone_resolves_to_the_right_metric(self):
        """The compact form is the whole point of the birth table."""
        self.birth()
        moment = now().replace(microsecond=0) + dt.timedelta(seconds=1)
        message = sp.new_payload(timestamp=moment, seq=self.next_seq())
        # No name at all - only the alias the DBIRTH established.
        sp.add_metric(message, "", 91.5, datatype=DataType.Double, alias=1)
        self.publish(MessageType.DDATA, raw=sp.encode(message))
        self.drain()

        sample = TelemetrySample.objects.get(metric_key="battery_soc", ts=moment)
        self.assertAlmostEqual(sample.value, 91.5)

    def test_an_unknown_alias_is_counted_not_guessed(self):
        """Filing it under a guessed metric would corrupt a real series."""
        self.birth()
        before = TelemetrySample.objects.count()
        message = sp.new_payload(timestamp=now(), seq=self.next_seq())
        sp.add_metric(message, "", 12.0, datatype=DataType.Double, alias=99)
        self.publish(MessageType.DDATA, raw=sp.encode(message))
        stats = self.drain()

        self.assertEqual(stats.get("unresolved_aliases"), 1)
        self.assertEqual(TelemetrySample.objects.count(), before)

    def test_a_rebirth_replaces_the_alias_table(self):
        """An alias dropped by a new birth must not decode later messages."""
        self.birth()
        self.publish(
            MessageType.NBIRTH,
            [("bdSeq", 2, DataType.Int64), (sp.NODE_REBIRTH_METRIC, False)],
        )
        self.publish(
            MessageType.DBIRTH, [("grid_power_w", 10.0, DataType.Double, 1)]
        )
        self.drain()

        aliases = dict(
            MetricAlias.objects.filter(device=self.device).values_list("alias", "name")
        )
        self.assertEqual(aliases, {1: "grid_power_w"})

    def test_redelivery_does_not_duplicate_samples(self):
        self.birth()
        timestamp = now().replace(microsecond=0)
        metrics = [("battery_soc", 50.0, DataType.Double)]

        self.publish(MessageType.DDATA, metrics, timestamp=timestamp, seq=5)
        self.drain()
        # The same envelope again, as an at-least-once redelivery would produce.
        self.publish(MessageType.DDATA, metrics, timestamp=timestamp, seq=5)
        self.drain()

        self.assertEqual(
            TelemetrySample.objects.filter(
                metric_key="battery_soc", ts=timestamp
            ).count(),
            1,
        )

    def test_malformed_payload_is_rejected_at_the_edge(self):
        self.publish(MessageType.DDATA, raw=b"{not protobuf at all")
        self.assertTrue(self.ingestor.inbound.empty())
        self.assertEqual(TelemetrySample.objects.count(), 0)

    def test_unregistered_node_is_dropped(self):
        self.publish(
            MessageType.DDATA,
            [("battery_soc", 1.0, DataType.Double)],
            node_id="NOT-REGISTERED",
        )
        self.assertTrue(self.ingestor.inbound.empty())

    def test_timestamp_far_in_the_future_is_rejected(self):
        future = now() + dt.timedelta(days=2)
        self.publish(
            MessageType.DDATA,
            [("battery_soc", 10.0, DataType.Double)],
            timestamp=future,
        )
        self.assertTrue(self.ingestor.inbound.empty())

    def test_a_device_death_takes_the_device_offline(self):
        self.birth()
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, ConnectionStatus.ONLINE)

        self.publish(MessageType.DDEATH)
        self.drain()
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, ConnectionStatus.OFFLINE)

    def test_a_node_death_takes_every_device_on_it_offline(self):
        """The devices cannot say so themselves - their connection just ended."""
        second = factories.device(self.org, "ZQS-TEST-0002", node=self.node)
        get_registry().invalidate()
        self.birth()

        self.publish(MessageType.NDEATH, [("bdSeq", 1, DataType.Int64)])
        self.drain()

        for device in (self.device, second):
            device.refresh_from_db()
        self.assertEqual(self.device.status, ConnectionStatus.OFFLINE)
        self.node.refresh_from_db()
        self.assertEqual(self.node.status, ConnectionStatus.OFFLINE)

    def test_a_stale_death_does_not_knock_a_reconnected_node_offline(self):
        """bdSeq is what makes a death safe to act on."""
        self.birth()
        self.node.refresh_from_db()
        self.assertEqual(self.node.bd_seq, 1)

        # A death from the *previous* session, arriving late.
        self.publish(MessageType.NDEATH, [("bdSeq", 0, DataType.Int64)])
        stats = self.drain()

        self.assertEqual(stats.get("ndeath_stale"), 1)
        self.node.refresh_from_db()
        self.assertEqual(self.node.status, ConnectionStatus.ONLINE)

    def test_a_birth_reports_node_and_device_properties(self):
        self.publish(
            MessageType.NBIRTH,
            [
                ("bdSeq", 1, DataType.Int64),
                ("Properties/Firmware", "1.4.2", DataType.String),
                ("Properties/IP", "10.0.0.9", DataType.String),
            ],
        )
        self.publish(
            MessageType.DBIRTH,
            [
                ("Properties/Latitude", 24.1477, DataType.Double),
                ("Properties/Longitude", 120.6736, DataType.Double),
                ("Properties/Address", "Taichung", DataType.String),
            ],
        )
        self.drain()

        self.node.refresh_from_db()
        self.assertEqual(self.node.firmware_version, "1.4.2")
        self.assertEqual(self.node.ip_address, "10.0.0.9")

        self.device.refresh_from_db()
        self.assertAlmostEqual(self.device.latitude, 24.1477)
        self.assertEqual(self.device.location_source, "device")

    def test_an_alarm_metric_becomes_a_device_event(self):
        self.birth()
        self.publish(
            MessageType.DDATA,
            [
                (
                    "Alarm/E0500",
                    True,
                    DataType.Boolean,
                    None,
                    {"severity": "major", "message": "Insulation low"},
                )
            ],
        )
        self.drain()

        event = DeviceEvent.objects.get(code="E0500")
        self.assertEqual(event.message, "Insulation low")
        self.assertEqual(event.level, "error")

    def test_an_event_metric_is_recorded(self):
        self.birth()
        self.publish(
            MessageType.DDATA,
            [
                (
                    "Event/E0231",
                    "Fan speed low",
                    DataType.String,
                    None,
                    {"level": "warning"},
                )
            ],
        )
        self.drain()

        event = DeviceEvent.objects.get(code="E0231")
        self.assertEqual(event.message, "Fan speed low")
        self.assertEqual(event.level, "warning")

    def test_command_ack_updates_the_command(self):
        self.birth()
        command = Command.objects.create(
            organization=self.org,
            device=self.device,
            name="set_power_limit",
            params={"limit_w": 500},
            status=CommandStatus.SENT,
            expires_at=now() + dt.timedelta(minutes=5),
        )
        self.publish(
            MessageType.DDATA,
            [
                ("Command/ID", str(command.id), DataType.String),
                ("Command/Status", "succeeded", DataType.String),
                ("Command/Result/applied", 500.0, DataType.Double),
            ],
        )
        self.drain()

        command.refresh_from_db()
        self.assertEqual(command.status, CommandStatus.SUCCEEDED)
        self.assertEqual(command.response, {"applied": 500.0})
        self.assertIsNotNone(command.completed_at)

    def test_late_ack_does_not_regress_a_terminal_command(self):
        self.birth()
        command = Command.objects.create(
            organization=self.org,
            device=self.device,
            name="set_power_limit",
            status=CommandStatus.SUCCEEDED,
            expires_at=now() + dt.timedelta(minutes=5),
        )
        self.publish(
            MessageType.DDATA,
            [
                ("Command/ID", str(command.id), DataType.String),
                ("Command/Status", "accepted", DataType.String),
            ],
        )
        self.drain()
        command.refresh_from_db()
        self.assertEqual(command.status, CommandStatus.SUCCEEDED)

    def test_disabled_device_is_ignored(self):
        Device.objects.filter(pk=self.device.pk).update(is_enabled=False)
        get_registry().invalidate()
        self.publish(
            MessageType.DDATA, [("battery_soc", 1.0, DataType.Double)]
        )
        self.assertTrue(self.ingestor.inbound.empty())

    def test_a_transient_metric_is_shown_but_not_stored(self):
        """``is_transient`` is the publisher saying "do not keep this"."""
        self.birth()
        before = TelemetrySample.objects.count()
        message = sp.new_payload(timestamp=now(), seq=self.next_seq())
        sp.add_metric(
            message, "battery_soc", 44.0, datatype=DataType.Double, is_transient=True
        )
        self.publish(MessageType.DDATA, raw=sp.encode(message))
        stats = self.drain()

        self.assertEqual(stats.get("transient"), 1)
        self.assertEqual(TelemetrySample.objects.count(), before)

    def test_a_sequence_gap_asks_for_a_rebirth(self):
        """The only sanctioned recovery: the alias table may now be wrong."""
        self.birth()
        with self.settings(MQTT={**__import__("django").conf.settings.MQTT, "ENABLED": False}):
            self.publish(
                MessageType.DDATA,
                [("battery_soc", 1.0, DataType.Double)],
                seq=200,
            )
            stats = self.drain()
        self.assertEqual(stats.get("seq_gap"), 1)

    def test_the_bus_carries_one_stream(self):
        """Order matters to seq, and two streams cannot preserve it."""
        self.birth()
        self.publish(MessageType.DDATA, [("battery_soc", 1.0, DataType.Double)])
        stream, _envelope = self.ingestor.inbound.get_nowait()
        self.assertEqual(streams.logical(stream), streams.INGEST)

    def test_an_unresolved_alias_asks_for_a_rebirth(self):
        """A worker that started after the device must be able to recover.

        Without this the stream is permanently unreadable: the aliases mean
        nothing, no birth is coming unprompted, and every reading is discarded
        silently for as long as the device stays connected.
        """
        message = sp.new_payload(timestamp=now(), seq=1)
        sp.add_metric(message, "", 12.0, datatype=DataType.Double, alias=7)

        with mock.patch(
            "apps.devices.edge_nodes.publish_bytes"
        ) as publish:
            self.publish(MessageType.DDATA, raw=sp.encode(message))
            stats = self.drain()

        self.assertEqual(stats.get("unresolved_aliases"), 1)
        self.assertEqual(stats.get("rebirth_requested"), 1)

        topic, body = publish.call_args[0]
        self.assertEqual(
            topic, f"spBv1.0/{self.org.slug}/NCMD/{self.node.node_id}"
        )
        metrics = {m.name: m.value for m in sp.decode(body).metrics}
        self.assertIs(metrics[sp.NODE_REBIRTH_METRIC], True)
