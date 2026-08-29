"""內建工具（locate / measure / detect / dl）單元測試：全部用合成影像。"""

from __future__ import annotations

import math

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision.tools import base
from apps.vision.tools.base import ToolError
from apps.vision.tools.builtin import dl as dl_mod
from tests._helpers import (
    blank,
    circle_image,
    gap_classifier_onnx,
    identity_onnx,
    rect_image,
    run_tool,
    save_png,
    temp_dir,
)


class RegistryTests(SimpleTestCase):
    def test_all_new_tools_registered(self):
        expected = {
            "template_match", "shape_align", "fixture_roi", "find_circle", "find_line", "hough_circles", "hough_lines",
            "caliper", "distance", "angle", "intensity", "calibration", "histogram",
            "fit_arc", "fit_ellipse", "wall_thickness", "concentricity", "chamfer_angle", "tolerance_judge",
            "blob", "defect_diff", "barcode", "text_presence", "color_check", "edge_density", "pixel_count",
            "dl_classify", "dl_detect", "dl_segment",
        }
        keys = {t.key for t in base.all_types()}
        self.assertTrue(expected <= keys, expected - keys)
        cats = {t.key: t.category for t in base.all_types()}
        self.assertEqual(cats["template_match"], "locate")
        self.assertEqual(cats["caliper"], "measure")
        self.assertEqual(cats["blob"], "detect")
        self.assertEqual(cats["dl_classify"], "dl")
        base.catalogue()  # 不會炸

    def test_teach_params_marked(self):
        teach = {t.key: {p.key for p in t.params if p.teach} for t in base.all_types()}
        self.assertEqual(teach["threshold"], {"threshold", "low", "high", "block", "c"})
        self.assertEqual(teach["template_match"], {"threshold", "angle_range"})
        self.assertEqual(teach["blob"], {"min_area", "max_area", "min_circularity"})
        self.assertEqual(teach["caliper"], {"edge_threshold", "polarity"})
        self.assertEqual(teach["find_circle"], {"edge_threshold"})
        self.assertEqual(teach["find_line"], {"edge_threshold"})
        self.assertEqual(teach["defect_diff"], {"threshold", "min_area"})
        self.assertEqual(teach["color_range"], {"h_low", "h_high", "s_low", "s_high", "v_low", "v_high"})
        self.assertEqual(teach["color_check"], {"tolerance"})
        self.assertEqual(teach["in_range"], {"low", "high"})
        self.assertEqual(teach["if_number"], {"threshold"})
        self.assertEqual(teach["dl_classify"], {"threshold"})
        self.assertEqual(teach["dl_detect"], {"conf"})
        self.assertEqual(teach["pixel_count"], {"min_count", "max_count"})
        self.assertEqual(teach["edge_density"], {"max_ratio"})
        self.assertEqual(teach["text_presence"], {"min_ratio", "max_ratio"})
        self.assertEqual(teach["tolerance_judge"], {"nominal", "upper_tol", "lower_tol"})
        self.assertEqual(teach["concentricity"], {"max_deviation"})
        cat = {t["key"]: t for t in base.catalogue()}
        self.assertTrue(any(p["teach"] for p in cat["threshold"]["params"]))


# ---------------------------------------------------------------------------
# locate
# ---------------------------------------------------------------------------
class LocateTests(SimpleTestCase):
    def _scene(self):
        img = blank(value=40)
        # 一個不對稱的圖案，避免旋轉對稱造成歧義
        cv2.rectangle(img, (150, 100), (210, 140), 220, -1)
        cv2.circle(img, (165, 112), 8, 90, -1)
        cv2.line(img, (150, 100), (210, 140), 10, 2)
        return img

    def test_template_match_finds_template(self):
        img = self._scene()
        folder = temp_dir()
        tpl_path = save_png(img[95:145, 145:215], folder, "tpl.png")
        for pyramid in (False, True):
            r = run_tool("template_match", img, {"template": "t", "threshold": 0.8, "max_matches": 3, "pyramid": pyramid}, assets={"t": tpl_path})
            self.assertEqual(r.status, "ok", r.message)
            self.assertEqual(r.branch, "found")
            self.assertEqual(r.outputs["count"], 1)
            self.assertAlmostEqual(r.outputs["best_x"], 180, delta=1.5)
            self.assertAlmostEqual(r.outputs["best_y"], 120, delta=1.5)
            self.assertGreater(r.outputs["best_score"], 0.95)

    def test_template_match_with_roi_and_rotation(self):
        img = self._scene()
        folder = temp_dir()
        tpl_path = save_png(img[95:145, 145:215], folder, "tpl.png")
        rotated = cv2.warpAffine(img, cv2.getRotationMatrix2D((180, 120), 10, 1.0), (320, 240), borderValue=40)
        r = run_tool("template_match", rotated, {"template": "t", "threshold": 0.7, "angle_range": 15, "angle_step": 5, "pyramid": False,
                                                 "roi": {"shape": "rect", "x": 100, "y": 60, "w": 160, "h": 120}}, assets={"t": tpl_path})
        self.assertEqual(r.branch, "found", r.message)
        self.assertAlmostEqual(r.outputs["best_x"], 180, delta=3)
        self.assertAlmostEqual(r.outputs["best_y"], 120, delta=3)
        self.assertAlmostEqual(abs(r.outputs["best_angle"]), 10, delta=2.5)

    def test_template_match_not_found_is_ng(self):
        img = self._scene()
        folder = temp_dir()
        tpl = np.zeros((40, 40), np.uint8)
        cv2.circle(tpl, (20, 20), 15, 255, 2)
        r = run_tool("template_match", img, {"template": "t", "threshold": 0.9}, assets={"t": save_png(tpl, folder, "x.png")})
        self.assertEqual(r.status, "ng")
        self.assertEqual(r.outputs["count"], 0)

    def test_template_match_missing_asset(self):
        with self.assertRaises(ToolError):
            run_tool("template_match", blank(), {"template": "nope"})

    def test_shape_align_and_fixture(self):
        matches = [{"cx": 110.0, "cy": 60.0, "angle": 5.0, "score": 0.9}]
        r = run_tool("shape_align", blank(), {"ref_x": 100, "ref_y": 50, "ref_angle": 0}, inputs={"matches": matches})
        self.assertAlmostEqual(r.outputs["dx"], 10)
        self.assertAlmostEqual(r.outputs["dy"], 10)
        self.assertAlmostEqual(r.outputs["dtheta"], 5)
        t = r.outputs["transform"]
        f = run_tool("fixture_roi", blank(), {"roi": {"shape": "rect", "x": 100, "y": 50, "w": 20, "h": 10}}, inputs={"transform": t})
        region = f.outputs["region"]
        self.assertEqual(region["shape"], "rotated_rect")
        # 先繞參考點旋轉 dθ，再平移 dx/dy
        m = cv2.getRotationMatrix2D((100.0, 50.0), -5.0, 1.0)
        ex, ey = m @ np.array([110.0, 55.0, 1.0])
        self.assertAlmostEqual(region["cx"], ex + 10, delta=1e-6)
        self.assertAlmostEqual(region["cy"], ey + 10, delta=1e-6)
        self.assertAlmostEqual(region["angle"], 5)
        # 純平移（circle）
        f2 = run_tool("fixture_roi", None, {"roi": {"shape": "circle", "cx": 10, "cy": 10, "r": 3}}, inputs={"transform": {"dx": 1, "dy": 2, "dtheta": 0}})
        self.assertEqual((f2.outputs["region"]["cx"], f2.outputs["region"]["cy"]), (11, 12))
        # 用 a/b 數值
        r2 = run_tool("shape_align", None, {"ref_x": 0, "ref_y": 0}, inputs={"a": 3, "b": 4})
        self.assertEqual((r2.outputs["dx"], r2.outputs["dy"]), (3, 4))
        with self.assertRaises(ToolError):
            run_tool("shape_align", None, {"ref_x": 0, "ref_y": 0})

    def test_find_circle(self):
        img = cv2.GaussianBlur(circle_image(160, 120, 50), (3, 3), 0)
        for roi in ({"shape": "circle", "cx": 158, "cy": 122, "r": 80}, {"shape": "annulus", "cx": 158, "cy": 122, "r_inner": 30, "r_outer": 80}, {"shape": "rect", "x": 80, "y": 40, "w": 160, "h": 160}):
            for ransac in (True, False):
                r = run_tool("find_circle", img, {"roi": roi, "polarity": "light_to_dark", "edge_threshold": 15, "ransac": ransac})
                self.assertEqual(r.branch, "found", r.message)
                self.assertAlmostEqual(r.outputs["cx"], 160, delta=1.0)
                self.assertAlmostEqual(r.outputs["cy"], 120, delta=1.0)
                self.assertAlmostEqual(r.outputs["r"], 50, delta=1.5)
        # 極性相反 → 找不到 → ng
        r = run_tool("find_circle", img, {"roi": {"shape": "circle", "cx": 160, "cy": 120, "r": 80}, "polarity": "dark_to_light", "edge_threshold": 15})
        self.assertEqual(r.status, "ng")

    def test_find_line(self):
        img = blank(value=40)
        # 斜邊：y = 0.2 x + 60 以下為亮
        pts = np.array([[0, 60], [320, 124], [320, 240], [0, 240]], np.int32)
        cv2.fillPoly(img, [pts], 220)
        img = cv2.GaussianBlur(img, (3, 3), 0)
        r = run_tool("find_line", img, {"roi": {"shape": "rect", "x": 40, "y": 40, "w": 240, "h": 100}, "polarity": "dark_to_light", "edge_threshold": 15, "num_calipers": 12})
        self.assertEqual(r.branch, "found", r.message)
        self.assertAlmostEqual(r.outputs["angle"], math.degrees(math.atan(0.2)), delta=0.7)
        # 端點落在直線上
        for x, y in ((r.outputs["x1"], r.outputs["y1"]), (r.outputs["x2"], r.outputs["y2"])):
            self.assertAlmostEqual(y, 0.2 * x + 60, delta=1.5)
        self.assertGreaterEqual(len(r.outputs["points"]), 10)
        # rotated_rect ROI（垂直長邊）
        img2 = blank(value=40)
        img2[:, 150:] = 220
        r2 = run_tool("find_line", img2, {"roi": {"shape": "rotated_rect", "cx": 150, "cy": 120, "w": 60, "h": 180, "angle": 0}, "num_calipers": 10, "edge_threshold": 15})
        self.assertEqual(r2.branch, "found", r2.message)
        self.assertAlmostEqual(abs(r2.outputs["angle"]), 90, delta=0.7)
        self.assertAlmostEqual(r2.outputs["x1"], 149.5, delta=1.0)

    def test_hough_circles_and_lines(self):
        img = circle_image(160, 120, 40)
        r = run_tool("hough_circles", img, {"min_radius": 30, "max_radius": 50, "param2": 10})
        self.assertEqual(r.branch, "found", r.message)
        self.assertAlmostEqual(r.outputs["circles"][0]["cx"], 160, delta=3)
        self.assertAlmostEqual(r.outputs["circles"][0]["r"], 40, delta=3)
        img2 = blank(value=0)
        cv2.line(img2, (20, 100), (300, 100), 255, 3)
        r2 = run_tool("hough_lines", img2, {"threshold": 50, "min_length": 100, "roi": {"shape": "rect", "x": 10, "y": 50, "w": 300, "h": 100}})
        self.assertEqual(r2.branch, "found")
        self.assertAlmostEqual(abs(r2.outputs["lines"][0]["angle"]) % 180, 0, delta=1)
        self.assertAlmostEqual(r2.outputs["lines"][0]["y1"], 100, delta=3)
        r3 = run_tool("hough_lines", blank(value=0), {})
        self.assertEqual(r3.status, "ng")


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------
class MeasureTests(SimpleTestCase):
    def test_caliper_width(self):
        img = rect_image(100, 80, 120, 60)
        r = run_tool("caliper", img, {"roi": {"shape": "rect", "x": 60, "y": 90, "w": 200, "h": 40}, "edge_threshold": 20})
        self.assertEqual(r.status, "ok", r.message)
        self.assertAlmostEqual(r.outputs["width"], 120, delta=1.0)
        self.assertAlmostEqual(r.outputs["edge1_x"], 99.5, delta=1.0)
        self.assertAlmostEqual(r.outputs["edge2_x"], 219.5, delta=1.0)
        self.assertAlmostEqual(r.outputs["edge1_y"], 110, delta=0.6)
        self.assertEqual(len(r.outputs["profile"]), 200)
        # 垂直卡尺（短邊為 x）量高度
        r2 = run_tool("caliper", img, {"roi": {"shape": "rect", "x": 140, "y": 40, "w": 30, "h": 160}, "edge_pair": "widest"})
        self.assertAlmostEqual(r2.outputs["width"], 60, delta=1.0)
        # 旋轉矩形 ROI：旋轉 90° 等同垂直
        r3 = run_tool("caliper", img, {"roi": {"shape": "rotated_rect", "cx": 155, "cy": 110, "w": 160, "h": 30, "angle": 90}})
        self.assertAlmostEqual(r3.outputs["width"], 60, delta=1.5)
        r4 = run_tool("caliper", blank(), {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 100, "h": 20}})
        self.assertEqual(r4.status, "ng")

    def test_distance_and_angle(self):
        r = run_tool("distance", None, {}, inputs={"a": {"x": 0, "y": 0}, "b": [3, 4]})
        self.assertAlmostEqual(r.outputs["distance"], 5)
        r = run_tool("distance", None, {"mode": "dx"}, inputs={"ax": 1, "ay": 1, "bx": 4, "by": 9})
        self.assertAlmostEqual(r.outputs["distance"], 3)
        with self.assertRaises(ToolError):
            run_tool("distance", None, {}, inputs={"a": [1, 2]})
        r = run_tool("angle", None, {}, inputs={"a": {"x1": 0, "y1": 0, "x2": 10, "y2": 0}, "b": [0, 0, 10, 10]})
        self.assertAlmostEqual(r.outputs["angle_deg"], 45)
        r = run_tool("angle", None, {"range": "signed"}, inputs={"ax1": 0, "ay1": 0, "ax2": 10, "ay2": 0, "bx1": 0, "by1": 0, "bx2": 0, "by2": -10})
        self.assertAlmostEqual(r.outputs["angle_deg"], -90)

    def test_intensity_histogram(self):
        img = circle_image(160, 120, 50, bg=30, fg=220)
        r = run_tool("intensity", img, {"roi": {"shape": "circle", "cx": 160, "cy": 120, "r": 30}})
        self.assertEqual(r.outputs["mean"], 220)
        self.assertEqual(r.outputs["std"], 0)
        r = run_tool("intensity", img, {})
        self.assertGreater(r.outputs["mean"], 30)
        self.assertEqual(r.outputs["min"], 30)
        self.assertEqual(r.outputs["max"], 220)
        h = run_tool("histogram", img, {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 50, "h": 50}})
        self.assertEqual(len(h.outputs["histogram"]), 256)
        self.assertEqual(h.outputs["peak"], 30)
        self.assertEqual(h.outputs["histogram"][30], 2500)
        h2 = run_tool("histogram", img, {"normalize": True})
        self.assertAlmostEqual(sum(h2.outputs["histogram"]), 1.0)
        self.assertTrue(30 <= h2.outputs["otsu"] < 220)  # 兩階影像：類間變異在 [30, 219] 皆相同，取最小者

    def test_calibration(self):
        r = run_tool("calibration", None, {"mode": "pixel_size", "pixel_size_mm": 0.05}, inputs={"value": 200})
        self.assertAlmostEqual(r.outputs["mm"], 10)
        r = run_tool("calibration", None, {"mode": "known_distance", "px_distance": 100, "real_mm": 25, "power": "2"}, inputs={"value": 400, "points": [[100, 200]]})
        self.assertAlmostEqual(r.outputs["mm"], 25)
        self.assertEqual(r.outputs["points_mm"], [[25, 50]])
        with self.assertRaises(ToolError):
            run_tool("calibration", None, {"mode": "known_distance", "px_distance": 0, "real_mm": 1}, inputs={"value": 1})

    def test_fit_arc(self):
        img = circle_image(160, 120, 50)
        # 只看右上 1/4 圓（polygon ROI）：圓心／半徑仍對，起終角落在 270°~360°
        poly = {"shape": "polygon", "points": [[160, 120], [230, 120], [230, 50], [160, 50]]}
        r = run_tool("fit_arc", img, {"roi": poly, "num_rays": 90})
        self.assertEqual(r.status, "ok", r.message)
        self.assertAlmostEqual(r.outputs["radius"], 50, delta=1.0)
        self.assertAlmostEqual(r.outputs["cx"], 160, delta=1.0)
        self.assertAlmostEqual(r.outputs["cy"], 120, delta=1.0)
        self.assertLess(r.outputs["residual_rms"], 0.6)
        self.assertGreater(r.outputs["start_angle"], 265)
        self.assertLess(r.outputs["end_angle"], 362)
        self.assertTrue(any(o["kind"] == "polyline" for o in r.overlays))
        # 圓環 ROI：整圈
        r2 = run_tool("fit_arc", img, {"roi": {"shape": "annulus", "cx": 160, "cy": 120, "r_inner": 30, "r_outer": 70}})
        self.assertAlmostEqual(r2.outputs["radius"], 50, delta=1.0)
        self.assertEqual((r2.outputs["start_angle"], r2.outputs["end_angle"]), (0.0, 360.0))
        # 旋轉矩形 ROI：卡尺取點
        r3 = run_tool("fit_arc", img, {"roi": {"shape": "rotated_rect", "cx": 160, "cy": 70, "w": 80, "h": 30, "angle": 0}, "num_rays": 20})
        self.assertEqual(r3.status, "ok", r3.message)
        self.assertAlmostEqual(r3.outputs["radius"], 50, delta=4.0)
        self.assertEqual(run_tool("fit_arc", blank(), {"roi": poly}).status, "ng")

    def test_fit_ellipse(self):
        img = blank()
        cv2.ellipse(img, (160, 120), (60, 40), 30, 0, 360, 220, -1)
        r = run_tool("fit_ellipse", img, {"roi": {"shape": "annulus", "cx": 160, "cy": 120, "r_inner": 20, "r_outer": 80}, "num_rays": 72})
        self.assertEqual(r.status, "ok", r.message)
        self.assertAlmostEqual(r.outputs["a"], 60, delta=1.5)
        self.assertAlmostEqual(r.outputs["b"], 40, delta=1.5)
        self.assertAlmostEqual(r.outputs["angle"], 30, delta=2.0)
        self.assertAlmostEqual(r.outputs["roundness"], 40 / 60, delta=0.03)
        self.assertLess(r.outputs["residual_rms"], 1.0)
        self.assertEqual(run_tool("fit_ellipse", blank(), {"roi": {"shape": "circle", "cx": 160, "cy": 120, "r": 60}}).status, "ng")

    def test_wall_thickness(self):
        img = blank()
        cv2.rectangle(img, (150, 40), (159, 200), 220, -1)  # 10px 寬的亮壁
        r = run_tool("wall_thickness", img, {"roi": {"shape": "rect", "x": 120, "y": 60, "w": 70, "h": 120}, "num_calipers": 8})
        self.assertEqual(r.status, "ok", r.message)
        self.assertEqual(r.outputs["count"], 8)
        self.assertAlmostEqual(r.outputs["thickness"], 10, delta=0.5)
        self.assertAlmostEqual(r.outputs["min"], 10, delta=0.5)
        self.assertAlmostEqual(r.outputs["max"], 10, delta=0.5)
        self.assertEqual(len(r.outputs["pairs"]), 8)
        self.assertAlmostEqual(r.outputs["pairs"][0][0][0], 149.5, delta=1.0)
        self.assertAlmostEqual(r.outputs["pairs"][0][1][0], 159.5, delta=1.0)
        # 線段 ROI：剖面沿線
        r2 = run_tool("wall_thickness", img, {"roi": {"shape": "line", "x1": 120, "y1": 100, "x2": 190, "y2": 100}})
        self.assertAlmostEqual(r2.outputs["thickness"], 10, delta=0.5)
        # 指定外緣極性（旋轉 90° 的矩形：由左向右掃）
        r3 = run_tool("wall_thickness", img, {"roi": {"shape": "rotated_rect", "cx": 155, "cy": 120, "w": 120, "h": 70, "angle": 90}, "polarity": "dark_to_light"})
        self.assertAlmostEqual(r3.outputs["thickness"], 10, delta=0.5)
        self.assertEqual(run_tool("wall_thickness", blank(), {"roi": {"shape": "rect", "x": 120, "y": 60, "w": 70, "h": 120}}).status, "ng")

    def test_concentricity(self):
        r = run_tool("concentricity", None, {"max_deviation": 5}, inputs={"a": {"cx": 100, "cy": 100, "r": 50}, "bx": 103, "by": 104, "br": 20})
        self.assertEqual((r.status, r.branch), ("ok", "ok"))
        self.assertAlmostEqual(r.outputs["deviation"], 5)
        self.assertAlmostEqual(r.outputs["concentricity"], 10)
        self.assertEqual((r.outputs["dx"], r.outputs["dy"]), (3, 4))
        r = run_tool("concentricity", None, {"max_deviation": 2}, inputs={"ax": 0, "ay": 0, "bx": 3, "by": 4})
        self.assertEqual((r.status, r.branch, r.outputs["in_spec"]), ("ng", "ng", False))
        r = run_tool("concentricity", None, {}, inputs={"ax": float("nan"), "ay": 0, "bx": 3, "by": 4})
        self.assertEqual(r.status, "ng")
        with self.assertRaises(ToolError):
            run_tool("concentricity", None, {}, inputs={"ax": 1})

    def test_chamfer_angle(self):
        img = blank()
        # 上邊 y=80（x 100~200）接 45° 倒角到 (240,120)
        cv2.fillPoly(img, [np.array([[100, 80], [200, 80], [240, 120], [240, 200], [100, 200]], np.int32)], 220)
        r = run_tool("chamfer_angle", img, {"roi": {"shape": "rect", "x": 110, "y": 60, "w": 125, "h": 70}, "num_calipers": 50, "direction": "first"})
        self.assertEqual(r.status, "ok", r.message)
        self.assertAlmostEqual(r.outputs["angle_deg"], 45, delta=1.5)
        self.assertTrue(30 < r.outputs["length"] < 60, r.outputs["length"])  # ROI 只到 x=235：倒角段約 35px 長（斜邊 ~49px），端點受 RANSAC 容差影響
        self.assertAlmostEqual(r.outputs["ix"], 200, delta=2)
        self.assertAlmostEqual(r.outputs["iy"], 80, delta=2)
        self.assertAlmostEqual(abs(r.outputs["line1"]["angle"]), 0, delta=1.0)
        self.assertEqual(run_tool("chamfer_angle", blank(), {"roi": {"shape": "rect", "x": 110, "y": 60, "w": 125, "h": 70}}).status, "ng")
        # 只有一條直線：找不到第二段 → ng
        r2 = run_tool("chamfer_angle", rect_image(100, 80, 120, 60), {"roi": {"shape": "rect", "x": 105, "y": 60, "w": 100, "h": 40}})
        self.assertEqual(r2.status, "ng")

    def test_tolerance_judge(self):
        ctx = {"_outputs": {"x": 1}}
        params = {"nominal": 12, "upper_tol": 0.05, "lower_tol": -0.05, "unit": "mm", "spec_source": "圖號 A-1 ⌀12"}
        r = run_tool("tolerance_judge", None, params, inputs={"value": 12.02}, context=ctx)
        self.assertEqual((r.status, r.branch), ("ok", "pass"))
        self.assertAlmostEqual(r.outputs["deviation"], 0.02)
        self.assertEqual((r.outputs["lower"], r.outputs["upper"], r.outputs["spec_source"]), (11.95, 12.05, "圖號 A-1 ⌀12"))
        tol = r.context["_outputs"]["tolerances"]
        self.assertEqual(r.context["_outputs"]["x"], 1)
        self.assertEqual(len(tol), 1)
        self.assertEqual(tol[0]["name"], "tolerance_judge")
        self.assertTrue(tol[0]["in_spec"])
        self.assertEqual(tol[0]["spec_source"], "圖號 A-1 ⌀12")
        r2 = run_tool("tolerance_judge", None, {**params, "name": "od"}, inputs={"value": 12.2}, context=dict(r.context))
        self.assertEqual((r2.status, r2.branch, r2.outputs["in_spec"]), ("ng", "fail", False))
        names = [t["name"] for t in r2.context["_outputs"]["tolerances"]]
        self.assertEqual(names, ["tolerance_judge", "od"])
        r3 = run_tool("tolerance_judge", None, {"nominal": 12}, inputs={"value": float("nan")})
        self.assertEqual((r3.status, r3.branch), ("ng", "fail"))
        self.assertIsNone(r3.context["_outputs"]["tolerances"][0]["value"])
        with self.assertRaises(ToolError):
            run_tool("tolerance_judge", None, {"nominal": 12}, inputs={"value": "abc"})


# ---------------------------------------------------------------------------
# detect
# ---------------------------------------------------------------------------
class DetectTests(SimpleTestCase):
    def _blobs_image(self):
        img = blank(value=20)
        cv2.circle(img, (60, 60), 20, 240, -1)        # 圓 A ≈ 1257
        cv2.rectangle(img, (200, 50), (259, 109), 240, -1)  # 方 60x60 = 3600
        cv2.circle(img, (150, 180), 12, 240, -1)      # 小圓 ≈ 408
        return img

    def test_blob_basic(self):
        img = self._blobs_image()
        r = run_tool("blob", img, {"min_area": 50})
        self.assertEqual(r.outputs["count"], 3)
        self.assertEqual(r.branch, "found")
        first = r.outputs["blobs"][0]
        self.assertAlmostEqual(first["area"], 3600, delta=120)
        self.assertAlmostEqual(first["cx"], 229.5, delta=1)
        self.assertAlmostEqual(first["cy"], 79.5, delta=1)
        self.assertEqual(r.outputs["mask"].shape, img.shape)
        self.assertEqual(len(r.outputs["contours"]), 3)
        self.assertEqual(len(r.outputs["centers"]), 3)
        # 圓形度篩選：圓 > 方
        circles = run_tool("blob", img, {"min_area": 50, "min_circularity": 0.8})
        self.assertEqual(circles.outputs["count"], 2)
        for b in circles.outputs["blobs"]:
            self.assertGreater(b["circularity"], 0.8)
        # 排序 x
        byx = run_tool("blob", img, {"min_area": 50, "sort_by": "x"})
        xs = [b["cx"] for b in byx.outputs["blobs"]]
        self.assertEqual(xs, sorted(xs))
        # ROI + 面積上限
        roi = run_tool("blob", img, {"min_area": 50, "roi": {"shape": "rect", "x": 0, "y": 0, "w": 120, "h": 120}})
        self.assertEqual(roi.outputs["count"], 1)
        self.assertAlmostEqual(roi.outputs["blobs"][0]["cx"], 60, delta=1)
        # 暗物件 / 空
        dark = run_tool("blob", 255 - img, {"min_area": 50, "polarity": "dark"})
        self.assertEqual(dark.outputs["count"], 3)
        empty = run_tool("blob", blank(value=0), {"threshold_method": "fixed", "threshold": 128})
        self.assertEqual(empty.status, "ng")
        self.assertEqual(empty.outputs["count"], 0)

    def test_blob_holes(self):
        img = blank(value=0)
        cv2.rectangle(img, (50, 50), (149, 149), 255, -1)
        cv2.rectangle(img, (80, 80), (119, 119), 0, -1)
        r = run_tool("blob", img, {"threshold_method": "none", "external_only": False})
        self.assertAlmostEqual(r.outputs["blobs"][0]["area"], 10000 - 1600, delta=300)
        f = run_tool("blob", img, {"threshold_method": "none", "fill_holes": True})
        self.assertAlmostEqual(f.outputs["blobs"][0]["area"], 10000, delta=300)
        self.assertEqual(int(f.outputs["mask"][100, 100]), 255)

    def test_defect_diff(self):
        good = blank(value=120)
        cv2.rectangle(good, (60, 60), (260, 180), 200, -1)
        cv2.circle(good, (100, 100), 15, 60, -1)
        folder = temp_dir()
        tpl = save_png(good, folder, "good.png")
        bad = np.roll(good, (2, 3), axis=(0, 1))  # 微小位移
        cv2.circle(bad, (200, 130), 10, 20, -1)   # 缺陷
        for align in ("none", "phase", "ecc"):
            r = run_tool("defect_diff", bad, {"template": "g", "align": align, "threshold": 60, "min_area": 30}, assets={"g": tpl})
            self.assertEqual(r.status, "ng", (align, r.message))
            self.assertGreaterEqual(r.outputs["count"], 1)
            d = max(r.outputs["defects"], key=lambda x: x["area"])
            self.assertAlmostEqual(d["cx"], 200, delta=4)
            self.assertAlmostEqual(d["cy"], 130, delta=4)
        ok = run_tool("defect_diff", bad, {"template": "g", "align": "phase", "threshold": 60, "min_area": 30, "roi": {"shape": "rect", "x": 40, "y": 40, "w": 100, "h": 100}}, assets={"g": tpl})
        self.assertEqual(ok.status, "ok", ok.message)
        self.assertEqual(ok.outputs["defect_mask"].shape, bad.shape)

    def test_barcode_qr(self):
        enc = getattr(cv2, "QRCodeEncoder", None)
        if enc is None:
            self.skipTest("OpenCV 沒有 QRCodeEncoder")
        qr = enc.create().encode("VS-123")
        qr = cv2.resize(qr, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
        img = np.full((qr.shape[0] + 80, qr.shape[1] + 80), 255, np.uint8)
        img[40 : 40 + qr.shape[0], 40 : 40 + qr.shape[1]] = qr
        r = run_tool("barcode", img, {"types": "qr"})
        self.assertEqual(r.branch, "found", r.message)
        self.assertEqual(r.outputs["first"], "VS-123")
        bad = run_tool("barcode", img, {"types": "qr", "expected": "OTHER"})
        self.assertEqual(bad.status, "ng")
        none = run_tool("barcode", blank(), {})
        self.assertEqual(none.outputs["count"], 0)
        self.assertEqual(none.status, "ng")

    def test_text_presence(self):
        img = blank(value=230)
        cv2.putText(img, "ABC123", (40, 140), cv2.FONT_HERSHEY_SIMPLEX, 2, 20, 4)
        roi = {"shape": "rect", "x": 20, "y": 60, "w": 280, "h": 120}
        r = run_tool("text_presence", img, {"roi": roi, "min_ratio": 0.03})
        self.assertEqual(r.branch, "present", r.message)
        r2 = run_tool("text_presence", blank(value=230), {"roi": roi, "min_ratio": 0.03})
        self.assertEqual(r2.branch, "absent")
        self.assertEqual(r2.status, "ng")

    def test_color_check(self):
        img = np.zeros((100, 100, 3), np.uint8)
        img[:] = (0, 0, 200)  # BGR 紅
        r = run_tool("color_check", img, {"color": "#c80000", "tolerance": 30})
        self.assertTrue(r.outputs["is_match"])
        self.assertEqual(r.outputs["mean_hex"], "#c80000")
        self.assertEqual(r.branch, "match")
        r2 = run_tool("color_check", img, {"color": "#0000ff", "tolerance": 30})
        self.assertEqual(r2.branch, "mismatch")
        r3 = run_tool("color_check", img, {"color": "#ff0000", "space": "hsv", "tolerance": 20, "roi": {"shape": "circle", "cx": 50, "cy": 50, "r": 20}})
        self.assertTrue(r3.outputs["is_match"])
        with self.assertRaises(ToolError):
            run_tool("color_check", img, {"color": "red"})

    def test_edge_density_and_pixel_count(self):
        smooth = blank(value=100)
        r = run_tool("edge_density", smooth, {"max_ratio": 0.01})
        self.assertEqual(r.outputs["ratio"], 0)
        self.assertEqual(r.branch, "ok")
        scratched = smooth.copy()
        for y in range(20, 220, 10):
            cv2.line(scratched, (10, y), (310, y + 5), 200, 1)
        r2 = run_tool("edge_density", scratched, {"max_ratio": 0.01, "roi": {"shape": "rect", "x": 0, "y": 0, "w": 320, "h": 240}})
        self.assertEqual(r2.branch, "ng")
        self.assertGreater(r2.outputs["ratio"], 0.01)
        mask = np.zeros((100, 100), np.uint8)
        mask[10:20, 10:30] = 255
        p = run_tool("pixel_count", mask, {"min_count": 100, "max_count": 300})
        self.assertEqual(p.outputs["count"], 200)
        self.assertEqual(p.branch, "ok")
        p2 = run_tool("pixel_count", mask, {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 20, "h": 100}, "min_count": 150})
        self.assertEqual(p2.outputs["count"], 100)
        self.assertEqual(p2.status, "ng")


# ---------------------------------------------------------------------------
# dl
# ---------------------------------------------------------------------------
class DlTests(SimpleTestCase):
    def setUp(self):
        if dl_mod.ort is None:
            self.skipTest("未安裝 onnxruntime")
        dl_mod.clear_sessions()

    def test_classify_with_tiny_model(self):
        folder = temp_dir()
        model = gap_classifier_onnx(folder, 8)
        img = np.zeros((50, 50, 3), np.uint8)
        img[:] = (255, 0, 0)  # BGR 純藍
        params = {"model": "m", "labels": "blue\ngreen\nred", "mean": "0", "std": "1", "color_order": "bgr", "threshold": 0.5}
        r = run_tool("dl_classify", img, params, assets={"m": model})
        self.assertEqual(r.outputs["label"], "blue", r.message)
        self.assertEqual(r.branch, "pass")
        self.assertGreater(r.outputs["score"], 0.5)
        self.assertEqual(len(r.outputs["top"]), 3)
        # rgb 順序 → 通道 0 變成 R=0，最高的是 B（索引 2 → "red" 標籤位置）
        r2 = run_tool("dl_classify", img, {**params, "color_order": "rgb"}, assets={"m": model})
        self.assertEqual(r2.outputs["index"], 2)
        # pass_labels 篩選 → fail
        r3 = run_tool("dl_classify", img, {**params, "pass_labels": "red"}, assets={"m": model})
        self.assertEqual(r3.branch, "fail")
        self.assertEqual(r3.status, "ng")
        # ROI（旋轉矩形）也能跑
        r4 = run_tool("dl_classify", img, {**params, "roi": {"shape": "rotated_rect", "cx": 25, "cy": 25, "w": 20, "h": 10, "angle": 30}}, assets={"m": model})
        self.assertEqual(r4.outputs["label"], "blue")
        self.assertIn(model, dl_mod._SESSIONS)

    def test_segment_with_identity_model(self):
        folder = temp_dir()
        model = identity_onnx(folder, 8)
        img = np.zeros((40, 40, 3), np.uint8)
        img[:, :20] = (255, 0, 0)  # 左半藍 → 類別 0（bgr）
        img[:, 20:] = (0, 0, 255)  # 右半紅 → 類別 2
        r = run_tool("dl_segment", img, {"model": "m", "mean": "0", "std": "1", "color_order": "bgr", "target_class": 2, "labels": "b\ng\nr"}, assets={"m": model})
        self.assertEqual(r.outputs["mask"].shape, (40, 40))
        self.assertEqual(int(r.outputs["mask"][10, 30]), 255)
        self.assertEqual(int(r.outputs["mask"][10, 5]), 0)
        self.assertEqual(r.outputs["area"], 800)
        self.assertEqual({c["label"]: c["area"] for c in r.outputs["classes"]}, {"b": 800, "r": 800})
        self.assertEqual(r.branch, "ok")

    def test_missing_model_and_bad_model(self):
        with self.assertRaises(ToolError):
            run_tool("dl_detect", blank(), {"model": "x"})
        folder = temp_dir()
        bad = f"{folder}/bad.onnx"
        with open(bad, "wb") as f:
            f.write(b"not a model")
        with self.assertRaises(ToolError):
            run_tool("dl_classify", blank(), {"model": "b"}, assets={"b": bad})

    def test_parse_yolo_formats(self):
        # v8：[1, 4+nc, N]
        nc, n = 3, 10
        v8 = np.zeros((1, 4 + nc, n), np.float32)
        v8[0, :4, 0] = (100, 120, 40, 20)
        v8[0, 4 + 1, 0] = 0.9
        boxes, scores, ids = dl_mod.parse_yolo(v8, nc)
        self.assertEqual(boxes.shape, (n, 4))
        self.assertAlmostEqual(float(scores[0]), 0.9)
        self.assertEqual(int(ids[0]), 1)
        # v5：[1, N, 5+nc]
        v5 = np.zeros((1, n, 5 + nc), np.float32)
        v5[0, 0, :4] = (100, 120, 40, 20)
        v5[0, 0, 4] = 0.5
        v5[0, 0, 5 + 2] = 0.8
        boxes, scores, ids = dl_mod.parse_yolo(v5, nc)
        self.assertAlmostEqual(float(scores[0]), 0.4)
        self.assertEqual(int(ids[0]), 2)
        with self.assertRaises(ToolError):
            dl_mod.parse_yolo(np.zeros((1, 10, 3), np.float32), 0)

    def test_preprocess_letterbox(self):
        img = np.zeros((100, 200, 3), np.uint8)
        t, info = dl_mod.preprocess(img, (64, 64), np.zeros(3, np.float32), np.ones(3, np.float32), "rgb", letterbox=True)
        self.assertEqual(t.shape, (1, 3, 64, 64))
        self.assertAlmostEqual(info["scale"], 0.32)
        self.assertEqual(info["pad_y"], 16)
        self.assertAlmostEqual(float(t[0, 0, 0, 0]), 114 / 255, places=5)  # 上方 padding
