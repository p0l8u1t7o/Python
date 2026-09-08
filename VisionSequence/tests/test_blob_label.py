from __future__ import annotations

import math

import cv2
import numpy as np
from django.test import SimpleTestCase

from tests._helpers import run_tool


class BlobEnhancedTests(SimpleTestCase):
    def test_hysteresis_keeps_low_components_that_touch_high_seed(self):
        img = np.full((80, 140), 10, np.uint8)
        img[20:50, 20:60] = 120
        img[28:42, 30:50] = 230
        img[20:50, 80:100] = 120

        high = run_tool("blob", img, {"threshold_method": "fixed", "threshold": 200, "min_area": 1})
        low = run_tool("blob", img, {"threshold_method": "fixed", "threshold": 100, "min_area": 1})
        hyst = run_tool("blob", img, {"threshold_method": "hysteresis", "threshold": 200, "threshold_low": 100, "min_area": 1})

        self.assertEqual(high.outputs["count"], 1)
        self.assertEqual(high.outputs["blobs"][0]["area"], 20 * 14)
        self.assertEqual(low.outputs["count"], 2)
        self.assertEqual([b["area"] for b in low.outputs["blobs"]], [40 * 30, 20 * 30])
        self.assertEqual(hyst.outputs["count"], 1)
        self.assertEqual(hyst.outputs["blobs"][0]["area"], 40 * 30)
        self.assertEqual(hyst.outputs["blobs"][0]["bbox"], [20, 20, 40, 30])

    def test_soft_threshold_area_is_between_high_and_low_hard_thresholds(self):
        h, w = 100, 100
        yy, xx = np.mgrid[0:h, 0:w]
        r = np.hypot(xx - 50, yy - 50)
        img = np.clip(230 - r * 5, 20, 230).astype(np.uint8)
        width = 60
        threshold = 150

        high = run_tool("blob", img, {"threshold_method": "fixed", "threshold": threshold + width / 2, "min_area": 1})
        low = run_tool("blob", img, {"threshold_method": "fixed", "threshold": threshold - width / 2, "min_area": 1})
        soft = run_tool("blob", img, {"threshold_method": "soft", "threshold": threshold, "soft_width": width, "min_area": 1})

        high_area = high.outputs["blobs"][0]["area"]
        low_area = low.outputs["blobs"][0]["area"]
        soft_area = soft.outputs["blobs"][0]["area"]
        self.assertGreater(soft_area, high_area)
        self.assertLess(soft_area, low_area)

    def test_inscribed_rect_for_rectangle_and_circle(self):
        rect = np.zeros((90, 120), np.uint8)
        rect[20:60, 30:80] = 255
        r = run_tool("blob", rect, {"threshold_method": "none", "min_area": 1})
        self.assertEqual(r.outputs["blobs"][0]["inscribed_rect"], {"x": 30, "y": 20, "w": 50, "h": 40})

        radius = 20
        circle = np.zeros((90, 90), np.uint8)
        cv2.circle(circle, (45, 45), radius, 255, -1)
        c = run_tool("blob", circle, {"threshold_method": "none", "min_area": 1})
        inscribed = c.outputs["blobs"][0]["inscribed_rect"]
        expected = radius * math.sqrt(2)
        self.assertLessEqual(abs(inscribed["w"] - expected), 2.0)
        self.assertLessEqual(abs(inscribed["h"] - expected), 2.0)

    def test_sort_by_xy_uses_reading_order(self):
        img = np.zeros((90, 90), np.uint8)
        centers = [(15, 15), (45, 15), (75, 15), (15, 45), (45, 45), (75, 45), (15, 75), (45, 75), (75, 75)]
        for cx, cy in centers:
            img[cy - 3 : cy + 4, cx - 3 : cx + 4] = 255
        r = run_tool("blob", img, {"threshold_method": "none", "min_area": 1, "sort_by": "xy"})
        got = [(round(b["cx"]), round(b["cy"])) for b in r.outputs["blobs"]]
        self.assertEqual(got, centers)

    def test_blob_label_counts_classes_and_ignores_label(self):
        labels = np.full((80, 100), 99, np.uint16)
        labels[5:15, 5:17] = 1
        labels[20:32, 5:17] = 2
        labels[20:32, 30:42] = 2
        labels[50:62, 60:72] = 3

        r = run_tool("blob_label", None, {"classes": "1:scratch\n2:dent\n3:stain\n99:bg", "ignore_label": 99, "min_area": 1, "sort_by": "xy"},
                     {"labels": labels})

        self.assertEqual(r.outputs["count"], 4)
        counts = {c["label"]: c["count"] for c in r.outputs["counts"]}
        self.assertEqual(counts, {"scratch": 1, "dent": 2, "stain": 1})
        self.assertNotIn(99, {b["class_id"] for b in r.outputs["blobs"]})
        self.assertEqual([b["label"] for b in r.outputs["blobs"]], ["scratch", "dent", "dent", "stain"])

    def test_tools_do_not_modify_input_arrays(self):
        image = np.zeros((60, 80), np.uint8)
        image[10:30, 10:30] = 200
        labels = np.zeros((60, 80), np.uint16)
        labels[10:30, 10:30] = 1
        image_before = image.copy()
        labels_before = labels.copy()

        run_tool("blob", image, {"threshold_method": "hysteresis", "threshold": 180, "threshold_low": 100, "min_area": 1})
        run_tool("blob_label", None, {"classes": "1:part", "min_area": 1}, {"labels": labels})

        np.testing.assert_array_equal(image, image_before)
        np.testing.assert_array_equal(labels, labels_before)
