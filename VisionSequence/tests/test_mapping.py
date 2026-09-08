"""相機間映射測試：最小平方、不丟點、工具與 API 都用同一個 calibration payload。"""

from __future__ import annotations

import json
import math
import os

import numpy as np
from django.test import SimpleTestCase, TestCase

from apps.vision import calib
from apps.vision.models import Asset
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool, temp_dir


W, H = 1280, 960


def _affine_truth() -> np.ndarray:
    rad = math.radians(8.0)
    scale = 1.1
    return np.array([
        [scale * math.cos(rad), -scale * math.sin(rad), 30.0],
        [scale * math.sin(rad), scale * math.cos(rad), -20.0],
        [0.0, 0.0, 1.0],
    ])


def _points() -> np.ndarray:
    return np.array([[10.0, 20.0], [300.0, 40.0], [90.0, 260.0], [420.0, 310.0], [610.0, 120.0], [140.0, 500.0]])


def _pairs(matrix: np.ndarray, src: np.ndarray | None = None) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    source = _points() if src is None else src
    mapped = calib.apply(matrix, source)
    return [(tuple(a), tuple(b)) for a, b in zip(source, mapped, strict=True)]


class MappingSolveTests(SimpleTestCase):
    def test_affine_synthetic_truth_recovers_matrix_and_zero_residuals(self):
        truth = _affine_truth()
        got = calib.solve_mapping(_pairs(truth), "affine", from_source="cam A", to_source="cam B")
        np.testing.assert_allclose(got["matrix"], truth, atol=1e-6, rtol=0)
        self.assertLess(got["max_error"], 1e-9)
        self.assertLess(got["rms"], 1e-9)
        self.assertEqual(len(got["points"]), len(_points()))
        self.assertEqual((got["from_source"], got["to_source"]), ("cam A", "cam B"))
        checked = calib.validate({"image_size": [W, H], "mapping": got})
        self.assertEqual(checked["mapping"], got)
        self.assertIn("cam A to cam B affine", calib.summary(checked))
        self.assertEqual(calib.quality(checked)["mapping"], "good")

    def test_outlier_is_kept_and_has_the_largest_residual(self):
        truth = _affine_truth()
        source = _points()
        target = calib.apply(truth, source)
        target[2] += [80.0, -55.0]
        got = calib.solve_mapping([(tuple(a), tuple(b)) for a, b in zip(source, target, strict=True)], "affine")
        errors = [p["error"] for p in got["points"]]
        self.assertEqual(len(errors), len(source))
        self.assertEqual(int(np.argmax(errors)), 2)
        self.assertGreater(errors[2], 2 * max(errors[:2] + errors[3:]))
        self.assertGreater(got["max_error"], got["rms"])

    def test_perspective_uses_four_or_more_points(self):
        truth = np.array([[1.02, 0.08, 12.0], [-0.04, 0.97, 18.0], [2e-4, -1.5e-4, 1.0]])
        got = calib.solve_mapping(_pairs(truth), "perspective")
        expect = truth / truth[2, 2]
        actual = np.asarray(got["matrix"]) / np.asarray(got["matrix"])[2, 2]
        np.testing.assert_allclose(actual, expect, atol=1e-6, rtol=0)
        self.assertLess(got["max_error"], 1e-7)
        with self.assertRaises(calib.CalibError):
            calib.solve_mapping(_pairs(truth)[:3], "perspective")

    def test_two_board_views_match_direct_correspondence_solve(self):
        obj = calib.board_object_points(4, 3, 10.0)
        board_to_a = np.array([[2.0, 0.1, 30.0], [0.2, 1.8, 45.0], [0.0005, -0.0002, 1.0]])
        board_to_b = np.array([[1.7, -0.2, 100.0], [0.15, 2.2, 20.0], [-0.0001, 0.0003, 1.0]])
        corners_a = calib.apply(board_to_a, obj[:, :2])
        corners_b = calib.apply(board_to_b, obj[:, :2])
        from_board = calib.solve_mapping_from_boards(corners_a, corners_b, obj)
        direct = calib.solve_mapping([(tuple(a), tuple(b)) for a, b in zip(corners_a, corners_b, strict=True)], "perspective")
        a = np.asarray(from_board["matrix"]) / np.asarray(from_board["matrix"])[2, 2]
        b = np.asarray(direct["matrix"]) / np.asarray(direct["matrix"])[2, 2]
        np.testing.assert_allclose(a, b, atol=1e-6, rtol=0)
        self.assertLess(from_board["max_error"], 1e-6)


class MappingToolTests(SimpleTestCase):
    def setUp(self):
        self.folder = temp_dir()
        self.mapping_path = os.path.join(self.folder, "mapping.json")
        self.world_path = os.path.join(self.folder, "world.json")
        mapping = calib.solve_mapping(_pairs(_affine_truth()), "affine")
        calib.save(self.mapping_path, {"unit": "mm", "image_size": [W, H], "mapping": mapping})
        calib.save(self.world_path, {
            "unit": "mm", "image_size": [W, H],
            "world": {"kind": "affine", "matrix": [[2, 0, 10], [0, 3, 20], [0, 0, 1]], "mm_per_px": 2, "rms": 0.0, "max_error": 0.0},
        })
        self.assets = {"mapping": self.mapping_path, "world": self.world_path}

    def test_map_points_forward_inverse_round_trip(self):
        points = [[25.0, 31.0], [440.0, 120.0], [72.5, 88.25]]
        forward = run_tool("map_points", params={"calibration": "mapping"}, inputs={"points": points, "x": 11.0, "y": 7.0}, assets=self.assets)
        backward = run_tool("map_points", params={"calibration": "mapping", "direction": "inverse"},
                            inputs={"points": forward.outputs["points"], "x": forward.outputs["x"], "y": forward.outputs["y"]}, assets=self.assets)
        np.testing.assert_allclose(backward.outputs["points"], points, atol=1e-9, rtol=0)
        np.testing.assert_allclose([backward.outputs["x"], backward.outputs["y"]], [11.0, 7.0], atol=1e-9, rtol=0)

    def test_map_points_handles_matches_and_requires_mapping(self):
        result = run_tool("map_points", params={"calibration": "mapping"},
                          inputs={"matches": [{"cx": 10.0, "cy": 20.0, "angle": 5.0, "score": 0.9}]}, assets=self.assets)
        self.assertEqual(result.outputs["count"], 1)
        self.assertIn("score", result.outputs["matches"][0])
        self.assertNotEqual(result.outputs["matches"][0]["cx"], 10.0)
        with self.assertRaisesRegex(ToolError, "no mapping block"):
            run_tool("map_points", params={"calibration": "world"}, inputs={"x": 1.0, "y": 2.0}, assets=self.assets)

    def test_align_offset_without_mapping_keeps_output_keys(self):
        plain = run_tool("align_offset", params={"calibration": "world"}, inputs={"a": 30.0, "b": 40.0, "c": 90.0}, assets=self.assets)
        self.assertEqual(plain.status, "ok", plain.message)
        self.assertEqual(set(plain.outputs), {"dx", "dy", "dtheta", "transform", "abs_x", "abs_y", "abs_angle", "world_x", "world_y", "world_angle"})
        self.assertFalse(any(key.startswith("mapped_") for key in plain.outputs))
        mapped = run_tool("align_offset", params={"calibration": "mapping"}, inputs={"a": 30.0, "b": 40.0, "c": 90.0}, assets=self.assets)
        self.assertEqual(mapped.status, "ok", mapped.message)
        self.assertIn("mapped_x", mapped.outputs)
        self.assertIn("mapped_y", mapped.outputs)
        self.assertIn("mapped_angle", mapped.outputs)


class MappingApiTests(TestCase):
    def test_mapping_solve_returns_payload_and_does_not_create_asset(self):
        before = Asset.objects.count()
        truth = _affine_truth()
        points = [{"a": list(a), "b": list(b)} for a, b in _pairs(truth)]
        r = self.client.post(
            "/api/vision/calibration/solve",
            data=json.dumps({"mode": "mapping", "image_size": [W, H], "kind": "affine", "points": points}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertIn("mapping", body["payload"])
        np.testing.assert_allclose(body["payload"]["mapping"]["matrix"], truth, atol=1e-6, rtol=0)
        self.assertEqual(Asset.objects.count(), before)
