"""W2 需量窗口積分控制。

驗收情境來自 ZQS-Cloud-next-phase.md §W2：階躍負載 400→900 kW、上限 650，
放電必須從第 6 分鐘開始；窗口尾端不重算；邊界不歸零；涵蓋率不足退回瞬時。
"""

from __future__ import annotations

import datetime as dt
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.ems import demand_window
from apps.ems.demand_window import MIN_REMAINING_H, WindowState, required_discharge_kw, window_state
from apps.ems.forecast import ErrorStats
from apps.ems.models import AssetRole, DispatchStrategy, EnergyAsset, StoragePlan
from apps.ems.strategy import strategy_power_w
from apps.telemetry.models import LatestSample, TelemetrySample
from tests import factories

UTC = dt.timezone.utc


def _state(elapsed_min: float, accumulated_kwh: float, *, coverage: float = 1.0) -> WindowState:
    start = dt.datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    return WindowState(
        window_start=start, accumulated_kwh=accumulated_kwh, coverage=coverage,
        is_trustworthy=coverage >= demand_window.MIN_COVERAGE, elapsed_h=elapsed_min / 60.0,
    )


class RequiredDischargeTests(TestCase):
    """純算術，不碰資料庫。"""

    def test_step_load_starts_discharging_from_minute_six(self) -> None:
        """400 kW 跑 5 分鐘後跳到 900 kW，上限 650：
        第 5 分鐘尚未超（400×5 + 900×10 = 11,000 kWh·min → 平均 733 > 650，
        其實在跳上去的那一刻就該放）；規格要求最晚第 6 分鐘開始放電。"""
        start = dt.datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        # 前 5 分鐘 400 kW：累積 33.33 kWh
        before_step = _state(5, 400 * 5 / 60)
        need = required_discharge_kw(before_step, 650.0, 400.0, start + dt.timedelta(minutes=5))
        self.assertLess(need, 0, "still at 400 kW the window has headroom")

        # 第 6 分鐘：負載已跳到 900 kW，剩餘 9 分鐘預測 900
        at_six = _state(6, 400 * 5 / 60 + 900 * 1 / 60)
        need = required_discharge_kw(at_six, 650.0, 900.0, start + dt.timedelta(minutes=6))
        # 窗口預期平均 = (33.33 + 15 + 900×9/60) / 0.25 = 733.3 kW；
        # 超出 83.3 kW × 0.25 h = 20.8 kWh，要在剩餘 9 分鐘內削掉 → 138.9 kW。
        self.assertAlmostEqual(need, 138.9, delta=0.5)
        self.assertGreater(need, 0)

        # 驗證：照這個功率放到窗口結束，平均正好落在上限。
        avg = (at_six.accumulated_kwh + (900 - need) * at_six.remaining_h) / 0.25
        self.assertAlmostEqual(avg, 650.0, delta=0.01)

    def test_instantaneous_logic_would_have_acted_too_late(self) -> None:
        """對照組：瞬時邏輯只在 900 > 650 時放 250 kW，但窗口平均早就救不回來
        的情形——積分版在第 13 分鐘要求的功率明顯大於瞬時差值。"""
        start = dt.datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        late = _state(13, 400 * 5 / 60 + 900 * 8 / 60)
        need = required_discharge_kw(late, 650.0, 900.0, start + dt.timedelta(minutes=13))
        self.assertGreater(need, 900 - 650)

    def test_tail_of_window_holds_previous_setpoint(self) -> None:
        start = dt.datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        tail = _state(14.5, 200.0)  # 剩 30 秒 < MIN_REMAINING_H
        self.assertLess(tail.remaining_h, MIN_REMAINING_H)
        self.assertEqual(
            required_discharge_kw(tail, 650.0, 900.0, start + dt.timedelta(seconds=870), previous_kw=120.0),
            120.0,
        )
        self.assertIsNone(required_discharge_kw(tail, 650.0, 900.0, start + dt.timedelta(seconds=870)))

    def test_just_before_threshold_still_recomputes(self) -> None:
        start = dt.datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        state = _state(13.5, 200.0)  # 剩 90 秒
        need = required_discharge_kw(state, 650.0, 900.0, start + dt.timedelta(seconds=810), previous_kw=120.0)
        self.assertNotEqual(need, 120.0)
        self.assertIsNotNone(need)


class WindowStrategyTests(TestCase):
    """透過 strategy_power_w 走完整路徑：遙測 → window_state → 決策。"""

    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, "plant")
        self.battery = factories.device(self.org, "BESS-1", site_obj=self.site)
        self.meter = factories.device(self.org, "METER-1", site_obj=self.site)
        EnergyAsset.objects.create(
            organization=self.org, site=self.site, device=self.battery,
            role=AssetRole.BATTERY, power_metric="battery_power_kw",
        )
        EnergyAsset.objects.create(
            organization=self.org, site=self.site, device=self.meter,
            role=AssetRole.GRID_METER, power_metric="grid_power_kw",
        )
        self.plan = StoragePlan.objects.create(
            organization=self.org, name="cap", strategy=DispatchStrategy.DEMAND_CAP,
            demand_cap_target_kw=650.0, max_charge_kw=500.0, max_discharge_kw=500.0,
            usable_capacity_kwh=1000.0,
        )
        self.site.storage_plan = self.plan
        self.site.save(update_fields=["storage_plan"])
        demand_window._last_decision.clear()
        # 沒有預測、沒有誤差統計：只測窗口算術本身。
        self._patches = [
            mock.patch("apps.ems.forecast.forecast_site", return_value=[]),
            mock.patch("apps.ems.forecast.forecast_error_stats",
                       return_value=ErrorStats(self.site.id, 14, 0, None, None, None, None)),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def sample(self, ts: dt.datetime, grid_kw: float, battery_kw: float = 0.0) -> None:
        TelemetrySample.objects.create(
            organization=self.org, device=self.meter, metric_key="grid_power_kw", ts=ts, value=grid_kw,
        )
        TelemetrySample.objects.create(
            organization=self.org, device=self.battery, metric_key="battery_power_kw", ts=ts, value=battery_kw,
        )
        LatestSample.objects.update_or_create(
            organization=self.org, device=self.meter, metric_key="grid_power_kw",
            defaults={"value": grid_kw, "ts": timezone.now(), "quality": 0},
        )
        LatestSample.objects.update_or_create(
            organization=self.org, device=self.battery, metric_key="battery_power_kw",
            defaults={"value": battery_kw, "ts": timezone.now(), "quality": 0},
        )

    def test_window_state_integrates_native_demand_with_battery_restored(self) -> None:
        start = dt.datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        for minute in range(0, 10, 1):
            # 電表 300 kW、電池放電 100 kW → native 400 kW
            self.sample(start + dt.timedelta(minutes=minute), 300.0, 100.0)
        state = window_state(self.site, start + dt.timedelta(minutes=10))
        self.assertTrue(state.is_trustworthy)
        self.assertAlmostEqual(state.accumulated_kwh, 400 * 10 / 60, delta=0.01)
        self.assertAlmostEqual(state.last_native_kw, 400.0)

    def test_step_load_discharges_from_minute_six(self) -> None:
        start = dt.datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        for minute in range(0, 5):
            self.sample(start + dt.timedelta(minutes=minute), 400.0)
        self.sample(start + dt.timedelta(minutes=5), 900.0)
        decision = strategy_power_w(self.plan, self.site.pk, start + dt.timedelta(minutes=6))
        self.assertIn("window projection", decision.reason)
        self.assertAlmostEqual(decision.power_w, 138_900.0, delta=1_000.0)

    def test_low_coverage_falls_back_to_instantaneous_with_reason(self) -> None:
        start = dt.datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        # 前 10 分鐘沒有任何樣本，第 10 分鐘才出現一筆 → 涵蓋率 ≈ 0.17
        self.sample(start + dt.timedelta(minutes=10), 700.0)
        decision = strategy_power_w(self.plan, self.site.pk, start + dt.timedelta(minutes=12))
        self.assertIn("window fallback", decision.reason)
        self.assertIn("coverage", decision.reason)
        # 瞬時邏輯：700 − 650 = 50 kW
        self.assertAlmostEqual(decision.power_w, 50_000.0, delta=1.0)
        self.assertIn("over ceiling", decision.reason)

    def test_window_boundary_holds_previous_setpoint(self) -> None:
        start = dt.datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        for minute in range(0, 14):
            self.sample(start + dt.timedelta(minutes=minute), 900.0)
        first = strategy_power_w(self.plan, self.site.pk, start + dt.timedelta(minutes=2))
        self.assertGreater(first.power_w, 0)
        # 新窗口第一秒：窗口內還沒有樣本，靠前值保持（seed）延續上一窗口的
        # 負載，設定點連續而不是歸零再重建。
        at_boundary = strategy_power_w(self.plan, self.site.pk, start + dt.timedelta(minutes=15, seconds=1))
        # 穩態 900 kW、上限 650、整個窗口都在前面：正好 250 kW，不是 0。
        self.assertAlmostEqual(at_boundary.power_w, 250_000.0, delta=1_000.0)

    def test_window_boundary_without_any_telemetry_holds_last_setpoint(self) -> None:
        """連 seed 都沒有（閘道剛好在邊界斷線一拍）：沿用上一輪記住的設定點。"""
        start = dt.datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
        demand_window.remember(self.site.id, start - dt.timedelta(minutes=15), 120.0)
        self.sample(start - dt.timedelta(hours=2), 900.0)  # 太舊，不進 seed 視窗
        decision = strategy_power_w(self.plan, self.site.pk, start + dt.timedelta(seconds=5))
        self.assertIn("window boundary", decision.reason)
        self.assertAlmostEqual(decision.power_w, 120_000.0, delta=1.0)

    def test_safety_margin_uses_forecast_p90(self) -> None:
        stats = ErrorStats(self.site.id, 14, 200, 0.05, 10.0, 30.0, 1.0)
        margin, reason = demand_window.safety_margin_kw(self.site.id, stats=stats)
        self.assertEqual(margin, 30.0)
        self.assertIn("P90", reason)
        margin, _ = demand_window.safety_margin_kw(
            self.site.id, stats=ErrorStats(self.site.id, 14, 10, None, None, 30.0, None)
        )
        self.assertEqual(margin, 0.0, "too few samples → no extra margin")
