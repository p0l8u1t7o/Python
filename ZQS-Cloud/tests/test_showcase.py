"""The customer showcase: seed, fleet wiring, and the closed loop in the
simulated plant (setpoint -> battery -> meter)."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.devices.models import Device, EdgeNode, Site
from apps.ems.models import AssetRole, EnergyAsset, StoragePlan
from apps.ems.plans import effective_plan
from services.harness.fleet import SitePhysics, build_fleet


class SeedShowcaseTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        call_command("bootstrap", stdout=StringIO())
        call_command("seed_showcase", stdout=StringIO())
        from apps.accounts.models import Organization

        cls.org = Organization.objects.get(slug="zqs-demo")

    def test_sites_devices_and_gateways(self) -> None:
        self.assertEqual(Site.objects.filter(organization=self.org).count(), 5)
        self.assertEqual(
            Device.objects.filter(organization=self.org, deleted_at__isnull=True).count(), 20
        )
        self.assertEqual(
            EdgeNode.objects.filter(organization=self.org, is_implicit=False).count(), 4
        )
        # Every device sits on its site's gateway, and every gateway has a credential.
        for device in Device.objects.filter(organization=self.org):
            self.assertEqual(device.edge_node.site_id, device.site_id)
            self.assertTrue(hasattr(device.edge_node, "credential"))

    def test_plan_inheritance_and_override(self) -> None:
        campus = Site.objects.get(organization=self.org, code="hsinchu")
        a = Site.objects.get(organization=self.org, code="hsinchu-a")
        b = Site.objects.get(organization=self.org, code="hsinchu-b")
        plan_a, source_a = effective_plan(a)
        plan_b, source_b = effective_plan(b)
        self.assertEqual(plan_a.name, "園區契約容量管理")
        self.assertEqual(source_a.pk, campus.pk)  # inherited
        self.assertEqual(plan_b.name, "研發大樓光儲自發自用")
        self.assertEqual(source_b.pk, b.pk)  # overridden
        self.assertEqual(StoragePlan.objects.filter(organization=self.org).count(), 4)

    def test_every_energy_site_has_the_four_roles_with_ratings(self) -> None:
        for code in ("hsinchu-a", "hsinchu-b", "taichung", "taipei-hq"):
            site = Site.objects.get(organization=self.org, code=code)
            roles = {a.role: a for a in EnergyAsset.objects.filter(site=site)}
            self.assertEqual(
                set(roles), {AssetRole.BATTERY, AssetRole.GRID_METER, AssetRole.PV, AssetRole.LOAD_METER}
            )
            self.assertTrue(roles[AssetRole.BATTERY].rated_power_kw)
            self.assertTrue(roles[AssetRole.BATTERY].rated_energy_kwh)
            self.assertTrue(roles[AssetRole.LOAD_METER].rated_power_kw)

    def test_the_fleet_builds_one_runner_per_gateway_sized_from_the_assets(self) -> None:
        runners = build_fleet(self.org, interval=5.0, faults=False, autonomous=False, report=lambda _: None)
        self.assertEqual(len(runners), 4)
        by_node = {r.node_id: r for r in runners}
        taichung = by_node["GW-TAICHUNG"]
        self.assertEqual(len(taichung.devices), 5)
        self.assertEqual(taichung.physics.kind, "factory")
        self.assertEqual(taichung.physics.battery_kw_rated, 1000.0)
        self.assertEqual(taichung.physics.battery_kwh, 2000.0)
        self.assertEqual(taichung.physics.peak_load_kw, 1200.0)
        self.assertEqual(taichung.physics.timezone_name, "Asia/Taipei")

    def test_the_six_workflows_exist_and_run_without_error(self) -> None:
        """Each example advances through the engine (dry run) with fresh
        readings present, and nothing logs an error or fails."""
        import datetime as dt

        from django.utils import timezone

        from apps.telemetry.models import LatestSample
        from apps.workflows.engine import advance
        from apps.workflows.models import RunStatus, Workflow, WorkflowLog
        from apps.workflows.runner import start_run

        workflows = list(Workflow.objects.filter(organization=self.org).order_by("name"))
        self.assertEqual(len(workflows), 6)
        now = timezone.now()
        for device in Device.objects.filter(organization=self.org):
            for key, value in (("grid_power_w", 700_000.0), ("battery_soc", 55.0),
                               ("battery_temperature_c", 30.0), ("pv_power_w", 300_000.0)):
                LatestSample.objects.update_or_create(
                    organization=self.org, device=device, metric_key=key,
                    defaults={"value": value, "ts": now, "quality": 0},
                )
        for workflow in workflows:
            self.assertTrue(workflow.is_enabled)
            self.assertTrue(any(n["type"] == "note" for n in workflow.graph["nodes"]), workflow.name)
            run = start_run(workflow, dry_run=True)
            clock = now
            for _ in range(12):
                advance(run, moment=clock)
                run.refresh_from_db()
                if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
                    break
                clock += dt.timedelta(seconds=15)
            self.assertNotEqual(run.status, RunStatus.FAILED, workflow.name)
            errors = list(WorkflowLog.objects.filter(run=run, level="error").values_list("message", flat=True))
            self.assertEqual(errors, [], workflow.name)
            self.assertGreater(WorkflowLog.objects.filter(run=run).count(), 2, workflow.name)

    def test_seeding_twice_is_idempotent(self) -> None:
        call_command("seed_showcase", stdout=StringIO())
        self.assertEqual(
            Device.objects.filter(organization=self.org, deleted_at__isnull=True).count(), 20
        )
        self.assertEqual(StoragePlan.objects.filter(organization=self.org).count(), 4)


class SitePhysicsTests(TestCase):
    """The simulated plant keeps its books: grid = load - pv - battery."""

    def test_a_setpoint_moves_the_battery_and_the_meter(self) -> None:
        physics = SitePhysics(kind="factory", peak_load_kw=900.0, pv_peak_kw=400.0,
                              battery_kw_rated=500.0, battery_kwh=1000.0)
        physics.step()
        idle_grid = physics.grid_kw
        physics.command("set_power_setpoint", {"power_w": -200000})
        physics.step()
        self.assertAlmostEqual(physics.battery_kw, -200.0)
        # The meter rose by the charge, give or take the load noise.
        self.assertGreater(physics.grid_kw - idle_grid, 150.0)
        battery = physics.sample(AssetRole.BATTERY, "battery_power_w")
        meter = physics.sample(AssetRole.GRID_METER, "grid_power_w")
        self.assertAlmostEqual(battery["battery_power_w"], -200000.0)
        self.assertAlmostEqual(
            meter["grid_power_w"] / 1000, physics.load_kw - physics.pv_kw + 200.0, delta=0.1
        )

    def test_emergency_stop_overrides_the_setpoint(self) -> None:
        physics = SitePhysics(kind="office")
        physics.command("set_power_setpoint", {"power_w": 100000})
        physics.command("emergency_stop", {})
        physics.step()
        self.assertEqual(physics.battery_kw, 0.0)

    def test_soc_stays_inside_its_limits(self) -> None:
        physics = SitePhysics(kind="office", battery_kw_rated=100.0, battery_kwh=10.0,
                              soc=94.0, max_soc=95.0)
        physics.command("set_power_setpoint", {"power_w": -100000})
        physics._last -= 3600  # pretend an hour passed
        physics.step()
        self.assertLessEqual(physics.soc, 95.0 + 1e-6)
