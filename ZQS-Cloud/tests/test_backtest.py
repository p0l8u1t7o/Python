"""W3 離線回測。

釘住的失敗模式：回測寫了資料庫；策略在回測裡走另一套邏輯；節省永遠是正的；
殘缺區間被當成 0 重播。
"""

from __future__ import annotations

import datetime as dt

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.ems.backtest import backtest_with_baseline, compare_strategies, run_backtest
from apps.ems.models import (
    AssetRole,
    DispatchStrategy,
    EnergyAsset,
    EnergyInterval,
    StoragePlan,
    Tariff,
)
from tests import factories

UTC = dt.timezone.utc


class BacktestTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, "plant")
        self.battery = factories.device(self.org, "BESS-1", site_obj=self.site)
        EnergyAsset.objects.create(
            organization=self.org, site=self.site, device=self.battery,
            role=AssetRole.BATTERY, power_metric="battery_power_kw", soc_metric="soc",
            cost_parameters={"cycle_cost_per_kwh": 2.0},
        )
        # 平價 3 元、需量費 200 元/kW、沒有尖離峰——套利應該完全不動。
        self.tariff = Tariff.objects.create(
            organization=self.org, name="flat", timezone_name="Asia/Taipei",
            default_import_price=3.0, demand_charge_per_kw=200.0, periods=[],
        )
        self.plan = StoragePlan.objects.create(
            organization=self.org, name="cap", strategy=DispatchStrategy.DEMAND_CAP,
            tariff=self.tariff, contract_capacity_kw=600.0, demand_cap_target_kw=500.0,
            usable_capacity_kwh=400.0, max_charge_kw=200.0, max_discharge_kw=200.0,
            min_soc_percent=10.0, backup_reserve_percent=10.0, max_soc_percent=100.0,
            round_trip_efficiency=1.0, offpeak_recharge=True,
        )
        self.start = dt.datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
        self.end = self.start + dt.timedelta(days=1)

    def intervals(self, profile):
        """``profile(hour) -> load_kw``；一天 96 個區間。"""
        rows = []
        cursor = self.start
        while cursor < self.end:
            load_kw = profile(cursor.hour)
            rows.append(EnergyInterval(
                organization=self.org, site=self.site, interval_start=cursor,
                interval_seconds=900, load_kwh=load_kw * 0.25, grid_import_kwh=load_kw * 0.25,
                pv_kwh=0.0, coverage=1.0,
            ))
            cursor += dt.timedelta(minutes=15)
        EnergyInterval.objects.bulk_create(rows)

    def test_demand_cap_shaves_the_peak_and_writes_nothing(self) -> None:
        # 夜間 300 kW、09–11 點 650 kW 的尖峰：電池 200 kW 足以壓到 500。
        self.intervals(lambda h: 650.0 if 9 <= h < 11 else 300.0)
        before = {
            "intervals": EnergyInterval.objects.count(),
            "plans": StoragePlan.objects.count(),
        }
        with CaptureQueriesContext(connection) as queries:
            result = backtest_with_baseline(self.site, self.plan, self.start, self.end)
        writes = [q["sql"] for q in queries.captured_queries if q["sql"].split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}]
        self.assertEqual(writes, [], "backtest must not write")
        self.assertEqual(before["intervals"], EnergyInterval.objects.count())
        self.assertEqual(before["plans"], StoragePlan.objects.count())

        self.assertAlmostEqual(result.peak_demand_kw, 500.0, delta=1.0)
        self.assertEqual(result.penalty, 0.0)
        self.assertAlmostEqual(result.demand_charge, 500.0 * 200.0, delta=200.0)
        # 對照組的峰值 650 kW → 超約 50 kW 罰款；節省為正。
        self.assertGreater(result.savings, 0)
        self.assertGreater(result.equivalent_cycles, 0)
        self.assertEqual(len(result.intervals), 96)

    def test_savings_can_be_negative(self) -> None:
        """尖峰本來就在上限下：電池只會磨循環成本，節省是負的、不是 0。"""
        self.intervals(lambda h: 450.0)
        plan = self.plan
        plan.strategy = DispatchStrategy.SELF_CONSUMPTION  # 只改記憶體內的物件
        result = backtest_with_baseline(self.site, plan, self.start, self.end)
        # 沒有 PV、負載恆定：自發自用會一路放電補「負載缺口」直到 SOC 底；
        # 沒有任何需量或能源費用的好處，只剩循環成本。
        self.assertLess(result.savings, 0)
        # 放掉的初始電量以平均電價計回（3 元 × 160 kWh），再加循環成本。
        self.assertAlmostEqual(result.stored_energy_adjustment, 160.0 * 3.0, delta=0.01)
        self.assertAlmostEqual(result.savings, -result.cycle_cost, delta=0.01)

    def test_incomplete_intervals_are_skipped_not_zeroed(self) -> None:
        self.intervals(lambda h: 450.0)
        EnergyInterval.objects.filter(interval_start__hour__lt=6).update(coverage=0.2)
        result = run_backtest(self.site, self.plan, self.start, self.end)
        self.assertEqual(len(result.intervals), 96 - 24)
        self.assertTrue(all(i.native_load_kw > 0 for i in result.intervals))

    def test_compare_ranks_by_total_and_shares_one_baseline(self) -> None:
        self.intervals(lambda h: 650.0 if 9 <= h < 11 else 300.0)
        results = compare_strategies(self.site, self.plan, self.start, self.end)
        totals = [r.total for r in results]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(len({r.baseline_total for r in results}), 1)
        self.assertEqual(results[0].strategy, DispatchStrategy.DEMAND_CAP)
        # 平價方案：套利沒有價差，什麼都不做 → 與無電池對照組同價。
        tou = next(r for r in results if r.strategy == DispatchStrategy.TOU_ARBITRAGE)
        self.assertAlmostEqual(tou.total, tou.baseline_total, delta=0.01)
        # 原方案的策略沒有被改掉。
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.strategy, DispatchStrategy.DEMAND_CAP)

    def test_no_tariff_means_zero_money_and_a_note(self) -> None:
        self.intervals(lambda h: 300.0)
        self.plan.tariff = None
        result = run_backtest(self.site, self.plan, self.start, self.end)
        self.assertEqual(result.energy_cost, 0.0)
        self.assertEqual(result.demand_charge, 0.0)
        self.assertTrue(any("no tariff" in n for n in result.notes))
