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


class ImageThruTests(SimpleTestCase):
    """隱含影像直通埠（_image）：每個工具預設可把影像傳進（無 image 輸入者）、傳出（原樣）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    def _run(self, graph: dict, image: np.ndarray) -> engine.RunReport:
        compiled = compile_graph(validate_graph(graph))
        return engine.execute(compiled, flow_id=1, flow_version=1, trigger="test", grab=lambda s: None, asset_path=lambda a: None, preview=True, input_image=image)

    def test_image_flows_through_logic_and_detect_tools(self):
        image = np.zeros((40, 60, 3), np.uint8)
        image[10:30, 20:40] = 255
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"mode": "input"}},
                # blob 有 image 輸入、輸出是 mask/count——直通輸出應是「原影像」不是 mask
                {"id": "blob", "type": "blob", "params": {"threshold_method": "fixed", "threshold": 100, "min_area": 10}},
                # formula 是純邏輯工具：影像經 _image 直通進出
                {"id": "f", "type": "formula", "params": {"expression": "a*1"}},
                {"id": "th", "type": "threshold", "params": {"method": "fixed", "threshold": 100}},
            ],
            "edges": [
                {"id": "e1", "source": "src", "source_handle": "image", "target": "blob", "target_handle": "image"},
                {"id": "e2", "source": "blob", "source_handle": "count", "target": "f", "target_handle": "a"},
                {"id": "e3", "source": "blob", "source_handle": "_image", "target": "f", "target_handle": "_image"},
                {"id": "e4", "source": "f", "source_handle": "_image", "target": "th", "target_handle": "image"},
            ],
        }
        report = self._run(graph, image)
        self.assertEqual(report.nodes["th"].status, "ok", report.nodes["th"].message)
        # threshold 收到的是原影像（彩色 40×60），且 blob 的標記沒畫進去
        out = report.nodes["th"].outputs.get("image")
        self.assertIsInstance(out, dict)
        self.assertEqual((out["width"], out["height"]), (60, 40))
        self.assertEqual(report.nodes["f"].outputs.get("value"), 1.0)

    def test_catalogue_declares_thru_ports(self):
        from apps.vision.tools import base as tools_base

        items = {t["key"]: t for t in tools_base.catalogue()}
        # 每個工具都有 _image 直通輸出
        for key in ("blob", "formula", "judge", "threshold"):
            self.assertIn("_image", [p["key"] for p in items[key]["outputs"]], key)
        # 沒有 image 輸入的邏輯工具才補直通輸入；有的（threshold）不重複加
        self.assertIn("_image", [p["key"] for p in items["formula"]["inputs"]])
        self.assertNotIn("_image", [p["key"] for p in items["threshold"]["inputs"]])

    def test_disabled_node_passes_thru(self):
        image = np.full((30, 30, 3), 200, np.uint8)
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"mode": "input"}},
                {"id": "f", "type": "formula", "params": {"expression": "1"}, "enabled": False},
                {"id": "th", "type": "threshold", "params": {"method": "fixed", "threshold": 100}},
            ],
            "edges": [
                {"id": "e1", "source": "src", "source_handle": "image", "target": "f", "target_handle": "_image"},
                {"id": "e2", "source": "f", "source_handle": "_image", "target": "th", "target_handle": "image"},
            ],
        }
        report = self._run(graph, image)
        self.assertEqual(report.nodes["th"].status, "ok", report.nodes["th"].message)
