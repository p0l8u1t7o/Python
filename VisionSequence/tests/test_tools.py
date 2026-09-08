"""內建工具（locate / measure / detect / dl）單元測試：全部用合成影像。"""

from __future__ import annotations

import math
import tempfile

import cv2
import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.vision.tools import base, defects
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
    yolo_seg_onnx,
)


class RegistryTests(SimpleTestCase):
    def test_all_new_tools_registered(self):
        expected = {
            "template_match", "shape_align", "fixture_roi", "find_circle", "find_line", "hough_circles", "hough_lines",
            "caliper", "distance", "angle", "intensity", "calibration", "histogram",
            "fit_arc", "fit_ellipse", "wall_thickness", "concentricity", "chamfer_angle", "tolerance_judge",
            "blob", "defect_diff", "barcode", "text_presence", "color_check", "edge_density", "pixel_count",
            "dl_classify", "dl_detect", "dl_segment", "dl_instance",
            "convert_depth", "lut", "filter", "fft_filter", "warp_perspective", "line_profile", "color_stats", "geometry",
            "polar_unwrap", "polar_restore", "contour_find", "contour_filter", "contour_geometry", "contour_match",
            "region_from_shape", "region_combine", "shading_correct", "defect_stat", "shape_match", "dl_anomaly", "circular_caliper", "profile_defect", "ocr_read", "ocv_verify",
        }
        keys = {t.key for t in base.all_types()}
        self.assertTrue(expected <= keys, expected - keys)
        cats = {t.key: t.category for t in base.all_types()}
        self.assertEqual(cats["template_match"], "locate")
        self.assertEqual(cats["caliper"], "measure")
        self.assertEqual(cats["blob"], "detect")
        self.assertEqual(cats["dl_classify"], "dl")
        self.assertEqual({k for k in keys if k.startswith("ai_")}, {"ai_detect", "ai_segment", "ai_classify", "ai_pose", "ai_obb"})
        self.assertEqual(cats["ai_detect"], "dl")
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
        self.assertEqual(teach["ai_detect"], {"conf"})
        self.assertEqual(teach["ai_classify"], {"threshold"})
        self.assertEqual(teach["pixel_count"], {"min_count", "max_count"})
        self.assertEqual(teach["edge_density"], {"max_ratio"})
        self.assertEqual(teach["text_presence"], {"min_ratio", "max_ratio"})
        self.assertEqual(teach["tolerance_judge"], {"nominal", "upper_tol", "lower_tol"})
        self.assertEqual(teach["concentricity"], {"max_deviation"})
        self.assertEqual(teach["polar_unwrap"], {"roi", "start_angle"})
        self.assertEqual(teach["polar_restore"], set())
        self.assertEqual(teach["contour_find"], {"threshold", "min_area"})
        self.assertEqual(teach["contour_filter"], {"min_area", "max_area"})
        self.assertEqual(teach["contour_geometry"], {"defect_depth"})
        self.assertEqual(teach["contour_match"], {"max_distance"})
        self.assertEqual(teach["region_combine"], {"base"})
        self.assertEqual(teach["region_from_shape"], {"roi"})
        self.assertEqual(teach["shading_correct"], set())
        self.assertEqual(teach["defect_stat"], {"roi", "sigma", "min_area", "direction"})
        self.assertEqual(teach["shape_match"], {"min_score", "max_matches", "angle_start", "angle_extent"})
        self.assertEqual(teach["dl_anomaly"], {"roi", "threshold", "min_area"})
        self.assertEqual(teach["circular_caliper"], {"roi", "caliper_count", "edge_threshold", "polarity", "edge_select"})
        self.assertEqual(teach["profile_defect"], {"threshold", "threshold_mode", "min_width", "direction", "max_defects"})
        self.assertEqual(teach["ocr_read"], {"roi", "charset", "custom_charset", "polarity", "min_confidence"})
        self.assertEqual(teach["ocv_verify"], {"expected", "min_char_confidence"})
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
        # getRotationMatrix2D 的 +10 是畫面逆時針；平台角度以畫面順時針為正（與 ROI／找直線一致）→ −10
        self.assertAlmostEqual(r.outputs["best_angle"], -10, delta=1.0)

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
class ToolPurityTests(SimpleTestCase):
    """保證：工具的標記（overlays）只是顯示層 metadata——不畫進影像、也不就地修改輸入影像。
    下一個工具收到的影像不受上一個工具的標記影響（draw_result 也只畫在自己的 copy）。"""

    def test_tools_do_not_mutate_input_images(self):
        import os
        import shutil
        import sys

        scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from bench_tools import Scene, cases, make_ctx

        folder = temp_dir()
        try:
            scene = Scene(640, 480, folder)
            for name, key, image, params, inputs, context in cases(scene):
                snapshots = [(k, v, v.copy()) for k, v in {"image": image, **inputs, **context}.items() if isinstance(v, np.ndarray)]
                if not snapshots:
                    continue
                base.get(key).execute(make_ctx(key, image, params, inputs, scene.assets, context))
                for port, arr, snap in snapshots:
                    self.assertTrue(np.array_equal(arr, snap), f"{name}（{key}）就地修改了輸入 '{port}' 的影像")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


    def test_overlays_use_known_kinds(self):
        """每個標記都要有前端畫得出來的 kind。寫成 "type" 或打錯字時前端只會安靜地不畫，這裡擋下來。"""
        import os
        import shutil
        import sys

        scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from bench_tools import Scene, cases, make_ctx

        known = {"rect", "circle", "annulus", "polygon", "polyline", "line", "point", "points", "text", "contours"}
        folder = temp_dir()
        try:
            scene = Scene(640, 480, folder)
            seen = 0
            for name, key, image, params, inputs, context in cases(scene):
                result = base.get(key).execute(make_ctx(key, image, params, inputs, scene.assets, context))
                for overlay in result.overlays:
                    self.assertIsInstance(overlay, dict, f"{name}（{key}）的標記不是 dict")
                    self.assertIn(overlay.get("kind"), known, f"{name}（{key}）的標記 kind 前端畫不出來：{overlay!r}"[:200])
                    seen += 1
            self.assertGreater(seen, 100)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


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

    def test_instance_with_synthetic_seg_model(self):
        """dl_instance 接線：letterbox 前處理、NMS、mask 合成、座標回映到全圖。"""
        folder = temp_dir()
        model = yolo_seg_onnx(folder, 64)
        img = np.full((128, 128, 3), 50, np.uint8)
        r = run_tool("dl_instance", img, {"model": "m", "labels": "obj", "conf": 0.5}, assets={"m": model})
        self.assertEqual(r.outputs["count"], 1, r.message)
        self.assertEqual(r.branch, "found")
        m0 = r.outputs["matches"][0]
        self.assertEqual(m0["label"], "obj")
        self.assertGreater(m0["score"], 0.5)
        # letterbox 中央 40% 的框 → 全圖中央（128×128、scale 0.5）：約 (38.4, 38.4)~(89.6, 89.6)
        self.assertAlmostEqual(m0["x"], 38.4, delta=3)
        self.assertAlmostEqual(m0["w"], 51.2, delta=4)
        mask = r.outputs["mask"]
        self.assertEqual(mask.shape, (128, 128))
        self.assertEqual(int(mask[64, 64]), 255)
        self.assertEqual(int(mask[5, 5]), 0)
        self.assertTrue(r.outputs["contours"])
        # 信心門檻高過唯一候選 → not_found 分支、status 依 min_count 判 ng
        r2 = run_tool("dl_instance", img, {"model": "m", "labels": "obj", "conf": 0.95}, assets={"m": model})
        self.assertEqual((r2.outputs["count"], r2.branch, r2.status), (0, "not_found", "ng"))
        # filter_labels 對不上 → 全被濾掉
        r3 = run_tool("dl_instance", img, {"model": "m", "labels": "obj", "conf": 0.5, "filter_labels": "nope"}, assets={"m": model})
        self.assertEqual(r3.outputs["count"], 0)

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


class NiVisionToolTests(SimpleTestCase):
    """NI Vision 對照的新工具：LUT／卷積濾波／FFT／位深轉換／透視校正／線剖面／色彩統計／幾何計算。"""

    def test_lut_gamma_and_linear(self):
        img = np.full((10, 10), 64, np.uint8)
        r = run_tool("lut", img, {"mode": "power", "gamma": 0.5})
        self.assertEqual(int(r.outputs["image"][0, 0]), 127)  # sqrt(64/255)*255
        r = run_tool("lut", img, {"mode": "linear", "brightness": 20, "contrast": 1.0})
        self.assertEqual(int(r.outputs["image"][0, 0]), 84)
        r = run_tool("lut", img, {"mode": "invert"})
        self.assertEqual(int(r.outputs["image"][0, 0]), 191)

    def test_filter_gradient_highlights_edges(self):
        img = np.zeros((20, 40), np.uint8)
        img[:, 20:] = 200
        r = run_tool("filter", img, {"method": "gradient"})
        out = r.outputs["image"]
        self.assertGreater(int(out[10, 20]), 100)  # 邊緣處梯度大
        self.assertEqual(int(out[10, 5]), 0)  # 平坦區為 0
        with self.assertRaises(ToolError):
            run_tool("filter", img, {"method": "custom", "kernel": [[1, 2], [3, 4]]})

    def test_fft_lowpass_removes_stripes(self):
        # 高頻直條紋：低通後振幅應大幅下降
        x = np.arange(64)
        img = (128 + 100 * np.sin(x * np.pi / 2)).astype(np.uint8)[None, :].repeat(64, axis=0)
        r = run_tool("fft_filter", img, {"mode": "lowpass", "style": "truncate", "cutoff": 0.1})
        out = r.outputs["image"]
        self.assertLess(float(out.std()), float(img.std()) * 0.3)
        self.assertEqual(r.outputs["spectrum"].shape, img.shape)

    def test_convert_depth_roundtrip(self):
        img = np.full((5, 5), 100, np.uint8)
        up = run_tool("convert_depth", img, {"to": "u16"}).outputs["image"]
        self.assertEqual(up.dtype, np.uint16)
        self.assertEqual(int(up[0, 0]), 100 << 8)
        back = run_tool("convert_depth", up, {"to": "u8", "scale": "shift"}).outputs["image"]
        self.assertEqual(back.dtype, np.uint8)
        self.assertEqual(int(back[0, 0]), 100)
        f = run_tool("convert_depth", img, {"to": "f32"}).outputs["image"]
        self.assertEqual(f.dtype, np.float32)

    def test_warp_perspective(self):
        img = np.zeros((80, 100, 3), np.uint8)
        cv2.rectangle(img, (20, 20), (80, 60), (0, 255, 0), -1)
        r = run_tool("warp_perspective", img, {"roi": {"shape": "polygon", "points": [[20, 20], [80, 20], [80, 60], [20, 60]]}, "width": 60, "height": 40})
        out = r.outputs["image"]
        self.assertEqual(out.shape[:2], (40, 60))
        self.assertGreater(int(out[20, 30, 1]), 200)  # 中央是綠色
        with self.assertRaises(ToolError):
            run_tool("warp_perspective", img, {"roi": {"shape": "polygon", "points": [[0, 0], [1, 0], [1, 1]]}})

    def test_line_profile(self):
        img = np.zeros((40, 60), np.uint8)
        img[:, 30:] = 200
        r = run_tool("line_profile", img, {"roi": {"shape": "line", "x1": 5, "y1": 20, "x2": 55, "y2": 20}})
        self.assertEqual(len(r.outputs["values"]), 50)
        self.assertEqual(r.outputs["min"], 0.0)
        self.assertEqual(r.outputs["max"], 200.0)
        r = run_tool("line_profile", img, {"roi": {"shape": "polyline", "points": [[5, 5], [30, 35], [55, 5]]}, "samples": 40})
        self.assertEqual(len(r.outputs["values"]), 40)

    def test_color_stats(self):
        img = np.zeros((20, 20, 3), np.uint8)
        img[:] = (30, 30, 220)  # BGR 紅
        r = run_tool("color_stats", img, {})
        self.assertGreater(r.outputs["mean_r"], 200)
        self.assertLess(r.outputs["mean_b"], 40)
        self.assertTrue(r.outputs["hex"].startswith("#dc"))

    def test_geometry_modes(self):
        r = run_tool("geometry", None, {"mode": "intersect"}, inputs={"a": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}, "b": {"x1": 0, "y1": 10, "x2": 10, "y2": 0}})
        self.assertEqual((r.outputs["x"], r.outputs["y"]), (5.0, 5.0))
        r = run_tool("geometry", None, {"mode": "point_line"}, inputs={"a": [5, 0], "b": {"x1": 0, "y1": 10, "x2": 10, "y2": 10}})
        self.assertEqual(r.outputs["distance"], 10.0)
        r = run_tool("geometry", None, {"mode": "midpoint"}, inputs={"a": [0, 0], "b": [10, 20]})
        self.assertEqual((r.outputs["x"], r.outputs["y"]), (5.0, 10.0))
        r = run_tool("geometry", None, {"mode": "intersect"}, inputs={"a": {"x1": 0, "y1": 0, "x2": 10, "y2": 0}, "b": {"x1": 0, "y1": 5, "x2": 10, "y2": 5}})
        self.assertEqual(r.status, "ng")  # 平行

    def test_blob_separate_and_fields(self):
        img = np.zeros((80, 130), np.uint8)
        cv2.circle(img, (40, 40), 20, 255, -1)
        cv2.circle(img, (76, 40), 20, 255, -1)
        base = {"threshold_method": "fixed", "threshold": 100, "min_area": 50}
        self.assertEqual(run_tool("blob", img, base).outputs["count"], 1)
        r = run_tool("blob", img, {**base, "separate": True})
        self.assertEqual(r.outputs["count"], 2)
        b = r.outputs["blobs"][0]
        for field_name in ("perimeter", "orientation", "elongation"):
            self.assertIn(field_name, b)

    def test_threshold_triangle(self):
        img = np.zeros((30, 30), np.uint8)
        img[10:20, 10:20] = 220
        r = run_tool("threshold", img, {"method": "triangle"})
        self.assertEqual(int(r.outputs["image"][15, 15]), 255)


class ImageDepthTests(SimpleTestCase):
    """位深（NI 的 U8/I16/SGL/RGB U64 對照）：宣告支援的工具原樣進出、其他自動正規化 u8。"""

    def test_transparent_tools_keep_depth(self):
        u16 = np.full((20, 20), 30000, np.uint16)
        self.assertEqual(run_tool("blur", u16, {"method": "gaussian", "ksize": 3}).outputs["image"].dtype, np.uint16)
        self.assertEqual(run_tool("crop", u16, {"roi": {"shape": "rect", "x": 2, "y": 2, "w": 10, "h": 10}}).outputs["image"].dtype, np.uint16)
        f32 = np.random.default_rng(1).random((20, 20)).astype(np.float32)
        self.assertEqual(run_tool("resize", f32, {"scale": 0.5}).outputs["image"].dtype, np.float32)

    def test_u8_tools_auto_normalize(self):
        # threshold 只吃 u8：u16 進來自動右移 8 正規化，不炸、行為合理
        u16 = np.zeros((20, 20), np.uint16)
        u16[5:15, 5:15] = 60000  # >>8 = 234
        r = run_tool("threshold", u16, {"method": "fixed", "threshold": 128})
        self.assertEqual(int(r.outputs["image"][10, 10]), 255)
        self.assertEqual(int(r.outputs["image"][1, 1]), 0)
        r = run_tool("histogram", u16, {})
        self.assertEqual(r.status, "ok")

    def test_purity_on_u16(self):
        u16 = np.full((20, 20), 40000, np.uint16)
        snap = u16.copy()
        run_tool("threshold", u16, {"method": "otsu"})
        self.assertTrue(np.array_equal(u16, snap))  # 正規化產生新陣列，不動輸入


class RoiShapeTests(SimpleTestCase):
    """ROI 新形狀（NI 工具面板對照）：ellipse／annulus 扇形／point／polyline。"""

    def test_ellipse_mask_and_transform(self):
        from apps.vision.tools.roi import mask_for, transform_region

        m = mask_for({"shape": "ellipse", "cx": 50, "cy": 40, "rx": 30, "ry": 15, "angle": 0}, 100, 80)
        area = int(m.sum() / 255)
        self.assertAlmostEqual(area, 3.14159 * 30 * 15, delta=area * 0.1)
        out = transform_region({"shape": "ellipse", "cx": 10, "cy": 10, "rx": 5, "ry": 3, "angle": 0}, 5, 0, 90, (0, 0))
        self.assertEqual(out["angle"], 90.0)

    def test_annulus_sector(self):
        from apps.vision.tools.roi import mask_for

        sector = mask_for({"shape": "annulus", "cx": 50, "cy": 40, "r_inner": 10, "r_outer": 30, "a0": 0, "a1": 90}, 100, 80)
        full = mask_for({"shape": "annulus", "cx": 50, "cy": 40, "r_inner": 10, "r_outer": 30}, 100, 80)
        self.assertAlmostEqual(sector.sum() / full.sum(), 0.25, delta=0.05)

    def test_point_and_polyline(self):
        from apps.vision.tools.roi import bounding_rect, mask_for, region_overlay

        self.assertEqual(bounding_rect({"shape": "point", "x": 5, "y": 6}, 100, 80), (5, 6, 1, 1))
        m = mask_for({"shape": "polyline", "points": [[0, 0], [50, 0], [50, 40]]}, 100, 80)
        self.assertAlmostEqual(int(m.sum() / 255), 90, delta=3)
        self.assertEqual(region_overlay({"shape": "point", "x": 1, "y": 2})["kind"], "point")
        self.assertEqual(region_overlay({"shape": "ellipse", "cx": 5, "cy": 5, "rx": 3, "ry": 2})["kind"], "polygon")

    def test_intensity_point_roi(self):
        img = np.zeros((20, 20), np.uint8)
        img[7, 9] = 137
        r = run_tool("intensity", img, {"roi": {"shape": "point", "x": 9, "y": 7}})
        self.assertEqual(r.outputs["mean"], 137.0)
        self.assertEqual(r.outputs["pixels"], 1)

class PolarTests(SimpleTestCase):
    """WP-04 極座標展開：合成 N 條徑向線的圓環 → 展開後 blob 數＝N；還原往返；扇形寬度；方向與起始角；位深。"""

    N = 12

    def _ring(self, n: int | None = None, phase: float = 7.0) -> np.ndarray:
        n = n or self.N
        img = np.full((480, 640), 30, np.uint8)
        cx, cy = 320, 240
        cv2.circle(img, (cx, cy), 150, 80, -1)
        cv2.circle(img, (cx, cy), 100, 30, -1)
        for k in range(n):
            t = math.radians(phase + k * 360.0 / n)
            cv2.line(img, (int(round(cx + 103 * math.cos(t))), int(round(cy + 103 * math.sin(t)))),
                     (int(round(cx + 147 * math.cos(t))), int(round(cy + 147 * math.sin(t)))), 230, 4)
        return img

    ROI = {"shape": "annulus", "cx": 320, "cy": 240, "r_inner": 100, "r_outer": 150}

    def test_unwrap_counts_radial_lines(self):
        r = run_tool("polar_unwrap", self._ring(), {"roi": self.ROI})
        self.assertEqual(r.status, "ok", r.message)
        strip = r.outputs["image"]
        m = r.outputs["mapping"]
        # auto 步進：外緣弧長 1 px → 寬＝2π·r_outer；高＝r_outer−r_inner+1
        self.assertEqual(strip.shape, (51, int(round(2 * math.pi * 150))))
        self.assertEqual((m["width"], m["height"]), (strip.shape[1], strip.shape[0]))
        self.assertAlmostEqual(r.outputs["step_deg"], 360 / (2 * math.pi * 150))
        b = run_tool("blob", strip, {"threshold_method": "fixed", "threshold": 150, "min_area": 40})
        self.assertEqual(b.outputs["count"], self.N)
        self.assertEqual({o["kind"] for o in r.overlays}, {"annulus", "line"})

    def test_restore_roundtrip_and_marks_the_lines(self):
        from apps.vision.tools.builtin import polar

        r = run_tool("polar_unwrap", self._ring(), {"roi": self.ROI})
        m = r.outputs["mapping"]
        pts = np.array([[440.0, 240.0], [320.0, 120.0], [320 - 140 * math.cos(0.4), 240 + 140 * math.sin(0.4)]])
        back = polar.polar_to_image(polar.image_to_polar(pts, m), m)
        self.assertLess(float(np.abs(back - pts).max()), 0.5)
        b = run_tool("blob", r.outputs["image"], {"threshold_method": "fixed", "threshold": 150, "min_area": 40})
        rr = run_tool("polar_restore", None, {}, {"mapping": m, "points": b.outputs["centers"], "contours": b.outputs["contours"]})
        self.assertEqual(rr.outputs["count"], 2 * self.N)
        self.assertEqual(len(rr.outputs["contours"]), self.N)
        self.assertEqual(rr.outputs["contours"][0].shape[1:], (1, 2))
        angles = sorted((math.degrees(math.atan2(y - 240, x - 320)) - 7.0) % 30.0 for x, y in rr.outputs["points"])
        for a in angles:  # 每個還原的中心都落在某條徑向線上（相位 7°、間隔 30°）
            self.assertLess(min(a, 30 - a), 1.0, angles)
        for x, y in rr.outputs["points"]:
            self.assertTrue(103 <= math.hypot(x - 320, y - 240) <= 147)
        self.assertEqual({o["kind"] for o in rr.overlays}, {"contours", "points"})
        self.assertFalse(math.isnan(rr.outputs["first_angle"]))

    def test_sector_width(self):
        r = run_tool("polar_unwrap", self._ring(), {"roi": {**self.ROI, "a0": 0, "a1": 90}, "angle_step": "1"})
        self.assertEqual(r.outputs["image"].shape, (51, 91))
        r = run_tool("polar_unwrap", self._ring(), {"roi": {**self.ROI, "a0": 300, "a1": 60}, "angle_step": "2"})
        self.assertEqual(r.outputs["image"].shape[1], 61)  # 跨 0° 的扇形：120°／2° ＋ 1
        self.assertTrue(r.outputs["mapping"]["sector"])

    def test_direction_and_start_angle(self):
        img = self._ring(n=1, phase=0.0)  # 只有 3 點鐘方向一條線
        cw = run_tool("polar_unwrap", img, {"roi": self.ROI, "angle_step": "1", "direction": "cw", "start_angle": -45})
        ccw = run_tool("polar_unwrap", img, {"roi": self.ROI, "angle_step": "1", "direction": "ccw", "start_angle": -45})
        col_cw = int(np.argmax(cw.outputs["image"][25]))
        col_ccw = int(np.argmax(ccw.outputs["image"][25]))
        self.assertAlmostEqual(col_cw, 45, delta=1)   # 順時針：−45° 起走 45° 到 0°
        self.assertAlmostEqual(col_ccw, 315, delta=1)  # 逆時針：−45° 往回走 315° 到 0°

    def test_keeps_depth_and_colour(self):
        u16 = (self._ring().astype(np.uint16) << 8)
        r = run_tool("polar_unwrap", u16, {"roi": self.ROI, "interpolation": "nearest"})
        self.assertEqual(r.outputs["image"].dtype, np.uint16)
        bgr = cv2.cvtColor(self._ring(), cv2.COLOR_GRAY2BGR)
        r = run_tool("polar_unwrap", bgr, {"roi": self.ROI, "interpolation": "cubic"})
        self.assertEqual(r.outputs["image"].shape[2], 3)
        with self.assertRaises(ToolError):
            run_tool("polar_unwrap", bgr, {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 10, "h": 10}})
        r = run_tool("polar_unwrap", bgr, {}, {"roi": {"shape": "circle", "cx": 320, "cy": 240, "r": 60}})
        self.assertEqual(r.outputs["r_inner"], 0.0)

    def test_restore_without_mapping_uses_numbers_and_params(self):
        r = run_tool("polar_unwrap", self._ring(), {"roi": self.ROI, "angle_step": "1", "direction": "cw", "start_angle": 10})
        rr = run_tool("polar_restore", None, {"angle_step": "1", "direction": "cw", "start_angle": 10},
                      {"cx": 320, "cy": 240, "r_inner": 100, "r_outer": 150, "points": [[35, 20]]})
        expect = (320 + 120 * math.cos(math.radians(45)), 240 + 120 * math.sin(math.radians(45)))
        self.assertAlmostEqual(rr.outputs["first_x"], expect[0], places=6)
        self.assertAlmostEqual(rr.outputs["first_y"], expect[1], places=6)
        self.assertEqual(r.outputs["mapping"]["step_deg"], 1.0)
        with self.assertRaises(ToolError):
            run_tool("polar_restore", None, {}, {"points": [[1, 1]]})
        empty = run_tool("polar_restore", None, {}, {"mapping": r.outputs["mapping"]})
        self.assertEqual(empty.outputs["count"], 0)


class ContourTests(SimpleTestCase):
    """WP-15 contours 工具鏈：萃取（面積＝像素數）、凸缺陷、篩選、Hu 矩比對、串接。"""

    @staticmethod
    def _rect_mask(notch: bool = False) -> np.ndarray:
        img = np.zeros((480, 640), np.uint8)
        cv2.rectangle(img, (100, 90), (499, 389), 255, -1)
        if notch:
            cv2.fillPoly(img, [np.array([[280, 90], [320, 90], [300, 120]], np.int32)], 0)  # 三角缺角，深 30
        return img

    @staticmethod
    def _star(cx: float, cy: float, r: float, scale: float = 1.0, rot: float = 0.0) -> np.ndarray:
        pts = []
        for k in range(10):
            a = math.radians(rot + k * 36)
            rr = r * scale * (1.0 if k % 2 == 0 else 0.45)
            pts.append([cx + rr * math.cos(a), cy + rr * math.sin(a)])
        return np.round(np.array(pts)).astype(np.int32)


    def test_chain_into_gdt_measure(self):
        """WP-10 串接：contour_find → contour_filter → contour_geometry → gdt_measure（真圓度）——圓盤在公差內、崩邊的圓盤超差。"""
        for chip, expect in ((False, "pass"), (True, "fail")):
            img = np.zeros((480, 640), np.uint8)
            cv2.circle(img, (320, 240), 150, 255, -1)
            cv2.circle(img, (40, 40), 12, 255, -1)  # 小雜點：篩選要把它去掉
            if chip:
                cv2.ellipse(img, (470, 240), (30, 18), 0, 0, 360, 0, -1)
            found = run_tool("contour_find", img, {"threshold_method": "none", "mode": "external"})
            self.assertEqual(found.outputs["count"], 2)
            filt = run_tool("contour_filter", None, {"min_area": 5000}, {"contours": found.outputs["contours"]})
            self.assertEqual(filt.outputs["count"], 1)
            geo = run_tool("contour_geometry", None, {}, {"contours": filt.outputs["contours"]})
            self.assertGreater(geo.outputs["first_circularity"], 0.75)  # 像素化輪廓的周長偏長，圓的 4πA/P² 約 0.82
            r = run_tool("gdt_measure", None, {"mode": "roundness", "tolerance": 4}, {"points": filt.outputs["contours"]})
            self.assertEqual(r.branch, expect, r.message)
            if chip:
                self.assertGreater(r.outputs["deviation"], 10)
            else:
                self.assertLess(r.outputs["deviation"], 1.5)  # 像素化的圓：MZC 帶寬在 1 px 上下

    def test_find_area_is_pixel_count(self):
        r = run_tool("contour_find", self._rect_mask(), {"threshold_method": "none"})
        self.assertEqual(r.branch, "found")
        self.assertEqual(r.outputs["count"], 1)
        self.assertEqual(r.outputs["first_area"], 120000.0)  # 400×300，誤差 0（規格要求 < 1%）
        self.assertAlmostEqual(r.outputs["first_cx"], 299.5, delta=0.01)
        self.assertAlmostEqual(r.outputs["first_cy"], 239.5, delta=0.01)
        self.assertEqual(r.outputs["contours"][0].shape[1:], (1, 2))
        self.assertEqual({o["kind"] for o in r.overlays}, {"contours"})
        # 灰階輸入自動二值化＋ROI 裁切座標換回全圖
        gray = (self._rect_mask() // 2 + 20).astype(np.uint8)
        r = run_tool("contour_find", gray, {"roi": {"shape": "rect", "x": 50, "y": 50, "w": 300, "h": 200}})
        self.assertEqual(r.outputs["count"], 1)
        self.assertAlmostEqual(r.outputs["first_cx"], (100 + 349) / 2, delta=0.6)
        empty = run_tool("contour_find", np.zeros((40, 40), np.uint8), {"threshold_method": "none"})
        self.assertEqual((empty.branch, empty.status, empty.outputs["count"]), ("not_found", "ng", 0))

    def test_find_modes_return_holes(self):
        img = self._rect_mask()
        cv2.circle(img, (300, 240), 40, 0, -1)
        ext = run_tool("contour_find", img, {"threshold_method": "none", "mode": "external"})
        every = run_tool("contour_find", img, {"threshold_method": "none", "mode": "list"})
        self.assertEqual((ext.outputs["count"], every.outputs["count"]), (1, 2))
        self.assertAlmostEqual(every.outputs["areas"][1], math.pi * 40.5 * 40.5, delta=150)  # 孔的輪廓含邊界像素環，略大於幾何面積

    def test_geometry_convexity_defect(self):
        r = run_tool("contour_find", self._rect_mask(notch=True), {"threshold_method": "none"})
        g = run_tool("contour_geometry", None, {"defect_depth": 5}, {"contours": r.outputs["contours"]})
        self.assertEqual(g.outputs["first_defects"], 1)
        self.assertAlmostEqual(g.outputs["first_max_defect_depth"], 30, delta=2)
        d = g.outputs["geometry"][0]["defects"][0]
        self.assertAlmostEqual(d["x"], 300, delta=2)
        self.assertLess(g.outputs["first_convexity"], 1.0)
        self.assertEqual(g.outputs["defect_points"], [[d["x"], d["y"]]])
        self.assertTrue(any(o["kind"] == "point" and o["color"] == "#ef4444" for o in g.overlays))
        clean = run_tool("contour_geometry", None, {"defect_depth": 5}, {"contours": run_tool("contour_find", self._rect_mask(), {"threshold_method": "none"}).outputs["contours"]})
        self.assertEqual((clean.outputs["first_defects"], clean.outputs["first_convexity"]), (0, 1.0))
        self.assertAlmostEqual(clean.outputs["first_w"], 399, delta=1)
        self.assertAlmostEqual(clean.outputs["first_h"], 299, delta=1)
        self.assertEqual(len(clean.outputs["geometry"][0]["hu"]), 7)
        none = run_tool("contour_geometry", None, {}, {"contours": []})
        self.assertEqual(none.outputs["count"], 0)

    def test_filter_limits_and_sort(self):
        img = np.zeros((480, 640), np.uint8)
        cv2.circle(img, (150, 150), 60, 255, -1)
        cv2.rectangle(img, (400, 300), (600, 400), 255, -1)
        cv2.circle(img, (500, 100), 10, 255, -1)
        cnts = run_tool("contour_find", img, {"threshold_method": "none"}).outputs["contours"]
        f = run_tool("contour_filter", None, {"min_area": 1000, "sort_by": "x"}, {"contours": cnts})
        self.assertEqual((f.outputs["count"], f.outputs["rejected"]), (2, 1))
        self.assertLess(f.outputs["centers"][0][0], f.outputs["centers"][1][0])
        inside = run_tool("contour_filter", None, {"roi": {"shape": "rect", "x": 350, "y": 250, "w": 300, "h": 200}}, {"contours": cnts})
        self.assertEqual(inside.outputs["count"], 1)
        self.assertAlmostEqual(inside.outputs["first_area"], 201 * 101, delta=1)
        aspect = run_tool("contour_filter", None, {"min_aspect": 1.5}, {"contours": cnts})
        self.assertEqual(aspect.outputs["count"], 1)
        nothing = run_tool("contour_filter", None, {"min_area": 1e9}, {"contours": cnts})
        self.assertEqual((nothing.branch, nothing.status), ("not_found", "ng"))

    def test_match_template_asset_and_reference_port(self):
        tpl = np.zeros((200, 200), np.uint8)
        cv2.fillPoly(tpl, [self._star(100, 100, 80)], 255)
        folder = temp_dir()
        tpl_path = save_png(tpl, folder, "star.png")
        scene = np.zeros((480, 640), np.uint8)
        cv2.fillPoly(scene, [self._star(200, 240, 80, 1.4, 25)], 255)  # 放大、旋轉的星形
        cv2.rectangle(scene, (400, 150), (560, 330), 255, -1)
        cnts = run_tool("contour_find", scene, {"threshold_method": "none"}).outputs["contours"]
        m = run_tool("contour_match", None, {"template": "t", "max_distance": 0.1}, {"contours": cnts}, assets={"t": tpl_path})
        self.assertEqual(m.branch, "match")
        self.assertEqual(m.outputs["match_count"], 1)
        self.assertLess(m.outputs["distance"], 0.02)
        star_idx = m.outputs["best_index"]
        self.assertGreater(m.outputs["distances"][1 - star_idx], 0.1)
        self.assertEqual(len(m.outputs["matched"]), 1)
        ref = run_tool("contour_match", None, {"max_distance": 0.05}, {"contours": cnts, "reference": [cnts[star_idx]]})
        self.assertAlmostEqual(ref.outputs["distance"], 0.0, places=6)
        with self.assertRaises(ToolError):
            run_tool("contour_match", None, {}, {"contours": cnts})
        strict = run_tool("contour_match", None, {"template": "t", "max_distance": 0.0001}, {"contours": cnts[1 - star_idx: 2 - star_idx]}, assets={"t": tpl_path})
        self.assertEqual((strict.branch, strict.status), ("no_match", "ng"))

    def test_chain_find_filter_geometry(self):
        img = self._rect_mask(notch=True)
        cv2.circle(img, (40, 40), 8, 255, -1)  # 雜訊粒子
        found = run_tool("contour_find", img, {"threshold_method": "none"})
        kept = run_tool("contour_filter", None, {"min_area": 5000}, {"contours": found.outputs["contours"]})
        geo = run_tool("contour_geometry", None, {"defect_depth": 10}, {"contours": kept.outputs["contours"]})
        self.assertEqual((found.outputs["count"], kept.outputs["count"], geo.outputs["count"]), (2, 1, 1))
        self.assertEqual(geo.outputs["total_defects"], 1)
        self.assertEqual(geo.outputs["areas"], kept.outputs["areas"])


class CompositeRoiTests(SimpleTestCase):
    """WP-08 多重 ROI 與排除區：composite 的遮罩／外框／中心／位移／標記，與 region_combine／region_from_shape 工具。"""

    RECT = {"shape": "rect", "x": 20, "y": 10, "w": 100, "h": 60}
    HOLE = {"shape": "circle", "cx": 70, "cy": 40, "r": 15}

    def test_mask_union_subtract_intersect_nested(self):
        from apps.vision.tools.roi import composite, mask_for

        rect_px = 100 * 60
        hole_px = int(mask_for(self.HOLE, 160, 100).sum() / 255)
        sub = composite(self.RECT, [("subtract", self.HOLE)])
        self.assertEqual(int(mask_for(sub, 160, 100).sum() / 255), rect_px - hole_px)
        far = {"shape": "rect", "x": 130, "y": 80, "w": 20, "h": 10}
        uni = composite(self.RECT, [("union", far)])
        self.assertEqual(int(mask_for(uni, 160, 100).sum() / 255), rect_px + 200)
        inter = composite(self.RECT, [("intersect", {"shape": "rect", "x": 100, "y": 50, "w": 100, "h": 100})])
        self.assertEqual(int(mask_for(inter, 160, 100).sum() / 255), 20 * 20)
        # 巢狀：(rect − hole) ∪ far，再挖掉 far 的一半
        nested = composite(uni_sub := composite(sub, [("union", far)]), [("subtract", {"shape": "rect", "x": 130, "y": 80, "w": 10, "h": 10})])
        self.assertEqual(len(uni_sub["ops"]), 3)
        self.assertEqual(int(mask_for(nested, 160, 100).sum() / 255), rect_px - hole_px + 100)
        # 子視窗（crop 用的 offset）與全圖一致
        full = mask_for(sub, 160, 100)
        window = mask_for(sub, 100, 60, offset=(20, 10))
        self.assertTrue(np.array_equal(full[10:70, 20:120], window))
        with self.assertRaises(ValueError):
            composite(self.RECT, [("xor", self.HOLE)])

    def test_bounding_rect_center_transform_overlay(self):
        from apps.vision.tools.roi import bounding_rect, composite, crop, region_center, region_overlay, region_overlays, transform_region

        sub = composite(self.RECT, [("subtract", {"shape": "circle", "cx": 150, "cy": 40, "r": 40})])
        self.assertEqual(bounding_rect(sub, 400, 300), (20, 10, 100, 60))  # 挖除項不擴大外框
        uni = composite(self.RECT, [("union", {"shape": "rect", "x": 150, "y": 100, "w": 10, "h": 10})])
        self.assertEqual(bounding_rect(uni, 400, 300), (20, 10, 140, 100))
        cx, cy = region_center(composite(self.RECT, [("subtract", {"shape": "rect", "x": 20, "y": 10, "w": 50, "h": 60})]))
        self.assertAlmostEqual(cx, 95, delta=1.0)  # 挖掉左半後重心在右半
        self.assertAlmostEqual(cy, 40, delta=1.0)
        moved = transform_region(composite(self.RECT, [("subtract", self.HOLE)]), 5, -3)
        self.assertEqual(moved["shape"], "composite")
        self.assertEqual((moved["ops"][0]["region"]["x"], moved["ops"][1]["region"]["cx"]), (25, 75))
        rotated = transform_region(composite(self.RECT, [("subtract", self.HOLE)]), 0, 0, 90, (70, 40))
        self.assertEqual(rotated["ops"][0]["region"]["shape"], "rotated_rect")
        ov = region_overlay(composite(self.RECT, [("subtract", self.HOLE)]))
        self.assertEqual(ov["kind"], "contours")
        self.assertEqual(len(ov["contours"]), 2)  # 外框＋孔
        parts = region_overlays(composite(self.RECT, [("subtract", self.HOLE), ("union", {"shape": "point", "x": 1, "y": 1})]))
        self.assertEqual([p["kind"] for p in parts], ["rect", "circle", "point"])
        self.assertEqual(parts[1]["color"], "#ef4444")
        c = crop(np.zeros((300, 400), np.uint8), sub)
        self.assertEqual(c.image.shape, (60, 100))
        self.assertIsNotNone(c.mask)

    def test_existing_tools_honour_composite(self):
        from apps.vision.tools.roi import composite

        img = np.full((100, 160), 200, np.uint8)
        cv2.circle(img, (70, 40), 15, 20, -1)  # 量測區中央一個暗孔
        with_hole = run_tool("intensity", img, {"roi": self.RECT})
        excluded = run_tool("intensity", img, {}, {"roi": composite(self.RECT, [("subtract", self.HOLE)])})
        self.assertLess(with_hole.outputs["mean"], 190)
        self.assertEqual(excluded.outputs["mean"], 200.0)  # 孔內像素完全不算
        self.assertEqual(excluded.outputs["pixels"], with_hole.outputs["pixels"] - int(cv2.countNonZero(cv2.circle(np.zeros((100, 160), np.uint8), (70, 40), 15, 255, -1))))
        # blob／pixel_count／histogram／edge_density／color_check／contour_find／find_circle／caliper 都吃得下
        mask = np.zeros((100, 160), np.uint8)
        cv2.circle(mask, (70, 40), 15, 255, -1)
        cv2.circle(mask, (30, 30), 5, 255, -1)
        blobs = run_tool("blob", mask, {"threshold_method": "none", "min_area": 10}, {"roi": composite(self.RECT, [("subtract", self.HOLE)])})
        self.assertEqual(blobs.outputs["count"], 1)  # 大圓被挖掉、只剩小圓
        self.assertEqual(run_tool("pixel_count", mask, {}, {"roi": composite(self.RECT, [("subtract", self.HOLE)])}).outputs["count"], int(cv2.countNonZero(mask[10:70, 20:120]) - int(mask[25:56, 55:86].sum() / 255)))
        for key, params in (("histogram", {}), ("edge_density", {}), ("color_check", {"color": "#c8c8c8"}), ("contour_find", {"threshold_method": "fixed", "threshold": 100, "polarity": "dark"})):
            r = run_tool(key, img, params, {"roi": composite(self.RECT, [("subtract", self.HOLE)])})
            self.assertNotEqual(r.status, "error", key)
        ring = circle_image(cx=160, cy=120, r=50)
        fc = run_tool("find_circle", ring, {"edge_threshold": 20}, {"roi": composite({"shape": "rect", "x": 80, "y": 40, "w": 160, "h": 160}, [("subtract", {"shape": "circle", "cx": 160, "cy": 120, "r": 20})])})
        self.assertEqual(fc.branch, "found")
        self.assertAlmostEqual(fc.outputs["r"], 50, delta=1.0)
        cal = run_tool("caliper", rect_image(), {}, {"roi": composite({"shape": "rect", "x": 60, "y": 100, "w": 200, "h": 20}, [("subtract", {"shape": "circle", "cx": 160, "cy": 110, "r": 5})])})
        self.assertEqual(cal.status, "ok", cal.message)  # 矩形類工具退化用組合區域的外框
        self.assertAlmostEqual(cal.outputs["width"], 120, delta=1.5)

    def test_region_tools(self):
        from apps.vision.tools.roi import mask_for

        shape = run_tool("region_from_shape", None, {"roi": self.HOLE})
        self.assertEqual(shape.outputs["region"], self.HOLE)
        combined = run_tool("region_combine", None, {"base": self.RECT, "mode": "subtract"}, {"regions": [shape.outputs["region"], {"shape": "rect", "x": 20, "y": 10, "w": 10, "h": 10}]})
        region = combined.outputs["region"]
        self.assertEqual(region["shape"], "composite")
        self.assertEqual([op["op"] for op in region["ops"]], ["union", "subtract", "subtract"])
        self.assertEqual(combined.outputs["count"], 3)
        self.assertEqual({o["kind"] for o in combined.overlays}, {"rect", "circle", "contours"})
        area = int(mask_for(region, 160, 100).sum() / 255)
        self.assertEqual(area, 6000 - int(mask_for(self.HOLE, 160, 100).sum() / 255) - 100)
        # 基底走輸入埠、regions 只有一個 dict、union 模式；基底缺省時第一個 region 當基底
        uni = run_tool("region_combine", None, {"mode": "union"}, {"base": self.RECT, "regions": {"shape": "rect", "x": 200, "y": 0, "w": 10, "h": 10}})
        self.assertEqual(int(mask_for(uni.outputs["region"], 300, 100).sum() / 255), 6100)
        first = run_tool("region_combine", None, {"mode": "intersect"}, {"regions": [self.RECT, {"shape": "rect", "x": 100, "y": 50, "w": 100, "h": 100}]})
        self.assertEqual(int(mask_for(first.outputs["region"], 300, 200).sum() / 255), 400)
        # 再組合一次：composite 當基底會接續 ops，不會巢狀兩層
        again = run_tool("region_combine", None, {"mode": "subtract"}, {"base": region, "regions": [{"shape": "point", "x": 50, "y": 50}]})
        self.assertEqual(len(again.outputs["region"]["ops"]), 4)
        with self.assertRaises(ToolError):
            run_tool("region_combine", None, {}, {})
        with self.assertRaises(ToolError):
            run_tool("region_from_shape", None, {})


class ShadingTests(SimpleTestCase):
    """WP-12 平場／陰影校正：徑向漸暈校正回均勻、增益圖快取、尺寸不符訊息、暗場、背景估計、位深與彩色。"""

    @staticmethod
    def _vignette(level: float, h: int = 240, w: int = 320) -> np.ndarray:
        yy, xx = np.mgrid[0:h, 0:w]
        v = 1.0 - 0.5 * (((xx - w / 2) ** 2 + (yy - h / 2) ** 2) / ((w / 2) ** 2 + (h / 2) ** 2))
        return np.clip(v * level, 0, 255).astype(np.uint8)

    def test_flat_field_restores_uniform_image(self):
        from apps.vision.tools.builtin import preprocess as pp

        folder = temp_dir()
        flat = save_png(self._vignette(240), folder, "flat.png")
        img = self._vignette(180)
        self.assertGreater(float(img.std()), 15)
        pp._GAIN_CACHE.clear()
        r = run_tool("shading_correct", img, {"mode": "flat_field", "flat": "f"}, assets={"f": flat})
        out = r.outputs["image"]
        self.assertEqual(out.dtype, np.uint8)
        self.assertLess(float(out.std()), 1.0)  # 漸暈拿掉後回到均勻（原圖標準差 ~20）
        self.assertAlmostEqual(r.outputs["mean_after"], 180 / 240 * float(self._vignette(240).mean()), delta=1.5)
        self.assertEqual(r.detail["zero_ratio"], 0.0)
        # 增益圖快取：第二次是同一個物件
        gain_obj = next(iter(pp._GAIN_CACHE.values()))[2]
        run_tool("shading_correct", img, {"mode": "flat_field", "flat": "f"}, assets={"f": flat})
        self.assertIs(next(iter(pp._GAIN_CACHE.values()))[2], gain_obj)
        # 目標亮度：白板映到 200
        t = run_tool("shading_correct", self._vignette(240), {"mode": "flat_field", "flat": "f", "target_level": 200}, assets={"f": flat})
        self.assertAlmostEqual(t.outputs["mean_after"], 200, delta=1.0)

    def test_dark_flat_estimate_and_errors(self):
        folder = temp_dir()
        flat = save_png(self._vignette(240), folder, "flat.png")
        dark = save_png(np.full((240, 320), 12, np.uint8), folder, "dark.png")
        img = np.clip(self._vignette(180).astype(np.int32) + 12, 0, 255).astype(np.uint8)
        r = run_tool("shading_correct", img, {"mode": "dark_flat", "flat": "f", "dark": "d"}, assets={"f": flat, "d": dark})
        self.assertLess(float(r.outputs["image"].std()), 2.0)
        e = run_tool("shading_correct", self._vignette(180), {"mode": "estimate", "blur_sigma": 101})
        self.assertLess(float(e.outputs["image"].std()), 3.0)  # 原圖 σ≈20；小圖邊界外推留一點殘差
        self.assertAlmostEqual(e.outputs["mean_after"], e.outputs["mean_before"], delta=1.5)
        with self.assertRaises(ToolError) as cm:
            run_tool("shading_correct", self._vignette(180, 120, 160), {"mode": "flat_field", "flat": "f"}, assets={"f": flat})
        self.assertIn("320×240", str(cm.exception))
        self.assertIn("160×120", str(cm.exception))
        # 灰階白板套在彩色影像上：參考影像依影像通道數解碼，三通道同一組增益
        colour = run_tool("shading_correct", cv2.cvtColor(self._vignette(180), cv2.COLOR_GRAY2BGR), {"mode": "flat_field", "flat": "f"}, assets={"f": flat})
        self.assertLess(float(colour.outputs["image"].std()), 1.0)
        with self.assertRaises(ToolError):
            run_tool("shading_correct", self._vignette(180), {"mode": "flat_field"})

    def test_keeps_depth_and_colour(self):
        folder = temp_dir()
        flat_gray = save_png(self._vignette(240), folder, "flat.png")
        flat_bgr = save_png(cv2.cvtColor(self._vignette(240), cv2.COLOR_GRAY2BGR), folder, "flatc.png")
        u16 = self._vignette(180).astype(np.uint16) << 8
        r = run_tool("shading_correct", u16, {"mode": "flat_field", "flat": "f"}, assets={"f": flat_gray})
        self.assertEqual(r.outputs["image"].dtype, np.uint16)
        self.assertLess(float(r.outputs["image"].std()) / 256, 1.0)
        f32 = self._vignette(180).astype(np.float32)
        r = run_tool("shading_correct", f32, {"mode": "flat_field", "flat": "f"}, assets={"f": flat_gray})
        self.assertEqual(r.outputs["image"].dtype, np.float32)
        bgr = cv2.cvtColor(self._vignette(180), cv2.COLOR_GRAY2BGR)
        r = run_tool("shading_correct", bgr, {"mode": "flat_field", "flat": "c"}, assets={"c": flat_bgr})
        self.assertEqual(r.outputs["image"].shape, bgr.shape)
        self.assertLess(float(r.outputs["image"].std()), 1.0)


class DefectSegmentTests(SimpleTestCase):
    """一維缺陷分段的共用零件（tools/defects.py）：基線、離群、把超標的點串成區段。
    `profile_defect` 與之後沿參考幾何佈卡尺的邊緣缺陷檢測共用同一套，所以直接對函式測。"""

    def test_segments_merge_across_the_seam_only_when_wrapped(self):
        flag = np.array([True, True, False, False, True, True], dtype=bool)
        self.assertEqual(defects.segments(flag, False), [(0, 1), (4, 5)])
        # 繞一圈時頭尾相連合併成一段（end 小於 start）
        self.assertEqual(defects.segments(flag, True), [(4, 1)])
        self.assertEqual(defects.seg_len((4, 1), 6), 4)
        self.assertEqual(list(defects.seg_indices((4, 1), 6)), [4, 5, 0, 1])
        self.assertEqual(defects.segments(np.zeros(5, bool), True), [])
        self.assertEqual(defects.segments(np.ones(5, bool), True), [(0, 4)])

    def test_moving_median_skips_gaps_and_wraps(self):
        values = np.array([10.0, 10.0, np.nan, 10.0, 30.0])
        out = defects.moving_median(values, 3, wrap=False)
        self.assertAlmostEqual(out[2], 10.0)  # 中間的 NaN 由鄰居補
        self.assertTrue(np.isfinite(out).all())
        self.assertAlmostEqual(defects.moving_median(values, 3, wrap=True)[0], 10.0)

    def test_robust_outliers_uses_mad_and_ignores_gaps(self):
        values = np.array([10.0, 10.1, 9.9, 10.0, 20.0, np.nan])
        flags = defects.robust_outliers(values, 3.0)
        self.assertTrue(flags[4])
        self.assertFalse(flags[:4].any())
        self.assertFalse(flags[5])  # NaN 不算離群
        self.assertFalse(defects.robust_outliers(values, 0).any())  # 0＝不篩


class AlgorithmAccuracyTests(SimpleTestCase):
    """演算法精度：以解析式反鋸齒的合成影像（已知真值）鎖住次像素精度、部分圓弧無偏與方向慣例。"""

    @staticmethod
    def _disk(h, w, cx, cy, r, bg=40, fg=200, blur=1.0, noise=3.0, seed=0):
        # 覆蓋率 = clip(r + 0.5 − dist)；cv2.circle 實心會多含 1px 外框（半徑偏大 0.5），不能當真值
        yy, xx = np.mgrid[0:h, 0:w]
        cov = np.clip(r + 0.5 - np.hypot(xx - cx, yy - cy), 0, 1)
        img = cv2.GaussianBlur((bg + (fg - bg) * cov).astype(np.uint8), (0, 0), blur)
        rng = np.random.default_rng(seed)
        return np.clip(img.astype(np.float32) + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)

    @staticmethod
    def _scene():
        scene = np.full((400, 500), 60, np.uint8)
        cv2.rectangle(scene, (200, 150), (300, 250), 200, -1)
        cv2.circle(scene, (250, 200), 25, 40, -1)
        cv2.putText(scene, "A7", (215, 215), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 3)
        cv2.line(scene, (210, 160), (290, 240), 120, 3)
        cv2.circle(scene, (330, 200), 8, 255, -1)  # 範本外的特徵點，驗證 ROI 跟隨
        return cv2.GaussianBlur(scene, (0, 0), 0.8)

    def test_circle_fit_partial_arc_unbiased(self):
        from apps.vision.tools.builtin.locate import fit_circle_kasa, fit_circle_lsq

        rng = np.random.default_rng(1)
        th = np.radians(np.linspace(0, 60, 30))
        geo, kasa = [], []
        for _ in range(300):
            pts = np.column_stack([100 * np.cos(th), 100 * np.sin(th)]) + rng.normal(0, 0.5, (30, 2))
            geo.append(fit_circle_lsq(pts)[2] - 100)
            kasa.append(fit_circle_kasa(pts)[2] - 100)
        # 60° 短弧的半徑估計本身變異大（單次 σ≈1.5px），看的是平均偏差：幾何擬合 < 0.4px，Kåsa 平均少約 1px
        self.assertLess(abs(float(np.mean(geo))), 0.4)
        self.assertLess(abs(float(np.mean(geo))), 0.5 * abs(float(np.mean(kasa))))
        t = np.linspace(0, 2 * np.pi, 40, endpoint=False)
        cx, cy, r = fit_circle_lsq(np.column_stack([10 + 50 * np.cos(t), 20 + 50 * np.sin(t)]))
        self.assertAlmostEqual(r, 50, delta=1e-6)
        self.assertAlmostEqual(cx, 10, delta=1e-6)
        self.assertAlmostEqual(cy, 20, delta=1e-6)

    def test_find_circle_sector_roi_and_refine(self):
        img = self._disk(500, 600, 300.37, 250.61, 80.25)
        r = run_tool("find_circle", img, {"roi": {"shape": "annulus", "cx": 300, "cy": 251, "r_inner": 40, "r_outer": 130, "a0": -30, "a1": 30}, "num_rays": 60, "polarity": "light_to_dark"})
        self.assertEqual(r.branch, "found", r.message)
        pts = np.asarray(r.outputs["points"])
        ang = np.degrees(np.arctan2(pts[:, 1] - 250.61, pts[:, 0] - 300.37))
        self.assertEqual(len(pts), 60)
        self.assertTrue(np.all(np.abs(ang) <= 31), ang)
        self.assertAlmostEqual(r.outputs["r"], 80.25, delta=0.2)
        # ROI 偏心 30px：重掃後圓心誤差 < 0.1px
        r2 = run_tool("find_circle", img, {"roi": {"shape": "circle", "cx": 330, "cy": 271, "r": 150}, "polarity": "light_to_dark"})
        self.assertLess(math.hypot(r2.outputs["cx"] - 300.37, r2.outputs["cy"] - 250.61), 0.1)
        self.assertAlmostEqual(r2.outputs["r"], 80.25, delta=0.15)

    def test_fit_arc_polygon_wedge(self):
        cx, cy = 300.37, 250.61
        img = self._disk(500, 600, cx, cy, 80.25)
        wedge = [[cx, cy]] + [[cx + 130 * math.cos(math.radians(a)), cy + 130 * math.sin(math.radians(a))] for a in np.linspace(-30, 30, 7)]
        r = run_tool("fit_arc", img, {"roi": {"shape": "polygon", "points": wedge}, "num_rays": 90, "polarity": "light_to_dark"})
        self.assertEqual(r.status, "ok", r.message)
        self.assertAlmostEqual(r.outputs["radius"], 80.25, delta=0.4)
        self.assertLess(math.hypot(r.outputs["cx"] - cx, r.outputs["cy"] - cy), 0.4)
        # 不重掃：多邊形質心在工件外，掃描線斜切邊緣，誤差明顯
        r0 = run_tool("fit_arc", img, {"roi": {"shape": "polygon", "points": wedge}, "num_rays": 90, "polarity": "any", "refine": False})
        self.assertGreater(abs(r0.outputs["radius"] - 80.25), 0.8)

    def test_fit_ellipse_partial_arc(self):
        big = np.full((3200, 3200), 40, np.uint8)
        cv2.ellipse(big, ((1600.0, 1600.0), (1440.0, 960.0), 20.0), 200, -1, lineType=cv2.LINE_AA)
        img = cv2.GaussianBlur(cv2.resize(big, (400, 400), interpolation=cv2.INTER_AREA), (0, 0), 0.8)
        wedge = [[200, 200]] + [[200 + 150 * math.cos(math.radians(t)), 200 + 150 * math.sin(math.radians(t))] for t in np.linspace(-30, 70, 9)]
        r = run_tool("fit_ellipse", img, {"roi": {"shape": "polygon", "points": wedge}, "num_rays": 120, "polarity": "light_to_dark"})
        self.assertEqual(r.status, "ok", r.message)
        self.assertAlmostEqual(r.outputs["a"], 90, delta=1.0)
        self.assertAlmostEqual(r.outputs["b"], 60, delta=1.0)
        self.assertAlmostEqual(r.outputs["angle"], 20, delta=1.0)

    def test_template_match_subpixel_position_and_angle(self):
        scene = self._scene()
        assets = {"t": save_png(scene[140:260, 190:310], temp_dir(), "tpl.png")}
        for dx, dy, ang in ((0.3, -0.4, 0.0), (0.5, 0.5, 0.0), (0.25, 0.25, 7.0), (0.0, 0.0, -12.0)):
            m = cv2.getRotationMatrix2D((250, 200), -ang, 1.0)  # 畫面順時針 ang
            m[0, 2] += dx
            m[1, 2] += dy
            test = cv2.warpAffine(scene, m, (500, 400), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            for pyramid in (True, False):
                r = run_tool("template_match", test, {"template": "t", "threshold": 0.5, "angle_range": 15 if ang else 0, "angle_step": 5, "pyramid": pyramid}, assets=assets)
                self.assertEqual(r.branch, "found", r.message)
                self.assertAlmostEqual(r.outputs["best_x"], 250 + dx, delta=0.12, msg=(dx, dy, ang, pyramid))
                self.assertAlmostEqual(r.outputs["best_y"], 200 + dy, delta=0.12, msg=(dx, dy, ang, pyramid))
                self.assertAlmostEqual(r.outputs["best_angle"], ang, delta=0.6, msg=(dx, dy, ang, pyramid))
        shifted = cv2.warpAffine(scene, np.float32([[1, 0, 0.5], [0, 1, 0.5]]), (500, 400))
        r = run_tool("template_match", shifted, {"template": "t", "threshold": 0.5, "subpixel": False}, assets=assets)
        self.assertEqual(r.outputs["best_x"] % 1, 0)

    def test_locate_chain_direction(self):
        """範本比對角度（畫面順時針為正）→ 定位補正 → ROI 跟隨：跟隨 ROI 要落在旋轉後的特徵上。"""
        scene = self._scene()
        assets = {"t": save_png(scene[140:260, 190:310], temp_dir(), "tpl.png")}
        for ang in (-10.0, 10.0):
            m = cv2.getRotationMatrix2D((250, 200), ang, 1.0)  # OpenCV 正值＝畫面逆時針
            m[0, 2] += 12
            m[1, 2] += -7
            test = cv2.warpAffine(scene, m, (500, 400), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            feat = m @ np.array([330.0, 200.0, 1.0])
            r = run_tool("template_match", test, {"template": "t", "threshold": 0.5, "angle_range": 15, "angle_step": 5}, assets=assets)
            self.assertAlmostEqual(r.outputs["best_angle"], -ang, delta=0.6)
            t = run_tool("shape_align", None, {"ref_x": 250, "ref_y": 200, "ref_angle": 0}, inputs={"matches": r.outputs["matches"]}).outputs["transform"]
            moved = run_tool("fixture_roi", None, {"roi": {"shape": "circle", "cx": 330, "cy": 200, "r": 15}}, inputs={"transform": t}).outputs["region"]
            self.assertLess(math.hypot(moved["cx"] - feat[0], moved["cy"] - feat[1]), 0.5, (ang, moved, feat))

    def test_caliper_pair_polarity_and_expected_width(self):
        img = np.full((60, 220), 40, np.uint8)
        img[:, 80:100] = 140  # 低對比亮條，寬 20
        img[:, 150:152] = 255  # 高對比雜訊線
        img[:, 152:154] = 0
        img = cv2.GaussianBlur(img, (0, 0), 0.7)
        roi = {"shape": "rect", "x": 40, "y": 10, "w": 160, "h": 40}
        base = run_tool("caliper", img, {"roi": roi, "edge_pair": "strongest", "edge_threshold": 15})
        self.assertGreater(abs(base.outputs["width"] - 20), 5)  # 被雜訊邊緣搶走
        r = run_tool("caliper", img, {"roi": roi, "edge_threshold": 15, "expected_width": 20})
        self.assertAlmostEqual(r.outputs["width"], 20, delta=0.6)
        r2 = run_tool("caliper", img, {"roi": roi, "edge_threshold": 15, "pair_polarity": "bright", "edge_pair": "widest"})
        self.assertLess(r2.outputs["edge1_x"], r2.outputs["edge2_x"])
        r3 = run_tool("caliper", img, {"roi": roi, "edge_threshold": 15, "pair_polarity": "dark", "edge_pair": "narrowest"})
        self.assertAlmostEqual(r3.outputs["width"], 49.5, delta=1.0)  # 兩條亮邊之間的暗段

    def test_blob_pixel_area_small_particles(self):
        m = np.zeros((120, 200), np.uint8)
        for i, size in enumerate((1, 2, 3, 5, 9)):
            m[20 : 20 + size, 20 + i * 35 : 20 + i * 35 + size] = 255
        r = run_tool("blob", m, {"threshold_method": "none", "min_area": 0, "sort_by": "x"})
        self.assertEqual([b["area"] for b in r.outputs["blobs"]], [1.0, 4.0, 9.0, 25.0, 81.0])
        self.assertEqual(run_tool("blob", m, {"threshold_method": "none", "min_area": 4}).outputs["count"], 4)
        ring = np.zeros((100, 100), np.uint8)
        cv2.rectangle(ring, (20, 20), (79, 79), 255, -1)
        cv2.rectangle(ring, (40, 40), (59, 59), 0, -1)
        with_holes = run_tool("blob", ring, {"threshold_method": "none", "min_area": 0}).outputs["blobs"][0]["area"]
        without = run_tool("blob", ring, {"threshold_method": "none", "min_area": 0, "external_only": False}).outputs["blobs"][0]["area"]
        self.assertEqual((with_holes, without), (3600.0, 3200.0))

    def test_blob_otsu_uses_roi_mask(self):
        img = np.full((120, 120), 40, np.uint8)
        cv2.circle(img, (60, 60), 20, 90, -1)  # 低對比物件
        img[:12, :] = 255  # 白邊落在圓 ROI 外、但在外框內
        img[-12:, :] = 255
        r = run_tool("blob", img, {"roi": {"shape": "circle", "cx": 60, "cy": 60, "r": 50}, "threshold_method": "otsu", "polarity": "bright", "min_area": 50})
        self.assertEqual(r.outputs["count"], 1, r.message)
        self.assertAlmostEqual(r.outputs["blobs"][0]["area"], math.pi * 20 * 20, delta=80)

    def test_blob_separate_mixed_sizes(self):
        m = np.zeros((200, 300), np.uint8)
        cv2.circle(m, (80, 100), 40, 255, -1)
        cv2.circle(m, (200, 100), 10, 255, -1)
        cv2.circle(m, (216, 100), 10, 255, -1)
        r = run_tool("blob", m, {"threshold_method": "none", "min_area": 20, "separate": True})
        self.assertEqual(r.outputs["count"], 3, [b["area"] for b in r.outputs["blobs"]])
        bar = np.zeros((100, 200), np.uint8)
        cv2.rectangle(bar, (20, 40), (180, 60), 255, -1)
        self.assertEqual(run_tool("blob", bar, {"threshold_method": "none", "min_area": 20, "separate": True}).outputs["count"], 1)

    def test_fft_highpass_is_bipolar(self):
        step = np.full((64, 128), 50, np.uint8)
        step[:, 64:] = 200
        row = run_tool("fft_filter", step, {"mode": "highpass", "style": "truncate", "cutoff": 0.1}).outputs["image"][32].astype(int)
        self.assertLess(row[60], 128)
        self.assertGreater(row[66], 128)
        low = run_tool("fft_filter", step, {"mode": "lowpass", "cutoff": 0.3}).outputs["image"]
        self.assertLess(abs(int(low[32, 5]) - 50), 12)

    def test_color_check_hsv_gray_target(self):
        img = np.zeros((40, 40, 3), np.uint8)
        img[:] = (126, 128, 130)
        r = run_tool("color_check", img, {"color": "#808080", "space": "hsv", "tolerance": 10})
        self.assertLess(r.outputs["distance"], 5)
        self.assertTrue(r.outputs["is_match"])
        red = np.zeros((40, 40, 3), np.uint8)
        red[:] = (0, 0, 220)
        self.assertFalse(run_tool("color_check", red, {"color": "#00ff00", "space": "hsv", "tolerance": 10}).outputs["is_match"])


class ParseMessageToolTests(SimpleTestCase):
    """把一段文字拆成具名值：條碼 payload、OCR 讀到的一行、上位機送來的訊息。"""

    def _run(self, text, **params):
        params.setdefault("fields", "lot\ndate\nslot:int")
        return run_tool("parse_message", None, params, inputs={"text": text})

    def test_splits_a_barcode_payload_into_named_outputs(self):
        r = self._run("LOT12345|2026-09-08|7", separator="|")
        self.assertEqual((r.status, r.branch), ("ok", "matched"))
        self.assertEqual(r.outputs["lot"], "LOT12345")
        self.assertEqual(r.outputs["slot"], 7)
        self.assertEqual(r.outputs["count"], 3)
        self.assertEqual(r.outputs["first"], "LOT12345")
        self.assertEqual([f["name"] for f in r.outputs["fields"]], ["lot", "date", "slot"])
        # 每個欄位也進具名輸出，回覆才帶得回去
        self.assertEqual(r.context["_outputs"]["slot"], 7)

    def test_missing_fields_take_the_not_matched_branch(self):
        r = self._run("LOT9", separator="|")
        self.assertEqual((r.status, r.branch), ("ok", "not_matched"))
        self.assertIsNone(r.outputs["date"])
        self.assertEqual(r.outputs["count"], 1)
        # 要當成失敗才設 on_missing=fail
        self.assertEqual(self._run("LOT9", separator="|", on_missing="fail").status, "ng")

    def test_field_line_syntax(self):
        # 位置、倍率、位元組範圍與位元組順序
        r = run_tool("parse_message", None, {"fields": "qty:int:2"}, inputs={"text": "a,b,42"})
        self.assertEqual(r.outputs["qty"], 42)
        r = run_tool("parse_message", None, {"fields": "w:float*0.01"}, inputs={"text": "1234"})
        self.assertEqual(r.outputs["w"], 12.34)
        r = run_tool("parse_message", None, {"mode": "fixed", "fields": "id:int:0-1\ntag:string:2-3"},
                     inputs={"text": b"\x01\x02AB"})
        self.assertEqual((r.outputs["id"], r.outputs["tag"]), (258, "AB"))
        r = run_tool("parse_message", None, {"mode": "fixed", "fields": "n:int:0-1:DCBA"}, inputs={"text": b"\x02\x01"})
        self.assertEqual(r.outputs["n"], 258)

    def test_prefix_and_publish_off(self):
        r = self._run("A|B|1", separator="|", prefix="in_")
        self.assertIn("in_lot", r.context["_outputs"])
        self.assertNotIn("lot", r.context["_outputs"])
        self.assertEqual(self._run("A|B|1", separator="|", publish=False).context, {})

    def test_bad_settings_say_what_to_fix(self):
        with self.assertRaisesMessage(ToolError, "List the fields"):
            run_tool("parse_message", None, {"fields": "  "}, inputs={"text": "x"})
        with self.assertRaisesMessage(ToolError, "Connect the text"):
            run_tool("parse_message", None, {}, inputs={})
        with self.assertRaisesMessage(ToolError, "multiplier"):
            run_tool("parse_message", None, {"fields": "a*zz"}, inputs={"text": "1"})
        with self.assertRaisesMessage(ToolError, "byte range"):
            run_tool("parse_message", None, {"mode": "fixed", "fields": "a:int:x-y"}, inputs={"text": b"ab"})


class SurfaceFilterTests(SimpleTestCase):
    """表面缺陷濾波：有紋理的面上找細長刮傷。一般的邊緣濾波會把紋理一起找出來。"""

    @staticmethod
    def _surface(scratch: bool, seed: int = 5) -> np.ndarray:
        """拉絲紋理（隨機、非週期），要的話畫一道細刮傷。"""
        rng = np.random.default_rng(seed)
        base = np.full((300, 400), 175.0, np.float32) + rng.normal(0, 16, (300, 400)).astype(np.float32)
        base = cv2.GaussianBlur(base, (61, 3), 0)
        img = np.clip(base, 0, 255).astype(np.uint8)
        if scratch:
            cv2.line(img, (60, 80), (320, 200), 120, 2)
        return cv2.GaussianBlur(img, (0, 0), 0.8)

    def test_a_scratch_stands_out_and_the_grain_does_not(self):
        with_mark = run_tool("surface_filter", self._surface(True), {"polarity": "dark", "width": 3, "length": 21})
        clean = run_tool("surface_filter", self._surface(False), {"polarity": "dark", "width": 3, "length": 21})
        self.assertGreater(with_mark.outputs["max_response"], clean.outputs["max_response"] * 2)
        self.assertEqual(with_mark.outputs["image"].dtype, np.uint8)
        self.assertEqual(with_mark.outputs["image"].shape, (300, 400))

    def test_polarity_picks_the_side(self):
        bright = self._surface(False).copy()
        cv2.line(bright, (60, 80), (320, 200), 235, 2)  # 亮刮傷
        dark_side = run_tool("surface_filter", bright, {"polarity": "dark"}).outputs["max_response"]
        bright_side = run_tool("surface_filter", bright, {"polarity": "bright"}).outputs["max_response"]
        either = run_tool("surface_filter", bright, {"polarity": "any"}).outputs["max_response"]
        self.assertGreater(bright_side, dark_side)
        self.assertAlmostEqual(either, bright_side, places=3)

    def test_the_region_limits_the_work_and_the_rest_comes_through(self):
        img = self._surface(True)
        far = {"shape": "rect", "x": 0, "y": 220, "w": 120, "h": 70}  # 刮傷不在裡面
        result = run_tool("surface_filter", img, {"roi": far, "gain": 14})
        out = result.outputs["image"]
        self.assertTrue(np.array_equal(out[0:50, 300:400], img[0:50, 300:400]))  # 區域外原樣
        self.assertFalse(np.array_equal(out[230:280, 10:110], img[230:280, 10:110]))
        self.assertEqual(len(result.overlays), 1)

    def test_the_kernels_are_worked_out_once(self):
        from apps.vision.tools.builtin.preprocess import surface_kernels

        first = surface_kernels(13, 21, 8, 1.5)
        self.assertIs(surface_kernels(13, 21, 8, 1.5), first)
        self.assertEqual(len(first), 8)
        for kernel in first:
            self.assertEqual(kernel.shape, (21, 13))
            self.assertLess(abs(float(kernel.sum())), 1e-4)  # 零均值：平坦區域回 0
        self.assertEqual(len(surface_kernels(13, 21, 4, 1.5)), 4)

    def test_the_input_is_left_alone(self):
        img = self._surface(True)
        before = img.copy()
        run_tool("surface_filter", img, {})
        self.assertTrue(np.array_equal(img, before))


@override_settings(VISION={**settings.VISION, "ASSET_DIR": tempfile.mkdtemp(prefix="vs-tpl-")})
class MultiTemplateTests(SimpleTestCase):
    """一次比對好幾種模板：同一條線上兩種蓋子、同一個工件的兩種姿態。"""

    @staticmethod
    def _scene() -> np.ndarray:
        """三個方塊（上排）＋兩個圓（下排）。"""
        img = np.full((300, 500), 40, np.uint8)
        for x in (60, 200, 340):
            cv2.rectangle(img, (x, 60), (x + 40, 100), 220, -1)
        for x in (100, 300):
            cv2.circle(img, (x, 220), 22, 220, -1)
        return cv2.GaussianBlur(img, (0, 0), 0.8)

    def _run(self, image, **params):
        base = {"threshold": 0.7, "max_matches": 10}
        return run_tool("template_match", image, {**base, **params}, inputs=params.pop("_inputs", None) or {})

    def test_one_template_still_behaves_exactly_as_before(self):
        img = self._scene()
        r = run_tool("template_match", img, {"threshold": 0.7, "max_matches": 10}, inputs={"template_image": img[55:105, 55:105].copy()})
        self.assertEqual((r.branch, r.outputs["count"]), ("found", 5))   # 方塊與圓都像一個亮塊
        self.assertEqual(r.outputs["best_label"], "")
        self.assertEqual(r.outputs["counts"], [])                        # 只有一個模板就不分類

    def test_several_templates_say_which_one_matched(self):
        from apps.vision import fixed_images

        img = self._scene()
        square = fixed_images.store(img[55:105, 55:105].copy(), "square")
        circle = fixed_images.store(img[195:245, 75:125].copy(), "circle")
        r = run_tool("template_match", img, {"threshold": 0.85, "max_matches": 10, "templates": [square, circle]})
        self.assertEqual(r.branch, "found")
        labels = {m["label"] for m in r.outputs["matches"]}
        self.assertEqual(labels, {"square", "circle"})
        counts = {c["label"]: c["count"] for c in r.outputs["counts"]}
        self.assertEqual(counts["square"], 3)
        self.assertEqual(counts["circle"], 2)
        self.assertIn(r.outputs["best_label"], ("square", "circle"))

    def test_the_same_target_is_not_reported_twice(self):
        """兩個模板都認得同一個目標時，只留分數高的那一個。"""
        from apps.vision import fixed_images

        img = self._scene()
        a = fixed_images.store(img[55:105, 55:105].copy(), "a")
        b = fixed_images.store(img[56:106, 56:106].copy(), "b")   # 幾乎一樣的模板
        r = run_tool("template_match", img, {"threshold": 0.8, "max_matches": 10, "templates": [a, b]})
        centres = [(round(m["cx"]), round(m["cy"])) for m in r.outputs["matches"]]
        self.assertEqual(len(centres), len(set(centres)))
        self.assertLessEqual(r.outputs["count"], 5)

    def test_the_order_of_the_matches_can_be_chosen(self):
        img = self._scene()
        tpl = img[55:105, 55:105].copy()

        def centres(mode):
            r = run_tool("template_match", img, {"threshold": 0.7, "max_matches": 10, "sort_by": mode}, inputs={"template_image": tpl})
            return [(round(m["cx"]), round(m["cy"])) for m in r.outputs["matches"]]

        self.assertEqual(centres("x"), sorted(centres("x")))                       # 由左到右
        self.assertEqual([c[1] for c in centres("y")], sorted(c[1] for c in centres("y")))
        reading = centres("xy")
        self.assertEqual(reading[:3], [(80, 80), (220, 80), (360, 80)])            # 先上排、再由左到右
        self.assertEqual(reading[3:], [(100, 220), (300, 220)])
        self.assertEqual(centres("score")[0], (80, 80))

    def test_the_template_can_be_stretched(self):
        img = self._scene()
        tpl = img[55:105, 55:105].copy()
        self.assertEqual(run_tool("template_match", img, {"threshold": 0.7, "max_matches": 10, "scale_x": 1.5},
                                  inputs={"template_image": tpl}).outputs["count"], 0)
        wide = np.full((300, 500), 40, np.uint8)
        cv2.rectangle(wide, (60, 60), (120, 100), 220, -1)        # 寬了 1.5 倍的方塊
        wide = cv2.GaussianBlur(wide, (0, 0), 0.8)
        r = run_tool("template_match", wide, {"threshold": 0.6, "max_matches": 5, "scale_x": 1.5}, inputs={"template_image": tpl})
        self.assertEqual(r.branch, "found")

    def test_a_part_running_off_the_edge_can_still_be_found(self):
        img = np.full((200, 200), 40, np.uint8)
        cv2.rectangle(img, (150, 80), (230, 120), 220, -1)        # 右邊被切掉一半
        img = cv2.GaussianBlur(img, (0, 0), 0.8)
        tpl = np.full((50, 90), 40, np.uint8)
        cv2.rectangle(tpl, (5, 5), (85, 45), 220, -1)
        tpl = cv2.GaussianBlur(tpl, (0, 0), 0.8)
        # 被切掉的工件分數本來就低（模板有一截對不到），所以門檻要放寬一點
        plain = run_tool("template_match", img, {"threshold": 0.6, "max_matches": 3}, inputs={"template_image": tpl})
        clipped = run_tool("template_match", img, {"threshold": 0.6, "max_matches": 3, "allow_clipped": True}, inputs={"template_image": tpl})
        self.assertEqual(plain.outputs["count"], 0)
        self.assertEqual(clipped.branch, "found")
        self.assertGreater(clipped.outputs["best_x"], 150)
        self.assertGreater(clipped.outputs["best_score"], 0.6)

    def test_a_time_limit_returns_what_it_has(self):
        img = self._scene()
        tpl = img[55:105, 55:105].copy()
        params = {"threshold": 0.7, "max_matches": 10, "angle_range": 30, "angle_step": 1, "pyramid": False}
        full = run_tool("template_match", img, params, inputs={"template_image": tpl})
        quick = run_tool("template_match", img, {**params, "timeout_ms": 1}, inputs={"template_image": tpl})
        self.assertEqual(full.branch, "found")
        self.assertEqual(quick.branch, "found")          # 有結果就回結果，不是失敗
        self.assertLessEqual(quick.outputs["count"], full.outputs["count"])

    def test_no_template_at_all_says_so(self):
        with self.assertRaises(ToolError):
            run_tool("template_match", self._scene(), {})


class EdgeDefectTests(SimpleTestCase):
    """沿一條邊找缺陷並分類：缺口、斷裂、階差、寬度不對。"""

    LINE_ROI = {"shape": "rect", "x": 20, "y": 130, "w": 360, "h": 40}
    DISC_ROI = {"shape": "circle", "cx": 200, "cy": 200, "r": 120}

    @staticmethod
    def _edge(notch=None, step=0):
        """上暗下亮，交界在 y=150。notch=(x0, x1, deep) 挖一個缺口；step 讓右半邊整個上下位移。"""
        img = np.full((300, 400), 40, np.uint8)
        img[150:, :] = 210
        if step:
            img[150:, 200:] = 40
            img[150 + step:, 200:] = 210
        if notch:
            x0, x1, deep = notch
            cv2.rectangle(img, (x0, 150), (x1, 150 + deep), 40, -1)
        return cv2.GaussianBlur(img, (0, 0), 0.8)

    @staticmethod
    def _disc(gap=None):
        """亮圓盤 r=120；gap=(起, 迄) 度數的缺口。"""
        img = np.zeros((400, 400), np.uint8)
        cv2.circle(img, (200, 200), 120, 220, -1)
        if gap:
            cv2.ellipse(img, (200, 200), (120, 120), 0, gap[0], gap[1], 0, -1)
        return cv2.GaussianBlur(img, (0, 0), 0.8)

    def _run(self, image, **params):
        base = {"roi": self.LINE_ROI, "polarity": "dark_to_light", "calipers": 80, "search": 18, "threshold": 2.0}
        return run_tool("edge_defect", image, {**base, **params})

    def test_a_clean_edge_is_clean(self):
        r = self._run(self._edge())
        self.assertEqual((r.branch, r.status), ("ok", "ok"))
        self.assertEqual(r.outputs["count"], 0)
        self.assertEqual(len(r.outputs["points"]), 80)
        self.assertIn("80/80", r.message)

    def test_a_notch_is_one_fault_with_a_box_and_a_length(self):
        r = self._run(self._edge(notch=(180, 200, 6)))
        self.assertEqual((r.branch, r.status), ("defect", "ng"))
        self.assertEqual(r.outputs["count"], 1)
        fault = r.outputs["defects"][0]
        self.assertEqual(fault["type"], "dislocation")
        self.assertGreater(abs(fault["peak"]), 4.0)          # 缺口 6 px 深
        self.assertGreater(fault["size"], 8.0)               # 沿邊長度（缺口 20 px 寬）
        self.assertLess(fault["size"], 40.0)
        self.assertEqual(fault["rect"]["shape"], "rotated_rect")
        self.assertGreater(fault["area"], 0)
        self.assertAlmostEqual(r.outputs["max_size"], fault["size"], places=3)

    def test_which_side_counts_can_be_narrowed(self):
        img = self._edge(notch=(180, 200, 6))
        both = self._run(img, direction="both").outputs["count"]
        self.assertEqual(both, 1)
        # 這個缺口讓邊往掃描方向（下）移動，所以只看反向就找不到
        one_way = self._run(img, direction="inward").outputs["count"]
        other_way = self._run(img, direction="outward").outputs["count"]
        self.assertEqual(sorted([one_way, other_way]), [0, 1])

    def test_single_caliper_noise_is_not_a_fault(self):
        img = self._edge(notch=(198, 201, 5))   # 只有兩三把卡尺打得到
        self.assertEqual(self._run(img, min_width=6).outputs["count"], 0)
        self.assertGreaterEqual(self._run(img, min_width=1).outputs["count"], 1)

    def test_a_gap_in_a_round_edge_is_a_break(self):
        r = run_tool("edge_defect", self._disc(gap=(20, 35)),
                     {"roi": self.DISC_ROI, "polarity": "light_to_dark", "calipers": 180, "search": 25, "threshold": 2.5})
        self.assertEqual((r.branch, r.status), ("defect", "ng"))
        self.assertEqual(r.outputs["count"], 1)
        fault = r.outputs["defects"][0]
        self.assertEqual(fault["type"], "fracture")
        self.assertEqual(fault["direction"], "missing")
        self.assertGreater(fault["count"], 4)                 # 15° 的缺口 ≈ 180 把裡的 7~8 把
        self.assertLess(abs(fault["position"] - 20), 4)       # 位置是角度（度）
        clean = run_tool("edge_defect", self._disc(),
                         {"roi": self.DISC_ROI, "polarity": "light_to_dark", "calipers": 180, "search": 25, "threshold": 2.5})
        self.assertEqual((clean.branch, clean.outputs["count"]), ("ok", 0))

    def test_a_break_can_be_switched_off(self):
        params = {"roi": self.DISC_ROI, "polarity": "light_to_dark", "calipers": 180, "search": 25, "threshold": 2.5}
        with_break = run_tool("edge_defect", self._disc(gap=(20, 35)), params)
        without = run_tool("edge_defect", self._disc(gap=(20, 35)), {**params, "fracture_run": 0})
        self.assertEqual(with_break.outputs["count"], 1)
        self.assertEqual(without.outputs["count"], 0)  # 打空不算缺陷了，剩下的都在門檻內

    def test_a_step_between_neighbours_is_its_own_kind(self):
        img = self._edge(step=8)
        # 只看階差：整段偏移的門檻關掉
        r = self._run(img, threshold=0, step_threshold=4)
        self.assertEqual(r.outputs["count"], 1)
        self.assertEqual(r.outputs["defects"][0]["type"], "step")
        self.assertEqual(self._run(img, threshold=0, step_threshold=0).outputs["count"], 0)

    def test_a_pair_of_edges_checks_the_width(self):
        band = np.full((200, 400), 30, np.uint8)
        band[90:130, :] = 200
        band[90:110, 200:260] = 30                  # 這一段只剩一半寬
        band = cv2.GaussianBlur(band, (0, 0), 0.8)
        r = run_tool("edge_defect", band, {"roi": {"shape": "rect", "x": 10, "y": 70, "w": 380, "h": 80}, "mode": "pair",
                                           "pair_polarity": "bright", "calipers": 60, "search": 60, "threshold": 0, "width_min": 35})
        self.assertEqual(r.outputs["count"], 1)
        self.assertEqual(r.outputs["defects"][0]["type"], "width")
        widths = [w for w in r.outputs["widths"] if w]
        self.assertEqual(len(widths), 60)
        self.assertLess(abs(max(widths) - 40.0), 0.3)

    def test_a_missing_band_is_a_break_not_a_width_fault(self):
        band = np.full((200, 400), 30, np.uint8)
        band[90:130, :] = 200
        band[90:130, 200:240] = 30                  # 整段不見了
        band = cv2.GaussianBlur(band, (0, 0), 0.8)
        r = run_tool("edge_defect", band, {"roi": {"shape": "rect", "x": 10, "y": 70, "w": 380, "h": 80}, "mode": "pair",
                                           "pair_polarity": "bright", "calipers": 60, "search": 60, "threshold": 3})
        self.assertEqual(r.outputs["count"], 1)
        self.assertEqual(r.outputs["defects"][0]["type"], "fracture")

    def test_the_ideal_edge_can_come_from_the_step_before(self):
        """接上游找圓的結果：理想邊是這一顆工件實際的圓，不是教導時畫的位置。"""
        img = self._disc(gap=(20, 35))
        circle = run_tool("find_circle", img, {"roi": {"shape": "annulus", "cx": 205, "cy": 195, "r_inner": 90, "r_outer": 150},
                                               "polarity": "light_to_dark", "num_rays": 72})
        self.assertIsNotNone(circle.outputs["circle"])
        r = run_tool("edge_defect", img, {"calipers": 180, "search": 25, "polarity": "light_to_dark", "threshold": 2.5},
                     inputs={"circle": circle.outputs["circle"]})
        self.assertEqual(r.outputs["count"], 1)
        self.assertEqual(r.outputs["defects"][0]["type"], "fracture")

    def test_the_settings_have_to_make_sense(self):
        with self.assertRaisesMessage(ToolError, "Draw a region"):
            run_tool("edge_defect", self._edge(), {})
        with self.assertRaisesMessage(ToolError, "rectangle"):
            run_tool("edge_defect", self._edge(), {"roi": {"shape": "polygon", "points": [[0, 0], [10, 0], [10, 10]]}})

    def test_how_many_faults_are_allowed(self):
        img = self._edge(notch=(120, 140, 6))
        cv2.rectangle(img, (260, 150), (280, 156), 40, -1)
        img = cv2.GaussianBlur(img, (0, 0), 0.8)
        two = self._run(img)
        self.assertEqual(two.outputs["count"], 2)
        self.assertEqual(two.branch, "defect")
        self.assertEqual(self._run(img, max_defects=2).branch, "ok")   # 兩個以內可以接受
        self.assertEqual(self._run(img, max_defects=1).branch, "defect")

    def test_the_step_helper_marks_both_sides_of_a_jump(self):
        from apps.vision.tools.builtin.edge_defect import step_flags

        values = np.array([0.0, 0.1, 0.0, 5.0, 5.1, 5.0])
        flags = step_flags(values, 2.0)
        self.assertEqual(list(flags), [False, False, True, True, False, False])
        self.assertFalse(step_flags(values, 0).any())
        self.assertFalse(step_flags(np.array([1.0]), 1.0).any())


class GeometryFinderTests(SimpleTestCase):
    """幾何查找家族：矩形、平行邊、多條線、圓陣列。真值用平台自己的 `mask_for` 畫，避免混進別套角度慣例。"""

    @staticmethod
    def _shape(region, size=(400, 500), fg=210, bg=40, blur=1.0):
        from apps.vision.tools.roi import mask_for

        h, w = size
        mask = mask_for(region, w, h)
        return cv2.GaussianBlur(np.where(mask > 0, fg, bg).astype(np.uint8), (0, 0), blur)

    def test_a_rectangle_comes_back_with_its_size_and_angle(self):
        truth = {"shape": "rotated_rect", "cx": 250.0, "cy": 180.0, "w": 200.0, "h": 120.0, "angle": 12.0}
        img = self._shape(truth)
        r = run_tool("find_rectangle", img, {"roi": {"shape": "rotated_rect", "cx": 250, "cy": 180, "w": 260, "h": 190, "angle": 12},
                                             "polarity": "dark_to_light"})
        self.assertEqual(r.branch, "found")
        self.assertLess(abs(r.outputs["width"] - 200.0), 1.0, r.outputs["width"])
        self.assertLess(abs(r.outputs["height"] - 120.0), 1.0, r.outputs["height"])
        self.assertLess(abs(r.outputs["angle"] - 12.0), 0.5, r.outputs["angle"])
        self.assertLess(math.hypot(r.outputs["cx"] - 250, r.outputs["cy"] - 180), 0.5)
        self.assertEqual(len(r.outputs["corners"]), 4)
        self.assertEqual(r.outputs["rect"]["shape"], "rotated_rect")  # 直接餵給下游當 ROI

    def test_a_rectangle_that_is_not_there_takes_the_other_branch(self):
        flat = np.full((300, 300), 128, np.uint8)
        r = run_tool("find_rectangle", flat, {"roi": {"shape": "rect", "x": 20, "y": 20, "w": 260, "h": 260}})
        self.assertEqual((r.branch, r.status), ("not_found", "ng"))
        self.assertTrue(math.isnan(r.outputs["width"]))

    def test_the_corners_come_out_clockwise_from_the_top_left(self):
        truth = {"shape": "rect", "x": 150.0, "y": 120.0, "w": 200.0, "h": 120.0}
        r = run_tool("find_rectangle", self._shape(truth), {"roi": {"shape": "rect", "x": 120, "y": 90, "w": 260, "h": 180},
                                                            "polarity": "dark_to_light"})
        corners = r.outputs["corners"]
        self.assertLess(corners[0][0], corners[1][0])   # 左上在右上的左邊
        self.assertLess(corners[0][1], corners[3][1])   # 左上在左下的上面
        self.assertLess(corners[1][1], corners[2][1])   # 右上在右下的上面

    def test_a_pair_of_edges_gives_the_width_and_the_centre_line(self):
        band = np.full((300, 400), 30, np.uint8)
        band[130:170, :] = 200
        band = cv2.GaussianBlur(band, (0, 0), 0.8)
        r = run_tool("find_parallel_lines", band, {"roi": {"shape": "rect", "x": 50, "y": 100, "w": 300, "h": 100},
                                                   "pair_polarity": "bright", "pair_mode": "widest"})
        self.assertEqual(r.branch, "found")
        self.assertLess(abs(r.outputs["distance"] - 40.0), 0.3, r.outputs["distance"])
        self.assertEqual(r.outputs["found_count"], 20)
        self.assertLess(abs(r.outputs["angle"]), 0.2)
        self.assertLess(abs(r.outputs["center_line"]["y1"] - 149.5), 0.3)  # 亮帶是第 130~169 列，中心在 149.5
        self.assertEqual(len(r.outputs["widths"]), 20)

    def test_a_pair_that_is_not_there_takes_the_other_branch(self):
        r = run_tool("find_parallel_lines", np.full((200, 200), 100, np.uint8), {"roi": {"shape": "rect", "x": 20, "y": 20, "w": 160, "h": 100}})
        self.assertEqual((r.branch, r.status), ("not_found", "ng"))

    def test_several_lines_come_back_with_their_angles(self):
        img = np.full((300, 400), 30, np.uint8)
        cv2.line(img, (20, 60), (380, 60), 220, 5)
        cv2.line(img, (60, 20), (60, 280), 220, 5)
        r = run_tool("find_lines_multi", img, {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 400, "h": 300},
                                               "max_lines": 6, "min_points": 60})
        self.assertEqual(r.branch, "found")
        angles = [abs(a) for a in r.outputs["angles"]]
        self.assertTrue(any(a < 2 for a in angles), angles)        # 水平那條
        self.assertTrue(any(a > 88 for a in angles), angles)       # 垂直那條
        self.assertGreaterEqual(r.outputs["count"], 2)
        self.assertIn("angle", r.outputs["first"])

    def test_lines_can_be_filtered_by_angle(self):
        img = np.full((300, 400), 30, np.uint8)
        cv2.line(img, (20, 60), (380, 60), 220, 5)
        cv2.line(img, (60, 20), (60, 280), 220, 5)
        r = run_tool("find_lines_multi", img, {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 400, "h": 300},
                                               "max_lines": 6, "min_points": 60, "angle_filter": 0, "angle_tolerance": 5})
        self.assertTrue(all(abs(a) <= 5 for a in r.outputs["angles"]), r.outputs["angles"])
        empty = run_tool("find_lines_multi", np.full((200, 200), 90, np.uint8), {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 200, "h": 200}})
        self.assertEqual((empty.branch, empty.status), ("not_found", "ng"))

    def test_a_grid_of_circles_reports_the_missing_ones(self):
        grid = np.full((300, 300), 220, np.uint8)
        holes = [(r_, c_) for r_ in range(3) for c_ in range(3) if (r_, c_) != (1, 1)]
        for r_, c_ in holes:
            cv2.circle(grid, (50 + c_ * 100, 50 + r_ * 100), 22, 40, -1)
        grid = cv2.GaussianBlur(grid, (0, 0), 0.8)
        params = {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 300, "h": 300}, "rows": 3, "cols": 3, "polarity": "dark_to_light"}
        r = run_tool("find_circles_matrix", grid, params)
        self.assertEqual((r.outputs["count"], r.outputs["expected"]), (8, 9))
        self.assertEqual(r.outputs["missing"], [4])          # 中央那一格是空的
        self.assertEqual((r.branch, r.status), ("not_found", "ng"))
        self.assertLess(abs(r.outputs["mean_radius"] - 22.0), 0.6, r.outputs["mean_radius"])
        self.assertEqual((r.outputs["pitch_x"], r.outputs["pitch_y"]), (100.0, 100.0))
        full = grid.copy()
        cv2.circle(full, (150, 150), 22, 40, -1)
        r2 = run_tool("find_circles_matrix", cv2.GaussianBlur(full, (0, 0), 0.8), params)
        self.assertEqual((r2.outputs["count"], r2.branch, r2.status), (9, "found", "ok"))

    def test_four_edges_become_four_corners(self):
        def line(x1, y1, x2, y2):
            return {"x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2)}

        r = run_tool("find_quadrilateral", None, {}, inputs={
            "a": line(0, 0, 100, 0), "b": line(100, 0, 100, 80), "c": line(100, 80, 0, 80), "d": line(0, 80, 0, 0)})
        self.assertEqual(r.branch, "found")
        self.assertEqual(r.outputs["corners"], [[100.0, 0.0], [100.0, 80.0], [0.0, 80.0], [0.0, 0.0]])
        self.assertEqual(r.outputs["sides"], [80.0, 100.0, 80.0, 100.0])
        self.assertEqual(r.outputs["area"], 8000.0)
        with self.assertRaisesMessage(ToolError, "Edge C"):
            run_tool("find_quadrilateral", None, {}, inputs={"a": line(0, 0, 1, 0), "b": line(1, 0, 1, 1), "d": line(0, 1, 0, 0)})
        parallel = run_tool("find_quadrilateral", None, {}, inputs={
            "a": line(0, 0, 100, 0), "b": line(0, 10, 100, 10), "c": line(100, 80, 0, 80), "d": line(0, 80, 0, 0)})
        self.assertEqual(parallel.branch, "not_found")

    def test_a_broken_edge_can_report_its_real_extent(self):
        img = np.full((200, 400), 30, np.uint8)
        for x in range(40, 360, 40):
            cv2.line(img, (x, 100), (x + 20, 100), 220, 3)
        img = cv2.GaussianBlur(img, (0, 0), 0.8)
        roi = {"shape": "rect", "x": 20, "y": 80, "w": 360, "h": 40}
        plain = run_tool("find_line", img, {"roi": roi, "polarity": "dark_to_light", "num_calipers": 30})
        gappy = run_tool("find_line", img, {"roi": roi, "polarity": "dark_to_light", "num_calipers": 30, "gap_tolerant": True})
        self.assertEqual((plain.branch, gappy.branch), ("found", "found"))
        self.assertLess(plain.outputs["coverage"], 0.8)          # 虛線只有部分卡尺打得到
        self.assertAlmostEqual(plain.outputs["x1"], 20.0, places=2)  # 一般模式：端點是 ROI 的兩端
        self.assertGreater(gappy.outputs["x1"], 30.0)            # 斷續模式：端點是真的找到邊的範圍
        self.assertLess(gappy.outputs["x2"], 350.0)
        self.assertLess(abs(gappy.outputs["angle"]), 0.2)


class GeometryConstructionTests(SimpleTestCase):
    """幾何作圖：圖面標的是「兩邊的中線」「孔到基準線的距離」，影像上沒有那條線，要算出來。"""

    H0 = {"x1": 0.0, "y1": 0.0, "x2": 100.0, "y2": 0.0}      # y=0 的水平線
    H20 = {"x1": 0.0, "y1": 20.0, "x2": 100.0, "y2": 20.0}   # y=20 的水平線
    V50 = {"x1": 50.0, "y1": -50.0, "x2": 50.0, "y2": 50.0}  # x=50 的垂直線

    def _geo(self, mode, **kw):
        params = {"mode": mode}
        for key in ("offset", "angle"):
            if key in kw:
                params[key] = kw.pop(key)
        return run_tool("geometry", None, params, inputs=kw)

    @staticmethod
    def _on_line(line, x, y, tol=1e-6):
        """(x, y) 在這條線上嗎（垂距 < tol）。"""
        from apps.vision.tools.builtin.measure import point_to_line

        return point_to_line((x, y), (line["x1"], line["y1"], line["x2"], line["y2"]))[2] < tol

    def test_where_two_lines_meet_and_at_what_angle(self):
        r = self._geo("intersect", a=self.H0, b=self.V50)
        self.assertEqual((round(r.outputs["x"]), round(r.outputs["y"])), (50, 0))
        self.assertAlmostEqual(r.outputs["angle"], 90.0, places=3)
        self.assertEqual(self._geo("intersect", a=self.H0, b=self.H20).status, "ng")  # 平行線不會相交

    def test_the_line_halfway_between_two_edges(self):
        line = self._geo("median", a=self.H0, b=self.H20).outputs["line"]
        self.assertTrue(self._on_line(line, 0, 10))
        self.assertTrue(self._on_line(line, 100, 10))

    def test_the_line_that_halves_a_corner(self):
        line = self._geo("bisector", a=self.H0, b=self.V50).outputs["line"]
        self.assertTrue(self._on_line(line, 50, 0))       # 過交點
        self.assertTrue(self._on_line(line, 60, 10))      # 45°

    def test_parallel_by_offset_or_through_a_point(self):
        shifted = self._geo("parallel", a=self.H0, offset=15).outputs["line"]
        self.assertTrue(self._on_line(shifted, 0, 15))
        through = self._geo("parallel", a=self.H0, b=[10.0, 30.0]).outputs["line"]
        self.assertTrue(self._on_line(through, 999, 30))

    def test_perpendicular_and_the_halfway_line_between_two_points(self):
        perp = self._geo("perpendicular", a=self.H0, b=[25.0, 0.0]).outputs["line"]
        self.assertTrue(self._on_line(perp, 25, 999))
        with self.assertRaises(ToolError):
            self._geo("perpendicular", a=self.H0)  # 沒給要過的點
        half = self._geo("perp_bisector", a=[0.0, 0.0], b=[10.0, 10.0]).outputs["line"]
        self.assertTrue(self._on_line(half, 5, 5))
        self.assertTrue(self._on_line(half, 10, 0))

    def test_the_circle_through_three_points(self):
        circle = self._geo("circle_3pts", a=[0.0, 0.0], b=[10.0, 0.0], c=[5.0, 5.0]).outputs["circle"]
        self.assertEqual((circle["cx"], circle["cy"], circle["r"]), (5.0, 0.0, 5.0))
        with self.assertRaisesMessage(ToolError, "on one line"):
            self._geo("circle_3pts", a=[0.0, 0.0], b=[5.0, 0.0], c=[10.0, 0.0])

    def test_turning_a_point_is_clockwise_like_every_other_angle(self):
        r = self._geo("rotate", a=[10.0, 0.0], b=[0.0, 0.0], angle=90)
        self.assertEqual((round(r.outputs["x"], 6), round(r.outputs["y"], 6)), (0.0, 10.0))

    def test_a_line_through_two_points_reports_its_angle(self):
        r = self._geo("line_2pts", a=[0.0, 0.0], b=[10.0, 10.0])
        self.assertAlmostEqual(r.outputs["angle"], 45.0, places=3)
        self.assertAlmostEqual(r.outputs["distance"], 14.142, places=2)

    def test_the_wrong_kind_of_input_says_which_one(self):
        with self.assertRaisesMessage(ToolError, "Input B"):
            self._geo("intersect", a=self.H0, b=[1.0, 2.0])
        with self.assertRaisesMessage(ToolError, "Input A"):
            self._geo("circle_3pts", a=self.H0, b=[1.0, 2.0], c=[3.0, 4.0])


class ShapeDistanceTests(SimpleTestCase):
    """圖面標的常常是「孔邊到邊」而不是「圓心到圓心」。"""

    C0 = {"cx": 0.0, "cy": 0.0, "r": 5.0}
    C30 = {"cx": 30.0, "cy": 0.0, "r": 5.0}
    LINE = {"x1": 0.0, "y1": 20.0, "x2": 100.0, "y2": 20.0}

    def _d(self, mode, **kw):
        return round(run_tool("distance", None, {"mode": mode}, inputs=kw).outputs["distance"], 4)

    def test_two_circles(self):
        self.assertEqual(self._d("centers", a=self.C0, b=self.C30), 30.0)
        self.assertEqual(self._d("nearest", a=self.C0, b=self.C30), 20.0)
        self.assertEqual(self._d("farthest", a=self.C0, b=self.C30), 40.0)

    def test_a_circle_and_a_line_or_a_point(self):
        self.assertEqual(self._d("nearest", a=self.C0, b=self.LINE), 15.0)
        self.assertEqual(self._d("centers", a=self.C0, b=self.LINE), 20.0)
        self.assertEqual(self._d("nearest", a=self.C0, b=[0.0, 40.0]), 35.0)
        self.assertEqual(self._d("farthest", a=self.C0, b=[0.0, 40.0]), 45.0)
        self.assertEqual(self._d("nearest", a=[0.0, 40.0], b=self.C0), 35.0)  # 接反了也一樣

    def test_a_point_and_a_line(self):
        self.assertEqual(self._d("nearest", a=self.LINE, b=[0.0, 40.0]), 20.0)
        self.assertEqual(self._d("euclid", a=[10.0, 0.0], b=self.LINE), 20.0)

    def test_two_points_are_unchanged(self):
        self.assertEqual(self._d("euclid", a=[0.0, 0.0], b=[3.0, 4.0]), 5.0)
        self.assertEqual(self._d("dx", a=[0.0, 0.0], b=[3.0, 4.0]), 3.0)


class PointSetTests(SimpleTestCase):
    """把幾個步驟找到的點併成一組，一次擬合。"""

    def test_points_come_together_with_a_centre(self):
        r = run_tool("points_merge", None, {}, inputs={"a": [1.0, 2.0], "b": [[3.0, 4.0], [5.0, 6.0]], "c": {"x": 7.0, "y": 8.0}})
        self.assertEqual(r.outputs["count"], 4)
        self.assertEqual(r.outputs["points"][0], [1.0, 2.0])
        self.assertEqual((r.outputs["cx"], r.outputs["cy"]), (4.0, 5.0))

    def test_repeats_can_be_dropped_and_nothing_is_ng(self):
        self.assertEqual(run_tool("points_merge", None, {"unique": True}, inputs={"a": [[1.0, 1.0], [1.0, 1.0], [2.0, 2.0]]}).outputs["count"], 2)
        self.assertEqual(run_tool("points_merge", None, {}, inputs={}).status, "ng")

    def test_a_drawn_shape_feeds_the_geometry_steps(self):
        """畫布上畫一條基準線，就能量每個孔到它的距離——那條線是圖面給的，影像上找不到。"""
        line = run_tool("region_from_shape", None, {"roi": {"shape": "line", "x1": 0.0, "y1": 0.0, "x2": 10.0, "y2": 0.0}})
        self.assertEqual(line.outputs["line"], {"x1": 0.0, "y1": 0.0, "x2": 10.0, "y2": 0.0})
        self.assertEqual(line.outputs["point"], [5.0, 0.0])
        circle = run_tool("region_from_shape", None, {"roi": {"shape": "circle", "cx": 5.0, "cy": 5.0, "r": 3.0}})
        self.assertEqual(circle.outputs["circle"], {"cx": 5.0, "cy": 5.0, "r": 3.0})
        self.assertIsNone(run_tool("region_from_shape", None, {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 4, "h": 4}}).outputs["line"])


class CaliperSeriesTests(SimpleTestCase):
    """通用卡尺序列（locate.caliper_series）：沿直線／圓弧等距佈卡尺，單邊或邊緣對，回全圖座標。
    這是幾何查找家族與邊緣缺陷家族共用的原語，所以直接對它測精度與慣例。"""

    @staticmethod
    def _edge_image(h=300, w=400, x_edge=180.5, bg=40, fg=200, blur=1.0, noise=2.0, seed=3):
        """垂直的亮暗交界：覆蓋率反鋸齒，邊在 x_edge（次像素真值）。"""
        xx = np.tile(np.arange(w, dtype=np.float64), (h, 1))
        cov = np.clip(xx - x_edge + 0.5, 0, 1)
        img = cv2.GaussianBlur((bg + (fg - bg) * cov).astype(np.uint8), (0, 0), blur)
        rng = np.random.default_rng(seed)
        return np.clip(img.astype(np.float32) + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)

    def test_line_calipers_hit_a_known_edge_to_sub_pixel(self):
        from apps.vision.tools.builtin.locate import caliper_series, line_geometry

        img = self._edge_image(x_edge=180.5)
        # 掃描方向＝線方向順時針轉 90°：線由下往上（0,−1）→ 掃描往 +x。中心在 x=180，搜尋 ±20
        centers, scan, tang, pos = line_geometry(180, 280, 180, 20, 24)
        self.assertAlmostEqual(float(scan[0][0]), 1.0, places=6)
        self.assertAlmostEqual(float(scan[0][1]), 0.0, places=6)
        hits = caliper_series(img, centers, scan, tang, pos, search=40, height=5, polarity="dark_to_light", threshold=15)
        self.assertEqual(len(hits), 24)
        self.assertTrue(all(h.found for h in hits))
        xs = np.array([h.x for h in hits])
        self.assertLess(abs(xs.mean() - 180.5), 0.2, xs.mean())
        self.assertLess(xs.std(), 0.15, xs.std())
        # position 是離起點的弧長，第一把 0、最後一把＝線長
        self.assertAlmostEqual(hits[0].position, 0.0, places=6)
        self.assertAlmostEqual(hits[-1].position, 260.0, places=6)
        # offset 是相對卡尺中線的位移（掃描方向為正）：中心在 180、邊在 180.5
        self.assertLess(abs(np.mean([h.offset for h in hits]) - 0.5), 0.2)
        # 反向極性找不到 → 照樣回傳，found=False（打空是缺陷訊號，不能被濾掉）
        blind = caliper_series(img, centers, scan, tang, pos, search=40, height=5, polarity="light_to_dark", threshold=15)
        self.assertEqual(len(blind), 24)
        self.assertFalse(any(h.found for h in blind))
        self.assertTrue(all(math.isnan(h.x) for h in blind))

    def test_arc_calipers_recover_the_radius(self):
        from apps.vision.tools.builtin.locate import arc_geometry, caliper_series, fit_circle_lsq, hit_points

        img = AlgorithmAccuracyTests._disk(400, 400, 200.0, 200.0, 80.0)
        centers, scan, tang, pos = arc_geometry(200, 200, 80, 90)
        hits = caliper_series(img, centers, scan, tang, pos, search=30, height=3, polarity="light_to_dark", threshold=10, select="strongest")
        self.assertGreater(sum(h.found for h in hits), 85)
        radii = np.array([math.hypot(h.x - 200, h.y - 200) for h in hits if h.found])
        self.assertLess(abs(radii.mean() - 80.0), 0.2, radii.mean())
        cx, cy, r = fit_circle_lsq(np.array(hit_points(hits)))
        self.assertLess(abs(r - 80.0), 0.2)
        self.assertLess(math.hypot(cx - 200, cy - 200), 0.2)
        # position 是角度（度，畫面順時針為正）
        self.assertAlmostEqual(hits[0].position, 0.0, places=6)
        self.assertAlmostEqual(hits[10].position, 40.0, places=4)  # 90 把繞一圈，每把 4°（角度用 float32 取樣）

    def test_pair_mode_measures_a_band_width(self):
        from apps.vision.tools.builtin.locate import caliper_series, line_geometry

        img = np.full((200, 300), 40, np.uint8)
        img[:, 100:130] = 200  # 30 px 寬的亮帶
        img = cv2.GaussianBlur(img, (0, 0), 0.8)
        centers, scan, tang, pos = line_geometry(115, 40, 115, 160, 12)
        hits = caliper_series(img, centers, scan, tang, pos, search=80, height=3, mode="pair",
                              pair_mode="widest", pair_polarity="bright", threshold=15)
        self.assertTrue(all(h.found for h in hits))
        widths = np.array([h.width for h in hits])
        self.assertLess(abs(widths.mean() - 30.0), 0.3, widths.mean())
        self.assertLess(widths.std(), 0.1)
        # 兩個邊都是全圖座標，依掃描方向排；這條線（由上往下）往 −x 掃，所以先遇到右邊那條
        self.assertAlmostEqual(float(scan[0][0]), -1.0, places=6)
        self.assertEqual({round(hits[0].x, 1), round(hits[0].x2, 1)}, {129.5, 99.5})
        self.assertGreater(hits[0].x, hits[0].x2)

    def test_series_and_missing_calipers_feed_the_defect_helpers(self):
        from apps.vision.tools.builtin.locate import arc_geometry, caliper_series, hit_series

        img = AlgorithmAccuracyTests._disk(400, 400, 200.0, 200.0, 80.0)
        cv2.ellipse(img, (200, 200), (80, 80), 0, 20, 40, 40, -1)  # 一段缺口
        img = cv2.GaussianBlur(img, (0, 0), 0.8)
        centers, scan, tang, pos = arc_geometry(200, 200, 80, 180)
        hits = caliper_series(img, centers, scan, tang, pos, search=24, height=3, polarity="light_to_dark", threshold=10)
        series = hit_series(hits, "offset")
        self.assertEqual(len(series), 180)
        self.assertTrue(any(v is None for v in series))  # 缺口讓卡尺打空
        values = np.array([np.nan if v is None else v for v in series])
        flag = ~np.isfinite(values)
        segs = defects.segments(flag, wrap=True)
        self.assertTrue(segs)
        self.assertGreaterEqual(max(defects.seg_len(s, 180) for s in segs), 5)

    def test_agrees_with_the_existing_line_and_arc_scanners(self):
        """同一張圖、同一組設定，新原語與既有的 caliper_points／radial_edge_points 找到同一條邊。"""
        from apps.vision.tools.builtin.locate import (
            arc_geometry, caliper_points, caliper_series, line_geometry, radial_edge_points,
        )

        # 直線：既有 caliper_points 在擺正的 crop 內佈卡尺
        img = self._edge_image(x_edge=180.5)
        crop_img = img[20:280, 160:200]  # 高 260、寬 40 → 長邊是 y
        pts, horizontal = caliper_points(crop_img, 20, "dark_to_light", 15, "strongest", 3)
        self.assertFalse(horizontal)
        old_x = np.array([p[0] for p in pts]) + 160
        centers, scan, tang, pos = line_geometry(180, 20 + 253.5, 180, 20 + 6.5, 20)  # 由下往上＝掃描往 +x
        hits = caliper_series(img, centers, scan, tang, pos, search=40, height=13, polarity="dark_to_light", threshold=15, select="strongest")
        new_x = np.array([h.x for h in hits if h.found])
        self.assertEqual(len(new_x), len(old_x))
        self.assertLess(abs(new_x.mean() - old_x.mean()), 0.1, (new_x.mean(), old_x.mean()))

        # 圓弧：既有 radial_edge_points 由圓心向外掃
        disc = AlgorithmAccuracyTests._disk(400, 400, 200.0, 200.0, 80.0)
        old_pts = np.array(radial_edge_points(disc, 200, 200, 65, 95, 72, "light_to_dark", 10, "strongest", 3))
        old_r = np.hypot(old_pts[:, 0] - 200, old_pts[:, 1] - 200)
        centers, scan, tang, pos = arc_geometry(200, 200, 80, 72)
        hits = caliper_series(disc, centers, scan, tang, pos, search=30, height=1, polarity="light_to_dark", threshold=10, select="strongest")
        new_r = np.array([math.hypot(h.x - 200, h.y - 200) for h in hits if h.found])
        self.assertEqual(len(new_r), len(old_r))
        self.assertLess(abs(new_r.mean() - old_r.mean()), 0.05, (new_r.mean(), old_r.mean()))


class GdtTests(SimpleTestCase):
    """WP-10 形位公差：每個 mode 對人工構造點集的解析解（ISO 1101 最小區域，不是最小二乘）。"""

    @staticmethod
    def _rot(pts, deg, cx=0.0, cy=0.0):
        t = math.radians(deg)
        c, s_ = math.cos(t), math.sin(t)
        p = np.asarray(pts, dtype=np.float64) - [cx, cy]
        return np.column_stack([p[:, 0] * c - p[:, 1] * s_, p[:, 0] * s_ + p[:, 1] * c]) + [cx, cy]

    @staticmethod
    def _sine_line():
        x = np.linspace(0, 400, 201)
        return np.column_stack([x, 100 + 2.0 * np.sin(x / 400 * 2 * math.pi * 3)])  # 振幅 2 → 直線度 4

    def test_straightness_is_minimum_zone_band_not_least_squares(self):
        pts = self._sine_line()
        for deg, want_angle in ((0, 0.0), (30, 30.0), (-75, -75.0)):
            r = run_tool("gdt_measure", None, {"mode": "straightness", "tolerance": 4.5}, {"points": self._rot(pts, deg, 200, 100).tolist()})
            self.assertAlmostEqual(r.outputs["deviation"], 4.0, delta=0.01, msg=f"rot {deg}")
            self.assertAlmostEqual(r.detail["angle"], want_angle, delta=0.2)
            self.assertTrue(r.outputs["in_spec"])
            self.assertEqual((r.branch, r.status, r.outputs["unit"]), ("pass", "ok", "px"))
            self.assertEqual(r.detail["method"], "rotating calipers")
            self.assertEqual(len(r.detail["extreme_index"]), 2)
        # 最小二乘殘差帶會說 4.6：這就是規格要求旋轉卡尺而不是 LSQ 的原因
        A = np.column_stack([pts[:, 0], np.ones(len(pts))])
        coef, *_ = np.linalg.lstsq(A, pts[:, 1], rcond=None)
        res = pts[:, 1] - A @ coef
        self.assertGreater(res.max() - res.min(), 4.5)
        # flatness（2D 投影）＝同一個帶；公差 3 → fail
        r = run_tool("gdt_measure", None, {"mode": "flatness", "tolerance": 3}, {"points": pts.tolist()})
        self.assertAlmostEqual(r.outputs["deviation"], 4.0, delta=0.01)
        self.assertEqual((r.branch, r.status), ("fail", "ng"))
        # 共線兩點：0
        r = run_tool("gdt_measure", None, {"mode": "straightness", "tolerance": 1}, {"points": [[0, 0], [10, 10]]})
        self.assertEqual(r.outputs["deviation"], 0.0)

    def test_roundness_mzc_versus_lsc(self):
        th = np.linspace(0, 2 * math.pi, 360, endpoint=False)
        rr = 100 + 1.5 * np.cos(3 * th)  # 三瓣：峰谷 3
        lobed = np.column_stack([300 + rr * np.cos(th), 300 + rr * np.sin(th)])
        r = run_tool("gdt_measure", None, {"mode": "roundness", "tolerance": 3.2}, {"points": lobed.tolist()})
        self.assertAlmostEqual(r.outputs["deviation"], 3.0, delta=0.01)
        self.assertAlmostEqual(r.detail["lsc"]["width"], 3.0, delta=0.01)
        self.assertAlmostEqual(r.detail["cx"], 300, delta=0.01)
        self.assertIn("MZC", r.detail["method"])
        self.assertEqual(r.branch, "pass")
        kinds = [o["kind"] for o in r.overlays]
        self.assertEqual(kinds.count("circle"), 2)  # 內外包絡圓
        # D 形（一側切平）：最小二乘圓心被平邊拉走，MZC 重新定心後的帶寬更窄——差異記錄在 detail.lsc
        dx = np.minimum(300 + 100 * np.cos(th), 390)
        dshape = np.column_stack([dx, 300 + 100 * np.sin(th)])
        r = run_tool("gdt_measure", None, {"mode": "roundness", "tolerance": 5}, {"points": dshape.tolist()})
        self.assertLess(r.outputs["deviation"], r.detail["lsc"]["width"])
        self.assertAlmostEqual(r.outputs["deviation"], 9.52, delta=0.05)
        self.assertAlmostEqual(r.detail["lsc"]["width"], 9.82, delta=0.05)
        self.assertEqual(r.branch, "fail")

    def test_parallelism_perpendicularity_angularity(self):
        b = {"x1": 0, "y1": 0, "x2": 300, "y2": 0}
        cases = (("parallelism", 1.0, 0, 200 * math.sin(math.radians(1.0)), "fail"),
                 ("perpendicularity", 90.5, 0, 200 * math.sin(math.radians(0.5)), "pass"),
                 ("angularity", 45.2, 45, 200 * math.sin(math.radians(0.2)), "pass"))
        for mode, ang, ref, expect, branch in cases:
            a = {"x1": 50, "y1": 50, "x2": 50 + 200 * math.cos(math.radians(ang)), "y2": 50 + 200 * math.sin(math.radians(ang))}
            r = run_tool("gdt_measure", None, {"mode": mode, "tolerance": 2, "reference_angle": ref}, {"a": a, "b": b})
            self.assertAlmostEqual(r.outputs["deviation"], expect, delta=1e-3, msg=mode)
            self.assertAlmostEqual(r.detail["angle_difference"], abs(ang - ref) % 90 if mode != "perpendicularity" else 0.5, delta=1e-3)
            self.assertEqual(r.branch, branch, mode)
            self.assertTrue(any(o.get("label") == "datum" for o in r.overlays))
        # a 為點集、b 為點集（主方向）或角度
        pa = self._rot(np.column_stack([np.linspace(0, 200, 50), np.zeros(50)]), 1.0)
        pb = np.column_stack([np.linspace(0, 300, 50), np.full(50, 300.0)])
        want = 200 * math.sin(math.radians(1.0))
        for datum in (pb.tolist(), {"angle": 0}):
            r = run_tool("gdt_measure", None, {"mode": "parallelism", "tolerance": 4}, {"a": pa.tolist(), "b": datum})
            self.assertAlmostEqual(r.outputs["deviation"], want, delta=1e-3)
            self.assertEqual(r.detail["feature_points"], 50)

    def test_mm_mode_and_errors(self):
        pts = self._sine_line().tolist()
        r = run_tool("gdt_measure", None, {"mode": "straightness", "tolerance": 0.05, "unit": "mm"}, {"points": pts, "scale": 0.01})
        self.assertAlmostEqual(r.outputs["deviation"], 0.04, delta=1e-4)
        self.assertEqual((r.outputs["unit"], r.branch), ("mm", "pass"))
        r = run_tool("gdt_measure", None, {"mode": "straightness", "tolerance": 0.05, "unit": "mm", "mm_per_px": 0.02}, {"points": pts})
        self.assertAlmostEqual(r.outputs["deviation"], 0.08, delta=1e-4)
        self.assertEqual(r.branch, "fail")
        with self.assertRaisesMessage(ToolError, "needs a scale"):
            run_tool("gdt_measure", None, {"mode": "straightness", "unit": "mm"}, {"points": pts})
        with self.assertRaisesMessage(ToolError, "Connect the points"):
            run_tool("gdt_measure", None, {"mode": "roundness"}, {"points": [[0, 0], [1, 1]]})
        with self.assertRaisesMessage(ToolError, "Connect feature a"):
            run_tool("gdt_measure", None, {"mode": "parallelism"}, {"a": {"x1": 0, "y1": 0, "x2": 1, "y2": 0}})


class PhotometricTests(SimpleTestCase):
    """WP-11 光度立體：球面法向誤差 < 5°、刻印字單張抓不到／curvature 抓得到、3 燈可解、退化與尺寸錯誤。"""

    AZ = [0, 90, 180, 270]
    EL = 30.0

    @classmethod
    def _render(cls, normals_hw3, albedo, ambient=0.0):
        from apps.vision.tools.builtin import photometric as P

        L = P.light_directions(cls.AZ, cls.EL)
        return [np.clip(albedo * np.clip(normals_hw3 @ L[k], 0, None) + ambient, 0, 255).astype(np.uint8) for k in range(4)]

    @staticmethod
    def _sphere(h=400, w=400, r=150.0):
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
        x, y = xx - w / 2, yy - h / 2
        inside = x * x + y * y < r * r
        z = np.sqrt(np.clip(r * r - x * x - y * y, 0, None))
        n = np.dstack([x / r, y / r, z / r])
        n[~inside] = [0, 0, 1]
        return n, inside

    def test_sphere_normals_within_5_degrees(self):
        from apps.vision.tools.builtin import photometric as P

        n_true, inside = self._sphere()
        imgs = self._render(n_true, 200.0)
        L = P.light_directions(self.AZ, self.EL)
        lit = (np.stack([n_true @ L[k] for k in range(4)]) > 0.02).sum(axis=0)
        for drop in (True, False):
            n_est, albedo = P.solve(imgs, self.AZ, self.EL, drop_darkest=drop)
            self.assertEqual(n_est.shape, (3, 400, 400))
            err = np.degrees(np.arccos(np.clip((np.moveaxis(n_est, 0, -1) * n_true).sum(axis=2), -1, 1)))
            self.assertLess(err[inside & (lit >= 4)].max(), 1.0, f"drop={drop}: fully lit pixels")
            if drop:
                # 一盞燈在陰影裡：丟掉最暗那張後仍準（p95 < 1°、最大 < 5°）
                self.assertLess(np.percentile(err[inside & (lit >= 3)], 95), 1.0)
                self.assertLess(err[inside & (lit >= 3)].max(), 5.0)
            else:
                self.assertGreater(err[inside & (lit == 3)].max(), 5.0)  # 不丟：陰影把法向拉歪，這就是 drop_darkest 的理由
            self.assertAlmostEqual(float(np.median(albedo[inside & (lit >= 4)])), 200.0, delta=2.0)

    def test_embossed_text_invisible_to_threshold_visible_in_curvature(self):
        h, w = 480, 640
        mask = np.zeros((h, w), np.uint8)
        cv2.putText(mask, "VS 42", (60, 300), cv2.FONT_HERSHEY_SIMPLEX, 5, 255, 24)
        height = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 3) * 6.0
        gx = cv2.Sobel(height, cv2.CV_32F, 1, 0, ksize=3, scale=1 / 8)
        gy = cv2.Sobel(height, cv2.CV_32F, 0, 1, ksize=3, scale=1 / 8)
        nrm = np.dstack([-gx, -gy, np.ones_like(gx)])
        nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
        imgs = self._render(nrm, 180.0, ambient=10)
        letters = mask > 0
        for k in range(4):  # 任一張單獨 Otsu 二值化：與字的 IoU < 0.2（兩種極性都試）
            th = cv2.threshold(imgs[k], 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
            for pol in (th > 0, th == 0):
                self.assertLess((pol & letters).sum() / (pol | letters).sum(), 0.2)
        r = run_tool("photometric_stereo", imgs[0], {"output": "curvature"}, {"image_1": imgs[1], "image_2": imgs[2], "image_3": imgs[3]})
        self.assertEqual(r.outputs["lights"], 4)
        curv = r.outputs["image"]
        self.assertEqual((curv.dtype, curv.shape), (np.uint8, (h, w)))
        edge = (cv2.absdiff(curv, 128) > 25).astype(np.uint8) * 255
        filled = cv2.morphologyEx(edge, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))) > 0
        self.assertGreater((filled & letters).sum() / (filled | letters).sum(), 0.45)
        # 凸起內部散度為正（亮）、外緣為負（暗）；shape strength 是無號版
        signed = curv.astype(np.int32) - 128
        self.assertGreater(signed[letters].mean(), 30)
        self.assertGreater(r.outputs["curvature_abs"][letters].mean(), r.outputs["curvature_abs"][~cv2.dilate(mask, np.ones((9, 9))).astype(bool)].mean())
        self.assertEqual(set(r.outputs) - {"image", "lights"}, {"curvature", "curvature_abs", "albedo", "normal_x", "normal_y"})
        # 反射率圖幾乎是平的（材質同色）
        alb = r.outputs["albedo"]
        self.assertLess(float(alb[letters].mean() - alb[~letters].mean()), 12)
        # float 輸出
        rf = run_tool("photometric_stereo", imgs[0], {"normalize": False, "output": "normal_x"}, {"image_1": imgs[1], "image_2": imgs[2], "image_3": imgs[3]})
        self.assertEqual(rf.outputs["image"].dtype, np.float32)
        self.assertLessEqual(float(np.abs(rf.outputs["image"]).max()), 1.0)

    def test_three_lights_and_errors(self):
        n_true, inside = self._sphere(120, 120, 40)
        imgs = self._render(n_true, 150.0)
        r = run_tool("photometric_stereo", imgs[0], {"light_azimuth": "[0, 120, 240]"}, {"image_1": imgs[1], "image_2": imgs[2]})
        self.assertEqual(r.outputs["lights"], 3)
        with self.assertRaisesMessage(ToolError, "At least three lighting pictures"):
            run_tool("photometric_stereo", imgs[0], {}, {"image_1": imgs[1]})
        with self.assertRaisesMessage(ToolError, "degenerate"):
            run_tool("photometric_stereo", imgs[0], {"light_azimuth": [0, 0, 0, 0]}, {"image_1": imgs[1], "image_2": imgs[2], "image_3": imgs[3]})
        with self.assertRaisesMessage(ToolError, "same size"):
            run_tool("photometric_stereo", imgs[0], {}, {"image_1": imgs[1], "image_2": imgs[2][:60], "image_3": imgs[3]})
        with self.assertRaisesMessage(ToolError, "only 3 light azimuths"):
            run_tool("photometric_stereo", imgs[0], {"light_azimuth": [0, 90, 180]}, {"image_1": imgs[1], "image_2": imgs[2], "image_3": imgs[3]})
        with self.assertRaisesMessage(ToolError, "JSON list"):
            run_tool("photometric_stereo", imgs[0], {"light_azimuth": "nope"}, {"image_1": imgs[1], "image_2": imgs[2]})
        # 彩色輸入也吃（轉灰階）
        bgr = [cv2.cvtColor(im, cv2.COLOR_GRAY2BGR) for im in imgs]
        r = run_tool("photometric_stereo", bgr[0], {}, {"image_1": bgr[1], "image_2": bgr[2], "image_3": bgr[3]})
        self.assertEqual(r.outputs["image"].shape, (120, 120))
