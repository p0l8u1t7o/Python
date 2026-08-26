"""結算區間：物理上不可能的功率讀值不能進能量平衡。

一台額定 1,200 kW 的負載電錶回報 45 MW，是刻度錯、測試覆寫或接線問題，不是尖峰。
放進去的後果是需量「基準線」爆炸、需量費受益變成天文數字——示範資料就這樣出過事。
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.core.timeutils import now
from apps.ems.aggregator import PLAUSIBILITY_FACTOR, SiteAggregator
from apps.ems.models import AssetRole, EnergyAsset, EnergyInterval
from apps.telemetry.models import TelemetrySample
from tests import factories


class PlausibilityGuardTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, "hq")
        self.meter = factories.device(self.org, "GRID-1", site_obj=self.site)
        self.load = factories.device(self.org, "LOAD-1", site_obj=self.site)
        EnergyAsset.objects.create(
            organization=self.org, site=self.site, device=self.meter,
            role=AssetRole.GRID_METER, power_metric="grid_power_w", power_scale=0.001,
        )
        EnergyAsset.objects.create(
            organization=self.org, site=self.site, device=self.load,
            role=AssetRole.LOAD_METER, power_metric="load_power_w", power_scale=0.001,
            rated_power_kw=1200.0,
        )
        self.start = now().replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)

    def _feed(self, load_watts: list[float]) -> EnergyInterval:
        rows = []
        for index, watts in enumerate(load_watts):
            ts = self.start + dt.timedelta(minutes=index)
            rows.append(TelemetrySample(organization=self.org, device=self.meter, metric_key="grid_power_w", ts=ts, value=1_000_000.0))
            rows.append(TelemetrySample(organization=self.org, device=self.load, metric_key="load_power_w", ts=ts, value=watts))
        TelemetrySample.objects.bulk_create(rows)
        SiteAggregator(self.site).run(self.start, self.start + dt.timedelta(minutes=15))
        return EnergyInterval.objects.get(site=self.site, interval_start=self.start)

    def test_a_45_mw_reading_on_a_1200_kw_meter_is_ignored(self) -> None:
        interval = self._feed([1_000_000.0] * 8 + [45_002_248.2] * 7)
        # The bad points are gone; the honest ones carry the interval.
        self.assertLess(interval.peak_load_kw, 1200.0 * PLAUSIBILITY_FACTOR)
        self.assertAlmostEqual(interval.peak_load_kw, 1000.0, delta=1.0)

    def test_a_real_overload_within_the_factor_still_counts(self) -> None:
        interval = self._feed([1_000_000.0] * 10 + [1_800_000.0] * 5)
        self.assertAlmostEqual(interval.peak_load_kw, 1800.0, delta=1.0)

    def test_unrated_assets_are_not_filtered(self) -> None:
        EnergyAsset.objects.filter(device=self.load).update(rated_power_kw=None)
        interval = self._feed([1_000_000.0] * 10 + [45_002_248.2] * 5)
        self.assertGreater(interval.peak_load_kw, 40_000.0)
