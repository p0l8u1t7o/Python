"""WP-09 條碼品質分級：完美符號 A、退化單調、各分項獨立失效模式、min_grade 分支、1D 與 DPM 路徑、工具輸出。

符號用 zxing-cpp 的編碼器產生（沒裝就整個模組略過——正式環境 requirements.txt 有它）。
"""

from __future__ import annotations

import unittest

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision import grading as G
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool

try:
    import zxingcpp
except ImportError:  # pragma: no cover
    zxingcpp = None


def render(fmt, text: str, scale: int = 8, qz: int = 2, border: int = 40, **kw) -> np.ndarray:
    a = np.array(zxingcpp.write_barcode(fmt, text, quiet_zone=qz, **kw))
    big = np.kron(a, np.ones((scale, scale), np.uint8))
    return cv2.copyMakeBorder(big, border, border, border, border, cv2.BORDER_CONSTANT, value=255)


def contrast(img: np.ndarray, lo: int, hi: int) -> np.ndarray:
    return np.clip(lo + (img.astype(np.float32) / 255.0) * (hi - lo), 0, 255).astype(np.uint8)


def noisy(img: np.ndarray, sigma: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.clip(img.astype(np.float32) + rng.normal(0, sigma, img.shape), 0, 255).astype(np.uint8)


def param(out: dict, key: str) -> dict:
    return next(p for p in out["params"] if p["key"] == key)


@unittest.skipIf(zxingcpp is None, "zxing-cpp 未安裝")
class Grading2DTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.dm = render(zxingcpp.BarcodeFormat.DataMatrix, "VS-000123", scale=8, qz=2)  # 14×14，模組 8 px，符號從 (48, 48) 起
        cls.qr = render(zxingcpp.BarcodeFormat.QRCode, "VS-000123", scale=6, qz=4, ec_level=1)

    def test_perfect_symbols_grade_a(self):
        for name, img in (("dm", self.dm), ("qr", self.qr)):
            out = G.grade(img)
            self.assertEqual(out["grade"], "A", (name, out["params"]))
            self.assertEqual(out["grade_value"], 4.0)
            self.assertEqual(out["text"], "VS-000123")
            self.assertEqual([p["key"] for p in out["params"]], ["decode", "symbol_contrast", "modulation", "fixed_pattern_damage", "axial_nonuniformity", "grid_nonuniformity", "unused_error_correction"])
            self.assertTrue(all(p["grade"] == 4 for p in out["params"]))
            self.assertAlmostEqual(param(out, "modulation")["value"], 1.0, delta=0.02)
            self.assertAlmostEqual(param(out, "unused_error_correction")["value"], 1.0)
            self.assertEqual(out["detail"]["standard_used"], "iso15415")
        out = G.grade(self.dm)
        self.assertEqual(out["detail"]["modules"], [14, 14])
        self.assertAlmostEqual(out["detail"]["pitch_px"], 8.0, delta=0.05)
        # 大一點的 QR（版本 3）也 A、對位圖形有檢查
        qr3 = render(zxingcpp.BarcodeFormat.QRCode, "VS-000123-" * 6, scale=4, qz=4, ec_level=2)
        out = G.grade(qr3)
        self.assertEqual(out["grade"], "A", out["params"])
        self.assertEqual(out["detail"]["version"], "3")
        self.assertIn("alignment", out["detail"]["fixed_pattern"]["segments"])

    def test_contrast_steps_are_monotonic(self):
        expect = {(60, 220): "B", (90, 200): "C", (110, 190): "D", (130, 180): "F"}
        for (lo, hi), letter in expect.items():
            out = G.grade(contrast(self.dm, lo, hi))
            sc = param(out, "symbol_contrast")
            self.assertAlmostEqual(sc["value"], (hi - lo) / 255, delta=0.03)
            self.assertEqual(sc["letter"], letter, (lo, hi))
            self.assertEqual(out["grade"], letter)  # 其餘分項仍 A，總評＝對比

    def test_noise_and_blur_degrade_monotonically(self):
        grades = [G.grade(noisy(cv2.GaussianBlur(self.dm, (0, 0), 1.0), s))["grade_value"] for s in (0, 10, 25)]
        self.assertEqual(grades[0], 4.0)
        self.assertTrue(all(a >= b for a, b in zip(grades, grades[1:])), grades)
        self.assertLess(grades[-1], 4.0)
        mods = [param(G.grade(cv2.GaussianBlur(self.dm, (0, 0), s)), "modulation")["grade"] for s in (1.5, 2.5)]
        self.assertEqual(mods, [4, 2])

    def test_axial_nonuniformity(self):
        for fx, letter in ((1.03, "A"), (1.07, "B"), (1.13, "F")):
            out = G.grade(cv2.resize(self.dm, None, fx=fx, fy=1.0, interpolation=cv2.INTER_LINEAR))
            an = param(out, "axial_nonuniformity")
            self.assertAlmostEqual(an["value"], (fx - 1) / (1 + (fx - 1) / 2), delta=0.01)
            self.assertEqual(an["letter"], letter, fx)
            self.assertEqual(out["grade"], letter)

    def test_grid_nonuniformity_sees_warp(self):
        h, w = self.dm.shape
        mx, my = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        base = param(G.grade(self.dm), "grid_nonuniformity")["value"]
        self.assertLess(base, 0.1)
        warped = cv2.remap(self.dm, mx + 2.5 * np.sin(my / 25.0), my, cv2.INTER_LINEAR, borderValue=255)
        gn = param(G.grade(warped), "grid_nonuniformity")
        self.assertGreater(gn["value"], base + 0.1)
        self.assertIn("edges checked", gn["note"])

    def test_fixed_pattern_damage_and_quiet_zone(self):
        d = self.dm.copy()
        cv2.rectangle(d, (48, 48 + 2 * 8), (55, 48 + 3 * 8 - 1), 255, -1)  # L 邊（左欄）一格塗白
        out = G.grade(d)
        fp = param(out, "fixed_pattern_damage")
        self.assertEqual(fp["letter"], "B")
        self.assertAlmostEqual(out["detail"]["fixed_pattern"]["segments"]["left_side"]["damage"], 1 / 14, delta=0.01)
        self.assertEqual(out["grade"], "B")
        q = self.dm.copy()
        cv2.rectangle(q, (42, 70), (50, 100), 0, -1)  # 靜區髒污
        out = G.grade(q)
        self.assertLess(param(out, "fixed_pattern_damage")["grade"], 4)
        self.assertGreater(out["detail"]["fixed_pattern"]["segments"]["quiet_zone"]["damage"], 0)
        # QR：定時圖形一格塗白 → FPD 掉級、格式資訊沒動
        q4 = self.qr.copy()
        cv2.rectangle(q4, (64 + 6 * 10, 64 + 6 * 6), (64 + 6 * 11 - 1, 64 + 6 * 7 - 1), 255, -1)
        out = G.grade(q4)
        segs = out["detail"]["fixed_pattern"]["segments"]
        self.assertGreater(segs["timing"]["damage"], 0)
        self.assertEqual(segs["format_info"]["bit_errors"], 0)
        self.assertLess(param(out, "fixed_pattern_damage")["grade"], 4)

    def test_unused_error_correction_from_flipped_modules(self):
        letters = []
        for n_flip in (1, 2, 3, 4):
            d = self.dm.copy()
            rng = np.random.default_rng(5)
            for _ in range(n_flip):
                r, c = 2 + rng.integers(0, 8), 2 + rng.integers(0, 8)
                y, x = 48 + r * 8, 48 + c * 8
                d[y:y + 8, x:x + 8] = 255 - d[y:y + 8, x:x + 8]
            out = G.grade(d)
            uec = param(out, "unused_error_correction")
            self.assertAlmostEqual(uec["value"], 1 - 0.2 * n_flip, delta=0.01)  # 14×14：10 個 EC 碼字，每翻一格 = 一個碼字錯
            letters.append(uec["letter"])
            self.assertEqual(out["grade"], uec["letter"])
        self.assertEqual(letters, ["A", "B", "C", "F"])

    def test_rotation_and_tilt(self):
        self.assertEqual(G.grade(cv2.rotate(self.dm, cv2.ROTATE_90_CLOCKWISE))["grade"], "A")
        M = cv2.getRotationMatrix2D((self.dm.shape[1] / 2, self.dm.shape[0] / 2), 10, 1)
        tilt = cv2.warpAffine(self.dm, M, (self.dm.shape[1], self.dm.shape[0]), borderValue=255, flags=cv2.INTER_LINEAR)
        out = G.grade(tilt)
        self.assertEqual(out["grade"], "A", out["params"])
        self.assertEqual(out["text"], "VS-000123")

    def test_dpm_path_is_separate(self):
        mark = noisy(contrast(self.dm, 100, 180), 8)
        iso = G.grade(mark)
        dpm = G.grade(mark, standard="aim_dpm")
        self.assertEqual(iso["grade"], "D")
        self.assertEqual(param(iso, "symbol_contrast")["letter"], "D")
        self.assertEqual(dpm["grade"], "A", dpm["params"])
        self.assertEqual([p["key"] for p in dpm["params"]], ["decode", "cell_contrast", "cell_modulation", "minimum_reflectance", "fixed_pattern_damage", "axial_nonuniformity", "grid_nonuniformity", "unused_error_correction"])
        self.assertGreater(param(dpm, "cell_contrast")["value"], 0.3)
        self.assertEqual(dpm["detail"]["standard_used"], "aim_dpm")
        self.assertIn("cell_means", dpm["detail"])
        med = G.grade(mark, standard="aim_dpm", dpm_filter="median")
        self.assertEqual(med["grade"], "A")
        # 全黑暗格（Rmin = 0）在 DPM 是曝光不足 → minimum_reflectance F
        self.assertEqual(param(G.grade(self.dm, standard="aim_dpm"), "minimum_reflectance")["grade"], 0)

    def test_symbology_filter_and_no_symbol(self):
        out = G.grade(self.dm, symbology="qr")
        self.assertEqual((out["grade"], out["text"]), ("F", ""))
        self.assertEqual([p["key"] for p in out["params"]], ["decode"])
        self.assertEqual(G.grade(np.full((120, 120), 200, np.uint8))["grade"], "F")


@unittest.skipIf(zxingcpp is None, "zxing-cpp 未安裝")
class Grading1DTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        ean = render(zxingcpp.BarcodeFormat.EAN13, "4006381333931", scale=3, qz=10)
        cls.ean = cv2.resize(ean, (ean.shape[1], ean.shape[0] * 3), interpolation=cv2.INTER_NEAREST)
        c128 = render(zxingcpp.BarcodeFormat.Code128, "VS-0001", scale=4, qz=10)
        cls.c128 = cv2.resize(c128, (c128.shape[1], c128.shape[0] * 2), interpolation=cv2.INTER_NEAREST)

    def test_perfect_linear_symbols(self):
        for name, img, text in (("ean", self.ean, "4006381333931"), ("code128", self.c128, "VS-0001")):
            out = G.grade(img, standard="iso15415")  # 線性碼自動改走 15416
            self.assertEqual(out["grade"], "A", (name, out["params"]))
            self.assertEqual(out["text"], text)
            self.assertEqual(out["detail"]["standard_used"], "iso15416")
            self.assertEqual(len(out["detail"]["scans"]), 10)
            self.assertTrue(all(s["decoded"] and s["grade"] == 4 for s in out["detail"]["scans"]))
            self.assertEqual([p["key"] for p in out["params"]], ["decode", "symbol_contrast", "min_reflectance", "edge_contrast", "modulation", "defects", "decodability"])
        out = G.grade(self.ean)
        self.assertAlmostEqual(out["detail"]["x_dim_px"], 3.0, delta=0.05)
        self.assertGreater(param(out, "decodability")["value"], 0.62)
        self.assertLess(param(out, "defects")["value"], 0.05)

    def test_contrast_and_min_reflectance(self):
        out = G.grade(contrast(self.ean, 80, 220))
        self.assertEqual(param(out, "symbol_contrast")["letter"], "C")
        self.assertEqual(out["grade"], "C")
        out = G.grade(contrast(self.ean, 110, 190))
        self.assertEqual(param(out, "min_reflectance")["grade"], 0)  # 條不夠暗（Rmin > 0.5·Rmax）
        self.assertEqual(out["grade"], "F")

    def test_defect_spot_in_a_space(self):
        # Code 128 有 ≥ 3 模組寬的空白：從中線的元素找一個寬空白放一條細刮痕（孔徑濾波後是空白裡的谷、不是新的條）
        base = G.grade(self.c128)
        y = self.c128.shape[0] // 2
        row = self.c128[y]
        runs = []
        start = 0
        for x in range(1, len(row) + 1):
            if x == len(row) or row[x] != row[start]:
                runs.append((start, x, row[start] == 0))
                start = x
        bars = [r for r in runs if r[2]]
        spaces = [r for r in runs if not r[2] and r[0] > bars[0][0] and r[1] < bars[-1][1] and (r[1] - r[0]) >= 12]
        self.assertTrue(spaces)
        a, b, _ = spaces[len(spaces) // 2]
        d = self.c128.copy()
        x = (a + b) // 2
        d[40:-40, x:x + 2] = 150  # 一條 2 px 的淡刮痕貫穿條高（每條掃描線都碰得到；淡到不會變成一條新的條）
        out = G.grade(d)
        self.assertEqual(out["text"], "VS-0001", out["params"])
        self.assertGreater(param(out, "defects")["value"], param(base, "defects")["value"] + 0.1)
        self.assertLess(param(out, "defects")["grade"], 4)

    def test_blur_hurts_modulation(self):
        out = G.grade(cv2.GaussianBlur(self.ean, (0, 0), 1.2))
        self.assertLess(param(out, "modulation")["grade"], 4)
        self.assertLess(out["grade_value"], 4.0)


@unittest.skipIf(zxingcpp is None, "zxing-cpp 未安裝")
class BarcodeGradeToolTests(SimpleTestCase):
    def setUp(self) -> None:
        self.dm = render(zxingcpp.BarcodeFormat.DataMatrix, "VS-000123", scale=8, qz=2)
        self.scene = cv2.copyMakeBorder(self.dm, 200, 200, 300, 300, cv2.BORDER_CONSTANT, value=225)

    def test_min_grade_branches_and_outputs(self):
        c_symbol = contrast(self.scene, 90, 200)  # 對比 0.43 → C
        r = run_tool("barcode_grade", c_symbol, {"min_grade": "C"})
        self.assertEqual((r.branch, r.status), ("pass", "ok"), r.message)
        self.assertEqual(r.outputs["grade"], "C")
        self.assertEqual(r.outputs["grade_value"], 2.0)
        self.assertEqual(r.outputs["text"], "VS-000123")
        self.assertEqual(r.outputs["symbology"], "Data Matrix")
        self.assertTrue(r.outputs["decoded"])
        self.assertEqual(param({"params": r.outputs["params"]}, "symbol_contrast")["letter"], "C")
        self.assertTrue(any(o["kind"] == "polygon" and o["label"].startswith("C (2.0)") for o in r.overlays))
        r = run_tool("barcode_grade", c_symbol, {"min_grade": "B"})
        self.assertEqual((r.branch, r.status), ("fail", "ng"))
        self.assertIn("limited by symbol contrast", r.message)
        # ROI（含靜區）與碼制限定、彩色輸入
        roi = {"shape": "rect", "x": 300, "y": 200, "w": self.dm.shape[1], "h": self.dm.shape[0]}
        r = run_tool("barcode_grade", cv2.cvtColor(self.scene, cv2.COLOR_GRAY2BGR), {"roi": roi, "symbology": "datamatrix", "min_grade": "A"})
        self.assertEqual(r.branch, "pass", r.message)
        self.assertEqual(r.outputs["grade"], "A")
        poly = next(o for o in r.overlays if o["kind"] == "polygon")
        xs = [p[0] for p in poly["points"]]
        self.assertGreater(min(xs), 300)  # 角點已換回全圖座標
        r = run_tool("barcode_grade", self.scene, {"symbology": "qr"})
        self.assertEqual((r.branch, r.outputs["grade"], r.outputs["decoded"]), ("fail", "F", False))
        self.assertIn("No symbol decoded", r.message)
        with self.assertRaisesMessage(ToolError, "outside the image"):
            run_tool("barcode_grade", self.scene, {"roi": {"shape": "rect", "x": 5000, "y": 5000, "w": 10, "h": 10}})

    def test_barcode_tool_reads_datamatrix_through_zxing(self):
        r = run_tool("barcode", self.scene, {"types": "2d"})
        self.assertEqual(r.branch, "found", r.message)
        self.assertEqual(r.outputs["first"], "VS-000123")
        self.assertEqual(r.outputs["codes"][0]["type"], "DataMatrix")
        self.assertEqual(run_tool("barcode", self.scene, {"types": "1d"}).outputs["count"], 0)
        qr = render(zxingcpp.BarcodeFormat.QRCode, "VS-7", scale=6, qz=4)
        self.assertEqual(run_tool("barcode", qr, {"types": "qr"}).outputs["codes"][0]["type"], "QR")
