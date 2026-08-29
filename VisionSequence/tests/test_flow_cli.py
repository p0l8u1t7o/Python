"""流程匯出／匯入／CLI 執行：穩定序列化、byte-identical 往返、API 端點。"""

from __future__ import annotations

import io
import json
import os
import shutil
from unittest import mock

import cv2
import numpy as np
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.vision import serialize
from apps.vision.models import Flow, ImageSource
from apps.vision.runner import runner
from tests._helpers import save_png, temp_dir


def messy_graph(source_id) -> dict:
    """故意亂序、浮點座標、key 順序不同、沒填 handle。"""
    return {
        "nodes": [
            {"params": {"name": "otsu"}, "type": "output", "id": "o", "position": {"x": 900.4, "y": 10.6}},
            {"id": "t", "type": "threshold", "params": {"method": "otsu"}, "position": {"y": 0.2, "x": 600.49}},
            {"id": "src", "type": "image_source", "params": {"source_id": source_id}, "label": "取像 中文", "position": {"x": 0, "y": 0}},
            {"id": "g", "type": "grayscale", "params": {}, "position": {"x": 300.5, "y": 0}},
        ],
        "edges": [
            {"id": "e3", "source": "t", "source_handle": "threshold_used", "target": "o", "target_handle": "value"},
            {"id": "e2", "source": "g", "target": "t"},
            {"id": "e1", "source": "src", "target": "g"},
        ],
    }


class FlowSerializeTests(TestCase):
    def setUp(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})
        self.flow = Flow.objects.create(name="hole 中文", description="d", graph=messy_graph(self.source.id), continuous_interval_ms=50)
        self.tmp = temp_dir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_format(self):
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1700000000"}):
            data = serialize.to_bytes(serialize.export_flow(self.flow))
        text = data.decode("utf-8")
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn("\r", text)
        self.assertTrue(text.endswith("}\n"))
        self.assertIn("取像 中文", text)  # ensure_ascii=False
        self.assertIn("\n  \"schema_version\": 1,\n", text)  # 2 空格縮排
        doc = json.loads(text)
        self.assertEqual(list(doc), ["schema_version", "exported_at", "name", "description", "continuous_interval_ms", "graph"])
        self.assertEqual(doc["exported_at"], "2023-11-14T22:13:20Z")
        self.assertEqual(doc["continuous_interval_ms"], 50)
        nodes = doc["graph"]["nodes"]
        self.assertEqual([n["id"] for n in nodes], ["g", "o", "src", "t"])
        self.assertEqual(list(nodes[0]), ["id", "type", "params", "position"])
        self.assertEqual(nodes[1]["position"], {"x": 900, "y": 11})
        self.assertEqual(nodes[3]["position"], {"x": 600, "y": 0})
        src = next(n for n in nodes if n["id"] == "src")
        self.assertEqual(src["params"]["source_id"], "{SOURCE}")
        edges = doc["graph"]["edges"]
        self.assertEqual([(e["source"], e["target"]) for e in edges], [("g", "t"), ("src", "g"), ("t", "o")])
        self.assertEqual(list(edges[0]), ["id", "source", "source_handle", "target", "target_handle"])
        self.assertEqual(edges[1]["source_handle"], "image")  # validate_graph 補上的 handle 也匯出

    def test_export_import_export_byte_identical(self):
        p1 = os.path.join(self.tmp, "a.flow.json")
        p2 = os.path.join(self.tmp, "b.flow.json")
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1700000000"}):
            call_command("flow", "export", str(self.flow.id), "-o", p1, stderr=io.StringIO())
            out = io.StringIO()
            call_command("flow", "import", p1, "--source", str(self.source.id), stdout=out)
            self.assertIn("更新", out.getvalue())
            self.flow.refresh_from_db()
            self.assertEqual(self.flow.version, 2)
            self.assertEqual(next(n for n in self.flow.graph["nodes"] if n["id"] == "src")["params"]["source_id"], self.source.id)
            call_command("flow", "export", self.flow.name, "-o", p2, stderr=io.StringIO())
        with open(p1, "rb") as f1, open(p2, "rb") as f2:
            b1, b2 = f1.read(), f2.read()
        self.assertEqual(b1, b2)
        self.assertNotIn(b"\r\n", b1)

    def test_import_creates_and_leaves_placeholder_empty(self):
        doc = serialize.export_flow(self.flow)
        doc["name"] = "new one"
        path = os.path.join(self.tmp, "n.flow.json")
        serialize.write_file(doc, path)
        out = io.StringIO()
        call_command("flow", "import", path, stdout=out)
        self.assertIn("建立", out.getvalue())
        flow = Flow.objects.get(name="new one")
        self.assertEqual(flow.version, 1)
        self.assertEqual(next(n for n in flow.graph["nodes"] if n["id"] == "src")["params"]["source_id"], "")
        with self.assertRaises(CommandError):
            call_command("flow", "import", os.path.join(self.tmp, "missing.json"))
        with self.assertRaises(CommandError):
            call_command("flow", "export", "no-such-flow", "-o", os.path.join(self.tmp, "x.json"))
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write(json.dumps({"schema_version": 99, "name": "x", "graph": {}}))
        with self.assertRaises(CommandError):
            call_command("flow", "import", bad)

    def test_import_update_keeps_existing_source_when_unspecified(self):
        """更新既有流程、沒指定 source_id → 取像步驟沿用原流程的來源（不能清成空白）；有指定則覆蓋。"""
        doc = serialize.export_flow(self.flow)
        flow, created = serialize.import_flow(doc, source_id=None)
        self.assertFalse(created)
        self.assertEqual(next(n for n in flow.graph["nodes"] if n["id"] == "src")["params"]["source_id"], self.source.id)
        other = ImageSource.objects.create(name="other", kind="synthetic", config={"width": 8, "height": 8})
        flow, _ = serialize.import_flow(doc, source_id=other.id)
        self.assertEqual(next(n for n in flow.graph["nodes"] if n["id"] == "src")["params"]["source_id"], other.id)
        # 取像步驟 id 不同也沿用原流程任一來源
        doc2 = json.loads(json.dumps(doc))
        for n in doc2["graph"]["nodes"]:
            if n["id"] == "src":
                n["id"] = "src2"
        for e in doc2["graph"]["edges"]:
            if e["source"] == "src":
                e["source"] = "src2"
        flow, _ = serialize.import_flow(doc2, source_id=None)
        self.assertEqual(next(n for n in flow.graph["nodes"] if n["id"] == "src2")["params"]["source_id"], other.id)

    def test_run_once_folder_and_file(self):
        out = io.StringIO()
        call_command("flow", "run", str(self.flow.id), "--json", stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["status"], "ok")
        self.assertIn("otsu", data["items"][0]["outputs"])

        folder = os.path.join(self.tmp, "imgs")
        os.makedirs(folder)
        save_png(np.full((48, 64), 200, np.uint8), folder, "b.png")
        save_png(np.full((48, 64), 20, np.uint8), folder, "a.png")
        with open(os.path.join(folder, "readme.txt"), "w") as f:
            f.write("skip")
        out = io.StringIO()
        call_command("flow", "run", self.flow.name, "--images", folder, stdout=out)
        lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("ok") and "a.png" in lines[0])
        self.assertIn("b.png", lines[1])

        # 直接跑檔案（不進 DB）
        path = os.path.join(self.tmp, "f.flow.json")
        serialize.write_file(serialize.export_flow(self.flow), path)
        out = io.StringIO()
        call_command("flow", "run", path, "--source", str(self.source.id), "--images", folder, "--json", stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual([r["name"] for r in data["items"]], ["a.png", "b.png"])
        self.assertTrue(all(r["status"] == "ok" for r in data["items"]))
        self.assertEqual(Flow.objects.count(), 1)

    # -- API ---------------------------------------------------------------
    def test_api_export_and_import(self):
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1700000000"}):
            r = self.client.get(f"/api/vision/flows/{self.flow.id}/export")
            self.assertEqual(r.status_code, 200)
            self.assertIn("attachment", r["Content-Disposition"])
            self.assertIn(".flow.json", r["Content-Disposition"])
            expected = serialize.to_bytes(serialize.export_flow(self.flow))
        self.assertEqual(r.content, expected)
        doc = json.loads(r.content)

        # JSON body：同名 → 更新 (200)
        doc["description"] = "changed"
        r = self.client.post("/api/vision/flows/import", data=json.dumps({**doc, "source_id": self.source.id}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["created"])
        self.assertEqual(r.json()["flow"]["version"], 2)
        self.assertEqual(r.json()["flow"]["description"], "changed")

        # multipart file：新名稱 → 建立 (201)
        doc["name"] = "imported"
        f = io.BytesIO(serialize.to_bytes(doc))
        f.name = "imported.flow.json"
        r = self.client.post("/api/vision/flows/import", data={"file": f})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["created"])
        self.assertEqual(Flow.objects.get(name="imported").graph["nodes"][2]["params"]["source_id"], "")

        r = self.client.post("/api/vision/flows/import", data=json.dumps({"doc": {"schema_version": 2, "name": "x", "graph": {}}}), content_type="application/json")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.client.get("/api/vision/flows/9999/export").status_code, 404)

    def test_bad_image_in_folder(self):
        folder = os.path.join(self.tmp, "bad")
        os.makedirs(folder)
        with open(os.path.join(folder, "x.png"), "wb") as f:
            f.write(b"not png")
        ok, buf = cv2.imencode(".png", np.full((48, 64, 3), 200, np.uint8))
        buf.tofile(os.path.join(folder, "y.png"))
        out = io.StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command("flow", "run", str(self.flow.id), "--images", folder, stdout=out)
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("無法解碼", out.getvalue())
