"""執行訊息的代碼與中文樣板（PM-REVIEW-R2 L-4 第 1 點）。

靜態掃描 apps/ 底下所有 `Msg.of("代碼", "樣板", ...)`：每個代碼在兩份中文字典都要有、中文的佔位符不超出樣板、
同一代碼只對一個樣板、字典裡沒有已經不存在的代碼。新增或改寫訊息時跟著補 frontend/src/i18n/locales/toolMessages.*.ts。
"""

from __future__ import annotations

import ast
import copy
import json
import pickle
import re
from pathlib import Path

from django.test import SimpleTestCase

from apps.vision.engine import NodeReport, RunReport
from apps.vision.tools.messages import Msg, fields, parts

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "frontend" / "src" / "i18n" / "locales"
ENTRY = re.compile(r"^\s*'([A-Za-z0-9_.]+)':\s*'((?:[^'\\]|\\.)*)',\s*$", re.M)
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def backend_messages() -> dict[str, set[str]]:
    """代碼 → 樣板集合（同一代碼應該只有一個樣板）。"""
    found: dict[str, set[str]] = {}
    for path in (ROOT / "apps").rglob("*.py"):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "of"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "Msg"):
                continue
            args = node.args
            if len(args) < 2 or not all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in args[:2]):
                raise AssertionError(f"{path.relative_to(ROOT)}:{node.lineno}: Msg.of needs a literal code and template")
            found.setdefault(args[0].value, set()).add(args[1].value)
    return found


def dictionary(name: str) -> dict[str, str]:
    return dict(ENTRY.findall((LOCALES / name).read_text(encoding="utf-8")))


class MsgTests(SimpleTestCase):
    def test_msg_is_the_english_sentence_with_display_arguments(self):
        m = Msg.of("template_match.found", "{n} matches, best {score:.3f} @ ({x:.1f}, {y:.1f})", n=3, score=0.97512, x=10, y=20.04)
        self.assertEqual(m, "3 matches, best 0.975 @ (10.0, 20.0)")
        self.assertEqual(parts(m), ("template_match.found", {"n": "3", "score": "0.975", "x": "10.0", "y": "20.0"}))
        self.assertEqual(Msg.of("t.r", "bad {raw!r}", raw="x").args, {"raw": "'x'"})
        self.assertEqual(json.dumps(m), json.dumps("3 matches, best 0.975 @ (10.0, 20.0)"))
        self.assertEqual(copy.deepcopy(m).code, "template_match.found")
        self.assertEqual(pickle.loads(pickle.dumps(m)).args["score"], "0.975")
        self.assertEqual(parts("plain"), ("", {}))
        self.assertEqual(fields("{a} and {b:.2f} and {a}"), ["a", "b"])

    def test_every_code_has_both_chinese_templates(self):
        codes = backend_messages()
        self.assertTrue(codes, "no Msg.of calls found")
        mixed = {code: sorted(t) for code, t in codes.items() if len({tuple(sorted(fields(x))) for x in t}) > 1}
        self.assertEqual(mixed, {}, "the same code is used with different placeholders")
        for name in ("toolMessages.zh-Hant.ts", "toolMessages.zh-Hans.ts"):
            zh = dictionary(name)
            missing = sorted(set(codes) - set(zh))
            stale = sorted(set(zh) - set(codes))
            self.assertEqual(missing, [], f"{name} is missing these codes")
            self.assertEqual(stale, [], f"{name} has codes nothing uses any more")
            extra = {code: sorted(set(PLACEHOLDER.findall(text)) - set(fields(next(iter(codes[code])))))
                     for code, text in zh.items() if set(PLACEHOLDER.findall(text)) - set(fields(next(iter(codes[code]))))}
            self.assertEqual(extra, {}, f"{name} uses placeholders the English template does not have")

    def test_rejecting_comparison_keeps_the_code_with_its_label(self):
        # 比較工具判 NG 時接上使用者的標籤：英文照舊是「句子 (標籤)」，代碼不能因為字串相加而消失
        from types import SimpleNamespace

        from apps.vision.tools.base import apply_reject

        ctx = SimpleNamespace(param=lambda key, default=None: {"on_false": "reject", "ng_label": "Too big"}.get(key, default), context={})
        message = Msg.of("if_number.false", "{value} is not above {limit}", value=5, limit=3)
        status, out, context = apply_reject(ctx, False, message)
        self.assertEqual(status, "ng")
        self.assertEqual(str(out), "5 is not above 3 (Too big)")
        self.assertEqual(parts(out), ("if_number.false", {"value": "5", "limit": "3", "ng_label": "Too big"}))
        self.assertEqual(context["_outputs"]["judge_label"], "Too big")
        # 普通字串照舊相加
        self.assertEqual(apply_reject(ctx, False, "plain")[1], "plain (Too big)")

    def test_reports_carry_the_code_and_arguments(self):
        report = RunReport(id="x", flow_id=1, flow_version=1, trigger="test")
        from apps.vision import engine

        node = NodeReport()
        engine._set_message(node, Msg.of("engine.upstream_skipped", "upstream '{node}' skipped", node="find"))
        report.nodes["n"] = node
        out = report.to_dict()["nodes"]["n"]
        self.assertEqual((out["message"], out["message_code"], out["message_args"]), ("upstream 'find' skipped", "engine.upstream_skipped", {"node": "find"}))
        self.assertIs(type(node.message), str)
        engine._set_message(node, "plain text")
        self.assertEqual((node.message_code, node.message_args), ("", {}))

    def test_folded_composite_keeps_the_inner_code(self):
        from apps.vision import composites

        report = RunReport(id="x", flow_id=1, flow_version=1, trigger="test")
        report.nodes["c.a"] = NodeReport(status="ng", message="0 matches", message_code="template_match.none", message_args={"n": "0"})
        composites.fold_report(report, {"c": {"inner": ["c.a"], "outputs": {}, "tool": "t", "enabled": True}})
        self.assertEqual((report.nodes["c"].message_code, report.nodes["c"].message_args), ("template_match.none", {"n": "0"}))

    def test_inspect_readings_carry_the_reason_code(self):
        from apps.vision import inspect

        row = inspect._reading("t", "skipped", False, None, None, "", Msg.of("inspect.step_disabled", "A task step is disabled"), [], "n")
        self.assertEqual((row["reason"], row["reason_code"]), ("A task step is disabled", "inspect.step_disabled"))
        self.assertIs(type(row["reason"]), str)
        plain = inspect._reading("t", "pass", True, True, 1, "", "done", [], "n")
        self.assertEqual((plain["reason_code"], plain["reason_args"]), ("", {}))
