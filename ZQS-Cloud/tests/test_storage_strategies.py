"""The built-in storage strategies as arithmetic, and their order of authority.

Everything here feeds the engine synthetic readings through LatestSample and
checks the sign and size of the setpoint it derives - no MQTT, no hardware.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from apps.ems.dispatch import decide
from apps.ems.models import (
    AssetRole,
    DemandResponseEvent,
    DispatchStrategy,
    EnergyAsset,
    EnergyInterval,
    StoragePlan,
    Tariff,
)
from apps.ems.strategy import strategy_power_w
from apps.telemetry.models import LatestSample
from tests import factories

TPE = dt.timezone(dt.timedelta(hours=8))


class StrategyTestCase(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, "plant")
        self.battery = factories.device(self.org, "BESS-1", site_obj=self.site)
        self.meter = factories.device(self.org, "METER-1", site_obj=self.site)
        self.pv = factories.device(self.org, "PV-1", site_obj=self.site)

        EnergyAsset.objects.create(
            organization=self.org, site=self.site, device=self.battery,
            role=AssetRole.BATTERY, power_metric="battery_power_kw",
            soc_metric="battery_soc",
        )
        EnergyAsset.objects.create(
            organization=self.org, site=self.site, device=self.meter,
            role=AssetRole.GRID_METER, power_metric="grid_power_kw",
        )
        EnergyAsset.objects.create(
            organization=self.org, site=self.site, device=self.pv,
            role=AssetRole.PV, power_metric="pv_power_kw",
        )

    def reading(self, device, metric: str, value: float) -> None:
        LatestSample.objects.update_or_create(
            organization=self.org, device=device, metric_key=metric,
            defaults={"value": value, "ts": timezone.now(), "quality": 0},
        )

    def plan(self, strategy: str, **kwargs) -> StoragePlan:
        defaults = {
            "organization": self.org,
            "strategy": strategy,
            "max_charge_kw": 100.0,
            "max_discharge_kw": 100.0,
            "usable_capacity_kwh": 200.0,
        }
        defaults.update(kwargs)
        plan, _ = StoragePlan.objects.update_or_create(
            organization=self.org, name="strategy-under-test", defaults=defaults
        )
        self.site.storage_plan = plan
        self.site.save(update_fields=["storage_plan"])
        return plan

    def tou_tariff(self) -> Tariff:
        """Peak 16-22 at 7.0, everything else 2.0 - a 5.0 spread."""
        return Tariff.objects.create(
            organization=self.org, name="tou", timezone_name="Asia/Taipei",
            default_import_price=2.0,
            periods=[{"name": "peak", "start": "16:00", "end": "22:00",
                      "import_price": 7.0}],
        )


class DemandCapTests(StrategyTestCase):
    def test_over_the_ceiling_discharges_the_excess(self) -> None:
        plan = self.plan(DispatchStrategy.DEMAND_CAP, demand_cap_target_kw=500.0)
        self.reading(self.meter, "grid_power_kw", 560.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertAlmostEqual(decision.power_w, 60_000.0, delta=1.0)

    def test_a_charging_battery_does_not_look_like_an_excursion(self) -> None:
        """Meter 120 kW over a 100 kW ceiling *because* the battery is taking
        40 kW: the site itself draws 80, so the right answer is to stop the
        charge, not to order a 20 kW discharge and start oscillating."""
        plan = self.plan(DispatchStrategy.DEMAND_CAP, demand_cap_target_kw=100.0)
        self.reading(self.meter, "grid_power_kw", 120.0)
        self.reading(self.battery, "battery_power_kw", -40.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertAlmostEqual(decision.power_w, 0.0, delta=1.0)

    def test_under_the_ceiling_idles_without_a_tariff(self) -> None:
        plan = self.plan(DispatchStrategy.DEMAND_CAP, demand_cap_target_kw=500.0)
        self.reading(self.meter, "grid_power_kw", 300.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertEqual(decision.power_w, 0.0)

    def test_the_ceiling_falls_back_to_95_percent_of_contract(self) -> None:
        plan = self.plan(DispatchStrategy.DEMAND_CAP, contract_capacity_kw=1000.0)
        self.reading(self.meter, "grid_power_kw", 990.0)  # over 950
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertAlmostEqual(decision.power_w, 40_000.0, delta=1.0)

    def test_offpeak_recharge_never_exceeds_the_headroom(self) -> None:
        """The recharge that causes the demand excursion it exists to prevent
        is the failure mode this pins."""
        tariff = self.tou_tariff()
        plan = self.plan(
            DispatchStrategy.DEMAND_CAP, demand_cap_target_kw=500.0,
            tariff=tariff, offpeak_recharge=True, max_charge_kw=999.0,
        )
        self.reading(self.meter, "grid_power_kw", 480.0)
        off_peak = dt.datetime(2026, 7, 15, 3, 0, tzinfo=TPE)
        decision = strategy_power_w(plan, self.site.pk, off_peak)
        # Charging, but no harder than the 20 kW of headroom.
        self.assertLess(decision.power_w, 0)
        self.assertAlmostEqual(decision.power_w, -20_000.0, delta=1.0)

    def test_no_fresh_reading_means_no_opinion(self) -> None:
        plan = self.plan(DispatchStrategy.DEMAND_CAP, demand_cap_target_kw=500.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertIsNone(decision.power_w)


class TouArbitrageTests(StrategyTestCase):
    def test_discharges_at_the_peak_and_charges_at_the_trough(self) -> None:
        plan = self.plan(DispatchStrategy.TOU_ARBITRAGE, tariff=self.tou_tariff())
        self.reading(self.meter, "grid_power_kw", 100.0)

        peak = dt.datetime(2026, 7, 15, 18, 0, tzinfo=TPE)
        trough = dt.datetime(2026, 7, 15, 3, 0, tzinfo=TPE)
        self.assertAlmostEqual(
            strategy_power_w(plan, self.site.pk, peak).power_w, 100_000.0, delta=1.0
        )
        self.assertAlmostEqual(
            strategy_power_w(plan, self.site.pk, trough).power_w, -100_000.0, delta=1.0
        )

    def test_a_flat_day_does_nothing(self) -> None:
        flat = Tariff.objects.create(
            organization=self.org, name="flat-ish", timezone_name="Asia/Taipei",
            default_import_price=3.0,
            periods=[{"name": "peak", "start": "16:00", "end": "22:00",
                      "import_price": 3.5}],
        )
        plan = self.plan(DispatchStrategy.TOU_ARBITRAGE, tariff=flat,
                         min_price_spread=1.0)
        peak = dt.datetime(2026, 7, 15, 18, 0, tzinfo=TPE)
        self.assertEqual(strategy_power_w(plan, self.site.pk, peak).power_w, 0.0)

    def test_no_export_caps_discharge_at_the_site_load(self) -> None:
        plan = self.plan(DispatchStrategy.TOU_ARBITRAGE, tariff=self.tou_tariff(),
                         export_limit_kw=0.0)
        # Node balance: load = grid + pv + battery = 30 + 0 + 0.
        self.reading(self.meter, "grid_power_kw", 30.0)
        self.reading(self.pv, "pv_power_kw", 0.0)
        self.reading(self.battery, "battery_power_kw", 0.0)
        peak = dt.datetime(2026, 7, 15, 18, 0, tzinfo=TPE)
        self.assertAlmostEqual(
            strategy_power_w(plan, self.site.pk, peak).power_w, 30_000.0, delta=1.0
        )

    def test_trough_charging_respects_the_contract_capacity(self) -> None:
        plan = self.plan(DispatchStrategy.TOU_ARBITRAGE, tariff=self.tou_tariff(),
                         contract_capacity_kw=150.0, max_charge_kw=999.0)
        self.reading(self.meter, "grid_power_kw", 100.0)
        trough = dt.datetime(2026, 7, 15, 3, 0, tzinfo=TPE)
        # Headroom is measured to 95% of the contract, not the contract
        # itself: a charge that lands exactly on the contract would become
        # the month's billed peak. 150 x 0.95 - 100 = 42.5 kW.
        self.assertAlmostEqual(
            strategy_power_w(plan, self.site.pk, trough).power_w, -42_500.0, delta=1.0
        )

    def test_trough_charging_ignores_its_own_charge(self) -> None:
        """The meter already carries the battery's flow; the headroom must be
        measured against the site's own demand, or the charge shrinks itself
        cycle by cycle."""
        plan = self.plan(DispatchStrategy.TOU_ARBITRAGE, tariff=self.tou_tariff(),
                         contract_capacity_kw=150.0, max_charge_kw=999.0)
        # Meter 130 kW while charging 30 kW: the site itself draws 100.
        self.reading(self.meter, "grid_power_kw", 130.0)
        self.reading(self.battery, "battery_power_kw", -30.0)
        trough = dt.datetime(2026, 7, 15, 3, 0, tzinfo=TPE)
        self.assertAlmostEqual(
            strategy_power_w(plan, self.site.pk, trough).power_w, -42_500.0, delta=1.0
        )


class SelfConsumptionTests(StrategyTestCase):
    def test_pv_surplus_charges_and_deficit_discharges(self) -> None:
        plan = self.plan(DispatchStrategy.SELF_CONSUMPTION)
        # load = grid + pv + battery = -40 + 90 + 0 = 50; surplus = 90-50 = 40.
        self.reading(self.meter, "grid_power_kw", -40.0)
        self.reading(self.pv, "pv_power_kw", 90.0)
        self.reading(self.battery, "battery_power_kw", 0.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertAlmostEqual(decision.power_w, -40_000.0, delta=1.0)

        # Evening: no PV, importing 60 -> discharge to cover the load.
        self.reading(self.meter, "grid_power_kw", 60.0)
        self.reading(self.pv, "pv_power_kw", 0.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertAlmostEqual(decision.power_w, 60_000.0, delta=1.0)


class BackupOnlyTests(StrategyTestCase):
    def test_low_reserve_charges_and_held_reserve_idles(self) -> None:
        plan = self.plan(DispatchStrategy.BACKUP_ONLY, backup_reserve_percent=40.0)
        self.reading(self.battery, "battery_soc", 25.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertLess(decision.power_w, 0)

        self.reading(self.battery, "battery_soc", 60.0)
        decision = strategy_power_w(plan, self.site.pk, timezone.now())
        self.assertEqual(decision.power_w, 0.0)


class HealthConstraintTests(StrategyTestCase):
    def test_over_temperature_stops_everything(self) -> None:
        self.plan(
            DispatchStrategy.DEMAND_CAP, demand_cap_target_kw=500.0,
            temperature_max_c=45.0, temperature_metric="cell_temp_c",
        )
        self.reading(self.meter, "grid_power_kw", 600.0)
        self.reading(self.battery, "battery_soc", 50.0)
        self.reading(self.battery, "cell_temp_c", 52.0)
        decision = decide(self.site.pk)
        self.assertEqual(decision.power_w, 0.0)
        self.assertIn("temperature", decision.reason)

    def test_spent_cycle_budget_blocks_discharge_but_not_charge(self) -> None:
        plan = self.plan(
            DispatchStrategy.DEMAND_CAP, demand_cap_target_kw=500.0,
            max_cycles_per_day=1.0, usable_capacity_kwh=100.0,
        )
        # 120 kWh discharged today = 1.2 cycles of a 100 kWh pack.
        EnergyInterval.objects.create(
            organization=self.org, site=self.site,
            interval_start=timezone.now().replace(hour=0, minute=0),
            battery_discharge_kwh=120.0,
        )
        self.reading(self.meter, "grid_power_kw", 600.0)
        self.reading(self.battery, "battery_soc", 50.0)
        decision = decide(self.site.pk)
        self.assertEqual(decision.power_w, 0.0)
        self.assertIn("cycle", decision.reason)

        # Charging is still allowed: it does not spend discharge budget.
        from apps.ems.strategy import apply_health_constraints

        power, reason = apply_health_constraints(plan, self.site.pk, -50_000.0, timezone.now())
        self.assertEqual(power, -50_000.0)
        self.assertEqual(reason, "")


class AuthorityOrderTests(StrategyTestCase):
    def test_a_live_dr_event_outranks_the_strategy(self) -> None:
        self.plan(DispatchStrategy.SELF_CONSUMPTION)
        self.reading(self.meter, "grid_power_kw", -40.0)
        self.reading(self.pv, "pv_power_kw", 90.0)
        self.reading(self.battery, "battery_power_kw", 0.0)
        self.reading(self.battery, "battery_soc", 80.0)

        moment = timezone.now()
        DemandResponseEvent.objects.create(
            organization=self.org, site=self.site,
            starts_at=moment - dt.timedelta(minutes=5),
            ends_at=moment + dt.timedelta(minutes=55),
            target_power_kw=80.0,
        )
        decision = decide(self.site.pk, moment)
        # Discharging 80 kW for the grid, not charging 40 for self-consumption.
        self.assertAlmostEqual(decision.power_w, 80_000.0, delta=1.0)
        self.assertIn("demand response", decision.reason)

    def test_a_cancelled_event_is_ignored(self) -> None:
        self.plan(DispatchStrategy.SELF_CONSUMPTION)
        self.reading(self.meter, "grid_power_kw", -40.0)
        self.reading(self.pv, "pv_power_kw", 90.0)
        self.reading(self.battery, "battery_power_kw", 0.0)

        moment = timezone.now()
        DemandResponseEvent.objects.create(
            organization=self.org, site=self.site,
            starts_at=moment - dt.timedelta(minutes=5),
            ends_at=moment + dt.timedelta(minutes=55),
            target_power_kw=80.0,
            cancelled_at=moment,
        )
        decision = decide(self.site.pk, moment)
        self.assertLess(decision.power_w, 0)  # back to soaking up PV

    def test_a_scheduled_window_still_beats_the_strategy(self) -> None:
        from apps.ems.models import DispatchMode, DispatchWindow

        self.plan(DispatchStrategy.SELF_CONSUMPTION)
        self.reading(self.meter, "grid_power_kw", -40.0)
        self.reading(self.pv, "pv_power_kw", 90.0)
        self.reading(self.battery, "battery_power_kw", 0.0)
        self.reading(self.battery, "battery_soc", 50.0)

        moment = timezone.now()
        DispatchWindow.objects.create(
            organization=self.org, site=self.site,
            starts_at=moment - dt.timedelta(hours=1),
            ends_at=moment + dt.timedelta(hours=1),
            mode=DispatchMode.DISCHARGE, target_power_kw=25.0,
        )
        decision = decide(self.site.pk, moment)
        self.assertAlmostEqual(decision.power_w, 25_000.0, delta=1.0)


from tests.test_api import ApiTestCase  # noqa: E402


class DemandResponseEndpointTests(ApiTestCase):
    def _site(self):
        return factories.site(self.org, "dr-site")

    def test_trigger_overlap_and_cancel(self) -> None:
        site = self._site()
        token = self.login("op@acme-demo.com")

        created = self.post(
            f"/api/ems/sites/{site.id}/demand-response",
            token,
            {"target_power_kw": 80, "duration_minutes": 30, "note": "test dispatch"},
        )
        self.assertEqual(created.status_code, 201, created.content)
        body = created.json()
        self.assertTrue(body["is_active"])

        # A second event over the same window is refused, not stacked.
        overlap = self.post(
            f"/api/ems/sites/{site.id}/demand-response",
            token,
            {"target_power_kw": 50, "duration_minutes": 10},
        )
        self.assertEqual(overlap.status_code, 409)

        cancelled = self.post(
            f"/api/ems/demand-response/{body['id']}/cancel", token
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertIsNotNone(cancelled.json()["cancelled_at"])
        self.assertFalse(cancelled.json()["is_active"])

        listing = self.get(f"/api/ems/sites/{site.id}/demand-response", token)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)

    def test_viewer_cannot_trigger(self) -> None:
        site = self._site()
        token = self.login("view@acme-demo.com")
        response = self.post(
            f"/api/ems/sites/{site.id}/demand-response",
            token,
            {"target_power_kw": 80, "duration_minutes": 30},
        )
        self.assertEqual(response.status_code, 403)
