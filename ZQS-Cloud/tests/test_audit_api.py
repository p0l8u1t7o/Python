"""Audit endpoints, including the label serialisation that once broke them."""

from __future__ import annotations

import orjson
from django.core.cache import cache
from django.test import Client, TestCase

from apps.accounts.models import Role
from apps.audit.models import AuditAction, AuditLog
from tests import factories

API = "/api"


class AuditApiTestCase(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.client = Client()
        self.org = factories.organization("acme")
        self.admin, _ = factories.member(self.org, Role.ADMIN, email="admin@acme-demo.com")
        self.password = "TestPassw0rd!23"

        response = self.client.post(
            f"{API}/auth/login",
            data=orjson.dumps({"email": self.admin.email, "password": self.password}),
            content_type="application/json",
        )
        self.token = response.json()["access_token"]

    def get(self, path: str):
        return self.client.get(path, HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_action_vocabulary_serialises(self):
        """Choice labels are lazy translation proxies, not str.

        Returning the proxy directly makes pydantic reject the whole response,
        so every label has to be coerced before it leaves the view.
        """
        response = self.get(f"{API}/audit/actions")
        self.assertEqual(response.status_code, 200, response.content[:400])

        body = response.json()
        self.assertEqual(len(body), len(AuditAction.choices))
        for row in body:
            self.assertIsInstance(row["label"], str)
            self.assertTrue(row["label"])

    def test_login_is_recorded_and_listed_with_a_label(self):
        response = self.get(f"{API}/audit")
        self.assertEqual(response.status_code, 200, response.content[:400])

        body = response.json()
        self.assertGreaterEqual(body["total"], 1)
        entry = body["items"][0]
        self.assertEqual(entry["action"], AuditAction.LOGIN)
        self.assertIsInstance(entry["action_label"], str)
        self.assertEqual(entry["actor_label"], self.admin.email)

    def test_unknown_action_falls_back_to_the_raw_value(self):
        AuditLog.objects.create(
            organization=self.org, action="something.new", actor_label="tester"
        )
        body = self.get(f"{API}/audit?action=something.new").json()
        self.assertEqual(body["items"][0]["action_label"], "something.new")

    def test_device_trail_is_scoped_to_one_device(self):
        device = factories.device(self.org, "AUD-0001")
        AuditLog.objects.create(
            organization=self.org,
            action=AuditAction.DEVICE_UPDATED,
            target_type="device",
            target_id=str(device.id),
            target_label=device.name,
        )
        AuditLog.objects.create(
            organization=self.org,
            action=AuditAction.DEVICE_UPDATED,
            target_type="device",
            target_id=str(factories.device(self.org, "AUD-0002").id),
        )

        body = self.get(f"{API}/audit/devices/{device.id}").json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["target_id"], str(device.id))

    def test_secrets_are_redacted_before_being_stored(self):
        from apps.audit.services import record

        record(
            AuditAction.APIKEY_CREATED,
            organization=self.org,
            payload={"name": "key", "secret": "super-secret", "nested": {"password": "hunter2"}},
        )
        entry = AuditLog.objects.filter(action=AuditAction.APIKEY_CREATED).get()
        self.assertEqual(entry.payload["secret"], "***")
        self.assertEqual(entry.payload["nested"]["password"], "***")
        self.assertEqual(entry.payload["name"], "key")
