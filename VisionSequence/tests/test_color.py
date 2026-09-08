from __future__ import annotations

import tempfile

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.vision import fixed_images
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool


SEGMENTS = "\n".join([
    "red:170,10,80,255,80,255",
    "green:45,85,80,255,80,255",
    "blue:110,130,80,255,80,255",
])


def _colour_blocks() -> np.ndarray:
    image = np.zeros((80, 220, 3), dtype=np.uint8)
    image[10:50, 10:70] = (0, 0, 255)
    image[10:50, 80:140] = (0, 255, 0)
    image[10:50, 150:210] = (255, 0, 0)
    return image


class ColorSegmentTests(SimpleTestCase):
    def test_color_segment_areas_and_hue_wrap(self):
        image = _colour_blocks()
        result = run_tool("color_segment", image, {"segments": SEGMENTS, "space": "hsv"})
        self.assertEqual(result.outputs["classes"], ["red", "green", "blue"])
        labels = result.outputs["labels"]
        self.assertEqual(labels.dtype, np.uint8)
        expected = 40 * 60
        areas = {item["label"]: item["area"] for item in result.outputs["areas"]}
        for name in ("red", "green", "blue"):
            self.assertLess(abs(areas[name] - expected) / expected, 0.02)
        self.assertEqual(int(np.count_nonzero(labels == 1)), expected)
        self.assertEqual(int(np.count_nonzero(labels == 2)), expected)
        self.assertEqual(int(np.count_nonzero(labels == 3)), expected)

    def test_color_segment_labels_feed_blob_label(self):
        segmented = run_tool("color_segment", _colour_blocks(), {"segments": SEGMENTS, "space": "hsv"})
        labelled = run_tool(
            "blob_label",
            None,
            {"classes": "1:red\n2:green\n3:blue", "min_area": 10, "min_count": 3, "max_count_ok": 3},
            inputs={"labels": segmented.outputs["labels"]},
        )
        self.assertEqual(labelled.status, "ok", labelled.message)
        self.assertEqual(labelled.outputs["count"], 3)
        self.assertEqual({item["label"]: item["count"] for item in labelled.outputs["counts"]}, {"red": 1, "green": 1, "blue": 1})


class ColorClassifyTests(SimpleTestCase):
    def test_color_classify_samples_and_ng(self):
        with tempfile.TemporaryDirectory(prefix="vs-colour-") as folder:
            vision = {**settings.VISION, "ASSET_DIR": folder}
            with override_settings(VISION=vision):
                samples = [
                    fixed_images.store(np.full((24, 24, 3), (0, 0, 255), np.uint8), "red"),
                    fixed_images.store(np.full((24, 24, 3), (0, 255, 0), np.uint8), "green"),
                    fixed_images.store(np.full((24, 24, 3), (255, 0, 0), np.uint8), "blue"),
                ]
                green = np.full((30, 30, 3), (0, 255, 0), np.uint8)
                result = run_tool("color_classify", green, {"samples": samples, "space": "hsv", "bins": 16, "min_similarity": 0.95})
                self.assertEqual(result.status, "ok", result.message)
                self.assertEqual(result.branch, "ok")
                self.assertEqual(result.outputs["label"], "green")
                self.assertGreaterEqual(result.outputs["similarity"], 0.99)
                self.assertEqual(len(result.outputs["ranking"]), 3)

                yellow = np.full((30, 30, 3), (0, 255, 255), np.uint8)
                ng = run_tool("color_classify", yellow, {"samples": samples, "space": "hsv", "bins": 16, "min_similarity": 0.95})
                self.assertEqual(ng.status, "ng")
                self.assertEqual(ng.branch, "ng")


class ColorConvertMergeTests(SimpleTestCase):
    def test_merge_rgb_preserves_channels(self):
        r = np.array([[1, 2], [3, 4]], dtype=np.uint8)
        g = np.array([[10, 20], [30, 40]], dtype=np.uint8)
        b = np.array([[100, 110], [120, 130]], dtype=np.uint8)
        result = run_tool("color_convert", None, {"mode": "merge_rgb"}, inputs={"r": r, "g": g, "b": b})
        image = result.outputs["image"]
        np.testing.assert_array_equal(image[:, :, 2], r)
        np.testing.assert_array_equal(image[:, :, 1], g)
        np.testing.assert_array_equal(image[:, :, 0], b)

    def test_merge_rgb_rejects_size_mismatch(self):
        with self.assertRaisesMessage(ToolError, "first channel"):
            run_tool(
                "color_convert",
                None,
                {"mode": "merge_rgb"},
                inputs={"r": np.zeros((2, 2), np.uint8), "g": np.zeros((3, 2), np.uint8)},
            )


class ColorPurityTests(SimpleTestCase):
    def test_color_tools_do_not_modify_inputs(self):
        image = _colour_blocks()
        original = image.copy()
        run_tool("color_segment", image, {"segments": SEGMENTS, "space": "hsv"})
        np.testing.assert_array_equal(image, original)

        r = np.array([[1, 2], [3, 4]], dtype=np.uint8)
        g = np.array([[10, 20], [30, 40]], dtype=np.uint8)
        b = np.array([[100, 110], [120, 130]], dtype=np.uint8)
        before = (r.copy(), g.copy(), b.copy())
        run_tool("color_convert", None, {"mode": "merge_rgb"}, inputs={"r": r, "g": g, "b": b})
        np.testing.assert_array_equal(r, before[0])
        np.testing.assert_array_equal(g, before[1])
        np.testing.assert_array_equal(b, before[2])

        with tempfile.TemporaryDirectory(prefix="vs-colour-") as folder:
            vision = {**settings.VISION, "ASSET_DIR": folder}
            with override_settings(VISION=vision):
                samples = [fixed_images.store(np.full((8, 8, 3), (0, 0, 255), np.uint8), "red")]
                run_tool("color_classify", image, {"samples": samples, "space": "hsv", "bins": 8, "min_similarity": 0})
        np.testing.assert_array_equal(image, original)
