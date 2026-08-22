"""Registration rules, moving a device between sites, and per-user layouts.

Three of these guard against a silent wrong answer rather than a crash, which
is why they exist at all:

* a duplicate serial means the same physical unit was registered twice, and
  then its energy is counted twice with nothing raising anywhere;
* an energy binding left on the old site makes that site's balance depend on
  equipment that is no longer there, while the new site reads as unconfigured;
* an MQTT-less deployment reporting "cannot reach broker" trains people to
  ignore the health card, which is where a real outage would have shown up.
"""

from __future__ import annotations

from unittest import mock

import orjson
from django.test import Client, override_settings

from apps.accounts.models import UserPreference
from apps.devices.models import DeviceCategory
from apps.ems.models import AssetRole, EnergyAsset
from tests import factories
from tests.test_api import API, ApiTestCase


class SerialNumberTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.site = factories.site(self.org, "hq")
        self.first = factories.device(
            self.org, "SER-0001", site_obj=self.site, name="First", serial_number="SN-42"
        )
        self.token = self.login(self.admin.email)

    def test_registering_a_duplicate_serial_is_refused(self):
        response = self.post(
            f"{API}/devices",
            self.token,
            {"device_id": "SER-0002", "name": "Second", "serial_number": "SN-42"},
        )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "serial_number_taken")

    def test_the_error_names_the_device_that_already_has_it(self):
        """"Which one?" is the only question this error provokes."""
        response = self.post(
            f"{API}/devices",
            self.token,
            {"device_id": "SER-0003", "name": "Third", "serial_number": "SN-42"},
        )
        details = response.json()["error"]["details"]
        self.assertEqual(details["device_name"], "First")
        self.assertEqual(details["device_external_id"], "SER-0001")

    def test_editing_onto_a_taken_serial_is_refused(self):
        other = factories.device(self.org, "SER-0004", site_obj=self.site)
        response = self.patch(
            f"{API}/devices/{other.id}", self.token, {"serial_number": "SN-42"}
        )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "serial_number_taken")

    def test_a_device_may_keep_its_own_serial_when_edited(self):
        response = self.patch(
            f"{API}/devices/{self.first.id}",
            self.token,
            {"name": "Renamed", "serial_number": "SN-42"},
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_blank_serials_do_not_collide(self):
        """They are usually unknown at commissioning; a forced placeholder
        would defeat the constraint far more thoroughly."""
        for index in (5, 6):
            response = self.post(
                f"{API}/devices",
                self.token,
                {"device_id": f"SER-000{index}", "name": f"Blank {index}"},
            )
            self.assertEqual(response.status_code, 201, response.content)

    def test_another_tenant_may_hold_the_same_serial(self):
        """Two customers buying from one vendor legitimately share serials."""
        other_admin, _ = factories.member(self.other_org, "admin", email="o@x.com")
        token = self.login(other_admin.email)
        response = self.post(
            f"{API}/devices",
            token,
            {"device_id": "SER-9001", "name": "Theirs", "serial_number": "SN-42"},
        )
        self.assertEqual(response.status_code, 201, response.content)


class EnergyBindingFollowsDeviceTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.origin = factories.site(self.org, "origin", name="Origin")
        self.destination = factories.site(self.org, "destination", name="Destination")
        self.device = factories.device(
            self.org, "MOVE-ASSET", site_obj=self.origin, name="Meter"
        )
        self.asset = EnergyAsset.objects.create(
            organization=self.org,
            site=self.origin,
            device=self.device,
            role=AssetRole.GRID_METER,
            power_metric="grid_power_w",
        )
        self.token = self.login(self.admin.email)

    def test_the_binding_moves_with_the_device(self):
        response = self.patch(
            f"{API}/devices/{self.device.id}",
            self.token,
            {"site_id": str(self.destination.id)},
        )
        self.assertEqual(response.status_code, 200, response.content)

        self.asset.refresh_from_db()
        self.assertEqual(self.asset.site_id, self.destination.id)

    def test_the_destination_site_reports_the_asset_afterwards(self):
        """This is the symptom: the new site said "no energy assets bound"."""
        self.patch(
            f"{API}/devices/{self.device.id}",
            self.token,
            {"site_id": str(self.destination.id)},
        )
        assets = self.get(
            f"{API}/ems/assets?site_id={self.destination.id}", self.token
        ).json()
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["device_id"], str(self.device.id))

        # ...and the site it left no longer claims it.
        left_behind = self.get(
            f"{API}/ems/assets?site_id={self.origin.id}", self.token
        ).json()
        self.assertEqual(left_behind, [])

    def test_the_move_is_recorded_in_the_audit_entry(self):
        from apps.audit.models import AuditLog

        self.patch(
            f"{API}/devices/{self.device.id}",
            self.token,
            {"site_id": str(self.destination.id)},
        )
        entry = AuditLog.objects.filter(action="device.updated").latest("created_at")
        self.assertIn("energy_bindings", entry.payload)

    def test_detaching_the_device_deactivates_the_binding(self):
        """It has nowhere to follow the device to, and it must stop feeding a
        balance the device is no longer part of."""
        self.patch(f"{API}/devices/{self.device.id}", self.token, {"site_id": None})
        self.asset.refresh_from_db()
        self.assertFalse(self.asset.is_active)

    def test_an_unrelated_edit_leaves_bindings_alone(self):
        self.patch(f"{API}/devices/{self.device.id}", self.token, {"name": "Renamed"})
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.site_id, self.origin.id)
        self.assertTrue(self.asset.is_active)


class HealthReportingTests(ApiTestCase):
    """A dependency this deployment does not use is not a fault."""

    def test_mqtt_reads_as_disabled_rather_than_broken(self):
        mqtt = {**self.settings_mqtt(), "ENABLED": False}
        with override_settings(MQTT=mqtt):
            body = Client().get(f"{API}/system/health").json()

        component = next(c for c in body["components"] if c["name"] == "mqtt")
        self.assertEqual(component["state"], "disabled")
        self.assertTrue(component["ok"])
        self.assertFalse(component["required"])

    def test_an_enabled_but_unreachable_broker_is_still_an_error(self):
        mqtt = {**self.settings_mqtt(), "ENABLED": True}
        with override_settings(MQTT=mqtt), mock.patch(
            "services.mqtt.publisher.get_publisher",
            side_effect=ConnectionError("refused"),
        ):
            body = Client().get(f"{API}/system/health").json()

        component = next(c for c in body["components"] if c["name"] == "mqtt")
        self.assertEqual(component["state"], "error")
        self.assertFalse(component["ok"])

    def test_a_disabled_dependency_does_not_drag_the_verdict_down(self):
        mqtt = {**self.settings_mqtt(), "ENABLED": False}
        with override_settings(MQTT=mqtt, BUS_BACKEND="memory"):
            body = Client().get(f"{API}/system/health").json()
        self.assertEqual(body["status"], "ok")

    @staticmethod
    def settings_mqtt() -> dict:
        from django.conf import settings

        return dict(settings.MQTT)


class UiPreferenceTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.token = self.login(self.admin.email)

    def put(self, key: str, value: dict):
        return self.client.put(
            f"{API}/auth/me/ui/{key}",
            data=orjson.dumps({"value": value}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    def test_an_unset_key_returns_an_empty_value_not_404(self):
        """First visit is the normal case, not an error every caller must
        write a try/catch for."""
        response = self.get(f"{API}/auth/me/ui/dashboard-view", self.token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["value"], {})

    def test_a_layout_round_trips(self):
        self.assertEqual(self.put("dashboard-view", {"view": "energy"}).status_code, 200)
        body = self.get(f"{API}/auth/me/ui/dashboard-view", self.token).json()
        self.assertEqual(body["value"], {"view": "energy"})

    def test_preferences_are_per_user(self):
        self.put("dashboard-view", {"view": "energy"})
        other = self.login(self.viewer.email)
        body = self.get(f"{API}/auth/me/ui/dashboard-view", other).json()
        self.assertEqual(body["value"], {})

    def test_keys_are_namespaced_and_validated(self):
        self.assertEqual(self.put("device-metrics:abc-123", {"keys": []}).status_code, 200)
        self.assertEqual(self.put("Not A Key", {}).status_code, 422)

    def test_listing_can_be_filtered_by_prefix(self):
        self.put("device-metrics:one", {"keys": ["a"]})
        self.put("device-metrics:two", {"keys": ["b"]})
        self.put("dashboard-view", {"view": "fleet"})
        rows = self.get(f"{API}/auth/me/ui?prefix=device-metrics:", self.token).json()
        self.assertEqual(len(rows), 2)

    def test_an_oversized_value_is_refused(self):
        response = self.put("device-metrics:big", {"keys": ["x" * 20_000]})
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.json()["error"]["code"], "preference_too_large")

    def test_clearing_falls_back_to_the_default(self):
        self.put("dashboard-view", {"view": "energy"})
        self.delete(f"{API}/auth/me/ui/dashboard-view", self.token)
        self.assertFalse(UserPreference.objects.filter(key="dashboard-view").exists())


class BlueprintCatalogueTests(ApiTestCase):
    """The blueprint picker is where somebody learns what a PCS is."""

    def test_descriptions_come_back_in_the_readers_language(self):
        from apps.devices.models import DeviceType

        DeviceType.objects.create(
            organization=self.org,
            key="acme-bess",
            name="ACME BESS",
            category=DeviceCategory.BATTERY,
            description="A battery.",
            translations={"zh-hant": {"description": "一組電池。"}},
        )
        self.admin.language = "zh-hant"
        self.admin.save(update_fields=["language"])

        token = self.login(self.admin.email)
        blueprint = next(
            item
            for item in self.get(f"{API}/blueprints", token).json()
            if item["key"] == "acme-bess"
        )
        self.assertEqual(blueprint["description_text"], "一組電池。")
        # The stored English is still there, so an editor round-trips.
        self.assertEqual(blueprint["description"], "A battery.")

    def test_an_untranslated_blueprint_falls_back_to_english(self):
        from apps.devices.models import DeviceType

        DeviceType.objects.create(
            organization=self.org,
            key="plain",
            name="Plain",
            category=DeviceCategory.METER,
            description="Just a meter.",
        )
        self.admin.language = "zh-hant"
        self.admin.save(update_fields=["language"])

        token = self.login(self.admin.email)
        blueprint = next(
            item
            for item in self.get(f"{API}/blueprints", token).json()
            if item["key"] == "plain"
        )
        self.assertEqual(blueprint["description_text"], "Just a meter.")


class InvestmentTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.site = factories.site(self.org, "hq")
        self.priced = factories.device(
            self.org,
            "COST-1",
            site_obj=self.site,
            name="Battery",
            capital_cost=1_000_000.0,
            cost_currency="TWD",
            expected_life_years=10.0,
            annual_maintenance_cost=20_000.0,
        )
        self.unpriced = factories.device(
            self.org, "COST-2", site_obj=self.site, name="Meter"
        )
        self.token = self.login(self.admin.email)

    def test_annual_cost_is_amortised_capital_plus_upkeep(self):
        self.assertAlmostEqual(self.priced.annual_cost, 120_000.0)

    def test_a_device_with_no_cost_recorded_reads_as_unknown_not_free(self):
        """Zero would quietly make every payback figure look wonderful."""
        self.assertIsNone(self.unpriced.annual_cost)

    def test_the_site_summary_counts_what_it_does_not_know(self):
        body = self.get(f"{API}/ems/sites/{self.site.id}/investment", self.token).json()
        self.assertEqual(body["total_capital_cost"], 1_000_000.0)
        self.assertEqual(body["total_annual_cost"], 120_000.0)
        self.assertEqual(body["devices_without_cost"], 1)
        self.assertEqual(body["currency"], "TWD")

    def test_the_battery_cost_model_derives_wear_from_the_purchase_price(self):
        """So an operator does not have to divide it out by hand - and so the
        default is not zero, which would make arbitrage look free."""
        from apps.ems import costs
        from apps.ems.tariffs import Price
        import datetime as dt

        from apps.core.timeutils import now

        asset = EnergyAsset(
            role=AssetRole.BATTERY,
            device=self.priced,
            cost_parameters={
                "warranted_throughput_kwh": 5_000_000.0,
                "charge_price_per_kwh": 0.0,
            },
        )
        start = now()
        result = costs.compute(
            "battery_cycle",
            costs.CostContext(
                start=start,
                end=start + dt.timedelta(minutes=15),
                interval_seconds=900,
                energy_kwh=100.0,
                price_at=lambda _m: Price("", 0.0, 0.0, "TWD"),
                asset=asset,
            ),
        )
        # 1,000,000 / 5,000,000 = 0.2 per kWh, over 100 kWh.
        self.assertAlmostEqual(result.breakdown["cycle_wear"], 20.0)
