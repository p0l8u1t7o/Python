"""圖驗證與編譯。"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.core.errors import ValidationError
from apps.vision.graph import compile_graph, validate_graph
from apps.vision.tools.base import UnknownToolType


def n(nid: str, ntype: str, **params):
    return {"id": nid, "type": ntype, "params": params}


def e(s: str, t: str, sh: str = "", th: str = ""):
    return {"source": s, "target": t, "source_handle": sh, "target_handle": th}


class ValidateGraphTests(SimpleTestCase):
    def test_minimal_ok_and_defaults_fill_handles(self):
        g = validate_graph({"nodes": [n("a", "image_source"), n("b", "grayscale")], "edges": [e("a", "b")]})
        self.assertEqual(g["edges"][0]["source_handle"], "image")
        self.assertEqual(g["edges"][0]["target_handle"], "image")

    def test_unknown_tool_lists_available(self):
        with self.assertRaises(UnknownToolType) as ctx:
            validate_graph({"nodes": [n("a", "nope")], "edges": []})
        self.assertIn("grayscale", ctx.exception.details["available"])

    def test_duplicate_id(self):
        with self.assertRaises(ValidationError):
            validate_graph({"nodes": [n("a", "grayscale"), n("a", "grayscale")], "edges": []})

    def test_type_mismatch_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_graph({"nodes": [n("a", "image_source"), n("c", "if_number")], "edges": [e("a", "c", "image", "value")]})
        self.assertEqual(ctx.exception.code, "invalid_graph")

    def test_flow_handle_only_to_flow_input(self):
        with self.assertRaises(ValidationError):
            validate_graph({"nodes": [n("c", "if_number"), n("j", "judge")], "edges": [e("c", "j", "true", "value")]})
        validate_graph({"nodes": [n("c", "if_number"), n("j", "judge")], "edges": [e("c", "j", "true", "_flow")]})

    def test_cycle_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_graph({"nodes": [n("a", "grayscale"), n("b", "grayscale")], "edges": [e("a", "b"), e("b", "a")]})
        self.assertIn("cycle", ctx.exception.message)

    def test_note_cannot_be_target(self):
        with self.assertRaises(ValidationError):
            validate_graph({"nodes": [n("a", "grayscale"), {"id": "x", "type": "note"}], "edges": [e("a", "x")]})

    def test_single_input_port_rejects_two_edges(self):
        with self.assertRaises(ValidationError):
            validate_graph({"nodes": [n("a", "image_source"), n("b", "image_source"), n("g", "grayscale")], "edges": [e("a", "g"), e("b", "g")]})

    def test_multiple_port_allows_two_edges(self):
        validate_graph({"nodes": [n("a", "if_number"), n("b", "if_number"), n("l", "bool_logic")], "edges": [e("a", "l", "result", "values"), e("b", "l", "result", "values")]})


class CompileGraphTests(SimpleTestCase):
    def test_implicit_ports_come_from_one_table(self):
        """隱含埠的型別、單／多線、進不進目錄都讀 tools/base.py 的那張表——加新的埠只要補一筆。"""
        from apps.vision.tools import base

        # 表本身：控制輸入可多線且不進目錄，影像直通單線、由引擎收值
        flow_in = base.implicit_input(base.FLOW_IN)
        thru_in = base.implicit_input(base.IMAGE_THRU)
        self.assertEqual((flow_in.type, flow_in.multiple, flow_in.catalogued), ("flow", True, False))
        self.assertEqual((thru_in.type, thru_in.multiple, thru_in.collect), ("image", False, True))
        self.assertIsNone(base.implicit_input(base.OVERLAYS_OUT))  # 標記只是輸出
        self.assertIsNone(base.implicit_output(base.FLOW_IN))
        # 驗證走表：兩條線接同一個直通輸入要擋（隱含埠不在工具的宣告清單裡，不能讓 next() 炸掉）
        g = {"nodes": [n("a", "image_source"), n("b", "image_source"), n("c", "judge")],
             "edges": [e("a", "c", "image", "_image"), e("b", "c", "image", "_image")]}
        with self.assertRaises(ValidationError) as ctx:
            validate_graph(g)
        self.assertIn("only one connection", str(ctx.exception))
        # 控制輸入可以接多條
        multi = {"nodes": [n("c1", "if_number"), n("c2", "if_number"), n("j", "judge")],
                 "edges": [e("c1", "j", "true", "_flow"), e("c2", "j", "false", "_flow")]}
        self.assertEqual(len(validate_graph(multi)["edges"]), 2)

    def test_order_and_consumed(self):
        g = validate_graph({
            "nodes": [n("src", "image_source"), n("g", "grayscale"), n("t", "threshold"), n("c", "if_number"), n("j", "judge")],
            "edges": [e("src", "g"), e("g", "t"), e("t", "c", "threshold_used", "value"), e("c", "j", "true", "_flow")],
        })
        c = compile_graph(g)
        self.assertEqual(c.order, ["src", "g", "t", "c", "j"])
        self.assertIn(("src", "image"), c.consumed)
        self.assertNotIn(("t", "image"), c.consumed)
        self.assertEqual(c.nodes["j"].flow_inputs, [("c", "true")])
        self.assertEqual(c.nodes["g"].primary_image_port, "image")
