"""檢測任務輔助工具：彙總必要結果與缺陷幾何轉換。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out


class InspectionSummaryTool(Tool):
    key = "inspection_summary"
    label = "Inspection summary"
    description = "Combines required inspection booleans and rejects the run when any required result is missing or failed."
    category = "logic"
    icon = "ClipboardCheck"
    params = [Param("expected_count", "Expected results", kind="number", required=True, default=1, minimum=1)]
    inputs = [Port("results", "Results", "bool", required=False, multiple=True)]
    outputs = [
        flow_out("ok", "OK", "ok"), flow_out("ng", "NG", "critical"),
        Port("received", "Received", "number"), Port("passed", "Passed", "number"), Port("missing", "Missing", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        expected = max(1, ctx.integer("expected_count", 1))
        values = [bool(v) for v in (ctx.inputs.get("results") or []) if v is not None]
        received = len(values)
        passed = sum(1 for v in values if v)
        missing = max(0, expected - received)
        ok = received >= expected and passed == received
        message = f"Received {received}/{expected}, {received - passed} failed"
        return Result(
            outputs={"received": received, "passed": passed, "missing": missing},
            branch="ok" if ok else "ng",
            status="ok" if ok else "ng",
            message=message,
        )


def _rect_corners(rect: dict[str, Any]) -> list[list[float]] | None:
    """rotated_rect／rect dict 轉四角點。"""
    try:
        shape = rect.get("shape")
        if shape == "rotated_rect":
            box = cv2.boxPoints(((float(rect["cx"]), float(rect["cy"])), (float(rect["w"]), float(rect["h"])), float(rect.get("angle", 0))))
            return [[float(x), float(y)] for x, y in box]
        if shape == "rect":
            x, y, w, h = float(rect["x"]), float(rect["y"]), float(rect["w"]), float(rect["h"])
            return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _rect_center(rect: dict[str, Any]) -> list[float] | None:
    if not isinstance(rect, dict):
        return None
    try:
        if rect.get("shape") == "rotated_rect":
            return [float(rect["cx"]), float(rect["cy"])]
        if rect.get("shape") == "rect":
            return [float(rect["x"]) + float(rect["w"]) / 2.0, float(rect["y"]) + float(rect["h"]) / 2.0]
    except (KeyError, TypeError, ValueError):
        return None
    pts = _rect_corners(rect)
    if pts:
        arr = np.asarray(pts, dtype=np.float64)
        return [float(arr[:, 0].mean()), float(arr[:, 1].mean())]
    return None


def _span_points(item: dict[str, Any]) -> list[list[float]] | None:
    """優先使用明確 span，否則用外框主軸兩端近似缺陷起訖。"""
    span = item.get("span")
    if isinstance(span, list) and len(span) >= 2:
        try:
            return [[float(span[0][0]), float(span[0][1])], [float(span[1][0]), float(span[1][1])]]
        except (TypeError, ValueError, IndexError):
            pass
    rect = item.get("rect")
    corners = _rect_corners(rect) if isinstance(rect, dict) else None
    if not corners:
        return None
    arr = np.asarray(corners, dtype=np.float64)
    best = (0.0, arr[0], arr[1])
    for a in arr:
        for b in arr:
            d = float(np.sum((a - b) ** 2))
            if d > best[0]:
                best = (d, a, b)
    return [[float(best[1][0]), float(best[1][1])], [float(best[2][0]), float(best[2][1])]]


class DefectsToGeometryTool(Tool):
    key = "defects_to_geometry"
    label = "Defects to geometry"
    description = "Converts defect records into centres, box corners or span points for downstream geometry and coordinate restore tools."
    category = "logic"
    icon = "ScanLine"
    params = [
        Param("output", "Output", kind="select", default="centres", options=[
            {"value": "centres", "label": "Centres"},
            {"value": "boxes", "label": "Box corners"},
            {"value": "spans", "label": "Span ends"},
        ]),
    ]
    inputs = [Port("defects", "Defects", "list")]
    outputs = [Port("points", "Points", "points"), Port("contours", "Contours", "contours"), Port("count", "Count", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        defects = ctx.inputs.get("defects")
        if defects is None:
            raise ToolError("Connect the defects input")
        if not isinstance(defects, list):
            raise ToolError("Defects must be a list")
        mode = str(ctx.param("output", "centres"))
        points: list[list[float]] = []
        contours: list[np.ndarray] = []
        skipped = 0
        for i, item in enumerate(defects):
            if not isinstance(item, dict):
                skipped += 1
                ctx.log(f"Defect {i + 1} is not an object; skipped", level="warn")
                continue
            if mode == "boxes":
                corners = _rect_corners(item.get("rect") if isinstance(item.get("rect"), dict) else {})
                if not corners:
                    skipped += 1
                    ctx.log(f"Defect {i + 1} has no usable box; skipped", level="warn")
                    continue
                points.extend(corners)
                contours.append(np.asarray(corners, dtype=np.float32).reshape(-1, 1, 2))
            elif mode == "spans":
                span = _span_points(item)
                if not span:
                    skipped += 1
                    ctx.log(f"Defect {i + 1} has no usable span; skipped", level="warn")
                    continue
                points.extend(span)
                contours.append(np.asarray(span, dtype=np.float32).reshape(-1, 1, 2))
            else:
                centre = item.get("centre") or item.get("center") or item.get("centroid") or _rect_center(item.get("rect") if isinstance(item.get("rect"), dict) else {})
                if not centre:
                    skipped += 1
                    ctx.log(f"Defect {i + 1} has no usable centre; skipped", level="warn")
                    continue
                try:
                    points.append([float(centre[0]), float(centre[1])])
                except (TypeError, ValueError, IndexError):
                    skipped += 1
                    ctx.log(f"Defect {i + 1} has no usable centre; skipped", level="warn")
        overlays = []
        if points:
            overlays.append({"kind": "points", "points": points, "color": "#f59e0b"})
        if contours:
            overlays.append({"kind": "contours", "contours": [c.reshape(-1, 2).tolist() for c in contours], "color": "#22c55e", "width": 1})
        count = len(defects) - skipped
        return Result(outputs={"points": points, "contours": contours, "count": count}, overlays=overlays, message=f"{count} defects converted")


TOOLS = [InspectionSummaryTool(), DefectsToGeometryTool()]
