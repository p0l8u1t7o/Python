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
from apps.vision.graph import GraphError, compile_graph, validate_graph
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

    def test_the_moved_region_is_drawn_dashed_only_when_a_correction_was_applied(self):
        """結果畫面要同時看得到「畫的位置」（實線）與「實際量的位置」（虛線）；沒接或沒找到就不多畫。"""
        roi = {"shape": "rect", "x": 10, "y": 10, "w": 4, "h": 4}
        moved = _context({"roi": roi}, {base.TRANSFORM_IN: MOVE})
        moved.roi()
        marks = base.moved_regions(moved)
        self.assertEqual(len(marks), 1)
        self.assertTrue(marks[0]["dash"])
        self.assertEqual(marks[0]["label"], "fixture")
        plain = _context({"roi": roi}, {})
        plain.roi()
        self.assertEqual(base.moved_regions(plain), [])
        missing = _context({"roi": roi}, {base.TRANSFORM_IN: None})
        missing.roi()
        self.assertEqual(base.moved_regions(missing), [])

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


class ParamBindingTests(SimpleTestCase):
    """參數訂閱：`param:<key>` 讓一個參數改吃上游送來的值（門檻跟著亮度走就是這樣做的）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    @staticmethod
    def _graph(handle: str = "param:threshold") -> dict:
        return {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"mode": "input"}},
                {"id": "i", "type": "intensity", "params": {}},
                {"id": "thr", "type": "threshold", "params": {"method": "fixed", "threshold": 10}},
            ],
            "edges": [
                {"id": "e1", "source": "src", "source_handle": "image", "target": "i", "target_handle": "image"},
                {"id": "e2", "source": "src", "source_handle": "image", "target": "thr", "target_handle": "image"},
                {"id": "e3", "source": "i", "source_handle": "mean", "target": "thr", "target_handle": handle},
            ],
        }

    @staticmethod
    def _run(graph: dict, image):
        return engine.execute(compile_graph(validate_graph(graph)), flow_id=0, flow_version=1, trigger="test",
                              grab=lambda s: None, asset_path=lambda a: None, input_image=image, preview=True)

    def test_the_upstream_value_wins_over_the_one_on_the_step(self):
        img = np.zeros((100, 120), np.uint8)
        cv2.rectangle(img, (20, 20), (60, 60), 200, -1)
        report = self._run(self._graph(), img)
        mean = report.nodes["i"].outputs["mean"]
        self.assertGreater(mean, 20)
        self.assertIn(f"{mean:.4g}"[:4], report.nodes["thr"].message)  # 用了平均值，不是畫布上填的 10
        self.assertEqual(report.nodes["thr"].status, "ok")

    def test_a_parameter_that_cannot_be_driven_is_refused(self):
        # code 綁上去會繞過腳本核准（apps/vision/scripts.py），這是資安項
        with self.assertRaisesMessage(GraphError, "has no parameter 'code'"):
            validate_graph({
                "nodes": [{"id": "i", "type": "intensity", "params": {}}, {"id": "s", "type": "python_script", "params": {}}],
                "edges": [{"id": "e", "source": "i", "source_handle": "mean", "target": "s", "target_handle": "param:code"}],
            })
        for kind_key, tool in (("model", "dl_classify"), ("source_id", "image_source")):
            with self.assertRaises(GraphError, msg=kind_key):
                validate_graph({
                    "nodes": [{"id": "i", "type": "intensity", "params": {}}, {"id": "t", "type": tool, "params": {}}],
                    "edges": [{"id": "e", "source": "i", "source_handle": "mean", "target": "t", "target_handle": f"param:{kind_key}"}],
                })

    def test_an_unknown_parameter_says_so(self):
        with self.assertRaisesMessage(GraphError, "has no parameter 'nope'"):
            validate_graph({
                "nodes": [{"id": "i", "type": "intensity", "params": {}}, {"id": "b", "type": "blob", "params": {}}],
                "edges": [{"id": "e", "source": "i", "source_handle": "mean", "target": "b", "target_handle": "param:nope"}],
            })

    def test_one_value_per_parameter(self):
        graph = self._graph()
        graph["nodes"].append({"id": "i2", "type": "intensity", "params": {}})
        graph["edges"].append({"id": "e4", "source": "src", "source_handle": "image", "target": "i2", "target_handle": "image"})
        graph["edges"].append({"id": "e5", "source": "i2", "source_handle": "mean", "target": "thr", "target_handle": "param:threshold"})
        with self.assertRaises(GraphError):
            validate_graph(graph)

    def test_no_value_from_upstream_falls_back_to_the_step(self):
        """上游這次沒算出值（定位補正找不到，dx 是 None）：丟掉那個覆蓋、記一筆，不讓整次 run 失敗。"""
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"mode": "input"}},
                {"id": "loc", "type": "shape_align", "params": {"ref_x": 10, "ref_y": 10}},
                {"id": "thr", "type": "threshold", "params": {"method": "fixed", "threshold": 77}},
            ],
            "edges": [
                {"id": "e1", "source": "src", "source_handle": "image", "target": "thr", "target_handle": "image"},
                {"id": "e2", "source": "loc", "source_handle": "dx", "target": "thr", "target_handle": "param:threshold"},
            ],
        }
        report = self._run(graph, np.zeros((40, 40), np.uint8))
        self.assertEqual(report.nodes["thr"].status, "ok")
        self.assertIn("77", report.nodes["thr"].message)  # 退回畫布上填的值
        self.assertTrue(any("could not be used" in log["message"] for log in report.nodes["thr"].logs), report.nodes["thr"].logs)

    def test_types_are_converted_the_way_the_parameter_needs(self):
        number = base.Param("threshold", "Threshold", kind="number")
        self.assertEqual(base.coerce_param(number, "12.5"), 12.5)
        self.assertIs(base.coerce_param(number, "abc"), base._BAD_PARAM)  # noqa: SLF001
        self.assertIs(base.coerce_param(number, None), base._BAD_PARAM)  # noqa: SLF001
        boolean = base.Param("on", "On", kind="boolean")
        self.assertIs(base.coerce_param(boolean, "yes"), True)
        self.assertIs(base.coerce_param(boolean, 0), False)
        region = base.Param("roi", "Region", kind="roi")
        self.assertEqual(base.coerce_param(region, {"shape": "rect", "x": 1, "y": 1, "w": 2, "h": 2})["shape"], "rect")
        self.assertIs(base.coerce_param(region, 5), base._BAD_PARAM)  # noqa: SLF001

    def test_autotune_leaves_bound_parameters_alone(self):
        from apps.vision.agent import autotune

        graph = self._graph()
        keys = {(d.node_id, d.key) for d in autotune.search_space(graph)}
        self.assertNotIn(("thr", "threshold"), keys)  # 調它沒有用，執行時會被上游蓋掉
        graph["edges"] = [e for e in graph["edges"] if e["id"] != "e3"]
        self.assertIn(("thr", "threshold"), {(d.node_id, d.key) for d in autotune.search_space(graph)})


class SwitchTests(SimpleTestCase):
    """一個料號一條路：`switch` 的分支埠數量看節點自己的設定。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    def _run(self, value, cases="A17\nB22\nC30", **params):
        return run_tool("switch", None, {"cases": cases, **params}, inputs={"value": value})

    def test_the_first_matching_case_wins(self):
        self.assertEqual(self._run("A17").branch, "case_1")
        self.assertEqual(self._run("B22").outputs["index"], 2)
        self.assertEqual(self._run("ZZZ").branch, "default")
        self.assertFalse(self._run("ZZZ").outputs["matched"])
        self.assertEqual(self._run("a17").branch, "case_1")  # 預設不分大小寫
        self.assertEqual(self._run("a17", case_sensitive=True).branch, "default")

    def test_matching_by_part_of_the_text_or_a_pattern(self):
        self.assertEqual(self._run("xx B22 yy", match="contains").branch, "case_2")
        self.assertEqual(self._run("A17-0091", match="prefix").branch, "case_1")
        self.assertEqual(self._run("abc123", cases="^[a-z]+" + chr(92) + "d+$", match="regex").branch, "case_1")
        self.assertEqual(self._run("abc", cases="(", match="regex").branch, "default")  # 樣式壞掉不算相符

    def test_numbers_and_ranges(self):
        self.assertEqual(self._run(15, cases="1-9\n10-20", match="number").branch, "case_2")
        self.assertEqual(self._run(5, cases="1-9\n10-20", match="number").branch, "case_1")
        self.assertEqual(self._run(99, cases="1-9\n10-20", match="number").branch, "default")
        self.assertEqual(self._run(7, cases="7", match="number").branch, "case_1")
        self.assertEqual(self._run("nope", cases="7", match="number").branch, "default")

    def test_the_settings_have_to_make_sense(self):
        with self.assertRaisesMessage(base.ToolError, "List the cases"):
            self._run("A17", cases="  ")
        with self.assertRaisesMessage(base.ToolError, "No value"):
            run_tool("switch", None, {"cases": "A"}, inputs={})

    def test_the_branch_ports_follow_the_settings(self):
        node = {"type": "switch", "params": {"cases": "A17\nB22"}}
        ports = base.case_ports(base.get("switch"), node)
        self.assertEqual([p.key for p in ports], ["case_1", "case_2"])
        self.assertEqual([p.label for p in ports], ["A17", "B22"])
        self.assertTrue(all(p.type == "flow" for p in ports))
        self.assertEqual(base.case_ports(base.get("switch"), {"params": {"cases": ""}}), ())
        self.assertEqual(base.case_ports(base.get("blob"), node), ())  # 沒宣告 cases_param 的工具沒有
        many = {"params": {"cases": chr(10).join(str(i) for i in range(50))}}
        self.assertEqual(len(base.case_ports(base.get("switch"), many)), base.MAX_CASES)

    def test_only_the_chosen_branch_runs(self):
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"mode": "input"}},
                {"id": "txt", "type": "format_text", "params": {"template": "B22"}},
                {"id": "sw", "type": "switch", "params": {"cases": "A17\nB22"}},
                {"id": "j1", "type": "judge", "params": {"verdict": "ok", "label": "first"}},
                {"id": "j2", "type": "judge", "params": {"verdict": "ok", "label": "second"}},
            ],
            "edges": [
                {"id": "e1", "source": "txt", "source_handle": "text", "target": "sw", "target_handle": "value"},
                {"id": "e2", "source": "sw", "source_handle": "case_1", "target": "j1", "target_handle": "_flow"},
                {"id": "e3", "source": "sw", "source_handle": "case_2", "target": "j2", "target_handle": "_flow"},
            ],
        }
        report = engine.execute(compile_graph(validate_graph(graph)), flow_id=0, flow_version=1, trigger="test",
                                grab=lambda s: None, asset_path=lambda a: None, input_image=np.zeros((8, 8), np.uint8))
        self.assertEqual(report.nodes["sw"].branch, "case_2")
        self.assertEqual(report.nodes["j1"].status, "skipped")
        self.assertEqual(report.nodes["j2"].status, "ok")

    def test_a_branch_that_does_not_exist_is_refused(self):
        graph = {
            "nodes": [{"id": "sw", "type": "switch", "params": {"cases": "A17"}},
                      {"id": "j", "type": "judge", "params": {"verdict": "ok"}}],
            "edges": [{"id": "e", "source": "sw", "source_handle": "case_9", "target": "j", "target_handle": "_flow"}],
        }
        with self.assertRaisesMessage(GraphError, "case_9"):
            validate_graph(graph)


class StringMatchTests(SimpleTestCase):
    """條碼是不是我們的、日期碼在不在允許清單裡。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        register_builtins()

    def _run(self, text, **params):
        params.setdefault("list", "OK\nPASS")
        return run_tool("string_match", None, params, inputs={"text": text})

    def test_found_and_not_found(self):
        r = self._run("PASS")
        self.assertEqual((r.branch, r.outputs["index"], r.outputs["matched"]), ("found", 2, "PASS"))
        self.assertTrue(r.outputs["found"])
        r = self._run("NOPE")
        self.assertEqual((r.branch, r.outputs["index"], r.outputs["matched"]), ("not_found", 0, ""))

    def test_case_and_the_ways_to_match(self):
        self.assertEqual(self._run("pass").branch, "found")
        self.assertEqual(self._run("pass", case_sensitive=True).branch, "not_found")
        self.assertEqual(self._run("the PASS one", match="contains").branch, "found")
        self.assertEqual(self._run("PASSED", match="prefix").branch, "found")
        self.assertEqual(self._run("A17-9", list="^A" + chr(92) + "d+", match="regex").branch, "found")

    def test_a_list_of_values_that_must_not_appear(self):
        r = self._run("GOOD", list="BAD\nSCRAP", invert=True)
        self.assertEqual((r.branch, r.outputs["found"]), ("found", True))
        self.assertEqual(self._run("BAD", list="BAD", invert=True).branch, "not_found")

    def test_the_settings_have_to_make_sense(self):
        with self.assertRaisesMessage(base.ToolError, "List the values"):
            self._run("x", list="   ")
        with self.assertRaisesMessage(base.ToolError, "Connect the text"):
            run_tool("string_match", None, {"list": "A"}, inputs={})

    def test_numbers_become_text_the_way_a_person_would_write_them(self):
        self.assertEqual(self._run(7.0, list="7").branch, "found")  # 7.0 是 "7"，不是 "7.0"


def _context(params: dict, inputs: dict) -> base.ToolContext:
    return base.ToolContext(
        run_id="r", flow_id=0, node={"params": params}, inputs=inputs, context={},
        moment=0.0, log=lambda *a, **k: None, asset_path=lambda _a: None, grab=lambda _s: None,
    )
