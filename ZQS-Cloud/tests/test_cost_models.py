"""Pluggable cost models, and the trust boundary around their parameters.

The security test at the bottom is the important one. A cost model decides
what a report says the generator cost, and an operator may dispatch on that -
so a device that could declare its own fuel consumption could talk itself into
looking ten times cheaper than the grid. §3.12 of device-classification.md
requires that the settlement result be unchanged by anything a device claims.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.core.timeutils import now
from apps.ems import costs
from apps.ems.costs.base import UnknownCostModel
from apps.ems.models import (
    AssetRole,
    EnergyAsset,
    EnergyInterval,
    EnergyIntervalCost,
    StoragePlan,
    Tariff,
)
from apps.ems.tariffs import Price
from tests import factories


class Registry(TestCase):
    def test_the_built_in_models_are_registered(self):
        self.assertEqual(
            set(costs.available()),
            {"grid_tariff", "grid_export", "battery_cycle", "diesel_fuel"},
        )

    def test_an_unknown_key_raises_rather_than_costing_nothing(self):
        """Silently free energy is the error nobody notices."""
        with self.assertRaises(UnknownCostModel):
            costs.get("cold_fusion")

    def test_the_asset_overrides_the_role_default(self):
        asset = EnergyAsset(role=AssetRole.GENERATOR, cost_model="grid_tariff")
        self.assertEqual(costs.model_for(asset, AssetRole.GENERATOR), "grid_tariff")

    def test_a_blank_key_falls_back_to_the_role(self):
        asset = EnergyAsset(role=AssetRole.GENERATOR, cost_model="")
        self.assertEqual(costs.model_for(asset, AssetRole.GENERATOR), "diesel_fuel")


def _context(**kwargs):
    start = now()
    defaults = dict(
        start=start,
        end=start + dt.timedelta(minutes=15),
        interval_seconds=900,
        energy_kwh=10.0,
        price_at=lambda _moment: Price(
            period_name="peak", import_price=8.0, export_price=2.0, currency="TWD"
        ),
    )
    defaults.update(kwargs)
    return costs.CostContext(**defaults)


class DieselTests(TestCase):
    def test_a_flat_consumption_figure_is_fuel_times_price(self):
        asset = EnergyAsset(
            role=AssetRole.GENERATOR,
            rated_power_kw=200.0,
            cost_parameters={"litres_per_kwh": 0.25, "fuel_price_per_litre": 32.0},
        )
        result = costs.compute("diesel_fuel", _context(asset=asset))
        self.assertAlmostEqual(result.amount, 10.0 * 0.25 * 32.0)
        self.assertEqual(result.basis, "measured")

    def test_maintenance_accrues_per_running_hour(self):
        asset = EnergyAsset(
            role=AssetRole.GENERATOR,
            cost_parameters={
                "litres_per_kwh": 0.25,
                "fuel_price_per_litre": 32.0,
                "maintenance_per_hour": 400.0,
            },
        )
        result = costs.compute(
            "diesel_fuel", _context(asset=asset, running_hours=0.25)
        )
        self.assertAlmostEqual(result.breakdown["maintenance"], 100.0)

    def test_a_load_curve_is_interpolated(self):
        asset = EnergyAsset(
            role=AssetRole.GENERATOR,
            rated_power_kw=100.0,
            cost_parameters={
                "fuel_price_per_litre": 10.0,
                "fuel_curve": [[0.25, 0.40], [0.75, 0.20]],
            },
        )
        # 10 kWh over 15 minutes is 40 kW, i.e. 40% of rating - three tenths
        # of the way from 0.25 to 0.75, so 0.40 - 0.3 x 0.20 = 0.34 l/kWh.
        result = costs.compute("diesel_fuel", _context(asset=asset))
        self.assertAlmostEqual(result.breakdown["litres"], 10.0 * 0.34, places=4)

    def test_an_unconfigured_generator_is_reported_as_an_estimate(self):
        """A default consumption figure is a guess about someone else's engine."""
        asset = EnergyAsset(role=AssetRole.GENERATOR)
        result = costs.compute("diesel_fuel", _context(asset=asset))
        self.assertEqual(result.basis, "estimated")


class BatteryTests(TestCase):
    def test_discharging_costs_wear_plus_the_energy_that_went_in(self):
        asset = EnergyAsset(
            role=AssetRole.BATTERY,
            cost_parameters={
                "cycle_cost_per_kwh": 1.5,
                "charge_price_per_kwh": 2.0,
                "round_trip_efficiency": 0.8,
            },
        )
        result = costs.compute("battery_cycle", _context(asset=asset))
        # 10 kWh out needed 12.5 kWh in at 2.0, plus 10 x 1.5 of wear.
        self.assertAlmostEqual(result.amount, 15.0 + 25.0)
        self.assertAlmostEqual(result.breakdown["cycle_wear"], 15.0)
        self.assertEqual(result.basis, "measured")

    def test_without_a_charge_price_the_result_is_an_estimate(self):
        asset = EnergyAsset(
            role=AssetRole.BATTERY, cost_parameters={"cycle_cost_per_kwh": 1.0}
        )
        result = costs.compute("battery_cycle", _context(asset=asset))
        self.assertEqual(result.basis, "estimated")

    def test_the_plan_supplies_the_efficiency_when_the_asset_does_not(self):
        asset = EnergyAsset(
            role=AssetRole.BATTERY, cost_parameters={"charge_price_per_kwh": 1.0}
        )
        plan = StoragePlan(round_trip_efficiency=0.5)
        result = costs.compute("battery_cycle", _context(asset=asset, plan=plan))
        self.assertAlmostEqual(result.amount, 20.0)


class ExportTests(TestCase):
    def test_export_is_a_negative_amount(self):
        """Money coming in, expressed on the same axis as money going out."""
        result = costs.compute("grid_export", _context(asset=EnergyAsset()))
        self.assertAlmostEqual(result.amount, -20.0)


class SettlementIntegrationTests(TestCase):
    """The aggregator's totals, the breakdown table, and the trust boundary."""

    def setUp(self) -> None:
        from apps.telemetry.models import TelemetrySample

        self.org = factories.organization("costs")
        self.site = factories.site(self.org, "hq")
        self.meter = factories.device(self.org, "COST-METER", site_obj=self.site)
        self.generator = factories.device(self.org, "COST-GEN", site_obj=self.site)

        tariff = Tariff.objects.create(
            organization=self.org,
            name="Flat",
            default_import_price=5.0,
            default_export_price=1.0,
        )
        factories.storage_plan(self.org, self.site, tariff=tariff)

        EnergyAsset.objects.create(
            organization=self.org,
            site=self.site,
            device=self.meter,
            role=AssetRole.GRID_METER,
            power_metric="grid_power_w",
            power_scale=0.001,
        )
        EnergyAsset.objects.create(
            organization=self.org,
            site=self.site,
            device=self.generator,
            role=AssetRole.GENERATOR,
            power_metric="generator_power_w",
            power_scale=0.001,
            rated_power_kw=200.0,
            cost_parameters={"litres_per_kwh": 0.3, "fuel_price_per_litre": 30.0},
        )

        self.start = now().replace(minute=0, second=0, microsecond=0) - dt.timedelta(
            hours=1
        )
        rows = []
        for index in range(16):
            ts = self.start + dt.timedelta(minutes=index)
            rows.append(
                TelemetrySample(
                    organization=self.org,
                    device=self.meter,
                    metric_key="grid_power_w",
                    ts=ts,
                    value=100_000.0,
                )
            )
            rows.append(
                TelemetrySample(
                    organization=self.org,
                    device=self.generator,
                    metric_key="generator_power_w",
                    ts=ts,
                    value=40_000.0,
                )
            )
        TelemetrySample.objects.bulk_create(rows)

    def _run(self):
        from apps.ems.aggregator import SiteAggregator

        SiteAggregator(self.site).run(self.start, self.start + dt.timedelta(minutes=15))
        return EnergyInterval.objects.get(site=self.site, interval_start=self.start)

    def test_each_source_gets_its_own_priced_row(self):
        interval = self._run()
        rows = {row.source: row for row in interval.costs.all()}
        self.assertEqual(set(rows), {"grid", "generator"})
        self.assertEqual(rows["generator"].cost_model, "diesel_fuel")
        # 40 kW for a quarter hour is 10 kWh, at 0.3 l/kWh and 30/l.
        self.assertAlmostEqual(rows["generator"].amount, 10.0 * 0.3 * 30.0, places=2)

    def test_the_headline_totals_keep_their_old_grid_only_meaning(self):
        """Existing dashboards and roll-ups must not shift under them."""
        interval = self._run()
        self.assertAlmostEqual(interval.energy_cost, 25.0 * 5.0, places=2)

    def test_savings_are_unknown_while_a_generator_is_carrying_the_site(self):
        """There is no "buy it from the grid instead" during an outage."""
        interval = self._run()
        self.assertIsNone(interval.estimated_savings)

    def test_rebuilding_replaces_the_breakdown_instead_of_appending(self):
        self._run()
        first = EnergyIntervalCost.objects.count()
        self._run()
        self.assertEqual(EnergyIntervalCost.objects.count(), first)

    def test_a_device_declaration_cannot_change_what_anything_costs(self):
        """The trust boundary §3.12 asks for, pinned.

        A device claiming a fuel consumption ten times lower must not move the
        settlement figure by one cent: costing reads the asset row, which only
        an admin can write.
        """
        from apps.devices.models import DeviceDeclaration

        before = self._run().costs.get(source="generator").amount

        DeviceDeclaration.objects.create(
            device=self.generator,
            payload={
                "cost_model_hint": "grid_tariff",
                "ratings": {"fuel_consumption_l_per_kwh": 0.001},
                "capabilities": {"can_export": True},
            },
            received_at=now(),
        )
        after = self._run().costs.get(source="generator").amount
        self.assertEqual(before, after)
