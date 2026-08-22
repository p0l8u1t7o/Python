"""The history backfill used by the one-command dev setup."""

from __future__ import annotations


from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.alerts.models import Alert, AlertRule, Operator, RuleScope, Severity
from apps.core.timeutils import now
from apps.devices.models import ConnectionStatus, DeviceEvent
from apps.ems.models import AssetRole, DispatchStrategy, EnergyAsset, EnergyInterval
from apps.telemetry.models import LatestSample, TelemetrySample
from tests import factories


class GenerateHistoryTestCase(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, timezone_name="Asia/Taipei")
        self.meter = factories.device(self.org, "GEN-METER", site_obj=self.site)
        self.pv = factories.device(self.org, "GEN-PV", site_obj=self.site)
        self.battery = factories.device(self.org, "GEN-BESS", site_obj=self.site)

        for device, role, extra in (
            (self.meter, AssetRole.GRID_METER, {"power_metric": "grid_power_w"}),
            (self.pv, AssetRole.PV, {"power_metric": "pv_power_w", "rated_power_kw": 400.0}),
            (
                self.battery,
                AssetRole.BATTERY,
                {
                    "power_metric": "battery_power_w",
                    "soc_metric": "battery_soc",
                    "rated_power_kw": 500.0,
                    "rated_energy_kwh": 1000.0,
                },
            ),
        ):
            EnergyAsset.objects.create(
                organization=self.org,
                site=self.site,
                device=device,
                role=role,
                power_scale=0.001,
                **extra,
            )

        factories.storage_plan(
            self.org,
            self.site,
            strategy=DispatchStrategy.PEAK_SHAVING,
            contract_capacity_kw=450.0,
            peak_shaving_target_kw=250.0,
            usable_capacity_kwh=1000.0,
            max_charge_kw=500.0,
            max_discharge_kw=500.0,
        )

    def run_command(self, **options) -> str:
        out = StringIO()
        call_command("generate_history", stdout=out, **options)
        return out.getvalue()

    def test_writes_samples_intervals_and_latest_values(self):
        self.run_command(days=1, interval=300)

        self.assertGreater(TelemetrySample.objects.count(), 0)
        self.assertGreater(EnergyInterval.objects.filter(site=self.site).count(), 0)
        self.assertGreater(LatestSample.objects.count(), 0)

        for metric in ("grid_power_w", "pv_power_w", "battery_power_w", "battery_soc"):
            self.assertTrue(
                TelemetrySample.objects.filter(metric_key=metric).exists(), metric
            )

    def test_energy_balance_is_self_consistent(self):
        """load must equal import - export + pv + discharge - charge."""
        self.run_command(days=1, interval=300)

        for interval in EnergyInterval.objects.filter(site=self.site)[:20]:
            derived = (
                interval.grid_import_kwh
                - interval.grid_export_kwh
                + interval.pv_kwh
                + interval.battery_discharge_kwh
                - interval.battery_charge_kwh
            )
            self.assertAlmostEqual(interval.load_kwh, max(0.0, derived), places=3)

    def test_battery_cycles_within_its_soc_limits(self):
        self.run_command(days=2, interval=300)

        socs = [
            value
            for value in EnergyInterval.objects.filter(site=self.site).values_list(
                "soc_end_percent", flat=True
            )
            if value is not None
        ]
        self.assertTrue(socs)
        self.assertGreaterEqual(min(socs), 10.0)
        self.assertLessEqual(max(socs), 95.0)
        # A battery that never moves would make the whole demo pointless.
        self.assertGreater(max(socs) - min(socs), 5.0)

    def test_peak_shaving_holds_import_under_the_contract(self):
        self.run_command(days=2, interval=300)

        peak = max(
            value
            for value in EnergyInterval.objects.filter(site=self.site).values_list(
                "peak_import_kw", flat=True
            )
            if value is not None
        )
        self.assertLessEqual(peak, 450.0)

    def test_devices_are_marked_as_having_reported(self):
        self.run_command(days=1, interval=600)

        for device in (self.meter, self.pv, self.battery):
            device.refresh_from_db()
            self.assertEqual(device.status, ConnectionStatus.ONLINE)
            self.assertIsNotNone(device.last_telemetry_at)
            self.assertTrue(device.status_events.exists())

    def test_faults_raise_alerts_and_write_device_events(self):
        AlertRule.objects.create(
            organization=self.org,
            name="Battery over-temperature",
            scope=RuleScope.SITE,
            site=self.site,
            metric_key="battery_temperature_c",
            operator=Operator.GT,
            threshold=45.0,
            hysteresis=3.0,
            for_duration_seconds=60,
            severity=Severity.MAJOR,
        )

        self.run_command(days=2, interval=300, with_faults=True)

        self.assertTrue(Alert.objects.exists())
        self.assertTrue(DeviceEvent.objects.exists())
        # One excursion runs up to "now", so the console has an open alert.
        self.assertTrue(Alert.objects.exclude(status="resolved").exists())

    def test_clean_run_raises_no_alerts(self):
        """Without --with-faults the generated data must stay in range."""
        AlertRule.objects.create(
            organization=self.org,
            name="Battery over-temperature",
            scope=RuleScope.SITE,
            site=self.site,
            metric_key="battery_temperature_c",
            operator=Operator.GT,
            threshold=45.0,
            for_duration_seconds=60,
            severity=Severity.MAJOR,
        )

        self.run_command(days=1, interval=300)
        self.assertFalse(Alert.objects.exists())
        self.assertFalse(DeviceEvent.objects.exists())

    def test_rerunning_with_clear_does_not_duplicate(self):
        self.run_command(days=1, interval=600, with_faults=True)
        samples = TelemetrySample.objects.count()
        events = DeviceEvent.objects.count()

        self.run_command(days=1, interval=600, with_faults=True, clear=True)

        # Timestamps shift slightly between runs, so allow a small margin
        # rather than asserting exact equality.
        self.assertLess(abs(TelemetrySample.objects.count() - samples), samples * 0.1)
        self.assertEqual(DeviceEvent.objects.count(), events)

    def test_window_covers_the_requested_span(self):
        self.run_command(days=1, interval=600)

        oldest = TelemetrySample.objects.order_by("ts").first()
        newest = TelemetrySample.objects.order_by("-ts").first()
        span = (newest.ts - oldest.ts).total_seconds()
        self.assertGreater(span, 0.9 * 24 * 3600)
        self.assertLess((now() - newest.ts).total_seconds(), 3600)

    def test_refuses_a_pathological_interval(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command(days=1, interval=1)

    def test_refuses_when_no_energy_assets_exist(self):
        from django.core.management.base import CommandError

        EnergyAsset.objects.all().delete()
        with self.assertRaises(CommandError):
            self.run_command(days=1, interval=600)

    def test_site_filter_limits_generation(self):
        from django.core.management.base import CommandError

        factories.site(self.org, code="other")

        # Filtering to a site with no bound assets is a mistake worth naming,
        # not a silent no-op.
        with self.assertRaises(CommandError) as caught:
            self.run_command(days=1, interval=600, site="other")
        self.assertIn("site=other", str(caught.exception))
        self.assertEqual(TelemetrySample.objects.count(), 0)

        self.run_command(days=1, interval=600, site=self.site.code)
        self.assertGreater(TelemetrySample.objects.count(), 0)


class HistoryDeviceStatusTestCase(TestCase):
    def test_devices_without_assets_are_left_alone(self):
        org = factories.organization()
        site = factories.site(org)
        bound = factories.device(org, "BOUND-1", site_obj=site)
        unbound = factories.device(org, "UNBOUND-1", site_obj=site)

        EnergyAsset.objects.create(
            organization=org,
            site=site,
            device=bound,
            role=AssetRole.GRID_METER,
            power_metric="grid_power_w",
            power_scale=0.001,
        )
        call_command("generate_history", days=0.5, interval=900, stdout=StringIO())

        bound.refresh_from_db()
        unbound.refresh_from_db()
        self.assertEqual(bound.status, ConnectionStatus.ONLINE)
        self.assertEqual(unbound.status, ConnectionStatus.UNKNOWN)


class HistorySpanTestCase(TestCase):
    def test_zero_asset_site_is_skipped_without_crashing(self):
        """A site with a plan but no assets must not break a multi-site run."""
        org = factories.organization()
        empty = factories.site(org, code="empty")
        factories.storage_plan(org, empty)

        active = factories.site(org, code="active")
        device = factories.device(org, "ACT-1", site_obj=active)
        EnergyAsset.objects.create(
            organization=org,
            site=active,
            device=device,
            role=AssetRole.GRID_METER,
            power_metric="grid_power_w",
            power_scale=0.001,
        )

        call_command("generate_history", days=0.5, interval=900, stdout=StringIO())
        self.assertEqual(EnergyInterval.objects.filter(site=empty).count(), 0)
        self.assertGreater(EnergyInterval.objects.filter(site=active).count(), 0)


