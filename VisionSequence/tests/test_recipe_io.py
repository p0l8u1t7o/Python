"""配方匯出／匯入與合理化檢查。"""

from __future__ import annotations

import io
import json

from django.test import TestCase

from apps.vision.models import Flow, ImageSource
from apps.vision.runner import runner
from apps.vision.tools import base as tools


class RecipeIoTests(TestCase):
    def setUp(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 160, "height": 120})
        self.graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": self.source.id}},
                {"id": "t", "type": "threshold", "label": "二值化", "params": {"method": "fixed", "threshold": 50}},
                {"id": "b", "type": "blur", "params": {"ksize": 5}},
            ],
            "edges": [{"source": "src", "target": "t"}, {"source": "t", "target": "b"}],
        }
        self.flow = Flow.objects.create(name="rio", graph=self.graph)

    def post(self, path, body):
        return self.client.post(path, data=json.dumps(body), content_type="application/json")

    def test_check_list(self):
        r = self.post(f"/api/vision/flows/{self.flow.id}/recipes/check", {"param_overrides": {
            "t": {"threshold": 120, "method": "nope", "ghost": 1, "invert": "yes"},
            "b": {"ksize": 5},
            "zzz": {"x": 1},
        }})
        self.assertEqual(r.status_code, 200, r.content)
        status = {i["key"]: i["status"] for i in r.json()["items"]}
        self.assertEqual(status["t.threshold"], "ok")
        self.assertEqual(status["t.method"], "value_invalid")
        self.assertEqual(status["t.ghost"], "param_missing")
        self.assertEqual(status["t.invert"], "value_invalid")
        self.assertEqual(status["b.ksize"], "unchanged")
        self.assertEqual(status["zzz.x"], "node_missing")
        item = next(i for i in r.json()["items"] if i["key"] == "t.threshold")
        self.assertEqual(item["node_label"], "二值化")
        self.assertEqual(item["current"], 50)
        self.assertEqual(r.json()["summary"]["acceptable"], 2)
        # include_all：其他參數以圖值列出、帶 teach 標記
        r = self.post(f"/api/vision/flows/{self.flow.id}/recipes/check", {"param_overrides": {"t": {"threshold": 120}}, "include_all": True})
        items = {i["key"]: i for i in r.json()["items"]}
        self.assertEqual(items["t.threshold"]["status"], "ok")
        self.assertTrue(items["t.threshold"]["teach"])
        self.assertEqual(items["t.method"]["status"], "unchanged")
        self.assertEqual(items["t.method"]["current"], "fixed")
        self.assertFalse(items["b.method"]["teach"])
        self.assertEqual(items["b.ksize"]["kind"], "number")
        self.assertIn("src.mode", items)

    def test_export_import_roundtrip_and_validation(self):
        rid = self.post(f"/api/vision/flows/{self.flow.id}/recipes", {"name": "A", "param_overrides": {"t": {"threshold": 120}, "b": {"ksize": 7}}, "is_default": True}).json()["id"]
        r = self.client.get(f"/api/vision/flows/{self.flow.id}/recipes/{rid}/export")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        doc = json.loads(r.content)
        self.assertEqual(doc["kind"], "recipe")
        self.assertEqual(doc["tool_versions"]["t"]["type"], "threshold")
        self.assertEqual(doc["recipe"]["param_overrides"]["t"]["threshold"], 120)
        # 檢查：同一流程全部 ok
        chk = self.post(f"/api/vision/flows/{self.flow.id}/recipes/import/check", doc).json()
        self.assertTrue(chk["fingerprint_match"])
        self.assertTrue(chk["recipes"][0]["exists"])
        self.assertEqual(chk["recipes"][0]["summary"]["ok"], 2)
        # 流程改了：刪掉 b、t 換工具 → 對應項目被擋
        g2 = json.loads(json.dumps(self.graph))
        g2["nodes"] = [n for n in g2["nodes"] if n["id"] != "b"]
        g2["edges"] = [e for e in g2["edges"] if e["target"] != "b"]
        g2["nodes"][1]["type"] = "grayscale"
        g2["nodes"][1]["params"] = {}
        other = Flow.objects.create(name="rio2", graph=g2)
        chk = self.post(f"/api/vision/flows/{other.id}/recipes/import/check", doc).json()
        self.assertFalse(chk["fingerprint_match"])
        status = {i["key"]: i["status"] for i in chk["recipes"][0]["items"]}
        self.assertEqual(status["t.threshold"], "type_changed")
        self.assertEqual(status["b.ksize"], "node_missing")
        r = self.post(f"/api/vision/flows/{other.id}/recipes/import", {"doc": doc})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["items"][0]["accepted"], 0)
        self.assertEqual(len(r.json()["skipped"]), 2)
        # 版本變了：記錄版本 99 → version_changed，預設不接受，明確 accept 才寫入
        doc2 = json.loads(json.dumps(doc))
        doc2["tool_versions"]["t"]["version"] = 99
        chk = self.post(f"/api/vision/flows/{self.flow.id}/recipes/import/check", doc2).json()
        self.assertEqual({i["key"]: i["status"] for i in chk["recipes"][0]["items"]}["t.threshold"], "version_changed")
        r = self.post(f"/api/vision/flows/{self.flow.id}/recipes/import", {"doc": doc2, "name": "B"})
        self.assertEqual(r.json()["items"][0]["accepted"], 1)  # 只有 b.ksize
        r = self.post(f"/api/vision/flows/{self.flow.id}/recipes/import", {"doc": doc2, "name": "C", "accept": ["t.threshold", "b.ksize"]})
        self.assertEqual(r.json()["items"][0]["accepted"], 2)
        self.assertEqual(r.json()["items"][0]["param_overrides"]["t"]["threshold"], 120)
        # 匯入同名 → 更新
        r = self.post(f"/api/vision/flows/{self.flow.id}/recipes/import", {"doc": doc, "description": "updated"})
        self.assertFalse(r.json()["items"][0]["created"])
        self.assertEqual(r.json()["items"][0]["description"], "updated")
        # multipart 檔案檢查
        f = io.BytesIO(json.dumps(doc).encode("utf-8"))
        f.name = "a.recipe.json"
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/recipes/import/check", data={"file": f})
        self.assertEqual(r.status_code, 200, r.content)
        bad = io.BytesIO(b"{}")
        bad.name = "bad.json"
        self.assertEqual(self.client.post(f"/api/vision/flows/{self.flow.id}/recipes/import/check", data={"file": bad}).status_code, 422)
        # export-all
        r = self.client.get(f"/api/vision/flows/{self.flow.id}/recipes/export-all")
        self.assertEqual(json.loads(r.content)["kind"], "recipes")
        self.assertGreaterEqual(len(json.loads(r.content)["recipes"]), 3)

    def test_tool_version_in_catalogue(self):
        items = {t["key"]: t for t in tools.catalogue()}
        self.assertEqual(items["threshold"]["version"], 1)
