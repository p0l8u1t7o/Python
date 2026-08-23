"""W5 策略疊加仲裁。

釘住：單策略行為一個位元都不變；硬約束永遠不被軟目標推翻（套利收益很高
但會超約 → 不套利）；回測證明「套利 + 需量」優於單獨任一個。
"""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from apps.ems import demand_window
from apps.ems.arbitration import STACKABLE, arbitrate, propose
from apps.ems.backtest import run_backtest
from apps.ems.models import AssetRole, DispatchStrategy, EnergyAsset, EnergyInterval, StoragePlan
from apps.ems.strategy import single_strategy_power_w, strategy_power_w
from tests.test_storage_strategies import TPE, StrategyTestCase

UTC = dt.timezone.utc


class StackingTests(StrategyTestCase):
    def setUp(self) -> None:
        super().setUp()
        demand_window._last_decision.clear()
        EnergyAsset.objects.filter(role=AssetRole.BATTERY).update(cost_parameters={"cycle_cost_per_kwh": 1.0})

    def stacked(self, *strategies, **kwargs) -> StoragePlan:
        plan = self.plan(strategies[0], **kwargs)
        plan.strategies = list(strategies)
        plan.save(update_fields=["strategies"])
        return plan

    # ---- 相容性 -----------------------------------------------------------
    def test_single_strategy_plans_are_untouched(self) -> None:
        tariff = self.tou_tariff()
        self.reading(self.meter, "grid_power_kw", 480.0)
        self.reading(self.pv, "pv_power_kw", 100.0)
        self.reading(self.battery, "battery_soc", 40.0)
        for key in STACKABLE:
            plan = self.plan(key, tariff=tariff, demand_cap_target_kw=500.0, contract_capacity_kw=600.0)
            self.assertEqual(plan.active_strategies, [key])
            moment = dt.datetime(2026, 7, 15, 18, 0, tzinfo=TPE)
            direct = single_strategy_power_w(plan, self.site.pk, moment, key)
            via = strategy_power_w(plan, self.site.pk, moment)
            self.assertEqual((direct.power_w, direct.reason), (via.power_w, via.reason), key)

    def test_migration_shape_single_element_list_is_still_single(self) -> None:
        plan = self.stacked(DispatchStrategy.DEMAND_CAP, demand_cap_target_kw=500.0)
        self.assertEqual(plan.active_strategies, [DispatchStrategy.DEMAND_CAP])
        self.reading(self.meter, "grid_power_kw", 520.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertAlmostEqual(decision.power_w, 20_000.0, delta=1.0)

    # ---- 硬約束 > 軟目標 --------------------------------------------------
    def test_lucrative_arbitrage_charge_is_capped_by_demand_headroom(self) -> None:
        """離峰電價最低、套利想用 999 kW 充電，但需量餘裕只有 20 kW：充 20。"""
        tariff = self.tou_tariff()
        plan = self.stacked(
            DispatchStrategy.DEMAND_CAP, DispatchStrategy.TOU_ARBITRAGE,
            tariff=tariff, demand_cap_target_kw=500.0, max_charge_kw=999.0, offpeak_recharge=False,
        )
        self.reading(self.meter, "grid_power_kw", 480.0)
        off_peak = dt.datetime(2026, 7, 15, 3, 0, tzinfo=TPE)
        proposals = propose(plan, self.site.pk, off_peak)
        arb = next(p for p in proposals if p.strategy == DispatchStrategy.TOU_ARBITRAGE)
        self.assertLess(arb.power_w, -100_000.0, "arbitrage itself wants a big charge")
        self.assertGreater(arb.value_per_hour, 0)
        decision = strategy_power_w(plan, self.site.pk, off_peak)
        self.assertAlmostEqual(decision.power_w, -20_000.0, delta=1.0)
        self.assertIn("capped", decision.reason)

    def test_arbitrage_cannot_charge_when_already_over_the_ceiling(self) -> None:
        tariff = self.tou_tariff()
        plan = self.stacked(
            DispatchStrategy.DEMAND_CAP, DispatchStrategy.TOU_ARBITRAGE,
            tariff=tariff, demand_cap_target_kw=500.0, max_charge_kw=999.0,
        )
        self.reading(self.meter, "grid_power_kw", 530.0)  # 超過上限 30 kW
        off_peak = dt.datetime(2026, 7, 15, 3, 0, tzinfo=TPE)
        decision = strategy_power_w(plan, self.site.pk, off_peak)
        self.assertAlmostEqual(decision.power_w, 30_000.0, delta=1.0, msg="discharge, never charge")
        self.assertIn("raised", decision.reason)

    def test_arbitrage_discharge_adds_to_demand_discharge_at_peak(self) -> None:
        """尖峰：需量要放 30 kW，套利想放 100 kW（上限）：放 100——兩者同向，取大者。"""
        tariff = self.tou_tariff()
        plan = self.stacked(
            DispatchStrategy.DEMAND_CAP, DispatchStrategy.TOU_ARBITRAGE,
            tariff=tariff, demand_cap_target_kw=500.0, max_discharge_kw=100.0, export_limit_kw=0.0,
        )
        self.reading(self.meter, "grid_power_kw", 530.0)
        peak = dt.datetime(2026, 7, 15, 18, 0, tzinfo=TPE)
        decision = strategy_power_w(plan, self.site.pk, peak)
        self.assertAlmostEqual(decision.power_w, 100_000.0, delta=1.0)
        self.assertIn("tou_arbitrage", decision.reason)

    def test_arbitrage_not_worth_it_falls_back_to_demand_cap_recharge(self) -> None:
        """循環成本高過價差：套利價值 ≤ 0，不做；需量策略自己的離峰回充照跑。"""
        EnergyAsset.objects.filter(role=AssetRole.BATTERY).update(cost_parameters={"cycle_cost_per_kwh": 50.0})
        tariff = self.tou_tariff()
        plan = self.stacked(
            DispatchStrategy.DEMAND_CAP, DispatchStrategy.TOU_ARBITRAGE,
            tariff=tariff, demand_cap_target_kw=500.0, max_charge_kw=999.0, offpeak_recharge=True,
        )
        self.reading(self.meter, "grid_power_kw", 480.0)
        off_peak = dt.datetime(2026, 7, 15, 3, 0, tzinfo=TPE)
        decision = strategy_power_w(plan, self.site.pk, off_peak)
        self.assertAlmostEqual(decision.power_w, -20_000.0, delta=1.0)
        self.assertIn("not worth it", decision.reason)
        self.assertIn("off-peak recharge", decision.reason)

    def test_backup_reserve_yields_to_demand_cap(self) -> None:
        plan = self.stacked(
            DispatchStrategy.DEMAND_CAP, DispatchStrategy.BACKUP_ONLY,
            demand_cap_target_kw=500.0, backup_reserve_percent=50.0, max_charge_kw=100.0,
        )
        self.reading(self.meter, "grid_power_kw", 540.0)
        self.reading(self.battery, "battery_soc", 20.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertAlmostEqual(decision.power_w, 40_000.0, delta=1.0)
        self.assertIn("demand cap outranks", decision.reason)

    def test_backup_reserve_charge_respects_demand_headroom(self) -> None:
        plan = self.stacked(
            DispatchStrategy.DEMAND_CAP, DispatchStrategy.BACKUP_ONLY,
            demand_cap_target_kw=500.0, backup_reserve_percent=50.0, max_charge_kw=100.0,
        )
        self.reading(self.meter, "grid_power_kw", 470.0)
        self.reading(self.battery, "battery_soc", 20.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertAlmostEqual(decision.power_w, -30_000.0, delta=1.0)

    def test_unknown_or_unstackable_keys_are_ignored(self) -> None:
        plan = self.stacked(DispatchStrategy.DEMAND_CAP, DispatchStrategy.MANUAL, "nonsense", demand_cap_target_kw=500.0)
        self.reading(self.meter, "grid_power_kw", 520.0)
        proposals = propose(plan, self.site.pk, timezone.now())
        self.assertEqual([p.strategy for p in proposals], [DispatchStrategy.DEMAND_CAP])
        self.assertAlmostEqual(arbitrate(proposals, plan).power_w, 20_000.0, delta=1.0)

    # ---- 回測證明 -----------------------------------------------------------
    def test_backtest_stacking_beats_each_strategy_alone(self) -> None:
        """離峰 2 元、尖峰 7 元；白天 10–12 點有 650 kW 的負載尖峰（上限 500）。
        單做需量：只削尖峰；單做套利：尖峰時段放電但白天尖峰超約；疊加：兩者都賺。"""
        tariff = self.tou_tariff()
        tariff.demand_charge_per_kw = 200.0
        tariff.save()
        plan = self.plan(
            DispatchStrategy.DEMAND_CAP, tariff=tariff, demand_cap_target_kw=500.0, contract_capacity_kw=600.0,
            usable_capacity_kwh=800.0, max_charge_kw=300.0, max_discharge_kw=300.0, export_limit_kw=0.0,
            min_soc_percent=10.0, backup_reserve_percent=10.0, max_soc_percent=100.0, round_trip_efficiency=1.0,
            min_price_spread=1.0, offpeak_recharge=True,
        )
        start = dt.datetime(2026, 7, 6, 0, 0, tzinfo=TPE).astimezone(UTC)
        end = start + dt.timedelta(days=3)
        rows = []
        cursor = start
        while cursor < end:
            hour = cursor.astimezone(TPE).hour
            load = 650.0 if 10 <= hour < 12 else 300.0
            rows.append(EnergyInterval(
                organization=self.org, site=self.site, interval_start=cursor, interval_seconds=900,
                load_kwh=load * 0.25, grid_import_kwh=load * 0.25, pv_kwh=0.0, coverage=1.0,
            ))
            cursor += dt.timedelta(minutes=15)
        EnergyInterval.objects.bulk_create(rows)

        cap = run_backtest(self.site, plan, start, end, strategy=DispatchStrategy.DEMAND_CAP, keep_intervals=False)
        tou = run_backtest(self.site, plan, start, end, strategy=DispatchStrategy.TOU_ARBITRAGE, keep_intervals=False)
        both = run_backtest(
            self.site, plan, start, end,
            strategy=[DispatchStrategy.DEMAND_CAP, DispatchStrategy.TOU_ARBITRAGE], keep_intervals=False,
        )
        self.assertLess(both.total, cap.total)
        self.assertLess(both.total, tou.total)
        # 逐項解釋：疊加的需量費／罰款與單做需量相同（硬約束守住了），能源費低於單做需量（套利賺到）。
        self.assertAlmostEqual(both.penalty, cap.penalty, delta=1.0)
        self.assertAlmostEqual(both.peak_demand_kw, cap.peak_demand_kw, delta=1.0)
        self.assertLess(both.energy_cost, cap.energy_cost)
        self.assertGreater(tou.penalty, 0, "arbitrage alone lets the noon spike exceed the contract")
