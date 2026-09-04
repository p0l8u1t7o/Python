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
