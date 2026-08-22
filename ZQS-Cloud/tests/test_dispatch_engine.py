"""Automatic dispatch, and the storage plan as a gate rather than a note.

Two properties get most of the attention here because both are the kind that
silently stop holding:

* the engine issues a command only when the target has **moved** - otherwise
  every scheduler cycle republishes the same setpoint to real hardware;
* the plan's envelope applies to the **manual** path too, so an operator and
  the scheduler cannot end up with different limits.
"""

from __future__ import annotations

import datetime as dt
from unittest import mock

from django.test import TestCase

from apps.accounts.models import Role
from apps.accounts.security import AuthContext
from apps.core.errors import ValidationError
from apps.core.timeutils import now
from apps.devices.models import Command, DeviceCategory
from apps.devices.services import dispatch_command
from apps.ems import dispatch
from apps.ems.models import (
    AssetRole,
    DispatchMode,
    DispatchWindow,
    EnergyAsset,
    StoragePlan,
)
from apps.telemetry.models import LatestSample
from tests import factories

SETPOINT_SPEC = {
    "name": "set_power_setpoint",
    "kind": "dispatch",
    "min_role": Role.OPERATOR,
    "params": {
        "type": "object",
        "required": ["power_w"],
        "properties": {
            "power_w": {"type": "number", "minimum": -5_000_000, "maximum": 5_000_000}
        },
    },
}


class DispatchTestCase(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization("dispatch")
        self.site = factories.site(self.org, "hq")
        self.blueprint = factories.blueprint(
            "bess",
            org=self.org,
            category=DeviceCategory.BATTERY,
            can_charge=True,
            can_discharge=True,
            can_export=True,
            is_dispatchable=True,
            command_definitions=[SETPOINT_SPEC],
        )
        self.device = factories.device(
            self.org, "DISP-BESS", site_obj=self.site, device_type=self.blueprint
        )
        self.asset = EnergyAsset.objects.create(
            organization=self.org,
            site=self.site,
            device=self.device,
            role=AssetRole.BATTERY,
            power_metric="battery_power_w",
            soc_metric="battery_soc",
            power_scale=0.001,
            rated_power_kw=500.0,
        )
        self.plan = factories.storage_plan(
            self.org,
            self.site,
            max_charge_kw=200.0,
            max_discharge_kw=200.0,
            min_soc_percent=10.0,
            max_soc_percent=95.0,
            backup_reserve_percent=20.0,
        )
        self.ctx = AuthContext(organization=self.org, role=Role.ADMIN)

    def _soc(self, percent: float) -> None:
        LatestSample.objects.update_or_create(
            device=self.device,
            metric_key="battery_soc",
            defaults={
                "organization": self.org,
                "ts": now(),
                "value": percent,
            },
        )

    def _window(self, mode, **kwargs) -> DispatchWindow:
        moment = now()
        return DispatchWindow.objects.create(
            organization=self.org,
            site=self.site,
            mode=mode,
            starts_at=kwargs.pop("starts_at", moment - dt.timedelta(minutes=5)),
            ends_at=kwargs.pop("ends_at", moment + dt.timedelta(hours=1)),
            **kwargs,
        )


class ClampTests(DispatchTestCase):
    def test_a_discharge_above_the_plan_is_reduced(self):
        permitted, reason = dispatch.clamp_to_plan(self.plan, 500_000.0)
        self.assertEqual(permitted, 200_000.0)
        self.assertEqual(reason, "max_discharge_kw")

    def test_a_charge_above_the_plan_is_reduced(self):
        permitted, _ = dispatch.clamp_to_plan(self.plan, -500_000.0)
        self.assertEqual(permitted, -200_000.0)

    def test_discharging_stops_at_the_backup_reserve(self):
        permitted, reason = dispatch.clamp_to_plan(
            self.plan, 100_000.0, soc_percent=18.0
        )
        self.assertEqual(permitted, 0.0)
        self.assertIn("backup_reserve_percent", reason)

    def test_charging_stops_at_the_upper_soc_bound(self):
        permitted, _ = dispatch.clamp_to_plan(self.plan, -100_000.0, soc_percent=96.0)
        self.assertEqual(permitted, 0.0)

    def test_an_unknown_soc_leaves_the_power_limits_to_do_the_work(self):
        """Guessing at SOC would either block real dispatch or allow a deep
        discharge; neither is acceptable, so it is simply not guessed."""
        permitted, _ = dispatch.clamp_to_plan(self.plan, 100_000.0, soc_percent=None)
        self.assertEqual(permitted, 100_000.0)

    def test_enforcement_can_be_turned_off(self):
        self.plan.enforce_limits = False
        permitted, reason = dispatch.clamp_to_plan(self.plan, 999_000.0)
        self.assertEqual(permitted, 999_000.0)
        self.assertEqual(reason, "")


class ManualCommandTests(DispatchTestCase):
    """The plan is a gate on what a person can send, not just documentation."""

    def test_a_setpoint_beyond_the_plan_is_refused(self):
        with mock.patch("apps.devices.services.publish_bytes"):
            with self.assertRaises(ValidationError) as caught:
                dispatch_command(
                    self.ctx,
                    self.device,
                    name="set_power_setpoint",
                    params={"power_w": 400_000},
                )
        self.assertEqual(caught.exception.code, "storage_plan_limit")

    def test_a_setpoint_inside_the_plan_goes_through(self):
        with mock.patch("apps.devices.services.publish_bytes"):
            command = dispatch_command(
                self.ctx,
                self.device,
                name="set_power_setpoint",
                params={"power_w": 150_000},
            )
        self.assertEqual(command.params["power_w"], 150_000)

    def test_the_capability_check_still_reports_first(self):
        """"Cannot charge at all" is more useful than "cannot charge that hard"."""
        self.device.can_charge = False
        self.device.save(update_fields=["can_charge"])
        with mock.patch("apps.devices.services.publish_bytes"):
            with self.assertRaises(ValidationError) as caught:
                dispatch_command(
                    self.ctx,
                    self.device,
                    name="set_power_setpoint",
                    params={"power_w": -400_000},
                )
        self.assertEqual(caught.exception.code, "capability_not_supported")

    def test_a_site_with_no_plan_is_unconstrained(self):
        StoragePlan.objects.all().delete()
        with mock.patch("apps.devices.services.publish_bytes"):
            command = dispatch_command(
                self.ctx,
                self.device,
                name="set_power_setpoint",
                params={"power_w": 900_000},
            )
        self.assertEqual(command.params["power_w"], 900_000)


class WindowSelectionTests(DispatchTestCase):
    def test_the_higher_priority_window_wins(self):
        low = self._window(DispatchMode.CHARGE, priority=0)
        high = self._window(DispatchMode.DISCHARGE, priority=5)
        chosen = dispatch.active_window([low, high], now())
        self.assertEqual(chosen.pk, high.pk)

    def test_equal_priority_is_broken_by_the_later_start(self):
        """So a one-off override entered today beats the daily schedule."""
        early = self._window(
            DispatchMode.CHARGE, starts_at=now() - dt.timedelta(hours=3)
        )
        late = self._window(
            DispatchMode.DISCHARGE, starts_at=now() - dt.timedelta(minutes=1)
        )
        self.assertEqual(dispatch.active_window([early, late], now()).pk, late.pk)

    def test_a_disabled_window_is_ignored(self):
        window = self._window(DispatchMode.CHARGE, is_enabled=False)
        self.assertIsNone(dispatch.active_window([window], now()))

    def test_idle_asks_for_zero_not_for_nothing(self):
        window = self._window(DispatchMode.IDLE)
        self.assertEqual(dispatch.target_power_w(window, self.plan), 0.0)

    def test_auto_names_no_setpoint(self):
        """Following a strategy is not this engine's decision to make."""
        window = self._window(DispatchMode.AUTO)
        self.assertIsNone(dispatch.target_power_w(window, self.plan))

    def test_a_window_with_no_figure_uses_the_whole_envelope(self):
        window = self._window(DispatchMode.CHARGE)
        self.assertEqual(dispatch.target_power_w(window, self.plan), -200_000.0)


class EngineTests(DispatchTestCase):
    def test_the_engine_issues_the_clamped_setpoint(self):
        self._window(DispatchMode.DISCHARGE, target_power_kw=400.0)
        self._soc(80.0)
        with mock.patch("apps.devices.services.publish_bytes"):
            decision = dispatch.run_site(self.ctx, self.site.pk)

        self.assertEqual(decision.power_w, 200_000.0)
        self.assertEqual(decision.clamped_from_w, 400_000.0)
        command = Command.objects.get()
        self.assertEqual(command.params["power_w"], 200_000.0)

    def test_a_second_cycle_sends_nothing_when_the_target_has_not_moved(self):
        self._window(DispatchMode.DISCHARGE, target_power_kw=100.0)
        self._soc(80.0)
        with mock.patch("apps.devices.services.publish_bytes"):
            dispatch.run_site(self.ctx, self.site.pk)
            second = dispatch.run_site(self.ctx, self.site.pk)

        self.assertEqual(second.skipped, "unchanged")
        self.assertEqual(Command.objects.count(), 1)

    def test_no_active_window_means_no_command(self):
        # With no window, the plan's strategy gets its say - and a manual
        # plan's strategy has none, so the site is left alone.
        decision = dispatch.decide(self.site.pk)
        self.assertIsNone(decision.power_w)
        self.assertEqual(decision.skipped, "no_setpoint")

    def test_a_disabled_plan_stops_the_engine(self):
        self._window(DispatchMode.DISCHARGE, target_power_kw=100.0)
        self.plan.is_enabled = False
        self.plan.save(update_fields=["is_enabled"])
        self.assertEqual(dispatch.decide(self.site.pk).skipped, "plan_disabled")

    def test_a_dry_run_decides_without_sending(self):
        self._window(DispatchMode.DISCHARGE, target_power_kw=100.0)
        self._soc(80.0)
        decision = dispatch.run_site(self.ctx, self.site.pk, dry_run=True)
        self.assertEqual(decision.power_w, 100_000.0)
        self.assertEqual(decision.skipped, "dry_run")
        self.assertEqual(Command.objects.count(), 0)

    def test_a_refused_command_is_recorded_rather_than_raised(self):
        """One site's problem must not stop the other sites being served."""
        self._window(DispatchMode.DISCHARGE, target_power_kw=100.0)
        self._soc(80.0)
        self.device.can_discharge = False
        self.device.save(update_fields=["can_discharge"])

        decision = dispatch.run_site(self.ctx, self.site.pk)
        self.assertEqual(decision.skipped, "capability_not_supported")
        self.assertEqual(Command.objects.count(), 0)

    def test_a_retired_battery_is_not_dispatched(self):
        from apps.devices.models import LifecycleState

        self._window(DispatchMode.DISCHARGE, target_power_kw=100.0)
        self.device.commissioning_state = LifecycleState.RETIRED
        self.device.save(update_fields=["commissioning_state"])
        self.assertEqual(dispatch.decide(self.site.pk).skipped, "no_device")
