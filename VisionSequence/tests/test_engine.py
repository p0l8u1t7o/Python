"""引擎端到端：image_source（API 送圖）→ grayscale → threshold → blob → if_number → judge。"""

from __future__ import annotations

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision import engine
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.tools import register_builtins


def _graph(threshold_count: int) -> dict:
    nodes = [
        {"id": "src", "type": "image_source", "params": {"mode": "input"}},
        {"id": "gray", "type": "grayscale", "params": {}},
        {"id": "thr", "type": "threshold", "params": {"method": "fixed", "threshold": 128}},
        {"id": "blob", "type": "blob", "params": {"threshold_method": "none", "min_area": 50}},
        {"id": "cmp", "type": "if_number", "params": {"operator": "ge", "threshold": threshold_count}},
        {"id": "judge_ok", "type": "judge", "params": {"verdict": "ok", "label": "count-ok"}},
        {"id": "judge_ng", "type": "judge", "params": {"verdict": "ng", "label": "count-ng"}},
        {"id": "out", "type": "output", "params": {"name": "count"}},
    ]
    edges = [
        {"id": "e1", "source": "src", "source_handle": "image", "target": "gray", "target_handle": "image"},
        {"id": "e2", "source": "gray", "source_handle": "image", "target": "thr", "target_handle": "image"},
        {"id": "e3", "source": "thr", "source_handle": "image", "target": "blob", "target_handle": "image"},
        {"id": "e4", "source": "blob", "source_handle": "count", "target": "cmp", "target_handle": "value"},
        {"id": "e5", "source": "cmp", "source_handle": "true", "target": "judge_ok", "target_handle": "_flow"},
        {"id": "e6", "source": "cmp", "source_handle": "false", "target": "judge_ng", "target_handle": "_flow"},
        {"id": "e7", "source": "blob", "source_handle": "count", "target": "out", "target_handle": "value"},
    ]
    return {"nodes": nodes, "edges": edges}


def _image(n_blobs: int) -> np.ndarray:
    img = np.full((200, 300, 3), 20, np.uint8)
    for i in range(n_blobs):
        cv2.circle(img, (40 + i * 60, 100), 15, (230, 230, 230), -1)
    return img


class EngineEndToEndTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    def _run(self, graph: dict, image: np.ndarray) -> engine.RunReport:
        compiled = compile_graph(validate_graph(graph))
        return engine.execute(compiled, flow_id=1, flow_version=1, trigger="test", grab=lambda s: None, asset_path=lambda a: None, preview=True, input_image=image)

    def test_ok_path(self):
        report = self._run(_graph(3), _image(3))
        self.assertEqual(report.status, "ok", report.to_dict())
        nodes = report.nodes
        self.assertEqual(nodes["blob"].status, "ok")
        self.assertEqual(nodes["blob"].outputs["count"], 3)
        self.assertEqual(nodes["cmp"].branch, "true")
        self.assertEqual(nodes["judge_ok"].status, "ok")
        self.assertEqual(nodes["judge_ng"].status, "skipped")
        self.assertEqual(report.outputs["judge"], "OK")
        self.assertEqual(report.outputs["judge_label"], "count-ok")
        self.assertEqual(report.outputs["count"], 3)
        self.assertTrue(nodes["blob"].overlays)
        self.assertEqual(nodes["blob"].overlay_on, "image")
        self.assertIn("_input_ref", nodes["blob"].detail)

    def test_ng_path(self):
        report = self._run(_graph(3), _image(2))
        self.assertEqual(report.status, "ng")
        self.assertEqual(report.nodes["cmp"].branch, "false")
        self.assertEqual(report.nodes["judge_ok"].status, "skipped")
        self.assertEqual(report.nodes["judge_ng"].status, "ng")
        self.assertEqual(report.outputs["judge"], "NG")
        self.assertEqual(report.outputs["count"], 2)

    def test_tool_error_marks_run_failed(self):
        graph = _graph(1)
        graph["nodes"][3]["params"] = {"threshold_method": "none", "roi": {"shape": "rect", "x": 1000, "y": 1000, "w": 10, "h": 10}}
        report = self._run(graph, _image(1))
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.nodes["blob"].status, "error")
        self.assertEqual(report.nodes["cmp"].status, "skipped")
