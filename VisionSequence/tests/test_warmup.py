from __future__ import annotations

import io
import shutil
import tempfile
from unittest.mock import patch

import numpy as np
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.vision import fixed_images, variables, warmup
from apps.vision.graph import validate_graph
from apps.vision.images import store as image_store
from apps.vision.models import Flow, FlowRun, FlowRunHourly, FlowVariable, ImageSource, MeasurementLog
from apps.vision.runner import runner
from apps.vision.tools.base import Port, Tool, unregister
from apps.vision.tools.base import register as register_tool


def _node(node_id: str, node_type: str, **params):
    return {"id": node_id, "type": node_type, "params": params}


def _edge(source: str, target: str, source_handle: str = "", target_handle: str = ""):
    return {"source": source, "target": target, "source_handle": source_handle, "target_handle": target_handle}


class WarmupBoomTool(Tool):
    key = "_warmup_boom"
    label = "warmup boom"
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("image", "Image", "image")]

    def execute(self, ctx):
        raise RuntimeError("warmup exploded")


class WarmupTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_tool(WarmupBoomTool())

    @classmethod
    def tearDownClass(cls):
        unregister("_warmup_boom")
        super().tearDownClass()

    def setUp(self):
        for flow_id in list(runner._runtimes):
            runner.forget(flow_id)
        variables.store.clear()
        self.tmp = tempfile.mkdtemp(prefix="vs-warmup-assets-")
        self.override = override_settings(VISION={**settings.VISION, "ASSET_DIR": self.tmp, "WARMUP": "off"})
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(variables.store.clear)
        self.addCleanup(self._clear_runner)

    def _clear_runner(self):
        for flow_id in list(runner._runtimes):
            runner.forget(flow_id)

    def _fixed_desc(self):
        image = np.full((24, 32, 3), 80, np.uint8)
        image[4:10, 4:10] = 220
        return fixed_images.store(image, "warmup.png")

    def _fixed_flow(self, *, name: str = "fixed warm", boom: bool = False) -> Flow:
        desc = self._fixed_desc()
        nodes = [
            _node("src", "fixed_image", images=[desc], mode="fixed", index=1),
            _node("count", "variable_set", name="parts", mode="add"),
            _node("read", "variable_get", name="parts", default="0"),
            _node("out", "output", name="parts"),
        ]
        edges = [
            _edge("src", "count", "image", "_image"),
            _edge("count", "read", "_image", "_image"),
            _edge("read", "out", "value", "value"),
        ]
        if boom:
            nodes.insert(1, _node("boom", "_warmup_boom"))
            edges = [_edge("src", "boom"), _edge("boom", "count")]
        graph = validate_graph({"nodes": nodes, "edges": edges})
        return Flow.objects.create(name=name, graph=graph, commissioned=True, is_enabled=True)

    def test_fixed_image_flow_warms_without_run_history_stats_or_cached_images(self):
        flow = self._fixed_flow()
        stats_before = image_store.stats()
        before = {
            "runs": FlowRun.objects.count(),
            "hourly": FlowRunHourly.objects.count(),
            "measurements": MeasurementLog.objects.count(),
        }

        result = warmup.warm_flows([flow.id], timeout_s=5)

        self.assertEqual(result["items"][0]["status"], "warmed", result)
        self.assertEqual(result["summary"], {"warmed": 1, "skipped": 0, "failed": 0})
        self.assertEqual(FlowRun.objects.count(), before["runs"])
        self.assertEqual(FlowRunHourly.objects.count(), before["hourly"])
        self.assertEqual(MeasurementLog.objects.count(), before["measurements"])
        self.assertEqual(runner.runtime(flow.id).stats.runs, 0)
        self.assertEqual(image_store.stats(), stats_before)
        self.assertEqual(variables.store.snapshot(flow.id), {})
        variables.store.flush()
        self.assertFalse(FlowVariable.objects.filter(flow=flow).exists())

    def test_image_source_without_recent_image_is_skipped(self):
        source = ImageSource.objects.create(name="live", kind="synthetic", config={"width": 32, "height": 24})
        flow = Flow.objects.create(
            name="live source",
            commissioned=True,
            is_enabled=True,
            graph=validate_graph({"nodes": [_node("src", "image_source", source_id=source.id), _node("g", "grayscale")], "edges": [_edge("src", "g")]}),
        )

        result = warmup.warm_flows([flow.id], timeout_s=5)

        row = result["items"][0]
        self.assertEqual(row["status"], "skipped", result)
        self.assertIn("No recent source image", row["reason"])
        self.assertEqual(FlowRun.objects.count(), 0)
        self.assertEqual(runner.runtime(flow.id).stats.runs, 0)

    def test_tool_exception_returns_failed(self):
        flow = self._fixed_flow(name="boom warm", boom=True)

        result = warmup.warm_flows([flow.id], timeout_s=5)

        row = result["items"][0]
        self.assertEqual(row["status"], "failed", result)
        self.assertIn("warmup exploded", row["reason"])
        self.assertEqual(FlowRun.objects.count(), 0)
        self.assertEqual(runner.runtime(flow.id).stats.runs, 0)

    def test_serve_warmup_off_does_not_start_background(self):
        from apps.vision.management.commands import serve

        with override_settings(VISION={**settings.VISION, "WARMUP": "off"}):
            with patch("apps.vision.warmup.start_background") as start_background:
                serve._start_warmup_if_enabled(8765)
        start_background.assert_not_called()

    def test_management_command_runs(self):
        flow = self._fixed_flow()
        out = io.StringIO()

        call_command("warmup", "--flows", str(flow.id), stdout=out)

        text = out.getvalue()
        self.assertIn("Warmup complete", text)
        self.assertIn("warmed", text)
