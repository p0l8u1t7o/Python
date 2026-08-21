"""Per-device energy: gauge integration, counter deltas, and counter resets.

The counter-reset cases are the point. A meter that goes backwards has three
possible explanations with three different corrections, and picking the wrong
one silently changes a monthly total - so the rule is to report "unknown"
unless the wrap point is actually known.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.core.timeutils import UTC
from apps.telemetry import repository
from apps.telemetry.energy import (
    BASIS_COUNTER,
    BASIS_INTEGRATED,
    BASIS_UNKNOWN,
    build_timeline,
    counter_delta,
    integrate_kwh,
)
from apps.telemetry.models import Rollup, TelemetrySample
from tests import factories


class GaugeIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.start = dt.datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
        self.end = self.start + dt.timedelta(hours=1)

    def test_constant_power_over_an_hour(self):
        result = integrate_kwh([(self.start, 10.0)], self.start, self.end)
        self.assertAlmostEqual(result.kwh, 10.0, places=6)
        self.assertEqual(result.basis, BASIS_INTEGRATED)
        self.assertAlmostEqual(result.coverage, 1.0)

    def test_zero_order_hold_not_trapezoid(self):
        # 0 kW for the first half hour, then 100 kW. Holding the step gives
        # 50 kWh; a trapezoid would average the ramp and give 25.
        points = [(self.start, 0.0), (self.start + dt.timedelta(minutes=30), 100.0)]
        self.assertAlmostEqual(integrate_kwh(points, self.start, self.end).kwh, 50.0)

    def test_a_late_first_sample_lowers_coverage(self):
        points = [(self.start + dt.timedelta(minutes=45), 40.0)]
        result = integrate_kwh(points, self.start, self.end)
        self.assertAlmostEqual(result.kwh, 10.0, places=6)
        self.assertAlmostEqual(result.coverage, 0.25, places=6)

    def test_a_seed_covers_the_whole_window(self):
        seed = (self.start - dt.timedelta(hours=3), 5.0)
        result = integrate_kwh([], self.start, self.end, seed=seed)
        self.assertAlmostEqual(result.kwh, 5.0, places=6)
        self.assertAlmostEqual(result.coverage, 1.0)

    def test_no_samples_is_unknown_not_zero(self):
        result = integrate_kwh([], self.start, self.end)
        self.assertIsNone(result.kwh)
        self.assertEqual(result.basis, BASIS_UNKNOWN)

    def test_negative_power_integrates_negatively(self):
        result = integrate_kwh([(self.start, -20.0)], self.start, self.end)
        self.assertAlmostEqual(result.kwh, -20.0, places=6)

    def test_timeline_prefers_the_latest_pre_window_sample(self):
        seed = (self.start - dt.timedelta(hours=2), 1.0)
        points = [(self.start - dt.timedelta(minutes=1), 9.0)]
        timeline = build_timeline(points, self.start, self.end, seed=seed)
        self.assertEqual(timeline, [(self.start, 9.0)])


class CounterDeltaTests(TestCase):
    def test_a_normal_increase(self):
        result = counter_delta(1000.0, 1025.5)
        self.assertAlmostEqual(result.kwh, 25.5)
        self.assertEqual(result.basis, BASIS_COUNTER)
        self.assertFalse(result.counter_reset)

    def test_no_movement_is_zero(self):
        self.assertAlmostEqual(counter_delta(1000.0, 1000.0).kwh, 0.0)

    def test_float_noise_is_not_a_reset(self):
        result = counter_delta(1_000_000.0, 1_000_000.0 - 1e-9)
        self.assertAlmostEqual(result.kwh, 0.0)
        self.assertFalse(result.counter_reset)

    def test_a_backwards_counter_is_unknown_not_zero(self):
        # Meter swap, firmware reset and overflow are indistinguishable here.
        result = counter_delta(9000.0, 12.0)
        self.assertIsNone(result.kwh)
        self.assertEqual(result.basis, BASIS_UNKNOWN)
        self.assertTrue(result.counter_reset)

    def test_a_backwards_counter_is_never_negative(self):
        self.assertIsNone(counter_delta(500.0, 100.0).kwh)

    def test_a_declared_wrap_point_allows_a_correction(self):
        # 16-bit counter: 65530 -> 20 is 26 kWh across the wrap.
        result = counter_delta(65_530.0, 20.0, counter_max=65_535.0)
        self.assertAlmostEqual(result.kwh, 25.0)
        self.assertEqual(result.basis, BASIS_COUNTER)
        self.assertTrue(result.counter_reset)

    def test_a_missing_reading_is_unknown(self):
        self.assertIsNone(counter_delta(None, 100.0).kwh)
        self.assertIsNone(counter_delta(100.0, None).kwh)


class RollupEdgeTests(TestCase):
    """`first_value` / `last_value` were on the model but never written."""

    def setUp(self) -> None:
        self.org = factories.organization()
        self.device = factories.device(self.org, "ROLLUP-1")
        self.start = dt.datetime(2026, 6, 1, 0, 0, tzinfo=UTC)

    def sample(self, value: float, offset_minutes: int) -> None:
        TelemetrySample.objects.create(
            organization=self.org,
            device=self.device,
            metric_key="load_energy_kwh",
            ts=self.start + dt.timedelta(minutes=offset_minutes),
            value=value,
        )

    def test_build_rollups_records_the_bucket_edges(self):
        for offset, value in ((0, 100.0), (5, 104.0), (10, 111.0)):
            self.sample(value, offset)

        written = repository.build_rollups(
            organization_id=self.org.id,
            device_ids=[self.device.id],
            metric_keys=["load_energy_kwh"],
            start=self.start,
            end=self.start + dt.timedelta(minutes=15),
            interval_seconds=900,
        )
        self.assertEqual(written, 1)

        bucket = Rollup.objects.get()
        self.assertAlmostEqual(bucket.first_value, 100.0)
        self.assertAlmostEqual(bucket.last_value, 111.0)
        self.assertAlmostEqual(bucket.min_value, 100.0)
        self.assertAlmostEqual(bucket.max_value, 111.0)
        self.assertEqual(bucket.count, 3)

    def test_edges_make_the_counter_delta_available(self):
        for offset, value in ((0, 100.0), (10, 111.0)):
            self.sample(value, offset)
        repository.build_rollups(
            organization_id=self.org.id,
            device_ids=[self.device.id],
            metric_keys=["load_energy_kwh"],
            start=self.start,
            end=self.start + dt.timedelta(minutes=15),
            interval_seconds=900,
        )
        bucket = Rollup.objects.get()
        self.assertAlmostEqual(
            counter_delta(bucket.first_value, bucket.last_value).kwh, 11.0
        )

    def test_edges_are_refreshed_when_a_bucket_is_rebuilt(self):
        self.sample(100.0, 0)
        kwargs = {
            "organization_id": self.org.id,
            "device_ids": [self.device.id],
            "metric_keys": ["load_energy_kwh"],
            "start": self.start,
            "end": self.start + dt.timedelta(minutes=15),
            "interval_seconds": 900,
        }
        repository.build_rollups(**kwargs)
        self.sample(140.0, 8)
        repository.build_rollups(**kwargs)

        bucket = Rollup.objects.get()
        self.assertAlmostEqual(bucket.first_value, 100.0)
        self.assertAlmostEqual(bucket.last_value, 140.0)

    def test_the_chart_query_stays_on_the_cheap_plan(self):
        # with_edges defaults off so the per-redraw path keeps the simple SQL.
        self.sample(100.0, 0)
        rows = repository.aggregate_series(
            device_ids=[self.device.id],
            metric_keys=["load_energy_kwh"],
            start=self.start,
            end=self.start + dt.timedelta(minutes=15),
            interval_seconds=900,
        )
        self.assertNotIn("first_value", rows[0])
