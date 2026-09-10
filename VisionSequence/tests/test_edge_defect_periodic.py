"""封閉展開序列的接縫回歸：合成真值來自解析式，不依實作產生。"""

import math

import numpy as np
from django.test import SimpleTestCase

from apps.vision import demo
from tests.test_inspect import run_graph


def rim_image(angle=0, cx=500, cy=350, dtype=np.uint8):
    y, x = np.ogrid[:701, :1001]
    radius = np.hypot(x - cx, y - cy)
    theta = np.degrees(np.arctan2(y - cy, x - cx))
    outer = np.where(np.abs((theta - angle + 180) % 360 - 180) <= 10, 240., 250.)
    cover = np.clip(radius - 229.5, 0, 1) * np.clip(outer + .5 - radius, 0, 1)
    return (cover * (55000 if dtype == np.uint16 else 220)).astype(dtype)


def periodic_graph(start=0, direction="cw"):
    graph = demo.polar_edge_check_flow(None)
    graph["nodes"][1]["params"].update(start_angle=start, direction=direction)
    graph["nodes"][2]["params"].update(roi={"shape": "rect", "x": 0, "y": 20, "w": 360, "h": 20},
                                        calipers=360, caliper_width=1, closed_sequence=True)
    return graph


class PeriodicEdgeTests(SimpleTestCase):
    def test_step_at_period_boundary_is_detected(self):
        from tests._helpers import run_tool
        y, x = np.ogrid[:101, :181]
        image = (np.clip(y - (30 + 20 * x / 180) + .5, 0, 1) * 220).astype(np.uint8)
        result = run_tool("edge_defect", image, {"roi": {"shape": "rect", "x": 0, "y": 35, "w": 181, "h": 10},
                          "closed_sequence": True, "calipers": 181, "caliper_width": 1, "search": 60,
                          "threshold": 0, "step_threshold": 5, "fracture_run": 0, "min_width": 2})
        self.assertEqual(result.outputs["count"], 1)
        defect = result.outputs["defects"][0]
        self.assertEqual(defect["type"], "step")
        self.assertGreater(defect["start"], defect["end"])
        self.assertLess(abs(defect["span"][1][0] - defect["span"][0][0]), 3)

    def test_closed_pair_and_single_modes_across_bit_depths(self):
        for dtype in (np.uint8, np.uint16, np.float32):
            for mode in ("single", "pair"):
                with self.subTest(dtype=dtype, mode=mode):
                    graph = periodic_graph()
                    graph["nodes"][2]["params"].update(mode=mode, search=60, pair_polarity="bright", polarity="any" if mode == "pair" else "light_to_dark")
                    report = run_graph(graph, rim_image(dtype=dtype))
                    self.assertEqual(report.nodes["edge"].outputs["count"], 1)
                    point = report.nodes["restore"].outputs["points"][0]
                    self.assertLessEqual(math.dist(point, [735 if mode == "pair" else 740, 350]), 1.5)

    def test_one_defect_and_correct_center_for_eight_starts_in_both_directions(self):
        for direction in ("cw", "ccw"):
            for start in (0, 5, 40, 90, 180, 270, 350, 355):
                with self.subTest(direction=direction, start=start):
                    report = run_graph(periodic_graph(start, direction), rim_image())
                    self.assertEqual(report.nodes["edge"].outputs["count"], 1)
                    points = report.nodes["restore"].outputs["points"]
                    self.assertEqual(len(points), 1)
                    error = math.dist(points[0], [740, 350])
                    self.assertLessEqual(error, 1.5)
                    print(f"periodic start={start:3d} direction={direction} count=1 error_px={error:.6f}")

    def test_default_off_matches_explicit_off_on_odd_images(self):
        for dtype in (np.uint8, np.uint16, np.float32):
            for mode in ("single", "pair"):
                graph = demo.polar_edge_check_flow(None)
                graph["nodes"][2]["params"]["mode"] = mode
                before = run_graph(graph, rim_image(40, dtype=dtype))
                graph["nodes"][2]["params"]["closed_sequence"] = False
                after = run_graph(graph, rim_image(40, dtype=dtype))
                for key in ("edge", "defects", "restore"):
                    self.assertEqual(before.nodes[key].message, after.nodes[key].message)
                    self.assertEqual(before.nodes[key].status, after.nodes[key].status)
                    self.assertEqual(before.nodes[key].overlays, after.nodes[key].overlays)
                self.assertEqual(before.nodes["edge"].outputs["defects"], after.nodes["edge"].outputs["defects"])
                self.assertEqual(before.nodes["restore"].outputs["points"], after.nodes["restore"].outputs["points"])
