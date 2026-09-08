"""call_flow、for_each 與 tile 的端到端測試。"""

from __future__ import annotations

import time
from unittest import mock

import numpy as np
from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.vision import engine
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.models import Flow
from apps.vision.runner import runner
from apps.vision.tools.base import Port, Result, Tool, register, unregister
from apps.vision.tools.builtin.subflow import MAX_SUBFLOW_DEPTH, tile_regions


def n(nid: str, ntype: str, **params):
    return {"id": nid, "type": ntype, "params": params}


def e(src: str, dst: str, sh: str = "", th: str = ""):
    return {"id": f"{src}_{sh}_{dst}_{th}", "source": src, "target": dst, "source_handle": sh, "target_handle": th}


class RegionsTool(Tool):
    key = "_test_regions"
    label = "regions"
    category = "logic"
    inputs = []
    outputs = [Port("regions", "Regions", "list")]
    allows_unconnected = True
    regions: list[dict] = []

    def execute(self, ctx):
        return Result(outputs={"regions": [dict(r) for r in type(self).regions]})


@override_settings(VISION={**settings.VISION, "PERSIST_RUNS": False, "MAX_WORKERS": 6})
class SubflowTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register(RegionsTool())

    @classmethod
    def tearDownClass(cls):
        unregister(RegionsTool.key)
        super().tearDownClass()

    def setUp(self):
        RegionsTool.regions = []
        for fid in list(runner._runtimes):
            runner.forget(fid)

    def tearDown(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)

    def flow(self, name: str, graph: dict, **fields) -> Flow:
        return Flow.objects.create(name=name, graph=validate_graph(graph), **fields)

    def test_tile_non_overlap_covers_whole_image_once(self):
        regions = tile_regions(120, 90, rows=3, cols=4, overlap=0)

        self.assertEqual(len(regions), 12)
        self.assertTrue(all(r["w"] == 30 and r["h"] == 30 for r in regions))
        canvas = np.zeros((90, 120), dtype=np.uint8)
        for r in regions:
            x0, y0, w, h = int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"])
            canvas[y0:y0 + h, x0:x0 + w] += 1
        self.assertEqual(int(canvas.min()), 1)
        self.assertEqual(int(canvas.max()), 1)

    def test_tile_overlap_ratio_has_exact_adjacent_overlap(self):
        regions = tile_regions(160, 90, rows=3, cols=4, overlap=0.25)
        a, b = regions[0], regions[1]
        overlap_w = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
        c = regions[0]
        d = regions[4]
        overlap_h = min(c["y"] + c["h"], d["y"] + d["h"]) - max(c["y"], d["y"])

        self.assertEqual(overlap_w, 10.0)
        self.assertEqual(overlap_h, 7.5)

    def test_call_flow_merges_named_outputs_with_prefix_and_does_not_record_child(self):
        child = self.flow("child-output", {
            "nodes": [n("f", "formula", expression="21"), n("o", "output", name="value"), n("j", "judge", verdict="ok")],
            "edges": [e("f", "o", "value", "value")],
        })
        parent = self.flow("parent-call", {
            "nodes": [n("c", "call_flow", target_flow_id=child.id, prefix="child_")],
            "edges": [],
        })

        report = runner.run_sync(parent, trigger="api")

        self.assertEqual(report.status, "ok")
        self.assertEqual(report.outputs["child_value"], 21.0)
        self.assertEqual(report.outputs["child_judge"], "OK")
        self.assertEqual(report.nodes["c"].outputs["outputs"]["value"], 21.0)
        self.assertEqual(runner.runtime(child.id).stats.runs, 0)

    def test_child_ng_takes_parent_ng_branch(self):
        child = self.flow("child-ng", {"nodes": [n("j", "judge", verdict="ng")], "edges": []})
        parent = self.flow("parent-branch", {
            "nodes": [
                n("c", "call_flow", target_flow_id=child.id),
                n("ok", "judge", verdict="ok", label="ok-path"),
                n("ng", "judge", verdict="ng", label="ng-path"),
            ],
            "edges": [e("c", "ok", "ok", "_flow"), e("c", "ng", "ng", "_flow")],
        })

        report = runner.run_sync(parent, trigger="api")

        self.assertEqual(report.status, "ng")
        self.assertEqual(report.nodes["c"].branch, "ng")
        self.assertEqual(report.nodes["ok"].status, "skipped")
        self.assertEqual(report.nodes["ng"].status, "ng")
        self.assertEqual(report.outputs["judge_label"], "ng-path")

    def test_call_self_loop_is_blocked(self):
        flow = self.flow("self-call", {"nodes": [], "edges": []})
        flow.graph = validate_graph({"nodes": [n("c", "call_flow", target_flow_id=flow.id)], "edges": []})
        flow.save(update_fields=["graph"])

        report = runner.run_sync(flow, trigger="api")

        self.assertEqual(report.status, "failed")
        self.assertIn("cannot trigger itself", report.nodes["c"].message)

    def test_trigger_then_call_loop_is_blocked_by_shared_chain(self):
        a = self.flow("loop-a", {"nodes": [], "edges": []})
        b = self.flow("loop-b", {"nodes": [], "edges": []})
        a.graph = validate_graph({"nodes": [n("to_b", "trigger_flow", target_flow_id=b.id, mode="sync")], "edges": []})
        b.graph = validate_graph({"nodes": [n("to_a", "call_flow", target_flow_id=a.id)], "edges": []})
        a.save(update_fields=["graph"])
        b.save(update_fields=["graph"])

        report = runner.run_sync(a, trigger="api")

        self.assertEqual(report.status, "failed")
        self.assertIn("Trigger chain would loop", report.nodes["to_b"].message)

    def test_nested_depth_limit_is_blocked(self):
        flows = [self.flow(f"depth-{i}", {"nodes": [], "edges": []}) for i in range(MAX_SUBFLOW_DEPTH + 2)]
        flows[-1].graph = validate_graph({"nodes": [n("j", "judge", verdict="ok")], "edges": []})
        flows[-1].save(update_fields=["graph"])
        for index, flow in enumerate(flows[:-1]):
            flow.graph = validate_graph({"nodes": [n("c", "call_flow", target_flow_id=flows[index + 1].id)], "edges": []})
            flow.save(update_fields=["graph"])

        report = runner.run_sync(flows[0], trigger="api")

        self.assertEqual(report.status, "failed")
        self.assertIn(f"Nested flow depth is limited to {MAX_SUBFLOW_DEPTH}", report.error)

    def test_for_each_regions_counts_and_restores_coordinates(self):
        img = np.zeros((50, 100), dtype=np.uint8)
        img[10, 15] = 255
        img[12, 48] = 255
        RegionsTool.regions = [
            {"shape": "rect", "x": 10, "y": 5, "w": 20, "h": 20},
            {"shape": "rect", "x": 40, "y": 5, "w": 20, "h": 20},
            {"shape": "rect", "x": 70, "y": 5, "w": 20, "h": 20},
        ]
        child = self.flow("child-blob", {
            "nodes": [
                n("src", "image_source", mode="input"),
                n("b", "blob", threshold_method="none", min_area=1, max_count=1, min_count=1, sort_by="x"),
                n("ox", "output", name="cx"),
                n("oy", "output", name="cy"),
            ],
            "edges": [e("src", "b", "image", "image"), e("b", "ox", "first_cx", "value"), e("b", "oy", "first_cy", "value")],
        })
        parent = self.flow("parent-each", {
            "nodes": [
                n("src", "image_source", mode="input"),
                n("r", RegionsTool.key),
                n("each", "for_each", target_flow_id=child.id, source="regions", max_items=3),
            ],
            "edges": [e("src", "each", "image", "image"), e("r", "each", "regions", "regions")],
        })

        report = runner.run_sync(parent, trigger="api", input_image=img)
        direct = self.flow("direct-blob", {
            "nodes": [n("src", "image_source", mode="input"), n("b", "blob", threshold_method="none", min_area=1, max_count=10, min_count=1, sort_by="x")],
            "edges": [e("src", "b", "image", "image")],
        })
        direct_report = runner.run_sync(direct, trigger="api", input_image=img)

        items = report.nodes["each"].outputs["items"]
        found = [row["outputs"] for row in items if row["status"] == "ok"]
        direct_centres = [[b["cx"], b["cy"]] for b in direct_report.nodes["b"].outputs["blobs"]]
        restored = [[row["cx"], row["cy"]] for row in found]

        self.assertEqual(report.nodes["each"].outputs["count"], 3)
        self.assertEqual(report.nodes["each"].outputs["ok_count"], 2)
        self.assertEqual(report.nodes["each"].outputs["ng_count"], 1)
        self.assertEqual(restored, direct_centres)

    def test_preview_and_flow_id_zero_do_not_execute_child(self):
        graph = validate_graph({"nodes": [n("c", "call_flow", target_flow_id=999)], "edges": []})
        compiled = compile_graph(graph)

        with mock.patch("apps.vision.tools.builtin.subflow._run_child") as run_child:
            preview = engine.execute(compiled, flow_id=1, flow_version=1, trigger="preview", preview=True,
                                     grab=lambda _sid: None, asset_path=lambda _aid: None,
                                     deadline=time.perf_counter() + 10)
            sandbox = engine.execute(compiled, flow_id=0, flow_version=1, trigger="bench",
                                     grab=lambda _sid: None, asset_path=lambda _aid: None,
                                     deadline=time.perf_counter() + 10)

        self.assertEqual(preview.nodes["c"].message, "Would call flow 999")
        self.assertEqual(sandbox.nodes["c"].message, "Would call flow 999")
        run_child.assert_not_called()
