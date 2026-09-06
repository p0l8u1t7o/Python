"""邏輯工具：數值比較分支、公式、布林組合。"""

from __future__ import annotations

import numpy as np

import ast
import math
import operator
from typing import Any

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out

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
    ]
    inputs = [Port("value", "Value", "number")]
    outputs = [flow_out("true", "True", "ok"), flow_out("false", "False", "critical"), Port("result", "Result", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        value = ctx.inputs.get("value")
        if value is None:
            raise ToolError("No value on the input")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ToolError(f"The input is not a number: {value!r}") from None
        op = ctx.param("operator", "gt")
        threshold = ctx.number("threshold")
        tol = ctx.number("tolerance")
        if op == "eq":
            ok = abs(v - threshold) <= tol
        elif op == "ne":
            ok = abs(v - threshold) > tol
        else:
            ok = _OPS[op](v, threshold)
        return Result(
            outputs={"result": ok},
            branch="true" if ok else "false",
            message=f"{v:g} {_OP_LABEL[op]} {threshold:g} → {ok}",
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
    ]
    inputs = [Port("value", "Value", "number")]
    outputs = [flow_out("inside", "In range", "ok"), flow_out("outside", "Out of range", "critical"), Port("result", "Result", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        value = ctx.inputs.get("value")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ToolError(f"The input is not a number: {value!r}") from None
        low, high = ctx.number("low"), ctx.number("high")
        ok = low <= v <= high
        return Result(outputs={"result": ok}, branch="inside" if ok else "outside",
                      message=f"{v:g} ∈ [{low:g}, {high:g}] → {ok}")


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
            raise ToolError("No boolean input is connected")
        mode = ctx.param("mode", "and")
        base = all(values) if mode in ("and", "nand") else any(values)
        ok = (not base) if mode in ("nand", "nor") else base
        return Result(outputs={"result": ok}, branch="true" if ok else "false", message=f"{mode}({values}) → {ok}")


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
            raise ToolError(f"Unknown name '{node.id}' in the expression")
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
        raise ToolError(f"Unsupported syntax in the expression: {type(node).__name__}")

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
            raise ToolError("The expression is empty")
        names = {k: ctx.inputs.get(k) for k in ("a", "b", "c", "d")}
        try:
            value = safe_eval(expr, names)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Expression error: {exc}") from None
        number = float(value) if isinstance(value, (int, float, bool)) else float("nan")
        return Result(outputs={"value": number, "result": bool(value)}, message=f"{expr} = {value!r}"[:200])


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
        return Result(outputs={"count": n}, message=f"{n} items")



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
                      message=f"{name} = {text[:80]}" + ("" if found else " (default)"))


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
            raise ToolError("Wire a value in")
        try:
            if mode in ("add", "max", "min"):
                current = ctx.variable(name, None, scope)
                try:
                    incoming = float(value)
                except (TypeError, ValueError):
                    raise ToolError(f"'{mode}' needs a number, got {value!r}") from None
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
        note = " (trial: not kept)" if ctx.sandboxed() else ""
        return Result(outputs={"value": stored, "previous": previous}, message=f"{name} = {str(shown)[:80]}{note}")


_MISSING = object()

TOOLS = [CompareNumberTool(), CompareRangeTool(), BoolLogicTool(), FormulaTool(), CounterTool(), VariableGetTool(), VariableSetTool()]
