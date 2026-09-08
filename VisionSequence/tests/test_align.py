"""對位工具的合成姿態、剛體解算、取料補償與標定測試。"""

import math
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase

from apps.vision.tools import base
from apps.vision.tools.base import ToolError
from tests._helpers import blank, run_tool


class AlignOffsetTests(SimpleTestCase):
    def assert_offset(self, result, expected):
        self.assertEqual(result.status, "ok", result.message)
        self.assertEqual(result.branch, "found")
        actual = [result.outputs[key] for key in ("dx", "dy", "dtheta")]
        self.assertLess(float(np.max(np.abs(np.asarray(actual) - expected))), 1e-6)

    def test_pure_translation(self):
        result = run_tool("align_offset", params={"ref_x": 30, "ref_y": 40, "ref_angle": 12},
                          inputs={"a": 37.25, "b": 35.5, "c": 12})
        self.assert_offset(result, [7.25, -4.5, 0])

    def test_pure_rotation(self):
        result = run_tool("align_offset", params={"ref_x": 30, "ref_y": 40, "ref_angle": 12},
                          inputs={"matches": [{"cx": 30, "cy": 40, "angle": 102}]})
        self.assert_offset(result, [0, 0, 90])

    def test_combined_translation_rotation(self):
        result = run_tool("align_offset", params={"ref_x": 30, "ref_y": 40, "ref_angle": 12},
                          inputs={"a": 37.25, "b": 35.5, "c": -25})
        self.assert_offset(result, [7.25, -4.5, -37])

    def test_matches_priority_and_first_match(self):
        result = run_tool("align_offset", inputs={
            "matches": [{"cx": 5, "cy": 6, "angle": 7}, {"cx": 100, "cy": 200, "angle": 90}],
            "a": 10, "b": 20, "c": 30,
        })
        self.assert_offset(result, [5, 6, 7])

    def test_pose_fallback_conventions(self):
        for inputs in ({"matches": [], "a": 3, "b": 4},
                       {"matches": [{"x": 3, "y": 4}]}, {"a": 3, "b": 4, "c": None}):
            with self.subTest(inputs=inputs):
                self.assert_offset(run_tool("align_offset", inputs=inputs), [3, 4, 0])

    def test_angle_wrap(self):
        self.assert_offset(run_tool("align_offset", params={"ref_angle": 170},
                                    inputs={"a": 0, "b": 0, "c": -170}), [0, 0, 20])

    def test_connected_missing_pose_is_ng(self):
        cases = [{"matches": []}, {"matches": None}, {"a": None, "b": None}, {"c": math.nan}]
        for key in ("a", "b", "c"):
            cases.append({"a": 3, "b": 4, "c": 5} | {key: math.nan})
        for key in ("cx", "cy", "angle"):
            cases.append({"matches": [{"cx": 3, "cy": 4, "angle": 5} | {key: math.nan}],
                          "a": 10, "b": 20, "c": 30})
        for mode in ("point", "grab"):
            for inputs in cases:
                with self.subTest(mode=mode, inputs=inputs):
                    result = run_tool("align_offset", params={"mode": mode}, inputs=inputs)
                    self.assertEqual(result.status, "ng")
                    self.assertEqual(result.branch, "not_found")
                    self.assertTrue(all(value is None for value in result.outputs.values()))

    def test_no_pose_connection_raises(self):
        for mode in ("point", "grab", "point_set", "line"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ToolError, "No current position"):
                run_tool("align_offset", params={"mode": mode})

    def test_point_set_rigid_solve(self):
        # 非原點重心、非對稱點集，可區分旋轉中心與原點平移項。
        for count in (2, 3, 8):
            # 既有 ROI 旋轉函式會以單精度接收中心；整合案例使用可精確表示的重心。
            reference = np.array([[10 + i * 3, 20 + i * i * 3] for i in range(count)], dtype=float)
            theta = math.radians(37)
            rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
            current = reference @ rotation.T + [7, -11]
            result = run_tool("align_offset", params={"mode": "point_set", "ref_points": reference.tolist(), "ref_angle": 12},
                              inputs={"points": current})
            with self.subTest(count=count):
                offset = current.mean(axis=0) - reference.mean(axis=0)
                self.assert_offset(result, [*offset, 37])
                transform = result.outputs["transform"]
                np.testing.assert_allclose(transform["pivot"], reference.mean(axis=0), atol=1e-7, rtol=0)
                np.testing.assert_allclose(transform["current"], [*current.mean(axis=0), 49], atol=1e-7, rtol=0)
                # 透過既有 ROI 工具套用輸出，驗證每一對點與下游契約一致。
                for source, target in zip(reference, current, strict=True):
                    moved = run_tool("fixture_roi", params={"roi": {"shape": "circle", "cx": source[0], "cy": source[1], "r": 2}},
                                     inputs={"transform": transform}).outputs["region"]
                    np.testing.assert_allclose([moved["cx"], moved["cy"]], target, atol=1e-7, rtol=0)

    def test_point_set_fractional_centroid_precision(self):
        reference = np.array([[10, 20], [13, 21], [16, 24]], dtype=float)
        radians = math.radians(37)
        expected_rotation = np.array([[math.cos(radians), -math.sin(radians)],
                                      [math.sin(radians), math.cos(radians)]])
        current = reference @ expected_rotation.T + [7, -11]
        result = run_tool("align_offset", params={"mode": "point_set", "ref_points": reference.tolist()},
                          inputs={"points": current.tolist()})
        self.assert_offset(result, [*(current.mean(axis=0) - reference.mean(axis=0)), 37])
        transform = result.outputs["transform"]
        radians = math.radians(transform["dtheta"])
        rotation = np.array([[math.cos(radians), -math.sin(radians)], [math.sin(radians), math.cos(radians)]])
        pivot = np.asarray(transform["pivot"])
        mapped = (reference - pivot) @ rotation.T + pivot + [transform["dx"], transform["dy"]]
        np.testing.assert_allclose(mapped, current, atol=1e-7, rtol=0)

    def test_point_set_uses_all_points_without_scale(self):
        reference = np.array([[0, 0], [8, 0], [0, 4], [4, 2]], dtype=float)
        centre = reference.mean(axis=0)
        # 帶尺度誤差的資料仍以所有點求最佳剛體解；不得吸收尺度或剔除點。
        current = (reference - centre) @ np.array([[0, 1], [-1, 0]]) * 1.2 + centre + [5, 7]
        result = run_tool("align_offset", params={"mode": "point_set", "ref_points": reference.tolist()},
                          inputs={"points": current.tolist()})
        self.assert_offset(result, [5, 7, 90])
        self.assertEqual(set(result.outputs["transform"]), {"dx", "dy", "dtheta", "pivot", "current"})

    def test_point_set_does_not_reflect(self):
        reference = np.array([[-3, -1], [3, -1], [3, 1], [-3, 1]])
        current = reference * [1, -1] + [4, 5]
        result = run_tool("align_offset", params={"mode": "point_set", "ref_points": reference.tolist()},
                          inputs={"points": current.tolist()})
        self.assert_offset(result, [4, 5, 0])

    def test_point_set_invalid_or_missing_is_ng(self):
        reference = [[0, 0], [1, 0]]
        cases = [(reference, None), (reference, []), (reference, [[0, 0], [math.nan, 0]]),
                 (reference, [[1, 1], [1, 1]]), (reference, [[0, 0], [1, 0], [2, 0]]),
                 ([[0, 0]], [[1, 0]]), ([[0, 0]] * 9, [[1, 0]] * 9), ([[0, 0]] * 2, reference)]
        for taught, current in cases:
            with self.subTest(taught=taught, current=current):
                result = run_tool("align_offset", params={"mode": "point_set", "ref_points": taught}, inputs={"points": current})
                self.assertEqual((result.status, result.branch), ("ng", "not_found"))

    def test_grab_absolute_coordinates(self):
        result = run_tool("align_offset", params={"mode": "grab", "ref_x": 100, "ref_y": 50,
                                                  "ref_angle": 15, "grab_x": 120, "grab_y": 55},
                          inputs={"a": 110, "b": 70, "c": 105})
        self.assert_offset(result, [10, 20, 90])
        np.testing.assert_allclose([result.outputs[k] for k in ("abs_x", "abs_y", "abs_angle")],
                                   [105, 90, 105], atol=1e-7, rtol=0)

    def test_line_midpoint_and_direction(self):
        result = run_tool("align_offset", params={"mode": "line", "ref_x": 10, "ref_y": 20, "ref_angle": 30},
                          inputs={"line": {"x1": 15, "y1": 25, "x2": 15, "y2": 35}})
        self.assert_offset(result, [5, 10, 60])

    def test_line_missing_or_degenerate_is_ng(self):
        for line in (None, {}, {"x1": 1, "y1": 2, "x2": 1, "y2": 2},
                     {"x1": math.nan, "y1": 2, "x2": 4, "y2": 5}):
            with self.subTest(line=line):
                result = run_tool("align_offset", params={"mode": "line"}, inputs={"line": line})
                self.assertEqual((result.status, result.branch), ("ng", "not_found"))

    def test_transform_matches_shape_align_exactly(self):
        params = {"ref_x": 100, "ref_y": 50, "ref_angle": 170}
        inputs = {"matches": [{"cx": 110, "cy": 60, "angle": -170}]}
        actual = run_tool("align_offset", params=params, inputs=inputs).outputs["transform"]
        expected = run_tool("shape_align", params=params, inputs=inputs).outputs["transform"]
        self.assertEqual(set(actual), set(expected))
        self.assertEqual(actual, expected)

    def test_calibration_robot_precedence_and_world_fallback(self):
        world = {"matrix": [[2, 0, 10], [0, 3, 20], [0, 0, 1]]}
        robot = {"matrix": [[0, 2, 100], [3, 0, 200], [0, 0, 1]]}
        for payload, expected in (({"robot": robot, "world": world}, [180, 290, 0]),
                                  ({"robot": robot}, [180, 290, 0]), ({"world": world}, [70, 140, 90])):
            with self.subTest(payload=payload), patch("apps.vision.calib.load", return_value=payload) as load:
                result = run_tool("align_offset", params={"calibration": "cal"}, inputs={"a": 30, "b": 40, "c": 90},
                                  assets={"cal": "calibration.json"})
                self.assertEqual(result.status, "ok", result.message)
                load.assert_called_once_with("calibration.json")
                np.testing.assert_allclose([result.outputs[k] for k in ("world_x", "world_y", "world_angle")],
                                           expected, atol=1e-7, rtol=0)

    def test_grab_calibration_uses_compensated_point(self):
        payload = {"world": {"matrix": [[2, 0, 10], [0, 3, 20], [0, 0, 1]]}}
        with patch("apps.vision.calib.load", return_value=payload):
            result = run_tool("align_offset", params={"mode": "grab", "grab_x": 4, "grab_y": 2, "calibration": "cal"},
                              inputs={"a": 10, "b": 20, "c": 90}, assets={"cal": "calibration.json"})
        np.testing.assert_allclose([result.outputs[k] for k in ("world_x", "world_y", "world_angle")],
                                   [26, 92, 90], atol=1e-7, rtol=0)

    def test_no_calibration_produces_only_pixel_outputs(self):
        with patch("apps.vision.calib.load") as load:
            result = run_tool("align_offset", inputs={"a": 3, "b": 4})
        load.assert_not_called()
        self.assertFalse(any(key.startswith("world_") for key in result.outputs))

    def test_overlays_use_full_image_coordinates_and_do_not_mutate(self):
        image = blank()
        original = image.copy()
        result = run_tool("align_offset", image, {"ref_x": 100, "ref_y": 80}, inputs={"a": 150, "b": 120, "c": 30})
        taught, current, line, label = result.overlays
        self.assertEqual((taught["x"], taught["y"], taught["color"]), (100, 80, "#38bdf8"))
        self.assertEqual((current["x"], current["y"], current["color"]), (150, 120, "#22c55e"))
        self.assertEqual([line[k] for k in ("x1", "y1", "x2", "y2")], [100, 80, 150, 120])
        self.assertEqual(label["text"], "dx=50.00 dy=40.00 dtheta=30.00 deg")
        np.testing.assert_array_equal(image, original)

    def test_teach_and_port_metadata(self):
        tool = base.get("align_offset")
        params = {p.key: p for p in tool.params}
        self.assertTrue(all(params[k].teach for k in ("ref_x", "ref_y", "ref_angle")))
        self.assertEqual(params["ref_points"].kind, "json")
        self.assertEqual((params["calibration"].kind, params["calibration"].accept), ("asset", "calibration"))
        self.assertEqual({p.key for p in tool.outputs if p.type == "flow"}, {"found", "not_found"})
