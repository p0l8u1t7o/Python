"""Rule engine: sustained conditions, hysteresis, dedup and device alarms."""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.alerts.engine import AlertEngine, RuleCache, breaches, clears
from apps.alerts.models import (
    Alert,
    AlertRule,
    AlertStatus,
    Operator,
    RuleScope,
    Severity,
)
from apps.core.timeutils import now
from apps.devices.registry import DeviceRef
from tests import factories


def _ref(device) -> DeviceRef:
    return DeviceRef(
        pk=device.id,
        device_id=device.device_id,
        edge_node_id=device.edge_node_id,
        organization_id=device.organization_id,
        site_id=device.site_id,
        device_type_id=device.device_type_id,
        recording_policy_id=None,
        is_enabled=True,
    )


class AlertEngineTestCase(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org)
        self.device = factories.device(self.org, "ALRT-0001", site_obj=self.site)
        self.ref = _ref(self.device)
        self.base = now().replace(microsecond=0)

        self.rule = AlertRule.objects.create(
            organization=self.org,
            name="SOC low",
            scope=RuleScope.ORGANIZATION,
            metric_key="battery_soc",
            operator=Operator.LT,
            threshold=20.0,
            hysteresis=5.0,
            for_duration_seconds=60,
            cooldown_seconds=0,
            severity=Severity.CRITICAL,
        )
        # A fresh cache per test so rules are picked up immediately.
        self.engine = AlertEngine(rule_cache=RuleCache(ttl_seconds=0))

    def evaluate(self, value: float, offset_s: int):
        return self.engine.evaluate(
            self.ref,
            "battery_soc",
            value,
            self.base + dt.timedelta(seconds=offset_s),
            device_name=self.device.name,
        )

    def test_condition_must_hold_for_the_configured_duration(self):
        self.assertEqual(self.evaluate(15.0, 0), [])
        self.assertEqual(self.evaluate(14.0, 30), [])
        self.assertEqual(Alert.objects.count(), 0)

        fired = self.evaluate(13.0, 61)
        self.assertEqual(len(fired), 1)
        alert = Alert.objects.get()
        self.assertEqual(alert.severity, Severity.CRITICAL)
        self.assertEqual(alert.status, AlertStatus.FIRING)
        self.assertAlmostEqual(alert.trigger_value, 13.0)

    def test_brief_excursion_does_not_fire(self):
        self.evaluate(15.0, 0)
        self.evaluate(30.0, 20)  # recovered before the duration elapsed
        self.evaluate(15.0, 40)
        self.evaluate(15.0, 70)  # timer restarted at t=40, so only 30s so far
        self.assertEqual(Alert.objects.count(), 0)

    def test_repeat_breach_bumps_the_existing_alert(self):
        self.evaluate(15.0, 0)
        self.evaluate(13.0, 61)
        self.evaluate(12.0, 90)
        self.evaluate(11.0, 120)

        self.assertEqual(Alert.objects.count(), 1)
        alert = Alert.objects.get()
        self.assertEqual(alert.occurrence_count, 3)
        self.assertAlmostEqual(alert.trigger_value, 11.0)

    def test_hysteresis_prevents_flapping(self):
        self.evaluate(15.0, 0)
        self.evaluate(13.0, 61)
        alert = Alert.objects.get()
        self.assertEqual(alert.status, AlertStatus.FIRING)

        # Back above 20 but not past 20 + 5, so the alert stays open.
        self.evaluate(22.0, 90)
        alert.refresh_from_db()
        self.assertEqual(alert.status, AlertStatus.FIRING)

        self.evaluate(26.0, 120)
        alert.refresh_from_db()
        self.assertEqual(alert.status, AlertStatus.RESOLVED)

    def test_scope_limits_which_devices_a_rule_watches(self):
        other_site = factories.site(self.org, code="branch")
        other_device = factories.device(self.org, "ALRT-0002", site_obj=other_site)
        AlertRule.objects.filter(pk=self.rule.pk).update(
            scope=RuleScope.SITE, site=self.site, for_duration_seconds=0
        )
        self.engine.rules.invalidate()

        self.engine.evaluate(_ref(other_device), "battery_soc", 5.0, self.base)
        self.assertEqual(Alert.objects.count(), 0)

        self.engine.evaluate(self.ref, "battery_soc", 5.0, self.base)
        self.assertEqual(Alert.objects.count(), 1)

    def test_device_alarm_raise_and_clear(self):
        self.engine.raise_device_alarm(
            self.ref,
            code="E0500",
            severity="major",
            message="Insulation fault",
            ts=self.base,
        )
        alert = Alert.objects.get(code="E0500")
        self.assertEqual(alert.status, AlertStatus.FIRING)

        # A repeat while still open must not create a second alert.
        self.engine.raise_device_alarm(
            self.ref, code="E0500", severity="major", message="Insulation fault", ts=self.base
        )
        self.assertEqual(Alert.objects.filter(code="E0500").count(), 1)

        self.engine.clear_device_alarm(self.ref, code="E0500", ts=self.base)
        alert.refresh_from_db()
        self.assertEqual(alert.status, AlertStatus.RESOLVED)


class ComparatorTestCase(TestCase):
    """The pure comparison helpers, independent of any database state."""

    def _rule(self, **kwargs):
        from apps.alerts.engine import CompiledRule
        import uuid

        defaults = dict(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            name="r",
            severity=Severity.WARNING,
            metric_key="m",
            operator=Operator.GT,
            threshold=10.0,
            threshold_upper=None,
            hysteresis=0.0,
            for_duration_seconds=0,
            cooldown_seconds=0,
            auto_resolve=True,
            message_template="",
            scope=RuleScope.ORGANIZATION,
            site_id=None,
            device_type_id=None,
        )
        defaults.update(kwargs)
        return CompiledRule(**defaults)

    def test_greater_than(self):
        rule = self._rule(operator=Operator.GT, threshold=10.0)
        self.assertTrue(breaches(rule, 10.1))
        self.assertFalse(breaches(rule, 10.0))

    def test_outside_range(self):
        rule = self._rule(operator=Operator.OUTSIDE, threshold=198.0, threshold_upper=242.0)
        self.assertTrue(breaches(rule, 190.0))
        self.assertTrue(breaches(rule, 250.0))
        self.assertFalse(breaches(rule, 220.0))

    def test_clear_requires_the_hysteresis_margin(self):
        rule = self._rule(operator=Operator.GT, threshold=100.0, hysteresis=10.0)
        self.assertFalse(clears(rule, 95.0))
        self.assertTrue(clears(rule, 90.0))

    def test_inside_range_clears_outside_the_margin(self):
        rule = self._rule(
            operator=Operator.INSIDE, threshold=10.0, threshold_upper=20.0, hysteresis=2.0
        )
        self.assertTrue(breaches(rule, 15.0))
        self.assertFalse(clears(rule, 9.0))
        self.assertTrue(clears(rule, 7.0))
        self.assertTrue(clears(rule, 23.0))


class NotificationPhaseTestCase(AlertEngineTestCase):
    """Raise and clear must produce two messages a person can tell apart."""

    def _channel(self):
        from apps.alerts.models import ChannelType, NotificationChannel

        channel = NotificationChannel.objects.create(
            organization=self.org, name="oncall", channel_type=ChannelType.WEBHOOK,
            config={"url": "https://example.com/hook"}, notify_alerts=True,
            min_severity=Severity.WARNING, notify_events=True, min_event_level="error",
        )
        self.rule.channels.add(channel)
        return channel

    def test_rule_alert_queues_a_raised_and_then_a_resolved_delivery(self):
        from apps.alerts.models import NotificationDelivery
        from services.worker.notifications import _notification_text, build_payload

        self._channel()
        self.evaluate(15.0, 0)
        self.evaluate(13.0, 61)
        self.evaluate(30.0, 120)
        phases = list(
            NotificationDelivery.objects.order_by("created_at").values_list("phase", flat=True)
        )
        self.assertEqual(phases, ["raised", "resolved"])

        raised, resolved = NotificationDelivery.objects.order_by("created_at")
        raised_text = _notification_text(build_payload(raised))
        resolved_text = _notification_text(build_payload(resolved))
        self.assertTrue(raised_text.startswith("🔴 發生"), raised_text)
        self.assertTrue(resolved_text.startswith("🟢 解除"), resolved_text)
        self.assertIn("持續", resolved_text)
        self.assertNotEqual(raised_text, resolved_text)

    def test_a_raised_delivery_sent_late_still_says_raised(self):
        """The alert may have cleared by the time the worker sends."""
        from apps.alerts.models import NotificationDelivery
        from services.worker.notifications import _notification_text, build_payload

        self._channel()
        self.evaluate(15.0, 0)
        self.evaluate(13.0, 61)
        self.evaluate(30.0, 120)
        raised = NotificationDelivery.objects.filter(phase="raised").get()
        self.assertEqual(raised.alert.status, AlertStatus.RESOLVED)
        self.assertTrue(_notification_text(build_payload(raised)).startswith("🔴 發生"))

    def test_device_alarm_clear_event_reaches_the_same_channel(self):
        """The clear is logged at info, below the channel's 'error' gate, but
        it carries the raise level and is queued as a resolved message."""
        from apps.alerts.models import NotificationDelivery
        from apps.devices.models import DeviceEvent, EventLevel
        from services.worker.notifications import (
            _notification_text,
            build_payload,
            queue_event_notifications,
        )

        self._channel()
        raised = DeviceEvent.objects.create(
            organization=self.org, device=self.device, ts=self.base, level=EventLevel.ERROR,
            code="A0007", message="PCS over-temperature",
            payload={"alarm_state": "active", "alarm_level": "error"},
        )
        cleared = DeviceEvent.objects.create(
            organization=self.org, device=self.device, ts=self.base, level=EventLevel.INFO,
            code="A0007", message="PCS over-temperature",
            payload={"alarm_state": "cleared", "alarm_level": "error"},
        )
        self.assertEqual(queue_event_notifications([raised, cleared]), 2)
        phases = {d.event_id: d.phase for d in NotificationDelivery.objects.all()}
        self.assertEqual(phases[raised.pk], "raised")
        self.assertEqual(phases[cleared.pk], "resolved")
        text = _notification_text(build_payload(NotificationDelivery.objects.get(event=cleared)))
        self.assertTrue(text.startswith("🟢 解除"), text)

    def test_a_plain_info_event_still_respects_the_gate(self):
        from apps.devices.models import DeviceEvent, EventLevel
        from services.worker.notifications import queue_event_notifications

        self._channel()
        info = DeviceEvent.objects.create(
            organization=self.org, device=self.device, ts=self.base, level=EventLevel.INFO,
            code="I0001", message="Firmware updated",
        )
        self.assertEqual(queue_event_notifications([info]), 0)
