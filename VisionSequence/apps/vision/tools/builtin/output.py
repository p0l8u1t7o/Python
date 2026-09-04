"""輸出工具：判定、具名輸出、存圖。"""

from __future__ import annotations

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
            {"value": "by_input", "label": "依布林輸入（真=OK，假=NG）"},
            {"value": "ok", "label": "固定 OK"},
            {"value": "ng", "label": "固定 NG"},
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
                raise ToolError("沒有布林輸入；請連線或改用固定判定")
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
            message=f"判定 {verdict.upper()}" + (f"（{label}）" if label else ""),
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
    description = "Saves the image into a folder, optionally in an OK or NG sub-folder. The filename carries the timestamp and the run id."
    category = "output"
    icon = "Save"
    params = [
        Param("folder", "Folder", kind="text", required=True, help_text="Blank saves to DATA_DIR/saved/<flow_id>."),
        Param("format", "Format", kind="select", default="png", options=[{"value": "png", "label": "PNG"}, {"value": "jpg", "label": "JPEG"}, {"value": "bmp", "label": "BMP"}]),
        Param("split_by_judge", "Sub-folder per verdict", kind="boolean", default=True),
        Param("only_ng", "Rejects only", kind="boolean", default=False),
        Param("prefix", "Filename prefix", kind="text", default=""),
    ]
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("path", "Path", "string")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        judge = str(ctx.context.get("_judge") or "ok")
        if ctx.flag("only_ng") and judge != "ng":
            return Result(outputs={"path": ""}, message="判定 OK，未存檔")
        folder = str(ctx.param("folder") or os.path.join(str(settings.DATA_DIR), "saved", str(ctx.flow_id)))
        if ctx.flag("split_by_judge", True):
            folder = os.path.join(folder, judge.upper())
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"{ctx.param('prefix', '')}{stamp}-{ctx.run_id[:8]}.{ctx.param('format', 'png')}"
        path = os.path.join(folder, name)
        ok, buf = cv2.imencode("." + str(ctx.param("format", "png")), image)
        if not ok:
            raise ToolError("影像編碼失敗")
        buf.tofile(path)
        return Result(outputs={"path": path}, message=f"已存 {path}")


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


TOOLS = [JudgeTool(), OutputValueTool(), SaveImageTool(), DrawResultTool()]
