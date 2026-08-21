"""Device capabilities, command gating, and the sub-meter balance rule.

Two classes of bug are pinned here:

* **Silent double counting.** A sub-meter folded into the energy balance
  produces figures that look entirely reasonable and are simply wrong.
* **Commands the hardware cannot honour.** Naming a command is not enough to
  know what it does - ``set_power_setpoint`` with a negative watt value is a
  charge instruction, and the blueprint schema allows the whole ±5 MW range.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.core.errors import Conflict, ValidationError
from apps.core.timeutils import UTC
from apps.devices.models import (
    CATEGORY_CAPABILITIES,
    LifecycleState,
    DeviceCategory,
    is_metering_only,
)
from apps.devices.services import check_capabilities
from apps.ems.aggregator import SiteAggregator
from apps.ems.models import AssetRole, EnergyAsset, EnergyInterval
from apps.telemetry.models import TelemetrySample
from tests import factories


class CategoryTests(TestCase):
    def test_metering_only_is_decided_by_category_not_by_flags(self):
        # A passive light circuit has every capability off and is still a load.
        self.assertEqual(
            CATEGORY_CAPABILITIES[DeviceCategory.LOAD], (False, False, False, False)
        )
        self.assertFalse(is_metering_only(DeviceCategory.LOAD))
        self.assertTrue(is_metering_only(DeviceCategory.METER))
        self.assertTrue(is_metering_only(DeviceCategory.SENSOR))

    def test_a_controllable_load_needs_no_extra_flag(self):
        # "Can it be commanded" is exactly is_dispatchable; a chiller that can
        # be switched off remotely differs from a lamp only in that flag.
        org = factories.organization()
        blueprint = factories.blueprint(
            "chiller", org, category=DeviceCategory.LOAD, is_dispatchable=True
        )
        device = factories.device(org, "CHILLER-1", device_type=blueprint)
        self.assertTrue(device.effective_capabilities()["is_dispatchable"])
        self.assertFalse(device.is_metering_only)

    def test_generator_can_discharge_but_never_charge_or_export(self):
        charge, discharge, export, dispatch = CATEGORY_CAPABILITIES[
            DeviceCategory.GENERATOR
        ]
        self.assertFalse(charge)
        self.assertTrue(discharge)
        self.assertFalse(export)
        self.assertTrue(dispatch)


class EffectiveCapabilityTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.blueprint = factories.blueprint(
            "pcs",
            self.org,
            category=DeviceCategory.BATTERY,
            can_charge=True,
            can_discharge=True,
            can_export=True,
            is_dispatchable=True,
        )

    def test_null_inherits_the_blueprint(self):
        device = factories.device(self.org, "INHERIT-1", device_type=self.blueprint)
        self.assertEqual(
            device.effective_capabilities(),
            {
                "can_charge": True,
                "can_discharge": True,
                "can_export": True,
                "is_dispatchable": True,
            },
        )

    def test_an_override_wins_over_the_blueprint(self):
        # Same model, commissioned without a charging circuit.
        device = factories.device(
            self.org, "NOCHARGE-1", device_type=self.blueprint, can_charge=False
        )
        capabilities = device.effective_capabilities()
        self.assertFalse(capabilities["can_charge"])
        self.assertTrue(capabilities["can_discharge"])

    def test_a_false_override_is_not_mistaken_for_unset(self):
        device = factories.device(
            self.org, "NOEXPORT-1", device_type=self.blueprint, can_export=False
        )
        self.assertFalse(device.effective_capabilities()["can_export"])

    def test_no_blueprint_stays_permissive(self):
        device = factories.device(self.org, "ORPHAN-1")
        self.assertTrue(all(device.effective_capabilities().values()))


class CommandGatingTests(TestCase):
    """What `check_capabilities` lets through, and what it refuses."""

    def setUp(self) -> None:
        self.org = factories.organization()
        self.bidirectional = factories.blueprint(
            "bidi",
            self.org,
            category=DeviceCategory.BATTERY,
            can_charge=True,
            can_discharge=True,
            can_export=True,
            is_dispatchable=True,
            command_definitions=[
                {"name": "set_power_setpoint", "params": {}},
                {"name": "set_mode", "params": {}},
                {"name": "set_export_limit", "params": {}},
                {"name": "set_report_interval", "params": {}, "kind": "config"},
            ],
        )

    def device(self, device_id: str, **overrides):
        return factories.device(
            self.org, device_id, device_type=self.bidirectional, **overrides
        )

    def assert_refused(self, device, name, params, code):
        with self.assertRaises((ValidationError, Conflict)) as caught:
            check_capabilities(device, name, params)
        self.assertEqual(caught.exception.code, code)

    # ---- the headline case ----------------------------------------------
    def test_a_discharge_only_unit_refuses_a_negative_setpoint(self):
        # Negative watts = charge. The blueprint schema allows -5 MW, so only
        # the capability check stands between the operator and the mistake.
        backup = self.device("BACKUP-1", can_charge=False)
        self.assert_refused(
            backup, "set_power_setpoint", {"power_w": -50_000}, "capability_not_supported"
        )

    def test_the_same_unit_accepts_a_positive_setpoint(self):
        backup = self.device("BACKUP-2", can_charge=False)
        check_capabilities(backup, "set_power_setpoint", {"power_w": 50_000})

    def test_a_zero_setpoint_needs_no_capability(self):
        inert = self.device("INERT-1", can_charge=False, can_discharge=False)
        check_capabilities(inert, "set_power_setpoint", {"power_w": 0})

    def test_charge_mode_is_refused_on_a_discharge_only_unit(self):
        backup = self.device("BACKUP-3", can_charge=False)
        self.assert_refused(
            backup, "set_mode", {"mode": "charge"}, "capability_not_supported"
        )

    def test_auto_mode_requires_both_directions(self):
        # Auto may do either, so a unit that cannot charge cannot follow it.
        backup = self.device("BACKUP-4", can_charge=False)
        self.assert_refused(
            backup, "set_mode", {"mode": "auto"}, "capability_not_supported"
        )

    def test_idle_mode_needs_nothing(self):
        backup = self.device("BACKUP-5", can_charge=False, can_discharge=False)
        check_capabilities(backup, "set_mode", {"mode": "idle"})

    def test_export_is_refused_when_not_permitted(self):
        ups = self.device("UPS-1", can_export=False)
        self.assert_refused(
            ups, "set_export_limit", {"limit_w": 10_000}, "export_not_permitted"
        )

    def test_an_export_limit_of_zero_is_always_allowed(self):
        # Setting the limit to zero *prevents* export; refusing it would be
        # backwards.
        ups = self.device("UPS-2", can_export=False)
        check_capabilities(ups, "set_export_limit", {"limit_w": 0})

    # ---- dispatchability -------------------------------------------------
    def test_a_meter_refuses_dispatch_commands(self):
        meter = self.device("METER-1", is_dispatchable=False)
        self.assert_refused(
            meter, "set_power_setpoint", {"power_w": 100}, "asset_not_dispatchable"
        )

    def test_a_meter_still_accepts_configuration_commands(self):
        # kind="config": changing the reporting interval moves no power.
        meter = self.device("METER-2", is_dispatchable=False)
        check_capabilities(meter, "set_report_interval", {"interval_s": 60})

    # ---- commissioning ---------------------------------------------------
    def test_a_pending_device_refuses_dispatch(self):
        unconfirmed = self.device(
            "PENDING-1", commissioning_state=LifecycleState.PENDING
        )
        self.assert_refused(
            unconfirmed, "set_power_setpoint", {"power_w": 100}, "device_unconfirmed"
        )

    def test_a_pending_device_still_accepts_configuration(self):
        unconfirmed = self.device(
            "PENDING-2", commissioning_state=LifecycleState.PENDING
        )
        check_capabilities(unconfirmed, "set_report_interval", {"interval_s": 60})

    def test_a_confirmed_device_is_unaffected(self):
        normal = self.device("OK-1")
        check_capabilities(normal, "set_power_setpoint", {"power_w": -100})


class BalanceExclusionTests(TestCase):
    """Sub-meters are measured and charted, but never summed into the balance."""

    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, timezone_name="Asia/Taipei")
        self.start = dt.datetime(2026, 6, 1, 4, 0, tzinfo=UTC)

    def asset(self, device_id: str, role: str, metric: str, **extra) -> EnergyAsset:
        device = factories.device(self.org, device_id, site_obj=self.site)
        return EnergyAsset.objects.create(
            organization=self.org,
            site=self.site,
            device=device,
            role=role,
            power_metric=metric,
            power_scale=0.001,
            **extra,
        )

    def sample(self, asset: EnergyAsset, metric: str, value: float) -> None:
        TelemetrySample.objects.create(
            organization=self.org,
            device_id=asset.device_id,
            metric_key=metric,
            ts=self.start,
            value=value,
        )

    def run_interval(self) -> EnergyInterval:
        SiteAggregator(self.site).run(self.start, self.start + dt.timedelta(minutes=15))
        return EnergyInterval.objects.get()

    def test_a_sub_meter_is_not_added_to_the_load(self):
        main = self.asset("MAIN-METER", AssetRole.LOAD_METER, "load_power_w")
        machine = self.asset(
            "MACHINE-1",
            AssetRole.LOAD_METER,
            "load_power_w",
            include_in_balance=False,
        )
        self.sample(main, "load_power_w", 400_000)  # 400 kW total
        self.sample(machine, "load_power_w", 100_000)  # already inside the 400

        # Counting both would report 500 kW for a quarter hour = 125 kWh.
        self.assertAlmostEqual(self.run_interval().load_kwh, 100.0, places=4)

    def test_two_included_load_meters_do_add_up(self):
        # Two feeders that together cover the site are legitimately summed.
        first = self.asset("FEEDER-A", AssetRole.LOAD_METER, "load_power_w")
        second = self.asset("FEEDER-B", AssetRole.LOAD_METER, "load_power_w")
        self.sample(first, "load_power_w", 200_000)
        self.sample(second, "load_power_w", 200_000)
        self.assertAlmostEqual(self.run_interval().load_kwh, 100.0, places=4)

    def test_an_excluded_ev_charger_is_not_double_counted(self):
        main = self.asset("MAIN-2", AssetRole.LOAD_METER, "load_power_w")
        self.asset(
            "EVSE-1",
            AssetRole.EV_CHARGER,
            "ev_charger_power_w",
            include_in_balance=False,
        )
        self.sample(main, "load_power_w", 400_000)
        TelemetrySample.objects.create(
            organization=self.org,
            device=factories.device(self.org, "EVSE-SAMPLE", site_obj=self.site),
            metric_key="ev_charger_power_w",
            ts=self.start,
            value=50_000,
        )
        self.assertAlmostEqual(self.run_interval().load_kwh, 100.0, places=4)

    def test_an_excluded_grid_meter_does_not_inflate_import(self):
        main = self.asset("GRID-MAIN", AssetRole.GRID_METER, "grid_power_w")
        shadow = self.asset(
            "GRID-SHADOW",
            AssetRole.GRID_METER,
            "grid_power_w",
            include_in_balance=False,
        )
        self.sample(main, "grid_power_w", 200_000)
        self.sample(shadow, "grid_power_w", 200_000)
        self.assertAlmostEqual(self.run_interval().grid_import_kwh, 50.0, places=4)


class GeneratorAggregationTests(TestCase):
    """The generator role used to fall through the aggregator untouched."""

    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, timezone_name="Asia/Taipei")
        self.start = dt.datetime(2026, 6, 1, 4, 0, tzinfo=UTC)

        self.grid = factories.device(self.org, "GEN-GRID", site_obj=self.site)
        self.genset = factories.device(self.org, "GEN-SET", site_obj=self.site)
        for device, role, metric in (
            (self.grid, AssetRole.GRID_METER, "grid_power_w"),
            (self.genset, AssetRole.GENERATOR, "load_power_w"),
        ):
            EnergyAsset.objects.create(
                organization=self.org,
                site=self.site,
                device=device,
                role=role,
                power_metric=metric,
                power_scale=0.001,
            )

    def sample(self, device, metric, value):
        TelemetrySample.objects.create(
            organization=self.org,
            device=device,
            metric_key=metric,
            ts=self.start,
            value=value,
        )

    def run_interval(self) -> EnergyInterval:
        SiteAggregator(self.site).run(self.start, self.start + dt.timedelta(minutes=15))
        return EnergyInterval.objects.get()

    def test_generator_output_is_recorded_in_its_own_column(self):
        self.sample(self.grid, "grid_power_w", 100_000)
        self.sample(self.genset, "load_power_w", 80_000)

        interval = self.run_interval()
        self.assertAlmostEqual(interval.generator_kwh, 20.0, places=4)
        # Never folded into the battery figures: round-trip efficiency is
        # discharge / charge, and a generator only ever discharges.
        self.assertAlmostEqual(interval.battery_discharge_kwh, 0.0, places=4)
        self.assertAlmostEqual(interval.battery_charge_kwh, 0.0, places=4)

    def test_generator_output_is_part_of_the_derived_load(self):
        # load = import - export + pv + discharge - charge + generator
        self.sample(self.grid, "grid_power_w", 100_000)  # 25 kWh
        self.sample(self.genset, "load_power_w", 80_000)  # 20 kWh
        self.assertAlmostEqual(self.run_interval().load_kwh, 45.0, places=4)
