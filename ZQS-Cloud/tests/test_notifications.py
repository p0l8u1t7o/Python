"""Notification channels: LINE, device-event subscriptions, delivery text.

The senders themselves talk to the outside world and are not exercised here;
what is tested is everything up to the network call - which deliveries get
queued for whom, what the message says, and what the API accepts.
"""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from apps.alerts.models import (
    ChannelType,
    NotificationChannel,
    NotificationDelivery,
)
from apps.devices.models import DeviceEvent, EventLevel
from services.worker.notifications import (
    _notification_text,
    build_payload,
    queue_event_notifications,
)
from tests import factories
from tests.test_api import ApiTestCase


class EventNotificationTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, "plant")
        self.device = factories.device(self.org, "NTF-1", site_obj=self.site)

    def channel(self, **kwargs) -> NotificationChannel:
        defaults = {
            "organization": self.org,
            "name": f"ch-{NotificationChannel.objects.count()}",
            "channel_type": ChannelType.WEBHOOK,
            "config": {"url": "https://example.com/hook"},
            "notify_events": True,
            "min_event_level": EventLevel.ERROR,
        }
        defaults.update(kwargs)
        return NotificationChannel.objects.create(**defaults)

    def event(self, level: str = EventLevel.ERROR) -> DeviceEvent:
        return DeviceEvent.objects.create(
            organization=self.org,
            device=self.device,
            ts=timezone.now(),
            level=level,
            code="E0231",
            message="Inverter fault",
        )

    def test_an_event_at_or_above_the_level_is_queued(self) -> None:
        channel = self.channel()
        queued = queue_event_notifications([self.event(EventLevel.CRITICAL)])
        self.assertEqual(queued, 1)
        delivery = NotificationDelivery.objects.get()
        self.assertEqual(delivery.channel, channel)
        self.assertIsNone(delivery.alert_id)
        self.assertIsNotNone(delivery.event_id)

    def test_an_event_below_the_level_is_not(self) -> None:
        self.channel(min_event_level=EventLevel.ERROR)
        queued = queue_event_notifications([self.event(EventLevel.WARNING)])
        self.assertEqual(queued, 0)

    def test_a_channel_not_subscribed_to_events_gets_none(self) -> None:
        self.channel(notify_events=False)
        self.assertEqual(queue_event_notifications([self.event()]), 0)

    def test_a_disabled_channel_gets_none(self) -> None:
        self.channel(is_enabled=False)
        self.assertEqual(queue_event_notifications([self.event()]), 0)

    def test_another_organizations_channel_gets_none(self) -> None:
        other = factories.organization(slug="other-org")
        NotificationChannel.objects.create(
            organization=other,
            name="elsewhere",
            channel_type=ChannelType.WEBHOOK,
            config={"url": "https://example.com/hook"},
            notify_events=True,
            min_event_level=EventLevel.INFO,
        )
        self.assertEqual(queue_event_notifications([self.event()]), 0)

    def test_the_event_payload_and_text_read_as_a_message(self) -> None:
        self.channel()
        queue_event_notifications([self.event()])
        delivery = NotificationDelivery.objects.select_related(
            "event", "event__device", "event__device__site"
        ).get()
        payload = build_payload(delivery)
        self.assertEqual(payload["kind"], "event")
        self.assertEqual(payload["code"], "E0231")
        text = _notification_text(payload)
        self.assertIn("Inverter fault", text)
        self.assertIn("NTF-1", text)


class ChannelApiTests(ApiTestCase):
    def _create(self, body: dict):
        token = self.login("admin@acme-demo.com")
        return self.post("/api/notification-channels", token, body), token

    def test_a_line_channel_requires_token_and_recipient(self) -> None:
        response, token = self._create(
            {"name": "line-alerts", "channel_type": "line", "config": {"to": "U1"}}
        )
        self.assertEqual(response.status_code, 422)

        response = self.post(
            "/api/notification-channels",
            token,
            {
                "name": "line-alerts",
                "channel_type": "line",
                "notify_events": True,
                "min_event_level": "warning",
                "config": {"channel_access_token": "tok-secret", "to": "U1234"},
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        # The token never comes back readable.
        self.assertEqual(body["config"]["channel_access_token"], "***")
        self.assertTrue(body["notify_events"])

    def test_updating_without_retyping_the_secret_keeps_it(self) -> None:
        response, token = self._create(
            {
                "name": "line-alerts",
                "channel_type": "line",
                "config": {"channel_access_token": "tok-secret", "to": "U1234"},
            }
        )
        created = response.json()

        # The edit form sends back the redacted token untouched.
        response = self.call(
            "put",
            f"/api/notification-channels/{created['id']}",
            token,
            {
                "name": "line-alerts",
                "channel_type": "line",
                "config": {"channel_access_token": "***", "to": "U5678"},
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        channel = NotificationChannel.objects.get(pk=created["id"])
        self.assertEqual(channel.config["channel_access_token"], "tok-secret")
        self.assertEqual(channel.config["to"], "U5678")


class TaipowerPresetTests(TestCase):
    """The bundled tables have to be internally coherent - the exact figures
    are posted rates the operator must verify, but a preset whose periods do
    not validate or whose peak resolves to the off-peak price is a bug."""

    def setUp(self) -> None:
        self.org = factories.organization()

    def tariff_from(self, preset: dict):
        from apps.ems.models import Tariff

        return Tariff.objects.create(
            organization=self.org, name=preset["name"], **preset["tariff"]
        )

    def test_every_preset_validates(self) -> None:
        from apps.ems.taipower import presets
        from apps.ems.tariffs import validate_periods

        for preset in presets():
            self.assertEqual(validate_periods(preset["tariff"]["periods"]), [],
                             preset["key"])

    def test_two_tier_resolves_peak_and_off_peak(self) -> None:
        import datetime as dt

        from apps.ems.taipower import presets
        from apps.ems.tariffs import resolve_price

        preset = next(p for p in presets() if p["key"] == "taipower-residential-2tier")
        tariff = self.tariff_from(preset)
        zone = dt.timezone(dt.timedelta(hours=8))  # Asia/Taipei, no DST

        # A summer weekday mid-morning is peak; the same hour on Sunday is not.
        summer_weekday = dt.datetime(2026, 7, 15, 10, 0, tzinfo=zone)  # Wednesday
        summer_sunday = dt.datetime(2026, 7, 19, 10, 0, tzinfo=zone)
        self.assertEqual(resolve_price(tariff, summer_weekday).period_name, "夏月尖峰")
        self.assertEqual(resolve_price(tariff, summer_sunday).period_name, "夏月離峰")

        # Winter weekday noon falls in the 11:00-14:00 gap - off-peak.
        winter_noon = dt.datetime(2026, 1, 14, 12, 0, tzinfo=zone)
        winter_evening = dt.datetime(2026, 1, 14, 20, 0, tzinfo=zone)
        self.assertEqual(resolve_price(tariff, winter_noon).period_name, "非夏月離峰")
        self.assertEqual(resolve_price(tariff, winter_evening).period_name, "非夏月尖峰(午後)")

    def test_presets_endpoint_serves_them(self) -> None:
        from apps.ems.taipower import presets

        self.assertGreaterEqual(len(presets()), 3)
        for preset in presets():
            self.assertIn("tariff_year", preset)


class RunStreamTests(ApiTestCase):
    """The SSE endpoint, exercised against a run that is already finished -
    the generator then emits its snapshot and closes without sleeping."""

    def _finished_run(self):
        from apps.workflows.models import RunStatus, Workflow, WorkflowRun

        workflow = Workflow.objects.create(
            organization=self.org, name="stream-test",
            graph={"nodes": [{"id": "s", "type": "start", "params": {}}], "edges": []},
        )
        return WorkflowRun.objects.create(
            organization=self.org, workflow=workflow, graph=workflow.graph,
            status=RunStatus.SUCCEEDED,
        )

    def test_requires_a_valid_token(self) -> None:
        run = self._finished_run()
        response = self.client.get(f"/api/workflow-runs/{run.id}/stream?token=bogus")
        self.assertEqual(response.status_code, 401)

    def test_streams_the_run_and_closes_on_terminal_state(self) -> None:
        run = self._finished_run()
        token = self.login("op@acme-demo.com")
        response = self.client.get(f"/api/workflow-runs/{run.id}/stream?token={token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        body = b"".join(response.streaming_content).decode()
        self.assertIn("event: run", body)
        self.assertIn('"status":"succeeded"', body)
        self.assertIn("event: done", body)

    def test_another_organizations_run_is_not_found(self) -> None:
        from apps.workflows.models import RunStatus, Workflow, WorkflowRun

        workflow = Workflow.objects.create(
            organization=self.other_org, name="not-yours",
            graph={"nodes": [{"id": "s", "type": "start", "params": {}}], "edges": []},
        )
        run = WorkflowRun.objects.create(
            organization=self.other_org, workflow=workflow, graph=workflow.graph,
            status=RunStatus.SUCCEEDED,
        )
        token = self.login("op@acme-demo.com")
        response = self.client.get(f"/api/workflow-runs/{run.id}/stream?token={token}")
        self.assertEqual(response.status_code, 404)
