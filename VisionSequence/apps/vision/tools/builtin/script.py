"""Python 腳本工具：使用者在工具頁寫一段 Python（`def run(ctx)`），與引擎同行程受限執行。

執行邊界（設計決定：同行程、固定輸出埠、只有管理員能編輯；這**不是**安全沙箱，防的是誤用不是惡意）：
- 受限 builtins；import 只允許白名單（numpy／cv2／math／json／re／statistics／itertools／collections／functools／time）。
- AST 檢查：禁止 dunder 名稱與屬性（`__class__`、`__subclasses__`…）與 exec／eval／compile／open／globals／locals／
  getattr／setattr／delattr／vars／breakpoint／input。
- 看門狗：sys.settrace 只追蹤使用者程式碼的 frame，超過 `max_ms` 中止純 Python 迴圈（numpy／cv2 內部呼叫沒有事件，不受影響）。
- 輸入影像是唯讀 view（就地修改會直接報錯），輸出影像必須是新陣列；overlays 只是 metadata（平台規則）。
- 只有管理員儲存過（核准，apps/vision/scripts.py）的程式碼才會執行；編輯器試執行由管理員以 context `_script_admin` 放行。
- 同一段程式碼的模組命名空間會快取重用（`run` 以外的模組層級狀態會跨次執行保留，與外掛相同）。
"""

from __future__ import annotations

import ast
import builtins
import math
import sys
import threading
import time
import traceback
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np

from apps.vision import scripts as approval
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.roi import Crop, crop, region_overlay

SCRIPT_FILENAME = "<python_script>"

TEMPLATE = '''# 在這裡寫檢測邏輯；可直接用 np、cv2、math。
# ctx.image：輸入影像（唯讀）   ctx.inputs["a"]…["d"]：上游接進來的值   ctx.params["p1"]…["p3"]：現場參數
# ctx.roi()：區域參數（dict）   ctx.crop()：依區域裁切 → .image／.mask／.to_full(x, y)   ctx.gray()：灰階影像
# 回傳 dict：value（數值）、result（布林）、text、data（任意）、image（新影像）、status（ok／ng）、
#           branch（pass／fail）、overlays（標記清單）、message（顯示在節點上的說明）
def run(ctx):
    gray = ctx.gray()
    mean = float(gray.mean())
    ok = mean >= ctx.params["p1"]
    return {"value": mean, "result": ok, "status": "ok" if ok else "ng", "message": f"平均灰階 {mean:.1f}"}
'''

#: 內建範本的 hash：平台自帶、無害，不必核准就能執行（插入工具後立即可試執行）。
TEMPLATE_HASH = approval.code_hash(TEMPLATE)

ALLOWED_MODULES = frozenset({"numpy", "cv2", "math", "json", "re", "statistics", "itertools", "collections", "functools", "time"})
FORBIDDEN_CALLS = frozenset({"exec", "eval", "compile", "open", "globals", "locals", "getattr", "setattr", "delattr", "vars", "breakpoint", "input", "__import__", "memoryview"})
_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "bytes", "callable", "chr", "dict", "divmod", "enumerate", "filter", "float", "format", "frozenset",
    "hash", "hex", "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next", "oct", "ord", "pow", "range",
    "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError", "RuntimeError", "ZeroDivisionError", "ArithmeticError",
    "AttributeError", "StopIteration", "NotImplementedError", "AssertionError", "LookupError", "OverflowError",
)

_current = threading.local()  # 執行中的腳本要把 print 導到哪個節點的 log


class ScriptTimeout(Exception):
    pass


def _guarded_import(name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    root = str(name).split(".")[0]
    if level or root not in ALLOWED_MODULES:
        raise ImportError(f"腳本不允許匯入 '{name}'（可用：{', '.join(sorted(ALLOWED_MODULES))}）")
    return builtins.__import__(name, globals_, locals_, fromlist, 0)


def _print(*args: Any, **kwargs: Any) -> None:
    log = getattr(_current, "log", None)
    if log is not None:
        log(" ".join(str(a) for a in args))


def _safe_builtins() -> dict[str, Any]:
    safe = {k: getattr(builtins, k) for k in _SAFE_BUILTIN_NAMES}
    safe["__import__"] = _guarded_import
    safe["print"] = _print
    return safe


def check_ast(tree: ast.AST) -> None:
    """靜態檢查：dunder、危險內建、非白名單 import。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ToolError(f"腳本不允許使用 '{node.id}'")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ToolError(f"腳本不允許存取 '{node.attr}'")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            raise ToolError(f"腳本不允許呼叫 {node.func.id}()")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_MODULES:
                    raise ToolError(f"腳本不允許匯入 '{alias.name}'（可用：{', '.join(sorted(ALLOWED_MODULES))}）")
        if isinstance(node, ast.ImportFrom):
            if node.level or not node.module or node.module.split(".")[0] not in ALLOWED_MODULES:
                raise ToolError(f"腳本不允許匯入 '{node.module or '.'}'（可用：{', '.join(sorted(ALLOWED_MODULES))}）")


#: 編譯＋執行過的模組命名空間快取：hash → namespace（含 run）。最多 64 段。
_NAMESPACES: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_NS_LOCK = threading.Lock()


def _namespace(code: str) -> dict[str, Any]:
    h = approval.code_hash(code)
    with _NS_LOCK:
        ns = _NAMESPACES.get(h)
        if ns is not None:
            _NAMESPACES.move_to_end(h)
            return ns
    source = approval.normalize(code)
    try:
        tree = ast.parse(source, filename=SCRIPT_FILENAME, mode="exec")
    except SyntaxError as exc:
        raise ToolError(f"腳本語法錯誤（第 {exc.lineno or '?'} 行）：{exc.msg}") from None
    check_ast(tree)
    compiled = compile(tree, SCRIPT_FILENAME, "exec")
    ns: dict[str, Any] = {"__builtins__": _safe_builtins(), "__name__": "python_script", "np": np, "cv2": cv2, "math": math}
    try:
        exec(compiled, ns)  # noqa: S102 - 受限命名空間，只定義 run 與模組層級輔助
    except Exception as exc:  # noqa: BLE001
        raise ToolError(_describe(exc, "載入腳本時")) from None
    if not callable(ns.get("run")):
        raise ToolError("腳本必須定義 def run(ctx)")
    with _NS_LOCK:
        _NAMESPACES[h] = ns
        while len(_NAMESPACES) > 64:
            _NAMESPACES.popitem(last=False)
    return ns


def _describe(exc: BaseException, prefix: str = "") -> str:
    """把例外翻成「第 N 行：Error: 訊息」，行號取使用者程式碼的最後一個 frame。"""
    lineno = None
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == SCRIPT_FILENAME:
            lineno = frame.lineno
    where = f"第 {lineno} 行" if lineno else prefix or "腳本"
    return f"{where}：{exc.__class__.__name__}: {str(exc)[:200]}"


def _watchdog(deadline: float):
    """只追蹤使用者程式碼的 frame（numpy／cv2 內部沒有 Python 事件），每 64 個事件看一次時間。"""
    counter = 0

    def local(frame: Any, event: str, arg: Any):
        nonlocal counter
        counter += 1
        if (counter & 63) == 0 and time.perf_counter() > deadline:
            raise ScriptTimeout()
        return local

    def tracer(frame: Any, event: str, arg: Any):
        return local if frame.f_code.co_filename == SCRIPT_FILENAME else None

    return tracer


class ScriptContext:
    """腳本看到的 ctx：影像（唯讀）、上游輸入、現場參數、ROI 與裁切輔助、log。"""

    __slots__ = ("image", "inputs", "params", "_region", "_log")

    def __init__(self, image: np.ndarray | None, inputs: dict[str, Any], params: dict[str, Any], region: dict[str, Any] | None, log: Any) -> None:
        if image is not None:
            view = image.view()
            view.setflags(write=False)
            image = view
        self.image = image
        self.inputs = inputs
        self.params = params
        self._region = region
        self._log = log

    def roi(self) -> dict[str, Any] | None:
        return dict(self._region) if self._region else None

    def crop(self, region: dict[str, Any] | None = None, image: np.ndarray | None = None, upright: bool = False) -> Crop:
        img = self.image if image is None else image
        if img is None:
            raise ValueError("沒有影像可裁切")
        return crop(img, region if region is not None else self._region, upright=upright)

    def gray(self, image: np.ndarray | None = None) -> np.ndarray:
        img = self.image if image is None else image
        if img is None:
            raise ValueError("沒有輸入影像")
        return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def log(self, *args: Any) -> None:
        self._log(" ".join(str(a) for a in args))


def _normalize_result(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, np.ndarray):
        return {"image": value}
    if isinstance(value, bool):
        return {"result": value}
    if isinstance(value, (int, float)):
        return {"value": value}
    if isinstance(value, str):
        return {"text": value}
    raise ToolError(f"run() 回傳了不支援的型別 {type(value).__name__}：請回傳 dict（value／result／text／data／image…）")


class PythonScriptTool(Tool):
    key = "python_script"
    label = "Python script"
    description = "Write your own inspection in Python (def run(ctx)): read the image, upstream values and on-site parameters, return a number, boolean, text, data, a new image and marks, and decide the pass or fail branch. Only administrators may edit scripts, and they run restricted (allow-listed imports, aborted on timeout)."
    category = "logic"
    icon = "Code"
    params = [
        Param("code", "Code", kind="code", required=True, default=TEMPLATE, accept="python",
              help_text="Define def run(ctx). numpy, OpenCV, math and the allow-listed modules are available. Return a dict, or a single number, boolean, string or image."),
        Param("p1", "On-site parameter 1", kind="number", default=0, teach=True, group="On-site parameters", help_text="The script reads it as ctx.params['p1']; a technician can tune it on the parameter card without touching code."),
        Param("p2", "On-site parameter 2", kind="number", default=0, teach=True, group="On-site parameters"),
        Param("p3", "On-site parameter 3", kind="number", default=0, teach=True, group="On-site parameters"),
        Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon", "line", "point"], help_text="The script reads it through ctx.roi() and ctx.crop(); blank means the whole image."),
        Param("max_ms", "Timeout (ms)", kind="number", default=5000, minimum=100, maximum=60000, unit="ms", group="Advanced", help_text="Aborts a pure-Python loop that runs longer than this; time inside numpy and OpenCV calls does not count."),
    ]
    inputs = [
        Port("image", "Image", "image", required=False), Port("roi", "Region (dynamic)", "region", required=False),
        Port("a", "a", "any", required=False), Port("b", "b", "any", required=False), Port("c", "c", "any", required=False), Port("d", "d", "any", required=False),
    ]
    outputs = [
        flow_out("pass", "Pass", "ok"), flow_out("fail", "Fail", "critical"),
        Port("image", "Image", "image"), Port("value", "Value", "number"), Port("result", "Boolean", "bool"),
        Port("text", "Text", "string"), Port("data", "Data", "any"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        code = str(ctx.param("code", TEMPLATE) or "")
        if not code.strip():
            raise ToolError("腳本是空的：請定義 def run(ctx)")
        # 內建範本視為已核准（插入工具就能試執行）；其餘先看管理員試執行旗標（不碰 DB），再查核准清單（記憶體集合）
        if approval.code_hash(code) != TEMPLATE_HASH and not ctx.context.get(approval.ADMIN_CONTEXT_KEY) and not approval.is_approved(code):
            raise ToolError("此腳本尚未由管理員核准：請管理員在編輯器儲存此流程後再執行")
        ns = _namespace(code)
        image = ctx.image()
        region = ctx.roi()
        sctx = ScriptContext(
            image, {k: ctx.inputs.get(k) for k in ("a", "b", "c", "d")},
            {k: ctx.number(k, 0) for k in ("p1", "p2", "p3")}, region, ctx.log,
        )
        deadline = time.perf_counter() + max(0.1, ctx.number("max_ms", 5000) / 1000.0)
        _current.log = ctx.log
        sys.settrace(_watchdog(deadline))
        try:
            raw = ns["run"](sctx)
        except ScriptTimeout:
            raise ToolError(f"腳本執行超過 {ctx.number('max_ms', 5000):g} ms 已中止（純 Python 迴圈太久？）") from None
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - 使用者程式碼的任何錯誤都翻成節點錯誤
            raise ToolError(_describe(exc)) from None
        finally:
            sys.settrace(None)
            _current.log = None

        out = _normalize_result(raw)
        nan = float("nan")
        outputs: dict[str, Any] = {"value": nan, "result": False, "text": "", "data": None}
        if "value" in out and out["value"] is not None:
            try:
                outputs["value"] = float(out["value"])
            except (TypeError, ValueError):
                raise ToolError(f"value 必須是數值，收到 {type(out['value']).__name__}") from None
        if "result" in out:
            outputs["result"] = bool(out["result"])
        if "text" in out and out["text"] is not None:
            outputs["text"] = str(out["text"])
        if "data" in out:
            outputs["data"] = out["data"]
        if out.get("image") is not None:
            img = out["image"]
            if not isinstance(img, np.ndarray) or img.ndim not in (2, 3):
                raise ToolError("image 必須是 2 維（灰階）或 3 維（BGR）的 numpy 陣列")
            if img.dtype != np.uint8:
                img = np.clip(img, 0, 255).astype(np.uint8)
            if image is not None and np.shares_memory(img, image):
                img = img.copy()  # 輸入影像的 view：複製一份再往下傳（輸入陣列不得被下游改到）
            outputs["image"] = np.ascontiguousarray(img)
        status = str(out.get("status") or ("ok" if outputs["result"] or "result" not in out else "ng"))
        if status not in ("ok", "ng"):
            raise ToolError(f"status 只能是 ok 或 ng，收到 {status!r}")
        branch = str(out.get("branch") or ("pass" if status == "ok" else "fail"))
        if branch not in ("pass", "fail"):
            raise ToolError(f"branch 只能是 pass 或 fail，收到 {branch!r}")
        overlays: list[dict[str, Any]] = [region_overlay(region, label="script")] if region else []
        extra = out.get("overlays")
        if extra is not None:
            if not isinstance(extra, (list, tuple)) or not all(isinstance(o, dict) and o.get("kind") for o in extra):
                raise ToolError("overlays 必須是 [{kind: rect|circle|line|point|points|polygon|polyline|text|contours, …}, …]")
            overlays += [dict(o) for o in extra]
        message = str(out.get("message") or "")[:200]
        if not message:
            message = f"value={outputs['value']:.4g}" if math.isfinite(outputs["value"]) else ("result=" + str(outputs["result"]))
        return Result(outputs=outputs, overlays=overlays, branch=branch, status=status, message=message)


TOOLS = [PythonScriptTool()]
