from __future__ import annotations

import cv2
import numpy as np
from django.test import SimpleTestCase

from tests._helpers import run_tool


def _uneven_text_image() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    image = np.empty((96, 180), dtype=np.uint8)
    image[:, :90] = 115
    image[:, 90:] = 205
    before = image.copy()
    cv2.putText(image, "VS", (17, 58), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 72, 2, cv2.LINE_8)
    cv2.putText(image, "VS", (107, 58), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 72, 2, cv2.LINE_8)
    text = before != image
    left = text & (np.indices(image.shape)[1] < 90)
    right = text & (np.indices(image.shape)[1] >= 90)
    return image, left, right


class ThresholdNormalizeTests(SimpleTestCase):
    def test_sauvola_and_niblack_split_text_on_dark_and_bright_sides(self):
        image, left_text, right_text = _uneven_text_image()
        global_mask = run_tool(
            "threshold",
            image,
            {"method": "fixed", "threshold": 60, "invert": True},
        ).outputs["image"]
        self.assertEqual(int(np.count_nonzero(global_mask[left_text])), 0)
        self.assertEqual(int(np.count_nonzero(global_mask[right_text])), 0)

        sauvola = run_tool(
            "threshold",
            image,
            {"method": "sauvola", "window": 31, "k": 0.2, "invert": True},
        ).outputs["image"]
        niblack = run_tool(
            "threshold",
            image,
            {"method": "niblack", "window": 31, "k": -0.2, "invert": True},
        ).outputs["image"]

        self.assertGreater(int(np.count_nonzero(sauvola[left_text])), 100)
        self.assertGreater(int(np.count_nonzero(sauvola[right_text])), 100)
        self.assertGreater(int(np.count_nonzero(niblack[left_text])), 100)
        self.assertGreater(int(np.count_nonzero(niblack[right_text])), 100)

    def test_compare_modes(self):
        image = np.array([[100, 127, 128, 129]], dtype=np.uint8)
        expected = {
            "ge": [[0, 0, 255, 255]],
            "le": [[255, 255, 255, 0]],
            "eq": [[0, 0, 255, 0]],
            "ne": [[255, 255, 0, 255]],
        }
        for compare, want in expected.items():
            with self.subTest(compare=compare):
                out = run_tool("threshold", image, {"method": "fixed", "threshold": 128, "compare": compare}).outputs["image"]
                self.assertEqual(out.tolist(), want)

    def test_threshold_offset_positive_and_negative(self):
        image = np.array([[90, 100, 110]], dtype=np.uint8)
        high = run_tool("threshold", image, {"method": "fixed", "threshold": 100, "offset": 20}).outputs["image"]
        low = run_tool("threshold", image, {"method": "fixed", "threshold": 100, "offset": -20}).outputs["image"]
        self.assertEqual(high.tolist(), [[0, 0, 0]])
        self.assertEqual(low.tolist(), [[255, 255, 255]])

    def test_outside_roi_black_and_keep(self):
        image = np.full((5, 5), 80, dtype=np.uint8)
        image[1:4, 1:4] = 160
        roi = {"shape": "rect", "x": 1, "y": 1, "w": 3, "h": 3}

        black = run_tool("threshold", image, {"method": "fixed", "threshold": 100, "roi": roi, "outside_roi": "black"}).outputs["image"]
        keep = run_tool("threshold", image, {"method": "fixed", "threshold": 100, "roi": roi, "outside_roi": "keep"}).outputs["image"]

        self.assertEqual(int(black[0, 0]), 0)
        self.assertEqual(int(black[2, 2]), 255)
        self.assertEqual(int(keep[0, 0]), 80)
        self.assertEqual(int(keep[2, 2]), 255)

    def test_normalize_ratio_uses_percentiles_not_outliers(self):
        image = np.array([[0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 255]], dtype=np.uint8)
        out = run_tool("lut", image, {"mode": "normalize_ratio", "low_percent": 10, "high_percent": 90}).outputs["image"]

        self.assertEqual(int(out[0, 1]), 0)
        self.assertEqual(int(out[0, 9]), 255)
        self.assertGreater(int(out[0, 8]) - int(out[0, 2]), 180)
        self.assertEqual(int(out[0, 10]), 255)

    def test_normalize_std_hits_target_mean_and_std(self):
        image = np.arange(100, dtype=np.uint8).reshape(10, 10)
        out = run_tool("lut", image, {"mode": "normalize_std", "target_mean": 120, "target_std": 30}).outputs["image"]

        self.assertLess(abs(float(out.mean()) - 120.0), 1.0)
        self.assertLess(abs(float(out.std()) - 30.0), 1.0)

    def test_geometry_offset_points_and_matches_add_and_subtract(self):
        points = [[1.0, 2.0], [3.5, 4.5]]
        added = run_tool("geometry", params={"mode": "offset", "offset_x": 10, "offset_y": -3}, inputs={"points": points}).outputs["points"]
        subtracted = run_tool("geometry", params={"mode": "offset", "offset_x": 10, "offset_y": -3, "sign": "subtract"}, inputs={"points": points}).outputs["points"]
        self.assertEqual(added, [[11.0, -1.0], [13.5, 1.5]])
        self.assertEqual(subtracted, [[-9.0, 5.0], [-6.5, 7.5]])
        self.assertEqual(points, [[1.0, 2.0], [3.5, 4.5]])

        matches = [{"x": 1.0, "y": 2.0, "cx": 6.0, "cy": 7.0, "w": 10, "h": 12, "score": 0.9}]
        shifted = run_tool("geometry", params={"mode": "offset", "offset_x": 4, "offset_y": 5}, inputs={"matches": matches}).outputs["matches"]
        back = run_tool("geometry", params={"mode": "offset", "offset_x": 4, "offset_y": 5, "sign": "subtract"}, inputs={"matches": shifted}).outputs["matches"]
        self.assertEqual(shifted[0]["x"], 5.0)
        self.assertEqual(shifted[0]["y"], 7.0)
        self.assertEqual(shifted[0]["cx"], 10.0)
        self.assertEqual(shifted[0]["cy"], 12.0)
        self.assertEqual(back, matches)

    def test_geometry_offset_accepts_crop_offset_ports(self):
        image = np.arange(100, dtype=np.uint8).reshape(10, 10)
        crop = run_tool("crop", image, {"roi": {"shape": "rect", "x": 3, "y": 4, "w": 4, "h": 3}}).outputs
        result = run_tool(
            "geometry",
            params={"mode": "offset"},
            inputs={"points": [[1.0, 2.0]], "offset_x": crop["offset_x"], "offset_y": crop["offset_y"]},
        )
        self.assertEqual(result.outputs["points"], [[4.0, 6.0]])

    def test_threshold_and_lut_do_not_mutate_input_images(self):
        image = np.arange(25, dtype=np.uint8).reshape(5, 5)
        original = image.copy()
        run_tool("threshold", image, {"method": "sauvola", "window": 5, "k": 0.2})
        self.assertTrue(np.array_equal(image, original))
        run_tool("lut", image, {"mode": "normalize_ratio", "low_percent": 10, "high_percent": 90})
        self.assertTrue(np.array_equal(image, original))
