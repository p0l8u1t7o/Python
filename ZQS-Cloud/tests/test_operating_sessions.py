"""Charge / discharge / running session detection.

The three rules that make session detection usable rather than noisy -
hysteresis, minimum duration, and the gap rule - each get a test, because each
of them is the kind of thing that looks like a needless complication until the
day it is removed.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.core.timeutils import now
from apps.devices.models import Device
from apps.ems.models import AssetRole, DeviceOperatingSession, EnergyAsset, SessionKind
from apps.ems.sessions import Thresholds, detect, rebuild_organization, thresholds_for
from apps.telemetry.models import TelemetrySample
from tests import factories


def _series(start, values, step_seconds=60):
    """``[(ts, kW), ...]`` at a fixed cadence."""
    return [
        (start + dt.timedelta(seconds=index * step_seconds), value)
        for index, value in enumerate(values)
    ]


class ThresholdTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization("sessions")
        self.site = factories.site(self.org, "hq")
        self.device = factories.device(self.org, "SESS-1", site_obj=self.site)

    def _asset(self, **kwargs) -> EnergyAsset:
        return EnergyAsset.objects.create(
            organization=self.org,
            site=self.site,
            device=self.device,
            role=kwargs.pop("role", AssetRole.BATTERY),
            power_metric="battery_power_w",
            **kwargs,
        )

    def test_defaults_scale_with_the_nameplate(self):
        asset = self._asset(rated_power_kw=500.0)
        thresholds = thresholds_for(asset)
        self.assertEqual(thresholds.enter_kw, 10.0)  # 2% of 500
        self.assertEqual(thresholds.exit_kw, 5.0)

    def test_a_tiny_asset_still_gets_a_usable_floor(self):
        asset = self._asset(rated_power_kw=1.0)
        self.assertEqual(thresholds_for(asset).enter_kw, 0.5)

    def test_exit_is_forced_below_enter_even_if_configured_the_other_way(self):
        """Without hysteresis a load sitting at the threshold flaps forever."""
        asset = self._asset(
            rated_power_kw=100.0, session_enter_kw=10.0, session_exit_kw=50.0
        )
        thresholds = thresholds_for(asset)
        self.assertLess(thresholds.exit_kw, thresholds.enter_kw)

    def test_a_load_uses_a_higher_fraction_than_a_battery(self):
        """Standby draw is 1-3% of rating, so 2% would call standby "running"."""
        asset = self._asset(role=AssetRole.LOAD_METER, rated_power_kw=100.0)
        self.assertEqual(thresholds_for(asset).enter_kw, 5.0)


class DetectionTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization("detect")
        self.site = factories.site(self.org, "hq")
        self.device = factories.device(self.org, "DET-1", site_obj=self.site)
        self.asset = EnergyAsset.objects.create(
            organization=self.org,
            site=self.site,
            device=self.device,
            role=AssetRole.BATTERY,
            power_metric="battery_power_w",
            rated_power_kw=100.0,
        )
        self.thresholds = Thresholds(
            enter_kw=10.0, exit_kw=5.0, min_duration_s=60, gap_s=300
        )
        self.start = now().replace(microsecond=0) - dt.timedelta(hours=2)

    def test_a_sustained_discharge_becomes_one_session(self):
        points = _series(self.start, [0.0, 40.0, 45.0, 42.0, 0.0])
        sessions = detect(self.asset, points, self.thresholds)
        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session.kind, SessionKind.DISCHARGE)
        self.assertEqual(session.duration_s, 180)
        self.assertAlmostEqual(session.peak_kw, 45.0)
        # 40 + 45 + 42 kW each held one minute.
        self.assertAlmostEqual(session.energy_kwh, (40 + 45 + 42) / 60.0, places=4)

    def test_charging_and_discharging_are_different_sessions(self):
        points = _series(self.start, [-40.0, -40.0, 40.0, 40.0, 0.0])
        sessions = detect(self.asset, points, self.thresholds)
        self.assertEqual(
            [session.kind for session in sessions],
            [SessionKind.CHARGE, SessionKind.DISCHARGE],
        )

    def test_hysteresis_keeps_a_wobbling_reading_as_one_session(self):
        """Between exit and enter is "still going", not "stopped and restarted"."""
        points = _series(self.start, [12.0, 7.0, 12.0, 8.0, 12.0, 0.0])
        sessions = detect(self.asset, points, self.thresholds)
        self.assertEqual(len(sessions), 1)

    def test_a_brief_spike_is_discarded(self):
        """A motor's inrush is not a discharge."""
        points = _series(self.start, [0.0, 80.0, 0.0], step_seconds=10)
        self.assertEqual(detect(self.asset, points, self.thresholds), [])

    def test_a_data_gap_closes_the_session_at_the_last_sample(self):
        points = [
            (self.start, 40.0),
            (self.start + dt.timedelta(minutes=2), 40.0),
            # Twenty minutes of silence, then the equipment reappears.
            (self.start + dt.timedelta(minutes=22), 40.0),
            (self.start + dt.timedelta(minutes=25), 0.0),
        ]
        sessions = detect(self.asset, points, self.thresholds)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].end_reason, "offline")
        # Not extrapolated across the silence: it ends where the data ends.
        self.assertEqual(
            sessions[0].ended_at, self.start + dt.timedelta(minutes=2)
        )

    def test_equipment_still_running_at_the_end_leaves_the_session_open(self):
        points = _series(self.start, [40.0] * 5)
        sessions = detect(
            self.asset,
            points,
            self.thresholds,
            window_end=self.start + dt.timedelta(minutes=5),
        )
        self.assertEqual(len(sessions), 1)
        self.assertIsNone(sessions[0].ended_at)
        self.assertIsNone(sessions[0].duration_s)

    def test_soc_is_carried_onto_the_session(self):
        points = _series(self.start, [40.0, 40.0, 40.0, 0.0])
        soc = _series(self.start, [90.0, 88.0, 86.0, 85.0])
        session = detect(self.asset, points, self.thresholds, soc_points=soc)[0]
        self.assertEqual(session.start_soc_percent, 90.0)
        self.assertEqual(session.end_soc_percent, 86.0)


class RebuildTests(TestCase):
    """The rebuild is only useful if re-running it is a no-op."""

    def setUp(self) -> None:
        self.org = factories.organization("rebuild")
        self.site = factories.site(self.org, "hq")
        self.device = factories.device(self.org, "REB-1", site_obj=self.site)
        EnergyAsset.objects.create(
            organization=self.org,
            site=self.site,
            device=self.device,
            role=AssetRole.BATTERY,
            power_metric="battery_power_w",
            power_scale=0.001,
            rated_power_kw=100.0,
            session_tracking_enabled=True,
        )
        start = now().replace(microsecond=0) - dt.timedelta(hours=1)
        TelemetrySample.objects.bulk_create(
            TelemetrySample(
                organization=self.org,
                device=self.device,
                metric_key="battery_power_w",
                ts=start + dt.timedelta(minutes=index),
                value=watts,
            )
            for index, watts in enumerate([0, 40_000, 40_000, 40_000, 0])
        )

    def test_rebuilding_twice_produces_the_same_rows(self):
        first = rebuild_organization(self.org, since=now() - dt.timedelta(hours=2))
        self.assertEqual(first.written, 1)
        count = DeviceOperatingSession.objects.count()

        second = rebuild_organization(self.org, since=now() - dt.timedelta(hours=2))
        self.assertEqual(second.written, 1)
        self.assertEqual(DeviceOperatingSession.objects.count(), count)

    def test_the_device_cache_points_at_the_newest_session(self):
        rebuild_organization(self.org, since=now() - dt.timedelta(hours=2))
        session = DeviceOperatingSession.objects.get()
        device = Device.objects.get(pk=self.device.pk)
        self.assertEqual(device.last_discharge_at, session.started_at)
        self.assertIsNone(device.last_charge_at)

    def test_tracking_off_means_nothing_is_written(self):
        EnergyAsset.objects.update(session_tracking_enabled=False)
        result = rebuild_organization(self.org, since=now() - dt.timedelta(hours=2))
        self.assertEqual(result.written, 0)
