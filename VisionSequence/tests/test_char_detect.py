"""單字元偵測的合成真值、旋轉分類、缺席與圖接線回歸。"""

from unittest.mock import patch

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision.demo_images import character_scene, character_tiles
from apps.vision.graph import validate_graph
from apps.vision.tools.base import ToolError
from tests._helpers import run_tool


class CharDetectTests(SimpleTestCase):
    def classify(self, image, **params):
        tiles = character_tiles()
        if params.get("polarity") == "light_on_dark":
            tiles = {key: 255 - tile for key, tile in tiles.items()}
        refs = [{"id": label, "name": label + ".png"} for label in tiles]
        with patch("apps.vision.fixed_images.load", side_effect=tiles.get):
            return run_tool("char_detect", image, {"classifier": "templates", "templates": refs, "merge_gap": 2, **params})

    def test_templates_all_layouts_and_rotations(self):
        for layout in ("reading", "arc", "scattered"):
            with self.subTest(layout=layout):
                image, centers = character_scene(layout)
                before = image.copy()
                result = self.classify(image, order="arc" if layout == "arc" else "reading")
                self.assertEqual(result.status, "ok")
                self.assertEqual(result.outputs["count"], 6)
                np.testing.assert_array_equal(image, before)
                for expected, center in zip("FPRATE", centers):
                    char = min(result.outputs["chars"], key=lambda c: np.linalg.norm(np.array([c["cx"], c["cy"]]) - center))
                    self.assertEqual(char["label"], expected)
                    self.assertLess(np.linalg.norm(np.array([char["cx"], char["cy"]]) - center), 3)
                    self.assertGreater(char["score"], 0.6)
                    self.assertEqual(np.asarray(char["polygon"]).shape, (4, 2))
                if layout != "scattered":
                    self.assertEqual(result.outputs["text"], "FPRATE")

    def test_thresholds_polarities_depths_roi_and_expected(self):
        image, _ = character_scene("reading")
        for method in ("otsu", "sauvola", "fixed"):
            for polarity in ("dark_on_light", "light_on_dark"):
                source = image if polarity == "dark_on_light" else 255 - image
                for dtype in (np.uint8, np.uint16, np.float32):
                    with self.subTest(method=method, polarity=polarity, dtype=dtype):
                        value = source.astype(dtype) * (257 if dtype == np.uint16 else 1)
                        result = self.classify(value, method=method, polarity=polarity, expected_text="FPRATE",
                                               roi={"shape": "rect", "x": 120, "y": 300, "w": 730, "h": 100})
                        self.assertEqual(result.status, "ok")
                        self.assertEqual(result.outputs["text"], "FPRATE")
        bad = self.classify(image, expected_text="OTHER")
        self.assertEqual((bad.status, bad.branch), ("ng", "ng"))

    def test_not_found_missing_inputs_and_missing_templates(self):
        empty = np.full((97, 333), 255, np.uint8)
        result = run_tool("char_detect", empty)
        self.assertEqual((result.status, result.branch, result.outputs["count"]), ("ng", "not_found", 0))
        self.assertEqual(result.outputs["chars"], [])
        with self.assertRaises(ToolError):
            run_tool("char_detect")
        with self.assertRaises(ToolError):
            run_tool("char_detect", empty, {"expected_text": "A"})
        with self.assertRaises(ToolError):
            run_tool("char_detect", empty, {"classifier": "templates"})
        with patch("apps.vision.fixed_images.load", return_value=None), self.assertRaisesRegex(ToolError, "missing"):
            run_tool("char_detect", empty, {"classifier": "templates", "templates": [{"id": "missing", "name": "A.png"}]})
        result = run_tool("char_detect", empty, {"roi": {"shape": "rect", "x": 999, "y": 999, "w": 10, "h": 10}})
        self.assertEqual(result.branch, "not_found")

    def test_merge_before_height_filter_and_keep_neighbours_separate(self):
        image = np.full((97, 333), 255, np.uint8)
        image[25:45, 30:35] = 0
        image[47:65, 30:35] = 0
        image[25:65, 70:75] = 0
        params = {"height_min": 30, "merge_gap": 2}
        self.assertEqual(run_tool("char_detect", image, params).outputs["count"], 2)
        params["merge_gap"] = 0
        self.assertEqual(run_tool("char_detect", image, params).outputs["count"], 1)

    def test_reading_order_matches_list_sort_and_arc_wrap(self):
        image, _ = character_scene("scattered")
        unsorted = self.classify(image, order="none").outputs["chars"]
        sorted_chars = self.classify(image, order="reading").outputs["chars"]
        matches = run_tool("list_sort", params={"by": "xy"}, inputs={"matches": unsorted}).outputs["matches"]
        self.assertEqual([c["label"] for c in sorted_chars], [c["label"] for c in matches])
        # 轉 180 度讓圓弧跨越角度零點，排序仍由最大空白角後開始。
        image, _ = character_scene("arc")
        rotated = cv2.rotate(image, cv2.ROTATE_180)
        self.assertEqual(self.classify(rotated, order="arc").outputs["text"], "FPRATE")

    def test_graph_connects_image_and_character_outputs(self):
        graph = {"nodes": [{"id": "src", "type": "image_source", "params": {}},
                           {"id": "chars", "type": "char_detect", "params": {}},
                           {"id": "pick", "type": "list_pick", "params": {}},
                           {"id": "text", "type": "string_match", "params": {}}],
                 "edges": [{"id": "image", "source": "src", "source_handle": "image", "target": "chars", "target_handle": "image"},
                           {"id": "list", "source": "chars", "source_handle": "chars", "target": "pick", "target_handle": "values"},
                           {"id": "text", "source": "chars", "source_handle": "text", "target": "text", "target_handle": "text"}]}
        self.assertEqual(len(validate_graph(graph)["edges"]), 3)
