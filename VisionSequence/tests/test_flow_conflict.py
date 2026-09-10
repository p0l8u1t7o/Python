"""流程儲存版本衝突：基準時間過期時不得覆蓋目前圖。"""

from __future__ import annotations

import copy
import json

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import AuthToken, UserPref
from apps.core.models import AuditLog
from apps.vision.models import Flow, ImageSource


def graph(source_id: int, threshold: int = 60) -> dict:
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "params": {"source_id": source_id}},
            {"id": "thr", "type": "threshold", "params": {"method": "fixed", "threshold": threshold}},
        ],
        "edges": [{"source": "src", "source_handle": "image", "target": "thr", "target_handle": "image"}],
    }


def set_threshold(g: dict, value: int) -> dict:
    out = copy.deepcopy(g)
    next(n for n in out["nodes"] if n["id"] == "thr")["params"]["threshold"] = value
    return out


class FlowConflictTests(TestCase):
    def setUp(self) -> None:
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})
        self.admin = User.objects.create_user("admin", password="x", is_staff=True)
        self.alice = User.objects.create_user("alice", password="x")
        self.operator = User.objects.create_user("op", password="x")
        UserPref.objects.create(user=self.operator, role="operator")
        self.admin_auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(self.admin)}"}
        self.alice_auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(self.alice)}"}
        self.operator_auth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(self.operator)}"}

    def _create_flow(self, name: str = "flow") -> dict:
        response = self.client.post(
            "/api/vision/flows",
            data=json.dumps({"name": name, "graph": graph(self.source.id)}),
            content_type="application/json",
            **self.admin_auth,
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def _patch(self, flow_id: int, body: dict, auth: dict | None = None):
        return self.client.patch(
            f"/api/vision/flows/{flow_id}",
            data=json.dumps(body),
            content_type="application/json",
            **(auth or self.admin_auth),
        )

    def test_stale_expected_updated_at_returns_409_with_current_graph_and_does_not_audit(self):
        flow = self._create_flow()
        stale = flow["updated_at"]
        server_graph = set_threshold(flow["graph"], 70)
        first = self._patch(flow["id"], {"graph": server_graph, "expected_updated_at": stale}, self.alice_auth)
        self.assertEqual(first.status_code, 200, first.content)
        audit_count = AuditLog.objects.filter(action="flow.update", target_id=str(flow["id"])).count()

        mine = set_threshold(flow["graph"], 80)
        conflict = self._patch(flow["id"], {"graph": mine, "expected_updated_at": stale})
        self.assertEqual(conflict.status_code, 409, conflict.content)
        error = conflict.json()["error"]
        self.assertEqual(error["code"], "version_conflict")
        self.assertEqual(error["details"]["version"], 2)
        self.assertEqual(error["details"]["graph"], server_graph)
        self.assertEqual(error["details"]["last_saved_by"]["name"], "alice")
        self.assertEqual(AuditLog.objects.filter(action="flow.update", target_id=str(flow["id"])).count(), audit_count)
        self.assertEqual(Flow.objects.get(pk=flow["id"]).graph, server_graph)

    def test_correct_expected_updated_at_saves_and_returns_new_baseline(self):
        flow = self._create_flow()
        changed = set_threshold(flow["graph"], 71)
        response = self._patch(flow["id"], {"graph": changed, "expected_updated_at": flow["updated_at"]})
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["version"], 2)
        self.assertEqual(body["graph"], changed)
        self.assertNotEqual(body["updated_at"], flow["updated_at"])

    def test_omitting_expected_updated_at_keeps_legacy_overwrite_behavior(self):
        flow = self._create_flow()
        changed = set_threshold(flow["graph"], 72)
        response = self._patch(flow["id"], {"graph": changed})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["graph"], changed)

    def test_two_users_cross_save_then_overwrite_with_fresh_server_baseline(self):
        flow = self._create_flow()
        alice_graph = set_threshold(flow["graph"], 73)
        saved_by_alice = self._patch(flow["id"], {"graph": alice_graph, "expected_updated_at": flow["updated_at"]}, self.alice_auth)
        self.assertEqual(saved_by_alice.status_code, 200, saved_by_alice.content)

        admin_graph = set_threshold(flow["graph"], 74)
        stale = self._patch(flow["id"], {"graph": admin_graph, "expected_updated_at": flow["updated_at"]}, self.admin_auth)
        self.assertEqual(stale.status_code, 409, stale.content)
        fresh = stale.json()["error"]["details"]["updated_at"]

        overwrite = self._patch(flow["id"], {"graph": admin_graph, "expected_updated_at": fresh}, self.admin_auth)
        self.assertEqual(overwrite.status_code, 200, overwrite.content)
        self.assertEqual(overwrite.json()["graph"], admin_graph)
        self.assertEqual(overwrite.json()["version"], 3)

    def test_diff_endpoint_summarizes_client_graph_against_server_graph(self):
        flow = self._create_flow()
        server_graph = set_threshold(flow["graph"], 75)
        saved = self._patch(flow["id"], {"graph": server_graph, "expected_updated_at": flow["updated_at"]})
        self.assertEqual(saved.status_code, 200, saved.content)

        response = self.client.post(
            f"/api/vision/flows/{flow['id']}/diff",
            data=json.dumps({"graph": flow["graph"]}),
            content_type="application/json",
            **self.admin_auth,
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertIn("threshold", body["summary"])
        self.assertEqual(body["diff"]["params"][0]["after"], 75)

    def test_operator_teach_save_with_stale_baseline_returns_409(self):
        flow = self._create_flow()
        server_graph = set_threshold(flow["graph"], 76)
        saved = self._patch(flow["id"], {"graph": server_graph, "expected_updated_at": flow["updated_at"]}, self.admin_auth)
        self.assertEqual(saved.status_code, 200, saved.content)

        teach_graph = set_threshold(flow["graph"], 77)
        response = self._patch(flow["id"], {"graph": teach_graph, "expected_updated_at": flow["updated_at"]}, self.operator_auth)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "version_conflict")
