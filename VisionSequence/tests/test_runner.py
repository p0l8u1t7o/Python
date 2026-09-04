"""引擎 + runner：分支 gating、停用直通、錯誤處理、並行、影像快取、事件。"""

from __future__ import annotations

import threading
import time

import numpy as np
from django.test import TestCase, override_settings

from apps.core.errors import RateLimited
from apps.vision import engine
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.images import store
from apps.vision.models import Flow, ImageSource
from apps.vision.runner import bus, runner
from apps.vision.tools.base import Port, Result, Tool, register, unregister


def n(nid, ntype, **params):
    return {"id": nid, "type": ntype, "params": params}


def e(s, t, sh="", th=""):
    return {"source": s, "target": t, "source_handle": sh, "target_handle": th}


class BoomTool(Tool):
    key = "_test_boom"
    label = "boom"
    inputs = [Port("image", "影像", "image")]
    outputs = [Port("image", "影像", "image")]

    def execute(self, ctx):
        raise RuntimeError("kaboom")


class ConstTool(Tool):
    key = "_test_const"
    label = "const"
    category = "logic"
    inputs = []
    outputs = [Port("value", "v", "number")]
    allows_unconnected = True

    def execute(self, ctx):
        return Result(outputs={"value": float(ctx.param("v", 1))})


def run_graph(graph, **kw):
    compiled = compile_graph(validate_graph(graph))
    return engine.execute(
        compiled,
        flow_id=1,
        flow_version=1,
        trigger="test",
        grab=lambda sid: np.full((60, 80, 3), 200, np.uint8),
        asset_path=lambda a: None,
        **kw,
    )


class EngineTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register(BoomTool())
        register(ConstTool())

    @classmethod
    def tearDownClass(cls):
        unregister("_test_boom")
        unregister("_test_const")
        super().tearDownClass()

    def test_branch_gating_and_judge(self):
        g = {
            "nodes": [n("c", "_test_const", v=5), n("if", "if_number", operator="gt", threshold=3), n("ok", "judge", verdict="ok"), n("ng", "judge", verdict="ng")],
            "edges": [e("c", "if", "value", "value"), e("if", "ok", "true", "_flow"), e("if", "ng", "false", "_flow")],
        }
        r = run_graph(g)
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.nodes["ok"].status, "ok")
        self.assertEqual(r.nodes["ng"].status, "skipped")
        self.assertEqual(r.outputs["judge"], "OK")

        g["nodes"][0]["params"]["v"] = 1
        r = run_graph(g)
        self.assertEqual(r.status, "ng")
        self.assertEqual(r.nodes["ng"].status, "ng")

    def test_input_image_overrides_source(self):
        g = {"nodes": [n("src", "image_source", mode="auto"), n("g", "grayscale")], "edges": [e("src", "g")]}
        img = np.zeros((10, 20, 3), np.uint8)
        r = run_graph(g, input_image=img)
        self.assertEqual(r.nodes["src"].outputs["width"], 20)
        self.assertIn("input", r.nodes["src"].message)

    def test_source_required_when_no_input(self):
        g = {"nodes": [n("src", "image_source", mode="input")], "edges": []}
        r = run_graph(g)
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.nodes["src"].status, "error")

    def test_disabled_node_passes_through(self):
        g = {"nodes": [n("src", "image_source", source_id="1"), {"id": "b", "type": "blur", "enabled": False, "params": {}}, n("t", "threshold")], "edges": [e("src", "b"), e("b", "t")]}
        r = run_graph(g)
        self.assertEqual(r.nodes["b"].message, "disabled (pass-through)")
        self.assertEqual(r.nodes["t"].status, "ok")

    def test_exception_marks_failed_and_downstream_skipped(self):
        g = {"nodes": [n("src", "image_source", source_id="1"), n("x", "_test_boom"), n("t", "threshold")], "edges": [e("src", "x"), e("x", "t")]}
        r = run_graph(g)
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.nodes["x"].status, "error")
        self.assertIn("kaboom", r.nodes["x"].message)
        self.assertEqual(r.nodes["t"].status, "skipped")
        self.assertIn("kaboom", r.error)

    def test_continue_on_error(self):
        g = {"nodes": [n("src", "image_source", source_id="1"), {"id": "x", "type": "_test_boom", "continue_on_error": True, "params": {}}, n("j", "judge", verdict="ok")], "edges": [e("src", "x")]}
        r = run_graph(g)
        self.assertEqual(r.status, "ok")

    def test_images_cached_only_when_consumed_or_preview(self):
        g = {"nodes": [n("src", "image_source", source_id="1"), n("g", "grayscale"), n("t", "threshold")], "edges": [e("src", "g"), e("g", "t")]}
        r = run_graph(g)
        self.assertIsNotNone(r.nodes["g"].outputs["image"]["ref"])   # 被 t 用到
        self.assertIsNone(r.nodes["t"].outputs["image"]["ref"])      # 沒人用
        p = run_graph(g, preview=True)
        self.assertIsNotNone(p.nodes["t"].outputs["image"]["ref"])
        self.assertIsNotNone(store.get(p.nodes["t"].outputs["image"]["ref"]))
        self.assertEqual(p.nodes["t"].detail["_input_ref"], f"{p.id}:g:image")

    def test_formula_and_output(self):
        g = {
            "nodes": [n("a", "_test_const", v=3), n("b", "_test_const", v=4), n("f", "formula", expression="sqrt(a*a+b*b)"), n("o", "output", name="hyp")],
            "edges": [e("a", "f", "value", "a"), e("b", "f", "value", "b"), e("f", "o", "value", "value")],
        }
        r = run_graph(g)
        self.assertEqual(r.outputs["hyp"], 5.0)

    def test_overlays_port_feeds_draw_result(self):
        g = {
            "nodes": [n("src", "image_source", source_id="1"), n("c", "crop", roi={"shape": "rect", "x": 5, "y": 5, "w": 20, "h": 10}), n("d", "draw_result")],
            "edges": [e("src", "c"), e("src", "d", "image", "image"), e("c", "d", "_overlays", "overlays")],
        }
        r = run_graph(g, preview=True)
        self.assertEqual(r.nodes["d"].status, "ok")
        self.assertEqual(r.nodes["c"].overlays[0]["kind"], "rect")

    def test_formula_rejects_unsafe(self):
        g = {"nodes": [n("f", "formula", expression="__import__('os')")], "edges": []}
        r = run_graph(g)
        self.assertEqual(r.nodes["f"].status, "error")


class RunnerTests(TestCase):
    def setUp(self):
        # TestCase 回滾後 flow id 會重用；runner 的每流程狀態要跟著清。
        for fid in list(runner._runtimes):
            runner.forget(fid)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 320, "height": 240})
        self.graph = {
            "nodes": [n("src", "image_source", source_id=self.source.id), n("g", "grayscale"), n("t", "threshold", method="otsu"), n("c", "in_range", low=0, high=255), n("ok", "judge", verdict="ok"), n("ng", "judge", verdict="ng")],
            "edges": [e("src", "g"), e("g", "t"), e("t", "c", "threshold_used", "value"), e("c", "ok", "inside", "_flow"), e("c", "ng", "outside", "_flow")],
        }

    def make_flow(self, name="f"):
        return Flow.objects.create(name=name, graph=validate_graph(self.graph))

    def test_run_sync_and_stats(self):
        flow = self.make_flow()
        r = runner.run_sync(flow, trigger="api")
        self.assertEqual(r.status, "ok")
        stats = runner.runtime(flow.id).stats
        self.assertEqual(stats.runs, 1)
        self.assertEqual(stats.ok, 1)
        self.assertGreater(stats.to_dict()["avg_ms"], 0)

    def test_recompiles_on_version_change(self):
        flow = self.make_flow()
        runner.run_sync(flow)
        flow.graph = validate_graph({"nodes": [n("src", "image_source", source_id=self.source.id)], "edges": []})
        flow.version += 1
        flow.save()
        r = runner.run_sync(flow)
        self.assertEqual(list(r.nodes), ["src"])

    def test_disabled_flow_refused(self):
        flow = self.make_flow()
        flow.is_enabled = False
        flow.save()
        from apps.core.errors import Conflict

        with self.assertRaises(Conflict):
            runner.submit(flow)

    def test_parallel_flows_run_concurrently(self):
        flows = [self.make_flow(f"p{i}") for i in range(6)]
        futures = [runner.submit(f) for f in flows]
        results = [fu.result(timeout=20) for fu in futures]
        self.assertTrue(all(r.status == "ok" for r in results))

    def test_same_flow_serialised_and_queue_limit(self):
        flow = self.make_flow()
        gate = threading.Event()

        class SlowTool(Tool):
            key = "_test_slow"
            label = "slow"
            inputs = []
            outputs = [Port("value", "v", "number")]
            allows_unconnected = True

            def execute(self, ctx):
                gate.wait(5)
                return Result(outputs={"value": 1})

        register(SlowTool())
        try:
            flow.graph = validate_graph({"nodes": [n("s", "_test_slow")], "edges": []})
            flow.version += 1
            flow.save()
            with override_settings(VISION={**runner_settings(), "MAX_QUEUE_PER_FLOW": 2}):
                first = runner.submit(flow)
                time.sleep(0.05)
                runner.submit(flow)
                runner.submit(flow)
                with self.assertRaises(RateLimited):
                    runner.submit(flow)
                gate.set()
                first.result(timeout=5)
        finally:
            gate.set()
            time.sleep(0.2)
            unregister("_test_slow")

    def test_events_published(self):
        flow = self.make_flow()
        since = bus.seq
        runner.run_sync(flow)
        _, events = bus.wait(since, 0.1)
        types = [ev["type"] for ev in events]
        self.assertIn("run_finished", types)
        finished = next(ev for ev in events if ev["type"] == "run_finished")
        self.assertEqual(finished["run"]["status"], "ok")
        self.assertEqual(finished["flow_id"], flow.id)

    def test_continuous_mode(self):
        flow = self.make_flow()
        flow.continuous_interval_ms = 5
        flow.save()
        runner.start_continuous(flow)
        time.sleep(0.4)
        runner.stop_continuous(flow.id)
        self.assertFalse(runner.is_continuous(flow.id))
        self.assertGreater(runner.runtime(flow.id).stats.runs, 3)


def runner_settings():
    from django.conf import settings

    return dict(settings.VISION)
