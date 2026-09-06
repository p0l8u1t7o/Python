"""WP-16 前處理加速：後端切換、沒有 GPU 時行為一致、OpenCL 與 CPU 結果等價、門檻以下走 CPU、失敗退回、經工具的路徑。"""

from __future__ import annotations

import unittest
from unittest import mock

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision.tools import accel
from tests._helpers import run_tool


def _have_opencl() -> bool:
    try:
        return bool(cv2.ocl.haveOpenCL())
    except cv2.error:
        return False


class AccelConfigTests(SimpleTestCase):
    def tearDown(self) -> None:
        accel.configure("cpu")

    def test_modes_and_fallbacks(self):
        s = accel.configure("cpu")
        self.assertEqual((s["mode"], s["backend"]), ("cpu", "cpu"))
        self.assertEqual(s["reason"], "cpu requested")
        s = accel.configure("nonsense")
        self.assertEqual(s["backend"], "cpu")
        s = accel.configure("cuda")  # headless wheel 沒有 cuda 模組：退回（有 OpenCL 就 opencl，否則 cpu）
        self.assertIn(s["backend"], ("cpu", "opencl"))
        self.assertIn("falling back", s["reason"]) if s["backend"] == "cpu" else None
        s = accel.configure("auto", min_pixels=123)
        self.assertEqual(s["min_pixels"], 123)
        self.assertIn(s["backend"], ("cpu", "opencl", "cuda"))
        self.assertEqual(s["calls"], 0)

    def test_cpu_mode_never_touches_gpu(self):
        accel.configure("cpu")
        img = np.random.default_rng(0).integers(0, 255, (2200, 2200), dtype=np.uint8)
        with mock.patch.object(cv2, "UMat", side_effect=AssertionError("UMat must not be used in cpu mode")):
            out = accel.median_blur(img, 5)
            self.assertTrue(np.array_equal(out, cv2.medianBlur(img, 5)))
            k = np.ones((5, 5), np.float32) / 25
            self.assertTrue(np.array_equal(accel.filter2d(img, -1, k), cv2.filter2D(img, -1, k)))
        st = accel.status()
        self.assertEqual((st["calls"], st["accelerated"]), (2, 0))


@unittest.skipUnless(_have_opencl(), "這台機器沒有 OpenCL")
class AccelOpenCLTests(SimpleTestCase):
    def setUp(self) -> None:
        self.rng = np.random.default_rng(1)
        self.big = self.rng.integers(0, 255, (2200, 2200), dtype=np.uint8)  # 4.84 MP ≥ 門檻
        self.small = self.rng.integers(0, 255, (480, 640), dtype=np.uint8)

    def tearDown(self) -> None:
        accel.configure("cpu")

    def test_opencl_results_match_cpu(self):
        s = accel.configure("opencl")
        if s["backend"] != "opencl":
            self.skipTest(s["reason"])
        k = self.rng.random((5, 5)).astype(np.float32)
        k /= k.sum()
        h, w = self.big.shape
        mx, my = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        mx2 = (mx + 2.5 * np.sin(my / 30)).astype(np.float32)
        pairs = [
            (accel.median_blur(self.big, 5), cv2.medianBlur(self.big, 5)),
            (accel.filter2d(self.big, -1, k), cv2.filter2D(self.big, -1, k)),
            (accel.remap(self.big, mx2, my, cv2.INTER_LINEAR), cv2.remap(self.big, mx2, my, cv2.INTER_LINEAR)),
        ]
        for got, want in pairs:
            self.assertEqual(got.shape, want.shape)
            self.assertEqual(got.dtype, want.dtype)
            d = np.abs(got.astype(np.int16) - want.astype(np.int16))
            self.assertLessEqual(int(d[4:-4, 4:-4].max()), 1)  # 內部：捨入差 1 LSB 以內
            # 邊界：取樣點落在影像外時，OpenCL 與 CPU 對常數邊界的捨入不同（實測 4.8 MP 有 56 個像素），只能是極少數
            self.assertLess(int((d > 1).sum()), d.size // 10000)
        f = self.big.astype(np.float32)
        got = accel.dft(f, cv2.DFT_COMPLEX_OUTPUT)
        want = cv2.dft(f, flags=cv2.DFT_COMPLEX_OUTPUT)
        self.assertLess(float(np.abs(got - want).max()) / max(1.0, float(np.abs(want).max())), 1e-4)
        st = accel.status()
        self.assertEqual(st["calls"], 4)
        self.assertEqual(st["accelerated"], 4)

    def test_small_images_stay_on_cpu(self):
        s = accel.configure("opencl")
        if s["backend"] != "opencl":
            self.skipTest(s["reason"])
        with mock.patch.object(cv2, "UMat", side_effect=AssertionError("small images must not go to the GPU")):
            out = accel.median_blur(self.small, 3)
        self.assertTrue(np.array_equal(out, cv2.medianBlur(self.small, 3)))
        self.assertEqual(accel.status()["accelerated"], 0)

    def test_gpu_failure_falls_back_to_cpu(self):
        s = accel.configure("opencl")
        if s["backend"] != "opencl":
            self.skipTest(s["reason"])
        with mock.patch.object(cv2, "UMat", side_effect=cv2.error("simulated driver failure")):
            out = accel.median_blur(self.big, 5)
        self.assertTrue(np.array_equal(out, cv2.medianBlur(self.big, 5)))

    def test_tools_route_through_accel(self):
        s = accel.configure("opencl")
        if s["backend"] != "opencl":
            self.skipTest(s["reason"])
        img = cv2.cvtColor(self.big, cv2.COLOR_GRAY2BGR)
        r = run_tool("blur", img, {"method": "median", "ksize": 5})
        accel.configure("cpu")
        want = run_tool("blur", img, {"method": "median", "ksize": 5})
        self.assertLessEqual(int(np.abs(r.outputs["image"].astype(np.int16) - want.outputs["image"].astype(np.int16)).max()), 1)
