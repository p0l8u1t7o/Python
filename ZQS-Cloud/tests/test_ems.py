"""Behind-the-meter aggregation and tariff resolution."""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.core.timeutils import UTC
from apps.ems.aggregator import SiteAggregator, integrate_power
from apps.ems.models import (
    AssetRole,
    DispatchStrategy,
    EnergyAsset,
    EnergyInterval,
    Tariff,
)
from apps.ems.tariffs import resolve_price, validate_periods
from apps.telemetry.models import TelemetrySample
from tests import factories


class IntegrationTestCase(TestCase):
    """Step-wise integration of a power series into energy."""

    def setUp(self) -> None:
        self.start = dt.datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
        self.end = self.start + dt.timedelta(minutes=15)

    def test_constant_power_over_the_window(self):
        points = [(self.start, 100.0)]
        result = integrate_power(points, self.start, self.end)
        # 100 kW for a quarter of an hour = 25 kWh.
        self.assertAlmostEqual(result.positive_kwh, 25.0, places=6)
        self.assertAlmostEqual(result.coverage, 1.0, places=6)
        self.assertAlmostEqual(result.peak_positive_kw, 100.0)

    def test_positive_and_negative_are_split(self):
        points = [
            (self.start, 100.0),
            (self.start + dt.timedelta(minutes=5), -60.0),
        ]
        result = integrate_power(points, self.start, self.end)
        self.assertAlmostEqual(result.positive_kwh, 100 * 5 / 60, places=6)
        self.assertAlmostEqual(result.negative_kwh, 60 * 10 / 60, places=6)
        self.assertAlmostEqual(result.peak_negative_kw, 60.0)

    def test_seed_sample_covers_the_whole_window(self):
        """A device reporting only on change still fills its interval."""
        seed = (self.start - dt.timedelta(minutes=30), 40.0)
        result = integrate_power([], self.start, self.end, seed=seed)
        self.assertAlmostEqual(result.positive_kwh, 10.0, places=6)
        self.assertAlmostEqual(result.coverage, 1.0, places=6)

    def test_no_samples_yields_nothing(self):
        result = integrate_power([], self.start, self.end)
        self.assertEqual(result.positive_kwh, 0.0)
        self.assertEqual(result.coverage, 0.0)


class SiteAggregatorTestCase(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, timezone_name="Asia/Taipei")
        self.meter = factories.device(self.org, "AGG-METER", site_obj=self.site)
        self.pv = factories.device(self.org, "AGG-PV", site_obj=self.site)
        self.battery = factories.device(self.org, "AGG-BESS", site_obj=self.site)

        for device, role, extra in (
            (self.meter, AssetRole.GRID_METER, {"power_metric": "grid_power_w"}),
            (self.pv, AssetRole.PV, {"power_metric": "pv_power_w"}),
            (
                self.battery,
                AssetRole.BATTERY,
                {"power_metric": "battery_power_w", "soc_metric": "battery_soc"},
            ),
        ):
            EnergyAsset.objects.create(
                organization=self.org,
                site=self.site,
                device=device,
                role=role,
                power_scale=0.001,  # W -> kW
                **extra,
            )

        self.tariff = Tariff.objects.create(
            organization=self.org,
            name="Flat",
            currency="TWD",
            timezone_name="Asia/Taipei",
            default_import_price=5.0,
            default_export_price=1.0,
        )
        factories.storage_plan(
            self.org,
            self.site,
            strategy=DispatchStrategy.PEAK_SHAVING,
            tariff=self.tariff,
        )
        self.start = dt.datetime(2026, 6, 1, 4, 0, tzinfo=UTC)

    def sample(self, device, metric: str, value: float, offset_s: int = 0) -> None:
        TelemetrySample.objects.create(
            organization=self.org,
            device=device,
            metric_key=metric,
            ts=self.start + dt.timedelta(seconds=offset_s),
            value=value,
        )

    def test_interval_energy_and_cost(self):
        # Importing 200 kW, generating 50 kW of PV, discharging 100 kW.
        self.sample(self.meter, "grid_power_w", 200_000)
        self.sample(self.pv, "pv_power_w", 50_000)
        self.sample(self.battery, "battery_power_w", 100_000)
        self.sample(self.battery, "battery_soc", 80.0)
        self.sample(self.battery, "battery_soc", 74.0, offset_s=890)

        count = SiteAggregator(self.site).run(
            self.start, self.start + dt.timedelta(minutes=15)
        )
        self.assertEqual(count, 1)

        interval = EnergyInterval.objects.get()
        self.assertAlmostEqual(interval.grid_import_kwh, 50.0, places=4)
        self.assertAlmostEqual(interval.grid_export_kwh, 0.0, places=4)
        self.assertAlmostEqual(interval.pv_kwh, 12.5, places=4)
        self.assertAlmostEqual(interval.battery_discharge_kwh, 25.0, places=4)
        # Derived load = import - export + pv + discharge - charge
        self.assertAlmostEqual(interval.load_kwh, 87.5, places=4)
        self.assertAlmostEqual(interval.peak_import_kw, 200.0, places=4)
        self.assertAlmostEqual(interval.energy_cost, 250.0, places=4)
        self.assertAlmostEqual(interval.soc_start_percent, 80.0)
        self.assertAlmostEqual(interval.soc_end_percent, 74.0)

    def test_savings_credit_the_battery(self):
        self.sample(self.meter, "grid_power_w", 200_000)
        self.sample(self.pv, "pv_power_w", 50_000)
        self.sample(self.battery, "battery_power_w", 100_000)
        self.sample(self.battery, "battery_soc", 80.0)

        SiteAggregator(self.site).run(self.start, self.start + dt.timedelta(minutes=15))
        interval = EnergyInterval.objects.get()

        # Without the battery the site would have imported the full 87.5 - 12.5
        # = 75 kWh at 5.0, i.e. 375; it actually paid 250.
        self.assertAlmostEqual(interval.estimated_savings, 125.0, places=4)

    def test_export_is_recorded_separately(self):
        self.sample(self.meter, "grid_power_w", -80_000)
        self.sample(self.pv, "pv_power_w", 100_000)

        SiteAggregator(self.site).run(self.start, self.start + dt.timedelta(minutes=15))
        interval = EnergyInterval.objects.get()
        self.assertAlmostEqual(interval.grid_export_kwh, 20.0, places=4)
        self.assertAlmostEqual(interval.export_revenue, 20.0, places=4)
        self.assertAlmostEqual(interval.self_consumption_ratio, 0.2, places=4)

    def test_rerun_updates_rather_than_duplicates(self):
        self.sample(self.meter, "grid_power_w", 100_000)
        window = (self.start, self.start + dt.timedelta(minutes=15))
        SiteAggregator(self.site).run(*window)
        SiteAggregator(self.site).run(*window)
        self.assertEqual(EnergyInterval.objects.count(), 1)

    def test_window_with_no_data_produces_no_row(self):
        SiteAggregator(self.site).run(self.start, self.start + dt.timedelta(minutes=15))
        self.assertEqual(EnergyInterval.objects.count(), 0)

    def test_inverted_sign_convention(self):
        EnergyAsset.objects.filter(role=AssetRole.BATTERY).update(invert_sign=True)
        # Device reports positive when charging; inverted, that is charging here.
        self.sample(self.battery, "battery_power_w", 100_000)
        self.sample(self.battery, "battery_soc", 50.0)
        self.sample(self.meter, "grid_power_w", 100_000)

        SiteAggregator(self.site).run(self.start, self.start + dt.timedelta(minutes=15))
        interval = EnergyInterval.objects.get()
        self.assertAlmostEqual(interval.battery_charge_kwh, 25.0, places=4)
        self.assertAlmostEqual(interval.battery_discharge_kwh, 0.0, places=4)


class TariffTestCase(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.tariff = Tariff.objects.create(
            organization=self.org,
            name="TOU",
            timezone_name="Asia/Taipei",
            default_import_price=2.0,
            default_export_price=1.0,
            periods=[
                {
                    "name": "summer_peak",
                    "months": [6, 7, 8, 9],
                    "weekdays": [0, 1, 2, 3, 4],
                    "start": "16:00",
                    "end": "22:00",
                    "import_price": 8.0,
                },
                {"name": "night", "start": "23:00", "end": "07:00", "import_price": 1.5},
            ],
        )

    def test_peak_window_on_a_weekday(self):
        # 2026-06-01 is a Monday; 10:00 UTC is 18:00 in Taipei.
        moment = dt.datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
        price = resolve_price(self.tariff, moment)
        self.assertEqual(price.period_name, "summer_peak")
        self.assertAlmostEqual(price.import_price, 8.0)

    def test_weekend_falls_through_to_the_default(self):
        # 2026-06-06 is a Saturday.
        moment = dt.datetime(2026, 6, 6, 10, 0, tzinfo=UTC)
        price = resolve_price(self.tariff, moment)
        self.assertEqual(price.period_name, "default")
        self.assertAlmostEqual(price.import_price, 2.0)

    def test_window_crossing_midnight(self):
        # 2026-06-01 20:00 UTC is 04:00 on the 2nd in Taipei -> night window.
        moment = dt.datetime(2026, 6, 1, 20, 0, tzinfo=UTC)
        price = resolve_price(self.tariff, moment)
        self.assertEqual(price.period_name, "night")
        self.assertAlmostEqual(price.import_price, 1.5)

    def test_no_tariff_is_free(self):
        price = resolve_price(None, dt.datetime(2026, 6, 1, tzinfo=UTC))
        self.assertEqual(price.import_price, 0.0)

    def test_period_validation_reports_problems(self):
        problems = validate_periods(
            [{"start": "nope", "months": [13], "weekdays": [9]}]
        )
        self.assertEqual(len(problems), 3)
