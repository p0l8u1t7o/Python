"""模擬器手動覆寫：鎖定物理量、關閉雜訊、單一 metric 強制上傳。

目的是讓雲端的計算可以用手算對帳，所以釘住的是「我說 400 就上傳 400」。
"""

from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase

from simulator.config import GatewayConfig
from simulator.gateway import GatewayRunner
from simulator.physics import SitePhysics


class ForcedPhysicsTests(SimpleTestCase):
    def test_forced_values_replace_curves_and_balance_exactly(self) -> None:
        p = SitePhysics(battery_kw_rated=500.0, battery_kwh=1000.0, soc=50.0, deterministic=True)
        p.force(load_kw=400.0, pv_kw=100.0, battery_kw=50.0, soc=42.0)
        p.step()
        self.assertEqual((p.load_kw, p.pv_kw, p.battery_kw), (400.0, 100.0, 50.0))
        self.assertEqual(p.grid_kw, 250.0, "grid = load - pv - battery")
        self.assertEqual(p.soc, 42.0, "SOC pinned, not integrated")
        self.assertEqual(p.mode, "forced")
        meter = p.sample("grid_meter", "grid_power_w")
        self.assertEqual(meter["grid_power_w"], 250_000.0)
        self.assertEqual(meter["grid_voltage_v"], 221.5, "deterministic: mid-point, no jitter")
        battery = p.sample("battery", "battery_power_w")
        self.assertEqual(battery["battery_power_w"], 50_000.0)
        self.assertEqual(battery["battery_soc"], 42.0)

    def test_energy_counters_integrate_the_forced_power(self) -> None:
        with mock.patch("simulator.physics.time.monotonic", return_value=0.0):
            p = SitePhysics(battery_kw_rated=500.0, battery_kwh=1000.0, deterministic=True)
            p._last = 0.0  # default_factory 綁的是真實時鐘，patch 不到
            p.force(load_kw=600.0, pv_kw=0.0, battery_kw=0.0)
            p.step()
        with mock.patch("simulator.physics.time.monotonic", return_value=3600.0):
            p.step()
        self.assertAlmostEqual(p.import_kwh, 600.0, places=6, msg="600 kW for one hour = 600 kWh")
        self.assertAlmostEqual(p.load_kwh, 600.0, places=6)

    def test_release_restores_the_curves(self) -> None:
        p = SitePhysics(deterministic=True)
        p.force(load_kw=1.0)
        p.step()
        self.assertEqual(p.load_kw, 1.0)
        p.force(load_kw=None)
        p.step()
        self.assertNotEqual(p.load_kw, 1.0)
        with self.assertRaises(KeyError):
            p.force(grid_kw=1.0)


class GatewayOverrideTests(SimpleTestCase):
    def runner(self) -> GatewayRunner:
        spec = GatewayConfig(node_id="GW-T", devices=[])
        from simulator.config import DeviceConfig

        spec.devices = [DeviceConfig("METER-1", "grid_meter", "grid_power_w")]
        return GatewayRunner(mock.Mock(), "g", spec, interval=1.0, faults=False, autonomous=False)

    def test_override_wins_over_physics_and_clears(self) -> None:
        runner = self.runner()
        runner.physics.deterministic = True
        runner.set_override("METER-1", "grid_power_w", 123_456.0)
        runner.set_override("METER-1", "grid_frequency_hz", 59.5)
        values = runner._sample(runner.devices[0])
        self.assertEqual(values["grid_power_w"], 123_456.0)
        self.assertEqual(values["grid_frequency_hz"], 59.5)
        self.assertIn("grid_voltage_v", values, "other metrics still come from physics")
        runner.set_override("METER-1", "grid_power_w", None)
        runner.set_override("METER-1", "grid_frequency_hz", None)
        self.assertEqual(runner.overrides, {})
        self.assertNotEqual(runner._sample(runner.devices[0])["grid_power_w"], 123_456.0)

    def test_publish_now_is_a_noop_when_offline(self) -> None:
        runner = self.runner()
        self.assertFalse(runner.publish_now())
