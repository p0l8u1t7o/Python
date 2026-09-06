"""WP-01 形狀比對：建模、搜尋精度（旋轉／平移／變暗）、遮擋、多物件、與 shape_align 銜接、API、指令。全部合成影像。"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile

import cv2
import numpy as np
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from apps.vision import shapemodel
from apps.vision.images import store
from apps.vision.models import Asset
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool, save_png, temp_dir

PART = np.array([[-80, -60], [80, -60], [80, 20], [30, 60], [-80, 60]], np.float64)


def draw_part(img: np.ndarray, cx: float, cy: float, angle: float, scale: float = 1.0, bright: float = 1.0) -> None:
    """不對稱的亮工件（五邊形＋偏心暗孔），角度為畫面順時針。"""
    t = math.radians(angle)
    r = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    poly = (PART * scale @ r.T + [cx, cy]).round().astype(np.int32)
    cv2.fillPoly(img, [poly], int(200 * bright))
    hole = np.array([-30.0, -10.0]) * scale @ r.T + [cx, cy]
    cv2.circle(img, (int(round(hole[0])), int(round(hole[1]))), max(2, int(18 * scale)), int(90 * bright), -1)


def scene(cx: float, cy: float, angle: float, scale: float = 1.0, bright: float = 1.0, size: tuple[int, int] = (480, 640)) -> np.ndarray:
    img = np.full(size, 60, np.uint8)
    draw_part(img, cx, cy, angle, scale, bright)
    return img


def template_crop() -> np.ndarray:
    return scene(320, 240, 0)[240 - 90 : 240 + 90, 320 - 100 : 320 + 100]


def expected_centroid(model: dict, cx: float, cy: float, angle: float, scale: float = 1.0) -> tuple[float, float]:
    """模型重心（範本座標）依姿態換到場景座標：範本左上角在 (cx−100, cy−90)。"""
    c = model["centroid"]
    off = np.array([c[0] - 100.0, c[1] - 90.0]) * scale
    t = math.radians(angle)
    r = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    p = off @ r.T + [cx, cy]
    return float(p[0]), float(p[1])


class TeachTests(SimpleTestCase):
    def test_teach_builds_pyramid_and_meta(self):
        model = shapemodel.teach(template_crop())
        meta = shapemodel.describe(model)
        self.assertGreaterEqual(meta["levels"], 3)
        self.assertLessEqual(meta["levels"], 6)
        self.assertGreater(meta["points"][0], 300)
        self.assertLess(meta["points"][-1], 120)
        self.assertGreaterEqual(meta["points"][-1], 4)
        self.assertGreater(meta["radius"], 80)
        self.assertGreater(meta["contrast_high"], meta["contrast_low"])
        # 方向是單位向量
        d = model["levels"][0]["dirs"]
        self.assertTrue(np.allclose(np.hypot(d[:, 0], d[:, 1]), 1.0, atol=1e-3))
        with self.assertRaises(shapemodel.ShapeModelError):
            shapemodel.teach(np.full((60, 60), 100, np.uint8))  # 沒有邊緣
        with self.assertRaises(shapemodel.ShapeModelError):
            shapemodel.teach(np.zeros((4, 4), np.uint8))
        masked = shapemodel.teach(template_crop(), mask=np.pad(np.full((90, 200), 255, np.uint8), ((0, 90), (0, 0))))
        self.assertLess(masked["levels"][0]["count"], model["levels"][0]["count"])  # 排除下半部

    def test_save_load_cache(self):
        folder = temp_dir()
        try:
            model = shapemodel.teach(template_crop())
            path = os.path.join(folder, "m.npz")
            shapemodel.save(path, model)
            loaded = shapemodel.load(path)
            self.assertIs(shapemodel.load(path), loaded)
            self.assertEqual(len(loaded["levels"]), len(model["levels"]))
            self.assertTrue(np.array_equal(loaded["levels"][0]["pts"], model["levels"][0]["pts"]))
            self.assertEqual(loaded["centroid"], model["centroid"])
            np.savez(os.path.join(folder, "bad.npz"), foo=np.zeros(3))
            with self.assertRaises(shapemodel.ShapeModelError):
                shapemodel.load(os.path.join(folder, "bad.npz"))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class FindTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = shapemodel.teach(template_crop())

    def test_rotated_shifted_dark(self):
        img = scene(700, 500, 37, bright=0.6, size=(960, 1280))
        matches, info = shapemodel.find(img, self.model, min_score=0.7)
        self.assertEqual(len(matches), 1, info)
        ex, ey = expected_centroid(self.model, 700, 500, 37)
        m = matches[0]
        self.assertLess(math.hypot(m["cx"] - ex, m["cy"] - ey), 1.0)
        self.assertLess(abs(m["angle"] - 37), 0.5)
        self.assertGreater(m["score"], 0.9)

    def test_occlusion_scores_in_proportion(self):
        img = scene(600, 480, 0, size=(960, 1280))
        # 遮掉約 25% 的邊緣點：用模型點算出遮住左側多少寬度會蓋掉四分之一
        pts = self.model["levels"][0]["pts"]
        ex, ey = expected_centroid(self.model, 600, 480, 0)
        xs = np.sort(pts[:, 0] + ex)
        cut = float(xs[int(len(xs) * 0.25)])
        cv2.rectangle(img, (int(ex - 120), int(ey - 100)), (int(cut), int(ey + 100)), 60, -1)
        matches, _ = shapemodel.find(img, self.model, min_score=0.5)
        self.assertEqual(len(matches), 1)
        self.assertGreater(matches[0]["score"], 0.62)
        self.assertLess(matches[0]["score"], 0.85)
        self.assertLess(math.hypot(matches[0]["cx"] - ex, matches[0]["cy"] - ey), 1.5)
        full, _ = shapemodel.find(scene(600, 480, 0, size=(960, 1280)), self.model, min_score=0.5)
        self.assertGreater(full[0]["score"], 0.95)

    def test_five_objects_no_duplicates(self):
        img = np.full((960, 1280), 60, np.uint8)
        poses = [(200, 200, 0), (700, 200, 45), (1050, 300, -90), (300, 700, 120), (900, 750, 200)]
        for x, y, a in poses:
            draw_part(img, x, y, a)
        matches, _ = shapemodel.find(img, self.model, min_score=0.7, max_matches=5)
        self.assertEqual(len(matches), 5)
        for x, y, a in poses:
            ex, ey = expected_centroid(self.model, x, y, a)
            near = [m for m in matches if math.hypot(m["cx"] - ex, m["cy"] - ey) < 2.0]
            self.assertEqual(len(near), 1, f"pose {(x, y, a)}")
            da = abs(((near[0]["angle"] - a) + 180) % 360 - 180)
            self.assertLess(da, 1.0)
        # max_matches=1 只回最好的一個
        self.assertEqual(len(shapemodel.find(img, self.model, min_score=0.7, max_matches=1)[0]), 1)

    def test_scale_search_and_polarity(self):
        img = scene(400, 300, 15, scale=1.2, size=(720, 960))
        matches, _ = shapemodel.find(img, self.model, min_score=0.7, scale_min=0.9, scale_max=1.3)
        self.assertEqual(len(matches), 1)
        self.assertAlmostEqual(matches[0]["scale"], 1.2, delta=0.06)
        ex, ey = expected_centroid(self.model, 400, 300, 15, 1.2)
        self.assertLess(math.hypot(matches[0]["cx"] - ex, matches[0]["cy"] - ey), 2.5)
        inverted = 255 - scene(320, 240, 0)
        self.assertEqual(len(shapemodel.find(inverted, self.model, min_score=0.7, polarity=True)[0]), 0)
        self.assertEqual(len(shapemodel.find(inverted, self.model, min_score=0.7, polarity=False)[0]), 1)

    def test_clutter_noise_and_not_found(self):
        rng = np.random.default_rng(0)
        img = scene(500, 400, -25, size=(960, 1280)).astype(np.int16) + rng.normal(0, 12, (960, 1280)).astype(np.int16)
        img = np.clip(img, 0, 255).astype(np.uint8)
        for _ in range(30):
            x, y = rng.integers(0, 1200, 2)
            cv2.rectangle(img, (int(x), int(y)), (int(x) + 30, int(y) + 30), 170, -1)
        matches, _ = shapemodel.find(img, self.model, min_score=0.6)
        self.assertEqual(len(matches), 1)
        ex, ey = expected_centroid(self.model, 500, 400, -25)
        self.assertLess(math.hypot(matches[0]["cx"] - ex, matches[0]["cy"] - ey), 1.5)
        self.assertEqual(shapemodel.find(np.full((480, 640), 60, np.uint8), self.model, min_score=0.7)[0], [])
        with self.assertRaises(shapemodel.ShapeModelError):
            shapemodel.find(img, self.model, angle_extent=0)
        with self.assertRaises(shapemodel.ShapeModelError):
            shapemodel.find(img, self.model, scale_min=1.5, scale_max=1.0)

    def test_early_stop_does_not_lose_the_match(self):
        img = scene(700, 500, 37, bright=0.6, size=(960, 1280))
        for g in (0.0, 0.5, 1.0):
            matches, _ = shapemodel.find(img, self.model, min_score=0.7, greediness=g)
            self.assertEqual(len(matches), 1, f"greediness {g}")


class ToolTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.folder = temp_dir()
        cls.model = shapemodel.teach(template_crop())
        cls.path = os.path.join(cls.folder, "model.npz")
        shapemodel.save(cls.path, cls.model)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)
        super().tearDownClass()

    def test_tool_outputs_feed_shape_align(self):
        img = scene(700, 500, 37, bright=0.6, size=(960, 1280))
        r = run_tool("shape_match", img, {"model": "m", "min_score": 0.7}, assets={"m": self.path})
        self.assertEqual((r.branch, r.status), ("found", "ok"))
        self.assertEqual(r.outputs["count"], 1)
        m = r.outputs["matches"][0]
        self.assertEqual(set(m), {"x", "y", "w", "h", "cx", "cy", "score", "angle", "scale"})
        ex, ey = expected_centroid(self.model, 700, 500, 37)
        self.assertAlmostEqual(r.outputs["best_x"], ex, delta=1.0)
        self.assertAlmostEqual(r.outputs["best_y"], ey, delta=1.0)
        self.assertAlmostEqual(r.outputs["best_angle"], 37, delta=0.5)
        self.assertEqual({o["kind"] for o in r.overlays}, {"points", "rect", "point"})
        self.assertIn("per_level", r.detail)
        # 接 shape_align：與 template_match.matches 同格式
        ref = expected_centroid(self.model, 320, 240, 0)
        al = run_tool("shape_align", None, {"ref_x": ref[0], "ref_y": ref[1], "ref_angle": 0}, {"matches": r.outputs["matches"]})
        self.assertAlmostEqual(al.outputs["transform"]["dtheta"], 37, delta=0.5)

    def test_tool_roi_and_errors(self):
        img = scene(700, 500, 10, size=(960, 1280))
        roi = {"shape": "rect", "x": 500, "y": 300, "w": 400, "h": 400}
        r = run_tool("shape_match", img, {"model": "m", "roi": roi, "angle_start": -30, "angle_extent": 60}, assets={"m": self.path})
        ex, ey = expected_centroid(self.model, 700, 500, 10)
        self.assertAlmostEqual(r.outputs["best_x"], ex, delta=1.0)  # 座標回全圖
        self.assertTrue(any(o["kind"] == "rect" and o.get("label") == "search" for o in r.overlays))
        poly = {"shape": "polygon", "points": [[500, 300], [900, 300], [900, 700], [500, 700]]}
        self.assertEqual(run_tool("shape_match", img, {"model": "m", "roi": poly}, assets={"m": self.path}).outputs["count"], 1)
        miss = run_tool("shape_match", img, {"model": "m", "roi": {"shape": "rect", "x": 0, "y": 0, "w": 300, "h": 200}}, assets={"m": self.path})
        self.assertEqual((miss.branch, miss.status, miss.outputs["count"]), ("not_found", "ng", 0))
        self.assertTrue(math.isnan(miss.outputs["best_x"]))
        with self.assertRaises(ToolError):
            run_tool("shape_match", img, {})
        with self.assertRaises(ToolError):
            run_tool("shape_match", img, {"model": "m", "angle_extent": 0}, assets={"m": self.path})
        with self.assertRaises(ToolError):
            run_tool("shape_match", img, {"model": "m", "scale_min": 2, "scale_max": 1}, assets={"m": self.path})
        with self.assertRaises(ToolError):
            run_tool("shape_match", img, {"model": "x"}, assets={"x": save_png(img, self.folder, "png.png")})


def _vision(tmp: str) -> dict:
    cfg = dict(settings.VISION)
    cfg["ASSET_DIR"] = tmp
    cfg["PERSIST_RUNS"] = False
    return cfg


class ApiTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vs-shape-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_create_from_asset_and_ref(self):
        with override_settings(VISION=_vision(self.tmp)):
            src = Asset.objects.create(name="part", kind="image", path=save_png(scene(320, 240, 0), self.tmp, "part.png"))
            region = {"shape": "rect", "x": 220, "y": 150, "w": 200, "h": 180}
            r = self.client.post("/api/vision/assets/shape-model", data=json.dumps({"asset_id": str(src.id), "region": region, "name": "bracket", "min_contrast": 10}), content_type="application/json")
            self.assertEqual(r.status_code, 201, r.content)
            body = r.json()
            self.assertEqual(body["kind"], "file")
            self.assertEqual(body["meta"]["region"], region)
            self.assertGreater(body["meta"]["points"][0], 300)
            asset = Asset.objects.get(pk=body["id"])
            info = self.client.get(f"/api/vision/assets/{asset.id}/shape-model").json()
            self.assertGreater(len(info["points"]), 100)
            self.assertEqual(info["meta"]["levels"], body["meta"]["levels"])
            preview = self.client.get(f"/api/vision/assets/{asset.id}/shape-model/preview")
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview["Content-Type"], "image/png")
            # 工具用這個資產找旋轉的件
            rr = run_tool("shape_match", scene(700, 500, 37, size=(960, 1280)), {"model": str(asset.id)}, assets={str(asset.id): asset.path})
            self.assertEqual(rr.outputs["count"], 1)
            # 從快取影像 + 排除區
            ref = "shapetest:cap:image"
            store.put(ref, scene(320, 240, 0), flow_id=0, run_id="shapetest", pinned=True)
            r = self.client.post("/api/vision/assets/shape-model", data=json.dumps({"ref": ref, "region": region, "exclude": {"shape": "circle", "cx": 290, "cy": 230, "r": 25}}), content_type="application/json")
            self.assertEqual(r.status_code, 201, r.content)
            self.assertLess(r.json()["meta"]["points"][0], body["meta"]["points"][0])  # 孔的邊緣被排除
            # 錯誤
            self.assertEqual(self.client.post("/api/vision/assets/shape-model", data=json.dumps({"region": region}), content_type="application/json").status_code, 404)
            self.assertEqual(self.client.post("/api/vision/assets/shape-model", data=json.dumps({"asset_id": str(src.id), "region": {"bad": 1}}), content_type="application/json").status_code, 422)
            flat = Asset.objects.create(name="flat", kind="image", path=save_png(np.full((100, 100), 90, np.uint8), self.tmp, "flat.png"))
            self.assertEqual(self.client.post("/api/vision/assets/shape-model", data=json.dumps({"asset_id": str(flat.id)}), content_type="application/json").status_code, 422)
            self.assertEqual(self.client.get(f"/api/vision/assets/{src.id}/shape-model").status_code, 422)


class CommandTests(TestCase):
    def test_shape_model_command(self):
        tmp = tempfile.mkdtemp(prefix="vs-shape-cmd-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = save_png(scene(320, 240, 0), tmp, "part.png")
        with override_settings(VISION=_vision(tmp)):
            call_command("shape_model", name="cmd model", image=path, region=json.dumps({"shape": "rect", "x": 220, "y": 150, "w": 200, "h": 180}))
        asset = Asset.objects.get(name="cmd model")
        self.assertEqual(asset.kind, "file")
        self.assertGreaterEqual(asset.meta["levels"], 3)
        self.assertEqual(shapemodel.load(asset.path)["width"], 200)
