"""邏輯工具：數值比較分支、公式、布林組合。"""

from __future__ import annotations

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
    label = "數值判斷"
    description = "把輸入數值與門檻比較，走 true / false 分支；下游連到分支把手的節點只在該分支被選中時執行。"
    category = "logic"
    icon = "GitBranch"
    params = [
        Param("operator", "比較", kind="select", default="gt", required=True,
              options=[{"value": k, "label": v} for k, v in _OP_LABEL.items()]),
        Param("threshold", "門檻", kind="number", required=True, default=0, teach=True),
        Param("tolerance", "容差（= / ≠ 用）", kind="number", default=0, minimum=0),
    ]
    inputs = [Port("value", "數值", "number")]
    outputs = [flow_out("true", "True", "ok"), flow_out("false", "False", "critical"), Port("result", "結果", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        value = ctx.inputs.get("value")
        if value is None:
            raise ToolError("沒有輸入數值")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ToolError(f"輸入不是數值：{value!r}") from None
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
    label = "範圍判斷"
    description = "數值是否落在 [下限, 上限]；常用於量測值公差判定。"
    category = "logic"
    icon = "Ruler"
    params = [
        Param("low", "下限", kind="number", required=True, default=0, teach=True),
        Param("high", "上限", kind="number", required=True, default=100, teach=True),
    ]
    inputs = [Port("value", "數值", "number")]
    outputs = [flow_out("inside", "在範圍內", "ok"), flow_out("outside", "超出範圍", "critical"), Port("result", "結果", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        value = ctx.inputs.get("value")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ToolError(f"輸入不是數值：{value!r}") from None
        low, high = ctx.number("low"), ctx.number("high")
        ok = low <= v <= high
        return Result(outputs={"result": ok}, branch="inside" if ok else "outside",
                      message=f"{v:g} ∈ [{low:g}, {high:g}] → {ok}")


class BoolLogicTool(Tool):
    key = "bool_logic"
    label = "布林組合"
    description = "把多個布林輸入以 AND / OR / NOT 組合，走 true / false 分支。"
    category = "logic"
    icon = "Binary"
    params = [
        Param("mode", "運算", kind="select", default="and", options=[
            {"value": "and", "label": "AND（全部為真）"},
            {"value": "or", "label": "OR（任一為真）"},
            {"value": "nand", "label": "NOT AND"},
            {"value": "nor", "label": "NOT OR"},
        ]),
    ]
    inputs = [Port("values", "布林值", "bool", multiple=True, required=True)]
    outputs = [flow_out("true", "True", "ok"), flow_out("false", "False", "critical"), Port("result", "結果", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        values = [bool(v) for v in (ctx.inputs.get("values") or []) if v is not None]
        if not values:
            raise ToolError("沒有任何布林輸入")
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
            raise ToolError(f"公式裡未知的名稱 '{node.id}'")
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
        raise ToolError(f"公式不支援的語法：{type(node).__name__}")

    return ev(tree)


class FormulaTool(Tool):
    key = "formula"
    label = "公式"
    description = "以 a、b、c、d 代表輸入，寫一段算式（例如 abs(a-b)/c*100）。支援 +-*/、比較、and/or、abs/min/max/sqrt/…。"
    category = "logic"
    icon = "Sigma"
    params = [
        Param("expression", "公式", kind="expression", required=True, default="a", help_text="變數 a b c d 對應四個輸入；結果可為數值或布林。"),
    ]
    inputs = [
        Port("a", "a", "any", required=False), Port("b", "b", "any", required=False),
        Port("c", "c", "any", required=False), Port("d", "d", "any", required=False),
    ]
    outputs = [Port("value", "數值", "number"), Port("result", "布林", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        expr = str(ctx.param("expression", "")).strip()
        if not expr:
            raise ToolError("公式為空")
        names = {k: ctx.inputs.get(k) for k in ("a", "b", "c", "d")}
        try:
            value = safe_eval(expr, names)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"公式錯誤：{exc}") from None
        number = float(value) if isinstance(value, (int, float, bool)) else float("nan")
        return Result(outputs={"value": number, "result": bool(value)}, message=f"{expr} = {value!r}"[:200])


class CounterTool(Tool):
    key = "count_list"
    label = "計數"
    description = "輸出 list／points／matches 的元素數量。"
    category = "logic"
    icon = "Hash"
    inputs = [Port("items", "清單", "list")]
    outputs = [Port("count", "數量", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        items = ctx.inputs.get("items")
        try:
            n = len(items)  # type: ignore[arg-type]
        except TypeError:
            n = 0 if items is None else 1
        return Result(outputs={"count": n}, message=f"{n} 項")


TOOLS = [CompareNumberTool(), CompareRangeTool(), BoolLogicTool(), FormulaTool(), CounterTool()]
