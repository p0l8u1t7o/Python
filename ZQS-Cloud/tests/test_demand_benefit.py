"""The capacity side of the bill: demand-charge benefit and the strategy's
native-demand correction.

The figures are what a customer is shown as "what the battery earned on the
demand charge", so the arithmetic is pinned exactly.
"""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from apps.ems.demand import demand_benefit, excess_charge
from apps.ems.strategy import _native_demand_kw


class ExcessChargeTests(SimpleTestCase):
    def test_under_contract_costs_nothing(self) -> None:
        self.assertEqual(excess_charge(500.0, 600.0, 236.2), 0.0)

    def test_within_ten_percent_is_billed_double(self) -> None:
        # 30 kW over a 600 kW contract, inside the 60 kW band: 30 x 236.2 x 2.
        self.assertAlmostEqual(excess_charge(630.0, 600.0, 236.2), 30 * 236.2 * 2)

    def test_beyond_ten_percent_is_billed_triple(self) -> None:
        # 100 kW over: the first 60 at 2x, the remaining 40 at 3x.
        expected = 60 * 236.2 * 2 + 40 * 236.2 * 3
        self.assertAlmostEqual(excess_charge(700.0, 600.0, 236.2), expected)

    def test_no_contract_or_rate_means_no_penalty(self) -> None:
        self.assertEqual(excess_charge(700.0, 0.0, 236.2), 0.0)
        self.assertEqual(excess_charge(700.0, 600.0, 0.0), 0.0)


class DemandBenefitTests(SimpleTestCase):
    def test_lower_peak_saves_the_rate_times_the_difference(self) -> None:
        benefit = demand_benefit(
            peak_demand_kw=650.0, baseline_peak_kw=700.0,
            contract_capacity_kw=None, demand_charge_per_kw=236.2,
        )
        self.assertAlmostEqual(benefit.demand_savings, 50 * 236.2)
        self.assertEqual(benefit.penalty_avoided, 0.0)

    def test_staying_under_contract_also_avoids_the_penalty(self) -> None:
        benefit = demand_benefit(
            peak_demand_kw=650.0, baseline_peak_kw=745.0,
            contract_capacity_kw=680.0, demand_charge_per_kw=236.2,
        )
        penalty = excess_charge(745.0, 680.0, 236.2)
        self.assertAlmostEqual(benefit.penalty_avoided, penalty)
        self.assertAlmostEqual(benefit.demand_savings, 95 * 236.2 + penalty)

    def test_a_higher_peak_than_baseline_is_reported_negative(self) -> None:
        # A night-time charge that set the month's peak: an honest minus.
        benefit = demand_benefit(
            peak_demand_kw=1100.0, baseline_peak_kw=1050.0,
            contract_capacity_kw=1100.0, demand_charge_per_kw=236.2,
        )
        self.assertLess(benefit.demand_savings, 0)

    def test_no_rate_means_no_figure(self) -> None:
        benefit = demand_benefit(
            peak_demand_kw=650.0, baseline_peak_kw=700.0,
            contract_capacity_kw=680.0, demand_charge_per_kw=0.0,
        )
        self.assertEqual(benefit.demand_savings, 0.0)
        self.assertEqual(benefit.as_dict()["demand_savings"], 0.0)

    def test_missing_peaks_yield_none_not_zero(self) -> None:
        benefit = demand_benefit(
            peak_demand_kw=None, baseline_peak_kw=None,
            contract_capacity_kw=680.0, demand_charge_per_kw=236.2,
        )
        self.assertIsNone(benefit.as_dict()["peak_demand_kw"])
        self.assertEqual(benefit.demand_savings, 0.0)


class NativeDemandTests(SimpleTestCase):
    """The strategies decide from demand *without* the battery's own flow,
    or a charge lifts the meter, the next cycle orders a discharge, and the
    battery chases its tail."""

    def test_a_charging_battery_is_subtracted(self) -> None:
        # Meter 690 kW while charging 120 kW: the site itself draws 570.
        self.assertAlmostEqual(_native_demand_kw({"grid_kw": 690.0, "battery_kw": -120.0}), 570.0)

    def test_a_discharging_battery_is_added_back(self) -> None:
        self.assertAlmostEqual(_native_demand_kw({"grid_kw": 500.0, "battery_kw": 150.0}), 650.0)

    def test_no_battery_reading_means_the_meter(self) -> None:
        self.assertAlmostEqual(_native_demand_kw({"grid_kw": 500.0}), 500.0)

    def test_no_meter_reading_means_none(self) -> None:
        self.assertIsNone(_native_demand_kw({"battery_kw": 10.0}))


class CostOverviewDemandTests(TestCase):
    """The overview carries the demand figures per site, from the intervals."""

    def test_peaks_come_from_interval_averages(self) -> None:
        import datetime as dt

        from django.utils import timezone

        from apps.ems.models import EnergyInterval, StoragePlan, Tariff
        from apps.ems.rollup import demand_by_site
        from tests import factories

        org = factories.organization()
        site = factories.site(org, "plant")
        tariff = Tariff.objects.create(
            organization=org, name="lv", demand_charge_per_kw=236.2, default_import_price=2.0
        )
        plan = StoragePlan.objects.create(
            organization=org, name="cap", strategy="demand_cap",
            contract_capacity_kw=680.0, tariff=tariff,
        )
        site.storage_plan = plan
        site.save(update_fields=["storage_plan"])

        start = timezone.now().replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=2)
        # Two quarter hours: the first with the battery shaving 100 kW, the
        # second idle. Load 700 kW (175 kWh / 15 min), PV 0.
        EnergyInterval.objects.create(
            organization=org, site=site, interval_start=start, interval_seconds=900,
            grid_import_kwh=150.0, load_kwh=175.0, pv_kwh=0.0,
            battery_discharge_kwh=25.0,
        )
        EnergyInterval.objects.create(
            organization=org, site=site,
            interval_start=start + dt.timedelta(minutes=15), interval_seconds=900,
            grid_import_kwh=160.0, load_kwh=160.0, pv_kwh=0.0,
        )
        peaks = demand_by_site([site.pk], start, start + dt.timedelta(hours=1))
        self.assertAlmostEqual(peaks[site.pk]["peak_demand_kw"], 640.0)
        self.assertAlmostEqual(peaks[site.pk]["baseline_peak_kw"], 700.0)
