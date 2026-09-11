"""任務試執行摘要的持久化、權限與跨語言簽章回歸。"""

import copy
import json
import statistics
import time
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import AuthToken, EngineLock, RolePermission, UserPref
from apps.core.models import AuditLog
from apps.vision.api_inspect import inspection_graph_hash
from apps.vision.models import Flow, InspectionTrial


class InspectionTrialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.maker = User.objects.create_user("trial-maker", is_staff=True)
        cls.reader = User.objects.create_user("trial-reader")
        UserPref.objects.create(user=cls.reader, role="operator")
        cls.flow = Flow.objects.create(name="Trial", owner=cls.maker, graph={"nodes": [], "edges": []})

    def setUp(self):
        self.payload = {
            "graph": self.flow.graph, "status": "ok", "judge": "OK", "executed_at": "2026-09-11T04:00:00Z",
            "readings": [{"task_id": "diam", "status": "pass", "valid": True, "detected": True,
                          "value": 35.0124, "unit": "mm", "message": "Within tolerance", "node_id": "diam_tol"}],
        }

    def call(self, method="get", payload=None, user=None, flow_id=None):
        token = AuthToken.issue(user or self.maker)
        return getattr(self.client, method)(f"/api/vision/inspect/{flow_id or self.flow.pk}/last-trial",
                                           data=json.dumps(payload) if payload is not None else None,
                                           content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_cross_user_read_latest_only_and_cascade(self):
        self.assertEqual(self.call().json(), {"trial": None})
        self.assertEqual(self.call("put", self.payload).json(), {"saved": True})
        row = self.call(user=self.reader).json()["trial"]
        self.assertEqual(row["readings"], self.payload["readings"])
        self.assertEqual(row["hash"], inspection_graph_hash(self.flow.graph))
        self.assertEqual(row["executed_by"], self.maker.username)
        self.assertEqual(row["executed_at"], "2026-09-11T04:00:00+00:00")
        self.assertTrue(AuditLog.objects.filter(action="inspect.last_trial", target_id=str(self.flow.pk)).exists())
        newer = {**self.payload, "executed_at": "2026-09-11T04:00:01Z", "judge": "NG", "status": "ng"}
        self.assertEqual(self.call("put", newer, self.reader).json(), {"saved": True})
        self.assertEqual(self.call("put", self.payload).json(), {"saved": False})
        self.assertEqual(InspectionTrial.objects.count(), 1)
        self.assertEqual(self.call().json()["trial"]["status"], "ng")
        self.flow.delete()
        self.assertEqual(InspectionTrial.objects.count(), 0)

    def test_graph_edits_and_version_restore_keep_original_signature(self):
        self.call("put", self.payload)
        original = self.call().json()["trial"]["hash"]
        for graph in ({"nodes": [{"id": "new", "params": {"threshold": 46}}], "edges": []},
                      {"nodes": [{"id": "old", "params": {"threshold": 60}}], "edges": []}):
            Flow.objects.filter(pk=self.flow.pk).update(graph=graph)
            self.assertEqual(self.call().json()["trial"]["hash"], original)
            self.assertNotEqual(original, inspection_graph_hash(graph))

    def test_permissions_visibility_and_execution_lock(self):
        self.call("put", self.payload)
        path = f"/api/vision/inspect/{self.flow.pk}/last-trial"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.call(flow_id=999999).status_code, 404)
        RolePermission.objects.create(role="operator", features=["flows.edit"])
        self.assertEqual(self.call(user=self.reader).status_code, 403)
        self.assertEqual(self.call("put", self.payload, self.reader).status_code, 403)
        RolePermission.objects.filter(role="operator").update(features=["flows.run"])
        EngineLock.objects.update_or_create(pk=1, defaults={"locked": True, "holder": "another-user"})
        self.assertEqual(self.call(user=self.reader).status_code, 200)
        self.assertEqual(self.call("put", self.payload, self.reader).status_code, 423)
        with patch("apps.vision.api._visible_flows", return_value=Flow.objects.none()):
            self.assertEqual(self.call().status_code, 404)
            self.assertEqual(self.call("put", self.payload).status_code, 423)

    def test_rejects_images_nonfinite_and_duplicate_readings(self):
        for field, value in (("value", {"ref": "image"}), ("value", [1, 2]), ("value", True),
                             ("value", float("nan")), ("value", float("inf")), ("overlays", []),
                             ("message", "x" * 4001)):
            payload = copy.deepcopy(self.payload)
            payload["readings"][0][field] = value
            with self.subTest(field=field, value=str(value)[:20]):
                self.assertEqual(self.call("put", payload).status_code, 422)
        payload = copy.deepcopy(self.payload)
        payload["readings"] *= 2
        self.assertEqual(self.call("put", payload).status_code, 422)
        self.assertEqual(InspectionTrial.objects.count(), 0)

    def test_signature_exact_unicode_numbers_and_key_order(self):
        graph = {"nodes": [], "edges": [], "Z": [1.0, -0.0, 1e-7, 1e21], "a": "杯😀\n", "_": True}
        expected = 'v2:{"Z":[n:3ff0000000000000,n:0000000000000000,n:3e7ad7f29abcaf48,n:444b1ae4d6e2ef50],"_":true,"a":"\\u676f\\ud83d\\ude00\\n","edges":[],"nodes":[]}'
        self.assertEqual(inspection_graph_hash(graph), expected)
        self.assertEqual(inspection_graph_hash(dict(reversed(list(graph.items())))), expected)
        self.assertNotEqual(inspection_graph_hash({"n": 1}), inspection_graph_hash({"n": "n:3ff0000000000000"}))

    def test_preview_never_calls_summary_storage_and_measure_latency(self):
        # 真正 preview 端點；故意讓摘要儲存延遲，證明熱路徑完全不呼叫它。
        graph = {"nodes": [{"id": "f", "type": "formula", "params": {"expression": "1+2"}}], "edges": []}
        token = AuthToken.issue(self.maker)
        path = f"/api/vision/flows/{self.flow.pk}/preview"

        def preview():
            start = time.perf_counter()
            response = self.client.post(path, data=json.dumps({"graph": graph, "analysis": False}),
                                        content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
            self.assertEqual(response.status_code, 200, response.content)
            return (time.perf_counter() - start) * 1000

        preview()
        baseline = [preview() for _ in range(10)]
        with patch.object(InspectionTrial.objects, "update_or_create", side_effect=lambda **kw: time.sleep(0.25)) as write:
            delayed = [preview() for _ in range(10)]
            write.assert_not_called()
        self.assertFalse(InspectionTrial.objects.exists())
        print(f"Trial preview latency: baseline median={statistics.median(baseline):.3f} ms; "
              f"storage delayed 250 ms median={statistics.median(delayed):.3f} ms; storage calls=0")
