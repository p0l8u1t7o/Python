"""流程匯出內嵌資產：模型、標定隨流程搬站，匯入以內容雜湊去重。"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import shutil
import tempfile
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from apps.vision import serialize
from apps.vision.models import Asset, Flow


def _vision(tmp: str) -> dict:
    return {**settings.VISION, "ASSET_DIR": tmp, "PERSIST_RUNS": False}


class ExportAssetsTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vs-export-assets-")
        self.override = override_settings(VISION=_vision(self.tmp), VISION_EXPORT_MAX_MB=200)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _asset(self, name: str, kind: str, data: bytes, ext: str) -> Asset:
        asset_id = uuid.uuid4()
        path = os.path.join(self.tmp, f"{asset_id.hex}{ext}")
        with open(path, "wb") as fh:
            fh.write(data)
        return Asset.objects.create(id=asset_id, name=name, kind=kind, path=path, size=len(data), meta={"fixture": name})

    def _flow(self, model: Asset, calibration: Asset) -> Flow:
        return Flow.objects.create(
            name="portable",
            graph={
                "nodes": [
                    {"id": "m", "type": "dl_classify", "params": {"model": str(model.id)}, "position": {"x": 0, "y": 0}},
                    {"id": "c", "type": "grayscale", "params": {"calibration": str(calibration.id)}, "position": {"x": 1, "y": 0}},
                ],
                "edges": [],
            },
        )

    def test_export_import_restores_rewrites_ids_and_dedupes(self):
        model_data = b"model-bytes"
        calib_data = b'{"unit":"mm","image_size":[16,16]}'
        model = self._asset("classifier", "model", model_data, ".onnx")
        calibration = self._asset("lens", "calibration", calib_data, ".json")
        old_ids = {str(model.id), str(calibration.id)}
        doc = serialize.export_flow(self._flow(model, calibration), include_assets=True)

        embedded = {item["id"]: item for item in doc["assets"]}
        self.assertEqual(set(embedded), old_ids)
        self.assertEqual(embedded[str(model.id)]["sha256"], hashlib.sha256(model_data).hexdigest())
        self.assertEqual(base64.b64decode(embedded[str(calibration.id)]["data"]), calib_data)

        for asset in (model, calibration):
            os.remove(asset.path)
        Asset.objects.all().delete()
        Flow.objects.all().delete()

        first = copy.deepcopy(doc)
        first["name"] = "portable imported"
        flow, created = serialize.import_flow(first)
        self.assertTrue(created)
        local_ids = {str(a.id) for a in Asset.objects.all()}
        self.assertEqual(len(local_ids), 2)
        self.assertTrue(local_ids.isdisjoint(old_ids))
        params = {n["id"]: n["params"] for n in flow.graph["nodes"]}
        self.assertIn(params["m"]["model"], local_ids)
        self.assertIn(params["c"]["calibration"], local_ids)
        self.assertEqual(len(serialize.asset_import_report(first)["restored"]), 2)

        second = copy.deepcopy(doc)
        second["name"] = "portable imported again"
        flow2, created = serialize.import_flow(second)
        self.assertTrue(created)
        self.assertEqual(Asset.objects.count(), 2)
        params2 = {n["id"]: n["params"] for n in flow2.graph["nodes"]}
        self.assertEqual({params2["m"]["model"], params2["c"]["calibration"]}, local_ids)
        self.assertEqual(len(serialize.asset_import_report(second)["reused"]), 2)

    def test_size_limit_skips_assets_and_reports(self):
        with override_settings(VISION=_vision(self.tmp), VISION_EXPORT_MAX_MB=0):
            model = self._asset("large", "model", b"x" * 32, ".onnx")
            doc = serialize.export_flow(self._flow(model, model), include_assets=True)
        self.assertEqual(doc["assets"], [])
        skipped = doc["asset_warnings"]["skipped"]
        self.assertEqual([item["id"] for item in skipped], [str(model.id)])
        self.assertEqual(skipped[0]["reason"], "export_size_limit")
        self.assertEqual(skipped[0]["size"], 32)

    def test_import_missing_asset_reports_without_failing(self):
        missing = str(uuid.uuid4())
        doc = {
            "schema_version": serialize.SCHEMA_VERSION,
            "name": "missing asset",
            "graph": {"nodes": [{"id": "m", "type": "dl_classify", "params": {"model": missing}}], "edges": []},
        }
        flow, created = serialize.import_flow(doc)
        self.assertTrue(created)
        self.assertEqual(flow.graph["nodes"][0]["params"]["model"], missing)
        self.assertEqual(serialize.asset_import_report(doc)["missing"][0]["id"], missing)

    def test_include_assets_false_keeps_export_shape_unchanged(self):
        model = self._asset("classifier", "model", b"model-bytes", ".onnx")
        doc = serialize.export_flow(self._flow(model, model))
        self.assertEqual(doc, serialize.export_flow(Flow.objects.get(name="portable"), include_assets=False))
        self.assertNotIn("assets", doc)
        self.assertNotIn("asset_warnings", doc)

    def test_api_export_parameter_and_import_report(self):
        model = self._asset("classifier", "model", b"model-bytes", ".onnx")
        flow = self._flow(model, model)
        r = self.client.get(f"/api/vision/flows/{flow.id}/export?include_assets=true&download=false")
        self.assertEqual(r.status_code, 200, r.content)
        doc = json.loads(r.content)
        self.assertEqual(doc["assets"][0]["id"], str(model.id))
        doc["name"] = "api imported"
        Asset.objects.all().delete()
        r = self.client.post("/api/vision/flows/import", data=json.dumps({"doc": doc}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(len(r.json()["assets"]["restored"]), 1)
