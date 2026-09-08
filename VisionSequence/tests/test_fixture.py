"""位置修正：畫在畫布上的 ROI 跟著工件走，或把影像轉回教導時的姿態。

以前要在圖裡插一顆「ROI 跟隨」，每個要跟隨的區域各接一次；工件一多，圖就被接線淹沒。
現在每個畫得出 ROI 的工具都有一個隱含輸入埠 `_transform`：接上定位補正，這個節點畫的
區域就自己跟著走，工具本身完全不必知道有這回事。
"""

from __future__ import annotations

import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.vision import engine
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.tools import base, register_builtins
from apps.vision.tools.base import all_types, catalogue
from apps.vision.tools import roi as roi_mod
from apps.vision.tools.builtin.locate import inverse_matrix
from tests._helpers import run_tool

MOVE = {"dx": 12.0, "dy": -7.0, "dtheta": 0.0, "pivot": [80.0, 50.0]}
TURN = {"dx": 12.0, "dy": -7.0, "dtheta": 15.0, "pivot": [80.0, 50.0]}


class ApplyTransformTests(SimpleTestCase):
    """roi.apply_transform：定位結果 → 移動後的區域（純函式）。"""

    def test_a_plain_move_shifts_every_shape(self):
        rect = roi_mod.apply_transform({"shape": "rect", "x": 10, "y": 20, "w": 30, "h": 40}, MOVE)
        self.assertEqual((rect["x"], rect["y"], rect["w"]), (22.0, 13.0, 30))
        circle = roi_mod.apply_transform({"shape": "circle", "cx": 50, "cy": 50, "r": 8}, MOVE)
        self.assertEqual((circle["cx"], circle["cy"], circle["r"]), (62.0, 43.0, 8))

    def test_a_turn_uses_the_pivot_and_upgrades_a_plain_rectangle(self):
        # 中心在 (110, 50)，在 pivot (80, 50) 右邊 30 px；繞 pivot 順時針 15° 會往下走（畫面 y 向下），再平移
        turned = roi_mod.apply_transform({"shape": "rect", "x": 100, "y": 40, "w": 20, "h": 20}, TURN)
        self.assertEqual(turned["shape"], "rotated_rect")  # 矩形轉了就升格成旋轉矩形
        self.assertAlmostEqual(turned["angle"], 15.0)
        self.assertAlmostEqual(turned["cx"], 120.98, places=1)
        self.assertAlmostEqual(turned["cy"], 50.76, places=1)
        # 中心剛好在 pivot 上時只有平移
        on_pivot = roi_mod.apply_transform({"shape": "rect", "x": 70, "y": 40, "w": 20, "h": 20}, TURN)
        self.assertEqual((on_pivot["cx"], on_pivot["cy"]), (92.0, 43.0))

    def test_nothing_to_do_returns_the_region_untouched(self):
        region = {"shape": "rect", "x": 1, "y": 2, "w": 3, "h": 4}
        self.assertIs(roi_mod.apply_transform(region, None), region)
        self.assertIs(roi_mod.apply_transform(region, {"dx": 0, "dy": 0, "dtheta": 0}), region)
        self.assertIs(roi_mod.apply_transform(region, {"dx": "很多"}), region)


class ImplicitPortTests(SimpleTestCase):
    """每個畫得出 ROI 的工具都要有這個埠，而且只有那些工具有。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    def test_the_port_follows_the_roi_parameter(self):
        by_key = {t["key"]: t for t in catalogue()}
        for tool in all_types():
            has_roi = any(getattr(p, "kind", "") == "roi" for p in tool.params)
            ports = [p["key"] for p in by_key[tool.key]["inputs"]]
            self.assertEqual(base.TRANSFORM_IN in ports, has_roi, tool.key)
        self.assertIn(base.TRANSFORM_IN, [p["key"] for p in by_key["blob"]["inputs"]])
        self.assertNotIn(base.TRANSFORM_IN, [p["key"] for p in by_key["grayscale"]["inputs"]])

    def test_the_graph_accepts_an_edge_into_it(self):
        graph = validate_graph({
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"mode": "input"}},
                {"id": "loc", "type": "shape_align", "params": {}},
                {"id": "blob", "type": "blob", "params": {"roi": {"shape": "rect", "x": 0, "y": 0, "w": 10, "h": 10}}},
            ],
            "edges": [
                {"id": "e1", "source": "src", "source_handle": "image", "target": "blob", "target_handle": "image"},
                {"id": "e2", "source": "loc", "source_handle": "transform", "target": "blob", "target_handle": "_transform"},
            ],
        })
        self.assertEqual(len(graph["edges"]), 2)


class ContextRoiTests(SimpleTestCase):
    """ctx.roi()：位置修正就內建在這裡，所有工具一次到位。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    @staticmethod
    def _image() -> np.ndarray:
        img = np.zeros((120, 160), np.uint8)
        cv2.rectangle(img, (70, 40), (90, 60), 255, -1)
        return img

    def test_a_measurement_follows_the_part(self):
        """亮塊在 (70,40)-(90,60)；ROI 畫在原位，工件移動 (12,-7) 之後量測要跟著移。"""
        img = np.zeros((120, 160), np.uint8)
        cv2.rectangle(img, (82, 33), (102, 53), 255, -1)  # 已經移動過的工件
        roi = {"shape": "rect", "x": 70, "y": 40, "w": 20, "h": 20}
        still = run_tool("intensity", img, {"roi": roi})
        moved = run_tool("intensity", img, {"roi": roi}, inputs={base.TRANSFORM_IN: MOVE})
        self.assertLess(still.outputs["mean"], 200)      # ROI 沒跟上，只蓋到一角
        self.assertEqual(moved.outputs["mean"], 255.0)   # 跟上了，整塊都是亮的

    def test_a_missing_transform_leaves_the_region_where_it_was_drawn(self):
        roi = {"shape": "rect", "x": 70, "y": 40, "w": 20, "h": 20}
        result = run_tool("intensity", self._image(), {"roi": roi}, inputs={base.TRANSFORM_IN: None})
        self.assertEqual(result.outputs["mean"], 255.0)  # 原位就是亮塊，代表沒有被移動

    def test_the_moved_region_is_only_worked_out_once(self):
        """多數工具一次 run 會問兩三次 ROI（畫 overlay、裁切、算遮罩）。"""
        ctx = _context({"roi": {"shape": "rect", "x": 10, "y": 10, "w": 4, "h": 4}}, {base.TRANSFORM_IN: MOVE})
        first = ctx.roi()
        self.assertIs(ctx.roi(), first)
        self.assertEqual(first["x"], 22.0)
        self.assertIsNone(_context({}, {}).roi())

    def test_the_input_port_still_wins_over_the_drawn_shape(self):
        ctx = _context({"roi": {"shape": "rect", "x": 10, "y": 10, "w": 4, "h": 4}},
                       {"roi": {"shape": "circle", "cx": 50, "cy": 50, "r": 5}, base.TRANSFORM_IN: MOVE})
        region = ctx.roi()
        self.assertEqual(region["shape"], "circle")
        self.assertEqual((region["cx"], region["cy"]), (62.0, 43.0))  # 動態區域也跟著走


class EngineFixtureTests(SimpleTestCase):
    """整條流程跑一次：定位找不到時要留下警告，不能靜默量到空氣。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    @staticmethod
    def _graph() -> dict:
        return {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"mode": "input"}},
                {"id": "loc", "type": "shape_align", "params": {"ref_x": 80, "ref_y": 50}},
                {"id": "val", "type": "intensity", "params": {"roi": {"shape": "rect", "x": 70, "y": 40, "w": 20, "h": 20}}},
            ],
            "edges": [
                {"id": "e2", "source": "src", "source_handle": "image", "target": "val", "target_handle": "image"},
                {"id": "e3", "source": "loc", "source_handle": "transform", "target": "val", "target_handle": base.TRANSFORM_IN},
            ],
        }

    def test_a_locate_step_that_finds_nothing_warns_instead_of_measuring_thin_air(self):
        img = np.zeros((120, 160), np.uint8)
        cv2.rectangle(img, (70, 40), (90, 60), 255, -1)
        report = engine.execute(compile_graph(validate_graph(self._graph())), flow_id=0, flow_version=1, trigger="test",
                                grab=lambda s: None, asset_path=lambda a: None, input_image=img)
        self.assertEqual(report.nodes["val"].status, "ok")          # 量測照跑
        self.assertEqual(report.nodes["val"].detail.get("fixture"), "missing")
        self.assertTrue(any("position correction" in w for w in report.warnings), report.warnings)


class ImageFixtureToolTests(SimpleTestCase):
    """把影像轉回教導時的姿態：整條流程都不必跟隨，教導的範本也還比得到。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    def test_the_inverse_matrix_undoes_the_move_exactly(self):
        point = {"shape": "point", "x": 100.0, "y": 60.0}
        moved = roi_mod.apply_transform(point, TURN)
        matrix = inverse_matrix(TURN["dx"], TURN["dy"], TURN["dtheta"], tuple(TURN["pivot"]))
        back = matrix @ np.array([moved["x"], moved["y"], 1.0])
        self.assertAlmostEqual(float(back[0]), 100.0, places=3)
        self.assertAlmostEqual(float(back[1]), 60.0, places=3)

    def test_a_moved_part_comes_back_to_where_it_was_taught(self):
        taught = np.zeros((120, 160), np.uint8)
        cv2.rectangle(taught, (70, 40), (90, 60), 255, -1)
        moved = np.zeros((120, 160), np.uint8)
        cv2.rectangle(moved, (82, 33), (102, 53), 255, -1)
        result = run_tool("image_fixture", moved, {}, inputs={"transform": MOVE})
        self.assertEqual(result.status, "ok")
        out = result.outputs["image"]
        self.assertEqual(out.shape, taught.shape)
        self.assertLess(float(np.abs(out.astype(np.int16) - taught.astype(np.int16)).mean()), 3.0)
        self.assertEqual((result.outputs["dx"], result.outputs["dy"]), (12.0, -7.0))

    def test_the_edges_are_filled_the_way_you_asked(self):
        img = np.full((60, 80), 128, np.uint8)
        black = run_tool("image_fixture", img, {"border": "black"}, inputs={"transform": MOVE}).outputs["image"]
        white = run_tool("image_fixture", img, {"border": "white"}, inputs={"transform": MOVE}).outputs["image"]
        near = run_tool("image_fixture", img, {"border": "replicate"}, inputs={"transform": MOVE}).outputs["image"]
        self.assertEqual(int(black[0, 0]), 0)
        self.assertEqual(int(white[0, 0]), 255)
        self.assertEqual(int(near[0, 0]), 128)

    def test_nothing_found_passes_the_picture_through_and_says_so(self):
        img = np.full((40, 40), 90, np.uint8)
        result = run_tool("image_fixture", img, {}, inputs={"transform": None})
        self.assertEqual(result.status, "ng")
        self.assertIs(result.outputs["image"], img)
        with self.assertRaises(base.ToolError):
            run_tool("image_fixture", img, {}, inputs={"transform": "不是 transform"})


def _context(params: dict, inputs: dict) -> base.ToolContext:
    return base.ToolContext(
        run_id="r", flow_id=0, node={"params": params}, inputs=inputs, context={},
        moment=0.0, log=lambda *a, **k: None, asset_path=lambda _a: None, grab=lambda _s: None,
    )
