"""Recording policy resolution and the keep/drop gate."""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.core.timeutils import now
from apps.devices.registry import DeviceRef, get_registry
from apps.telemetry.models import RecordingPolicy, RecordingRule
from apps.telemetry.policy import MetricRule, PolicyResolver, SampleGate
from tests import factories


class PolicyResolutionTestCase(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.blueprint = factories.blueprint(org=self.org)
        self.resolver = PolicyResolver(ttl_seconds=0)

    def _ref(self, **kwargs) -> DeviceRef:
        defaults = dict(
            pk=None,
            device_id="D1",
            edge_node_id=None,
            organization_id=self.org.id,
            site_id=None,
            device_type_id=None,
            recording_policy_id=None,
            is_enabled=True,
        )
        defaults.update(kwargs)
        return DeviceRef(**defaults)

    def test_falls_back_to_the_organization_default(self):
        policy = RecordingPolicy.objects.create(
            organization=self.org, name="Org default", is_default=True
        )
        RecordingRule.objects.create(
            policy=policy, metric_key="battery_soc", min_interval_seconds=30
        )
        resolved = self.resolver.for_device(self._ref())
        self.assertEqual(resolved.policy_id, policy.id)
        self.assertEqual(resolved.rule_for("battery_soc").min_interval_seconds, 30)

    def test_blueprint_policy_beats_the_org_default(self):
        RecordingPolicy.objects.create(
            organization=self.org, name="Org default", is_default=True
        )
        blueprint_policy = RecordingPolicy.objects.create(
            organization=self.org, name="For blueprint", device_type=self.blueprint
        )
        resolved = self.resolver.for_device(self._ref(device_type_id=self.blueprint.id))
        self.assertEqual(resolved.policy_id, blueprint_policy.id)

    def test_device_override_beats_everything(self):
        RecordingPolicy.objects.create(
            organization=self.org, name="Org default", is_default=True
        )
        RecordingPolicy.objects.create(
            organization=self.org, name="For blueprint", device_type=self.blueprint
        )
        device_policy = RecordingPolicy.objects.create(
            organization=self.org, name="For one device"
        )
        resolved = self.resolver.for_device(
            self._ref(device_type_id=self.blueprint.id, recording_policy_id=device_policy.id)
        )
        self.assertEqual(resolved.policy_id, device_policy.id)

    def test_allow_list_mode_drops_unlisted_metrics(self):
        policy = RecordingPolicy.objects.create(
            organization=self.org,
            name="Allow list",
            is_default=True,
            record_unlisted_metrics=False,
        )
        RecordingRule.objects.create(policy=policy, metric_key="battery_soc")
        resolved = self.resolver.for_device(self._ref())

        self.assertIsNotNone(resolved.rule_for("battery_soc"))
        self.assertIsNone(resolved.rule_for("signal_rssi_dbm"))

    def test_disabled_rule_drops_the_metric(self):
        policy = RecordingPolicy.objects.create(
            organization=self.org, name="P", is_default=True
        )
        RecordingRule.objects.create(policy=policy, metric_key="uptime_s", enabled=False)
        resolved = self.resolver.for_device(self._ref())
        self.assertIsNone(resolved.rule_for("uptime_s"))

    def test_no_policy_records_everything(self):
        resolved = self.resolver.for_device(self._ref())
        self.assertIsNotNone(resolved.rule_for("anything_at_all"))


class SampleGateTestCase(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.device = factories.device(self.org, "GATE-0001")
        get_registry().invalidate()
        self.gate = SampleGate()
        self.gate.seed_device(self.device.id)
        self.base = now().replace(microsecond=0)

    def store(self, offset_s: int, value: float, rule: MetricRule) -> bool:
        ts = self.base + dt.timedelta(seconds=offset_s)
        allowed = self.gate.should_store(
            self.device.id, "battery_soc", ts, value, None, rule
        )
        if allowed:
            self.gate.mark_stored(self.device.id, "battery_soc", ts, value, None)
        return allowed

    def test_first_sample_is_always_stored(self):
        rule = MetricRule(min_interval_seconds=60)
        self.assertTrue(self.store(0, 50.0, rule))

    def test_min_interval_thins_the_series(self):
        rule = MetricRule(min_interval_seconds=60, max_interval_seconds=0)
        self.assertTrue(self.store(0, 50.0, rule))
        self.assertFalse(self.store(30, 51.0, rule))
        self.assertTrue(self.store(60, 52.0, rule))

    def test_absolute_deadband_suppresses_small_changes(self):
        rule = MetricRule(deadband_absolute=1.0, max_interval_seconds=0)
        self.assertTrue(self.store(0, 50.0, rule))
        self.assertFalse(self.store(10, 50.5, rule))
        self.assertTrue(self.store(20, 51.5, rule))

    def test_percent_deadband(self):
        rule = MetricRule(deadband_percent=2.0, max_interval_seconds=0)
        self.assertTrue(self.store(0, 100.0, rule))
        self.assertFalse(self.store(10, 101.0, rule))  # 1% change
        self.assertTrue(self.store(20, 103.0, rule))  # 3% change

    def test_heartbeat_overrides_the_deadband(self):
        rule = MetricRule(deadband_absolute=100.0, max_interval_seconds=3600)
        self.assertTrue(self.store(0, 50.0, rule))
        self.assertFalse(self.store(1800, 50.1, rule))
        self.assertTrue(self.store(3600, 50.2, rule))

    def test_out_of_order_sample_is_stored_without_moving_the_gate(self):
        rule = MetricRule(min_interval_seconds=60, max_interval_seconds=0)
        self.assertTrue(self.store(600, 50.0, rule))
        # A late sample is still accepted for storage...
        self.assertTrue(self.store(300, 49.0, rule))
        # ...but must not have rewound the gate to t=300.
        self.assertFalse(self.store(620, 51.0, rule))

    def test_text_values_change_only_when_the_string_changes(self):
        rule = MetricRule(max_interval_seconds=0)
        ts = self.base
        self.assertTrue(
            self.gate.should_store(self.device.id, "pcs_state", ts, None, "idle", rule)
        )
        self.gate.mark_stored(self.device.id, "pcs_state", ts, None, "idle")
        self.assertFalse(
            self.gate.should_store(
                self.device.id, "pcs_state", ts + dt.timedelta(seconds=5), None, "idle", rule
            )
        )
        self.assertTrue(
            self.gate.should_store(
                self.device.id,
                "pcs_state",
                ts + dt.timedelta(seconds=10),
                None,
                "charging",
                rule,
            )
        )
