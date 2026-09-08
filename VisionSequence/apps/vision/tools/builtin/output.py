"""輸出工具：判定、具名輸出、存圖。"""

from __future__ import annotations

import codecs
import os
import time
from typing import Any

import cv2
import numpy as np
from django.conf import settings

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError


class JudgeTool(Tool):
    key = "judge"
    label = "OK / NG verdict"
    description = "Decides the verdict of the whole run. Wired to a branch handle it fires when that branch is taken; otherwise a boolean input decides."
    category = "output"
    icon = "CheckCircle2"
    params = [
        Param("verdict", "Verdict", kind="select", default="by_input", options=[
            {"value": "by_input", "label": "From the boolean input (true is OK, false is NG)"},
            {"value": "ok", "label": "Always OK"},
            {"value": "ng", "label": "Always NG"},
        ]),
        Param("label", "Result label", kind="text", default="", help_text="Written into run.outputs.judge_label so an automation system can tell which check fired."),
    ]
    inputs = [Port("value", "Boolean", "bool", required=False)]
    outputs = [Port("verdict", "Verdict", "string")]

    def execute(self, ctx: ToolContext) -> Result:
        mode = ctx.param("verdict", "by_input")
        if mode == "by_input":
            value = ctx.inputs.get("value")
            if value is None:
                raise ToolError("No boolean input; connect one or use a fixed verdict")
            verdict = "ok" if bool(value) else "ng"
        else:
            verdict = mode
        # 多個 judge：任一 NG 即 NG。
        current = ctx.context.get("_judge")
        merged = "ng" if "ng" in (current, verdict) else verdict
        outputs = dict(ctx.context.get("_outputs") or {})
        outputs["judge"] = merged.upper()
        label = ctx.param("label", "")
        if label:
            outputs["judge_label"] = label
        return Result(
            outputs={"verdict": verdict.upper()},
            status="ng" if verdict == "ng" else "ok",
            message=f"{verdict.upper()}" + (f" ({label})" if label else ""),
            context={"_judge": merged, "_outputs": outputs},
        )


class OutputValueTool(Tool):
    key = "output"
    label = "Named output"
    description = "Puts a value into the run outputs under a name of your choosing, for the HTTP and TCP replies to carry to the automation system."
    category = "output"
    icon = "Upload"
    params = [
        Param("name", "Name", kind="output_key", required=True, default="value"),
        Param("decimals", "Decimals", kind="number", default=3, minimum=0, maximum=10),
    ]
    inputs = [Port("value", "Value", "any")]
    outputs: list[Port] = []

    def execute(self, ctx: ToolContext) -> Result:
        name = str(ctx.param("name", "value"))
        value = ctx.inputs.get("value")
        if isinstance(value, np.ndarray):
            value = value.tolist() if value.size <= 200 else {"array": True, "shape": list(value.shape)}
        if isinstance(value, float):
            value = round(value, ctx.integer("decimals", 3))
        if isinstance(value, (np.floating,)):
            value = round(float(value), ctx.integer("decimals", 3))
        if isinstance(value, (np.integer,)):
            value = int(value)
        if isinstance(value, (np.bool_,)):
            value = bool(value)
        outputs = dict(ctx.context.get("_outputs") or {})
        outputs[name] = value
        return Result(message=f"{name} = {value!r}"[:200], context={"_outputs": outputs})


class SaveImageTool(Tool):
    key = "save_image"
    accepts = ("u8", "u16", "f32")  # 16-bit PNG/TIFF 原樣存檔
    label = "Save"
    description = "Saves the image into a folder in the background, optionally in an OK or NG sub-folder. The filename may use values such as {station}, {date}, {run_id} and named outputs."
    category = "output"
    icon = "Save"
    params = [
        Param("folder", "Folder", kind="text", required=True, help_text="Blank saves to DATA_DIR/saved/<flow_id>."),
        Param("format", "Format", kind="select", default="png", options=[{"value": "png", "label": "PNG"}, {"value": "jpg", "label": "JPEG"}, {"value": "bmp", "label": "BMP"}]),
        Param("condition", "Save when", kind="select", default="all", options=[
            {"value": "all", "label": "All runs"}, {"value": "ok", "label": "OK only"}, {"value": "ng", "label": "NG only"},
        ]),
        Param("split_by_judge", "Sub-folder per verdict", kind="boolean", default=True),
        Param("only_ng", "Rejects only", kind="boolean", default=False),
        Param("prefix", "Filename prefix", kind="text", default=""),
        Param("filename", "Filename", kind="text", default="{date}-{time}-{run_id:.8}", teach=True,
              help_text="Uses the same names as Format a reply, for example {station}_{lot}_{run_id:.8}."),
        Param("daily_folder", "Daily folder", kind="boolean", default=False),
        Param("jpeg_quality", "JPEG quality", kind="number", default=85, minimum=30, maximum=100, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("path", "Path", "string")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        judge = str(ctx.context.get("_judge") or "ok")
        condition = str(ctx.param("condition", "all") or "all").lower()
        if ctx.flag("only_ng") or condition == "ng":
            condition = "ng"
        if condition in ("ok", "ng") and judge != condition:
            return Result(outputs={"path": ""}, message="OK, not saved")
        folder = str(ctx.param("folder") or os.path.join(str(settings.DATA_DIR), "saved", str(ctx.flow_id)))
        if ctx.flag("split_by_judge", True):
            folder = os.path.join(folder, judge.upper())
        try:
            name = fill_template(str(ctx.param("filename", "{date}-{time}-{run_id:.8}") or "{date}-{time}-{run_id:.8}"), ctx, missing="blank")
        except (ValueError, TypeError, IndexError) as exc:
            raise ToolError(f"The filename could not be filled in: {exc}") from None
        prefix = str(ctx.param("prefix", "") or "")
        from apps.vision import fileout

        path = fileout.image_path(
            os.path.abspath(folder),
            prefix + name,
            str(ctx.param("format", "png") or "png"),
            daily_folder=ctx.flag("daily_folder", False),
            when=ctx.moment,
        )
        if ctx.sandboxed():
            return Result(outputs={"path": str(path)}, message=f"Would save {path}")
        queued = fileout.submit(fileout.ImageJob(path=path, image=image, fmt=str(ctx.param("format", "png") or "png").lower(), quality=ctx.integer("jpeg_quality", 85)))
        return Result(outputs={"path": str(path)}, message=(f"Queued {path}" if queued else "Dropped: file output queue is full"), detail={"queued": queued})


class WriteLogTool(Tool):
    key = "write_log"
    label = "Write log"
    description = "Writes named outputs as one TXT line or one CSV row in the background under DATA_DIR/file_outputs."
    category = "output"
    icon = "FileText"
    params = [
        Param("path", "Path", kind="text", default="", required=False, teach=True,
              help_text="Relative folder under DATA_DIR/file_outputs. Absolute paths and '..' are rejected."),
        Param("format", "Format", kind="select", default="csv", options=[{"value": "csv", "label": "CSV"}, {"value": "txt", "label": "TXT"}]),
        Param("fields", "Fields", kind="multiline", default="judge\nrun_id", required=True, teach=True,
              help_text="One field per line. A plain name reads that value; a {name:.2f} layout uses the same syntax as Format a reply."),
        Param("header", "Header row", kind="boolean", default=True),
        Param("filename", "Filename", kind="text", default="{station}_{date}", teach=True,
              help_text="Uses the same names as Format a reply, for example {station}_{lot}_{date}."),
        Param("daily_folder", "Daily folder", kind="boolean", default=True),
        Param("rotate_mb", "Rotate size", kind="number", default=0, minimum=0, unit="MB", group="Rotation"),
        Param("rotate_rows", "Rotate rows", kind="number", default=0, minimum=0, group="Rotation"),
        Param("encoding", "Encoding", kind="text", default="utf-8", group="Advanced"),
    ]
    inputs = [Port("a", "a", "any", required=False), Port("b", "b", "any", required=False),
              Port("c", "c", "any", required=False), Port("d", "d", "any", required=False)]
    outputs = [Port("path", "Path", "string"), Port("queued", "Queued", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        fmt = str(ctx.param("format", "csv") or "csv").lower()
        if fmt not in ("csv", "txt"):
            raise ToolError("Format must be csv or txt")
        fields = _field_lines(str(ctx.param("fields", "") or ""))
        if not fields:
            raise ToolError("Write at least one field")
        encoding = str(ctx.param("encoding", "utf-8") or "utf-8")
        try:
            codecs.lookup(encoding)
        except LookupError:
            raise ToolError(f"Unknown encoding '{encoding}'") from None
        try:
            values = format_values(ctx)
            row = [_field_value(field, values) for field in fields]
            filename = fill_template(str(ctx.param("filename", "{station}_{date}") or "{station}_{date}"), ctx, missing="blank")
        except (ValueError, TypeError, IndexError) as exc:
            raise ToolError(f"The log row could not be filled in: {exc}") from None
        from apps.vision import fileout

        try:
            folder = fileout.resolve_dir(str(ctx.param("path", "") or ""))
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        path = fileout.text_path(folder, filename, fmt, daily_folder=ctx.flag("daily_folder", True), when=ctx.moment)
        if ctx.sandboxed():
            return Result(outputs={"path": str(path), "queued": False}, message=f"Would write {path}")
        job = fileout.TextJob(
            path=path,
            fmt=fmt,
            row=[str(v) for v in row],
            header=[_field_header(f) for f in fields],
            write_header=ctx.flag("header", True),
            rotate_bytes=max(0, int(ctx.number("rotate_mb", 0) * 1024 * 1024)),
            rotate_rows=max(0, ctx.integer("rotate_rows", 0)),
            encoding=encoding,
        )
        queued = fileout.submit(job)
        return Result(outputs={"path": str(path), "queued": queued}, message=(f"Queued {path}" if queued else "Dropped: file output queue is full"), detail={"queued": queued})


class DrawResultTool(Tool):
    key = "draw_result"
    label = "Result image"
    description = "Draws the marks from upstream tools into the image, producing a result frame to save or show (green for OK, red for NG)."
    category = "output"
    icon = "Image"
    params = [
        Param("thickness", "Line width", kind="number", default=2, minimum=1, maximum=10),
        Param("banner", "Show verdict banner", kind="boolean", default=True),
    ]
    inputs = [Port("image", "Image", "image"), Port("overlays", "Marks", "list", required=False, multiple=True)]
    outputs = [Port("image", "Image", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        canvas = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image.copy()
        thickness = ctx.integer("thickness", 2)
        for group in ctx.inputs.get("overlays") or []:
            if isinstance(group, dict):  # 單一 overlay 直接接進來
                group = [group]
            if not isinstance(group, (list, tuple)):  # 接錯埠（影像／數值）就略過，不讓結果影像整個炸掉
                continue
            for ov in group:
                if isinstance(ov, dict):
                    draw_overlay(canvas, ov, thickness)
        if ctx.flag("banner", True):
            judge = str(ctx.context.get("_judge") or "").upper()
            if judge:
                color = (0, 200, 0) if judge == "OK" else (0, 0, 230)
                cv2.rectangle(canvas, (0, 0), (220, 60), color, -1)
                cv2.putText(canvas, judge, (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
        return Result(outputs={"image": canvas})


def format_values(ctx: ToolContext) -> dict[str, Any]:
    """依照 format_text 的順序彙整可填入樣板的值。"""
    values: dict[str, Any] = {}
    for key, value in (ctx.context.get("_outputs") or {}).items():
        values[str(key)] = value
    judge = ctx.context.get("_judge")
    if judge is not None and "judge" not in values:
        values["judge"] = str(judge).upper()
    for key, value in ctx.context.items():
        if not str(key).startswith("_"):
            values[str(key)] = value
    for key in ("a", "b", "c", "d"):
        value = ctx.inputs.get(key)
        if value is not None:
            values[key] = _plain(value)
    values.setdefault("run_id", ctx.run_id)
    values.setdefault("station", str(settings.VISION.get("STATION_ID", "")))
    when = time.localtime(ctx.moment or time.time())
    values.setdefault("date", time.strftime("%Y%m%d", when))
    values.setdefault("time", time.strftime("%H%M%S", when))
    return values


def fill_template(template: str, ctx: ToolContext, *, missing: str = "blank", seen: list[str] | None = None) -> str:
    return _unescape(template).format_map(_Fill(format_values(ctx), missing, seen if seen is not None else []))


def _field_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _field_value(field: str, values: dict[str, Any]) -> Any:
    field = field.strip()
    if "{" in field or "}" in field:
        return _unescape(field).format_map(_Fill(values, "blank", []))
    return _Fill(values, "blank", [])[field]


def _field_header(field: str) -> str:
    field = field.strip()
    if field.startswith("{") and field.endswith("}") and field.count("{") == 1 and field.count("}") == 1:
        return field[1:-1].split(":", 1)[0] or field
    return field


def _bgr(color: str | None) -> tuple[int, int, int]:
    if not color or not color.startswith("#") or len(color) != 7:
        return (0, 255, 0)
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return (b, g, r)


def draw_overlay(canvas: np.ndarray, ov: dict[str, Any], thickness: int = 2) -> None:
    kind = ov.get("kind")
    color = _bgr(ov.get("color"))
    t = int(ov.get("width") or thickness)
    if kind == "rect":
        if ov.get("angle"):
            cx, cy = ov["x"] + ov["w"] / 2, ov["y"] + ov["h"] / 2
            box = cv2.boxPoints(((cx, cy), (ov["w"], ov["h"]), float(ov["angle"])))
            cv2.polylines(canvas, [np.round(box).astype(np.int32)], True, color, t)
        else:
            cv2.rectangle(canvas, (int(ov["x"]), int(ov["y"])), (int(ov["x"] + ov["w"]), int(ov["y"] + ov["h"])), color, t)
    elif kind == "circle":
        cv2.circle(canvas, (int(ov["cx"]), int(ov["cy"])), int(ov["r"]), color, t)
    elif kind == "annulus":
        cv2.circle(canvas, (int(ov["cx"]), int(ov["cy"])), int(ov["r_outer"]), color, t)
        cv2.circle(canvas, (int(ov["cx"]), int(ov["cy"])), int(ov["r_inner"]), color, t)
    elif kind in ("polygon", "polyline"):
        pts = np.round(np.asarray(ov["points"])).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(canvas, [pts], kind == "polygon", color, t)
    elif kind == "line":
        cv2.line(canvas, (int(ov["x1"]), int(ov["y1"])), (int(ov["x2"]), int(ov["y2"])), color, t)
    elif kind == "point":
        cv2.drawMarker(canvas, (int(ov["x"]), int(ov["y"])), color, cv2.MARKER_CROSS, 12, t)
    elif kind == "points":
        for x, y in ov.get("points", []):
            cv2.circle(canvas, (int(x), int(y)), 3, color, -1)
    elif kind == "contours":
        for c in ov.get("contours", []):
            pts = np.round(np.asarray(c)).astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(canvas, [pts], True, color, t)
    elif kind == "text":
        cv2.putText(canvas, str(ov.get("text", "")), (int(ov["x"]), int(ov["y"])), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, max(1, t - 1))
    label = ov.get("label")
    if label and kind in ("rect", "circle"):
        x = int(ov.get("x", ov.get("cx", 0)))
        y = int(ov.get("y", ov.get("cy", 0))) - 6
        cv2.putText(canvas, str(label), (x, max(12, y)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)


class FormatTextTool(Tool):
    key = "format_text"
    label = "Format a reply"
    description = (
        "Builds one line of text out of the results, for equipment that cannot read JSON. Write the layout with the value "
        "names in braces, for example OK,{width:.2f},{height:.2f} — the reply then carries it, and Write Modbus or a "
        "TCP connection can send it out."
    )
    category = "output"
    icon = "Type"
    params = [
        Param(
            "template", "Layout", kind="multiline", required=True, default="{judge},{value}",
            teach=True,
            help_text=(
                "Names in braces are filled in: judge (OK or NG), any named output made earlier in the flow, anything the "
                "trigger sent with the request (a lot or serial number), and this step's own inputs a, b, c and d. "
                "Round a number with {name:.2f}, pad with {name:05.1f}. Type \\r\\n for a carriage return and line feed, \\t for a tab."
            ),
        ),
        Param("name", "Output name", kind="output_key", default="text", help_text="The reply carries the line under this name. Ask for it with fmt on the TCP command or format in the HTTP request."),
        Param("ending", "Line ending", kind="select", default="none", options=[
            {"value": "none", "label": "None"}, {"value": "lf", "label": "Line feed (\\n)"},
            {"value": "crlf", "label": "Carriage return and line feed (\\r\\n)"}, {"value": "cr", "label": "Carriage return (\\r)"},
        ]),
        Param("missing", "When a name has no value", kind="select", default="blank", options=[
            {"value": "blank", "label": "Leave it empty"},
            {"value": "keep", "label": "Leave the name in place"},
            {"value": "fail", "label": "Fail the step"},
        ], group="Advanced"),
    ]
    inputs = [Port("a", "a", "any", required=False), Port("b", "b", "any", required=False),
              Port("c", "c", "any", required=False), Port("d", "d", "any", required=False)]
    outputs = [Port("text", "Text", "string")]

    def execute(self, ctx: ToolContext) -> Result:
        template = str(ctx.param("template", "") or "")
        if not template.strip():
            raise ToolError("Write the layout of the line, for example {judge},{value}")
        template = _unescape(template)
        missing = str(ctx.param("missing", "blank"))
        seen: list[str] = []
        try:
            text = fill_template(template, ctx, missing=missing, seen=seen)
        except (ValueError, TypeError, IndexError) as exc:
            raise ToolError(f"The layout could not be filled in: {exc}") from None
        if missing == "fail" and seen:
            raise ToolError(f"No value for {', '.join(sorted(set(seen))[:5])}; run the step that produces it first")
        text += {"lf": "\n", "crlf": "\r\n", "cr": "\r"}.get(str(ctx.param("ending", "none")), "")
        name = str(ctx.param("name", "text") or "text")
        outputs = dict(ctx.context.get("_outputs") or {})
        outputs[name] = text
        return Result(outputs={"text": text}, context={"_outputs": outputs},
                      message=repr(text)[1:-1][:200] if text else "(empty)")

    def _values(self, ctx: ToolContext) -> dict[str, Any]:
        """能填進樣板的名字：具名輸出 → 觸發帶進來的引數 → 這一步的輸入 a~d。後者優先。"""
        return format_values(ctx)


def _unescape(text: str) -> str:
    """使用者在單行欄位裡打的 \\r\\n 要變成真的控制字元（設備的協定就是這樣寫的）。"""
    return text.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")


def _plain(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist() if value.size <= 50 else f"array{tuple(value.shape)}"
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


class _Fill(dict):
    """format_map 的填值：找不到的名字依設定留空／保留原樣／記下來讓工具報錯。"""

    def __init__(self, values: dict[str, Any], missing: str, seen: list[str]) -> None:
        super().__init__(values)
        self._missing = missing
        self._seen = seen

    def __missing__(self, key: str) -> Any:
        self._seen.append(key)
        return "{" + key + "}" if self._missing == "keep" else ""


TOOLS = [JudgeTool(), OutputValueTool(), SaveImageTool(), WriteLogTool(), DrawResultTool(), FormatTextTool()]
