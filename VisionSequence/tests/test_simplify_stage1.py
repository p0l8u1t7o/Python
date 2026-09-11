from __future__ import annotations

import copy
import json
import os
from types import SimpleNamespace

import cv2
import numpy as np
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import AuthToken, UserPref
from apps.vision import engine
from apps.vision.graph import GraphError, compile_graph, validate_graph
from apps.vision.models import Flow
from apps.vision.runner import apply_recipe
from apps.vision.tools import register_builtins
from apps.vision.tools.base import Port, Result, Tool, register, unregister
from tests._helpers import circle_image, run_tool, temp_dir


def n(nid: str, ntype: str, **params):
    node = {"id": nid, "type": ntype, "params": params}
    publish = params.pop("_publish", None)
    if publish is not None:
        # 具名輸出名稱現在在 node.interface.outputs[].alias（PRODUCT-DIRECTION v2 P0）
        node["interface"] = {"outputs": publish if isinstance(publish, list) else [{"key": k, "alias": v} for k, v in publish.items()]}
    return node


def e(s: str, t: str, sh: str = "", th: str = ""):
    return {"source": s, "target": t, "source_handle": sh, "target_handle": th}


def run_graph(graph: dict, **kw) -> engine.RunReport:
    compiled = compile_graph(validate_graph(graph))
    return engine.execute(
        compiled,
        flow_id=1,
        flow_version=1,
        trigger="test",
        grab=lambda _sid: np.full((60, 80, 3), 200, np.uint8),
        asset_path=lambda aid: (kw.pop("assets", {}) or {}).get(str(aid)),
        **kw,
    )


class StageConstTool(Tool):
    key = "_stage1_const"
    label = "stage const"
    category = "logic"
    inputs = []
    outputs = [Port("value", "Value", "any")]
    allows_unconnected = True

    def execute(self, ctx):
        return Result(outputs={"value": ctx.param("value", 0)})


class StageNumpyConstTool(Tool):
    key = "_stage1_numpy_const"
    label = "stage numpy const"
    category = "logic"
    inputs = []
    outputs = [Port("value", "Value", "number")]
    allows_unconnected = True

    def execute(self, ctx):
        return Result(outputs={"value": np.float32(ctx.number("value", 1.23456))})


class StageGrayProbeTool(Tool):
    key = "_stage1_gray_probe"
    label = "stage gray probe"
    category = "preprocess"
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("shape", "Shape", "list"), Port("pixels", "Pixels", "list")]
    wants_gray = True

    def execute(self, ctx):
        image = ctx.require_image()
        return Result(outputs={"shape": list(image.shape), "pixels": image.tolist()})


class StageFailTool(Tool):
    key = "_stage1_fail"
    label = "stage fail"
    category = "logic"
    inputs = []
    outputs = [Port("value", "Value", "number")]
    allows_unconnected = True

    def execute(self, ctx):
        raise RuntimeError("boom")


class SimplifyStage1EngineTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()
        register(StageConstTool())
        register(StageNumpyConstTool())
        register(StageGrayProbeTool())
        register(StageFailTool())

    @classmethod
    def tearDownClass(cls):
        unregister("_stage1_const")
        unregister("_stage1_numpy_const")
        unregister("_stage1_gray_probe")
        unregister("_stage1_fail")
        super().tearDownClass()

    def _logic_graph(self, tool_type: str, params: dict, value, input_port: str = "value") -> dict:
        return {
            "nodes": [n("c", "_stage1_const", value=value), n("judge", tool_type, **params)],
            "edges": [e("c", "judge", "value", input_port)],
        }

    def test_if_number_in_range_string_match_reject_by_default(self):
        cases = [
            ("if_number", {"operator": "gt", "threshold": 3, "ng_label": "too-low"}, 2, "value", "false", "result", False),
            ("in_range", {"low": 10, "high": 20, "ng_label": "out"}, 5, "value", "outside", "result", False),
            ("string_match", {"list": "OK", "match": "contains", "ng_label": "missing"}, "BAD", "text", "not_found", "found", False),
        ]
        for tool_type, params, value, port, branch, output_key, result in cases:
            with self.subTest(tool=tool_type):
                report = run_graph(self._logic_graph(tool_type, params, value, port))
                self.assertEqual(report.status, "ng", report.to_dict())
                self.assertEqual(report.nodes["judge"].status, "ng")
                self.assertEqual(report.nodes["judge"].branch, branch)
                self.assertEqual(report.nodes["judge"].outputs[output_key], result)
                self.assertEqual(report.outputs["judge"], "NG")
                self.assertEqual(report.outputs["judge_label"], params["ng_label"])
                self.assertIn(params["ng_label"], report.nodes["judge"].message)

    def test_logic_route_keeps_branch_only_behavior(self):
        cases = [
            ("if_number", {"operator": "gt", "threshold": 3, "on_false": "route"}, 2, "value", "false"),
            ("in_range", {"low": 10, "high": 20, "on_false": "route"}, 5, "value", "outside"),
            ("string_match", {"list": "OK", "match": "contains", "on_false": "route"}, "BAD", "text", "not_found"),
        ]
        for tool_type, params, value, port, branch in cases:
            with self.subTest(tool=tool_type):
                report = run_graph(self._logic_graph(tool_type, params, value, port))
                self.assertEqual(report.status, "ok", report.to_dict())
                self.assertEqual(report.nodes["judge"].status, "ok")
                self.assertEqual(report.nodes["judge"].branch, branch)
                self.assertEqual(report.outputs["judge"], "OK")
                self.assertNotIn("judge_label", report.outputs)

    def test_synthetic_blob_without_judge_gets_default_ng_judge(self):
        image = np.full((200, 300, 3), 20, np.uint8)
        for x in (70, 160):
            cv2.circle(image, (x, 100), 15, (230, 230, 230), -1)
        graph = {
            "nodes": [
                n("src", "image_source", mode="input"),
                n("blob", "blob", threshold_method="fixed", threshold=128, min_area=50),
                n("cmp", "if_number", operator="ge", threshold=3),
            ],
            "edges": [
                e("src", "blob", "image", "image"),
                e("blob", "cmp", "count", "value"),
            ],
        }
        report = run_graph(graph, input_image=image, preview=True)
        self.assertEqual(report.status, "ng", report.to_dict())
        self.assertEqual(report.nodes["blob"].outputs["count"], 2)
        self.assertEqual(report.nodes["cmp"].branch, "false")
        self.assertEqual(report.outputs["judge"], "NG")

    def test_publish_writes_named_outputs_from_ok_and_ng_nodes(self):
        graph = {
            "nodes": [
                n("np", "_stage1_numpy_const", value=1.23456, _publish={"value": "via_publish"}),
                n("out", "output", name="via_output", decimals=3),
                n("cmp", "if_number", operator="gt", threshold=3, ng_label="reject", _publish={"result": "cmp_result"}),
            ],
            "edges": [
                e("np", "out", "value", "value"),
                e("np", "cmp", "value", "value"),
            ],
        }
        report = run_graph(graph)
        self.assertEqual(report.status, "ng", report.to_dict())
        self.assertEqual(report.outputs["via_publish"], 1.235)
        self.assertEqual(report.outputs["via_output"], 1.235)
        self.assertIs(report.outputs["cmp_result"], False)
        self.assertEqual(report.outputs["judge"], "NG")
        self.assertEqual(report.outputs["judge_label"], "reject")

    def test_publish_validation_rejects_bad_specs(self):
        bad_specs = [
            ({"result": 123}, "invalid output name"),
            ({"false": "branch_name"}, "branch output port"),
            ({"missing": "name"}, "unknown output port"),
            ({"_image": "image_name"}, "implicit output port"),
        ]
        for spec, text in bad_specs:
            with self.subTest(spec=spec):
                graph = {"nodes": [n("cmp", "if_number", operator="gt", threshold=3, _publish=spec)], "edges": []}
                with self.assertRaises(GraphError) as caught:
                    validate_graph(graph)
                self.assertIn(text, str(caught.exception))
        # 同一個節點兩個埠不能發布成同一個名稱
        graph = {"nodes": [{"id": "c", "type": "find_circle", "params": {}, "interface": {"outputs": [{"key": "cx", "alias": "a"}, {"key": "cy", "alias": "a"}]}}], "edges": []}
        with self.assertRaisesRegex(GraphError, "same output name"):
            validate_graph(graph)

    def test_recipe_overrides_cannot_write_platform_params(self):
        graph = {"nodes": [n("cmp", "if_number", threshold=1, _publish={"result": "old"})], "edges": []}
        recipe = SimpleNamespace(param_overrides={"cmp": {"threshold": 2, "_publish": {"result": "new"}}})
        with self.assertLogs("apps.vision.runner", level="INFO") as logs:
            out = apply_recipe(graph, recipe)
        params = out["nodes"][0]["params"]
        self.assertEqual(params["threshold"], 2)
        self.assertNotIn("_publish", params)
        self.assertEqual(out["nodes"][0]["interface"], {"outputs": [{"key": "result", "alias": "old"}]})
        self.assertIn("_publish", "\n".join(logs.output))

    def test_legacy_publish_and_exposed_params_are_rejected(self):
        # 沒有相容層：舊欄位直接拒絕，錯誤訊息指出新欄位
        graph = {"nodes": [{"id": "cmp", "type": "if_number", "params": {"threshold": 1, "_publish": {"result": "x"}}}], "edges": []}
        with self.assertRaisesRegex(GraphError, "interface.outputs"):
            validate_graph(graph)
        graph = {"nodes": [{"id": "cmp", "type": "if_number", "params": {"threshold": 1}, "exposed_params": ["threshold"]}], "edges": []}
        with self.assertRaisesRegex(GraphError, "interface.inputs"):
            validate_graph(graph)
        # interface.inputs 的 param:<key> 要是可綁定的參數
        graph = {"nodes": [{"id": "cmp", "type": "if_number", "params": {"threshold": 1}, "interface": {"inputs": [{"key": "param:threshold", "exposed": True}, {"key": "value", "exposed": False}]}}], "edges": []}
        validate_graph(graph)
        graph["nodes"][0]["interface"]["inputs"].append({"key": "param:nope"})
        with self.assertRaisesRegex(GraphError, "unknown input port"):
            validate_graph(graph)

    def test_wants_gray_converts_three_channel_input(self):
        image = np.zeros((2, 3, 3), np.uint8)
        image[:, :, 0] = [[10, 20, 30], [40, 50, 60]]
        image[:, :, 1] = [[60, 50, 40], [30, 20, 10]]
        image[:, :, 2] = [[1, 2, 3], [4, 5, 6]]
        graph = {
            "nodes": [n("src", "image_source", mode="input"), n("probe", "_stage1_gray_probe")],
            "edges": [e("src", "probe", "image", "image")],
        }
        report = run_graph(graph, input_image=image)
        expected = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        self.assertEqual(report.nodes["probe"].outputs["shape"], [2, 3])
        self.assertEqual(report.nodes["probe"].outputs["pixels"], expected.tolist())

    def test_find_circle_diameter_outputs_and_world_projection(self):
        image = cv2.GaussianBlur(circle_image(160, 120, 50), (3, 3), 0)
        params = {
            "roi": {"shape": "circle", "cx": 158, "cy": 122, "r": 80},
            "polarity": "light_to_dark",
            "edge_threshold": 15,
            "ransac": False,
        }
        result = run_tool("find_circle", image, params)
        self.assertEqual(result.branch, "found", result.message)
        self.assertAlmostEqual(result.outputs["diameter"], result.outputs["r"] * 2, places=6)

        folder = temp_dir()
        calib_path = os.path.join(folder, "calib.json")
        with open(calib_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "image_size": [320, 240],
                    "unit": "mm",
                    "world": {"kind": "affine", "matrix": [[0.5, 0, 0], [0, 0.5, 0], [0, 0, 1]]},
                },
                fh,
            )
        world = run_tool("find_circle", image, {**params, "calibration": "cal"}, assets={"cal": calib_path})
        self.assertEqual(world.branch, "found", world.message)
        self.assertAlmostEqual(world.outputs["diameter_world"], world.outputs["r_world"] * 2, places=6)
        self.assertAlmostEqual(world.outputs["diameter_world"], world.outputs["diameter"] * 0.5, delta=0.05)

    def test_default_judge_output_for_ok_ng_and_failed_reports(self):
        ok = run_graph({"nodes": [n("c", "_stage1_const", value=1)], "edges": []})
        self.assertEqual((ok.status, ok.outputs["judge"]), ("ok", "OK"))

        ng_graph = {
            "nodes": [n("c", "_stage1_const", value=1), n("cmp", "if_number", operator="gt", threshold=3)],
            "edges": [e("c", "cmp", "value", "value")],
        }
        ng = run_graph(ng_graph)
        self.assertEqual((ng.status, ng.outputs["judge"]), ("ng", "NG"))

        failed = run_graph({"nodes": [n("f", "_stage1_fail")], "edges": []})
        self.assertEqual((failed.status, failed.outputs["judge"]), ("failed", "FAILED"))
        self.assertIn("boom", failed.error)


class SimplifyStage1ApiTests(TestCase):
    def setUp(self):
        register_builtins()
        admin = User.objects.create_user("admin", password="secret1", is_staff=True)
        op = User.objects.create_user("op", password="pass123")
        UserPref.objects.create(user=op, role="operator")
        self.admin = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(admin)}"}
        self.operator = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(op)}"}
        self.graph = validate_graph(
            {
                "nodes": [{"id": "cmp", "type": "if_number", "params": {"operator": "gt", "threshold": 1}}],
                "edges": [],
            }
        )
        self.flow = Flow.objects.create(name="stage1", graph=self.graph, owner=admin)

    def test_operator_cannot_patch_publish(self):
        graph = copy.deepcopy(self.graph)
        graph["nodes"][0]["interface"] = {"outputs": [{"key": "result", "alias": "cmp_result"}]}
        response = self.client.patch(
            f"/api/vision/flows/{self.flow.id}",
            data=json.dumps({"graph": graph}),
            content_type="application/json",
            **self.operator,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "teach_only")
