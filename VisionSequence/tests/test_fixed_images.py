"""固定影像：檔案庫（雜湊去重、載入快取、縮圖、孤兒）、fixed_image 工具（輪播／固定／試執行也推進／_input_image 優先）、
API（上傳多檔、from-ref、取檔與縮圖要登入）、範本以樣本圖實例化、參考影像埠（template_match／defect_diff／shading_correct／contour_match）、匯出匯入帶圖。"""

from __future__ import annotations

import base64
import io
import json
import shutil
import tempfile

import cv2
import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings

from apps.vision import demo, fixed_images, serialize
from apps.vision.images import store as image_store
from apps.vision.models import Flow
from apps.vision.tools.base import ToolError
from apps.vision.tools.builtin import fixed_image as fixed_tool
from tests._helpers import run_tool


def _png(h: int = 40, w: int = 60, value: int = 100) -> bytes:
    img = np.full((h, w, 3), value, np.uint8)
    cv2.rectangle(img, (5, 5), (20, 20), (255, 255, 255), -1)
    return cv2.imencode(".png", img)[1].tobytes()


def _tmp_assets(tmp: str) -> dict:
    return {**settings.VISION, "ASSET_DIR": tmp}


class FixedImageStoreTests(SimpleTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vs-fixed-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_store_dedupes_loads_and_thumbnails(self):
        with override_settings(VISION=_tmp_assets(self.tmp)):
            a = fixed_images.store_bytes(_png(), "one.png")
            b = fixed_images.store_bytes(_png(), "again.png")
            self.assertEqual(a["id"], b["id"])  # 同內容同 id
            self.assertEqual((a["width"], a["height"]), (60, 40))
            self.assertEqual(len(a["id"]), fixed_images.ID_LEN)
            self.assertEqual(fixed_images.list_ids(), [a["id"]])
            img = fixed_images.load(a["id"])
            self.assertEqual(img.shape, (40, 60, 3))
            self.assertFalse(img.flags.writeable)
            self.assertIs(fixed_images.load(a["id"]), img)  # 快取命中
            c = fixed_images.store_bytes(_png(value=30), "two.png")
            self.assertNotEqual(a["id"], c["id"])
            thumb = fixed_images.thumbnail(c["id"], 24)
            self.assertIsNotNone(thumb)
            self.assertEqual(cv2.imdecode(np.frombuffer(thumb, np.uint8), cv2.IMREAD_COLOR).shape[1], 24)
            self.assertIsNone(fixed_images.load("nope"))
            self.assertIsNone(fixed_images.load("x" * fixed_images.ID_LEN))
            with self.assertRaises(fixed_images.FixedImageError):
                fixed_images.store_bytes(b"not a picture")
            with self.assertRaises(fixed_images.FixedImageError):
                fixed_images.path_of("../evil")
            self.assertTrue(fixed_images.remove(c["id"]))
            self.assertFalse(fixed_images.exists(c["id"]))
            self.assertEqual(fixed_images.ids_in_graph({"nodes": [{"params": {"images": [a, {"id": "short"}], "other": 1}}]}), {a["id"]})


class FixedImageToolTests(SimpleTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vs-fixed-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        fixed_tool.reset_cursors()
        self.override = override_settings(VISION=_tmp_assets(self.tmp))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.descs = [fixed_images.store_bytes(_png(value=v), f"p{v}.png") for v in (10, 20, 30)]

    def _run(self, params, **kw):
        node = {"id": "fx", "type": "fixed_image", "params": params}
        from apps.vision.tools import base

        ctx = base.ToolContext(run_id="r", flow_id=kw.get("flow_id", 5), node=node, inputs={}, context=kw.get("context", {}), moment=0.0, log=lambda *a, **k: None,
                               asset_path=lambda _i: None, grab=lambda _s: None, preview=kw.get("preview", False))
        return base.get("fixed_image").execute(ctx)

    def test_cycle_and_fixed_modes(self):
        seq = [self._run({"images": self.descs, "mode": "cycle"}).outputs["index"] for _ in range(4)]
        self.assertEqual(seq, [1, 2, 3, 1])
        # 試執行也推進：現場按一次試執行就看下一張
        self.assertEqual([self._run({"images": self.descs, "mode": "cycle"}, preview=True).outputs["index"] for _ in range(3)], [2, 3, 1])
        # 批次測試與 AI 試跑（flow_id ≤ 0）自己餵圖，不動產線那條流程的游標
        self.assertEqual([self._run({"images": self.descs, "mode": "cycle"}, flow_id=-1).outputs["index"] for _ in range(2)], [1, 1])
        self.assertEqual(self._run({"images": self.descs, "mode": "cycle"}).outputs["index"], 2)
        r = self._run({"images": self.descs, "mode": "fixed", "index": 3})
        self.assertEqual((r.outputs["index"], r.outputs["name"], r.outputs["count"]), (3, "p30.png", 3))
        self.assertEqual(int(r.outputs["image"][30, 30, 0]), 30)
        self.assertEqual(self._run({"images": self.descs, "mode": "fixed", "index": 99}).outputs["index"], 3)  # 超出範圍夾到最後一張
        # 批次／API 送圖優先
        inp = np.full((8, 8), 7, np.uint8)
        r = self._run({"images": self.descs}, context={"_input_image": inp})
        self.assertEqual(r.outputs["name"], "input")
        self.assertEqual(r.outputs["image"].shape, (8, 8))
        gray = self._run({"images": self.descs, "mode": "fixed", "index": 1, "convert": "gray"}).outputs["image"]
        self.assertEqual(gray.ndim, 2)
        with self.assertRaisesMessage(ToolError, "No picture uploaded"):
            self._run({"images": []})
        with self.assertRaisesMessage(ToolError, "missing from the store"):
            self._run({"images": [{"id": "z" * fixed_images.ID_LEN, "name": "gone", "width": 1, "height": 1, "size": 1}]})

    def test_reference_ports_take_pictures(self):
        scene = np.full((200, 300), 40, np.uint8)
        cv2.rectangle(scene, (120, 80), (170, 130), 220, -1)
        tpl = scene[70:140, 110:180].copy()
        r = run_tool("template_match", scene, {"threshold": 0.7, "max_matches": 1}, {"template_image": tpl})
        self.assertEqual(r.branch, "found", r.message)
        self.assertAlmostEqual(r.outputs["best_x"], 145, delta=2)
        with self.assertRaisesMessage(ToolError, "Connect a picture to 'template_image'"):
            run_tool("template_match", scene, {"threshold": 0.7})
        golden = scene.copy()
        bad = scene.copy()
        cv2.circle(bad, (60, 60), 12, 255, -1)
        r = run_tool("defect_diff", bad, {"align": "none", "threshold": 45, "min_area": 50}, {"template_image": golden})
        self.assertEqual(r.outputs["count"], 1)
        flat = np.full((200, 300), 180, np.uint8)
        r = run_tool("shading_correct", scene, {"mode": "flat_field", "target_level": 200}, {"flat_image": flat})
        self.assertEqual(r.outputs["image"].shape, scene.shape)
        found = run_tool("contour_find", scene, {"threshold_method": "otsu"})
        r = run_tool("contour_match", None, {"max_distance": 0.2}, {"contours": found.outputs["contours"], "template_image": scene})
        self.assertTrue(r.outputs["match_flag"])


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False})
class FixedImageApiTests(TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vs-fixed-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.override = override_settings(VISION={**settings.VISION, "ASSET_DIR": self.tmp, "PERSIST_RUNS": False})
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.client = Client()

    def _token(self) -> str:
        r = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "Admin12345"}), content_type="application/json")
        self.assertIn(r.status_code, (200, 201), r.content)
        return r.json()["token"]

    def test_upload_from_ref_and_files(self):
        r = self.client.post("/api/vision/fixed-images", {"files": [io.BytesIO(_png()), io.BytesIO(_png(value=50))]})
        self.assertEqual(r.status_code, 201, r.content)
        items = r.json()["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["width"], 60)
        r = self.client.post("/api/vision/fixed-images", {"files": [io.BytesIO(b"junk")]})
        self.assertEqual(r.status_code, 422)
        image_store.put("t:fixed:x", np.full((10, 12, 3), 90, np.uint8), flow_id=0, run_id="t", pinned=True)
        r = self.client.post("/api/vision/fixed-images/from-ref", data=json.dumps({"ref": "t:fixed:x", "name": "shot"}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["width"], 12)
        r = self.client.post("/api/vision/fixed-images/from-ref", data=json.dumps({"ref": "nope:1:img"}), content_type="application/json")
        self.assertEqual(r.status_code, 404)
        info = self.client.get("/api/vision/fixed-images").json()
        self.assertGreaterEqual(info["count"], 2)
        # 沒有流程引用：上傳的都是孤兒；內建範本的樣本圖與參考圖不算孤兒
        self.assertTrue({d["id"] for d in items} <= set(info["orphans"]))
        self.assertTrue(set(info["orphans"]).isdisjoint(demo.builtin_fixed_ids()))
        self.assertEqual(set(info["orphans"]), set(fixed_images.list_ids()) - demo.builtin_fixed_ids())
        # 取檔與縮圖：沒有使用者時 bootstrap 放行；建了使用者就要 token
        image_id = items[0]["id"]
        self.assertEqual(self.client.get(f"/api/vision/fixed-images/{image_id}").status_code, 200)
        token = self._token()
        self.assertTrue(User.objects.exists())
        self.assertEqual(self.client.get(f"/api/vision/fixed-images/{image_id}").status_code, 401)
        r = self.client.get(f"/api/vision/fixed-images/{image_id}/thumb?w=32&token={token}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertEqual(self.client.get(f"/api/vision/fixed-images/{'q' * 20}/thumb?token={token}").status_code, 404)

    def test_template_instantiates_with_sample_pictures_and_runs(self):
        from apps.vision import demo

        samples = demo.template_samples("circle_gauge")
        self.assertGreaterEqual(len(samples), 4)
        r = self.client.post("/api/vision/templates/builtin:circle_gauge/instantiate", data=json.dumps({"source_id": None}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["used_samples"])
        self.assertFalse(body["missing_source"])
        src = next(n for n in body["graph"]["nodes"] if n["id"] == "src")
        self.assertEqual(src["type"], "fixed_image")
        self.assertEqual([d["id"] for d in src["params"]["images"]], [d["id"] for d in samples])
        # 不用樣本：維持取像節點、來源缺
        r = self.client.post("/api/vision/templates/builtin:circle_gauge/instantiate", data=json.dumps({"source_id": None, "use_samples": False}), content_type="application/json")
        self.assertTrue(r.json()["missing_source"])
        self.assertEqual(next(n for n in r.json()["graph"]["nodes"] if n["id"] == "src")["type"], "image_source")
        # 建成流程跑四次：輪播四張，第 4 張 NG
        r = self.client.post("/api/vision/flows", data=json.dumps({"name": "fixed gauge", "graph": body["graph"]}), content_type="application/json")
        self.assertIn(r.status_code, (200, 201), r.content)
        fid = r.json()["id"]
        statuses = []
        for _ in range(4):
            rr = self.client.post(f"/api/vision/flows/{fid}/run?wait=1", data="{}", content_type="application/json")
            self.assertEqual(rr.status_code, 200, rr.content)
            statuses.append(rr.json()["status"])
        self.assertEqual(statuses, ["ok", "ok", "ok", "ng"])
        # 匯出帶圖、匯入還原
        flow = Flow.objects.get(pk=fid)
        doc = serialize.export_flow(flow)
        self.assertEqual(set(doc["fixed_images"]), {d["id"] for d in samples})
        for image_id in list(doc["fixed_images"]):
            fixed_images.remove(image_id)
        self.assertFalse(fixed_images.exists(samples[0]["id"]))
        doc["name"] = "fixed gauge imported"
        flow2, created = serialize.import_flow(doc)
        self.assertTrue(created)
        self.assertTrue(fixed_images.exists(samples[0]["id"]))
        self.assertEqual(base64.b64decode(doc["fixed_images"][samples[0]["id"]])[:4], b"\x89PNG")
        self.assertIn(samples[0]["id"], fixed_images.referenced_ids())
        self.assertNotIn(samples[0]["id"], fixed_images.orphans())
