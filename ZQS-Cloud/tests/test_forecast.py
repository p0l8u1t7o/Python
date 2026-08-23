"""負載／PV 預測：同時段中位數 + 漂移，歷史不足時誠實回 unknown。"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from apps.ems import forecast
from apps.ems.models import EnergyInterval, LoadForecast
from tests import factories

UTC = dt.timezone.utc


def weekday_profile(local_hour: int, weekday: int) -> float:
    """工作日 400 kW 的上班時段、夜間 120；週末整天 150。"""
    if weekday >= 5:
        return 150.0
    return 400.0 if 8 <= local_hour < 18 else 120.0


class ForecastTestCase(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, "plant", timezone_name="Asia/Taipei")
        self.now = forecast.align_to_interval(timezone.now())

    def seed(self, weeks: int, *, noise: float = 0.0, coverage: float = 1.0) -> None:
        rows = []
        start = self.now - dt.timedelta(days=7 * weeks)
        cursor = start
        zone = dt.timezone(dt.timedelta(hours=8))
        while cursor < self.now:
            local = cursor.astimezone(zone)
            kw = weekday_profile(local.hour, local.weekday())
            kw *= 1 + noise * ((cursor.minute % 30) / 30 - 0.5)
            rows.append(EnergyInterval(
                organization=self.org, site=self.site, interval_start=cursor, interval_seconds=900,
                load_kwh=kw * 0.25, pv_kwh=0.0, coverage=coverage,
            ))
            cursor += forecast.INTERVAL
        EnergyInterval.objects.bulk_create(rows, batch_size=2000)

    def test_too_little_history_is_unknown_not_an_error(self) -> None:
        self.seed(weeks=1)
        points = forecast.forecast_site(self.site.pk, self.now, 2, record=False)
        self.assertEqual(len(points), 8)
        self.assertTrue(all(p.confidence == "unknown" and p.load_kw is None for p in points))

    def test_no_history_at_all_still_returns_points(self) -> None:
        points = forecast.forecast_site(self.site.pk, self.now, 1, record=False)
        self.assertEqual(len(points), 4)
        self.assertEqual({p.confidence for p in points}, {"unknown"})

    def test_a_weekday_slot_predicts_the_weekday_level(self) -> None:
        self.seed(weeks=5)
        # 找下一個工作日的 10:00（台北）。
        zone = dt.timezone(dt.timedelta(hours=8))
        target = self.now
        while not (target.astimezone(zone).weekday() < 5 and target.astimezone(zone).hour == 10
                   and target.astimezone(zone).minute == 0):
            target += forecast.INTERVAL
        horizon = int((target - self.now) / forecast.INTERVAL) + 1
        points = forecast.forecast_site(self.site.pk, self.now, max(1, horizon // 4 + 1), record=False)
        point = next(p for p in points if p.starts_at == target)
        self.assertEqual(point.confidence, "estimated")
        self.assertAlmostEqual(point.load_kw, 400.0, delta=1.0)

    def test_weekend_is_not_polluted_by_weekdays(self) -> None:
        self.seed(weeks=5)
        zone = dt.timezone(dt.timedelta(hours=8))
        target = self.now
        while not (target.astimezone(zone).weekday() == 6 and target.astimezone(zone).hour == 10
                   and target.astimezone(zone).minute == 0):
            target += forecast.INTERVAL
        points = forecast.forecast_site(self.site.pk, self.now, 24 * 8, record=False)
        point = next(p for p in points if p.starts_at == target)
        self.assertAlmostEqual(point.load_kw, 150.0, delta=1.0)

    def test_drift_follows_a_recent_level_shift_but_is_clamped(self) -> None:
        self.seed(weeks=5)
        # 最近三天負載整體 ×3：漂移應該往上，但夾在 1.5。
        since = self.now - dt.timedelta(days=3)
        for row in EnergyInterval.objects.filter(site=self.site, interval_start__gte=since):
            row.load_kwh *= 3
            row.save(update_fields=["load_kwh"])
        points = forecast.forecast_site(self.site.pk, self.now, 24, record=False)
        estimated = [p for p in points if p.confidence == "estimated"]
        self.assertTrue(estimated)
        # 工作日白天基準 400 → 夾限後最多 600。
        self.assertLessEqual(max(p.load_kw for p in estimated), 600.0 + 1.0)
        self.assertGreater(max(p.load_kw for p in estimated), 400.0 + 1.0)

    def test_forecasts_are_recorded_with_their_issue_time(self) -> None:
        self.seed(weeks=5)
        forecast.forecast_site(self.site.pk, self.now, 1)
        forecast.forecast_site(self.site.pk, self.now + dt.timedelta(minutes=1), 1)
        self.assertEqual(LoadForecast.objects.filter(site=self.site).count(), 8)
        self.assertEqual(LoadForecast.objects.filter(site=self.site).values("made_at").distinct().count(), 2)

    def test_error_stats_reflect_a_known_miss(self) -> None:
        self.seed(weeks=5)
        # 假裝一小時前做了預測，預測值比實測低 50 kW。
        made_at = self.now - dt.timedelta(hours=1)
        slots = [self.now - dt.timedelta(minutes=15 * k) for k in range(1, 5)]
        for slot in slots:
            actual = EnergyInterval.objects.get(site=self.site, interval_start=slot)
            LoadForecast.objects.create(
                site=self.site, starts_at=slot, made_at=made_at, horizon_minutes=30,
                load_kw=actual.load_kwh / 0.25 - 50.0, confidence="estimated", samples=4,
            )
        stats = forecast.forecast_error_stats(self.site.pk, days=1)
        self.assertEqual(stats.samples, 4)
        self.assertAlmostEqual(stats.bias_kw, 50.0, delta=0.01)
        self.assertAlmostEqual(stats.p90_abs_kw, 50.0, delta=0.01)

    def test_backtest_mape_is_small_on_regular_load(self) -> None:
        self.seed(weeks=6, noise=0.1)
        stats = forecast.backtest(self.site.pk, self.now - dt.timedelta(days=3), self.now)
        self.assertGreater(stats.samples, 200)
        self.assertLess(stats.mape, 0.15)

    def test_low_coverage_history_is_ignored(self) -> None:
        self.seed(weeks=5, coverage=0.2)
        points = forecast.forecast_site(self.site.pk, self.now, 1, record=False)
        self.assertEqual({p.confidence for p in points}, {"unknown"})
