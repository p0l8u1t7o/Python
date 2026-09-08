from __future__ import annotations

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision.tools.builtin.locate import find_edges_1d, pick_pair
from tests._helpers import run_tool


class CaliperTrendTests(SimpleTestCase):
    """D5 卡尺多候選與整條邊趨勢的合成真值測試。"""

    @staticmethod
    def _horizontal_edge(*, shifted: bool = False) -> np.ndarray:
        img = np.full((140, 220), 40, np.uint8)
        for x in range(img.shape[1]):
            y = 70 + (3 if shifted and 90 <= x < 130 else 0)
            img[y:, x] = 210
        return cv2.GaussianBlur(img, (0, 0), 0.8)

    @staticmethod
    def _bars() -> np.ndarray:
        img = np.full((90, 220), 40, np.uint8)
        img[:, 30:50] = 200
        img[:, 80:100] = 200
        img[:, 130:150] = 200
        return cv2.GaussianBlur(img, (0, 0), 0.8)

    def test_edge_trend_clean_reference_offsets_are_near_zero(self):
        img = self._horizontal_edge()
        line = {"x1": 20, "y1": 69.5, "x2": 200, "y2": 69.5}
        r = run_tool(
            "edge_trend",
            img,
            {"calipers": 36, "search": 24, "caliper_width": 5, "polarity": "dark_to_light", "edge_threshold": 10, "baseline": "reference"},
            inputs={"line": line},
        )
        self.assertEqual((r.branch, r.status), ("ok", "ok"))
        offsets = np.array(r.outputs["offsets"], dtype=np.float64)
        self.assertLess(float(np.nanmax(np.abs(offsets))), 0.25)
        self.assertEqual(r.outputs["missing"], [])

    def test_edge_trend_reports_a_three_pixel_shifted_segment(self):
        img = self._horizontal_edge(shifted=True)
        line = {"x1": 20, "y1": 69.5, "x2": 200, "y2": 69.5}
        r = run_tool(
            "edge_trend",
            img,
            {"calipers": 60, "search": 24, "caliper_width": 5, "polarity": "dark_to_light", "edge_threshold": 10,
             "baseline": "reference", "max_deviation": 2},
            inputs={"line": line},
        )
        self.assertEqual((r.branch, r.status), ("ng", "ng"))
        positions = np.array(r.outputs["positions"], dtype=np.float64)
        offsets = np.array(r.outputs["offsets"], dtype=np.float64)
        shifted = (positions >= 70) & (positions <= 115)
        self.assertGreater(int(shifted.sum()), 5)
        self.assertLess(abs(float(np.nanmedian(offsets[shifted])) - 3.0), 0.35)
        self.assertLess(abs(r.outputs["max"] - 3.0), 0.35)

    def test_caliper_multiple_results_sort_by_position(self):
        r = run_tool(
            "caliper",
            self._bars(),
            {"roi": {"shape": "rect", "x": 0, "y": 20, "w": 190, "h": 40}, "pair_polarity": "bright",
             "max_results": 3, "sort_by": "position", "edge_threshold": 10},
        )
        self.assertEqual(r.status, "ok")
        centers = [edge["position"] for edge in r.outputs["edges"]]
        self.assertEqual(len(centers), 3)
        self.assertLess(abs(centers[0] - 39.5), 0.5)
        self.assertLess(abs(centers[1] - 89.5), 0.5)
        self.assertLess(abs(centers[2] - 139.5), 0.5)

    def test_caliper_position_weight_can_choose_the_weaker_expected_edge(self):
        img = np.full((80, 220), 40, np.uint8)
        img[:, 45:55] = 100
        img[:, 150:160] = 230
        img = cv2.GaussianBlur(img, (0, 0), 0.8)
        params = {"roi": {"shape": "rect", "x": 0, "y": 20, "w": 200, "h": 40}, "pair_polarity": "bright", "edge_threshold": 5}
        strong = run_tool("caliper", img, {**params, "max_results": 2})
        weighted = run_tool("caliper", img, {**params, "expected_position": 50, "position_weight": 5, "contrast_weight": 1})
        strong_center = strong.outputs["edges"][0]["position"]
        weighted_center = weighted.outputs["edges"][0]["position"]
        self.assertGreater(strong_center, 140)
        self.assertLess(abs(weighted_center - 49.5), 0.5)

    def test_caliper_default_single_result_matches_legacy_pair_pick(self):
        img = self._bars()
        roi = {"shape": "rect", "x": 0, "y": 20, "w": 190, "h": 40}
        r = run_tool("caliper", img, {"roi": roi, "edge_threshold": 10})
        profile = cv2.reduce(np.ascontiguousarray(img[20:60, 0:190]), 0, cv2.REDUCE_AVG, dtype=cv2.CV_64F).reshape(-1)
        pair = pick_pair(find_edges_1d(profile, "any", 10, 3), "first_last", "any", 0)
        self.assertIsNotNone(pair)
        expected = abs(pair[1][0] - pair[0][0])
        self.assertLess(abs(r.outputs["width"] - expected), 0.01)
        self.assertEqual(len(r.outputs["edges"]), 1)

    def test_edge_trend_missing_calipers_are_kept(self):
        img = np.full((120, 180), 40, np.uint8)
        line = {"x1": 20, "y1": 60, "x2": 160, "y2": 60}
        r = run_tool(
            "edge_trend",
            img,
            {"calipers": 12, "search": 20, "polarity": "dark_to_light", "edge_threshold": 10, "baseline": "reference"},
            inputs={"line": line},
        )
        self.assertEqual((r.branch, r.status), ("ng", "ng"))
        self.assertEqual(r.outputs["missing"], list(range(12)))
        self.assertTrue(all(v is None for v in r.outputs["offsets"]))

    def test_tools_do_not_modify_the_input_image(self):
        img = self._horizontal_edge(shifted=True)
        before = img.copy()
        line = {"x1": 20, "y1": 69.5, "x2": 200, "y2": 69.5}
        run_tool("edge_trend", img, {"calipers": 20, "search": 24, "polarity": "dark_to_light", "edge_threshold": 10}, inputs={"line": line})
        run_tool("caliper", img, {"roi": {"shape": "rect", "x": 40, "y": 50, "w": 120, "h": 40}, "edge_threshold": 10})
        self.assertTrue(np.array_equal(img, before))
