"""邏輯工具：數值比較分支、公式、布林組合。"""

from __future__ import annotations

import re

import numpy as np

import ast
import math
import operator
from typing import Any

from apps.vision.tools.base import MAX_CASES, Param, Port, Result, Tool, ToolContext, ToolError, apply_reject, flow_out, reject_params
from apps.vision.tools.messages import Msg

_OPS = {
    "gt": operator.gt, "ge": operator.ge, "lt": operator.lt, "le": operator.le,
    "eq": operator.eq, "ne": operator.ne,
}
_OP_LABEL = {"gt": ">", "ge": "≥", "lt": "<", "le": "≤", "eq": "=", "ne": "≠"}


class CompareNumberTool(Tool):
    key = "if_number"
    label = "Compare number"
    description = "Compares a value against a threshold and takes the true or false branch. Steps wired to a branch handle run only when that branch is taken."
    category = "logic"
    icon = "GitBranch"
    params = [
        Param("operator", "Compare", kind="select", default="gt", required=True,
              options=[{"value": k, "label": v} for k, v in _OP_LABEL.items()]),
        Param("threshold", "Threshold", kind="number", required=True, default=0, teach=True),
        Param("tolerance", "Tolerance (for = and ≠)", kind="number", default=0, minimum=0),
        *reject_params(),
    ]
    inputs = [Port("value", "Value", "number")]
    outputs = [flow_out("true", "True", "ok"), flow_out("false", "False", "critical"), Port("result", "Result", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        value = ctx.inputs.get("value")
        if value is None:
            raise ToolError(Msg.of("if_number.no_value", "No value on the input"))
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ToolError(Msg.of("if_number.not_number", "The input is not a number: {value!r}", value=value)) from None
        op = ctx.param("operator", "gt")
        threshold = ctx.number("threshold")
        tol = ctx.number("tolerance")
        if op == "eq":
            ok = abs(v - threshold) <= tol
        elif op == "ne":
            ok = abs(v - threshold) > tol
        else:
            ok = _OPS[op](v, threshold)
        message = Msg.of("if_number.compare", "{value:g} {op} {threshold:g} → {ok}", value=v, op=_OP_LABEL[op], threshold=threshold, ok=ok)
        status, message, context = apply_reject(ctx, ok, message)
        return Result(
            outputs={"result": ok},
            branch="true" if ok else "false",
            status=status,
            message=message,
            context=context,
        )


class CompareRangeTool(Tool):
    key = "in_range"
    label = "In range"
    description = "Whether a value falls inside [lower, upper]; the usual way to check a measurement against limits."
    category = "logic"
    icon = "Ruler"
    params = [
        Param("low", "Lower", kind="number", required=True, default=0, teach=True),
        Param("high", "Upper", kind="number", required=True, default=100, teach=True),
        *reject_params(),
    ]
    inputs = [Port("value", "Value", "number")]
    outputs = [flow_out("inside", "In range", "ok"), flow_out("outside", "Out of range", "critical"), Port("result", "Result", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        value = ctx.inputs.get("value")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ToolError(Msg.of("in_range.not_number", "The input is not a number: {value!r}", value=value)) from None
        low, high = ctx.number("low"), ctx.number("high")
        ok = low <= v <= high
        message = Msg.of("in_range.check", "{value:g} ∈ [{low:g}, {high:g}] → {ok}", value=v, low=low, high=high, ok=ok)
        status, message, context = apply_reject(ctx, ok, message)
        return Result(outputs={"result": ok}, branch="inside" if ok else "outside",
                      status=status, message=message, context=context)


class BoolLogicTool(Tool):
    key = "bool_logic"
    label = "Boolean logic"
    description = "Combines boolean inputs with AND, OR or NOT and takes the true or false branch."
    category = "logic"
    icon = "Binary"
    params = [
        Param("mode", "Operation", kind="select", default="and", options=[
            {"value": "and", "label": "AND (all true)"},
            {"value": "or", "label": "OR (any true)"},
            {"value": "nand", "label": "NOT AND"},
            {"value": "nor", "label": "NOT OR"},
        ]),
    ]
    inputs = [Port("values", "Boolean", "bool", multiple=True, required=True)]
    outputs = [flow_out("true", "True", "ok"), flow_out("false", "False", "critical"), Port("result", "Result", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        values = [bool(v) for v in (ctx.inputs.get("values") or []) if v is not None]
        if not values:
            raise ToolError(Msg.of("bool_logic.no_input", "No boolean input is connected"))
        mode = ctx.param("mode", "and")
        base = all(values) if mode in ("and", "nand") else any(values)
        ok = (not base) if mode in ("nand", "nor") else base
        return Result(outputs={"result": ok}, branch="true" if ok else "false", message=Msg.of("bool_logic.result", "{mode}({values}) → {ok}", mode=mode, values=values, ok=ok))


# -- 安全的公式求值 -----------------------------------------------------------
_ALLOWED_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_ALLOWED_CMP = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Eq: operator.eq, ast.NotEq: operator.ne}
_FUNCS: dict[str, Any] = {
    "abs": abs, "min": min, "max": max, "round": round, "len": len, "sum": sum,
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "atan2": math.atan2,
    "degrees": math.degrees, "radians": math.radians, "hypot": math.hypot, "floor": math.floor, "ceil": math.ceil,
    "pi": math.pi, "int": int, "float": float, "bool": bool, "str": str,
}


def safe_eval(expr: str, names: dict[str, Any]) -> Any:
    tree = ast.parse(expr, mode="eval")

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in names:
                return names[node.id]
            if node.id in _FUNCS:
                return _FUNCS[node.id]
            raise ToolError(Msg.of("formula.unknown_name", "Unknown name '{name}' in the expression", name=node.id))
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BIN:
            return _ALLOWED_BIN[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -ev(node.operand)
            if isinstance(node.op, ast.Not):
                return not ev(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +ev(node.operand)
        if isinstance(node, ast.BoolOp):
            vals = [ev(v) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = ev(comp)
                if type(op) not in _ALLOWED_CMP or not _ALLOWED_CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return ev(node.body) if ev(node.test) else ev(node.orelse)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        if isinstance(node, ast.Subscript):
            return ev(node.value)[ev(node.slice)]
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(e) for e in node.elts]
        raise ToolError(Msg.of("formula.unsupported_syntax", "Unsupported syntax in the expression: {syntax}", syntax=type(node).__name__))

    return ev(tree)


class FormulaTool(Tool):
    key = "formula"
    label = "Expression"
    description = "Write an expression over the inputs a, b, c and d, for example abs(a-b)/c*100. Arithmetic, comparisons, and/or, and abs, min, max, sqrt and friends are supported."
    category = "logic"
    icon = "Sigma"
    params = [
        Param("expression", "Expression", kind="expression", required=True, default="a", help_text="The variables a, b, c and d are the four inputs; the result may be a number or a boolean."),
    ]
    inputs = [
        Port("a", "a", "any", required=False), Port("b", "b", "any", required=False),
        Port("c", "c", "any", required=False), Port("d", "d", "any", required=False),
    ]
    outputs = [Port("value", "Value", "number"), Port("result", "Boolean", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        expr = str(ctx.param("expression", "")).strip()
        if not expr:
            raise ToolError(Msg.of("formula.empty", "The expression is empty"))
        names = {k: ctx.inputs.get(k) for k in ("a", "b", "c", "d")}
        try:
            value = safe_eval(expr, names)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolError(Msg.of("formula.error", "Expression error: {error}", error=exc)) from None
        number = float(value) if isinstance(value, (int, float, bool)) else float("nan")
        return Result(outputs={"value": number, "result": bool(value)}, message=_clip(Msg.of("formula.result", "{expr} = {value!r}", expr=expr, value=value), 200))


class CounterTool(Tool):
    key = "count_list"
    label = "Count"
    description = "The number of elements in the list, points or matches output."
    category = "logic"
    icon = "Hash"
    inputs = [Port("items", "List", "list")]
    outputs = [Port("count", "Count", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        items = ctx.inputs.get("items")
        try:
            n = len(items)  # type: ignore[arg-type]
        except TypeError:
            n = 0 if items is None else 1
        return Result(outputs={"count": n}, message=Msg.of("count_list.count", "{n} items", n=n))



SCOPE_OPTIONS = [{"value": "flow", "label": "This flow"}, {"value": "station", "label": "Whole station"}]


class VariableGetTool(Tool):
    key = "variable_get"
    label = "Read a variable"
    description = (
        "Reads a value that survives between runs: a running count, the previous part's result, or the lot number a "
        "PLC sent with SET. Falls back to the default when nothing has been stored yet."
    )
    category = "logic"
    icon = "Database"
    params = [
        Param("name", "Variable", kind="text", required=True, default="counter", help_text="Letters, digits and underscores."),
        Param("scope", "Scope", kind="select", default="flow", options=SCOPE_OPTIONS, help_text="This flow only, or shared by every flow on the station."),
        Param("default", "Default", kind="text", default="0", help_text="Used until something is stored. A number stays a number; true and false are booleans."),
    ]
    inputs: list[Port] = []
    outputs = [Port("value", "Value", "any"), Port("number", "As number", "number"), Port("text", "As text", "string"), Port("found", "Was set", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        from apps.vision import variables as _vars

        name = str(ctx.param("name", "") or "")
        scope = str(ctx.param("scope", "flow"))
        try:
            value = ctx.variable(name, _MISSING, scope)
        except _vars.VariableError as exc:
            raise ToolError(str(exc)) from None
        found = value is not _MISSING
        if not found:
            value = _vars.parse_default(ctx.param("default", None))
        number = float("nan")
        if isinstance(value, bool):
            number = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                number = float("nan")
        text = "" if value is None else (value if isinstance(value, str) else str(value))
        return Result(outputs={"value": value, "number": number, "text": text, "found": found},
                      message=(Msg.of("variable_get.value", "{name} = {text}", name=name, text=text[:80]) if found
                               else Msg.of("variable_get.default", "{name} = {text} (default)", name=name, text=text[:80])))


class VariableSetTool(Tool):
    key = "variable_set"
    label = "Store a variable"
    description = (
        "Keeps a value for later runs: store it, add to it (a running count or total), or keep the largest or smallest "
        "seen. Read it back anywhere with Read a variable, or from outside with GET /flows/{id}/variables and TCP VARS."
    )
    category = "logic"
    icon = "DatabaseZap"
    params = [
        Param("name", "Variable", kind="text", required=True, default="counter"),
        Param("scope", "Scope", kind="select", default="flow", options=SCOPE_OPTIONS),
        Param("mode", "How", kind="select", default="set", options=[
            {"value": "set", "label": "Store the value"},
            {"value": "add", "label": "Add to it (count, total)"},
            {"value": "max", "label": "Keep the largest"},
            {"value": "min", "label": "Keep the smallest"},
        ]),
    ]
    inputs = [Port("value", "Value", "any", required=False)]
    outputs = [Port("value", "Stored value", "any"), Port("previous", "Previous value", "any")]

    def execute(self, ctx: ToolContext) -> Result:
        from apps.vision import variables as _vars

        name = str(ctx.param("name", "") or "")
        scope = str(ctx.param("scope", "flow"))
        mode = str(ctx.param("mode", "set"))
        value = ctx.inputs.get("value")
        if value is None and mode == "add":
            value = 1  # 沒接輸入的「加」就是計數
        if value is None:
            raise ToolError(Msg.of("variable_set.no_value", "Wire a value in"))
        try:
            if mode in ("add", "max", "min"):
                current = ctx.variable(name, None, scope)
                try:
                    incoming = float(value)
                except (TypeError, ValueError):
                    raise ToolError(Msg.of("variable_set.not_number", "'{mode}' needs a number, got {value!r}", mode=mode, value=value)) from None
                try:
                    base = float(current) if current is not None else None
                except (TypeError, ValueError):
                    base = None
                if base is None:
                    result: Any = incoming
                elif mode == "add":
                    result = base + incoming
                elif mode == "max":
                    result = max(base, incoming)
                else:
                    result = min(base, incoming)
                if float(result).is_integer() and isinstance(value, (int, float)) and not isinstance(value, bool) and (current is None or float(current).is_integer()):
                    result = int(result)
                previous = ctx.set_variable(name, result, scope)
                stored = result
            else:
                previous = ctx.set_variable(name, value, scope)
                stored = ctx.variable(name, None, scope)
        except _vars.VariableError as exc:
            raise ToolError(str(exc)) from None
        shown = stored if not isinstance(stored, np.ndarray) else f"image {stored.shape[1]}x{stored.shape[0]}"
        message = (Msg.of("variable_set.stored_trial", "{name} = {value} (trial: not kept)", name=name, value=str(shown)[:80]) if ctx.sandboxed()
                   else Msg.of("variable_set.stored", "{name} = {value}", name=name, value=str(shown)[:80]))
        return Result(outputs={"value": stored, "previous": previous}, message=message)


_MISSING = object()

class SwitchTool(Tool):
    key = "switch"
    label = "Route by value"
    description = (
        "Sends the run down a different path for each value: one branch per part number, per recipe code, per grade. Write the "
        "cases one per line and the step grows an output for each; anything that matches none of them takes the default branch."
    )
    category = "logic"
    icon = "GitFork"
    cases_param = "cases"
    params = [
        Param("cases", "Cases", kind="multiline", required=True, default="A17\\nB22\\nC30", teach=True,
              help_text=(
                  "One per line, in order; the first match wins. With Match set to a number a line may be a single value (12) "
                  "or a range (10-20). The step grows one output per line, plus the default."
              )),
        Param("match", "Match", kind="select", default="exact", options=[
            {"value": "exact", "label": "The value is exactly this"},
            {"value": "contains", "label": "The value contains this"},
            {"value": "prefix", "label": "The value starts with this"},
            {"value": "regex", "label": "A pattern (regular expression)"},
            {"value": "number", "label": "A number or a range (10-20)"},
        ]),
        Param("case_sensitive", "Match upper and lower case", kind="boolean", default=False, group="Advanced",
              visible_when={"param": "match", "in": ["exact", "contains", "prefix", "regex"]}),
    ]
    inputs = [Port("value", "Value", "any")]
    outputs = [
        flow_out("default", "None of them", "warn"),
        Port("index", "Which case", "number"), Port("matched", "Matched", "bool"), Port("value", "Value", "any"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        value = ctx.inputs.get("value")
        if value is None:
            raise ToolError(Msg.of("switch.no_value", "No value on the input"))
        cases = [ln.strip() for ln in str(ctx.param("cases", "") or "").splitlines() if ln.strip()][:MAX_CASES]
        if not cases:
            raise ToolError(Msg.of("switch.no_cases", "List the cases, one per line"))
        mode = str(ctx.param("match", "exact"))
        index = match_case(value, cases, mode, case_sensitive=ctx.flag("case_sensitive"))
        branch = f"case_{index}" if index else "default"
        shown = _plain_text(value)
        return Result(
            outputs={"index": index, "matched": bool(index), "value": value},
            branch=branch,
            message=(Msg.of("switch.case", "{value} -> {case}", value=shown[:40], case=cases[index - 1]) if index
                     else Msg.of("switch.default", "{value} -> default", value=shown[:40])),
        )


class StringMatchTool(Tool):
    key = "string_match"
    label = "Check text"
    description = (
        "Checks a piece of text against a list: is this barcode one of ours, is this date code in the allowed set, does the "
        "reading contain the part number. Takes the found or not-found branch and reports which entry matched."
    )
    category = "logic"
    icon = "SearchCheck"
    params = [
        Param("list", "Allowed values", kind="multiline", required=True, default="OK", teach=True,
              help_text="One per line. With Match set to a pattern each line is a regular expression."),
        Param("match", "Match", kind="select", default="exact", options=[
            {"value": "exact", "label": "The text is exactly this"},
            {"value": "contains", "label": "The text contains this"},
            {"value": "prefix", "label": "The text starts with this"},
            {"value": "regex", "label": "A pattern (regular expression)"},
        ]),
        Param("case_sensitive", "Match upper and lower case", kind="boolean", default=False),
        Param("invert", "Fail when it does match", kind="boolean", default=False, group="Advanced",
              help_text="For a list of values that must not appear."),
        *reject_params(),
    ]
    inputs = [Port("text", "Text", "any")]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("found", "Found", "bool"), Port("index", "Which entry", "number"),
        Port("matched", "The entry that matched", "string"), Port("text", "Text", "string"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        value = ctx.inputs.get("text")
        if value is None:
            raise ToolError(Msg.of("string_match.no_text", "Connect the text to check"))
        entries = [ln.strip() for ln in str(ctx.param("list", "") or "").splitlines() if ln.strip()]
        if not entries:
            raise ToolError(Msg.of("string_match.no_list", "List the values to check against, one per line"))
        text = _plain_text(value)
        index = match_case(text, entries, str(ctx.param("match", "exact")), case_sensitive=ctx.flag("case_sensitive"))
        found = bool(index) != ctx.flag("invert")
        message = (Msg.of("string_match.matches", "'{text}' matches — {entry}", text=text[:40], entry=entries[index - 1]) if index
                   else Msg.of("string_match.no_match", "'{text}' matches nothing", text=text[:40]))
        status, message, context = apply_reject(ctx, found, message)
        return Result(
            outputs={"found": found, "index": index, "matched": entries[index - 1] if index else "", "text": text},
            branch="found" if found else "not_found",
            status=status,
            message=message,
            context=context,
        )


def _clip(text: str, limit: int) -> str:
    """過長的訊息照舊截斷英文，但保留代碼與參數。"""
    if len(text) <= limit:
        return text
    if isinstance(text, Msg):
        return Msg(str(text)[:limit], text.code, text.args)
    return text[:limit]


def _plain_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def match_case(value: Any, cases: list[str], mode: str, *, case_sensitive: bool = False) -> int:
    """第一個相符的案例（1 起算）；都不符回 0。純函式，`switch` 與 `string_match` 共用。"""
    if mode == "number":
        try:
            number = float(_plain_text(value))
        except (TypeError, ValueError):
            return 0
        for i, case in enumerate(cases):
            low, sep, high = case.partition("-")
            try:
                if sep and low.strip():
                    if float(low) <= number <= float(high):
                        return i + 1
                elif abs(number - float(case)) < 1e-9:
                    return i + 1
            except (TypeError, ValueError):
                continue
        return 0
    text = _plain_text(value)
    hay = text if case_sensitive else text.lower()
    for i, case in enumerate(cases):
        needle = case if case_sensitive else case.lower()
        if mode == "contains" and needle in hay:
            return i + 1
        if mode == "prefix" and hay.startswith(needle):
            return i + 1
        if mode == "regex":
            try:
                if re.search(case, text, 0 if case_sensitive else re.IGNORECASE):
                    return i + 1
            except re.error:
                continue
        elif mode == "exact" and hay == needle:
            return i + 1
    return 0


class ParseMessageTool(Tool):
    key = "parse_message"
    label = "Split a message"
    description = (
        "Splits one piece of text into named values: a barcode payload like LOT12345|2026-09-08|A7, a line read by OCR, "
        "or a message the host sent with the trigger. Each field becomes a named output, so a later step can judge it, "
        "compare it or send it back."
    )
    category = "logic"
    icon = "SplitSquareHorizontal"
    params = [
        Param("mode", "How it is laid out", kind="select", default="delimiter", options=[
            {"value": "delimiter", "label": "Fields separated by a character"},
            {"value": "regex", "label": "A pattern (regular expression)"},
            {"value": "fixed", "label": "Fixed byte positions"},
        ]),
        Param("separator", "Separator", kind="text", default=",", teach=True,
              visible_when={"param": "mode", "in": ["delimiter"]},
              help_text="One or more characters. Type \\t for a tab."),
        Param("pattern", "Pattern", kind="text", default="", teach=True,
              visible_when={"param": "mode", "in": ["regex"]},
              help_text=r"For example LOT(?P<lot>\d+)\s+(?P<qty>\d+). Named groups fill the field of the same name; otherwise the groups fill the fields in order."),
        Param(
            "fields", "Fields", kind="multiline", required=True, default="lot\ndate\nslot:int",
            teach=True,
            help_text=(
                "One field per line, in order. Just a name takes the next piece as text; add a type with a colon "
                "(name:int, name:float, name:bool, name:hex). Take a piece out of order with its position, counting from 0 "
                "(name:int:3). For fixed byte positions give the byte range instead (name:int:0-1) and, when the equipment "
                "sends them the other way round, the byte order (name:float:2-5:DCBA). Multiply a number with *0.01 when the "
                "equipment sends 1234 for 12.34."
            ),
        ),
        Param("publish", "Add to the reply", kind="boolean", default=True,
              help_text="Each field also becomes a named output, so the HTTP and TCP replies carry it."),
        Param("prefix", "Name prefix", kind="text", default="", group="Advanced",
              help_text="Put in front of every field name in the reply, to keep two messages apart."),
        Param("on_missing", "When a field has no value", kind="select", default="pass", options=[
            {"value": "pass", "label": "Leave it empty and carry on"},
            {"value": "fail", "label": "Fail the step"},
        ], group="Advanced"),
    ]
    inputs = [Port("text", "Text", "any")]
    outputs = [
        flow_out("matched", "Matched", tone="ok"),
        flow_out("not_matched", "Not matched", tone="warn"),
        Port("fields", "Fields", "list"),
        Port("count", "Fields found", "number"),
        Port("first", "First field", "any"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        from apps.comm import protocol

        payload = ctx.inputs.get("text")
        if payload is None:
            raise ToolError(Msg.of("parse_message.no_text", "Connect the text to split (a barcode, an OCR reading or a value)"))
        lines = [ln.strip() for ln in str(ctx.param("fields", "") or "").splitlines() if ln.strip()]
        if not lines:
            raise ToolError(Msg.of("parse_message.no_fields", "List the fields, one per line, for example lot or slot:int"))
        mode = str(ctx.param("mode", "delimiter"))
        try:
            spec = protocol.Spec(
                mode=mode,
                fields=[_field_from_line(ln, i) for i, ln in enumerate(lines)],
                separator=str(ctx.param("separator", ",")),
                pattern=str(ctx.param("pattern", "")),
            )
            values = protocol.parse(spec, payload)
        except protocol.ProtocolError as exc:
            raise ToolError(str(exc)) from None
        found = {k: v for k, v in values.items() if v is not None}
        prefix = str(ctx.param("prefix", "") or "")
        if ctx.flag("publish", True):
            outputs = dict(ctx.context.get("_outputs") or {})
            for k, v in values.items():
                outputs[f"{prefix}{k}"] = v
            context = {"_outputs": outputs}
        else:
            context = {}
        ok = len(found) == len(values)
        if not ok and str(ctx.param("on_missing", "pass")) == "fail":
            status = "ng"
        else:
            status = "ok"
        items = [{"name": k, "value": v} for k, v in values.items()]
        first = next(iter(values.values()), None)
        summary = "、".join(f"{k}={v}" for k, v in list(values.items())[:4]) or "(none)"
        return Result(
            status=status,
            outputs={"fields": items, "count": len(found), "first": first, **values},
            branch="matched" if ok else "not_matched",
            context=context,
            message=_clip(Msg.of("parse_message.summary", "{found}/{total}: {summary}", found=len(found), total=len(values), summary=summary), 200),
        )


def _field_from_line(line: str, order: int) -> Any:
    """一行欄位設定 → protocol.Field。語法：name[:type][:位置或位元組範圍][:位元組順序][*倍率]

    `lot`、`slot:int`、`qty:int:3`（第 3 段）、`w:float:2-5:DCBA`（位元組 2~5，小端）、`w:int:0-1*0.01`。
    """
    from apps.comm import protocol

    text, scale = line, 1.0
    if "*" in text:
        text, _, raw = text.partition("*")
        try:
            scale = float(raw)
        except ValueError:
            raise ToolError(Msg.of("parse_message.bad_multiplier", "'{line}': the multiplier after * is not a number", line=line)) from None
    parts = [p.strip() for p in text.split(":")]
    name = parts[0]
    kind = parts[1].lower() if len(parts) > 1 and parts[1] else "string"
    where = parts[2] if len(parts) > 2 and parts[2] else ""
    byte_order = parts[3].upper() if len(parts) > 3 and parts[3] else "ABCD"
    index = start = end = None
    if "-" in where:
        a, _, b = where.partition("-")
        try:
            start, end = int(a), int(b)
        except ValueError:
            raise ToolError(Msg.of("parse_message.bad_range", "'{line}': the byte range should look like 0-3", line=line)) from None
    elif where:
        try:
            index = int(where)
        except ValueError:
            raise ToolError(Msg.of("parse_message.bad_position", "'{line}': the position should be a number counting from 0", line=line)) from None
    else:
        index = order
    try:
        return protocol.Field(name=name, type=kind, index=index, start=start, end=end, order=byte_order, scale=scale)
    except protocol.ProtocolError as exc:
        raise ToolError(Msg.of("parse_message.bad_field", "'{line}': {error}", line=line, error=exc)) from None


TOOLS = [CompareNumberTool(), CompareRangeTool(), BoolLogicTool(), FormulaTool(), CounterTool(), VariableGetTool(), VariableSetTool(), ParseMessageTool(), SwitchTool(), StringMatchTool()]
