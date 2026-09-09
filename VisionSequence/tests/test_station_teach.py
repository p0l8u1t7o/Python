"""站台層級現場教導參數與自訂捷徑群組。"""

from __future__ import annotations

import copy
import json

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import AuthToken, UserPref
from apps.vision.models import Flow, ImageSource


def graph(source_id: int, threshold: int = 60) -> dict:
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "label": "Camera", "params": {"source_id": source_id}},
            {"id": "thr", "type": "threshold", "label": "Threshold", "params": {"method": "fixed", "threshold": threshold}},
        ],
        "edges": [{"source": "src", "source_handle": "image", "target": "thr", "target_handle": "image"}],
    }


class StationTeachTests(TestCase):
    def setUp(self):
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})
        admin = User.objects.create_user("admin", password="secret1", is_staff=True)
        self.admin = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(admin)}"}
        op = User.objects.create_user("op", password="pass123")
        UserPref.objects.create(user=op, role="operator")
        self.operator = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(op)}"}
        self.flow_a = Flow.objects.create(name="front", graph=graph(self.source.id, 60), owner=admin)
        self.flow_b = Flow.objects.create(name="back", graph=graph(self.source.id, 80), owner=admin)

    def _json(self, method: str, path: str, body: dict | None = None, auth: dict | None = None):
        return getattr(self.client, method)(
            path,
            data=json.dumps(body or {}),
            content_type="application/json",
            **(auth or self.admin),
        )

    def test_aggregate_returns_only_teach_params_with_flow_node_and_tool(self):
        r = self.client.get("/api/vision/teach/params", **self.operator)
        self.assertEqual(r.status_code, 200, r.content)
        rows = r.json()["items"]
        keys = {row["param"]["key"] for row in rows}
        self.assertIn("threshold", keys)
        self.assertIn("offset", keys)
        self.assertNotIn("method", keys)
        self.assertEqual({row["flow_id"] for row in rows}, {self.flow_a.id, self.flow_b.id})
        row = next(x for x in rows if x["flow_id"] == self.flow_a.id)
        self.assertEqual((row["node_id"], row["tool_type"], row["tool_category"]), ("thr", "threshold", "preprocess"))

    def test_operator_patch_uses_teachguard_for_teach_and_non_teach_params(self):
        teach = copy.deepcopy(self.flow_a.graph)
        next(n for n in teach["nodes"] if n["id"] == "thr")["params"]["threshold"] = 99
        r = self._json("patch", f"/api/vision/flows/{self.flow_a.id}", {"graph": teach}, self.operator)
        self.assertEqual(r.status_code, 200, r.content)

        not_teach = copy.deepcopy(self.flow_a.graph)
        next(n for n in not_teach["nodes"] if n["id"] == "thr")["params"]["method"] = "otsu"
        r = self._json("patch", f"/api/vision/flows/{self.flow_a.id}", {"graph": not_teach}, self.operator)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "teach_only")

    def test_multi_flow_save_reports_success_and_failure_per_flow(self):
        ok = copy.deepcopy(self.flow_a.graph)
        next(n for n in ok["nodes"] if n["id"] == "thr")["params"]["threshold"] = 70
        bad = copy.deepcopy(self.flow_b.graph)
        next(n for n in bad["nodes"] if n["id"] == "thr")["params"]["method"] = "otsu"
        results = []
        for flow_id, payload in ((self.flow_a.id, ok), (self.flow_b.id, bad)):
            r = self._json("patch", f"/api/vision/flows/{flow_id}", {"graph": payload}, self.operator)
            results.append({"flow_id": flow_id, "ok": 200 <= r.status_code < 300, "status": r.status_code})
        self.assertEqual(results, [
            {"flow_id": self.flow_a.id, "ok": True, "status": 200},
            {"flow_id": self.flow_b.id, "ok": False, "status": 403},
        ])

    def test_groups_crud_limit_and_missing_refs(self):
        item = {"flow_id": self.flow_a.id, "node_id": "thr", "param": "threshold"}
        r = self._json("post", "/api/vision/teach/groups", {"name": "Daily", "items": [item]}, self.operator)
        self.assertEqual(r.status_code, 201, r.content)
        gid = r.json()["id"]
        self.assertTrue(r.json()["items"][0]["valid"])

        r = self._json("patch", f"/api/vision/teach/groups/{gid}", {"name": "Shift A"}, self.operator)
        self.assertEqual((r.status_code, r.json()["name"]), (200, "Shift A"))
        second = self._json("post", "/api/vision/teach/groups", {"name": "Shift B"}, self.operator).json()["id"]
        r = self._json("patch", "/api/vision/teach/groups/order", {"ids": [second, gid]}, self.operator)
        self.assertEqual([g["id"] for g in r.json()["items"][:2]], [second, gid])

        r = self._json(
            "patch",
            f"/api/vision/teach/groups/{gid}",
            {"items": [{"flow_id": self.flow_a.id, "node_id": "gone", "param": "threshold"}]},
            self.operator,
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["items"][0]["valid"], r.json()["items"][0]["reason"]), (False, "missing"))
        self.assertEqual(self.client.get("/api/vision/teach/groups", **self.operator).status_code, 200)

        self.assertEqual(self.client.delete(f"/api/vision/teach/groups/{second}", **self.operator).status_code, 204)
        existing = {g["name"] for g in self.client.get("/api/vision/teach/groups", **self.operator).json()["items"]}
        self.assertEqual(existing, {"Shift A"})

        for i in range(31):
            r = self._json("post", "/api/vision/teach/groups", {"name": f"G{i}"}, self.operator)
            self.assertEqual(r.status_code, 201, r.content)
        r = self._json("post", "/api/vision/teach/groups", {"name": "Too many"}, self.operator)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "too_many_groups")
