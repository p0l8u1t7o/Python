"""物理量與自訂座標系：解析真值、像素相容性、資產讀取及影像純度。"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from django.test import SimpleTestCase

from apps.vision import calib
from apps.vision.tools import base
from apps.vision.tools.base import ToolError
from apps.vision.tools.physical import world_outputs
from tests._helpers import blank, circle_image, rect_image, run_tool


class PhysicalTests(SimpleTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="vs-physical-")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.assets = {}
        self.matrix = [[0, -2, 10], [2, 0, -20], [0, 0, 1]]
        self.save("cal", self.matrix, unit="um")
        self.perspective = [[2, 0, 10], [0, 3, -20], [0.002, 0.001, 1]]
        self.save("perspective", self.perspective, kind="perspective")
        lens = {"camera_matrix": [[100, 0, 160], [0, 100, 120], [0, 0, 1]], "dist_coeffs": [0] * 5}
        self.save_payload("lens", {"version": 1, "image_size": [320, 240], "unit": "in", "lens": lens})

    def save_payload(self, key, payload):
        path = self.folder / f"{key}.json"
        calib.save(str(path), payload)
        self.assets[key] = str(path)

    def save(self, key, matrix, unit="in", kind="affine"):
        self.save_payload(key, {"version": 1, "image_size": [320, 240], "unit": unit,
                                "world": {"kind": kind, "matrix": matrix}})

    def ctx(self, asset="cal", key="calibration"):
        return SimpleNamespace(param=lambda name: asset if name == key else None,
                               asset_path=lambda aid: self.assets.get(str(aid)))

    def test_helper_no_asset_does_not_resolve(self):
        for empty in (None, "", 0):
            ctx = SimpleNamespace(param=lambda key: empty, asset_path=Mock(side_effect=AssertionError))
            self.assertEqual(world_outputs(ctx, points={("cx", "cy"): (1, 2)}), {})
            ctx.asset_path.assert_not_called()

    def test_helper_point_length_angle_and_custom_key(self):
        out = world_outputs(self.ctx(key="other"), key="other", points={("cx", "cy"): (3, 4)},
                            lengths={"length": (5, (3, 4))}, angles={"angle": (30, (3, 4))})
        self.assertEqual((out["cx_world"], out["cy_world"], out["length_world"], out["unit"]), (2, -14, 10, "um"))
        self.assertAlmostEqual(out["angle_world"], 120)

    def test_helper_perspective_position_dependent_scale(self):
        # 解析齊次除法及一像素探針面積，獨立於 calib.scale_at。
        def project(x, y):
            w = 1 + 0.002 * x + 0.001 * y
            return np.array([(2 * x + 10) / w, (3 * y - 20) / w])

        scales = []
        for x, y in ((0, 0), (200, 100)):
            p = project(x, y)
            dx, dy = project(x + 1, y) - p, project(x, y + 1) - p
            scale = math.sqrt(abs(dx[0] * dy[1] - dx[1] * dy[0]))
            out = world_outputs(self.ctx("perspective"), points={("x", "y"): (x, y)},
                                lengths={"length": (10, (x, y))}, angles={"angle": (45, (x, y))})
            np.testing.assert_allclose([out["x_world"], out["y_world"]], p, atol=1e-12)
            self.assertAlmostEqual(out["length_world"], 10 * scale)
            d = project(x + math.sqrt(0.5), y + math.sqrt(0.5)) - p
            self.assertAlmostEqual(out["angle_world"], math.degrees(math.atan2(d[1], d[0])))
            scales.append(scale)
        self.assertGreater(scales[0], scales[1])

    def test_robot_mapping_precedes_world_and_works_alone(self):
        robot = calib.solve_robot([{"px": x, "py": y, "rx": 4 * x + 7, "ry": -4 * y + 9}
                                   for x, y in ((0, 0), (100, 0), (0, 100), (100, 100))],
                                  kind="translation", camera_mode="fixed")
        payload = calib.load(self.assets["cal"])
        self.save_payload("both", {**payload, "robot": robot})
        self.save_payload("robot", {"image_size": [320, 240], "unit": "in", "robot": robot})
        for asset in ("both", "robot"):
            out = world_outputs(self.ctx(asset), points={("x", "y"): (3, 4)},
                                lengths={"r": (2, (3, 4))}, angles={"angle": (30, (3, 4))})
            np.testing.assert_allclose([out["x_world"], out["y_world"], out["r_world"], out["angle_world"]],
                                       [19, -7, 8, -30], atol=1e-9)

    def test_missing_mapping_is_tool_error(self):
        with self.assertRaisesMessage(ToolError, "The calibration has no world or robot mapping"):
            world_outputs(self.ctx("lens"))
        for tool, inputs in (("to_world", {"x": 1, "y": 2}), ("distance", {"a": [0, 0], "b": [3, 4]})):
            with self.subTest(tool=tool), self.assertRaises(ToolError):
                run_tool(tool, params={"calibration": "lens"}, inputs=inputs, assets=self.assets)
        with self.assertRaises(ToolError):
            world_outputs(self.ctx("deleted"))

    def measurement_cases(self):
        band = blank()
        band[90:130, :] = 220
        edge = blank()
        edge[100:, :] = 220
        return [
            ("distance", None, {}, {"a": [1, 2], "b": [4, 6]}, ["distance"], []),
            ("caliper", rect_image(), {"roi": {"shape": "rect", "x": 60, "y": 90, "w": 200, "h": 40}}, {},
             ["width"], [("edge1_x", "edge1_y"), ("edge2_x", "edge2_y")]),
            ("find_circle", circle_image(), {"roi": {"shape": "circle", "cx": 160, "cy": 120, "r": 70}}, {},
             ["r"], [("cx", "cy")]),
            ("fit_arc", circle_image(), {"roi": {"shape": "annulus", "cx": 160, "cy": 120, "r_inner": 30, "r_outer": 70}}, {},
             ["radius"], [("cx", "cy")]),
            ("find_rectangle", rect_image(), {"roi": {"shape": "rect", "x": 100, "y": 80, "w": 120, "h": 60}}, {},
             ["width", "height"], [("cx", "cy")]),
            ("find_parallel_lines", band, {"roi": {"shape": "rect", "x": 40, "y": 70, "w": 240, "h": 80},
                                           "pair_polarity": "bright", "pair_mode": "widest"}, {},
             ["distance", "min_distance", "max_distance"], []),
            ("find_line", edge, {"roi": {"shape": "rect", "x": 40, "y": 60, "w": 240, "h": 80}}, {},
             [], [("x1", "y1"), ("x2", "y2")]),
            ("geometry", None, {"mode": "line_2pts"}, {"a": [1, 2], "b": [4, 6]}, ["distance"], [("x", "y")]),
        ]

    def test_each_tool_keeps_pixels_and_adds_declared_world_ports(self):
        for key, image, params, inputs, lengths, points in self.measurement_cases():
            with self.subTest(tool=key):
                before = image.copy() if image is not None else None
                plain = run_tool(key, image, params, inputs)
                empty = run_tool(key, image, {**params, "calibration": ""}, inputs)
                physical = run_tool(key, image, {**params, "calibration": "cal"}, inputs, self.assets)
                self.assertEqual(plain.status, "ok", plain.message)
                self.assertEqual(plain, empty)
                self.assertEqual(plain.outputs, {k: v for k, v in physical.outputs.items() if k in plain.outputs})
                self.assertEqual((plain.overlays, plain.message, plain.status, plain.branch, plain.detail),
                                 (physical.overlays, physical.message, physical.status, physical.branch, physical.detail))
                for port in base.get(key).outputs:
                    if port.key.endswith("_world") or port.key == "unit":
                        self.assertIsNone(plain.outputs.get(port.key))
                        self.assertIn(port.key, physical.outputs)
                self.assertEqual(physical.outputs["unit"], "um")
                for name in lengths:
                    self.assertAlmostEqual(physical.outputs[name + "_world"], 2 * plain.outputs[name], places=7)
                for x, y in points:
                    self.assertAlmostEqual(physical.outputs[x + "_world"], 10 - 2 * plain.outputs[y], places=7)
                    self.assertAlmostEqual(physical.outputs[y + "_world"], 2 * plain.outputs[x] - 20, places=7)
                if image is not None:
                    np.testing.assert_array_equal(image, before)

    def test_distance_shape_and_perspective_midpoint(self):
        for params, inputs, at in (({}, {"a": [0, 0], "b": [200, 100]}, (100, 50)),
                                   ({"mode": "nearest"}, {"a": {"cx": 0, "cy": 0, "r": 5},
                                                         "b": {"cx": 30, "cy": 0, "r": 5}}, (15, 0))):
            r = run_tool("distance", params={**params, "calibration": "perspective"}, inputs=inputs, assets=self.assets)
            self.assertAlmostEqual(r.outputs["distance_world"], r.outputs["distance"] * calib.scale_at(self.perspective, at))

    def test_not_found_does_not_invent_physical_measurements(self):
        for key, image, params, inputs, _, _ in self.measurement_cases():
            if key == "distance":
                inputs = {"a": [float("nan"), 0], "b": [3, 4]}
            elif key == "geometry":
                params = {"mode": "intersect"}
                inputs = {"a": {"x1": 0, "y1": 0, "x2": 10, "y2": 0},
                          "b": {"x1": 0, "y1": 10, "x2": 10, "y2": 10}}
            else:
                image = blank()
            with self.subTest(tool=key):
                for calibration in (None, "cal"):
                    r = run_tool(key, image, {**params, "calibration": calibration}, inputs, self.assets)
                    self.assertEqual(r.status, "ng")
                    for port in base.get(key).outputs:
                        if port.key.endswith("_world"):
                            self.assertIsNone(r.outputs.get(port.key))

    def test_geometry_all_modes(self):
        line = {"x1": 0, "y1": 0, "x2": 10, "y2": 0}
        other = {"x1": 0, "y1": 0, "x2": 0, "y2": 10}
        cases = {"intersect": (line, other, None), "point_line": ([3, 4], line, None),
                 "midpoint": ([0, 0], [6, 8], None), "project": ([3, 4], line, None),
                 "line_2pts": ([0, 0], [6, 8], None), "parallel": (line, [3, 4], None),
                 "perpendicular": (line, [3, 4], None), "perp_bisector": ([0, 0], [6, 8], None),
                 "median": (line, {**line, "y1": 10, "y2": 10}, None), "bisector": (line, other, None),
                 "circle_3pts": ([5, 0], [0, 5], [-5, 0]), "rotate": ([10, 0], [0, 0], None)}
        for mode, (a, b, c) in cases.items():
            with self.subTest(mode=mode):
                r = run_tool("geometry", params={"mode": mode, "angle": 30, "calibration": "cal"},
                             inputs={"a": a, "b": b, "c": c}, assets=self.assets)
                self.assertEqual(r.status, "ok", r.message)
                self.assertAlmostEqual(r.outputs["distance_world"], 2 * r.outputs["distance"])
                if mode in ("rotate", "intersect"):
                    self.assertAlmostEqual(r.outputs["angle_world"], r.outputs["angle"])

    def test_coordinate_modes_and_port_precedence(self):
        for params, inputs in (({"origin_x": 10, "origin_y": 20, "axis_angle": 90}, {}),
                               ({"origin_x": 100, "origin_y": 200, "axis_angle": 0}, {"point": [10, 20], "angle": 90}),
                               ({"mode": "two_points"}, {"point": {"x": 10, "y": 20}, "point2": [10, 30]}),
                               ({"mode": "line"}, {"line": {"x1": 10, "y1": 20, "x2": 10, "y2": 30}})):
            r = run_tool("coordinate", params=params, inputs=inputs)
            self.assertEqual(r.branch, "found")
            self.assertEqual(r.outputs, {"frame": {"origin": [10, 20], "angle": 90, "scale": 1.0},
                                         "origin_x": 10, "origin_y": 20, "angle": 90})
            x_axis, y_axis = r.overlays[1:]
            np.testing.assert_allclose([x_axis["x2"], x_axis["y2"], y_axis["x2"], y_axis["y2"]], [10, 60, -30, 20], atol=1e-12)

    def test_coordinate_not_found(self):
        for params, inputs in (({}, {}), ({"mode": "two_points"}, {"point": [0, 0]}),
                               ({"mode": "two_points"}, {"point": [1, 2], "point2": [1, 2]}),
                               ({"mode": "line"}, {}), ({"mode": "line"}, {"line": [1, 2, 1, 2]}),
                               ({"origin_x": 1, "origin_y": 2}, {"point": None}),
                               ({}, {"point": [1, 2], "angle": None}), ({}, {"point": [float("nan"), 2]})):
            r = run_tool("coordinate", params=params, inputs=inputs)
            self.assertEqual((r.status, r.branch), ("ng", "not_found"))
            self.assertTrue(all(value is None for value in r.outputs.values()))

    def test_coordinate_teach_and_optional_asset_metadata(self):
        self.assertEqual({p.key for p in base.get("coordinate").params if p.teach},
                         {"origin_x", "origin_y", "axis_angle"})
        for key, *_ in self.measurement_cases():
            spec = next(p for p in base.get(key).params if p.key == "calibration")
            self.assertEqual((spec.kind, spec.accept, spec.required, spec.group), ("asset", "calibration", False, "Advanced"))

    def test_frame_translation_rotation_and_scale_truth(self):
        frame = {"origin": [10, 20], "angle": 90, "scale": 2}
        inputs = {"x": 10, "y": 26, "frame": frame, "value": 8, "angle": 90}
        out = run_tool("to_world", inputs=inputs).outputs
        np.testing.assert_allclose([out["x"], out["y"], out["length"], out["angle"], out["scale"]], [3, 0, 4, 0, 0.5], atol=1e-12)
        calibrated = run_tool("to_world", params={"calibration": "cal"}, inputs=inputs, assets=self.assets).outputs
        np.testing.assert_allclose([calibrated["x"], calibrated["y"], calibrated["length"], calibrated["angle"]], [10, -14, 8, 90], atol=1e-12)
        identity = run_tool("to_world", inputs={"x": 10, "y": 26}).outputs
        self.assertEqual((identity["x"], identity["y"], identity["scale"]), (10, 26, 1))

    def test_inverse_round_trip_affine_perspective_and_frame(self):
        points = np.array([[0.123456789, 4.987654321], [200, 100], [-10, 70]], dtype=float)
        before = points.copy()
        for asset in (None, "cal", "perspective"):
            for frame in (None, {"origin": [20, -30], "angle": 90, "scale": 2.5}):
                with self.subTest(asset=asset, frame=frame):
                    extra = {"frame": frame} if frame is not None else {}
                    forward = run_tool("to_world", params={"calibration": asset}, inputs={"points": points, **extra}, assets=self.assets)
                    inverse = run_tool("to_world", params={"calibration": asset, "mode": "to_pixel"},
                                       inputs={"points": forward.outputs["points_world"], **extra}, assets=self.assets)
                    np.testing.assert_allclose(inverse.outputs["points_world"], points, rtol=0, atol=1e-6)
                    np.testing.assert_allclose([inverse.outputs["x"], inverse.outputs["y"]], points[0], rtol=0, atol=1e-6)
                    np.testing.assert_allclose([inverse.overlays[0]["x"], inverse.overlays[0]["y"]], points[0], atol=1e-6)
        np.testing.assert_array_equal(points, before)

    def test_inverse_perspective_analytic_and_invalid_frame(self):
        # x'=2x/(1+0.01x), y'=3y/(1+0.01x)：(100,50) 對應 (100,75)。
        self.save("analytic", [[2, 0, 0], [0, 3, 0], [0.01, 0, 1]], kind="perspective")
        r = run_tool("to_world", params={"calibration": "analytic", "mode": "to_pixel"},
                     inputs={"x": 100, "y": 75}, assets=self.assets)
        np.testing.assert_allclose([r.outputs["x"], r.outputs["y"]], [100, 50], atol=1e-9)
        for frame in ({}, {"origin": [0, 0], "angle": 0, "scale": 0}):
            with self.assertRaises(ToolError):
                run_tool("to_world", inputs={"x": 1, "y": 2, "frame": frame})
        self.assertEqual(run_tool("to_world", inputs={"x": 1, "y": 2, "frame": None}).status, "ng")

    def test_length_only_compatibility_and_frame_conversion(self):
        with self.assertRaises(ToolError):
            run_tool("to_world", inputs={"value": 8})
        frame = {"origin": [10, 20], "angle": 90, "scale": 2}
        forward = run_tool("to_world", inputs={"value": 8, "angle": 90, "frame": frame})
        reverse = run_tool("to_world", params={"mode": "to_pixel"},
                           inputs={"value": forward.outputs["length"], "angle": forward.outputs["angle"], "frame": frame})
        np.testing.assert_allclose([forward.outputs["length"], forward.outputs["angle"]], [4, 0], atol=1e-12)
        np.testing.assert_allclose([reverse.outputs["length"], reverse.outputs["angle"]], [8, 90], atol=1e-12)
