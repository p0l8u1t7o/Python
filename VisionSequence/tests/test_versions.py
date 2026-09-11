"""流程版本歷史：每次存檔留快照、看得到差異、還原產生新版本、發行版不被淘汰。"""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.accounts.models import AuthToken, UserPref
from apps.vision import graphdiff
from apps.vision.models import Flow, FlowVersion, ImageSource

VISION = settings.VISION


def graph(threshold: int = 60, extra: bool = False) -> dict:
    nodes = [
        {"id": "src", "type": "image_source", "params": {"source_id": 1}, "position": {"x": 0, "y": 0}},
        {"id": "thr", "type": "threshold", "params": {"method": "fixed", "threshold": threshold}},
    ]
    edges = [{"source": "src", "source_handle": "image", "target": "thr", "target_handle": "image"}]
    if extra:
        nodes.append({"id": "gray", "type": "grayscale", "params": {}})
        edges.append({"source": "thr", "source_handle": "image", "target": "gray", "target_handle": "image"})
    return {"nodes": nodes, "edges": edges}


class GraphDiffTests(TestCase):
    """差異是講給人聽的：參數逐條列，結構只給數量。"""

    def test_parameter_change_is_the_unit(self):
        d = graphdiff.diff(graph(60), graph(46))
        self.assertEqual(d["params"], [{"node": "thr", "type": "threshold", "param": "threshold", "before": 60, "after": 46}])
        self.assertFalse(d["structural"])
        self.assertEqual(d["count"], 1)
        self.assertEqual(graphdiff.summarize(d), "threshold 60 → 46")
        self.assertEqual(graphdiff.summarize(graphdiff.diff(graph(60), graph(None))), "threshold 60 → null")

    def test_structure_is_summarised_not_dumped(self):
        d = graphdiff.diff(graph(60), graph(60, extra=True))
        self.assertEqual(d["added"], ["gray"])
        self.assertEqual(d["edges_added"], 1)
        self.assertTrue(d["structural"])
        self.assertIn("+1 step", graphdiff.summarize(d))

    def test_layout_only_change_is_not_a_real_change(self):
        moved = json.loads(json.dumps(graph(60)))
        moved["nodes"][0]["position"] = {"x": 99, "y": 99}
        d = graphdiff.diff(graph(60), moved)
        self.assertEqual(d["count"], 0)
        self.assertEqual(d["moved"], 1)
        self.assertEqual(graphdiff.summarize(d), "layout only")

    def test_long_values_are_clipped(self):
        a, b = graph(), graph()
        b["nodes"][1]["params"]["code"] = "x" * 5000
        d = graphdiff.diff(a, b)
        self.assertLessEqual(len(d["params"][0]["after"]), graphdiff.MAX_VALUE_CHARS + 1)

    def test_retype_and_rename(self):
        b = json.loads(json.dumps(graph()))
        b["nodes"][1]["type"] = "grayscale"
        b["nodes"][1]["label"] = "灰階"
        d = graphdiff.diff(graph(), b)
        self.assertEqual(d["retyped"][0]["after"], "grayscale")
        self.assertEqual(d["renamed"][0]["after"], "灰階")


@override_settings(VISION={**VISION, "PERSIST_RUNS": False})  # 背景持久化執行緒會鎖住測試 DB
class VersionApiTests(TestCase):
    def setUp(self):
        self.source = ImageSource.objects.create(name="s", kind="synthetic", config={"width": 32, "height": 32})
        r = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret1"}), content_type="application/json")
        self.token = r.json()["token"]
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}
        r = self.client.post("/api/vision/flows", data=json.dumps({"name": "versioned", "graph": graph(60)}), content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 201, r.content)
        self.flow_id = r.json()["id"]

    def _patch(self, body):
        return self.client.patch(f"/api/vision/flows/{self.flow_id}", data=json.dumps(body), content_type="application/json", **self.auth)

    def test_every_save_leaves_a_snapshot_with_a_readable_summary(self):
        self.assertEqual(FlowVersion.objects.filter(flow_id=self.flow_id).count(), 1)
        self.assertEqual(self._patch({"graph": graph(46)}).status_code, 200)
        self.assertEqual(self._patch({"graph": graph(46, extra=True)}).status_code, 200)
        body = self.client.get(f"/api/vision/flows/{self.flow_id}/versions", **self.auth).json()
        self.assertEqual(len(body["items"]), 3)
        self.assertEqual(body["items"][0]["is_current"], True)
        self.assertIn("+1 step", body["items"][0]["summary"])
        self.assertEqual(body["items"][1]["summary"], "threshold 60 → 46")
        self.assertEqual(body["items"][2]["note"], "created")

    def test_saving_without_touching_the_graph_makes_no_version(self):
        self.assertEqual(self._patch({"description": "just a note"}).status_code, 200)
        self.assertEqual(self._patch({"graph": graph(60)}).status_code, 200)  # 同一張圖
        self.assertEqual(FlowVersion.objects.filter(flow_id=self.flow_id).count(), 1)
        self.assertEqual(Flow.objects.get(pk=self.flow_id).version, 1)

    def test_compare_against_current(self):
        self._patch({"graph": graph(46)})
        body = self.client.get(f"/api/vision/flows/{self.flow_id}/versions/1", **self.auth).json()
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["current_version"], 2)
        self.assertEqual(body["diff"]["params"][0]["after"], 46)
        self.assertIn("nodes", body["graph"])
        self.assertEqual(self.client.get(f"/api/vision/flows/{self.flow_id}/versions/99", **self.auth).status_code, 404)

    def test_restore_creates_a_new_version_and_never_rewrites_history(self):
        self._patch({"graph": graph(46)})
        r = self.client.post(f"/api/vision/flows/{self.flow_id}/versions/1/restore", **self.auth)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["restored_from"], 1)
        flow = Flow.objects.get(pk=self.flow_id)
        self.assertEqual(flow.version, 3)
        self.assertEqual(flow.graph["nodes"][1]["params"]["threshold"], 60)
        rows = list(FlowVersion.objects.filter(flow_id=self.flow_id).order_by("version"))
        self.assertEqual([r.version for r in rows], [1, 2, 3])          # 第 2 版還在
        self.assertEqual(rows[1].graph["nodes"][1]["params"]["threshold"], 46)
        self.assertEqual(rows[2].note, "restored from v1")

    def test_release_marks_without_blocking_execution(self):
        r = self.client.post(f"/api/vision/flows/{self.flow_id}/versions/1/release",
                             data=json.dumps({"released": True, "note": "signed off"}), content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["is_released"], r.json()["note"]), (True, "signed off"))
        # 未發行的修改照樣跑得動——發行只是標記
        self._patch({"graph": graph(46)})
        self.assertEqual(self.client.post(f"/api/vision/flows/{self.flow_id}/run", data="{}", content_type="application/json", **self.auth).status_code, 200)
        r = self.client.post(f"/api/vision/flows/{self.flow_id}/versions/1/release",
                             data=json.dumps({"released": False}), content_type="application/json", **self.auth)
        self.assertFalse(r.json()["is_released"])

    @override_settings(VISION={**VISION, "KEEP_VERSIONS": 3, "PERSIST_RUNS": False})
    def test_pruning_keeps_the_newest_and_every_released_version(self):
        flow = Flow.objects.get(pk=self.flow_id)
        FlowVersion.objects.filter(flow=flow, version=1).update(is_released=True)
        for i in range(2, 9):
            self._patch({"graph": graph(i)})
        kept = sorted(FlowVersion.objects.filter(flow=flow).values_list("version", flat=True))
        self.assertIn(1, kept, "已發行的版本不該被淘汰")
        self.assertEqual(kept[-3:], [6, 7, 8])
        self.assertEqual(len(kept), 4)  # 3 個最新 + 1 個發行版

    def test_operator_cannot_restore_or_release(self):
        op = User.objects.create_user("op", password="x")
        UserPref.objects.create(user=op, role="operator")
        h = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(op)}"}
        self.assertEqual(self.client.get(f"/api/vision/flows/{self.flow_id}/versions", **h).status_code, 200)
        self.assertEqual(self.client.post(f"/api/vision/flows/{self.flow_id}/versions/1/restore", **h).status_code, 403)
        self.assertEqual(self.client.post(f"/api/vision/flows/{self.flow_id}/versions/1/release",
                                          data=json.dumps({"released": True}), content_type="application/json", **h).status_code, 403)
