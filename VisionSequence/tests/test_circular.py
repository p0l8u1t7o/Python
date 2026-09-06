"""WP-05 圓形卡尺與序列缺陷：完美圓 0 缺陷、20°×5 px 缺口 1 個 inward（角度誤差 < 3°）、大缺口卡尺打空也算缺陷、
毛刺 outward、扇形、線剖面（median／sigma 模式、不 wrap）、標記畫在原圖圓周上。全部合成影像。"""

from __future__ import annotations

import math

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision.tools.base import ToolError
from tests._helpers import run_tool

CX, CY, R = 640, 480, 300
ROI = {"shape": "annulus", "cx": CX, "cy": CY, "r_inner": 250, "r_outer": 350}


def disc(notch_deg: float | None = None, notch_depth: float = 5, notch_span: float = 20, gap_deg: float | None = None, burr_deg: float | None = None, noise: float = 3) -> np.ndarray:
    img = np.full((960, 1280), 40, np.uint8)
    cv2.circle(img, (CX, CY), R, 200, -1)
    if notch_deg is not None:
        a0, a1 = math.radians(notch_deg - notch_span / 2), math.radians(notch_deg + notch_span / 2)
        inner = [(CX + (R - notch_depth) * math.cos(a), CY + (R - notch_depth) * math.sin(a)) for a in np.linspace(a0, a1, 12)]
        outer = [(CX + (R + 20) * math.cos(a), CY + (R + 20) * math.sin(a)) for a in np.linspace(a1, a0, 12)]
        cv2.fillPoly(img, [np.round(np.array(inner + outer)).astype(np.int32)], 40)
    if gap_deg is not None:
        a0, a1 = math.radians(gap_deg - 15), math.radians(gap_deg + 15)
        wedge = [(CX, CY)] + [(CX + (R + 30) * math.cos(a), CY + (R + 30) * math.sin(a)) for a in np.linspace(a0, a1, 16)]
        cv2.fillPoly(img, [np.round(np.array(wedge)).astype(np.int32)], 40)
    if burr_deg is not None:
        a0, a1 = math.radians(burr_deg - 6), math.radians(burr_deg + 6)
        bump = [(CX + (R - 2) * math.cos(a), CY + (R - 2) * math.sin(a)) for a in np.linspace(a0, a1, 8)] + [(CX + (R + 6) * math.cos(a), CY + (R + 6) * math.sin(a)) for a in np.linspace(a1, a0, 8)]
        cv2.fillPoly(img, [np.round(np.array(bump)).astype(np.int32)], 200)
    rng = np.random.default_rng(0)
    return np.clip(img.astype(np.int16) + rng.normal(0, noise, img.shape).astype(np.int16), 0, 255).astype(np.uint8)


def caliper(img: np.ndarray, **params):
    return run_tool("circular_caliper", img, {"roi": ROI, "caliper_count": 72, "polarity": "light_to_dark", "edge_select": "first", **params})


class CircularCaliperTests(SimpleTestCase):
    def test_perfect_disc(self):
        r = caliper(disc())
        self.assertEqual(r.branch, "found")
        self.assertEqual(len(r.outputs["radii"]), 72)
        self.assertEqual(r.outputs["missing_count"], 0)
        self.assertAlmostEqual(r.outputs["mean_r"], R, delta=0.5)
        self.assertLess(r.outputs["runout"], 1.0)
        self.assertEqual(len(r.outputs["points"]), 72)
        self.assertEqual(len(r.outputs["all_points"]), 72)
        self.assertEqual({o["kind"] for o in r.overlays}, {"annulus", "point", "points"})
        self.assertAlmostEqual(r.outputs["angles"][18], 90.0, places=3)

    def test_sector_and_errors(self):
        r = caliper(disc(), roi={**ROI, "a0": 0, "a1": 90}, caliper_count=10)
        self.assertEqual(len(r.outputs["radii"]), 10)
        self.assertAlmostEqual(r.outputs["angles"][-1], 90.0, places=3)
        with self.assertRaises(ToolError):
            run_tool("circular_caliper", disc(), {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 10, "h": 10}})
        with self.assertRaises(ToolError):
            run_tool("circular_caliper", disc(), {})
        blank = run_tool("circular_caliper", np.full((960, 1280), 40, np.uint8), {"roi": ROI})
        self.assertEqual((blank.branch, blank.status), ("not_found", "ng"))
        self.assertEqual(blank.outputs["missing_count"], 72)
        self.assertTrue(math.isnan(blank.outputs["runout"]))

    def test_gap_leaves_missing_calipers_and_outliers_do_not_hide_defects(self):
        r = caliper(disc(gap_deg=200))
        self.assertGreaterEqual(r.outputs["missing_count"], 4)
        self.assertLessEqual(r.outputs["missing_count"], 8)
        self.assertTrue(any(o["kind"] == "line" and o["color"] == "#ef4444" for o in r.overlays))
        n = caliper(disc(notch_deg=60))
        # 缺口的半徑仍在 radii 裡（只從統計剔除），mean 不受影響
        deviations = [R - v for v in n.outputs["radii"] if v is not None]
        self.assertGreater(max(deviations), 4.0)
        self.assertAlmostEqual(n.outputs["mean_r"], R, delta=0.5)
        self.assertGreaterEqual(n.outputs["outlier_count"], 3)


class ProfileDefectTests(SimpleTestCase):
    def _chain(self, img: np.ndarray, **params):
        c = caliper(img)
        p = run_tool("profile_defect", None, {"baseline": "fit_circle", "threshold": 3, "min_width": 2, **params}, {"values": c.outputs["radii"], "points": c.outputs["all_points"]})
        return c, p

    def test_perfect_circle_has_no_defects(self):
        _, p = self._chain(disc())
        self.assertEqual((p.outputs["count"], p.branch, p.status), (0, "ok", "ok"))
        self.assertLess(p.outputs["max_deviation"], 1.0)
        self.assertEqual(p.detail["baseline"], "fit_circle")
        self.assertAlmostEqual(p.detail["r"], R, delta=0.5)

    def test_notch_is_one_inward_defect_at_the_right_angle(self):
        c, p = self._chain(disc(notch_deg=60))
        self.assertEqual(p.outputs["count"], 1)
        d = p.outputs["defects"][0]
        self.assertEqual(d["direction"], "inward")
        self.assertLess(d["peak_deviation"], -3.5)
        self.assertGreater(d["peak_deviation"], -7.0)
        centre = (c.outputs["angles"][d["start"]] + c.outputs["angles"][d["end"]]) / 2
        self.assertLess(abs(centre - 60), 3.0)
        self.assertEqual((p.branch, p.status), ("defect", "ng"))
        self.assertTrue(any(o["kind"] == "polyline" and o["color"] == "#ef4444" for o in p.overlays))
        # inward 只看凹陷；outward 模式看不到缺口
        _, q = self._chain(disc(notch_deg=60), direction="outward")
        self.assertEqual(q.outputs["count"], 0)
        # 允許 1 個缺陷
        _, q = self._chain(disc(notch_deg=60), max_defects=1)
        self.assertEqual((q.outputs["count"], q.branch), (1, "ok"))

    def test_large_gap_counts_as_missing_defect(self):
        c, p = self._chain(disc(gap_deg=200))
        self.assertEqual(p.outputs["count"], 1)
        d = p.outputs["defects"][0]
        self.assertTrue(d["missing"])
        self.assertEqual(d["direction"], "inward")
        centre = (c.outputs["angles"][d["start"]] + c.outputs["angles"][d["end"]]) / 2
        self.assertLess(abs(centre - 200), 6.0)
        _, q = self._chain(disc(gap_deg=200), missing_as_defect=False)
        self.assertEqual(q.outputs["count"], 0)

    def test_burr_is_outward_and_wrap_merges_the_seam(self):
        _, p = self._chain(disc(burr_deg=120), threshold=2.5)
        self.assertEqual(p.outputs["count"], 1)
        self.assertEqual(p.outputs["defects"][0]["direction"], "outward")
        self.assertGreater(p.outputs["defects"][0]["peak_deviation"], 2.5)
        # 缺口跨 0°：wrap 時是一個缺陷，不 wrap 時是兩個
        _, w = self._chain(disc(notch_deg=0))
        self.assertEqual(w.outputs["count"], 1)
        _, nw = self._chain(disc(notch_deg=0), wrap=False)
        self.assertEqual(nw.outputs["count"], 2)

    def test_line_profile_median_and_sigma_modes(self):
        values = [100.0] * 60
        for i in range(30, 34):
            values[i] = 80.0
        values[50] = 60.0  # 單點雜訊
        p = run_tool("profile_defect", None, {"baseline": "median", "window": 9, "threshold": 5, "min_width": 2, "wrap": False}, {"values": values})
        self.assertEqual(p.outputs["count"], 1)
        self.assertEqual((p.outputs["defects"][0]["start"], p.outputs["defects"][0]["end"], p.outputs["defects"][0]["direction"]), (30, 33, "inward"))
        noisy = (100 + np.random.default_rng(1).normal(0, 1.0, 80)).tolist()
        for i in range(30, 34):
            noisy[i] -= 15
        noisy[60] += 12
        s = run_tool("profile_defect", None, {"baseline": "median", "window": 11, "threshold": 4, "threshold_mode": "sigma", "min_width": 1, "wrap": False}, {"values": noisy})
        self.assertEqual(s.outputs["count"], 2)
        self.assertEqual({d["direction"] for d in s.outputs["defects"]}, {"inward", "outward"})
        self.assertIn("sigma", s.detail)
        # 全部相同的序列：MAD 為 0 也不能把一切當缺陷
        flat = run_tool("profile_defect", None, {"baseline": "mean", "threshold": 3, "threshold_mode": "sigma", "min_width": 1, "wrap": False}, {"values": [50.0] * 30})
        self.assertEqual(flat.outputs["count"], 0)
        ln = run_tool("profile_defect", None, {"baseline": "fit_line", "threshold": 2, "min_width": 1, "wrap": False}, {"values": [i * 0.5 for i in range(40)]})
        self.assertEqual(ln.outputs["count"], 0)
        self.assertIn("slope", ln.detail)
        with self.assertRaises(ToolError):
            run_tool("profile_defect", None, {}, {"values": [1, 2]})
        # 值裡有 None（卡尺打空）
        m = run_tool("profile_defect", None, {"baseline": "median", "threshold": 5, "min_width": 2, "wrap": False}, {"values": [100.0] * 20 + [None, None, None] + [100.0] * 20})
        self.assertEqual(m.outputs["count"], 1)
        self.assertTrue(m.outputs["defects"][0]["missing"])
