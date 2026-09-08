from __future__ import annotations

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision.tools.roi import polyline_points, resample_polyline
from tests._helpers import run_tool


def _angles(tangents: np.ndarray) -> list[float]:
    deg = np.degrees(np.arctan2(tangents[:, 1], tangents[:, 0]))
    return (((deg + 180.0) % 360.0) - 180.0).round(6).tolist()


class PolylineSamplingTests(SimpleTestCase):
    def test_l_shape_spacing_and_clockwise_angles(self):
        pts = [[0, 0], [20, 0], [20, 20]]
        samples, tangents = resample_polyline(pts, closed=False, spacing=10)

        self.assertAlmostEqual(polyline_points(pts, False), 40.0, places=6)
        self.assertEqual(samples.round(6).tolist(), [[0, 0], [10, 0], [20, 0], [20, 10], [20, 20]])
        steps = np.hypot(np.diff(samples[:, 0]), np.diff(samples[:, 1]))
        self.assertTrue(np.allclose(steps, 10.0), steps.tolist())
        # 影像座標 y 向下，因此往下的垂直段是 +90 度，符合「順時針為正」。
        self.assertEqual(_angles(tangents), [0.0, 0.0, 90.0, 90.0, 90.0])

        up_samples, up_tangents = resample_polyline([[0, 20], [0, 0]], closed=False, spacing=10)
        self.assertEqual(up_samples.round(6).tolist(), [[0, 20], [0, 10], [0, 0]])
        self.assertEqual(_angles(up_tangents), [-90.0, -90.0, -90.0])

    def test_closed_square_wraps_without_repeating_the_start(self):
        square = [[0, 0], [20, 0], [20, 20], [0, 20]]
        samples, _ = resample_polyline(square, closed=True, spacing=10)

        self.assertAlmostEqual(polyline_points(square, True), 80.0, places=6)
        self.assertEqual(len(samples), 8)
        self.assertNotEqual(samples[0].tolist(), samples[-1].tolist())
        wrapped = np.vstack([samples, samples[0]])
        steps = np.hypot(np.diff(wrapped[:, 0]), np.diff(wrapped[:, 1]))
        self.assertTrue(np.allclose(steps, 10.0), steps.tolist())

    def test_degenerate_inputs_are_empty(self):
        for pts in ([], [[1, 2]], [[3, 4], [3, 4]]):
            samples, tangents = resample_polyline(pts, closed=False, spacing=10)
            self.assertEqual(polyline_points(pts, False), 0.0)
            self.assertEqual(samples.shape, (0, 2))
            self.assertEqual(tangents.shape, (0, 2))


class PathExtractToolTests(SimpleTestCase):
    def test_equal_interval_outputs_points_angles_and_length(self):
        r = run_tool("path_extract", None, {"spacing": 10}, inputs={"points": [[0, 0], [20, 0], [20, 20]]})

        self.assertEqual((r.branch, r.status), ("ok", "ok"))
        self.assertEqual(r.outputs["points"], [[0, 0], [10, 0], [20, 0], [20, 10], [20, 20]])
        self.assertEqual(r.outputs["angles"], [0.0, 0.0, 90.0, 90.0, 90.0])
        self.assertEqual(r.outputs["count"], 5)
        self.assertAlmostEqual(r.outputs["length"], 40.0, places=6)

    def test_polygon_defaults_to_closed_and_count_takes_priority(self):
        roi = {"shape": "polygon", "points": [[0, 0], [20, 0], [20, 20], [0, 20]]}
        r = run_tool("path_extract", None, {"roi": roi, "spacing": 3, "count": 8})

        self.assertEqual((r.branch, r.status), ("ok", "ok"))
        self.assertEqual(r.outputs["count"], 8)
        wrapped = np.vstack([np.asarray(r.outputs["points"], dtype=np.float64), r.outputs["points"][0]])
        steps = np.hypot(np.diff(wrapped[:, 0]), np.diff(wrapped[:, 1]))
        self.assertTrue(np.allclose(steps, 10.0), steps.tolist())

    @staticmethod
    def _bright_block(gap: bool = False) -> np.ndarray:
        img = np.full((180, 180), 30, np.uint8)
        cv2.rectangle(img, (40, 40), (140, 140), 220, -1)
        if gap:
            img[40:60, 80:101] = 30
        return cv2.GaussianBlur(img, (0, 0), 0.8)

    def test_edge_search_finds_polygon_boundary(self):
        path = [[45, 35], [135, 35]]
        r = run_tool("path_extract", self._bright_block(), {
            "mode": "edge_search", "spacing": 10, "search": 12, "caliper_width": 3,
            "polarity": "dark_to_light", "edge_threshold": 15,
        }, inputs={"points": path})

        self.assertEqual((r.branch, r.status), ("ok", "ok"), r.message)
        self.assertEqual(r.outputs["missing"], [])
        pts = np.asarray(r.outputs["points"], dtype=np.float64)
        err = np.abs(pts[:, 1] - 39.5)
        self.assertLess(float(err.max()), 1.0, err.tolist())
        self.assertTrue(np.all((pts[:, 0] >= 44.5) & (pts[:, 0] <= 135.5)))
        self.assertTrue(all(o > 0 for o in r.outputs["offsets"]))

    def test_edge_search_reports_missing_indices_on_a_gap(self):
        path = [[45, 35], [135, 35]]
        r = run_tool("path_extract", self._bright_block(gap=True), {
            "mode": "edge_search", "spacing": 10, "search": 12, "caliper_width": 3,
            "polarity": "dark_to_light", "edge_threshold": 15,
        }, inputs={"points": path})

        self.assertEqual((r.branch, r.status), ("not_found", "ng"))
        self.assertTrue(r.outputs["missing"])
        samples, _ = resample_polyline(path, closed=False, spacing=10)
        missing_x = [samples[i, 0] for i in r.outputs["missing"]]
        self.assertTrue(any(80 <= x <= 100 for x in missing_x), missing_x)

    def test_degenerate_paths_return_not_found(self):
        img = np.full((40, 40), 0, np.uint8)
        for pts in ([], [[1, 1]], [[1, 1], [1, 1]]):
            r = run_tool("path_extract", img, {"mode": "edge_search"}, inputs={"points": pts})
            self.assertEqual((r.branch, r.status), ("not_found", "ng"))
            self.assertEqual(r.outputs["points"], [])

    def test_edge_search_does_not_modify_input_image(self):
        img = self._bright_block()
        before = img.copy()
        run_tool("path_extract", img, {
            "mode": "edge_search", "spacing": 10, "search": 12,
            "polarity": "dark_to_light", "edge_threshold": 15,
        }, inputs={"points": [[45, 35], [135, 35]]})
        self.assertTrue(np.array_equal(img, before))
