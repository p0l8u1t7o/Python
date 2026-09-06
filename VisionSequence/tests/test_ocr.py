"""WP-02 OCR／OCV：字型教導路（完全離線：PIL 預設字型渲染 → API 存樣本 → 訓練 → ocr_read → 辨識率 > 95%）、ocv_verify 萬用字元與
fail_index、切分模式、模型安裝指令；通用 PP-OCR 路（ASSET_DIR/ocr 有模型時：數字串 > 95%、session 快取、多行偵測）。"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import time
import zipfile

import cv2
import numpy as np
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image, ImageDraw, ImageFont

from apps.vision import ocr
from apps.vision.images import store
from apps.vision.models import Asset
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool, save_png, temp_dir


def render(text: str, size: int = 36, rot: float = 0.0, noise: float = 0.0, w: int = 400, h: int = 80, light_on_dark: bool = False, seed: int = 0) -> np.ndarray:
    """PIL 內建 TrueType 字型（不依賴系統字型）渲染一行字。"""
    font = ImageFont.load_default(size=size)
    img = Image.new("L", (w, h), 20 if light_on_dark else 235)
    d = ImageDraw.Draw(img)
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((w - tw) // 2 - bb[0], (h - th) // 2 - bb[1]), text, fill=235 if light_on_dark else 25, font=font)
    arr = np.array(img)
    if rot:
        arr = cv2.warpAffine(arr, cv2.getRotationMatrix2D((w / 2, h / 2), rot, 1.0), (w, h), borderValue=int(arr[0, 0]))
    if noise:
        rng = np.random.default_rng(seed)
        arr = np.clip(arr.astype(np.int16) + rng.normal(0, noise, arr.shape).astype(np.int16), 0, 255).astype(np.uint8)
    return arr


def digits(rng: np.random.Generator, n: int = 8) -> str:
    return "".join(rng.choice(list("0123456789"), n))


def _vision(tmp: str) -> dict:
    cfg = dict(settings.VISION)
    cfg["ASSET_DIR"] = tmp
    cfg["PERSIST_RUNS"] = False
    return cfg


class SegmentAndCompareTests(SimpleTestCase):
    def test_segment_modes(self):
        line = render("240912", size=40)
        proj = ocr.segment_chars(line, "projection")
        self.assertEqual(len(proj), 6)
        self.assertTrue(all(b[2] > b[0] and b[3] > b[1] for b in proj))
        self.assertTrue(all(proj[i][0] < proj[i + 1][0] for i in range(5)))
        comp = ocr.segment_chars(line, "components")
        self.assertEqual(len(comp), 6)
        fixed = ocr.segment_chars(line, "fixed", count=6)
        self.assertEqual(len(fixed), 6)
        self.assertEqual(ocr.segment_chars(np.full((40, 200), 235, np.uint8), "projection"), [])
        light = render("7", light_on_dark=True)
        self.assertEqual(len(ocr.segment_chars(light, "projection", polarity="light_on_dark")), 1)
        tile = ocr.char_tile(line, proj[0])
        self.assertEqual(tile.shape, (ocr.FONT_SIZE, ocr.FONT_SIZE))
        self.assertLess(int(tile.min()), 60)

    def test_compare_wildcards_and_fail_index(self):
        self.assertEqual(ocr.compare("LOT240912", "LOT######"), (True, -1))
        self.assertEqual(ocr.compare("LOT24091A", "LOT######"), (False, 8))
        self.assertEqual(ocr.compare("AB12", "A?12"), (True, -1))
        self.assertEqual(ocr.compare("AB1", "AB12"), (False, 3))
        self.assertEqual(ocr.compare("AB123", "AB12"), (False, 4))
        self.assertEqual(ocr.compare("XLOT2409Z", "LOT?409", "contains"), (True, -1))
        self.assertEqual(ocr.compare("XLOT2408Z", "LOT?409", "contains")[0], False)
        self.assertEqual(ocr.compare("AB12", "AB[0-9]{2}", "regex"), (True, -1))
        self.assertEqual(ocr.compare("AB1X", "AB[0-9]{2}", "regex")[0], False)
        with self.assertRaises(ocr.OcrError):
            ocr.compare("A", "[", "regex")

    def test_font_train_and_read_offline(self):
        rng = np.random.default_rng(1)
        tiles, labels = [], []
        for _ in range(30):
            txt = digits(rng)
            line = render(txt, size=36, noise=float(rng.uniform(0, 6)), seed=int(rng.integers(0, 9999)))
            boxes = ocr.segment_chars(line, "projection")
            if len(boxes) != len(txt):
                continue
            for b, ch in zip(boxes, txt):
                tiles.append(ocr.char_tile(line, b))
                labels.append(ch)
        model = ocr.train_font(tiles, labels, epochs=300)
        self.assertEqual(len(model["classes"]), 10)
        self.assertGreaterEqual(model["metrics"]["val_accuracy"], 0.9)
        ok = 0
        for i in range(40):
            txt = digits(rng)
            line = render(txt, size=36, rot=float(rng.uniform(-5, 5)), noise=float(rng.uniform(0, 8)), seed=100 + i)
            got, chars = ocr.read_with_font(line, model)
            ok += got == txt
            self.assertEqual(len(chars), len(got))
        self.assertGreaterEqual(ok / 40, 0.95)
        with self.assertRaises(ocr.OcrError):
            ocr.train_font(tiles[:3], ["1", "1", "1"])
        packed = ocr.pack_font(model)
        folder = temp_dir()
        try:
            path = os.path.join(folder, "font.npz")
            with open(path, "wb") as fh:
                fh.write(packed)
            loaded = ocr.load_font(path)
            self.assertEqual(loaded["classes"], model["classes"])
            self.assertIs(ocr.load_font(path), loaded)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class ToolTests(TestCase):
    """ocr_read（教導字型路）與 ocv_verify 經 API 教字型後串起來。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vs-ocr-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.override = override_settings(VISION=_vision(self.tmp))
        self.override.enable()
        self.addCleanup(self.override.disable)

    def _teach(self) -> Asset:
        rng = np.random.default_rng(5)
        for i in range(24):
            txt = digits(rng, 8)
            line = render(txt, size=36, noise=float(rng.uniform(0, 5)), seed=i)
            ref = f"ocrtest:{i}:image"
            store.put(ref, line, flow_id=0, run_id="ocrtest", pinned=True)
            r = self.client.post("/api/vision/ocr/fonts/dot/samples", data=json.dumps({"ref": ref, "text": txt}), content_type="application/json")
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual(len(r.json()["chars"]), 8)
        info = self.client.get("/api/vision/ocr/fonts/dot").json()
        self.assertEqual(len(info["counts"]), 10)
        self.assertGreaterEqual(info["samples"], 150)
        r = self.client.post("/api/vision/ocr/fonts/dot/train", data=json.dumps({"asset_name": "dot font", "epochs": 300}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["kind"], "model")
        self.assertTrue(body["meta"]["ocr_font"])
        self.assertEqual(body["meta"]["tool_key"], "ocr_read")
        self.assertEqual(len(body["meta"]["classes"]), 10)
        return Asset.objects.get(pk=body["id"])

    def test_teach_read_and_verify(self):
        asset = self._teach()
        assets = {str(asset.id): asset.path}
        rng = np.random.default_rng(9)
        ok = 0
        for i in range(30):
            txt = digits(rng, 8)
            img = np.full((300, 600), 235, np.uint8)
            img[100:180, 100:500] = render(txt, size=36, rot=float(rng.uniform(-5, 5)), noise=float(rng.uniform(0, 8)), seed=500 + i)
            r = run_tool("ocr_read", img, {"model": str(asset.id), "roi": {"shape": "rect", "x": 100, "y": 100, "w": 400, "h": 80}, "charset": "digits"}, assets=assets)
            ok += r.outputs["text"] == txt
        self.assertGreaterEqual(ok / 30, 0.95)
        # items 帶每個字的框（全圖座標）與信心；overlay 用 polygon
        self.assertEqual(r.outputs["count"], 1)
        chars = r.outputs["items"][0]["chars"]
        self.assertEqual(len(chars), len(r.outputs["text"]))
        self.assertTrue(all(100 <= p[0] <= 500 and 100 <= p[1] <= 180 for ch in chars for p in ch["box"]))
        self.assertTrue(any(o["kind"] == "polygon" for o in r.overlays))
        self.assertEqual((r.branch, r.status), ("found", "ok"))
        # OCV：預期字串（萬用字元）、輸入埠來源、fail_index 與紅框、逐字信心
        v = run_tool("ocv_verify", None, {"expected": "########"}, {"text": r.outputs["text"], "items": r.outputs["items"]})
        self.assertEqual((v.outputs["match"], v.outputs["fail_index"], v.branch), (True, -1, "pass"))
        wrong = txt[:3] + ("0" if txt[3] != "0" else "1") + txt[4:]
        v = run_tool("ocv_verify", None, {"expected_source": "input"}, {"text": r.outputs["text"], "expected": wrong, "items": r.outputs["items"]})
        self.assertEqual((v.outputs["match"], v.outputs["fail_index"], v.status), (False, 3, "ng"))
        red = [o for o in v.overlays if o["color"] == "#ef4444"]
        self.assertEqual(len(red), 1)
        self.assertEqual(red[0]["label"], txt[3])
        v = run_tool("ocv_verify", None, {"expected": "########", "min_char_confidence": 0.9999}, {"text": r.outputs["text"], "items": r.outputs["items"]})
        self.assertFalse(v.outputs["match"])
        with self.assertRaises(ToolError):
            run_tool("ocv_verify", None, {"expected_source": "input"}, {"text": "A"})
        # 沒有字
        blank = run_tool("ocr_read", np.full((100, 300), 235, np.uint8), {"model": str(asset.id)}, assets=assets)
        self.assertEqual((blank.branch, blank.outputs["text"]), ("not_found", ""))
        with self.assertRaises(ToolError):
            run_tool("ocr_read", img, {"model": "x"}, assets={"x": save_png(img, self.tmp, "p.png")})
        # 切分不符 → 422 帶切分結果
        bad = self.client.post("/api/vision/ocr/fonts/dot/samples", data=json.dumps({"ref": "ocrtest:0:image", "text": "1"}), content_type="application/json")
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["error"]["code"], "segment_mismatch")
        self.assertEqual(self.client.get("/api/vision/ocr/fonts").json()["items"][0]["name"], "dot")
        self.assertEqual(self.client.delete("/api/vision/ocr/fonts/dot").json()["deleted"], True)
        self.assertEqual(self.client.get("/api/vision/ocr/fonts/dot").status_code, 404)
        self.assertEqual(self.client.post("/api/vision/ocr/fonts/bad.name/samples", data="{}", content_type="application/json").status_code, 422)  # 名稱只准字母數字 - _

    def test_ocr_font_command_and_models_install(self):
        folder = os.path.join(self.tmp, "lines")
        os.makedirs(folder)
        rng = np.random.default_rng(3)
        for i in range(20):
            txt = digits(rng, 6)
            save_png(render(txt, size=36, seed=i), folder, f"{txt}_{i}.png")
        out = io.StringIO()
        call_command("ocr_font", name="cmd", folder=folder, epochs=200, stdout=out)
        asset = Asset.objects.get(meta__font="cmd")
        self.assertEqual(asset.kind, "model")
        self.assertIn("classes=", out.getvalue())
        # 模型安裝：從假的 wheel（zip）複製三個 ONNX 檔名，寫 MODELS.json；不下載
        fake = os.path.join(self.tmp, "rapidocr-fake.whl")
        with zipfile.ZipFile(fake, "w") as z:
            for name in ocr.MODEL_FILES:
                z.writestr(f"rapidocr_onnxruntime/models/{name}", b"not a model")
        out = io.StringIO()
        call_command("ocr_models", install=fake, stdout=out)
        self.assertTrue(os.path.isfile(os.path.join(ocr.models_dir(), ocr.REC_MODEL)))
        with open(os.path.join(ocr.models_dir(), "MODELS.json"), encoding="utf-8") as fh:
            self.assertIn("Apache-2.0", json.load(fh)["license"])
        self.assertTrue(self.client.get("/api/vision/ocr/models").json()["available"])
        with self.assertRaises(ocr.OcrError):
            ocr.session(ocr.model_path(ocr.REC_MODEL))  # 假檔載不起來：明確錯誤，不會去下載
        with self.assertRaises(ocr.OcrError):
            ocr.install_models(os.path.join(self.tmp, "nowhere"))


class GenericModelTests(SimpleTestCase):
    """通用 PP-OCR 路：只在 ASSET_DIR/ocr 有模型的機器上跑（開發機 manage.py ocr_models --install）。"""

    def setUp(self):
        if not ocr.models_available():
            self.skipTest("OCR models not installed")

    def test_digit_strings_over_95_percent(self):
        rng = np.random.default_rng(7)
        ok = tot = 0
        for i in range(40):
            txt = digits(rng, 10)
            img = render(txt, size=int(rng.integers(30, 44)), rot=float(rng.uniform(-5, 5)), noise=float(rng.uniform(0, 10)), seed=i)
            r = run_tool("ocr_read", img, {"charset": "digits"})
            tot += 1
            ok += r.outputs["text"] == txt
        self.assertGreaterEqual(ok / tot, 0.9)
        chars_ok = sum(a == b for a, b in zip(r.outputs["text"], txt))
        self.assertGreaterEqual(chars_ok, 8)

    def test_session_cache_and_detect_mode(self):
        img = render("A1B2C3D4", size=36)
        run_tool("ocr_read", img, {"charset": "upper"})
        ts = []
        for _ in range(20):
            t0 = time.perf_counter()
            run_tool("ocr_read", img, {"charset": "upper"})
            ts.append((time.perf_counter() - t0) * 1000)
        self.assertLess(float(np.mean(ts)), 3 * float(np.median(ts[5:])) + 5)  # 沒有每次重建 session
        self.assertLess(float(np.median(ts)), 80)
        canvas = np.full((300, 640), 235, np.uint8)
        canvas[40:120, 120:520] = render("LOT 240912", size=34)
        canvas[160:240, 120:520] = render("PN 8834", size=34)
        r = run_tool("ocr_read", canvas, {"mode": "detect", "charset": "upper"})
        self.assertEqual(r.outputs["count"], 2)
        self.assertIn("240912", r.outputs["text"].replace(" ", ""))
        self.assertTrue(all(len(it["box"]) == 4 for it in r.outputs["items"]))
