"""標定：payload 驗證、世界座標解算與殘差、鏡頭內參、標定板偵測、快取，以及三個吃標定的工具。

精度測試用**解析式合成**（cv2.projectPoints 反推），不用畫出來的影像當真值——畫出來的圓與線有 1px 級的
繪製誤差，會把 0.01px 級的數值誤差蓋掉（見 CLAUDE.md「合成真值」那一條）。
"""

from __future__ import annotations

import io
import json
import math
import os
import shutil
import time

import cv2
import numpy as np
from django.test import SimpleTestCase, TestCase

from apps.vision import calib
from apps.vision.images import store
from apps.vision.models import Asset
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


def robot_samples(matrix: np.ndarray | None = None) -> list[dict]:
    """合成分散於工作區的平移點對，中心點方便驗證離群殘差。"""
    px = np.array([[100, 100], [900, 100], [900, 700], [100, 700], [300, 250], [700, 550], [500, 400]], dtype=float)
    target = calib.apply(affine_matrix() if matrix is None else matrix, px)
    return [{"px": float(p[0]), "py": float(p[1]), "rx": float(r[0]), "ry": float(r[1])}
            for p, r in zip(px, target, strict=True)]


class SolveRobotTests(SimpleTestCase):
    def test_recovers_affine_and_handedness_for_both_camera_modes(self):
        for mode in ("fixed", "moving"):
            for mirror in (False, True):
                truth = affine_matrix() @ np.diag([1, -1 if mirror else 1, 1])
                points = robot_samples(truth)
                before = json.dumps(points)
                got = calib.solve_robot(points, kind="translation", camera_mode=mode)
                np.testing.assert_allclose(got["matrix"], truth, atol=1e-6, rtol=0)
                probes = [[44, 55], [650, 440], [1000, 810]]
                np.testing.assert_allclose(calib.apply(got["matrix"], probes), calib.apply(truth, probes), atol=1e-6, rtol=0)
                self.assertEqual(got["handedness"], "left" if mirror else "right")
                self.assertEqual(got["angle_sign"], -1 if mirror else 1)
                self.assertEqual(got["camera_mode"], mode)
                self.assertEqual(json.dumps(points), before)
                self.assertLess(got["max_error"], 1e-6)
                self.assertNotIn("rotation_center_px", got)
                checked = calib.validate({"image_size": [W, H], "robot": got})
                self.assertEqual(checked["robot"], got)

    def test_rotation_center_from_separate_short_arc(self):
        center = np.array([423.5, 317.25])
        angles = np.deg2rad(np.linspace(15, 105, 12))
        arc = center + 85 * np.column_stack([np.cos(angles), np.sin(angles)])
        for mode in ("fixed", "moving"):
            got = calib.solve_robot({"translation": robot_samples(), "rotation": arc.tolist()},
                                    kind="translation_rotation", camera_mode=mode)
            self.assertLess(np.linalg.norm(np.array(got["rotation_center_px"]) - center), 0.5)
            np.testing.assert_allclose(got["rotation_center_world"], calib.apply(affine_matrix(), [center])[0], atol=1e-6)
            payload = {"image_size": [W, H], "robot": got}
            self.assertEqual(calib.validate(payload)["robot"], got)
            self.assertIn("rotation center: yes", calib.summary(payload))
            self.assertEqual(calib.warnings(payload), [])
            self.assertEqual(len(got["rotation_points"]), len(arc))
            self.assertLess(got["rotation_max_error_px"], 1e-6)

    def test_rotation_outlier_is_retained_in_circle_fit(self):
        angles = np.linspace(0, 2 * np.pi, 20, endpoint=False)
        arc = np.array([400, 300]) + 85 * np.column_stack([np.cos(angles), np.sin(angles)])
        arc[0, 0] += 10
        got = calib.solve_robot({"translation": robot_samples(), "rotation": arc.tolist()},
                                kind="translation_rotation", camera_mode="fixed")
        residuals = [p["error"] for p in got["rotation_points"]]
        self.assertEqual(len(residuals), len(arc))
        self.assertEqual(int(np.argmax(residuals)), 0)
        self.assertGreater(residuals[0], 4 * max(residuals[1:]))
        self.assertGreater(np.linalg.norm(np.array(got["rotation_center_px"]) - [400, 300]), 0.1)
        self.assertTrue(any("rotation residual" in w for w in calib.warnings({"robot": got})))

    def test_keeps_outlier_and_reports_every_residual(self):
        points = robot_samples()
        points[-1]["rx"] += 5
        got = calib.solve_robot(points, kind="translation", camera_mode="fixed")
        errors = np.array([p["error"] for p in got["points"]])
        self.assertEqual(len(errors), len(points))
        self.assertEqual(int(errors.argmax()), len(points) - 1)
        self.assertGreater(errors[-1], 4 * max(errors[:-1]))
        self.assertGreater(min(errors[:-1]), 0.1)
        mapped = calib.apply(got["matrix"], [[p["px"], p["py"]] for p in points])
        expected = np.linalg.norm(mapped - [[p["rx"], p["ry"]] for p in points], axis=1)
        np.testing.assert_allclose(errors, expected, atol=1e-9)
        self.assertAlmostEqual(got["rms"], float(np.sqrt(np.mean(expected**2))))
        self.assertEqual(got["max_error"], float(errors.max()))
        payload = {"image_size": [W, H], "robot": got}
        self.assertIn("7 points", calib.summary(payload))
        self.assertIn("max", calib.summary(payload))
        self.assertEqual(calib.quality(payload)["robot"], "poor")
        self.assertTrue(any("maximum residual" in warning for warning in calib.warnings(payload)))

    def test_rejects_bad_inputs_and_degenerate_samples(self):
        cases = [
            ([], "translation", "fixed", "at least 3"),
            (robot_samples(), "bad", "fixed", "robot.kind"),
            (robot_samples(), "translation", "bad", "robot.camera_mode"),
            ([None] * 3, "translation", "fixed", "must be an object"),
            ([{"px": 1}] * 3, "translation", "fixed", "py"),
            ([{"px": i, "py": 2 * i, "rx": i, "ry": i} for i in range(3)], "translation", "fixed", "collinear"),
            (robot_samples(), "translation_rotation", "fixed", "rotation_points"),
        ]
        for rotation in ([], [[1, 2]], [[1, 2, 3]] * 3, [[1, 2], [2, 4], [3, 6]], [[float("nan"), 1]] * 3):
            cases.append(({"translation": robot_samples(), "rotation": rotation}, "translation_rotation", "fixed", "rotation_points"))
        for points, kind, mode, message in cases:
            with self.subTest(message=message, points=points):
                with self.assertRaisesRegex(calib.CalibError, message):
                    calib.solve_robot(points, kind=kind, camera_mode=mode)

    def test_validate_reports_field_errors(self):
        robot = calib.solve_robot(robot_samples(), kind="translation", camera_mode="fixed")
        cases = [("kind", "bad"), ("camera_mode", None), ("handedness", "left"),
                 ("handedness", "bad"), ("angle_sign", 0), ("angle_sign", True),
                 ("matrix", [1] * 9), ("matrix", np.zeros((3, 3)).tolist()),
                 ("matrix", [[1, 0, 0], [0, 1, 0], [0.1, 0, 1]]),
                 ("matrix", [[float("inf"), 0, 0], [0, 1, 0], [0, 0, 1]]),
                 ("rms", -1), ("rms", float("nan")), ("points", {}), ("points", []),
                 ("rotation_points", []), ("rotation_points", [None] * 3),
                 ("rotation_points", [{"px": 1, "py": 2, "error": -1}] * 3),
                 ("rotation_center_px", [1]), ("rotation_center_world", [None, 2])]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                with self.assertRaisesRegex(calib.CalibError, f"robot.{key}"):
                    calib.validate({"image_size": [W, H], "robot": {**robot, key: value}})
        for value in (None, [], "bad", {}):
            with self.assertRaisesRegex(calib.CalibError, "robot"):
                calib.validate({"image_size": [W, H], "robot": value})
        for key in ("px", "py", "rx", "ry", "error"):
            bad_points = [{**p} for p in robot["points"]]
            bad_points[1][key] = float("inf")
            with self.assertRaisesRegex(calib.CalibError, key):
                calib.validate({"image_size": [W, H], "robot": {**robot, "points": bad_points}})
        with self.assertRaisesRegex(calib.CalibError, "does not match"):
            calib.validate({"image_size": [W, H], "robot": {**robot, "rotation_center_px": [0, 0], "rotation_center_world": [0, 0]}})

    def test_optional_centers_and_coexisting_blocks(self):
        robot = calib.solve_robot(robot_samples()[:3], kind="translation", camera_mode="fixed")
        payload = {**lens_payload(), "world": world_payload()["world"], "robot": robot}
        self.assertEqual(set(calib.quality(calib.validate(payload))), {"lens", "robot"})
        self.assertTrue(any("only 3 points" in warning for warning in calib.warnings(payload)))
        for key in ("rotation_center_px", "rotation_center_world"):
            self.assertIn(key, calib.validate({**payload, "robot": {**robot, key: [1, 2]}})["robot"])
        # 保存超過既有世界標定上限的點數，也不得靜默裁掉機構點。
        many = {**robot, "points": robot["points"] * 80}
        self.assertEqual(len(calib.validate({**payload, "robot": many})["robot"]["points"]), 240)


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
        self.assertAlmostEqual(np.asarray(lens["dist_coeffs"])[0], DIST[0], delta=abs(DIST[0]) * 0.02)  # k1 誤差 < 2%
        self.assertAlmostEqual(np.asarray(lens["dist_coeffs"])[1], DIST[1], delta=abs(DIST[1]) * 0.05)
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


class CoverageTests(SimpleTestCase):
    def test_coverage_grid_and_warnings(self):
        views = [[[100 + i * 50, 100 + j * 50] for i in range(9) for j in range(6)]]  # 只在左上角
        cov = calib.coverage(views, (W, H))
        self.assertEqual((cov["cols"], cov["rows"], cov["cells"]), (4, 3, 12))
        self.assertEqual(cov["points"], 54)
        self.assertLess(cov["covered"], 6)
        self.assertGreater(cov["edge_missing"], 0)
        self.assertTrue(any("edges" in w or "areas" in w for w in calib.warnings({}, cov)))
        spread = [[[x, y] for x in range(40, W, 120) for y in range(40, H, 120)]]
        full = calib.coverage(spread, (W, H))
        self.assertEqual(full["covered"], 12)
        self.assertEqual(full["missing"], [])
        bad = calib.warnings({"lens": {"rms": 0.9, "views": 5, "camera_matrix": CAM.tolist(), "dist_coeffs": DIST.tolist()}}, full)
        self.assertTrue(any("0.9" in w and "0.5" in w for w in bad))
        self.assertTrue(any("5 pictures" in w for w in bad))
        self.assertEqual(calib.warnings({"lens": {"rms": 0.2, "views": 12}}, full), [])
        self.assertTrue(calib.warnings({"unit": "mm", "world": {"rms": 0.5, "mm_per_px": 0.05}}))


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
        # overlay 的鍵是 kind（不是 type），寫錯前端不會畫但也不會報錯
        self.assertTrue(any(o.get("kind") == "point" and "label" in o for o in r.overlays))

    def test_to_world_accepts_x_y_numbers_and_mirrored_calibrations(self):
        r = run_tool("to_world", None, {"calibration": "world"}, inputs={"x": 100.0, "y": 200.0}, assets=self.assets)
        expect = calib.apply(affine_matrix(), [[100.0, 200.0]])[0]
        self.assertAlmostEqual(r.outputs["x"], float(expect[0]), places=6)
        self.assertAlmostEqual(r.outputs["y"], float(expect[1]), places=6)
        # 往返：image → world → image 誤差 < 1e-6
        back = np.linalg.solve(affine_matrix(), np.array([expect[0], expect[1], 1.0]))
        self.assertLess(abs(back[0] - 100.0) + abs(back[1] - 200.0), 1e-6)
        # 鏡像（相機裝反：handedness 翻轉，det < 0）：角度換算跟著鏡像，往返仍一致
        mirror = affine_matrix() @ np.diag([1.0, -1.0, 1.0])
        path = os.path.join(self.folder, "mirror.json")
        calib.save(path, world_payload(mirror))
        m = run_tool("to_world", None, {"calibration": "m"}, inputs={"x": 100.0, "y": 200.0, "angle": 30.0}, assets={"m": path})
        self.assertLess(np.linalg.det(mirror[:2, :2]), 0)
        self.assertAlmostEqual(m.outputs["angle"], -(30.0) + 12.0, delta=1e-4)  # 鏡像：影像 +30° → 世界 −30°，再加座標系 12°
        with self.assertRaises(ToolError):
            run_tool("to_world", None, {"calibration": "world"}, inputs={"x": "a", "y": 1.0}, assets=self.assets)

    def test_undistort_alpha_cache_and_mm_per_pixel(self):
        import time

        img = np.zeros((H, W, 3), np.uint8)
        img[400:500, 300:900] = 255
        full = run_tool("undistort", img, {"calibration": "both", "alpha": 1.0}, assets=self.assets)
        crop_ = run_tool("undistort", img, {"calibration": "both", "alpha": 0.0}, assets=self.assets)
        self.assertLess(int((full.outputs["image"] > 40).sum()), int((crop_.outputs["image"] > 40).sum()))
        self.assertAlmostEqual(full.outputs["mm_per_pixel"], 0.05, places=9)  # 有世界對應時直接接 calibration
        self.assertTrue(np.isnan(run_tool("undistort", img, {"calibration": "lens"}, assets=self.assets).outputs["mm_per_pixel"]))
        # map 快取：100 幀平均 ≈ 純 remap（第一幀含建表）
        ts = []
        for _ in range(100):
            t0 = time.perf_counter()
            run_tool("undistort", img, {"calibration": "lens", "alpha": 0.5}, assets=self.assets)
            ts.append(time.perf_counter() - t0)
        self.assertLess(float(np.mean(ts[1:])), 3 * float(np.median(ts[1:])) + 0.002)

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


def chessboard_image(cols: int = 9, rows: int = 6, square: int = 70) -> np.ndarray:
    img = np.full((rows * square + 180, cols * square + 240), 255, np.uint8)
    for r in range(rows + 1):
        for c in range(cols + 1):
            if (r + c) % 2 == 0:
                cv2.rectangle(img, (120 + c * square, 90 + r * square), (120 + (c + 1) * square - 1, 90 + (r + 1) * square - 1), 0, -1)
    return img


class ApiTests(TestCase):
    """標定頁的 API：拍照→偵測→解算→存成資產。solve 不會偷偷存，存是另一步。"""

    def setUp(self):
        self.addCleanup(calib.invalidate)
        self.board = chessboard_image()
        info = store.put("calibtest:capture:image", self.board, flow_id=0, run_id="calibtest", pinned=True)
        self.ref = info["ref"]
        self.size = [info["width"], info["height"]]
        self.addCleanup(store.drop_run, "calibtest")

    def post(self, path: str, body: dict):
        return self.client.post(f"/api/vision/calibration/{path}", data=json.dumps(body), content_type="application/json")

    # ---- 拍照 ----
    def test_capture_uploaded_image(self):
        ok, buf = cv2.imencode(".png", self.board)
        self.assertTrue(ok)
        upload = io.BytesIO(buf.tobytes())
        upload.name = "board.png"
        r = self.client.post("/api/vision/calibration/capture", data={"image": upload})
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual([body["width"], body["height"]], list(self.board.shape[1::-1]))
        self.assertIsNotNone(store.get(body["ref"]))
        store.drop_run(body["ref"].split(":")[0])

    def test_capture_without_anything(self):
        r = self.client.post("/api/vision/calibration/capture", data={})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "no_input")

    # ---- 偵測 ----
    def test_detect_board(self):
        r = self.post("detect", {"ref": self.ref, "kind": "chessboard", "cols": 9, "rows": 6})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["found"])
        self.assertEqual(body["count"], 54)
        self.assertEqual(len(body["corners"]), 54)
        kinds = {o["kind"] for o in body["overlays"]}
        self.assertEqual(kinds, {"points", "polyline", "point"})

    def test_detect_says_why_when_it_fails(self):
        r = self.post("detect", {"ref": self.ref, "kind": "chessboard", "cols": 7, "rows": 5})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["found"])
        self.assertIn("7 x 5", r.json()["hint"])
        self.assertEqual(self.post("detect", {"ref": "gone", "cols": 9, "rows": 6}).status_code, 404)
        self.assertEqual(self.post("detect", {"ref": self.ref, "kind": "nope", "cols": 9, "rows": 6}).status_code, 422)

    # ---- 吸附 ----
    def test_snap_to_a_feature(self):
        img = np.full((200, 200), 240, np.uint8)
        cv2.circle(img, (120, 80), 12, 20, -1)
        store.put("snap:capture:image", img, flow_id=0, run_id="snap", pinned=True)
        self.addCleanup(store.drop_run, "snap")
        r = self.post("snap", {"ref": "snap:capture:image", "x": 126, "y": 86, "radius": 25})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["found"])
        self.assertAlmostEqual(body["x"], 120.0, delta=1.0)
        self.assertAlmostEqual(body["y"], 80.0, delta=1.0)
        # 空白處吸附不到就照實說，不會亂給一個點
        blank_r = self.post("snap", {"ref": "snap:capture:image", "x": 20, "y": 20, "radius": 10})
        self.assertFalse(blank_r.json()["found"])
        self.assertEqual(self.post("snap", {"ref": "snap:capture:image", "x": "a", "y": 1}).status_code, 422)

    # ---- 解算 ----
    def test_solve_board_gives_lens_and_world(self):
        corners = calib.find_board(self.board, 9, 6, "chessboard")
        views = [corners.tolist() for _ in range(4)]
        r = self.post("solve", {"mode": "board", "image_size": self.size, "cols": 9, "rows": 6, "spacing": 5.0, "views": views})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertIn("world", body["payload"])
        self.assertEqual(body["payload"]["world"]["kind"], "perspective")
        self.assertGreater(body["payload"]["world"]["mm_per_px"], 0)
        self.assertIn("mm/px", body["summary"])
        self.assertIn("world", body["quality"])
        # 只有一張時仍給世界座標，但沒有鏡頭資料
        one = self.post("solve", {"mode": "board", "image_size": self.size, "cols": 9, "rows": 6, "spacing": 5.0, "views": views[:1]})
        self.assertEqual(one.status_code, 200, one.content)
        self.assertNotIn("lens", one.json()["payload"])

    def test_coverage_endpoint_and_solve_warnings(self):
        views = [[[100 + i * 50, 100 + j * 50] for i in range(9) for j in range(6)]]
        r = self.client.post("/api/vision/calibration/coverage", data=json.dumps({"image_size": [W, H], "views": views}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["cells"], 12)
        self.assertGreater(len(body["missing"]), 0)
        self.assertTrue(any(o["kind"] == "rect" and o["color"] == "#ef4444" for o in body["overlays"]))
        self.assertTrue(body["warnings"])
        self.assertEqual(self.client.post("/api/vision/calibration/coverage", data=json.dumps({"image_size": [W], "views": []}), content_type="application/json").status_code, 422)
        # solve 回 warnings（張數少）與 coverage
        rng = np.random.default_rng(3)
        obj = calib.board_object_points(9, 6, 20.0)
        obj -= obj.mean(axis=0)
        vs = []
        for _ in range(3):
            pts, _ = cv2.projectPoints(obj.astype(np.float32), rng.uniform(-0.3, 0.3, 3), np.array([rng.uniform(-20, 20), rng.uniform(-20, 20), 500.0]), CAM, DIST)
            vs.append(pts.reshape(-1, 2).tolist())
        r = self.client.post("/api/vision/calibration/solve", data=json.dumps({"mode": "board", "image_size": [W, H], "cols": 9, "rows": 6, "spacing": 20.0, "views": vs}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["coverage"]["cells"], 12)
        self.assertTrue(any("pictures" in w for w in body["warnings"]))

    def test_solve_points_reports_residuals(self):
        truth = affine_matrix()
        px = [[100.0, 120], [900, 140], [880, 700], [120, 690], [500, 400], [300, 250], [700, 550]]
        world = calib.apply(truth, px)
        points = [{"px": p, "world": list(w)} for p, w in zip(px, world.tolist(), strict=True)]
        points[1]["world"][0] += 0.6
        r = self.post("solve", {"mode": "points", "image_size": self.size, "world_kind": "affine", "points": points})
        self.assertEqual(r.status_code, 200, r.content)
        got = r.json()["payload"]["world"]
        self.assertEqual(len(got["points"]), 7)
        self.assertEqual(int(np.argmax([p["error"] for p in got["points"]])), 1)
        self.assertGreater(got["max_error"], got["rms"])

    def test_solve_distance(self):
        r = self.post("solve", {"mode": "distance", "image_size": self.size, "distance": 25.0,
                                "points": [{"px": [100, 100]}, {"px": [600, 100]}]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertAlmostEqual(r.json()["payload"]["world"]["mm_per_px"], 0.05, places=9)

    def test_solve_robot_only_calculates_and_keeps_existing_blocks(self):
        points = robot_samples()
        points[-1]["rx"] += 5
        before = Asset.objects.count()
        r = self.post("solve", {"mode": "robot", "image_size": self.size, "points": points,
                                "camera_mode": "moving", "angle_sign": -1,
                                "lens": lens_payload()["lens"], "world": world_payload()["world"]})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        robot = body["payload"]["robot"]
        self.assertEqual(len(robot["points"]), len(points))
        self.assertEqual(int(np.argmax([p["error"] for p in robot["points"]])), len(points) - 1)
        self.assertEqual(robot["camera_mode"], "moving")
        self.assertEqual(robot["angle_sign"], -1)
        self.assertIn("lens", body["payload"])
        self.assertIn("world", body["payload"])
        self.assertIn("robot", body["summary"])
        self.assertEqual(body["quality"]["robot"], "poor")
        self.assertTrue(body["warnings"])
        self.assertEqual(Asset.objects.count(), before)

    def test_solve_robot_rotation_and_save_round_trip(self):
        angles = np.linspace(0, 2 * np.pi, 10, endpoint=False)
        arc = np.array([400, 300]) + 50 * np.column_stack([np.cos(angles), np.sin(angles)])
        r = self.post("solve", {"mode": "robot", "image_size": self.size, "kind": "translation_rotation",
                                "points": robot_samples(), "rotation_points": arc.tolist()})
        self.assertEqual(r.status_code, 200, r.content)
        payload = r.json()["payload"]
        np.testing.assert_allclose(payload["robot"]["rotation_center_px"], [400, 300], atol=0.5)
        self.assertFalse(Asset.objects.exists())
        saved = self.post("assets", {"name": "robot station", "payload": payload})
        self.assertEqual(saved.status_code, 201, saved.content)
        asset = Asset.objects.get(pk=saved.json()["id"])
        self.addCleanup(lambda: os.path.exists(asset.path) and os.remove(asset.path))
        self.assertTrue(asset.meta["has_robot"])
        self.assertFalse(asset.meta["has_lens"])
        self.assertEqual(calib.load(asset.path), payload)
        read = self.client.get(f"/api/vision/calibration/assets/{asset.id}")
        self.assertEqual(read.json()["payload"], payload)

    def test_solve_robot_bad_input_is_422(self):
        base = {"mode": "robot", "image_size": self.size, "points": robot_samples()}
        cases = [{"points": None}, {"points": [None] * 3}, {"points": robot_samples() * 30},
                 {"kind": "bad"}, {"camera_mode": []}, {"angle_sign": 2},
                 {"kind": "translation_rotation"}, {"rotation_points": {}},
                 {"rotation_points": [[1, 2]] * 201}]
        for change in cases:
            with self.subTest(change=change):
                r = self.post("solve", {**base, **change})
                self.assertEqual(r.status_code, 422, r.content)
                self.assertTrue(r.json()["error"]["message"].isascii())

    def test_solve_rejects_bad_input(self):
        cases = [
            ({"mode": "nope", "image_size": self.size}, "bad_mode"),
            ({"mode": "board", "image_size": [0, 0]}, "bad_size"),
            ({"mode": "board", "image_size": self.size, "views": []}, "no_views"),
            ({"mode": "distance", "image_size": self.size, "points": [{"px": [1, 1]}], "distance": 5}, "bad_points"),
            ({"mode": "distance", "image_size": self.size, "points": [{"px": [1, 1]}, {"px": [2, 2]}], "distance": 0}, "bad_distance"),
            ({"mode": "distance", "image_size": self.size, "points": [{"px": [1, 1]}, {"px": [1, 1]}], "distance": 5}, "bad_points"),
            ({"mode": "points", "image_size": self.size, "points": [{"px": [1, 1], "world": [0, 0]}]}, "bad_calibration"),
        ]
        for body, code in cases:
            r = self.post("solve", body)
            self.assertEqual(r.status_code, 422, (body, r.content))
            self.assertEqual(r.json()["error"]["code"], code, (body, r.content))

    def test_solve_keeps_an_existing_lens(self):
        lens = lens_payload()["lens"]
        r = self.post("solve", {"mode": "distance", "image_size": self.size, "distance": 25.0, "lens": lens,
                                "points": [{"px": [100, 100]}, {"px": [600, 100]}]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("lens", r.json()["payload"])

    # ---- 存成資產 ----
    def test_create_and_read_asset(self):
        payload = calib.validate({**lens_payload(), "world": world_payload()["world"]})
        r = self.post("assets", {"name": "station A", "group": "line 1", "payload": payload})
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        asset = Asset.objects.get(pk=body["id"])
        self.addCleanup(lambda: os.path.exists(asset.path) and os.remove(asset.path))
        self.assertEqual(asset.kind, "calibration")
        self.assertEqual(asset.group, "line 1")
        self.assertTrue(asset.meta["has_lens"])
        self.assertTrue(asset.meta["has_world"])
        self.assertGreater(asset.size, 0)
        # 讀回來
        r = self.client.get(f"/api/vision/calibration/assets/{asset.id}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["payload"]["world"]["kind"], "affine")
        self.assertIn("lens", r.json()["summary"])
        # 工具真的吃得到這個檔
        loaded = calib.load(asset.path)
        self.assertIn("lens", loaded)
        # 一般資產清單也看得到，且能依 kind 過濾
        listing = self.client.get("/api/vision/assets?kind=calibration").json()["items"]
        self.assertEqual([a["id"] for a in listing], [str(asset.id)])

    def test_asset_errors(self):
        self.assertEqual(self.post("assets", {"name": "x", "payload": {"image_size": [10, 10]}}).status_code, 422)
        r = self.client.get("/api/vision/calibration/assets/00000000-0000-0000-0000-000000000000")
        self.assertEqual(r.status_code, 404)
        image_asset = Asset.objects.create(name="img", kind="image", path="nope.png", size=1)
        self.assertEqual(self.client.get(f"/api/vision/calibration/assets/{image_asset.id}").status_code, 404)
