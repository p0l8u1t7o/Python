"""W6 邊緣 fail-safe 與停電偵測。

釘住的失效模式：斷網時電池停在最後一個設定點把 SOC 放乾；停電沒有事件、
沒有告警、節省被算成正數；沒有 valid_until 的舊藍圖讓整個場域的調度被 422 擋下。
"""

from __future__ import annotations

import copy
import datetime as dt
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.alerts.models import Alert, AlertStatus
from apps.devices.models import Command, DeviceEvent, EventLevel
from apps.ems.aggregator import SiteAggregator
from apps.ems.dispatch import decide, run_site, setpoint_params, supports_expiry
from apps.ems.models import (
    AssetRole,
    DispatchMode,
    DispatchStrategy,
    EnergyAsset,
    EnergyInterval,
    ExpiryPolicy,
    SiteOutage,
    StoragePlan,
)
from apps.ems.outage import OUTAGE_CODE, OutageDetector
from apps.telemetry.models import LatestSample
from services.sparkplug.datatypes import DataType
from services.sparkplug.topics import MessageType
from simulator.physics import SitePhysics
from tests import factories
from tests.test_dispatch_engine import SETPOINT_SPEC, DispatchTestCase
from tests.test_ingest_pipeline import PipelineTestCase

UTC = dt.timezone.utc


# ---------------------------------------------------------------------------
# 邊緣：模擬器的設定點有效期、watchdog、孤島
# ---------------------------------------------------------------------------
class SimulatorFailsafeTests(TestCase):
    def physics(self, **kwargs) -> SitePhysics:
        p = SitePhysics(battery_kw_rated=500.0, battery_kwh=1000.0, soc=60.0, peak_load_kw=400.0, pv_peak_kw=0.0, **kwargs)
        p.watchdog_seconds = 0  # 這些測試各自決定要不要 watchdog
        return p

    def test_setpoint_expires_into_idle_after_valid_until(self) -> None:
        """60 秒有效期、雲端斷線：61 秒後電池歸零，而不是繼續放 500 kW。"""
        p = self.physics()
        with mock.patch("simulator.physics.time.monotonic", return_value=1000.0):
            until = (dt.datetime.now(UTC) + dt.timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
            note = p.command("set_power_setpoint", {"power_w": 500_000, "valid_until": until, "on_expiry": "idle"})
            self.assertIn("then idle", note)
        with mock.patch("simulator.physics.time.monotonic", return_value=1030.0):
            p.step()
            self.assertEqual(p.mode, "normal")
            self.assertAlmostEqual(p.battery_kw, 500.0, delta=1.0)
        with mock.patch("simulator.physics.time.monotonic", return_value=1061.0):
            p.step()
            self.assertEqual(p.mode, "expired")
            self.assertEqual(p.battery_kw, 0.0)

    def test_hold_keeps_the_setpoint_and_reserve_charges_to_the_reserve_level(self) -> None:
        p = self.physics(reserve_soc=30.0)
        p.soc = 20.0
        until = (dt.datetime.now(UTC) - dt.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        p.command("set_power_setpoint", {"power_w": 100_000, "valid_until": until, "on_expiry": "hold"})
        p.step()
        self.assertEqual(p.mode, "expired")
        self.assertAlmostEqual(p.battery_kw, 100.0, delta=1.0)

        p.command("set_power_setpoint", {"power_w": 100_000, "valid_until": until, "on_expiry": "reserve"})
        p.step()
        self.assertEqual(p.mode, "expired")
        self.assertLess(p.battery_kw, 0.0, "charging toward the reserve")
        p.soc = 35.0
        p.step()
        self.assertEqual(p.battery_kw, 0.0, "at reserve: stop")

    def test_setpoint_without_valid_until_never_expires(self) -> None:
        """舊版平台的命令：沒有期限，行為與以前相同。"""
        p = self.physics()
        p.command("set_power_setpoint", {"power_w": 200_000})
        with mock.patch("simulator.physics.time.monotonic", return_value=1e9):
            p.step()
        self.assertEqual(p.mode, "normal")
        self.assertAlmostEqual(p.battery_kw, 200.0, delta=1.0)

    def test_watchdog_degrades_after_thirty_minutes_without_the_cloud(self) -> None:
        """斷網 30 分鐘：watchdog 進 reserve 政策，SOC 沒有被放乾。"""
        p = self.physics(reserve_soc=20.0)
        p.watchdog_seconds = 180.0
        with mock.patch("simulator.physics.time.monotonic", return_value=0.0):
            p.command("set_power_setpoint", {"power_w": 500_000})  # 沒有期限的放電命令
            p.step()
        soc_before = p.soc
        # 1 秒一步跑 30 分鐘，連線在第 10 秒斷掉。
        for second in range(1, 1801):
            with mock.patch("simulator.physics.time.monotonic", return_value=float(second)):
                if second == 10:
                    p.link_down_since = 10.0
                p.step()
        self.assertEqual(p.mode, "watchdog")
        self.assertGreaterEqual(p.soc, p.reserve_soc - 1.0)
        # 若沒有 watchdog，500 kW × 0.5 h = 250 kWh = 25% 的 SOC 會被放掉。
        self.assertGreater(p.soc, soc_before - 25.0 + 5.0)

    def test_outage_islands_the_battery_and_zeroes_the_meter(self) -> None:
        p = self.physics()
        p.command("set_power_setpoint", {"power_w": -100_000})  # 雲端叫它充電
        p.grid_outage = True
        p.step()
        self.assertEqual(p.mode, "island")
        self.assertEqual(p.grid_kw, 0.0)
        self.assertGreater(p.battery_kw, 0.0, "serving the load, not charging")
        sample = p.sample("grid_meter", "grid_power_w")
        self.assertEqual(sample["grid_voltage_v"], 0.0)
        self.assertEqual(sample["grid_power_w"], 0.0)


# ---------------------------------------------------------------------------
# 雲端：設定點參數、刷新、舊藍圖降級
# ---------------------------------------------------------------------------
class SetpointExpiryTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, "plant")
        self.plan = StoragePlan.objects.create(
            organization=self.org, name="p", strategy=DispatchStrategy.MANUAL,
            setpoint_ttl_seconds=300, on_expiry=ExpiryPolicy.RESERVE, heartbeat_interval_seconds=60,
        )

    def test_params_carry_valid_until_and_policy(self) -> None:
        moment = dt.datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
        params = setpoint_params(self.plan, -200_000.0, moment)
        self.assertEqual(params, {"power_w": -200_000.0, "valid_until": "2026-08-23T10:05:00Z", "on_expiry": "reserve"})
        self.assertEqual(setpoint_params(None, 1.0, moment), {"power_w": 1.0}, "manual path: no expiry")

    def test_blueprint_without_valid_until_degrades_to_plain_power(self) -> None:
        blueprint = factories.blueprint("old-bess", org=self.org, command_definitions=[SETPOINT_SPEC])
        device = factories.device(self.org, "BESS-OLD", site_obj=self.site, device_type=blueprint)
        self.assertFalse(supports_expiry(device))
        params = setpoint_params(self.plan, 1000.0, timezone.now(), device=device)
        self.assertEqual(list(params), ["power_w"])


class RefreshAsHeartbeatTests(DispatchTestCase):
    """引擎在設定點沒變時也要在 heartbeat_interval 後重送——那就是心跳。"""

    def setUp(self) -> None:
        super().setUp()
        spec = copy.deepcopy(SETPOINT_SPEC)
        spec["params"]["properties"]["valid_until"] = {"type": "string"}
        spec["params"]["properties"]["on_expiry"] = {"type": "string", "enum": ["idle", "hold", "reserve"]}
        self.blueprint.command_definitions = [spec]
        self.blueprint.save(update_fields=["command_definitions"])
        self.plan.setpoint_ttl_seconds = 300
        self.plan.heartbeat_interval_seconds = 60
        self.plan.on_expiry = ExpiryPolicy.IDLE
        self.plan.save()

    def test_unchanged_setpoint_is_resent_after_the_heartbeat_interval(self) -> None:
        self._window(DispatchMode.DISCHARGE, target_power_kw=100.0)
        self._soc(80.0)
        moment = timezone.now()
        with mock.patch("apps.devices.services.publish_bytes"):
            first = run_site(self.ctx, self.site.pk, moment=moment)
            self.assertFalse(first.skipped)
            self.assertEqual(Command.objects.count(), 1)
            self.assertEqual(Command.objects.get().params["on_expiry"], "idle")
            self.assertIn("valid_until", Command.objects.get().params)

            again = run_site(self.ctx, self.site.pk, moment=moment + dt.timedelta(seconds=30))
            self.assertEqual(again.skipped, "unchanged")
            self.assertEqual(Command.objects.count(), 1)

            refreshed = run_site(self.ctx, self.site.pk, moment=moment + dt.timedelta(seconds=61))
        self.assertFalse(refreshed.skipped)
        self.assertIn("refresh", refreshed.reason)
        self.assertEqual(Command.objects.count(), 2, "the refresh is a new command with a fresh valid_until")

    def test_old_blueprint_still_gets_plain_setpoints(self) -> None:
        self.blueprint.command_definitions = [SETPOINT_SPEC]
        self.blueprint.save(update_fields=["command_definitions"])
        self._window(DispatchMode.DISCHARGE, target_power_kw=100.0)
        self._soc(80.0)
        with mock.patch("apps.devices.services.publish_bytes"):
            decision = run_site(self.ctx, self.site.pk)
        self.assertFalse(decision.skipped)
        self.assertIn("blueprint lacks it", decision.reason)
        self.assertEqual(list(Command.objects.get().params), ["power_w"])


# ---------------------------------------------------------------------------
# 雲端：停電偵測走真實的 worker 管線
# ---------------------------------------------------------------------------
class OutageDetectionTests(TestCase):
    """沿用 PipelineTestCase 的佈置與 helper，但不繼承——繼承會把它的測試再跑一遍。"""

    publish = PipelineTestCase.publish
    drain = PipelineTestCase.drain
    next_seq = PipelineTestCase.next_seq

    def setUp(self) -> None:
        PipelineTestCase.setUp(self)
        self.battery = factories.device(self.org, "BESS-0001", site_obj=self.site, node=self.node)
        EnergyAsset.objects.create(
            organization=self.org, site=self.site, device=self.device, role=AssetRole.GRID_METER,
            power_metric="grid_power_w", voltage_metric="grid_voltage_v",
        )
        EnergyAsset.objects.create(
            organization=self.org, site=self.site, device=self.battery, role=AssetRole.BATTERY,
            power_metric="battery_power_w", soc_metric="battery_soc",
        )
        self.plan = StoragePlan.objects.create(
            organization=self.org, name="cap", strategy=DispatchStrategy.DEMAND_CAP,
            demand_cap_target_kw=500.0, outage_voltage_min_v=180.0, outage_for_seconds=5,
        )
        self.site.storage_plan = self.plan
        self.site.save(update_fields=["storage_plan"])
        self.shared.invalidate()
        self.publish(MessageType.NBIRTH, [("bdSeq", 0, DataType.Int64)])
        self.publish(MessageType.DBIRTH, [("grid_voltage_v", 220.0, DataType.Double), ("grid_power_w", 100.0, DataType.Double)])
        self.drain()

    def tearDown(self) -> None:
        PipelineTestCase.tearDown(self)

    def voltage(self, value: float, at: dt.datetime) -> dict:
        self.publish(MessageType.DDATA, [("grid_voltage_v", value, DataType.Double)], timestamp=at)
        return self.drain()

    def test_voltage_dip_must_persist_before_it_counts(self) -> None:
        t0 = timezone.now()
        self.voltage(0.0, t0)
        self.voltage(0.0, t0 + dt.timedelta(seconds=3))
        self.assertFalse(SiteOutage.objects.exists(), "3 s below threshold is a dip, not an outage")
        self.voltage(220.0, t0 + dt.timedelta(seconds=4))  # 回來了：重新計時
        self.voltage(0.0, t0 + dt.timedelta(seconds=10))
        self.voltage(0.0, t0 + dt.timedelta(seconds=14))
        self.assertFalse(SiteOutage.objects.exists())

    def test_outage_raises_event_alert_and_nulls_savings_then_clears(self) -> None:
        # 時間戳全部在過去：入口會拒收「來自未來」的樣本。
        t0 = (timezone.now() - dt.timedelta(minutes=30)).replace(microsecond=0)
        self.voltage(0.0, t0)
        stats = self.voltage(0.0, t0 + dt.timedelta(seconds=6))
        self.assertEqual(stats.get("outages_started"), 1)

        outage = SiteOutage.objects.get()
        self.assertIsNone(outage.ended_at)
        self.assertEqual(outage.started_at, t0)
        event = DeviceEvent.objects.get(code=OUTAGE_CODE, level=EventLevel.CRITICAL)
        self.assertEqual(event.payload["alarm_state"], "active")
        alert = Alert.objects.get(code=OUTAGE_CODE)
        self.assertEqual(alert.status, AlertStatus.FIRING)

        # 調度：停電中走備援模式，不下設定點。
        decision = decide(self.site.pk, t0 + dt.timedelta(seconds=10))
        self.assertEqual(decision.skipped, "grid_outage")

        # 彙總：與停電重疊的區間節省記 null，不重疊的照算。
        LatestSample.objects.all().delete()
        start = t0.replace(minute=(t0.minute // 15) * 15, second=0)
        aggregator = SiteAggregator(self.site)
        aggregator.run(start - dt.timedelta(minutes=15), start + dt.timedelta(minutes=15))
        during = EnergyInterval.objects.filter(site=self.site, interval_start=start).first()
        before = EnergyInterval.objects.filter(site=self.site, interval_start=start - dt.timedelta(minutes=15)).first()
        if during is not None:
            self.assertIsNone(during.estimated_savings)
        if before is not None and before.estimated_savings is not None:
            self.assertIsNotNone(before.estimated_savings)

        # 復電：關閉停電、清告警、info 事件。
        stats = self.voltage(221.0, t0 + dt.timedelta(minutes=20))
        self.assertEqual(stats.get("outages_ended"), 1)
        outage.refresh_from_db()
        self.assertIsNotNone(outage.ended_at)
        alert.refresh_from_db()
        self.assertEqual(alert.status, AlertStatus.RESOLVED)
        self.assertTrue(DeviceEvent.objects.filter(code=OUTAGE_CODE, level=EventLevel.INFO).exists())
        self.assertNotEqual(decide(self.site.pk, t0 + dt.timedelta(minutes=21)).skipped, "grid_outage")

    def test_no_rule_when_plan_has_no_threshold(self) -> None:
        self.plan.outage_voltage_min_v = None
        self.plan.save()
        self.shared.invalidate()  # 規則快取 30 秒；改方案後要失效
        detector = OutageDetector()
        self.assertIsNone(detector.rule_for(self.device.pk))
        t0 = timezone.now()
        self.voltage(0.0, t0)
        self.voltage(0.0, t0 + dt.timedelta(seconds=30))
        self.assertFalse(SiteOutage.objects.exists())
