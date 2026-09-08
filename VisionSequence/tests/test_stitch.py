"""影像拼接工具測試。"""

from __future__ import annotations

import os
import tempfile

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision import calib
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool


def _inputs(*images: np.ndarray) -> dict[str, np.ndarray]:
    return {f"image_{i}": image for i, image in enumerate(images, start=1)}


def _save_world(folder: str, name: str, image: np.ndarray, matrix: np.ndarray) -> str:
    h, w = image.shape[:2]
    path = os.path.join(folder, name)
    calib.save(path, {
        "unit": "px",
        "image_size": [w, h],
        "world": {
            "kind": "perspective",
            "matrix": matrix.tolist(),
            "mm_per_px": 1.0,
            "rms": 0.0,
            "max_error": 0.0,
        },
    })
    return path


class StitchGridTests(SimpleTestCase):
    def test_grid_2x2_cut_image_stitches_back_pixel_exact(self):
        yy, xx = np.mgrid[:60, :80]
        image = np.dstack([
            (xx * 3 + yy) % 256,
            (xx + yy * 5) % 256,
            (xx * 7 + yy * 11) % 256,
        ]).astype(np.uint8)
        pieces = [image[:30, :40], image[:30, 40:], image[30:, :40], image[30:, 40:]]

        result = run_tool("stitch_images", None, {"mode": "grid", "rows": 2, "cols": 2, "order": "row_major"}, _inputs(*pieces))

        self.assertEqual(result.outputs["count"], 4)
        self.assertEqual((result.outputs["width"], result.outputs["height"]), (80, 60))
        self.assertEqual(result.outputs["offsets"], [
            {"index": 1, "x": 0, "y": 0},
            {"index": 2, "x": 40, "y": 0},
            {"index": 3, "x": 0, "y": 30},
            {"index": 4, "x": 40, "y": 30},
        ])
        np.testing.assert_array_equal(result.outputs["image"], image)

    def test_trim_changes_grid_output_size(self):
        a = np.full((5, 6), 10, np.uint8)
        b = np.full((5, 6), 20, np.uint8)

        result = run_tool("stitch_images", None, {"mode": "grid", "rows": 1, "cols": 2, "trim": 1}, _inputs(a, b))

        self.assertEqual((result.outputs["width"], result.outputs["height"]), (8, 3))
        self.assertEqual(result.outputs["image"].shape, (3, 8))
        self.assertTrue(np.all(result.outputs["image"][:, :4] == 10))
        self.assertTrue(np.all(result.outputs["image"][:, 4:] == 20))

    def test_blend_modes_define_overlap_values(self):
        a = np.full((3, 4), 10, np.uint8)
        b = np.full((3, 4), 21, np.uint8)
        expected = {"mean": 16, "min": 10, "max": 21, "uncover": 21}
        for blend, value in expected.items():
            with self.subTest(blend=blend):
                result = run_tool(
                    "stitch_images",
                    None,
                    {"mode": "grid", "rows": 1, "cols": 2, "overlap_x": 2, "blend": blend},
                    _inputs(a, b),
                )
                out = result.outputs["image"]
                self.assertEqual(out.shape, (3, 6))
                self.assertTrue(np.all(out[:, 2:4] == value), (blend, out[:, 2:4]))

    def test_size_mismatch_names_the_image(self):
        a = np.zeros((3, 4), np.uint8)
        b = np.zeros((4, 4), np.uint8)

        with self.assertRaisesMessage(ToolError, "Image 2"):
            run_tool("stitch_images", None, {"mode": "grid", "rows": 1, "cols": 2}, _inputs(a, b))

    def test_inputs_are_not_modified(self):
        a = np.arange(12, dtype=np.uint8).reshape(3, 4)
        b = np.arange(12, 24, dtype=np.uint8).reshape(3, 4)
        before_a = a.copy()
        before_b = b.copy()

        run_tool("stitch_images", None, {"mode": "grid", "rows": 1, "cols": 2, "overlap_x": 1, "blend": "mean"}, _inputs(a, b))

        np.testing.assert_array_equal(a, before_a)
        np.testing.assert_array_equal(b, before_b)


class StitchHomographyTests(SimpleTestCase):
    def test_homography_reprojects_two_perspective_halves_to_world_plane(self):
        yy, xx = np.mgrid[:80, :120]
        truth = np.clip(35 + xx * 1.3 + yy * 0.7 + 18 * np.sin(xx / 9.0), 0, 255).astype(np.uint8)
        left_world = np.array([[0, 0], [72, 0], [66, 80], [0, 80]], dtype=np.float32)
        right_world = np.array([[48, 0], [120, 0], [120, 80], [54, 80]], dtype=np.float32)
        left_size = (74, 84)
        right_size = (74, 84)
        left_px = np.array([[0, 0], [left_size[0], 0], [left_size[0], left_size[1]], [0, left_size[1]]], dtype=np.float32)
        right_px = np.array([[0, 0], [right_size[0], 0], [right_size[0], right_size[1]], [0, right_size[1]]], dtype=np.float32)
        left_px_to_world = cv2.getPerspectiveTransform(left_px, left_world).astype(np.float64)
        right_px_to_world = cv2.getPerspectiveTransform(right_px, right_world).astype(np.float64)
        left = cv2.warpPerspective(truth, np.linalg.inv(left_px_to_world), left_size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        right = cv2.warpPerspective(truth, np.linalg.inv(right_px_to_world), right_size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        folder = tempfile.mkdtemp(prefix="vs-stitch-")
        assets = {
            "left": _save_world(folder, "left.json", left, left_px_to_world),
            "right": _save_world(folder, "right.json", right, right_px_to_world),
        }

        result = run_tool(
            "stitch_images",
            None,
            {"mode": "homography", "blend": "mean", "scale": 1, "calibration_1": "left", "calibration_2": "right"},
            _inputs(left, right),
            assets=assets,
        )

        out = result.outputs["image"]
        self.assertEqual(out.shape, truth.shape)
        self.assertEqual(result.outputs["origin"], [0.0, 0.0])
        self.assertEqual(result.outputs["scale"], 1.0)
        diff = cv2.absdiff(out, truth)
        self.assertLess(float(diff.mean()), 1.6)
        self.assertLess(float(np.percentile(diff, 95)), 5.0)
        self.assertLessEqual(int(diff.max()), 50)
