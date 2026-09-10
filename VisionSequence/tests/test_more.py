"""範本庫、批次測試、整合測試工具。"""

from __future__ import annotations

import io
import json

import cv2
import numpy as np
from django.test import TestCase

from apps.vision.models import Flow, FlowTemplate, ImageSource
from apps.vision.runner import runner


def png(w=64, h=48, value=180):
    ok, buf = cv2.imencode(".png", np.full((h, w, 3), value, np.uint8))
    assert ok
    f = io.BytesIO(buf.tobytes())
    f.name = f"img-{w}x{h}.png"
    return f


class TemplateTests(TestCase):
    def setUp(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 320, "height": 240})

    def test_builtin_templates_instantiate_and_run(self):
        r = self.client.get("/api/vision/templates")
        self.assertEqual(r.status_code, 200)
        builtin = [t for t in r.json()["items"] if t["source"] == "builtin"]
        self.assertGreaterEqual(len(builtin), 5)
        # 每個內建範本都附樣本圖：畫廊不選來源時取像節點就是帶著圖的固定影像
        self.assertEqual([t["id"] for t in builtin if not t["has_samples"]], [])
        for t in builtin:
            r = self.client.post(f"/api/vision/templates/{t['id']}/instantiate", data=json.dumps({"source_id": self.source.id, "prefix": "x_"}), content_type="application/json")
            self.assertEqual(r.status_code, 200, (t["id"], r.content))
            graph = r.json()["graph"]
            self.assertFalse(r.json()["missing_source"])
            self.assertTrue(all(n["id"].startswith("x_") for n in graph["nodes"]))
            src = next(n for n in graph["nodes"] if n["type"] == "image_source")
            self.assertEqual(src["params"]["source_id"], self.source.id)
            flow = Flow.objects.create(name=f"t-{t['id']}", graph=graph)
            report = runner.run_sync(flow, trigger="preview", preview=True)
            if t["id"] in ("builtin:hole_count", "builtin:exposure"):
                # 通用樣板在任意影像上都要能跑完；其他樣板需要對應的樣本來源／資產
                # （tests/test_demo.py 會用正確來源逐一實跑），在這張空白合成圖上
                # 找不到特徵而 failed 是預期行為，這裡只驗 instantiate 出來的 graph 能執行不崩。
                self.assertNotEqual(report.status, "failed", (t["id"], report.error))
        # 沒給來源（畫廊預設）：取像節點換成帶著範例圖片的固定影像，不再要求先選來源
        for t in builtin:
            r = self.client.post(f"/api/vision/templates/{t['id']}/instantiate", data=json.dumps({}), content_type="application/json")
            body = r.json()
            self.assertTrue(body["used_samples"], t["id"])
            self.assertFalse(body["missing_source"], t["id"])
            nodes = body["graph"]["nodes"]
            self.assertFalse([n for n in nodes if n["type"] == "image_source"], t["id"])
            src = next(n for n in nodes if n["type"] == "fixed_image")
            self.assertTrue(src["params"]["images"], t["id"])
        # 明確不要樣本圖：回到佔位符清空並回報 missing（自訂範本與整合方走這條）
        r = self.client.post("/api/vision/templates/builtin:exposure/instantiate", data=json.dumps({"use_samples": False}), content_type="application/json")
        self.assertTrue(r.json()["missing_source"])

    def test_custom_template_roundtrip(self):
        graph = {"nodes": [{"id": "src", "type": "image_source", "params": {"source_id": self.source.id}}, {"id": "g", "type": "grayscale", "params": {}}], "edges": [{"source": "src", "target": "g"}]}
        r = self.client.post("/api/vision/templates", data=json.dumps({"name": "mine", "description": "d", "graph": graph}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        tid = r.json()["id"]
        self.assertEqual(r.json()["graph"]["nodes"][0]["params"]["source_id"], "{SOURCE}")
        self.assertEqual(self.client.post("/api/vision/templates", data=json.dumps({"name": "mine", "graph": graph}), content_type="application/json").status_code, 409)
        r = self.client.post(f"/api/vision/templates/{tid}/instantiate", data=json.dumps({"source_id": self.source.id}), content_type="application/json")
        self.assertEqual(r.json()["graph"]["nodes"][0]["params"]["source_id"], self.source.id)
        self.assertEqual(self.client.delete("/api/vision/templates/builtin:exposure").status_code, 422)
        self.assertEqual(self.client.delete(f"/api/vision/templates/{tid}").status_code, 204)
        self.assertFalse(FlowTemplate.objects.filter(pk=tid).exists())


class BatchAndIntegrationTests(TestCase):
    def setUp(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 320, "height": 240})
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": self.source.id}},
                {"id": "t", "type": "threshold", "params": {"method": "otsu"}},
                {"id": "c", "type": "in_range", "params": {"low": 100, "high": 200}},
                {"id": "ok", "type": "judge", "params": {"verdict": "ok"}},
                {"id": "ng", "type": "judge", "params": {"verdict": "ng"}},
                {"id": "o", "type": "output", "params": {"name": "otsu"}},
            ],
            "edges": [
                {"source": "src", "target": "t"},
                {"source": "t", "source_handle": "threshold_used", "target": "c", "target_handle": "value"},
                {"source": "c", "source_handle": "inside", "target": "ok", "target_handle": "_flow"},
                {"source": "c", "source_handle": "outside", "target": "ng", "target_handle": "_flow"},
                {"source": "t", "source_handle": "threshold_used", "target": "o", "target_handle": "value"},
            ],
        }
        self.flow = Flow.objects.create(name="b", graph=graph)

    def test_batch_upload(self):
        files = [png(64, 48, 200), png(64, 48, 20), png(80, 40, 120)]
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/batch", data={"images": files})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["summary"]["total"], 3)
        self.assertEqual(body["summary"]["ok"] + body["summary"]["ng"] + body["summary"]["failed"], 3)
        row = body["items"][0]
        self.assertIn("otsu", row["outputs"])
        self.assertTrue(row["image_ref"])
        self.assertEqual(self.client.get(f"/api/vision/images/{row['image_ref']}?max=32").status_code, 200)
        # 未儲存的圖
        g2 = json.loads(json.dumps(self.flow.graph))
        g2["nodes"] = [n for n in g2["nodes"] if n["id"] in ("src", "t")]
        g2["edges"] = [e for e in g2["edges"] if e["target"] == "t"]
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/batch", data={"images": [png()], "graph": json.dumps(g2)})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["items"][0]["outputs"], {"judge": "OK"})
        empty = io.BytesIO(b"")
        empty.name = "empty.png"
        self.assertEqual(self.client.post(f"/api/vision/flows/{self.flow.id}/batch", data={"images": [empty]}).status_code, 422)
        bad = io.BytesIO(b"not an image")
        bad.name = "bad.png"
        self.assertEqual(self.client.post(f"/api/vision/flows/{self.flow.id}/batch", data={"images": [bad]}).status_code, 422)

    def test_batch_from_source(self):
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/batch-source", data=json.dumps({"source_id": self.source.id, "count": 4}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["summary"]["total"], 4)
        self.assertGreater(r.json()["summary"]["wall_ms"], 0)

    def test_integration_info_and_tcp_direct(self):
        r = self.client.get("/api/vision/integration/info")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["tcp_port"], 9000)
        self.assertIn("RUN <flow> [k=v ...]", r.json()["commands"])
        r = self.client.post("/api/vision/integration/tcp", data=json.dumps({"command": "PING"}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["response"]["pong"])
        self.assertIn(r.json()["via"], ("tcp", "direct"))
        r = self.client.post("/api/vision/integration/tcp", data=json.dumps({"command": "RUN b"}), content_type="application/json")
        if r.json()["via"] == "direct":  # 開發伺服器若正佔著 9000，會連到另一個行程（看不到測試 DB 的流程）
            self.assertIn(r.json()["response"]["status"], ("ok", "ng"), r.content)
        self.assertEqual(self.client.post("/api/vision/integration/tcp", data=json.dumps({"command": "  "}), content_type="application/json").status_code, 422)

    def test_tcp_via_real_socket(self):
        from apps.vision import tcp_server

        server = tcp_server.start_in_background("127.0.0.1", 9000)
        try:
            r = self.client.post("/api/vision/integration/tcp", data=json.dumps({"command": "LIST"}), content_type="application/json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.json()["via"], "tcp")
            self.assertIn("flows", r.json()["response"])
        finally:
            tcp_server.stop()
            del server
