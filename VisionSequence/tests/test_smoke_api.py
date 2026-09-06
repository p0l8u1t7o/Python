"""API 煙霧測試：以 bootstrap 身分掃過所有「無副作用」的 GET 端點，任何 5xx／例外都算失敗。

目的是抓「改了 schema／序列化／路由順序卻沒人打到」的回歸：清單、詳情、目錄、統計、設定類端點
一律要能回 2xx／預期的 4xx。有路徑參數的端點用建好的流程／來源／資產 id 代入。
"""

from __future__ import annotations

import io
import json

import cv2
import numpy as np
from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.vision.models import Asset, Flow, ImageSource


def _save_png(image: np.ndarray, name: str) -> str:
    """把合成影像寫進 ASSET_DIR（形狀範本建模的來源資產）。"""
    import os

    path = os.path.join(str(settings.VISION["ASSET_DIR"]), name)
    ok, buf = cv2.imencode(".png", image)
    assert ok
    buf.tofile(path)
    return path


def _png_upload(name: str = "a.png") -> io.BytesIO:
    ok, buf = cv2.imencode(".png", np.full((48, 64, 3), 160, np.uint8))
    assert ok
    f = io.BytesIO(buf.tobytes())
    f.name = name
    return f


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class GetEndpointsSmokeTests(TransactionTestCase):
    """TransactionTestCase：run 端點跨執行緒；PERSIST_RUNS=False 免得背景持久化執行緒握住測試 DB。"""
    def setUp(self):
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 160, "height": 120})
        graph = {"nodes": [{"id": "src", "type": "image_source", "params": {"source_id": self.source.id}}, {"id": "g", "type": "grayscale", "params": {}}, {"id": "j", "type": "judge", "params": {"verdict": "ok"}}],
                 "edges": [{"source": "src", "target": "g"}]}
        r = self.client.post("/api/vision/flows", data=json.dumps({"name": "smoke", "graph": graph}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.flow = Flow.objects.get(pk=r.json()["id"])
        r = self.client.post("/api/vision/assets", data={"file": _png_upload(), "kind": "image", "name": "tpl"})
        self.assertEqual(r.status_code, 201, r.content)
        self.asset = Asset.objects.get(pk=r.json()["id"])
        payload = {"unit": "mm", "image_size": [64, 48], "world": {"kind": "scale", "matrix": [[0.05, 0, 0], [0, 0.05, 0], [0, 0, 1]]}}
        r = self.client.post("/api/vision/calibration/assets", data=json.dumps({"name": "cal", "payload": payload}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.calibration_id = r.json()["id"]
        r = self.client.post("/api/vision/assets/stat-template", data={"images": [_png_upload(), _png_upload(), _png_upload()], "name": "stat", "align": "none"})
        self.assertEqual(r.status_code, 201, r.content)
        self.stat_id = r.json()["id"]
        shape_src = np.full((120, 160), 40, np.uint8)
        cv2.rectangle(shape_src, (40, 30), (110, 90), 220, -1)
        cv2.circle(shape_src, (60, 50), 8, 90, -1)
        shape_asset = Asset.objects.create(name="shape-src", kind="image", path=_save_png(shape_src, "shape-src.png"))
        r = self.client.post("/api/vision/assets/shape-model", data=json.dumps({"asset_id": str(shape_asset.id), "name": "shape", "min_contrast": 10}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.shape_id = r.json()["id"]
        # 跑一次，讓 recent／stats／runs 有資料
        r = self.client.post(f"/api/vision/flows/{self.flow.id}/run", data=json.dumps({"wait": True}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.run_id = r.json()["id"]
        # 批次測試：一個影像集＋一次執行（背景執行緒，等它跑完）
        from apps.vision.batch import jobs as batch_jobs

        r = self.client.post("/api/vision/batch/sets", data={"images": [_png_upload()], "flow_id": self.flow.id, "name": "smoke"})
        self.assertEqual(r.status_code, 201, r.content)
        self.set_id = r.json()["id"]
        r = self.client.post(f"/api/vision/batch/sets/{self.set_id}/runs", data=json.dumps({}), content_type="application/json")
        self.assertEqual(r.status_code, 202, r.content)
        self.batch_run_id = r.json()["id"]
        batch_jobs.wait(self.batch_run_id)

    def test_get_endpoints_do_not_5xx(self):
        fid, sid, aid = self.flow.id, self.source.id, self.asset.id
        paths = [
            "/api/auth/me", "/api/vision/lock", "/api/users", "/api/users/permissions",
            "/api/vision/flows", f"/api/vision/flows/{fid}", f"/api/vision/flows/{fid}/recent?limit=1", f"/api/vision/flows/{fid}/stats", f"/api/vision/flows/{fid}/spc", "/api/vision/spc/alerts",
            f"/api/vision/flows/{fid}/runs?limit=5", f"/api/vision/flows/{fid}/recipes", f"/api/vision/flows/{fid}/golden", f"/api/vision/flows/{fid}/golden/baseline",
            f"/api/vision/flows/{fid}/export", f"/api/vision/runs/{self.run_id}", f"/api/vision/flows/{fid}/board", f"/api/vision/flows/{fid}/variables", "/api/vision/variables",
            "/api/vision/tool-types", "/api/vision/sources", "/api/vision/sources/kinds", f"/api/vision/sources/{sid}",
            "/api/vision/assets", f"/api/vision/assets/{aid}/file", "/api/vision/ocr/models", "/api/vision/ocr/fonts", "/api/vision/assets?kind=calibration",
            f"/api/vision/calibration/assets/{self.calibration_id}", f"/api/vision/assets/{self.stat_id}/stat-template", f"/api/vision/assets/{self.stat_id}/stat-template/mean",
            f"/api/vision/assets/{self.shape_id}/shape-model", f"/api/vision/assets/{self.shape_id}/shape-model/preview",
            "/api/vision/groups?kind=source", "/api/vision/fs",
            "/api/vision/templates", "/api/vision/fixed-images", "/api/vision/capacity", "/api/vision/integration/info", "/api/vision/plugins",
            "/api/vision/audit", "/api/vision/audit.csv", "/api/vision/summary", f"/api/vision/flows/{fid}/versions", f"/api/vision/flows/{fid}/versions/1",
    "/api/vision/integration/trace",
            "/api/vision/capture/clients", "/api/vision/capture/download/info", "/api/vision/capture/download", "/api/vision/capture/clients/nope/channels/x/preview",
            "/api/vision/connections", "/api/vision/dl/projects", "/api/vision/dl/trainers", "/api/vision/dl/devices", "/api/vision/dl/train/status",
            "/api/vision/agent/info", "/api/vision/agent/help/search?q=批次測試", "/api/vision/agent/jobs", "/api/vision/agent/sessions", "/api/vision/agent/memory", "/api/vision/agent/skills/custom", "/api/vision/agent/skills", "/api/vision/agent/skills/platform", "/api/vision/agent/skills/blob",
            f"/api/vision/batch/sets?flow_id={fid}", f"/api/vision/batch/sets/{self.set_id}", f"/api/vision/batch/sets/{self.set_id}/runs",
            f"/api/vision/batch/sets/{self.set_id}/images/0?max=32", f"/api/vision/batch/runs/{self.batch_run_id}",
            f"/api/vision/batch/runs/{self.batch_run_id}/insights", f"/api/vision/batch/runs/{self.batch_run_id}/compare?other={self.batch_run_id}",
            f"/api/vision/flows/{fid}/events?max_seconds=0.2",
        ]
        bad = []
        for path in paths:
            try:
                r = self.client.get(path)
            except Exception as exc:  # noqa: BLE001
                bad.append((path, f"exception {exc!r}"))
                continue
            if r.status_code >= 500 or r.status_code == 405:
                bad.append((path, r.status_code, r.content[:200]))
        self.assertFalse(bad, bad)
