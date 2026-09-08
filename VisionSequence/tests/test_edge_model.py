"""edge_model_defect：任意輪廓模型的教導、取邊、分段與位置修正。"""

from __future__ import annotations

import cv2
import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.vision import fixed_images
from apps.vision.tools import base
from apps.vision.tools.builtin.edge_defect import teach_contour
from tests._helpers import run_tool, temp_dir


BG = 30
FG = 220
HEX = np.array([[90, 50], [150, 50], [190, 100], [150, 170], [90, 170], [50, 100]], dtype=np.float32)
MODEL = {"version": 1, "image_size": [240, 220], "closed": True, "points": HEX.tolist()}


def _part(*, notch: bool = False, burr: bool = False, fracture: bool = False) -> np.ndarray:
    img = np.full((220, 240), BG, np.uint8)
    cv2.fillPoly(img, [np.round(HEX).astype(np.int32)], FG)
    if notch:
        cv2.rectangle(img, (110, 45), (130, 54), BG, -1)
    if burr:
        cv2.rectangle(img, (110, 45), (130, 49), FG, -1)
    if fracture:
        cv2.rectangle(img, (110, 35), (130, 80), BG, -1)
    return cv2.GaussianBlur(img, (0, 0), 0.7)


def _params(**kw):
    params = {
        "model": MODEL,
        "calipers": 240,
        "search": 28,
        "caliper_width": 3,
        "polarity": "light_to_dark",
        "edge_threshold": 12,
        "threshold": 2.0,
        "min_width": 3,
        "fracture_run": 3,
        "step_threshold": 0,
    }
    params.update(kw)
    return params


class TeachContourTests(SimpleTestCase):
    def test_teach_contour_recovers_synthetic_hexagon_vertices(self):
        pts = np.asarray(teach_contour(_part(), simplify=2.0), dtype=np.float64)

        self.assertGreaterEqual(len(pts), 6)
        self.assertLessEqual(len(pts), 8)
        dists = []
        for vx, vy in HEX:
            d = np.hypot(pts[:, 0] - vx, pts[:, 1] - vy)
            dists.append(float(d.min()))
        self.assertLess(max(dists), 2.0, dists)

    def test_teach_contour_does_not_modify_input_image(self):
        img = _part()
        before = img.copy()
        teach_contour(img)

        self.assertTrue(np.array_equal(img, before))


class EdgeModelDefectTests(SimpleTestCase):
    def test_good_part_is_ok(self):
        result = run_tool("edge_model_defect", _part(), _params())

        self.assertEqual((result.branch, result.status), ("ok", "ok"), result.message)
        self.assertEqual(result.outputs["count"], 0)
        self.assertEqual(result.outputs["missing"], [])
        self.assertLess(result.outputs["max_deviation"], 2.0)

    def test_five_pixel_notch_is_one_inward_defect_at_the_notch(self):
        result = run_tool("edge_model_defect", _part(notch=True), _params(direction="both"))

        self.assertEqual((result.branch, result.status), ("defect", "ng"), result.message)
        self.assertEqual(result.outputs["count"], 1, result.outputs["defects"])
        defect = result.outputs["defects"][0]
        self.assertEqual(defect["direction"], "inward")
        self.assertAlmostEqual(abs(defect["max_deviation"]), 5.0, delta=1.0)
        rect = defect["rect"]
        self.assertIsNotNone(rect)
        self.assertAlmostEqual(rect["cx"], 120, delta=4.0)
        self.assertAlmostEqual(rect["cy"], 55, delta=4.0)

    def test_extra_material_is_outward_and_ignored_when_only_inward_counts(self):
        both = run_tool("edge_model_defect", _part(burr=True), _params(direction="both"))
        inward = run_tool("edge_model_defect", _part(burr=True), _params(direction="inward"))

        self.assertEqual(both.outputs["count"], 1, both.outputs["defects"])
        self.assertEqual(both.outputs["defects"][0]["direction"], "outward")
        self.assertEqual((inward.branch, inward.status), ("ok", "ok"), inward.message)
        self.assertEqual(inward.outputs["count"], 0)

    def test_cut_through_run_is_missing_and_fracture(self):
        result = run_tool("edge_model_defect", _part(fracture=True), _params())

        self.assertEqual((result.branch, result.status), ("defect", "ng"), result.message)
        self.assertTrue(result.outputs["missing"])
        self.assertEqual(result.outputs["count"], 1, result.outputs["defects"])
        defect = result.outputs["defects"][0]
        self.assertEqual(defect["type"], "fracture")
        self.assertEqual(defect["direction"], "missing")
        self.assertAlmostEqual(defect["rect"]["cx"], 120, delta=4.0)
        self.assertAlmostEqual(defect["rect"]["cy"], 50, delta=3.0)

    def test_transform_moves_the_model_with_the_part(self):
        img = _part()
        pivot = (120.0, 110.0)
        dx, dy, dtheta = 7.0, -4.0, 12.0
        mat = cv2.getRotationMatrix2D(pivot, -dtheta, 1.0)
        mat[0, 2] += dx
        mat[1, 2] += dy
        moved = cv2.warpAffine(img, mat, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR, borderValue=BG)

        result = run_tool(
            "edge_model_defect",
            moved,
            _params(),
            inputs={base.TRANSFORM_IN: {"dx": dx, "dy": dy, "dtheta": dtheta, "pivot": list(pivot)}},
        )

        self.assertEqual((result.branch, result.status), ("ok", "ok"), result.message)
        self.assertEqual(result.outputs["count"], 0)
        self.assertLess(result.outputs["max_deviation"], 2.0)

    def test_empty_model_auto_teaches_from_reference_picture(self):
        folder = temp_dir()
        with override_settings(VISION={**settings.VISION, "ASSET_DIR": folder}):
            ref = fixed_images.store(_part(), "hex")
            result = run_tool("edge_model_defect", _part(), _params(model=None, reference=[ref]))

        self.assertEqual((result.branch, result.status), ("ok", "ok"), result.message)
        self.assertTrue(result.detail["auto_taught"])
        self.assertIn("auto-taught", result.message)

    def test_execute_does_not_modify_input_image(self):
        img = _part(notch=True)
        before = img.copy()
        run_tool("edge_model_defect", img, _params())

        self.assertTrue(np.array_equal(img, before))
