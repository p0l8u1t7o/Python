"""杯口表單驗收的物理真值與退化輸入回歸。"""

import json
import math
import tempfile
from pathlib import Path

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision import fixed_images, inspect
from apps.vision.tasks import get
from apps.vision.tools import roi
from tests._helpers import run_tool
from tests.test_inspect import base_graph, diameter_task, run_graph, stage8_task


def cup_scene(angle=0, dx=0, dy=0, *, mark=True):
    """以平台 ROI 畫剛性杯件；旋轉正值為畫面順時針，所有零件一起移動。"""
    h, w = 1101, 1201
    image = np.full((h * 3, w * 3), 50, np.uint8)
    regions = [(dict(shape="circle", cx=600, cy=550, r=180), 220),
               (dict(shape="circle", cx=600, cy=550, r=140), 50),
               (dict(shape="rotated_rect", cx=762, cy=550, w=44, h=70, angle=0), 220)]
    if mark:
        regions.extend([(dict(shape="rotated_rect", cx=200, cy=300, w=91, h=11, angle=0), 240),
                        (dict(shape="rotated_rect", cx=200, cy=300, w=11, h=73, angle=0), 240)])
    for region, grey in regions:
        moved = roi.transform_region(region, dx, dy, angle, pivot=(200, 300))
        scaled = {k: v * 3 + 1 if k in ("cx", "cy") else v * 3 if k in ("r", "w", "h") else v for k, v in moved.items()}
        image[roi.mask_for(scaled, w * 3, h * 3) > 0] = grey
    return cv2.resize(image, (w, h), interpolation=cv2.INTER_AREA)


class Stage9FixTests(SimpleTestCase):
    def test_background_padded_mark_needs_joint_pose_refinement(self):
        def mark(angle=0, dx=0, dy=0):
            image = np.full((501, 701), 50, np.uint8)
            for region in (dict(shape="rotated_rect", cx=180, cy=160, w=91, h=11, angle=0),
                           dict(shape="rotated_rect", cx=180, cy=160, w=11, h=73, angle=0)):
                image[roi.mask_for(roi.transform_region(region, dx, dy, angle, pivot=(180, 160)), 701, 501) > 0] = 240
            return image
        template = mark()[10:311, 30:331]
        params = {"angle_range": 60, "threshold": .7}
        legacy = run_tool("template_match", mark(20, 50, 30), params, {"template_image": template})
        refined = run_tool("template_match", mark(20, 50, 30), {**params, "refine_rotation": True}, {"template_image": template})
        self.assertGreater(abs(legacy.outputs["best_angle"] - 20), 1)
        self.assertLess(abs(refined.outputs["best_angle"] - 20), 1)
        self.assertGreaterEqual(refined.outputs["best_score"], .7)

    def test_gap_length_degrees_and_calibrated_arc_length(self):
        y, x = np.ogrid[:701, :1001]
        radius = np.hypot(x - 500, y - 350)
        theta = np.degrees(np.arctan2(y - 350, x - 500))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scale.json"
            path.write_text(json.dumps({"image_size": [1001, 701], "world": {"kind": "scale", "matrix": [[.05, 0, 0], [0, .05, 0], [0, 0, 1]], "mm_per_px": .05}}), encoding="utf-8")
            for unit, limit, width, expected in [("deg", 8, 4, 0), ("deg", 8, 12, 1), ("mm", 2, 4, 0), ("mm", 2, 12, 1), ("mm", 3, 12, 0), ("mm", 3, 20, 1)]:
                for direction in ("cw", "ccw"):
                    outer = np.where(abs(theta) < width / 2, 210, 250)
                    image = (np.clip(radius - 229.5, 0, 1) * np.clip(outer + .5 - radius, 0, 1) * 220).astype(np.uint8)
                    graph = inspect.build(base_graph(), stage8_task("inspect_circular_surface", min_length=limit, unit=unit, calibration="scale" if unit == "mm" else "", direction=direction))
                    task = inspect.read(graph)["tasks"][0]
                    self.assertFalse(task["custom"], task["reasons"])
                    self.assertEqual(task["fields"]["min_length"], limit)
                    self.assertEqual(task["fields"]["unit"], unit)
                    report = run_graph(graph, image, {"scale": str(path)})
                    self.assertNotEqual(report.status, "failed", report.error)
                    self.assertEqual(report.nodes["item_defect"].outputs["count"], expected, (unit, limit, width, direction))
                    reading = inspect.evidence(graph, report)[0]
                    self.assertIn(f"minimum {limit:.3f} {unit}", reading["reason"])
                    self.assertNotIn("worst 0.00px", reading["reason"])
                    if expected:
                        self.assertEqual(report.nodes["item_defect"].outputs["defects"][0]["type"], "fracture")
                    print(f"gap={width}deg arc={250 * math.radians(width) * .05:.6f}mm minimum={limit}{unit} direction={direction} verdict={report.status} count={expected} {reading['reason']}")
            updated = inspect.update(graph, {"task_id": "item", "fields": {"unit": "deg", "calibration": "", "min_length": 7}})
            self.assertEqual(inspect.read(updated)["tasks"][0]["fields"]["min_length"], 7)
            self.assertNotIn("item_scale", {n["id"] for n in updated["nodes"]})

    def test_gap_filter_is_opt_in_and_applies_to_all_fault_kinds(self):
        x = np.arange(301)
        for mode, params, height in [
            ("fracture", {}, np.where((x > 110) & (x < 140), 110, 50)),
            ("dislocation", {}, np.where((x > 110) & (x < 140), 60, 50)),
            ("step", {"threshold": 0, "step_threshold": 3}, np.where(x > 140, 60, 50)),
            ("width", {"mode": "pair", "width_max": 22, "threshold": 0}, np.where((x > 110) & (x < 140), 70, 50)),
        ]:
            image = (np.arange(121)[:, None] < height).astype(np.uint8) * 220
            if mode == "width":
                image[:30] = 0
            base = {"roi": {"shape": "rect", "x": 0, "y": 45, "w": 300, "h": 10}, "calipers": 301, "search": 70,
                    "baseline": "reference", "threshold": 3, "min_width": 1, "caliper_width": 1, **params}
            raw = run_tool("edge_defect", image, base)
            self.assertIn(mode, {d["type"] for d in raw.outputs["defects"]})
            filtered = run_tool("edge_defect", image, {**base, "filter_fractures": True, "min_width": 80})
            self.assertEqual(filtered.outputs["count"], 0, mode)
            if mode == "fracture":
                legacy = run_tool("edge_defect", image, {**base, "min_width": 80})
                self.assertGreater(legacy.outputs["count"], 0)

    def test_circular_direction_for_displacements_and_missing_edges(self):
        y, x = np.ogrid[:701, :1001]
        radius = np.hypot(x - 500, y - 350)
        theta = np.degrees(np.arctan2(y - 350, x - 500))
        for delta in (-40, -10, 10, 40):
            outer = np.where(abs(theta) < 6, 250 + delta, 250)
            image = (np.clip(radius - 229.5, 0, 1) * np.clip(outer + .5 - radius, 0, 1) * 220).astype(np.uint8)
            for direction in ("cw", "ccw"):
                for side in ("inward", "outward", "both"):
                    graph = inspect.build(base_graph(), stage8_task("inspect_circular_surface", direction=direction, defect_direction=side))
                    report = run_graph(graph, image)
                    expected = side == "both" or (side == "inward") == (delta < 0)
                    self.assertNotEqual(report.status, "failed", report.error)
                    self.assertEqual(report.nodes["item_defect"].outputs["count"], int(expected), (delta, direction, side))

    def test_required_locator_default_remains_in_summary_after_task_removal(self):
        graph = inspect.build(base_graph(), {"kind": "locate_part", "task_id": "loc", "fields": {"template_images": []}})
        locator = inspect.read(graph)["tasks"][0]
        self.assertTrue(locator["required"])
        graph = inspect.build(graph, diameter_task("remove_me", locator="loc"))
        graph = inspect.build(graph, diameter_task("keep_me"))
        result = inspect.remove(graph, "remove_me")
        self.assertTrue(result["removed"])
        summary = next(n for n in result["graph"]["nodes"] if n["id"] == "inspection_summary")
        self.assertEqual(summary["params"]["expected_count"], 2)
        self.assertEqual(sum(e["target"] == "inspection_summary" for e in result["graph"]["edges"]), 2)

    def test_padded_mark_rigid_refinement_and_cup_measurements(self):
        image = cup_scene()
        template = image[150:451, 50:351].copy()
        desc = fixed_images.store(template, "Distinctive cup mark")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scale.json"
            path.write_text(json.dumps({"image_size": [1201, 1101], "world": {"kind": "scale", "matrix": [[.05, 0, 0], [0, .05, 0], [0, 0, 1]], "mm_per_px": .05}}), encoding="utf-8")
            assets = {"cal": str(path)}
            graph = inspect.build(base_graph(), {"kind": "locate_part", "task_id": "loc", "fields": {
                "template_images": [desc], "allow_rotation": True, "angle_range": 60,
                "ref_x": 200.5, "ref_y": 300.5}})
            for name, edge_name, diameter in [("outer", "outer", 360), ("inner", "inner", 280)]:
                task = diameter_task(name, edge_name=edge_name, nominal=diameter * .05, lower=-.2, upper=.2, locator="loc")
                task["fields"].update(roi={"shape": "annulus", "cx": 600, "cy": 550, "r_inner": 130, "r_outer": 190}, unit="mm", calibration="cal")
                graph = inspect.build(graph, task)
            graph = inspect.build(graph, stage8_task("measure_distance", roi={"shape": "rotated_rect", "cx": 760, "cy": 550, "w": 95, "h": 20, "angle": 0},
                                                   locator="loc", unit="mm", calibration="cal", nominal=2.2, upper_tol=.2, lower_tol=-.2))
            graph = inspect.build(graph, {"kind": "inspect_circular_surface", "task_id": "rim", "fields": {
                "roi": {"shape": "annulus", "cx": 600, "cy": 550, "r_inner": 155, "r_outer": 205}, "locator": "loc"}})
            baseline = run_graph(graph, image, assets)
            self.assertNotEqual(baseline.status, "failed", baseline.error)
            ports = [("outer_find", "diameter_world"), ("inner_find", "diameter_world"), ("item_cal", "width_world")]
            for angle in (-45, -20, 20, 45):
                with self.subTest(angle=angle):
                    moved = cup_scene(angle, 50, 30)
                    report = run_graph(graph, moved, assets)
                    self.assertNotEqual(report.status, "failed", report.error)
                    find = report.nodes["loc_find"].outputs
                    angle_error = abs(find["best_angle"] - angle)
                    expected = roi.transform_region({"shape": "circle", "cx": 200.5, "cy": 300.5, "r": 1}, 50, 30, angle, pivot=(200, 300))
                    position_error = math.dist([find["best_x"], find["best_y"]], [expected["cx"], expected["cy"]])
                    differences = [abs(report.nodes[n].outputs[p] - baseline.nodes[n].outputs[p]) for n, p in ports]
                    print(f"rotation={angle:+} angle_error={angle_error:.6f} position_error_px={position_error:.6f} measurement_delta_mm={differences}")
                    self.assertLessEqual(angle_error, 1)
                    self.assertLessEqual(position_error, 1)
                    self.assertTrue(all(d <= .02 for d in differences), differences)
                    self.assertEqual(report.nodes["rim_defect"].outputs["count"], 0)

    def test_missing_location_and_edges_are_not_execution_errors(self):
        scalar = run_tool("distance", inputs={"a": None, "b": None, "ax": 1, "ay": 2, "bx": 4, "by": 6})
        self.assertEqual(scalar.status, "ok")
        self.assertEqual(scalar.outputs["distance"], 5)
        desc = fixed_images.store(cup_scene()[250:351, 140:261], "Mark")
        graph = inspect.build(base_graph(), {"kind": "locate_part", "task_id": "loc", "fields": {"template_images": [desc]}})
        for name, mode in [("wall", "edge_pair"), ("centres", "hole_centres")]:
            task = stage8_task("measure_distance", mode=mode, locator="loc", roi_a={"shape": "circle", "cx": 500, "cy": 350, "r": 100}, roi_b={"shape": "circle", "cx": 550, "cy": 350, "r": 100})
            task["task_id"] = name
            graph = inspect.build(graph, task)
        report = run_graph(graph, np.full((701, 1001), 50, np.uint8))
        self.assertEqual(report.status, "ng", report.error)
        readings = {r["task_id"]: r for r in inspect.evidence(graph, report)}
        for name in ("wall", "centres"):
            self.assertEqual(readings[name]["verdict"], "locate_failed")
            self.assertIsNone(readings[name]["value"])
        for mode in ("edge_pair", "hole_centres"):
            isolated = inspect.build(base_graph(), stage8_task("measure_distance", mode=mode,
                calibration="scale", unit="mm", roi_a={"shape": "circle", "cx": 500, "cy": 350, "r": 100}, roi_b={"shape": "circle", "cx": 550, "cy": 350, "r": 100}))
            report = run_graph(isolated, np.full((701, 1001), 50, np.uint8))
            self.assertEqual(report.status, "ng", report.error)
            self.assertEqual(inspect.evidence(isolated, report)[0]["verdict"], "not_found")

    def test_task_order_required_locator_and_circular_name_roundtrip(self):
        graph = inspect.build(base_graph(), diameter_task("z_first"))
        graph = inspect.build(graph, diameter_task("a_second"))
        self.assertEqual([t["task_id"] for t in inspect.read(graph)["tasks"]], ["z_first", "a_second"])
        self.assertTrue(get("locate_part").fields["required"].default)
        graph = inspect.build(base_graph(), stage8_task("inspect_circular_surface", result_name="cup_gaps", min_length=2.5, defect_direction="outward"))
        task = inspect.read(graph)["tasks"][0]
        self.assertEqual(task["fields"]["result_name"], "cup_gaps")
        self.assertEqual(task["fields"]["min_length"], 2.5)
        self.assertEqual(task["fields"]["defect_direction"], "outward")
        self.assertFalse(task["custom"])
