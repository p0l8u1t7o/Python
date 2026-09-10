from __future__ import annotations

import math

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision import engine
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.tools.base import ToolError
from tests._helpers import blank, run_tool


def n(nid: str, ntype: str, **params):
    return {"id": nid, "type": ntype, "params": params}


def e(s: str, t: str, sh: str = "", th: str = ""):
    return {"source": s, "target": t, "source_handle": sh, "target_handle": th}


def run_graph(graph: dict, image: np.ndarray | None = None) -> engine.RunReport:
    compiled = compile_graph(validate_graph(graph))
    return engine.execute(
        compiled,
        flow_id=1,
        flow_version=1,
        trigger="test",
        grab=lambda _sid: None,
        asset_path=lambda _aid: None,
        preview=True,
        input_image=image,
    )


class Stage4FittingAndMaskTests(SimpleTestCase):
    def test_fit_line_circle_and_ellipse_from_points(self):
        xs = np.linspace(10, 110, 30)
        line_pts = [[float(x), float(0.5 * x + 20)] for x in xs] + [[80.0, 140.0]]
        line = run_tool("fit_line_points", None, {"method": "ransac", "ransac_tol": 1.5}, {"points": line_pts})
        self.assertEqual((line.status, line.branch), ("ok", "found"))
        self.assertGreaterEqual(line.outputs["inliers"], 30)
        self.assertAlmostEqual(line.outputs["angle"], math.degrees(math.atan(0.5)), delta=1.0)

        angles = np.linspace(0, 2 * math.pi, 60, endpoint=False)
        circle_pts = [[80 + 35 * math.cos(t), 70 + 35 * math.sin(t)] for t in angles]
        circle = run_tool("fit_circle_points", None, {"method": "lsq"}, {"points": circle_pts})
        self.assertEqual((circle.status, circle.branch), ("ok", "found"))
        self.assertAlmostEqual(circle.outputs["cx"], 80, delta=0.1)
        self.assertAlmostEqual(circle.outputs["cy"], 70, delta=0.1)
        self.assertAlmostEqual(circle.outputs["r"], 35, delta=0.1)

        ellipse_pts = [[120 + 45 * math.cos(t), 90 + 20 * math.sin(t)] for t in angles]
        ellipse = run_tool("fit_ellipse_points", None, {}, {"points": ellipse_pts})
        self.assertEqual((ellipse.status, ellipse.branch), ("ok", "found"))
        self.assertAlmostEqual(ellipse.outputs["cx"], 120, delta=0.2)
        self.assertAlmostEqual(ellipse.outputs["cy"], 90, delta=0.2)
        self.assertAlmostEqual(ellipse.outputs["major"], 90, delta=0.5)
        self.assertAlmostEqual(ellipse.outputs["minor"], 40, delta=0.5)

    def test_fitting_degenerate_inputs_are_ng_but_missing_input_is_error(self):
        too_few = run_tool("fit_circle_points", None, {}, {"points": [[1, 1], [2, 2]]})
        self.assertEqual((too_few.status, too_few.branch), ("ng", "not_found"))
        collinear = run_tool("fit_circle_points", None, {}, {"points": [[0, 0], [10, 10], [20, 20], [30, 30]]})
        self.assertEqual((collinear.status, collinear.branch), ("ng", "not_found"))
        with self.assertRaises(ToolError):
            run_tool("fit_line_points", None, {})

    def test_contour_output_can_feed_fit_line_in_graph_validation(self):
        graph = {
            "nodes": [
                n("src", "image_source", mode="input"),
                n("thr", "threshold", method="fixed", threshold=100),
                n("contours", "contour_find", threshold_method="none", min_area=10),
                n("fit", "fit_line_points"),
            ],
            "edges": [
                e("src", "thr", "image", "image"),
                e("thr", "contours", "image", "image"),
                e("contours", "fit", "contours", "contours"),
            ],
        }
        validated = validate_graph(graph)
        self.assertEqual(validated["edges"][-1]["target_handle"], "contours")

    def test_label_to_mask_keeps_requested_labels_only(self):
        labels = np.array([[0, 1, 2], [2, 3, 4]], dtype=np.uint16)
        r = run_tool("label_to_mask", None, {"values": "2, 4"}, {"labels": labels})
        self.assertEqual(r.outputs["pixels"], 3)
        self.assertEqual(r.outputs["mask"].tolist(), [[0, 0, 255], [255, 0, 255]])

        inv = run_tool("label_to_mask", None, {"values": "2", "invert": True}, {"labels": labels})
        self.assertEqual(inv.outputs["pixels"], 4)
        with self.assertRaisesMessage(ToolError, "integer"):
            run_tool("label_to_mask", None, {"values": "1"}, {"labels": labels.astype(np.float32) + 0.25})

    def test_defects_to_geometry_outputs_centres_boxes_and_spans(self):
        defects = [
            {"rect": {"shape": "rotated_rect", "cx": 20, "cy": 30, "w": 12, "h": 4, "angle": 0}},
            {"span": [[1, 2], [3, 4]], "rect": {"shape": "rect", "x": 1, "y": 2, "w": 8, "h": 6}},
            {"bad": True},
        ]
        centres = run_tool("defects_to_geometry", None, {"output": "centres"}, {"defects": defects})
        self.assertEqual(centres.outputs["count"], 2)
        self.assertEqual(centres.outputs["points"][0], [20.0, 30.0])

        boxes = run_tool("defects_to_geometry", None, {"output": "boxes"}, {"defects": defects})
        self.assertEqual(boxes.outputs["count"], 2)
        self.assertEqual(len(boxes.outputs["points"]), 8)
        self.assertEqual(len(boxes.outputs["contours"]), 2)

        spans = run_tool("defects_to_geometry", None, {"output": "spans"}, {"defects": defects})
        self.assertEqual(spans.outputs["count"], 2)
        self.assertIn([1.0, 2.0], spans.outputs["points"])


class Stage4ExpectedStateTests(SimpleTestCase):
    @staticmethod
    def _scene_with_square(present: bool = True) -> tuple[np.ndarray, np.ndarray]:
        img = blank(120, 160, 30)
        if present:
            cv2.rectangle(img, (55, 45), (84, 74), 220, -1)
            cv2.circle(img, (65, 55), 6, 60, -1)
            cv2.line(img, (55, 74), (84, 45), 120, 2)
        tpl = np.full((30, 30), 220, np.uint8)
        cv2.circle(tpl, (10, 10), 6, 60, -1)
        cv2.line(tpl, (0, 29), (29, 0), 120, 2)
        return img, tpl

    def test_template_match_expected_state_table(self):
        found_img, tpl = self._scene_with_square(True)
        blank_img, _ = self._scene_with_square(False)
        for expected, image, want_status, want_detected in [
            ("present", found_img, "ok", True),
            ("present", blank_img, "ng", False),
            ("absent", found_img, "ng", True),
            ("absent", blank_img, "ok", False),
        ]:
            r = run_tool("template_match", image, {"threshold": 0.9, "expected": expected}, {"template_image": tpl})
            self.assertEqual(r.status, want_status, (expected, r.message))
            self.assertEqual(r.outputs["detected"], want_detected)
            self.assertTrue(r.outputs["valid"])

        invalid = run_tool("template_match", blank_img, {"threshold": 0.9, "expected": "absent", "roi": {"shape": "rect", "x": 0, "y": 0, "w": 80, "h": 80}},
                           {"template_image": tpl, "_transform": None})
        self.assertEqual(invalid.status, "ng")
        self.assertFalse(invalid.outputs["valid"])

    def test_blob_expected_state_table(self):
        found = blank(100, 120, 0)
        cv2.circle(found, (50, 50), 12, 255, -1)
        empty = blank(100, 120, 0)
        for expected, image, want_status, want_detected in [
            ("present", found, "ok", True),
            ("present", empty, "ng", False),
            ("absent", found, "ng", True),
            ("absent", empty, "ok", False),
        ]:
            r = run_tool("blob", image, {"threshold_method": "none", "min_area": 20, "min_count": 0, "expected": expected})
            self.assertEqual(r.status, want_status, (expected, r.message))
            self.assertEqual(r.outputs["detected"], want_detected)
            self.assertTrue(r.outputs["valid"])

        invalid = run_tool("blob", empty, {"threshold_method": "none", "min_area": 20, "min_count": 0, "expected": "absent",
                                           "roi": {"shape": "rect", "x": 0, "y": 0, "w": 50, "h": 50}}, {"_transform": None})
        self.assertEqual(invalid.status, "ng")
        self.assertFalse(invalid.outputs["valid"])

    def test_text_presence_expected_state_table(self):
        roi = {"shape": "rect", "x": 20, "y": 20, "w": 80, "h": 50}
        printed = blank(90, 130, 230)
        cv2.putText(printed, "OK", (30, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 20, 2, cv2.LINE_AA)
        clean = blank(90, 130, 230)
        for expected, image, want_status, want_detected in [
            ("present", printed, "ok", True),
            ("present", clean, "ng", False),
            ("absent", printed, "ng", True),
            ("absent", clean, "ok", False),
        ]:
            r = run_tool("text_presence", image, {"roi": roi, "min_ratio": 0.02, "max_ratio": 0.5, "expected": expected})
            self.assertEqual(r.status, want_status, (expected, r.message))
            self.assertEqual(r.outputs["detected"], want_detected)
            self.assertTrue(r.outputs["valid"])

        invalid = run_tool("text_presence", clean, {"roi": roi, "min_ratio": 0.02, "max_ratio": 0.5, "expected": "absent"}, {"_transform": None})
        self.assertEqual(invalid.status, "ng")
        self.assertFalse(invalid.outputs["valid"])


class Stage4InspectionEngineTests(SimpleTestCase):
    def _summary_graph(self, expressions: list[str], expected_count: int) -> dict:
        nodes = [n(f"f{i}", "formula", expression=expr) for i, expr in enumerate(expressions, 1)]
        nodes.append(n("summary", "inspection_summary", expected_count=expected_count))
        edges = [e(f"f{i}", "summary", "result", "results") for i in range(1, len(expressions) + 1)]
        return {"nodes": nodes, "edges": edges}

    def test_inspection_summary_engine_ok_failed_and_missing_cases(self):
        ok = run_graph(self._summary_graph(["True", "1 < 2", "bool(1)"], 3))
        self.assertEqual(ok.status, "ok")
        self.assertEqual(ok.nodes["summary"].outputs["received"], 3)
        self.assertEqual(ok.nodes["summary"].outputs["passed"], 3)

        failed = run_graph(self._summary_graph(["True", "False", "True"], 3))
        self.assertEqual(failed.status, "ng")
        self.assertEqual(failed.nodes["summary"].branch, "ng")
        self.assertEqual(failed.nodes["summary"].outputs["passed"], 2)

        missing_graph = {
            "nodes": [
                n("pass1", "formula", expression="True"),
                n("pass2", "formula", expression="True"),
                n("gate_value", "formula", expression="0"),
                n("gate", "if_number", operator="gt", threshold=1),
                n("skipped", "formula", expression="True"),
                n("summary", "inspection_summary", expected_count=3),
            ],
            "edges": [
                e("gate_value", "gate", "value", "value"),
                e("gate", "skipped", "true", "_flow"),
                e("pass1", "summary", "result", "results"),
                e("pass2", "summary", "result", "results"),
                e("skipped", "summary", "result", "results"),
            ],
        }
        missing = run_graph(missing_graph)
        self.assertEqual(missing.status, "ng")
        self.assertEqual(missing.nodes["skipped"].status, "skipped")
        self.assertEqual(missing.nodes["summary"].outputs["received"], 2)
        self.assertEqual(missing.nodes["summary"].outputs["missing"], 1)

    def test_polar_edge_defects_restore_through_defect_geometry(self):
        image = np.zeros((400, 400), np.uint8)
        cv2.circle(image, (200, 200), 120, 220, -1)
        cv2.ellipse(image, (200, 200), (120, 120), 0, 20, 35, 0, -1)
        image = cv2.GaussianBlur(image, (0, 0), 0.8)
        graph = {
            "nodes": [
                n("src", "image_source", mode="input"),
                n("unwrap", "polar_unwrap", roi={"shape": "annulus", "cx": 200, "cy": 200, "r_inner": 80, "r_outer": 130, "a0": 0, "a1": 90},
                  angle_step="1", direction="cw", radial_step=1),
                n("edge", "edge_defect", roi={"shape": "rect", "x": 0, "y": 30, "w": 90, "h": 35},
                  polarity="light_to_dark", calipers=90, search=30, threshold=2.5, fracture_run=2),
                n("geom", "defects_to_geometry", output="centres"),
                n("restore", "polar_restore"),
            ],
            "edges": [
                e("src", "unwrap", "image", "image"),
                e("unwrap", "edge", "image", "image"),
                e("edge", "geom", "defects", "defects"),
                e("unwrap", "restore", "mapping", "mapping"),
                e("geom", "restore", "points", "points"),
            ],
        }
        report = run_graph(graph, image)
        self.assertEqual(report.nodes["edge"].outputs["count"], 1)
        self.assertEqual(report.nodes["geom"].outputs["count"], 1)
        self.assertEqual(report.nodes["restore"].outputs["count"], 1)
        self.assertAlmostEqual(report.nodes["restore"].outputs["first_angle"], 27.8, delta=1.0)
        self.assertAlmostEqual(report.nodes["restore"].outputs["first_radius"], 127.5, delta=1.5)
