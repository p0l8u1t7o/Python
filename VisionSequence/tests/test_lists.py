from __future__ import annotations

from copy import deepcopy
from unittest import mock

from django.test import SimpleTestCase

from apps.vision.tools.base import ToolError
from tests._helpers import blank, run_tool


def _box(cx: float, cy: float, w: float = 10, h: float = 10, score: float = 0.5, label: str = "part") -> dict:
    return {"cx": cx, "cy": cy, "w": w, "h": h, "score": score, "angle": 0, "label": label}


class OcrPatternTests(SimpleTestCase):
    def _read_text(self, text: str, pattern: str, confusables: str | None = None):
        chars = [{"ch": ch, "conf": 0.9, "x0": i, "x1": i + 1, "y0": 0, "y1": 1} for i, ch in enumerate(text)]
        params = {"pattern": pattern, "min_confidence": 0.1}
        if confusables is not None:
            params["confusables"] = confusables
        with mock.patch("apps.vision.tools.builtin.ocr_tools.ocr.recognise_line", return_value=(text, chars)):
            return run_tool("ocr_read", blank(20, 80), params)

    def test_pattern_accepts_and_rejects_by_position(self):
        ok = self._read_text("12AB", "NNAA")
        self.assertEqual(ok.status, "ok")
        self.assertTrue(ok.outputs["pattern_ok"])
        self.assertEqual(ok.outputs["text"], "12AB")
        self.assertEqual(ok.outputs["corrected"], "12AB")

        ng = self._read_text("1A2B", "NNAA")
        self.assertEqual(ng.status, "ng")
        self.assertEqual(ng.branch, "not_found")
        self.assertFalse(ng.outputs["pattern_ok"])

    def test_confusables_only_apply_when_replacement_satisfies_pattern(self):
        r = self._read_text("O123", "NNNN")
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.outputs["text"], "O123")
        self.assertEqual(r.outputs["corrected"], "0123")
        self.assertEqual(r.outputs["corrections"], [{"index": 0, "from": "O", "to": "0", "pattern": "N"}])

        letter_slot = self._read_text("O123", "ANNN")
        self.assertEqual(letter_slot.outputs["corrected"], "O123")
        self.assertEqual(letter_slot.outputs["corrections"], [])

        cleared = self._read_text("O123", "NNNN", confusables="")
        self.assertEqual(cleared.status, "ng")
        self.assertEqual(cleared.outputs["corrected"], "O123")
        self.assertEqual(cleared.outputs["corrections"], [])


class ListPostProcessTests(SimpleTestCase):
    def test_boxes_merge_iou_keeps_highest_score_metadata(self):
        matches = [_box(10, 10, score=0.2), _box(12, 10, score=0.9), _box(50, 50, score=0.4)]
        r = run_tool("boxes_merge", None, {"mode": "iou", "threshold": 0.5, "keep": "highest_score"}, {"matches": matches})
        self.assertEqual(r.outputs["count"], 2)
        merged = max(r.outputs["matches"], key=lambda m: m.get("merged", 1))
        self.assertEqual(merged["merged"], 2)
        self.assertEqual(merged["score"], 0.9)

    def test_boxes_filter_by_area_and_score_reports_removed(self):
        matches = [_box(10, 10, w=4, h=4, score=0.9), _box(30, 10, w=10, h=10, score=0.4), _box(50, 10, w=12, h=12, score=0.8)]
        area = run_tool("boxes_filter", None, {"min_area": 50}, {"matches": matches})
        self.assertEqual(area.outputs["count"], 2)
        self.assertEqual(area.outputs["removed"], 1)
        score = run_tool("boxes_filter", None, {"min_score": 0.75}, {"matches": matches})
        self.assertEqual(score.outputs["count"], 2)
        self.assertEqual(score.outputs["removed"], 1)

    def test_array_correct_fills_missing_grid_cells(self):
        matches = []
        true_pos = {}
        missing_indices = {5, 10}
        for row in range(3):
            for col in range(4):
                idx = row * 4 + col
                cx, cy = 20 + col * 30, 25 + row * 40
                true_pos[idx] = (cx, cy)
                if idx not in missing_indices:
                    matches.append(_box(cx, cy, w=12, h=8, score=0.7))
        r = run_tool("array_correct", None, {"rows": 3, "cols": 4, "tolerance": 2}, {"matches": matches})
        self.assertEqual(r.status, "ng")
        self.assertEqual(r.branch, "ng")
        self.assertEqual({m["index"] for m in r.outputs["missing"]}, missing_indices)
        self.assertEqual(len(r.outputs["matches"]), 12)
        self.assertTrue(all(m.get("filled") for m in r.outputs["matches"] if m["grid_index"] in missing_indices))
        for miss in r.outputs["missing"]:
            want = true_pos[miss["index"]]
            self.assertLess(abs(miss["cx"] - want[0]), 2)
            self.assertLess(abs(miss["cy"] - want[1]), 2)

    def test_list_sort_xy_reading_order(self):
        matches = [_box(40, 40), _box(20, 12), _box(10, 40), _box(40, 10)]
        r = run_tool("list_sort", None, {"by": "xy"}, {"matches": matches})
        self.assertEqual([(m["cx"], m["cy"]) for m in r.outputs["matches"]], [(20, 12), (40, 10), (10, 40), (40, 40)])

    def test_list_tools_do_not_modify_inputs_and_report_type_errors(self):
        matches = [_box(10, 10, score=0.4), _box(12, 10, score=0.8), _box(50, 50, score=0.5)]
        original = deepcopy(matches)
        run_tool("boxes_merge", None, {"threshold": 0.5}, {"matches": matches})
        run_tool("boxes_filter", None, {"min_score": 0.5}, {"matches": matches})
        run_tool("list_sort", None, {"by": "score"}, {"matches": matches})
        self.assertEqual(matches, original)

        with self.assertRaisesMessage(ToolError, "needs matches"):
            run_tool("boxes_merge", None, {}, {"values": [1, 2, 3]})
        with self.assertRaisesMessage(ToolError, "either matches or values"):
            run_tool("list_sort", None, {}, {"matches": matches, "values": [1, 2, 3]})
