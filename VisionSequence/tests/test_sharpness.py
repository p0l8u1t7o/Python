from __future__ import annotations

import cv2
import numpy as np
from django.test import SimpleTestCase

from tests._helpers import run_tool


METHODS = ("laplacian", "gradient", "autocorrelation")


def textured_image(h: int = 240, w: int = 320) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w]
    img = 126 + 58 * np.sin(x / 6.0) + 42 * np.sin(y / 9.0)
    cv2.rectangle(img, (30, 40), (145, 150), 230, -1)
    cv2.circle(img, (245, 125), 44, 30, -1)
    cv2.putText(img, "VS", (48, 215), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 220, 5)
    return np.clip(img, 0, 255).astype(np.uint8)


def blur(image: np.ndarray, sigma: float) -> np.ndarray:
    return image.copy() if sigma == 0 else cv2.GaussianBlur(image, (0, 0), sigma)


class SharpnessTests(SimpleTestCase):
    def test_scores_decrease_monotonically_with_blur(self):
        base = textured_image()
        sigmas = (0.0, 0.8, 1.6, 3.0, 5.0)
        for method in METHODS:
            scores = [run_tool("sharpness", blur(base, sigma), {"method": method}).outputs["score"] for sigma in sigmas]
            self.assertTrue(
                all(a > b for a, b in zip(scores, scores[1:])),
                f"{method} scores were not strictly decreasing: {scores}",
            )

    def test_roi_scores_only_the_selected_area(self):
        base = textured_image()
        scene = base.copy()
        scene[:, scene.shape[1] // 2:] = blur(base, 4.0)[:, scene.shape[1] // 2:]
        clear_roi = {"shape": "rect", "x": 0, "y": 0, "w": 150, "h": scene.shape[0]}
        blurred_roi = {"shape": "rect", "x": 170, "y": 0, "w": 150, "h": scene.shape[0]}
        for method in METHODS:
            clear = run_tool("sharpness", scene, {"method": method, "roi": clear_roi}).outputs["score"]
            blurred = run_tool("sharpness", scene, {"method": method, "roi": blurred_roi}).outputs["score"]
            self.assertGreater(clear, blurred * 2.0, f"{method}: clear={clear}, blurred={blurred}")

    def test_min_and_max_score_drive_ok_ng_branches(self):
        score = run_tool("sharpness", textured_image(), {"method": "laplacian"}).outputs["score"]
        ok = run_tool("sharpness", textured_image(), {"method": "laplacian", "min_score": score * 0.8, "max_score": score * 1.2})
        low_ng = run_tool("sharpness", textured_image(), {"method": "laplacian", "min_score": score * 1.2})
        high_ng = run_tool("sharpness", textured_image(), {"method": "laplacian", "max_score": score * 0.8})
        self.assertEqual((ok.status, ok.branch), ("ok", "ok"))
        self.assertEqual((low_ng.status, low_ng.branch), ("ng", "ng"))
        self.assertEqual((high_ng.status, high_ng.branch), ("ng", "ng"))

    def test_noise_estimate_rises_with_added_gaussian_noise(self):
        h, w = 240, 320
        y, x = np.mgrid[0:h, 0:w]
        clean = np.clip(120 + 25 * np.sin(x / 35.0) + 20 * np.sin(y / 27.0), 0, 255).astype(np.uint8)
        rng = np.random.default_rng(42)
        noisy = np.clip(clean.astype(np.float32) + rng.normal(0, 14, clean.shape), 0, 255).astype(np.uint8)
        clean_noise = run_tool("sharpness", clean, {"noise_estimate": True}).outputs["noise"]
        noisy_noise = run_tool("sharpness", noisy, {"noise_estimate": True}).outputs["noise"]
        self.assertIsNotNone(clean_noise)
        self.assertIsNotNone(noisy_noise)
        self.assertGreater(noisy_noise, clean_noise + 5.0)
        self.assertGreater(noisy_noise, clean_noise * 2.0)

    def test_does_not_modify_input_array(self):
        image = textured_image()
        original = image.copy()
        result = run_tool("sharpness", image, {"method": "gradient", "noise_estimate": True})
        self.assertEqual(result.status, "ok", result.message)
        np.testing.assert_array_equal(image, original)
