"""配方、站台識別、未教導警告。"""

from __future__ import annotations

import json

from django.test import TestCase, TransactionTestCase, override_settings
from django.conf import settings

from apps.vision.models import Flow, FlowRun, ImageSource
from apps.vision.runner import runner
from apps.vision.tcp_server import handle_command


class RecipeTests(TestCase):
    def setUp(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 320, "height": 240})
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": self.source.id}},
                {"id": "t", "type": "threshold", "params": {"method": "fixed", "threshold": 50}},
                {"id": "o", "type": "output", "params": {"name": "thr"}},
            ],
            "edges": [{"source": "src", "target": "t"}, {"source": "t", "source_handle": "threshold_used", "target": "o", "target_handle": "value"}],
        }
        self.flow = Flow.objects.create(name="rf", graph=graph)

    def post(self, path, body):
        return self.client.post(path, data=json.dumps(body), content_type="application/json")

    def test_crud_and_validation(self):
        r = self.post(f"/api/vision/flows/{self.flow.id}/recipes", {"name": "A", "param_overrides": {"t": {"threshold": 120}}, "is_default": True})
        self.assertEqual(r.status_code, 201, r.content)
        rid = r.json()["id"]
        self.assertEqual(self.post(f"/api/vision/flows/{self.flow.id}/recipes", {"name": "A", "param_overrides": {}}).status_code, 409)
        self.assertEqual(self.post(f"/api/vision/flows/{self.flow.id}/recipes", {"name": "bad", "param_overrides": {"nope": {"x": 1}}}).status_code, 422)
        self.assertEqual(self.post(f"/api/vision/flows/{self.flow.id}/recipes", {"name": "bad2", "param_overrides": {"t": {"not_a_param": 1}}}).status_code, 422)
        r2 = self.post(f"/api/vision/flows/{self.flow.id}/recipes", {"name": "B", "param_overrides": {"t": {"threshold": 200}}, "is_default": True})
        self.assertEqual(r2.status_code, 201)
        items = self.client.get(f"/api/vision/flows/{self.flow.id}/recipes").json()["items"]
        self.assertEqual([i["is_default"] for i in items], [False, True])  # 只能有一個預設
        self.assertEqual(self.client.get(f"/api/vision/flows/{self.flow.id}").json()["recipe_count"], 2)
        r = self.client.patch(f"/api/vision/flows/{self.flow.id}/recipes/{rid}", data=json.dumps({"description": "d", "is_default": True}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["is_default"])
        self.assertEqual(self.client.delete(f"/api/vision/flows/{self.flow.id}/recipes/{rid}").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/vision/flows/{self.flow.id}/recipes/{rid}").status_code, 404)

    def test_run_with_recipe_overrides_params(self):
        self.post(f"/api/vision/flows/{self.flow.id}/recipes", {"name": "A", "param_overrides": {"t": {"threshold": 120}}})
        self.post(f"/api/vision/flows/{self.flow.id}/recipes", {"name": "B", "param_overrides": {"t": {"threshold": 200}}, "is_default": True})
        base = self.post(f"/api/vision/flows/{self.flow.id}/run", {}).json()
        self.assertEqual(base["outputs"]["thr"], 200.0)  # 預設配方
        self.assertEqual(base["recipe"], "B")
        a = self.post(f"/api/vision/flows/{self.flow.id}/run", {"recipe": "A"}).json()
        self.assertEqual(a["outputs"]["thr"], 120.0)
        self.assertEqual(a["recipe"], "A")
        self.assertEqual(self.post(f"/api/vision/flows/{self.flow.id}/run", {"recipe": "nope"}).status_code, 404)
        # 改圖版本後配方仍套用；原圖不被改
        self.assertEqual(Flow.objects.get(pk=self.flow.pk).graph["nodes"][1]["params"]["threshold"], 50)
        # preview 也可帶配方
        p = self.post(f"/api/vision/flows/{self.flow.id}/preview", {"graph": self.flow.graph, "recipe": "A"}).json()
        self.assertEqual(p["nodes"]["t"]["outputs"]["threshold_used"], 120.0)
        # TCP recipe=
        res = handle_command("RUN rf recipe=A")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["recipe"], "A")
        self.assertEqual(res["outputs"]["thr"], 120.0)
        self.assertFalse(handle_command("RUN rf recipe=zzz")["ok"])

    @override_settings(VISION={**settings.VISION, "STATION_ID": "LINE2"})
    def test_station_id_and_commissioned_warning(self):
        body = self.post(f"/api/vision/flows/{self.flow.id}/run", {}).json()
        self.assertEqual(body["station_id"], "LINE2")
        self.assertTrue(any("teaching" in w for w in body["warnings"]))
        self.assertEqual(body["status"], "ok")  # 不阻擋
        res = handle_command("RUN rf")
        self.assertEqual(res["station_id"], "LINE2")
        self.assertTrue(res["warnings"])
        # 教導完成後不再警告
        r = self.client.patch(f"/api/vision/flows/{self.flow.id}", data=json.dumps({"commissioned": True}), content_type="application/json")
        self.assertTrue(r.json()["commissioned"])
        body = self.post(f"/api/vision/flows/{self.flow.id}/run", {}).json()
        self.assertEqual(body["warnings"], [])


class PersistedStationTests(TransactionTestCase):
    """背景執行緒寫入 FlowRun：TestCase 交易會擋住，這裡用真交易。"""

    @override_settings(VISION={**settings.VISION, "STATION_ID": "LINE2"})
    def test_station_persisted(self):
        import time

        for fid in list(runner._runtimes):
            runner.forget(fid)
        time.sleep(0.3)  # 讓前面測試的背景寫入落地後清掉（flow id 會重用）
        FlowRun.objects.all().delete()
        source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 160, "height": 120})
        flow = Flow.objects.create(name="pf", graph={"nodes": [{"id": "src", "type": "image_source", "params": {"source_id": source.id}}], "edges": []})
        self.client.post(f"/api/vision/flows/{flow.id}/run", data=json.dumps({}), content_type="application/json")
        for _ in range(50):
            if FlowRun.objects.filter(flow=flow).exists():
                break
            time.sleep(0.05)
        row = FlowRun.objects.filter(flow=flow).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.station_id, "LINE2")
        hist = self.client.get(f"/api/vision/flows/{flow.id}/runs").json()
        self.assertEqual(hist["items"][0]["station_id"], "LINE2")
