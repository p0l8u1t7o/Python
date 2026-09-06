"""標定：payload 驗證、世界座標解算與殘差、鏡頭內參、標定板偵測、快取，以及三個吃標定的工具。

精度測試用**解析式合成**（cv2.projectPoints 反推），不用畫出來的影像當真值——畫出來的圓與線有 1px 級的
繪製誤差，會把 0.01px 級的數值誤差蓋掉（見 CLAUDE.md「合成真值」那一條）。
"""

from __future__ import annotations

import json
import math
import os
import shutil
import time

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision import calib
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool, temp_dir

W, H = 1280, 960
CAM = np.array([[1400.0, 0, 640.0], [0, 1400.0, 480.0], [0, 0, 1.0]])
DIST = np.array([-0.28, 0.12, 0.0008, -0.0006, 0.0])


def affine_matrix(k: float = 0.05, deg: float = 12.0, tx: float = 12.0, ty: float = -8.0) -> np.ndarray:
    a = math.radians(deg)
    return np.array([[k * math.cos(a), -k * math.sin(a), tx], [k * math.sin(a), k * math.cos(a), ty], [0, 0, 1.0]])


def lens_payload(size: tuple[int, int] = (W, H)) -> dict:
    return {"unit": "mm", "image_size": list(size),
            "lens": {"camera_matrix": CAM.tolist(), "dist_coeffs": DIST.tolist(), "rms": 0.21, "views": 12}}


def world_payload(matrix: np.ndarray | None = None, size: tuple[int, int] = (W, H)) -> dict:
    m = affine_matrix() if matrix is None else matrix
    return {"unit": "mm", "image_size": list(size),
            "world": {"kind": "affine", "matrix": m.tolist(), "mm_per_px": 0.05, "rms": 0.01, "max_error": 0.02}}


class ValidateTests(SimpleTestCase):
    def test_needs_lens_or_world(self):
        with self.assertRaises(calib.CalibError):
            calib.validate({"unit": "mm", "image_size": [W, H]})

    def test_lens_only_and_world_only_are_both_valid(self):
        self.assertIn("lens", calib.validate(lens_payload()))
        self.assertIn("world", calib.validate(world_payload()))

    def test_rejects_broken_payloads(self):
        bad = [
            "not a dict",
            {"image_size": [0, 10], **{k: v for k, v in lens_payload().items() if k == "lens"}},
            {"image_size": [W, H], "lens": {"camera_matrix": [[1, 2], [3, 4]], "dist_coeffs": [0] * 5}},
            {"image_size": [W, H], "lens": {"camera_matrix": CAM.tolist(), "dist_coeffs": [0, 0, 0]}},
            {"image_size": [W, H], "lens": {"camera_matrix": [[0, 0, 1], [0, 0, 1], [0, 0, 1]], "dist_coeffs": [0] * 5}},
            {"image_size": [W, H], "world": {"kind": "nope", "matrix": np.eye(3).tolist()}},
            {"image_size": [W, H], "world": {"kind": "affine", "matrix": np.zeros((3, 3)).tolist()}},
            {"image_size": [W, H], "lens": {"camera_matrix": CAM.tolist(), "dist_coeffs": [float("nan")] * 5}},
        ]
        for payload in bad:
            with self.assertRaises(calib.CalibError, msg=repr(payload)[:60]):
                calib.validate(payload)

    def test_fills_in_the_scale_when_missing(self):
        payload = calib.validate({"image_size": [W, H], "world": {"kind": "affine", "matrix": affine_matrix().tolist()}})
        self.assertAlmostEqual(payload["world"]["mm_per_px"], 0.05, places=9)
        self.assertEqual(payload["version"], calib.VERSION)


class SolveWorldTests(SimpleTestCase):
    def test_recovers_each_kind_exactly(self):
        px = np.array([[100.0, 120], [900, 140], [880, 700], [120, 690], [500, 400]])
        for kind, truth in [
            ("scale", np.array([[0.05, 0, 3.0], [0, 0.05, -2.0], [0, 0, 1.0]])),
            ("affine", affine_matrix()),
            ("perspective", np.array([[0.04, -0.01, 3.0], [0.012, 0.05, -2.0], [1e-5, 2e-5, 1.0]])),
        ]:
            world = calib.apply(truth, px)
            got = calib.solve_world([(tuple(a), tuple(b)) for a, b in zip(px, world, strict=True)], kind)
            self.assertEqual(got["kind"], kind)
            self.assertLess(got["max_error"], 1e-5, kind)
            self.assertEqual(len(got["points"]), len(px))
            back = calib.apply(got["matrix"], px)
            np.testing.assert_allclose(back, world, atol=1e-5)

    def test_reports_which_point_is_wrong(self):
        truth = affine_matrix()
        px = np.array([[100.0, 120], [900, 140], [880, 700], [120, 690], [500, 400], [300, 250], [700, 550]])
        world = calib.apply(truth, px)
        world[2] += [0.6, 0.0]  # 第三點打錯 0.6 mm
        got = calib.solve_world([(tuple(a), tuple(b)) for a, b in zip(px, world, strict=True)], "affine")
        errors = [p["error"] for p in got["points"]]
        self.assertEqual(int(np.argmax(errors)), 2)
        self.assertGreater(got["max_error"], 0.25)
        self.assertGreater(got["max_error"], got["rms"])

    def test_point_count_and_degenerate_layouts(self):
        with self.assertRaises(calib.CalibError):
            calib.solve_world([((0, 0), (0, 0)), ((1, 1), (1, 1))], "affine")
        with self.assertRaises(calib.CalibError):
            calib.solve_world([((0, 0), (0, 0)), ((1, 1), (1, 1)), ((2, 2), (2, 2))], "affine")  # 共線
        with self.assertRaises(calib.CalibError):
            calib.solve_world([((0, 0), (0, 0)), ((0, 0), (5, 5))], "scale")  # 同一個像素點

    def test_scale_and_angle_helpers(self):
        m = affine_matrix(k=0.05, deg=12)
        self.assertAlmostEqual(calib.scale_at(m, (500, 400)), 0.05, places=9)
        self.assertAlmostEqual(calib.angle_to_world(m, 30.0), 42.0, places=6)
        self.assertAlmostEqual(calib.angle_to_world(np.eye(3), -15.0), -15.0, places=6)

    def test_apply_handles_empty(self):
        self.assertEqual(calib.apply(np.eye(3), []).shape, (0, 2))


class LensTests(SimpleTestCase):
    def _views(self, count: int = 10) -> tuple[list[np.ndarray], np.ndarray]:
        rng = np.random.default_rng(7)
        obj = calib.board_object_points(9, 6, 20.0)
        obj -= obj.mean(axis=0)
        views = []
        for _ in range(count):
            rvec = rng.uniform(-0.35, 0.35, 3)
            tvec = np.array([rng.uniform(-25, 25), rng.uniform(-20, 20), rng.uniform(420, 620)])
            pts, _ = cv2.projectPoints(obj.astype(np.float32), rvec, tvec, CAM, DIST)
            views.append(pts.reshape(-1, 2).astype(np.float64))
        return views, obj

    def test_recovers_the_camera(self):
        views, obj = self._views()
        lens = calib.calibrate_lens(views, obj, (W, H))
        cam = np.asarray(lens["camera_matrix"])
        self.assertAlmostEqual(cam[0, 0], CAM[0, 0], delta=1.0)
        self.assertAlmostEqual(cam[0, 2], CAM[0, 2], delta=1.0)
        self.assertAlmostEqual(np.asarray(lens["dist_coeffs"])[0], DIST[0], delta=0.01)
        self.assertLess(lens["rms"], 0.05)
        self.assertEqual(len(lens["view_errors"]), 10)
        calib.validate({"image_size": [W, H], "lens": lens})

    def test_needs_enough_views(self):
        views, obj = self._views(2)
        with self.assertRaises(calib.CalibError):
            calib.calibrate_lens(views, obj, (W, H))

    def test_view_point_count_must_match_the_board(self):
        views, obj = self._views(3)
        views[1] = views[1][:-1]
        with self.assertRaises(calib.CalibError):
            calib.calibrate_lens(views, obj, (W, H))


class BoardTests(SimpleTestCase):
    def test_object_points(self):
        pts = calib.board_object_points(4, 3, 5.0)
        self.assertEqual(pts.shape, (12, 3))
        np.testing.assert_allclose(pts[0], [0, 0, 0])
        np.testing.assert_allclose(pts[1], [5, 0, 0])
        np.testing.assert_allclose(pts[-1], [15, 10, 0])
        # 交錯圓點：奇數列右移半格、列距減半
        a = calib.board_object_points(4, 3, 5.0, "acircles")
        np.testing.assert_allclose(a[4], [2.5, 2.5, 0])
        for bad in ((1, 3, 5.0), (4, 3, 0.0)):
            with self.assertRaises(calib.CalibError):
                calib.board_object_points(*bad)

    def test_finds_a_chessboard_and_says_no_when_there_is_none(self):
        cols, rows, s = 9, 6, 70
        img = np.full((720, 960), 255, np.uint8)
        for r in range(rows + 1):
            for c in range(cols + 1):
                if (r + c) % 2 == 0:
                    cv2.rectangle(img, (120 + c * s, 90 + r * s), (120 + (c + 1) * s - 1, 90 + (r + 1) * s - 1), 0, -1)
        found = calib.find_board(img, cols, rows, "chessboard")
        self.assertIsNotNone(found)
        self.assertEqual(found.shape, (cols * rows, 2))
        # 角點間距就是格子大小（順序與 board_object_points 對應）
        self.assertAlmostEqual(float(np.linalg.norm(found[1] - found[0])), s, delta=1.0)
        self.assertIsNone(calib.find_board(np.full((480, 640), 128, np.uint8), cols, rows, "chessboard"))
        with self.assertRaises(calib.CalibError):
            calib.find_board(img, cols, rows, "nope")

    def test_world_from_a_flat_board(self):
        cols, rows, spacing = 9, 6, 20.0
        obj = calib.board_object_points(cols, rows, spacing)
        truth = np.array([[0.04, -0.01, 3.0], [0.012, 0.05, -2.0], [1e-5, 2e-5, 1.0]])
        corners = calib.apply(np.linalg.inv(truth), obj[:, :2])
        world = calib.world_from_board(corners, obj)
        self.assertEqual(world["kind"], "perspective")
        self.assertLess(world["max_error"], 1e-4)  # 單位是 mm：0.1 µm 等於完全吻合


class UndistortTests(SimpleTestCase):
    def test_straightens_a_bowed_line(self):
        payload = calib.validate(lens_payload())
        line = np.stack([np.linspace(-110, 110, 40), np.full(40, 95.0), np.zeros(40)], 1).astype(np.float32)
        proj, _ = cv2.projectPoints(line, np.zeros(3), np.array([0.0, 0.0, 500.0]), CAM, DIST)
        proj = proj.reshape(-1, 2)
        img = np.zeros((H, W), np.uint8)
        for p in proj.astype(int):
            cv2.circle(img, tuple(p), 3, 255, -1)

        def bow(points):
            p = np.asarray(points, float)
            n = np.array([-(p[-1] - p[0])[1], (p[-1] - p[0])[0]])
            return float(np.abs((p - p[0]) @ (n / np.linalg.norm(n))).max())

        out = calib.undistort(img, payload, alpha=1.0)
        self.assertEqual(out.shape, img.shape)
        blobs, _ = cv2.findContours((out > 60).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        centres = np.array([c.reshape(-1, 2).mean(0) for c in blobs])
        centres = centres[np.argsort(centres[:, 0])]
        self.assertEqual(len(centres), 40)
        self.assertGreater(bow(proj), 3.0)
        # 校正後的殘餘彎曲主要來自把點畫成 3px 圓與重取樣，不是標定本身
        self.assertLess(bow(centres), bow(proj) / 3)

    def test_rescales_for_a_different_image_size(self):
        lens = lens_payload()["lens"]
        half = calib.scaled_camera_matrix(lens, (W, H), (W // 2, H // 2))
        self.assertAlmostEqual(half[0, 0], CAM[0, 0] / 2, places=6)
        self.assertAlmostEqual(half[1, 2], CAM[1, 2] / 2, places=6)
        np.testing.assert_allclose(calib.scaled_camera_matrix(lens, (W, H), (W, H)), CAM)
        with self.assertRaises(calib.CalibError):
            calib.scaled_camera_matrix(lens, (W, H), (W // 2, H))  # 長寬比不同：不猜，直接說清楚

    def test_needs_lens_data(self):
        with self.assertRaises(calib.CalibError):
            calib.undistort(np.zeros((10, 10), np.uint8), calib.validate(world_payload()))


class FileTests(SimpleTestCase):
    def setUp(self):
        self.folder = temp_dir()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(calib.invalidate)
        self.path = os.path.join(self.folder, "c.json")

    def test_round_trip_and_cache(self):
        saved = calib.save(self.path, world_payload())
        self.assertEqual(saved["world"]["kind"], "affine")
        first = calib.load(self.path)
        self.assertIs(calib.load(self.path), first)  # 熱路徑：同一份物件，不重讀檔
        time.sleep(0.01)
        calib.save(self.path, lens_payload())
        os.utime(self.path, (time.time() + 2, time.time() + 2))
        self.assertIn("lens", calib.load(self.path))  # mtime 變了就重讀

    def test_missing_and_corrupt(self):
        with self.assertRaises(calib.CalibError):
            calib.load(os.path.join(self.folder, "nope.json"))
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with self.assertRaises(calib.CalibError):
            calib.load(self.path)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"image_size": [10, 10]}, fh)
        calib.invalidate(self.path)
        with self.assertRaises(calib.CalibError):
            calib.load(self.path)

    def test_summary_and_quality_are_plain_language(self):
        both = calib.validate({**lens_payload(), "world": world_payload()["world"]})
        text = calib.summary(both)
        self.assertIn("lens", text)
        self.assertIn("mm/px", text)
        self.assertEqual(calib.quality(both)["lens"], "good")
        poor = calib.validate({**lens_payload()})
        poor["lens"]["rms"] = 2.5
        self.assertEqual(calib.quality(poor)["lens"], "poor")
        # 世界座標的等級看「殘差折算成幾個像素」：0.1 mm / 0.05 = 2 px → 尚可
        graded = calib.validate({"image_size": [W, H], "world": {
            "kind": "affine", "matrix": affine_matrix().tolist(), "mm_per_px": 0.05, "rms": 0.1,
            "points": [{"px": [0, 0], "world": [0, 0], "error": 0.1}]}})
        self.assertEqual(calib.quality(graded)["world"], "fair")
        graded["world"]["rms"] = 0.4
        self.assertEqual(calib.quality(graded)["world"], "poor")


class ToolTests(SimpleTestCase):
    def setUp(self):
        self.folder = temp_dir()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(calib.invalidate)
        self.both = os.path.join(self.folder, "both.json")
        calib.save(self.both, {**lens_payload(), "world": world_payload()["world"]})
        self.lens_only = os.path.join(self.folder, "lens.json")
        calib.save(self.lens_only, lens_payload())
        self.world_only = os.path.join(self.folder, "world.json")
        calib.save(self.world_only, world_payload())
        self.assets = {"both": self.both, "lens": self.lens_only, "world": self.world_only}

    def test_undistort_tool(self):
        img = np.zeros((H, W, 3), np.uint8)
        img[400:500, 300:900] = 255
        out = run_tool("undistort", img, {"calibration": "lens"}, assets=self.assets)
        self.assertEqual(out.outputs["image"].shape, img.shape)
        self.assertFalse(np.array_equal(out.outputs["image"], img))
        # keep_edges 保留整個畫面 → 邊角是黑的，畫面比裁切版「窄」
        wide = run_tool("undistort", img, {"calibration": "lens", "keep_edges": True}, assets=self.assets)
        self.assertLess(int((wide.outputs["image"] > 40).sum()), int((out.outputs["image"] > 40).sum()))

    def test_to_world_tool(self):
        r = run_tool("to_world", None, {"calibration": "world"},
                     inputs={"points": [[100.0, 200.0], [140.0, 225.0]], "value": 100.0, "angle": 30.0}, assets=self.assets)
        expect = calib.apply(affine_matrix(), [[100.0, 200.0]])[0]
        self.assertAlmostEqual(r.outputs["x"], float(expect[0]), places=6)
        self.assertAlmostEqual(r.outputs["y"], float(expect[1]), places=6)
        self.assertEqual(len(r.outputs["points_world"]), 2)
        self.assertAlmostEqual(r.outputs["length"], 5.0, places=6)   # 100 px * 0.05
        self.assertAlmostEqual(r.outputs["angle"], 42.0, places=4)   # 影像 30° + 座標系 12°
        self.assertAlmostEqual(r.outputs["scale"], 0.05, places=9)
        self.assertTrue(any(o.get("type") == "point" for o in r.overlays))

    def test_to_world_needs_a_world_mapping_and_an_input(self):
        with self.assertRaises(ToolError) as bad:
            run_tool("to_world", None, {"calibration": "lens"}, inputs={"value": 1.0}, assets=self.assets)
        self.assertIn("lens", str(bad.exception))
        with self.assertRaises(ToolError):
            run_tool("to_world", None, {"calibration": "world"}, inputs={}, assets=self.assets)
        with self.assertRaises(ToolError):
            run_tool("to_world", None, {}, inputs={"value": 1.0}, assets=self.assets)
        with self.assertRaises(ToolError):
            run_tool("to_world", None, {"calibration": "gone"}, inputs={"value": 1.0}, assets=self.assets)

    def test_calibration_tool_reads_the_asset(self):
        r = run_tool("calibration", None, {"mode": "asset", "calibration": "world"}, inputs={"value": 200.0}, assets=self.assets)
        self.assertAlmostEqual(r.outputs["mm"], 10.0, places=6)
        self.assertAlmostEqual(r.outputs["scale"], 0.05, places=9)
        with self.assertRaises(ToolError):
            run_tool("calibration", None, {"mode": "asset", "calibration": "lens"}, inputs={"value": 1.0}, assets=self.assets)
        # 舊的兩種模式不受影響
        self.assertAlmostEqual(run_tool("calibration", None, {"pixel_size_mm": 0.01}, inputs={"value": 100.0}).outputs["mm"], 1.0, places=9)
