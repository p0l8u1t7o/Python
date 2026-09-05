"""稽核軌跡：誰在什麼時候改了什麼。只記變更、不記執行。"""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from tests.fakes import MEMORY_KIND, register_memory_kind
from apps.accounts.models import AuthToken, UserPref
from apps.core import audit
from apps.core.models import AuditLog
from apps.vision.models import Flow, ImageSource

VISION = settings.VISION

register_memory_kind()


def graph(threshold: int = 60) -> dict:
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "params": {"source_id": 1}},
            {"id": "thr", "type": "threshold", "params": {"method": "fixed", "threshold": threshold}},
        ],
        "edges": [{"source": "src", "source_handle": "image", "target": "thr", "target_handle": "image"}],
    }


class AuditHelperTests(TestCase):
    def test_clip_keeps_rows_small(self):
        big = {"text": "x" * 5000, "items": list(range(100)), "obj": object()}
        clipped = audit._clip(big)  # noqa: SLF001
        self.assertLessEqual(len(clipped["text"]), audit.MAX_CHARS + 1)
        self.assertEqual(len(clipped["items"]), audit.MAX_ITEMS)
        self.assertIsInstance(clipped["obj"], str)

    def test_fields_diff_and_summary(self):
        changes = audit.fields_diff({"a": 1, "b": "x"}, {"a": 2, "b": "x"}, ("a", "b"))
        self.assertEqual(changes, {"a": {"before": 1, "after": 2}})
        self.assertEqual(audit.summarize_fields(changes), "a: 1 → 2")

    def test_record_never_raises(self):
        self.assertIsNone(audit.record(None, "x" * 100, target=object(), detail=object()) and None)

    def test_purge_respects_zero_as_forever(self):
        audit.record(None, "flow.update")
        self.assertEqual(audit.purge(days=0), 0)
        self.assertEqual(AuditLog.objects.count(), 1)


@override_settings(VISION={**VISION, "PERSIST_RUNS": False})
class AuditTrailTests(TestCase):
    def setUp(self):
        self.source = ImageSource.objects.create(name="s", kind="synthetic", config={"width": 32, "height": 32})
        self.token = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret1"}),
                                      content_type="application/json").json()["token"]
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def _flow(self, name="audited"):
        r = self.client.post("/api/vision/flows", data=json.dumps({"name": name, "graph": graph(60)}),
                             content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["id"]

    def test_parameter_change_is_recorded_with_who_and_what(self):
        fid = self._flow()
        self.client.patch(f"/api/vision/flows/{fid}", data=json.dumps({"graph": graph(46)}),
                          content_type="application/json", **self.auth)
        row = AuditLog.objects.filter(action="flow.update").first()
        self.assertIsNotNone(row, "改了門檻卻沒有留下紀錄")
        self.assertEqual((row.actor_name, row.target_name), ("admin", "audited"))
        self.assertIn("threshold 60 → 46", row.summary)
        self.assertEqual(row.detail["params"][0], {"node": "thr", "type": "threshold", "param": "threshold", "before": 60, "after": 46})
        self.assertTrue(row.ip)

    def test_settings_and_lifecycle_are_recorded(self):
        fid = self._flow("lifecycle")
        self.client.patch(f"/api/vision/flows/{fid}", data=json.dumps({"is_enabled": False}), content_type="application/json", **self.auth)
        self.client.delete(f"/api/vision/flows/{fid}", **self.auth)
        actions = list(AuditLog.objects.values_list("action", flat=True))
        self.assertIn("flow.create", actions)
        self.assertIn("flow.settings", actions)
        self.assertIn("flow.delete", actions)
        settings_row = AuditLog.objects.get(action="flow.settings")
        self.assertIn("is_enabled", settings_row.detail)

    def test_change_over_and_recipes_are_recorded(self):
        fid = self._flow("changeover")
        rid = self.client.post(f"/api/vision/flows/{fid}/recipes", data=json.dumps({"name": "partB", "param_overrides": {}}),
                               content_type="application/json", **self.auth).json()["id"]
        self.client.post(f"/api/vision/flows/{fid}/recipes/{rid}/activate", **self.auth)
        self.assertIn("recipe.create", AuditLog.objects.values_list("action", flat=True))
        row = AuditLog.objects.get(action="recipe.activate")
        self.assertIn("partB", row.summary)

    def test_runs_are_not_audited(self):
        """執行已經有 FlowRun 與統計；記進稽核只會把真正的變更沖掉。"""
        fid = self._flow("runs")
        AuditLog.objects.all().delete()
        for _ in range(3):
            self.client.post(f"/api/vision/flows/{fid}/run", data="{}", content_type="application/json", **self.auth)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_accounts_and_lock_are_recorded(self):
        self.client.post("/api/users", data=json.dumps({"username": "bob", "password": "pass123", "role": "operator"}),
                         content_type="application/json", **self.auth)
        uid = User.objects.get(username="bob").id
        self.client.patch(f"/api/users/{uid}", data=json.dumps({"role": "engineer"}), content_type="application/json", **self.auth)
        self.client.post("/api/vision/lock", data=json.dumps({"reason": "production"}), content_type="application/json", **self.auth)
        self.client.delete("/api/vision/lock", **self.auth)
        actions = list(AuditLog.objects.values_list("action", flat=True))
        for expected in ("user.create", "user.update", "lock.acquire", "lock.release"):
            self.assertIn(expected, actions)
        self.assertIn("role", AuditLog.objects.get(action="user.update").detail)

    def test_connection_changes_are_recorded(self):
        r = self.client.post("/api/vision/connections", data=json.dumps({"name": "plc", "kind": MEMORY_KIND, "config": {"channels": ["DO0"]}}),
                             content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()["id"]
        self.client.patch(f"/api/vision/connections/{cid}", data=json.dumps({"is_enabled": False}), content_type="application/json", **self.auth)
        self.client.delete(f"/api/vision/connections/{cid}", **self.auth)
        actions = list(AuditLog.objects.values_list("action", flat=True))
        for expected in ("connection.create", "connection.update", "connection.delete"):
            self.assertIn(expected, actions)

    def test_operator_edits_are_attributed_to_the_operator(self):
        fid = self._flow("byop")
        op = User.objects.create_user("op", password="x")
        UserPref.objects.create(user=op, role="operator")
        h = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(op)}"}
        r = self.client.patch(f"/api/vision/flows/{fid}", data=json.dumps({"graph": graph(70)}), content_type="application/json", **h)
        self.assertEqual(r.status_code, 200, r.content)
        row = AuditLog.objects.filter(action="flow.update").first()
        self.assertEqual(row.actor_name, "op")
        self.assertIn("threshold 60 → 70", row.summary)

    def test_api_lists_filters_and_exports(self):
        fid = self._flow("listing")
        self.client.patch(f"/api/vision/flows/{fid}", data=json.dumps({"graph": graph(46)}), content_type="application/json", **self.auth)
        body = self.client.get("/api/vision/audit", **self.auth).json()
        self.assertGreaterEqual(body["total"], 2)
        self.assertIn("flow.update", body["actions"])
        self.assertIn("admin", body["actors"])
        only = self.client.get("/api/vision/audit?action=flow.update", **self.auth).json()
        self.assertEqual({i["action"] for i in only["items"]}, {"flow.update"})
        self.assertEqual(self.client.get("/api/vision/audit?q=listing", **self.auth).json()["total"], 2)
        csv = self.client.get(f"/api/vision/audit.csv?token={self.token}")
        self.assertEqual(csv.status_code, 200)
        text = b"".join(csv.streaming_content).decode("utf-8")
        self.assertTrue(text.startswith("﻿"), "Excel 需要 BOM 才不會亂碼")
        self.assertIn("flow.update", text)

    def test_audit_is_admin_only(self):
        eng = User.objects.create_user("eng", password="x")
        h = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(eng)}"}
        self.assertEqual(self.client.get("/api/vision/audit", **h).status_code, 403)
        self.assertEqual(self.client.get("/api/vision/audit").status_code, 401)

    def test_purge_by_age(self):
        from datetime import timedelta

        from django.utils import timezone

        self._flow("purged")
        AuditLog.objects.update(at=timezone.now() - timedelta(days=800))
        self.assertGreater(audit.purge(days=730), 0)
        self.assertEqual(AuditLog.objects.count(), 0)
        _ = Flow
