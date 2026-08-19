"""API surface: authentication, RBAC, tenant isolation, commands, queries."""

from __future__ import annotations

import datetime as dt
from unittest import mock

import orjson
from django.core.cache import cache
from django.test import Client, TestCase

from apps.accounts.models import Role
from apps.core.timeutils import now
from apps.devices.models import Command, CommandStatus, Device
from apps.telemetry.models import LatestSample, TelemetrySample
from tests import factories

API = "/api"


class ApiTestCase(TestCase):
    """Shared helpers: JSON requests with a bearer token and an org header."""

    def setUp(self) -> None:
        # Login throttling is cache-backed and the locmem cache outlives a
        # single test, so clear it or later tests hit the rate limit.
        cache.clear()
        self.client = Client()
        self.org = factories.organization("acme")
        self.other_org = factories.organization("rival")

        self.admin, _ = factories.member(self.org, Role.ADMIN, email="admin@acme-demo.com")
        self.operator, _ = factories.member(
            self.org, Role.OPERATOR, email="op@acme-demo.com"
        )
        self.viewer, _ = factories.member(self.org, Role.VIEWER, email="view@acme-demo.com")
        self.password = "TestPassw0rd!23"

    # ---- request helpers -------------------------------------------------
    def login(self, email: str) -> str:
        response = self.client.post(
            f"{API}/auth/login",
            data=orjson.dumps({"email": email, "password": self.password}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["access_token"]

    def call(self, method: str, path: str, token: str = "", body=None, **extra):
        headers = {}
        if token:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        headers.update(extra)
        kwargs = {"content_type": "application/json", **headers}
        if body is not None:
            kwargs["data"] = orjson.dumps(body)
        return getattr(self.client, method)(path, **kwargs)

    def get(self, path, token="", **extra):
        return self.call("get", path, token, None, **extra)

    def post(self, path, token="", body=None, **extra):
        return self.call("post", path, token, body if body is not None else {}, **extra)

    def patch(self, path, token="", body=None, **extra):
        return self.call("patch", path, token, body or {}, **extra)

    def delete(self, path, token="", **extra):
        return self.call("delete", path, token, None, **extra)


class AuthTestCase(ApiTestCase):
    def test_login_returns_a_token_pair(self):
        response = self.client.post(
            f"{API}/auth/login",
            data=orjson.dumps({"email": "admin@acme-demo.com", "password": self.password}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("access_token", body)
        self.assertIn("refresh_token", body)
        self.assertGreater(body["expires_in"], 0)

    def test_wrong_password_is_rejected_with_a_stable_code(self):
        response = self.client.post(
            f"{API}/auth/login",
            data=orjson.dumps({"email": "admin@acme-demo.com", "password": "nope"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credentials")

    def test_missing_authorization_is_401(self):
        self.assertEqual(self.get(f"{API}/devices").status_code, 401)

    def test_me_reports_role_and_permissions(self):
        token = self.login("op@acme-demo.com")
        body = self.get(f"{API}/auth/me", token).json()
        self.assertEqual(body["role"], Role.OPERATOR)
        self.assertIn("device:command", body["permissions"])
        self.assertNotIn("device:write", body["permissions"])

    def test_refresh_rotates_and_invalidates_the_old_token(self):
        login = self.client.post(
            f"{API}/auth/login",
            data=orjson.dumps({"email": "admin@acme-demo.com", "password": self.password}),
            content_type="application/json",
        ).json()

        rotated = self.client.post(
            f"{API}/auth/refresh",
            data=orjson.dumps({"refresh_token": login["refresh_token"]}),
            content_type="application/json",
        )
        self.assertEqual(rotated.status_code, 200)

        # Replaying the spent token is treated as theft.
        replay = self.client.post(
            f"{API}/auth/refresh",
            data=orjson.dumps({"refresh_token": login["refresh_token"]}),
            content_type="application/json",
        )
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(replay.json()["error"]["code"], "token_reuse_detected")

    def test_preferences_round_trip(self):
        token = self.login("view@acme-demo.com")
        response = self.patch(
            f"{API}/auth/me/preferences",
            token,
            {"theme": "dark", "language": "zh-hant", "timezone_name": "Asia/Taipei"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["theme"], "dark")
        self.assertEqual(body["language"], "zh-hant")

    def test_unsupported_language_is_rejected(self):
        token = self.login("view@acme-demo.com")
        response = self.patch(f"{API}/auth/me/preferences", token, {"language": "kl"})
        self.assertEqual(response.status_code, 422)


class RbacTestCase(ApiTestCase):
    def test_viewer_cannot_create_a_site(self):
        token = self.login("view@acme-demo.com")
        response = self.post(f"{API}/sites", token, {"name": "HQ", "code": "hq"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "permission_denied")

    def test_admin_can_create_a_site(self):
        token = self.login("admin@acme-demo.com")
        response = self.post(f"{API}/sites", token, {"name": "HQ", "code": "hq"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["code"], "hq")

    def test_operator_cannot_register_a_device(self):
        token = self.login("op@acme-demo.com")
        response = self.post(
            f"{API}/devices", token, {"device_id": "NEW-0001", "name": "New"}
        )
        self.assertEqual(response.status_code, 403)

    def test_duplicate_site_code_conflicts(self):
        token = self.login("admin@acme-demo.com")
        self.post(f"{API}/sites", token, {"name": "HQ", "code": "hq"})
        response = self.post(f"{API}/sites", token, {"name": "HQ2", "code": "hq"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "code_taken")


class DeviceApiTestCase(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.site = factories.site(self.org)
        self.blueprint = factories.blueprint(org=self.org)
        self.device = factories.device(
            self.org, "API-0001", site_obj=self.site, device_type=self.blueprint
        )
        self.token = self.login("admin@acme-demo.com")

    def test_registration_returns_credentials_once(self):
        response = self.post(
            f"{API}/devices",
            self.token,
            {"device_id": "API-0002", "name": "Second", "site_id": str(self.site.id)},
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["credential"]["mqtt_password"])
        self.assertEqual(body["device"]["device_id"], "API-0002")

    def test_duplicate_device_id_conflicts(self):
        response = self.post(
            f"{API}/devices", self.token, {"device_id": "API-0001", "name": "Clash"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "device_id_taken")

    def test_devices_from_another_tenant_are_invisible(self):
        stranger = factories.device(self.other_org, "OTHER-0001")
        listing = self.get(f"{API}/devices", self.token).json()
        self.assertEqual(listing["total"], 1)

        response = self.get(f"{API}/devices/{stranger.id}", self.token)
        self.assertEqual(response.status_code, 404)

    def test_map_falls_back_to_the_site_location(self):
        points = self.get(f"{API}/devices/map", self.token).json()
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["source"], "site")
        self.assertAlmostEqual(points[0]["latitude"], 25.0)

    def test_map_prefers_the_device_reported_location(self):
        Device.objects.filter(pk=self.device.pk).update(
            latitude=24.1, longitude=120.6, location_source="device"
        )
        points = self.get(f"{API}/devices/map", self.token).json()
        self.assertEqual(points[0]["source"], "device")
        self.assertAlmostEqual(points[0]["latitude"], 24.1)

    def test_detail_includes_latest_values_and_commands(self):
        LatestSample.objects.create(
            organization=self.org,
            device=self.device,
            metric_key="battery_soc",
            ts=now(),
            value=64.0,
        )
        body = self.get(f"{API}/devices/{self.device.id}", self.token).json()
        self.assertEqual(len(body["latest"]), 1)
        self.assertAlmostEqual(body["latest"][0]["value"], 64.0)
        self.assertEqual(body["available_commands"][0]["name"], "set_power_limit")

    def test_search_filter(self):
        factories.device(self.org, "API-9999", name="Rooftop inverter")
        body = self.get(f"{API}/devices?q=Rooftop", self.token).json()
        self.assertEqual(body["total"], 1)


class CommandApiTestCase(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.blueprint = factories.blueprint(org=self.org)
        self.device = factories.device(self.org, "CMD-0001", device_type=self.blueprint)
        self.token = self.login("op@acme-demo.com")

    def test_command_is_persisted_and_published(self):
        with mock.patch("apps.devices.services.publish_json") as publish:
            response = self.post(
                f"{API}/devices/{self.device.id}/commands",
                self.token,
                {"name": "set_power_limit", "params": {"limit_w": 500}},
            )

        self.assertEqual(response.status_code, 202, response.content)
        publish.assert_called_once()
        topic, payload = publish.call_args[0]
        self.assertEqual(topic, f"energy/devices/{self.device.device_id}/control")
        self.assertEqual(payload["name"], "set_power_limit")
        self.assertEqual(payload["params"], {"limit_w": 500})

        command = Command.objects.get()
        self.assertEqual(command.status, CommandStatus.SENT)
        self.assertEqual(command.issued_by, self.operator)

    def test_unknown_command_is_rejected(self):
        with mock.patch("apps.devices.services.publish_json") as publish:
            response = self.post(
                f"{API}/devices/{self.device.id}/commands",
                self.token,
                {"name": "self_destruct"},
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unknown_command")
        publish.assert_not_called()

    def test_parameter_out_of_range_is_rejected(self):
        with mock.patch("apps.devices.services.publish_json"):
            response = self.post(
                f"{API}/devices/{self.device.id}/commands",
                self.token,
                {"name": "set_power_limit", "params": {"limit_w": 99999}},
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "parameter_out_of_range")
        self.assertEqual(Command.objects.count(), 0)

    def test_missing_required_parameter_is_rejected(self):
        with mock.patch("apps.devices.services.publish_json"):
            response = self.post(
                f"{API}/devices/{self.device.id}/commands",
                self.token,
                {"name": "set_power_limit", "params": {}},
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "missing_parameter")

    def test_idempotency_key_returns_the_original_command(self):
        body = {
            "name": "set_power_limit",
            "params": {"limit_w": 100},
            "idempotency_key": "abc-123",
        }
        with mock.patch("apps.devices.services.publish_json") as publish:
            first = self.post(f"{API}/devices/{self.device.id}/commands", self.token, body)
            second = self.post(f"{API}/devices/{self.device.id}/commands", self.token, body)

        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(Command.objects.count(), 1)
        self.assertEqual(publish.call_count, 1)

    def test_broker_failure_records_a_failed_command(self):
        from services.mqtt.publisher import PublishError

        with mock.patch(
            "apps.devices.services.publish_json", side_effect=PublishError("down")
        ):
            response = self.post(
                f"{API}/devices/{self.device.id}/commands",
                self.token,
                {"name": "set_power_limit", "params": {"limit_w": 100}},
            )

        self.assertEqual(response.status_code, 503)
        command = Command.objects.get()
        self.assertEqual(command.status, CommandStatus.FAILED)
        self.assertIn("down", command.error)

    def test_viewer_cannot_send_commands(self):
        token = self.login("view@acme-demo.com")
        response = self.post(
            f"{API}/devices/{self.device.id}/commands",
            token,
            {"name": "set_power_limit", "params": {"limit_w": 100}},
        )
        self.assertEqual(response.status_code, 403)


class TelemetryApiTestCase(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.device = factories.device(self.org, "TLM-0001")
        self.token = self.login("view@acme-demo.com")
        self.base = now().replace(microsecond=0) - dt.timedelta(minutes=30)

        TelemetrySample.objects.bulk_create(
            [
                TelemetrySample(
                    organization=self.org,
                    device=self.device,
                    metric_key="battery_soc",
                    ts=self.base + dt.timedelta(seconds=index * 10),
                    value=50.0 + index,
                )
                for index in range(60)
            ]
        )

    def test_raw_series_for_a_short_window(self):
        response = self.post(
            f"{API}/telemetry/series",
            self.token,
            {
                "device_ids": [str(self.device.id)],
                "metrics": ["battery_soc"],
                "start": self.base.isoformat(),
                "end": (self.base + dt.timedelta(minutes=10)).isoformat(),
                "max_points": 5000,
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertFalse(body["downsampled"])
        self.assertEqual(len(body["series"]), 1)
        self.assertEqual(len(body["series"][0]["points"]), 60)

    def test_long_window_is_downsampled(self):
        response = self.post(
            f"{API}/telemetry/series",
            self.token,
            {
                "device_ids": [str(self.device.id)],
                "metrics": ["battery_soc"],
                "start": self.base.isoformat(),
                "end": (self.base + dt.timedelta(minutes=10)).isoformat(),
                "max_points": 10,
            },
        )
        body = response.json()
        self.assertTrue(body["downsampled"])
        self.assertLessEqual(len(body["series"][0]["points"]), 10)
        point = body["series"][0]["points"][0]
        self.assertIn("min", point)
        self.assertIn("max", point)

    def test_series_for_another_tenant_is_refused(self):
        stranger = factories.device(self.other_org, "TLM-OTHER")
        response = self.post(
            f"{API}/telemetry/series",
            self.token,
            {"device_ids": [str(stranger.id)], "metrics": ["battery_soc"]},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "device_not_found")

    def test_metric_catalogue_includes_builtins(self):
        from apps.telemetry.models import Metric

        Metric.objects.create(
            organization=None, key="battery_soc", display_name="State of charge", unit="%"
        )
        body = self.get(f"{API}/metrics", self.token).json()
        keys = {row["key"] for row in body}
        self.assertIn("battery_soc", keys)
        self.assertTrue(next(r for r in body if r["key"] == "battery_soc")["is_builtin"])


class ApiKeyTestCase(ApiTestCase):
    def test_api_key_authenticates_and_is_scoped(self):
        admin_token = self.login("admin@acme-demo.com")
        created = self.post(
            f"{API}/api-keys", admin_token, {"name": "BI export", "role": "viewer"}
        )
        self.assertEqual(created.status_code, 201, created.content)
        secret = created.json()["secret"]

        factories.device(self.org, "KEY-0001")
        response = self.client.get(
            f"{API}/devices", HTTP_AUTHORIZATION=f"ApiKey {secret}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)

        # A viewer-scoped key cannot write.
        write = self.client.post(
            f"{API}/sites",
            data=orjson.dumps({"name": "X", "code": "x"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"ApiKey {secret}",
        )
        self.assertEqual(write.status_code, 403)

    def test_revoked_key_is_refused(self):
        admin_token = self.login("admin@acme-demo.com")
        created = self.post(f"{API}/api-keys", admin_token, {"name": "temp"}).json()
        self.delete(f"{API}/api-keys/{created['key']['id']}", admin_token)

        response = self.client.get(
            f"{API}/devices", HTTP_AUTHORIZATION=f"ApiKey {created['secret']}"
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "api_key_expired")


class SystemApiTestCase(ApiTestCase):
    def test_capabilities_are_public(self):
        body = self.client.get(f"{API}/system/capabilities").json()
        codes = {row["code"] for row in body["languages"]}
        self.assertEqual(codes, {"en", "zh-hant", "zh-hans"})
        self.assertEqual(body["mqtt_topic_root"], "energy/devices")

    def test_fleet_counts(self):
        factories.device(self.org, "FLEET-1")
        factories.device(self.org, "FLEET-2")
        factories.device(self.other_org, "FLEET-3")
        token = self.login("view@acme-demo.com")
        body = self.get(f"{API}/system/fleet", token).json()
        self.assertEqual(body["total_devices"], 2)
