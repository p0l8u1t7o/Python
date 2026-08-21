"""Lifecycle, replacement, and stitching a chain back into one series.

The stitching test is the load-bearing one. Retired hardware routinely keeps
reporting - left powered on a bench, or simply not yet unplugged - so a naive
"same asset" report would count two devices over the same minutes. That inflates
energy and manufactures a peak that never happened, and both results look
entirely plausible on a chart.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.alerts.models import AlertRule, RuleScope
from apps.audit.models import AuditAction, AuditLog
from apps.core.errors import Conflict
from apps.core.timeutils import UTC, now
from apps.devices.models import (
    DECLARATION_SCHEMA_VERSION,
    Device,
    DeviceDeclaration,
    LifecycleState,
    chain_segments,
)
from apps.devices.services import check_capabilities, set_lifecycle
from apps.ems.models import AssetRole, EnergyAsset
from apps.telemetry.models import TelemetrySample
from tests import factories
from tests.test_api import API, ApiTestCase


class Ctx:
    """Minimal auth context for calling services directly, as the API would."""

    is_service = False

    def __init__(self, org, user=None):
        self.organization = org
        self.user = user
        self.principal_label = "test"

    def require(self, role):  # pragma: no cover - not exercised here
        return True


class LifecycleTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.ctx = Ctx(self.org)
        self.device = factories.device(self.org, "LIFE-1")

    def test_a_new_device_is_active_and_ingesting(self):
        self.assertEqual(self.device.commissioning_state, LifecycleState.ACTIVE)
        self.assertTrue(self.device.is_enabled)

    def test_suspending_also_closes_the_ingest_gate(self):
        set_lifecycle(self.ctx, self.device, LifecycleState.SUSPENDED)
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_enabled)
        self.assertIsNone(self.device.retired_at)

    def test_retiring_records_when_and_closes_the_gate(self):
        set_lifecycle(self.ctx, self.device, LifecycleState.RETIRED)
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_enabled)
        self.assertIsNotNone(self.device.retired_at)

    def test_retiring_never_soft_deletes(self):
        # History has to stay reachable, and a soft-deleted device disappears
        # from the API entirely.
        set_lifecycle(self.ctx, self.device, LifecycleState.RETIRED)
        self.device.refresh_from_db()
        self.assertIsNone(self.device.deleted_at)
        self.assertTrue(Device.objects.filter(pk=self.device.pk).exists())

    def test_returning_to_service_reopens_the_gate(self):
        set_lifecycle(self.ctx, self.device, LifecycleState.RETIRED)
        set_lifecycle(self.ctx, self.device, LifecycleState.ACTIVE)
        self.device.refresh_from_db()
        self.assertTrue(self.device.is_enabled)
        self.assertIsNone(self.device.retired_at)

    def test_every_transition_is_audited(self):
        set_lifecycle(self.ctx, self.device, LifecycleState.SUSPENDED)
        set_lifecycle(self.ctx, self.device, LifecycleState.ACTIVE)
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.DEVICE_SUSPENDED).exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.DEVICE_RESTORED).exists())

    def test_an_unknown_state_is_rejected(self):
        with self.assertRaises(Exception):
            set_lifecycle(self.ctx, self.device, "decommissioned")


class EnergyBindingGuardTests(TestCase):
    """Stopping a device the balance depends on would fail silently."""

    def setUp(self) -> None:
        self.org = factories.organization()
        self.ctx = Ctx(self.org)
        self.site = factories.site(self.org)
        self.device = factories.device(self.org, "BOUND-1", site_obj=self.site)
        EnergyAsset.objects.create(
            organization=self.org,
            site=self.site,
            device=self.device,
            role=AssetRole.GRID_METER,
            power_metric="grid_power_w",
        )

    def test_retiring_a_bound_device_is_refused(self):
        with self.assertRaises(Conflict) as caught:
            set_lifecycle(self.ctx, self.device, LifecycleState.RETIRED)
        self.assertEqual(caught.exception.code, "device_in_energy_model")
        self.assertEqual(len(caught.exception.details["assets"]), 1)
        self.assertEqual(
            caught.exception.details["assets"][0]["role"], AssetRole.GRID_METER
        )

    def test_suspending_a_bound_device_is_refused(self):
        with self.assertRaises(Conflict) as caught:
            set_lifecycle(self.ctx, self.device, LifecycleState.SUSPENDED)
        self.assertEqual(caught.exception.code, "device_in_energy_model")

    def test_an_inactive_binding_does_not_block(self):
        EnergyAsset.objects.filter(device=self.device).update(is_active=False)
        set_lifecycle(self.ctx, self.device, LifecycleState.RETIRED)
        self.device.refresh_from_db()
        self.assertTrue(self.device.is_retired)


class CommandGateTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.ctx = Ctx(self.org)
        self.blueprint = factories.blueprint(
            "gate-pcs",
            self.org,
            can_charge=True,
            can_discharge=True,
            is_dispatchable=True,
            command_definitions=[
                {"name": "set_power_setpoint", "params": {}},
                {"name": "set_report_interval", "params": {}, "kind": "config"},
            ],
        )
        self.device = factories.device(self.org, "GATE-1", device_type=self.blueprint)

    def assert_refused(self, code: str):
        with self.assertRaises(Conflict) as caught:
            check_capabilities(self.device, "set_power_setpoint", {"power_w": 100})
        self.assertEqual(caught.exception.code, code)

    def test_a_retired_device_refuses_dispatch(self):
        set_lifecycle(self.ctx, self.device, LifecycleState.RETIRED)
        self.assert_refused("device_retired")

    def test_a_suspended_device_refuses_dispatch(self):
        set_lifecycle(self.ctx, self.device, LifecycleState.SUSPENDED)
        self.assert_refused("device_suspended")

    def test_a_retired_device_still_accepts_configuration(self):
        # Changing a reporting interval moves no power.
        set_lifecycle(self.ctx, self.device, LifecycleState.RETIRED)
        check_capabilities(self.device, "set_report_interval", {"interval_s": 60})

    def test_an_identity_mismatch_freezes_dispatch(self):
        DeviceDeclaration.objects.create(
            device=self.device,
            payload={"schema_version": DECLARATION_SCHEMA_VERSION},
            schema_version=DECLARATION_SCHEMA_VERSION,
            received_at=now(),
            identity_mismatch=True,
        )
        self.assert_refused("device_identity_mismatch")

    def test_a_plain_capability_difference_does_not_freeze(self):
        # Only a category disagreement means "this may not be the same thing".
        DeviceDeclaration.objects.create(
            device=self.device,
            payload={"schema_version": DECLARATION_SCHEMA_VERSION},
            schema_version=DECLARATION_SCHEMA_VERSION,
            received_at=now(),
            diff_summary={"can_export": {"declared": True, "effective": False}},
            identity_mismatch=False,
        )
        check_capabilities(self.device, "set_power_setpoint", {"power_w": 100})


class ChainSegmentTests(TestCase):
    """Each device owns exactly one window; the windows never overlap."""

    def setUp(self) -> None:
        self.org = factories.organization()
        self.cut = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        self.old = factories.device(
            self.org,
            "CHAIN-OLD",
            commissioning_state=LifecycleState.RETIRED,
            retired_at=self.cut,
        )
        self.new = factories.device(self.org, "CHAIN-NEW")
        self.old.replaced_by = self.new
        self.old.save(update_fields=["replaced_by"])

    def test_the_chain_runs_oldest_first(self):
        self.assertEqual(
            [d.device_id for d in self.old.replacement_chain()],
            ["CHAIN-OLD", "CHAIN-NEW"],
        )

    def test_segments_meet_exactly_at_the_retirement_instant(self):
        segments = chain_segments(self.old)
        self.assertEqual(segments[0][1], None)
        self.assertEqual(segments[0][2], self.cut)
        self.assertEqual(segments[1][1], self.cut)
        self.assertEqual(segments[1][2], None)

    def test_a_three_device_chain_has_three_windows(self):
        third = factories.device(self.org, "CHAIN-THIRD")
        later = self.cut + dt.timedelta(days=30)
        Device.objects.filter(pk=self.new.pk).update(
            replaced_by=third,
            retired_at=later,
            commissioning_state=LifecycleState.RETIRED,
        )
        segments = chain_segments(Device.objects.get(pk=self.old.pk))
        self.assertEqual(len(segments), 3)
        self.assertEqual([s[1] for s in segments], [None, self.cut, later])

    def test_a_cycle_in_the_data_terminates(self):
        Device.objects.filter(pk=self.new.pk).update(replaced_by=self.old)
        self.assertLessEqual(
            len(Device.objects.get(pk=self.old.pk).replacement_chain()), 2
        )

    def test_the_root_walks_back_to_the_first_device(self):
        self.assertEqual(self.new.replacement_root().device_id, "CHAIN-OLD")


class StitchedSeriesTests(ApiTestCase):
    """`follow_replacements` must never double count across the handover."""

    def setUp(self) -> None:
        super().setUp()
        self.token = self.login("admin@acme-demo.com")
        self.cut = now().replace(microsecond=0) - dt.timedelta(hours=1)

        self.old = factories.device(
            self.org,
            "SWAP-OLD",
            commissioning_state=LifecycleState.RETIRED,
            retired_at=self.cut,
            is_enabled=False,
        )
        self.new = factories.device(self.org, "SWAP-NEW")
        self.old.replaced_by = self.new
        self.old.save(update_fields=["replaced_by"])

        # The old unit was left powered on and kept reporting for another hour
        # after it was retired; the new one was commissioned early and reported
        # before the handover. Both overlaps must be discarded.
        for device, offset, value in (
            (self.old, -90, 100.0),  # old, before the cut  -> counts
            (self.old, +30, 999.0),  # old, after the cut   -> dropped
            (self.new, -80, 888.0),  # new, before the cut  -> dropped
            (self.new, +20, 200.0),  # new, after the cut   -> counts
        ):
            TelemetrySample.objects.create(
                organization=self.org,
                device=device,
                metric_key="battery_power_w",
                ts=self.cut + dt.timedelta(minutes=offset),
                value=value,
            )

    def query(self, body: dict):
        return self.post(f"{API}/telemetry/series", self.token, body)

    def base_body(self, **extra) -> dict:
        return {
            "device_ids": [str(self.old.id)],
            "metrics": ["battery_power_w"],
            "start": (self.cut - dt.timedelta(hours=3)).isoformat(),
            "end": (self.cut + dt.timedelta(hours=3)).isoformat(),
            "interval_seconds": 0,
            **extra,
        }

    def test_without_stitching_only_the_requested_device_appears(self):
        response = self.query(self.base_body())
        self.assertEqual(response.status_code, 200, response.content)
        series = response.json()["series"]
        self.assertEqual(len(series), 1)
        self.assertEqual({point["value"] for point in series[0]["points"]}, {100.0, 999.0})

    def test_stitching_takes_one_device_per_instant(self):
        response = self.query(self.base_body(follow_replacements=True))
        self.assertEqual(response.status_code, 200, response.content)
        series = response.json()["series"]

        # One logical series, not two.
        self.assertEqual(len(series), 1)
        values = sorted(point["value"] for point in series[0]["points"])

        # The two overlap readings are the ones that must not appear: 999 came
        # from hardware already retired, 888 from hardware not yet in service.
        self.assertEqual(values, [100.0, 200.0])
        self.assertNotIn(999.0, values)
        self.assertNotIn(888.0, values)

    def test_the_response_says_which_devices_were_folded_in(self):
        response = self.query(self.base_body(follow_replacements=True))
        series = response.json()["series"][0]
        self.assertCountEqual(
            series["device_ids"], [str(self.old.id), str(self.new.id)]
        )

    def test_stitching_is_off_by_default(self):
        body = self.base_body()
        self.assertNotIn("follow_replacements", body)
        series = self.query(body).json()["series"][0]
        self.assertEqual(series["device_ids"], [str(self.old.id)])


class ReplacementApiTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.token = self.login("admin@acme-demo.com")
        self.site = factories.site(self.org)
        self.blueprint = factories.blueprint("rep-pcs", self.org)
        self.old = factories.device(
            self.org, "REP-OLD", site_obj=self.site, device_type=self.blueprint
        )
        self.asset = EnergyAsset.objects.create(
            organization=self.org,
            site=self.site,
            device=self.old,
            role=AssetRole.BATTERY,
            power_metric="battery_power_w",
        )
        self.rule = AlertRule.objects.create(
            organization=self.org,
            name="High power",
            scope=RuleScope.DEVICE,
            metric_key="battery_power_w",
            threshold=1000.0,
        )
        self.rule.devices.add(self.old)

    def replace(self, **extra):
        return self.post(
            f"{API}/devices/{self.old.id}/replace",
            self.token,
            {"device_id": "REP-NEW", "name": "Replacement PCS", **extra},
        )

    def test_a_replacement_moves_everything_and_retires_the_old_one(self):
        response = self.replace()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["moved_asset_count"], 1)
        self.assertEqual(body["moved_alert_rule_count"], 1)

        new = Device.objects.get(device_id="REP-NEW")
        self.old.refresh_from_db()

        self.assertEqual(self.old.commissioning_state, LifecycleState.RETIRED)
        self.assertEqual(self.old.replaced_by_id, new.pk)
        self.assertIsNotNone(self.old.retired_at)
        self.assertFalse(self.old.is_enabled)

        self.asset.refresh_from_db()
        self.assertEqual(self.asset.device_id, new.pk)
        self.assertIn(new, self.rule.devices.all())
        self.assertNotIn(self.old, self.rule.devices.all())

    def test_the_replacement_inherits_the_site_and_blueprint(self):
        self.replace()
        new = Device.objects.get(device_id="REP-NEW")
        self.assertEqual(new.site_id, self.site.id)
        self.assertEqual(new.device_type_id, self.blueprint.id)
        self.assertEqual(new.commissioning_state, LifecycleState.ACTIVE)

    def test_credentials_are_issued_once(self):
        body = self.replace().json()
        self.assertIsNotNone(body["credential"]["mqtt_password"])

    def test_reusing_an_existing_device_id_is_refused(self):
        response = self.replace(device_id=self.old.device_id)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "device_id_taken")

    def test_replacing_twice_is_refused(self):
        self.replace()
        response = self.replace(device_id="REP-THIRD")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "device_already_retired")

    def test_the_replacement_is_audited(self):
        self.replace()
        self.assertTrue(
            AuditLog.objects.filter(action=AuditAction.DEVICE_REPLACED).exists()
        )

    def test_a_viewer_cannot_replace(self):
        response = self.post(
            f"{API}/devices/{self.old.id}/replace",
            self.login("view@acme-demo.com"),
            {"device_id": "REP-X", "name": "x"},
        )
        self.assertEqual(response.status_code, 403)


class RestoreApiTests(ApiTestCase):
    """Hardware comes back. So must the row - but not into a conflict."""

    def setUp(self) -> None:
        super().setUp()
        self.token = self.login("admin@acme-demo.com")
        self.old = factories.device(self.org, "BACK-OLD")
        self.new = factories.device(self.org, "BACK-NEW")
        self.old.replaced_by = self.new
        self.old.commissioning_state = LifecycleState.RETIRED
        self.old.retired_at = now()
        self.old.is_enabled = False
        self.old.save()

    def set_state(self, device, state):
        return self.post(
            f"{API}/devices/{device.id}/lifecycle", self.token, {"state": state}
        )

    def test_restoring_while_the_successor_is_in_service_is_refused(self):
        response = self.set_state(self.old, "active")
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "successor_still_active")

    def test_restoring_works_once_the_successor_steps_aside(self):
        self.set_state(self.new, "retired")
        response = self.set_state(self.old, "active")
        self.assertEqual(response.status_code, 200, response.content)

        self.old.refresh_from_db()
        self.assertEqual(self.old.commissioning_state, LifecycleState.ACTIVE)
        self.assertTrue(self.old.is_enabled)
        # It is current equipment again, so it has no successor and no
        # retirement date - otherwise a stitched report would clip it.
        self.assertIsNone(self.old.replaced_by_id)
        self.assertIsNone(self.old.retired_at)

    def test_the_successors_id_is_never_the_obstacle(self):
        # device_id is unique platform-wide and a retired device keeps its own,
        # so restoring can never collide with the replacement.
        self.set_state(self.new, "retired")
        self.set_state(self.old, "active")
        self.assertTrue(Device.objects.filter(device_id="BACK-NEW").exists())
        self.assertTrue(Device.objects.filter(device_id="BACK-OLD").exists())

    def test_restoring_is_audited(self):
        self.set_state(self.new, "retired")
        self.set_state(self.old, "active")
        self.assertTrue(
            AuditLog.objects.filter(action=AuditAction.DEVICE_RESTORED).exists()
        )

    def test_a_retired_device_is_still_visible_in_the_api(self):
        response = self.get(f"{API}/devices/{self.old.id}", self.token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["commissioning_state"], "retired")

    def test_a_viewer_cannot_change_lifecycle(self):
        response = self.post(
            f"{API}/devices/{self.old.id}/lifecycle",
            self.login("view@acme-demo.com"),
            {"state": "active"},
        )
        self.assertEqual(response.status_code, 403)
