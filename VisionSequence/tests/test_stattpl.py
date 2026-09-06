"""WP-07 統計範本比對：建模、defect_stat 工具、與 defect_diff 的誤判對照、API、管理指令。全部用合成影像。"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile

import cv2
import numpy as np
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from apps.vision import stattpl
from apps.vision.models import Asset, BatchSet, Flow
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool, save_png, temp_dir


def good_part(seed: int, h: int = 240, w: int = 320, jitter: float = 10.0, shift: int = 3) -> np.ndarray:
    """合成良品：亮板＋棋盤紋理＋暗孔；整張亮度擾動 ±jitter、雜訊 σ3、整數位移 ±shift。"""
    r = np.random.default_rng(seed)
    img = np.full((h, w), 120, np.float64)
    cv2.rectangle(img, (50, 40), (270, 200), 200, -1)
    yy, xx = np.mgrid[0:h, 0:w]
    img[(yy // 8 + xx // 8) % 2 == 0] += 12
    cv2.circle(img, (160, 120), 30, 60, -1)
    img += r.uniform(-jitter, jitter)
    img += r.normal(0, 3, img.shape)
    dx, dy = int(r.integers(-shift, shift + 1)), int(r.integers(-shift, shift + 1))
    m = np.array([[1, 0, dx], [0, 1, dy]], np.float32)
    img = cv2.warpAffine(img.astype(np.float32), m, (w, h), borderMode=cv2.BORDER_REPLICATE)
    return np.clip(img, 0, 255).astype(np.uint8)


def stained(seed: int, delta: int = 40, jitter: float = 10.0) -> np.ndarray:
    img = good_part(seed, jitter=jitter)
    cv2.circle(img, (100, 75), 8, 200 - delta, -1)
    return img


class BuildTests(SimpleTestCase):
    def test_build_aligns_and_reports(self):
        payload, meta = stattpl.build([good_part(i) for i in range(30)], None, "phase")
        self.assertEqual(payload["mean"].shape, (240, 320))
        self.assertEqual(meta["samples"], 30)
        self.assertGreater(meta["shift_max"], 1.0)
        self.assertLess(meta["shift_max"], 6.0)
        self.assertGreater(meta["valid_ratio"], 0.9)
        self.assertLess(meta["valid_ratio"], 1.0)  # 位移後的邊界標為無效
        # 逐像素 std 主要來自 ±10 的整張亮度擾動（均勻分布 σ≈5.8）＋雜訊
        self.assertGreater(meta["std_p50"], 4.0)
        self.assertLess(meta["std_p50"], 9.0)
        self.assertGreater(meta["align_response_min"], 0.5)
        # 平坦區的 mean 對齊後接近真值（板 200＋紋理一半 → 206 附近；孔 60）
        self.assertAlmostEqual(float(payload["mean"][120, 160]), 60, delta=6)

    def test_region_and_errors(self):
        region = {"shape": "circle", "cx": 160, "cy": 120, "r": 50}
        payload, meta = stattpl.build([good_part(i) for i in range(5)], region, "none")
        self.assertEqual(payload["mean"].shape, (100, 100))
        self.assertEqual(meta["offset"], [110, 70])
        self.assertLess(meta["valid_ratio"], 0.85)  # 圓形遮罩外無效
        self.assertEqual(meta["region"], region)
        with self.assertRaises(stattpl.StatTemplateError):
            stattpl.build([good_part(0), good_part(1)])
        with self.assertRaises(stattpl.StatTemplateError):
            stattpl.build([good_part(0), good_part(1), good_part(2, h=200)])
        with self.assertRaises(stattpl.StatTemplateError):
            stattpl.build([good_part(i, shift=6) for i in range(6)], None, "phase", max_shift=0.5)

    def test_save_load_cache(self):
        folder = temp_dir()
        try:
            payload, _ = stattpl.build([good_part(i) for i in range(4)])
            path = os.path.join(folder, "t.npz")
            stattpl.save(path, payload)
            first = stattpl.load(path)
            self.assertIs(stattpl.load(path), first)  # mtime／size 沒變 → 同一物件
            self.assertTrue(np.array_equal(first["mean"], payload["mean"]))
            stattpl.save(path, stattpl.build([good_part(i + 10) for i in range(4)])[0])
            self.assertIsNot(stattpl.load(path), first)
            with self.assertRaises(stattpl.StatTemplateError):
                stattpl.load(os.path.join(folder, "missing.npz"))
            np.savez(os.path.join(folder, "bad.npz"), foo=np.zeros(3))
            with self.assertRaises(stattpl.StatTemplateError):
                stattpl.load(os.path.join(folder, "bad.npz"))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class DefectStatToolTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.folder = temp_dir()
        payload, _ = stattpl.build([good_part(i) for i in range(30)], None, "phase")
        cls.model = os.path.join(cls.folder, "model.npz")
        stattpl.save(cls.model, payload)
        cls.template = save_png(good_part(0), cls.folder, "golden.png")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)
        super().tearDownClass()

    def test_new_good_parts_pass_and_stain_is_caught(self):
        for i in range(100, 120):
            r = run_tool("defect_stat", good_part(i), {"model": "m", "sigma": 4, "min_area": 20}, assets={"m": self.model})
            self.assertEqual(r.outputs["count"], 0, f"good part {i} flagged: {r.message}")
            self.assertEqual(r.branch, "ok")
            self.assertLess(r.outputs["max_sigma"], 6.0)  # 單一像素的極值（7 萬像素取最大），不構成缺陷
        r = run_tool("defect_stat", stained(200), {"model": "m", "sigma": 4, "min_area": 20}, assets={"m": self.model})
        self.assertEqual(r.outputs["count"], 1)
        self.assertEqual((r.branch, r.status), ("defect", "ng"))
        d = r.outputs["regions"][0]
        self.assertAlmostEqual(d["cx"], 100, delta=3)
        self.assertAlmostEqual(d["cy"], 75, delta=3)
        self.assertGreater(d["peak_sigma"], 5)
        self.assertGreater(r.outputs["max_sigma"], 5)
        self.assertEqual(r.outputs["defect_mask"].shape, (240, 320))
        self.assertEqual(r.outputs["deviation"].dtype, np.uint8)
        self.assertTrue(any(o["kind"] == "rect" and o["color"] == "#ef4444" for o in r.overlays))
        darker = run_tool("defect_stat", stained(200), {"model": "m", "sigma": 4, "direction": "brighter"}, assets={"m": self.model})
        self.assertEqual(darker.outputs["count"], 0)  # 污漬是變暗，只看變亮就抓不到

    def test_false_positive_comparison_with_defect_diff(self):
        """規格要求的對照：同一組 20 張新良品，defect_stat 誤判 0；defect_diff 在門檻 ≤ 亮度擾動幅度時會誤判。"""
        # 兩邊都拿「亮度擾動 ±15」這個分布：統計範本由 30 張建；單張良品範本取一張偏亮 +14 的（現場拍良品時就是抽到某一張）
        payload, _ = stattpl.build([good_part(i, jitter=15.0) for i in range(400, 430)], None, "phase")
        model = os.path.join(self.folder, "harsh.npz")
        stattpl.save(model, payload)
        template = save_png(np.clip(good_part(0, jitter=0.0).astype(np.int32) + 14, 0, 255).astype(np.uint8), self.folder, "golden14.png")
        harsh = [good_part(i, jitter=15.0) for i in range(300, 320)]
        stat_fp = sum(run_tool("defect_stat", im, {"model": "h", "sigma": 4}, assets={"h": model}).outputs["count"] > 0 for im in harsh)
        diff_fp = {thr: sum(run_tool("defect_diff", im, {"template": "t", "threshold": thr, "min_area": 20}, assets={"t": template}).outputs["count"] > 0 for im in harsh) for thr in (20, 30, 40)}
        self.assertEqual(stat_fp, 0)
        self.assertGreater(diff_fp[20], 0)  # 單張良品：門檻 20 擋不住 ±15 的亮度擾動
        # 同時 defect_stat 仍抓得到 Δ50 污漬（σ 門檻不必為了容忍擾動而放鬆）
        self.assertEqual(run_tool("defect_stat", stained(321, 50), {"model": "h", "sigma": 4}, assets={"h": model}).outputs["count"], 1)

    def test_sigma_floor_and_size_mismatch(self):
        flat = np.full((240, 320), 150, np.uint8)
        payload, _ = stattpl.build([flat, flat, flat, flat], None, "none")  # std 全 0
        path = os.path.join(self.folder, "flat.npz")
        stattpl.save(path, payload)
        noisy = np.clip(flat.astype(np.int32) + np.random.default_rng(0).integers(-2, 3, flat.shape), 0, 255).astype(np.uint8)
        r = run_tool("defect_stat", noisy, {"model": "f", "sigma": 3, "min_sigma_floor": 3, "align": "none"}, assets={"f": path})
        self.assertEqual(r.outputs["count"], 0)  # ±2 灰階雜訊在 floor 3 之下
        r = run_tool("defect_stat", noisy, {"model": "f", "sigma": 3, "min_sigma_floor": 0, "align": "none", "morph": 0, "min_area": 0}, assets={"f": path})
        self.assertGreater(r.outputs["count"], 0)  # 沒有 floor：std 0 → 滿畫面假缺陷
        with self.assertRaises(ToolError) as cm:
            run_tool("defect_stat", good_part(1)[:120, :160], {"model": "m"}, assets={"m": self.model})
        self.assertIn("160×120", str(cm.exception))
        self.assertIn("320×240", str(cm.exception))
        with self.assertRaises(ToolError):
            run_tool("defect_stat", good_part(1), {})
        with self.assertRaises(ToolError):
            run_tool("defect_stat", good_part(1), {"model": "x"}, assets={"x": self.template})  # PNG 不是統計範本

    def test_roi_matches_template_region(self):
        region = {"shape": "rect", "x": 40, "y": 30, "w": 240, "h": 180}
        payload, _ = stattpl.build([good_part(i) for i in range(12)], region, "phase")
        path = os.path.join(self.folder, "roi.npz")
        stattpl.save(path, payload)
        r = run_tool("defect_stat", stained(500), {"model": "r", "roi": region, "sigma": 4}, assets={"r": path})
        self.assertEqual(r.outputs["count"], 1)
        self.assertAlmostEqual(r.outputs["regions"][0]["cx"], 100, delta=3)  # 座標回到全圖
        self.assertEqual(r.outputs["defect_mask"].shape, (240, 320))


def _vision(tmp: str) -> dict:
    cfg = dict(settings.VISION)
    cfg["ASSET_DIR"] = tmp
    cfg["PERSIST_RUNS"] = False
    return cfg


class ApiTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vs-stat-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _png(self, img: np.ndarray) -> io.BytesIO:
        ok, buf = cv2.imencode(".png", img)
        assert ok
        f = io.BytesIO(buf.tobytes())
        f.name = "good.png"
        return f

    def test_create_from_uploads_and_read_back(self):
        with override_settings(VISION=_vision(self.tmp)):
            files = [self._png(good_part(i)) for i in range(12)]
            r = self.client.post("/api/vision/assets/stat-template", data={"images": files, "name": "print stat", "region": json.dumps({"shape": "rect", "x": 40, "y": 30, "w": 240, "h": 180})})
            self.assertEqual(r.status_code, 201, r.content)
            body = r.json()
            self.assertEqual(body["kind"], "file")
            self.assertEqual(body["meta"]["samples"], 12)
            self.assertEqual((body["meta"]["width"], body["meta"]["height"]), (240, 180))
            asset = Asset.objects.get(pk=body["id"])
            self.assertTrue(asset.path.endswith(".npz"))
            info = self.client.get(f"/api/vision/assets/{asset.id}/stat-template").json()
            self.assertEqual(info["meta"]["samples"], 12)
            self.assertEqual(len(info["shifts"]), 12)
            for which in ("mean", "std", "valid"):
                img = self.client.get(f"/api/vision/assets/{asset.id}/stat-template/{which}")
                self.assertEqual(img.status_code, 200, which)
                self.assertEqual(img["Content-Type"], "image/png")
            self.assertEqual(self.client.get(f"/api/vision/assets/{asset.id}/stat-template/nope").status_code, 404)
            # 工具用這個資產
            rr = run_tool("defect_stat", stained(700), {"model": str(asset.id), "roi": {"shape": "rect", "x": 40, "y": 30, "w": 240, "h": 180}, "sigma": 4}, assets={str(asset.id): asset.path})
            self.assertEqual(rr.outputs["count"], 1)
            # 太少張、壞區域、非統計範本
            self.assertEqual(self.client.post("/api/vision/assets/stat-template", data={"images": [self._png(good_part(0)), self._png(good_part(1))]}).status_code, 422)
            self.assertEqual(self.client.post("/api/vision/assets/stat-template", data={"images": [self._png(good_part(i)) for i in range(3)], "region": "{bad"}).status_code, 422)
            png = Asset.objects.create(name="png", kind="image", path=save_png(good_part(0), self.tmp, "p.png"))
            self.assertEqual(self.client.get(f"/api/vision/assets/{png.id}/stat-template").status_code, 422)

    def test_create_from_batch_set(self):
        with override_settings(VISION=_vision(self.tmp)):
            flow = Flow.objects.create(name="f", graph={"nodes": [], "edges": []})
            items = []
            for i in range(8):
                path = save_png(good_part(i), self.tmp, f"b{i}.png")
                items.append({"index": i, "name": f"b{i}.png", "path": path, "width": 320, "height": 240, "expected": "ng" if i == 7 else "ok"})
            bs = BatchSet.objects.create(flow=flow, name="set", images=items, image_count=len(items))
            r = self.client.post("/api/vision/assets/stat-template", data={"batch_set_id": bs.id, "name": "from set"})
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual(r.json()["meta"]["samples"], 7)  # 標 NG 的那張不算
            r = self.client.post("/api/vision/assets/stat-template", data={"batch_set_id": bs.id, "only_ok": "false"})
            self.assertEqual(r.json()["meta"]["samples"], 8)
            self.assertEqual(self.client.post("/api/vision/assets/stat-template", data={"batch_set_id": 99999}).status_code, 404)


class CommandTests(TestCase):
    def test_stat_template_command(self):
        tmp = tempfile.mkdtemp(prefix="vs-stat-cmd-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        folder = os.path.join(tmp, "good")
        os.makedirs(folder)
        for i in range(6):
            save_png(good_part(i), folder, f"{i:02d}.png")
        with open(os.path.join(folder, "notes.txt"), "w") as fh:
            fh.write("skip me")
        out = io.StringIO()
        with override_settings(VISION=_vision(tmp)):
            call_command("stat_template", name="cmd stat", folder=folder, region=json.dumps({"shape": "rect", "x": 0, "y": 0, "w": 160, "h": 120}), stdout=out)
        asset = Asset.objects.get(name="cmd stat")
        self.assertEqual(asset.kind, "file")
        self.assertEqual(asset.meta["samples"], 6)
        self.assertEqual((asset.meta["width"], asset.meta["height"]), (160, 120))
        self.assertIn("samples=6", out.getvalue())
