"""W4 月結算。

驗收：整月窗口的 cost-overview 數字 = 結算表；封存後改電價數字不變；重跑相同；
savings 可為負、無基準線為 null；次月 5 號封存。
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.ems import rollup
from apps.ems.demand import excess_charge
from apps.ems.models import (
    DispatchStrategy,
    EnergyInterval,
    MonthlySettlement,
    SavingsBaseline,
    SettlementBasis,
    StoragePlan,
    Tariff,
)
from apps.ems.settlement import finalize_if_due, month_bounds, months_to_settle, parse_month, settle
from tests import factories

UTC = dt.timezone.utc
MONTH = dt.date(2026, 7, 1)


class SettlementTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, "plant", timezone_name="Asia/Taipei")
        self.tariff = Tariff.objects.create(
            organization=self.org, name="flat", timezone_name="Asia/Taipei",
            default_import_price=3.0, default_export_price=1.0, demand_charge_per_kw=200.0, periods=[],
        )
        self.plan = StoragePlan.objects.create(
            organization=self.org, name="cap", strategy=DispatchStrategy.DEMAND_CAP,
            tariff=self.tariff, contract_capacity_kw=600.0, savings_baseline=SavingsBaseline.NO_STORAGE,
        )
        self.site.storage_plan = self.plan
        self.site.save(update_fields=["storage_plan"])
        self.start, self.end = month_bounds(self.site, MONTH)

    def fill_month(self, *, load_kw=400.0, peak_kw=700.0, peak_hour=10, savings_per_interval=1.5,
                   battery_kw=100.0, coverage=1.0):
        rows = []
        cursor = self.start
        while cursor < self.end:
            native = peak_kw if cursor.astimezone(dt.timezone(dt.timedelta(hours=8))).hour == peak_hour else load_kw
            grid = native - battery_kw if native == peak_kw else native
            rows.append(EnergyInterval(
                organization=self.org, site=self.site, interval_start=cursor, interval_seconds=900,
                load_kwh=native * 0.25, pv_kwh=0.0, grid_import_kwh=grid * 0.25, grid_export_kwh=0.01,
                battery_discharge_kwh=(native - grid) * 0.25,
                energy_cost=grid * 0.25 * 3.0, export_revenue=0.01, estimated_savings=savings_per_interval,
                coverage=coverage,
            ))
            cursor += dt.timedelta(minutes=15)
        EnergyInterval.objects.bulk_create(rows)
        return len(rows)

    def test_month_bounds_follow_site_timezone(self) -> None:
        self.assertEqual(self.start, dt.datetime(2026, 6, 30, 16, 0, tzinfo=UTC))
        self.assertEqual(self.end, dt.datetime(2026, 7, 31, 16, 0, tzinfo=UTC))
        self.assertEqual(parse_month("2026-07"), MONTH)

    def test_settlement_matches_cost_overview_over_the_month_window(self) -> None:
        count = self.fill_month()
        row = settle(self.site, MONTH)
        costs = rollup.cost_by_site([self.site.pk], self.start, self.end)[self.site.pk]
        demand = rollup.demand_by_site([self.site.pk], self.start, self.end)[self.site.pk]
        self.assertAlmostEqual(row.energy_charge, costs["energy_cost"], places=2)
        self.assertAlmostEqual(row.export_revenue, costs["export_revenue"], places=2)
        self.assertAlmostEqual(row.peak_demand_kw, demand["peak_demand_kw"], places=3)
        self.assertAlmostEqual(row.baseline_peak_kw, demand["baseline_peak_kw"], places=3)
        self.assertEqual(row.interval_count, count)
        self.assertEqual(row.basis, SettlementBasis.MEASURED)
        self.assertAlmostEqual(row.coverage, 1.0)
        # 需量費 = 峰值 600 kW × 200；無超約。基準線峰值 700 → 罰款 100 kW 超約。
        self.assertAlmostEqual(row.demand_charge, 600.0 * 200.0, places=2)
        self.assertEqual(row.excess_penalty, 0.0)
        self.assertAlmostEqual(row.total, row.energy_charge + row.demand_charge - row.export_revenue, places=2)
        expected_baseline = (
            row.energy_charge + costs["estimated_savings"] + 700.0 * 200.0 + excess_charge(700.0, 600.0, 200.0)
            - row.export_revenue
        )
        self.assertAlmostEqual(row.baseline_total, expected_baseline, places=2)
        self.assertAlmostEqual(row.savings, expected_baseline - row.total, places=2)
        self.assertGreater(row.savings, 0)
        self.assertEqual(row.peak_occurred_at.astimezone(dt.timezone(dt.timedelta(hours=8))).hour, 10)
        self.assertEqual(row.tariff_snapshot["tariff"]["demand_charge_per_kw"], 200.0)

    def test_rerun_is_idempotent(self) -> None:
        self.fill_month()
        first = settle(self.site, MONTH)
        second = settle(self.site, MONTH)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(MonthlySettlement.objects.count(), 1)
        for field in ("total", "savings", "peak_demand_kw", "demand_charge", "energy_charge"):
            self.assertEqual(getattr(first, field), getattr(second, field))

    def test_finalized_month_ignores_a_later_tariff_change(self) -> None:
        self.fill_month()
        row = settle(self.site, MONTH)
        self.assertTrue(finalize_if_due(row, today=dt.date(2026, 8, 5)))
        frozen_total = row.total
        self.tariff.demand_charge_per_kw = 999.0
        self.tariff.save()
        again = settle(self.site, MONTH)
        self.assertEqual(again.total, frozen_total)
        self.assertEqual(again.tariff_snapshot["tariff"]["demand_charge_per_kw"], 200.0)
        # 明確 force 才重算——而且重算會用新電價。
        forced = settle(self.site, MONTH, force=True)
        self.assertNotEqual(forced.total, frozen_total)

    def test_open_month_follows_a_tariff_change(self) -> None:
        self.fill_month()
        before = settle(self.site, MONTH).total
        self.tariff.demand_charge_per_kw = 300.0
        self.tariff.save()
        self.assertNotEqual(settle(self.site, MONTH).total, before)

    def test_finalize_waits_for_the_fifth(self) -> None:
        self.fill_month()
        row = settle(self.site, MONTH)
        self.assertFalse(finalize_if_due(row, today=dt.date(2026, 8, 4)))
        self.assertIsNone(row.finalized_at)
        self.assertTrue(finalize_if_due(row, today=dt.date(2026, 8, 5)))
        self.assertIsNotNone(row.finalized_at)
        self.assertFalse(finalize_if_due(row, today=dt.date(2026, 9, 1)), "already finalized")

    def test_savings_null_when_any_interval_has_no_baseline(self) -> None:
        self.fill_month()
        EnergyInterval.objects.filter(site=self.site, interval_start=self.start).update(estimated_savings=None)
        row = settle(self.site, MONTH)
        self.assertIsNone(row.savings)
        self.assertIsNone(row.baseline_total)
        self.assertGreater(row.total, 0)

    def test_savings_can_be_negative(self) -> None:
        # 電池沒有削峰（battery_kw=0 → 峰值 = 基準線），每區間 savings −1：調度花更多。
        self.fill_month(battery_kw=0.0, savings_per_interval=-1.0)
        row = settle(self.site, MONTH)
        self.assertLess(row.savings, 0)
        self.assertAlmostEqual(row.excess_penalty, excess_charge(700.0, 600.0, 200.0), places=2)

    def test_basis_takes_the_worst_interval(self) -> None:
        self.fill_month()
        EnergyInterval.objects.filter(site=self.site, interval_start=self.start).update(coverage=0.5)
        self.assertEqual(settle(self.site, MONTH).basis, SettlementBasis.ESTIMATED)
        EnergyInterval.objects.filter(site=self.site, interval_start__lt=self.start + dt.timedelta(days=20)).delete()
        self.assertEqual(settle(self.site, MONTH).basis, SettlementBasis.UNKNOWN)

    def test_months_to_settle_are_local(self) -> None:
        self.assertEqual(
            months_to_settle(self.site, today=dt.date(2026, 8, 23)), [dt.date(2026, 7, 1), dt.date(2026, 8, 1)]
        )
        self.assertEqual(
            months_to_settle(self.site, today=dt.date(2026, 1, 3)), [dt.date(2025, 12, 1), dt.date(2026, 1, 1)]
        )
