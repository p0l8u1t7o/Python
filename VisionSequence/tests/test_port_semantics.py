from __future__ import annotations

from django.test import SimpleTestCase

from apps.vision.tools import base
from apps.vision.tools.base import Port, Tool


INTENTIONALLY_GENERIC: dict[tuple[str, str, str], str] = {
    ("camera_set", "applied", "output"): "camera settings report object",
    ("camera_set", "errors", "output"): "camera settings error report",
    ("image_source", "applied", "output"): "camera settings report object",
    ("polar_restore", "mapping", "input"): "polar unwrap mapping has no safe shared semantic",
    ("polar_unwrap", "mapping", "output"): "polar unwrap mapping has no safe shared semantic",
    ("call_flow", "outputs", "output"): "child run named outputs dictionary",
    ("string_match", "text", "input"): "coerces arbitrary values to text",
    ("list_classify", "counts", "output"): "class name to count dictionary",
    ("formula", "a", "input"): "expression variable",
    ("formula", "b", "input"): "expression variable",
    ("formula", "c", "input"): "expression variable",
    ("formula", "d", "input"): "expression variable",
    ("list_pick", "value", "output"): "selected value, match or point",
    ("python_script", "a", "input"): "script-defined input",
    ("python_script", "b", "input"): "script-defined input",
    ("python_script", "c", "input"): "script-defined input",
    ("python_script", "d", "input"): "script-defined input",
    ("python_script", "data", "output"): "script-defined output",
    ("variable_get", "value", "output"): "stored variable value",
    ("switch", "value", "input"): "routing value",
    ("switch", "value", "output"): "routed value passthrough",
    ("list_sort", "first", "output"): "first value or match from the selected list",
    ("parse_message", "text", "input"): "coerces arbitrary values to text",
    ("parse_message", "first", "output"): "first parsed field with declared field type",
    ("variable_set", "value", "input"): "stored variable value",
    ("variable_set", "value", "output"): "stored variable value",
    ("variable_set", "previous", "output"): "previous stored variable value",
    ("camera_io", "status", "input"): "verdict value",
    ("format_text", "a", "input"): "template variable",
    ("format_text", "b", "input"): "template variable",
    ("format_text", "c", "input"): "template variable",
    ("format_text", "d", "input"): "template variable",
    ("io_output", "status", "input"): "verdict value",
    ("output", "value", "input"): "named output value",
    ("write_modbus", "values", "input"): "communication payload value",
    ("write_log", "a", "input"): "log template value",
    ("write_log", "b", "input"): "log template value",
    ("write_log", "c", "input"): "log template value",
    ("write_log", "d", "input"): "log template value",
}


def _tool(tool_key: str) -> dict:
    return next(t for t in base.catalogue() if t["key"] == tool_key)


def _port(tool_key: str, direction: str, port_key: str) -> dict:
    ports = _tool(tool_key)[direction]
    return next(p for p in ports if p["key"] == port_key)


class PortSemanticsTests(SimpleTestCase):
    def test_rejects_unknown_output_semantic(self):
        class BadTool(Tool):
            key = "bad_semantic_output"
            label = "Bad"
            outputs = [Port("value", "Value", "any", semantic="vector")]

        with self.assertRaisesRegex(RuntimeError, "semantic 'vector'"):
            base.register(BadTool())

    def test_rejects_unknown_input_semantic(self):
        class BadTool(Tool):
            key = "bad_semantic_input"
            label = "Bad"
            inputs = [Port("value", "Value", "any", accepts_semantics=("vector",))]

        with self.assertRaisesRegex(RuntimeError, "accepts semantic 'vector'"):
            base.register(BadTool())

    def test_catalogue_includes_semantic_fields(self):
        self.assertEqual(_port("find_circle", "outputs", "circle")["semantic"], "circle")
        self.assertEqual(_port("shape_align", "outputs", "transform")["semantic"], "transform")
        self.assertEqual(_port("coordinate", "outputs", "frame")["semantic"], "frame")
        self.assertEqual(_port("concentricity", "inputs", "a")["accepts_semantics"], ["circle"])
        self.assertEqual(_port("distance", "inputs", "a")["accepts_semantics"], ["point", "line", "circle"])
        self.assertEqual(_port("find_circle", "inputs", base.TRANSFORM_IN)["accepts_semantics"], ["transform"])

    def test_every_any_port_is_marked_or_whitelisted(self):
        missing: list[tuple[str, str, str]] = []
        for tool in base.all_types():
            for direction, ports in (("input", tool.inputs), ("output", tool.outputs)):
                for port in ports:
                    if port.type != "any":
                        continue
                    if port.semantic or port.accepts_semantics:
                        continue
                    key = (tool.key, port.key, direction)
                    if key not in INTENTIONALLY_GENERIC:
                        missing.append(key)
        self.assertEqual(missing, [])

    def test_representative_semantic_compatibility(self):
        circle = _port("find_circle", "outputs", "circle")
        transform = _port("shape_align", "outputs", "transform")
        concentricity_a = _port("concentricity", "inputs", "a")
        distance_a = _port("distance", "inputs", "a")
        self.assertIn(circle["semantic"], concentricity_a["accepts_semantics"])
        self.assertIn(circle["semantic"], distance_a["accepts_semantics"])
        self.assertNotIn(transform["semantic"], distance_a["accepts_semantics"])
