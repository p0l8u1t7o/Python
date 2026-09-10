"""點集擬合工具：把上游找到的點或輪廓轉成可量測幾何。"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin import locate
from apps.vision.tools.physical import CALIBRATION_PARAM, world_outputs


METHOD_OPTIONS = [
    {"value": "lsq", "label": "Least squares"},
    {"value": "ransac", "label": "RANSAC"},
]


def _as_points(value: Any, *, allow_contours: bool = True) -> np.ndarray:
    """把 points／第一條 contour 正規化成 (N, 2) float64。"""
    if value is None:
        raise ToolError("Connect points or contours to fit")
    if isinstance(value, np.ndarray):
        arr = value
        if arr.ndim >= 2:
            return arr.reshape(-1, 2).astype(np.float64)
        raise ToolError("Connect points or contours to fit")
    if allow_contours and isinstance(value, list) and value and isinstance(value[0], np.ndarray):
        return np.asarray(value[0], dtype=np.float64).reshape(-1, 2)
    rows: list[list[float]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            x = item.get("x", item.get("cx"))
            y = item.get("y", item.get("cy"))
            if x is None or y is None:
                continue
            rows.append([float(x), float(y)])
        else:
            try:
                rows.append([float(item[0]), float(item[1])])
            except (TypeError, IndexError, ValueError):
                continue
    return np.asarray(rows, dtype=np.float64).reshape(-1, 2)


def _point_span(points: np.ndarray) -> float:
    """點雲最大跨度；用來判斷共線圓的退化半徑。"""
    if len(points) < 2:
        return 0.0
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    return float(np.hypot(*(maxs - mins)))


def _line_angle(vx: float, vy: float) -> float:
    """平台角度慣例：畫面座標中順時針為正。"""
    return float(math.degrees(math.atan2(vy, vx)))


def _line_residual(points: np.ndarray, fit: tuple[float, float, float, float]) -> float:
    vx, vy, x0, y0 = fit
    dist = np.abs((points[:, 0] - x0) * (-vy) + (points[:, 1] - y0) * vx)
    return float(math.sqrt(float(np.mean(dist * dist)))) if len(dist) else float("nan")


def _circle_residual(points: np.ndarray, circle: tuple[float, float, float]) -> float:
    cx, cy, r = circle
    dist = np.hypot(points[:, 0] - cx, points[:, 1] - cy) - r
    return float(math.sqrt(float(np.mean(dist * dist)))) if len(dist) else float("nan")


def _ng(message: str, count: int) -> Result:
    return Result(outputs={"count": count, "inliers": 0}, branch="not_found", status="ng", message=message)


class FitLinePointsTool(Tool):
    key = "fit_line_points"
    label = "Fit line from points"
    description = "Fits a line to points or the first contour, with optional outlier rejection."
    category = "measure"
    icon = "Slash"
    params = [
        CALIBRATION_PARAM,
        Param("method", "Method", kind="select", default="lsq", options=METHOD_OPTIONS),
        Param("ransac_tol", "RANSAC tolerance", kind="number", default=2.0, minimum=0.1, maximum=100, unit="px", teach=True),
    ]
    inputs = [Port("points", "Points", "points", required=False), Port("contours", "Contours", "contours", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("line", "Line", "any", semantic="line"), Port("x1", "X1", "number"), Port("y1", "Y1", "number"),
        Port("x2", "X2", "number"), Port("y2", "Y2", "number"), Port("angle", "Angle", "number"),
        Port("residual_rms", "Residual RMS", "number"), Port("inliers", "Inliers", "number"), Port("count", "Count", "number"),
        Port("x1_world", "X1 (world)", "number"), Port("y1_world", "Y1 (world)", "number"),
        Port("x2_world", "X2 (world)", "number"), Port("y2_world", "Y2 (world)", "number"),
        Port("angle_world", "Angle (world)", "number"), Port("unit", "Unit", "string"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        points = _as_points(ctx.inputs.get("points") if ctx.inputs.get("points") is not None else ctx.inputs.get("contours"))
        count = len(points)
        if count < 2 or _point_span(points) < 1e-9:
            return _ng("Need at least two distinct points", count)
        method = str(ctx.param("method", "lsq"))
        fitted = locate.fit_points_line(points, ransac=(method == "ransac"), tol=ctx.number("ransac_tol", 2.0))
        if fitted is None:
            return _ng("No line could be fitted", count)
        vx, vy, x0, y0, inliers = fitted
        used = points[np.asarray(inliers, dtype=bool)]
        if len(used) < 2:
            return _ng("No line could be fitted", count)
        line = locate.line_span((vx, vy, x0, y0), used)
        angle = _line_angle(vx, vy)
        outputs: dict[str, Any] = {
            "line": line, **line, "angle": angle,
            "residual_rms": _line_residual(used, (vx, vy, x0, y0)),
            "inliers": int(np.count_nonzero(inliers)), "count": count,
        }
        outputs.update(world_outputs(ctx, points={("x1", "y1"): (line["x1"], line["y1"]), ("x2", "y2"): (line["x2"], line["y2"])},
                                     angles={"angle": (angle, ((line["x1"] + line["x2"]) / 2, (line["y1"] + line["y2"]) / 2))}))
        return Result(
            outputs=outputs,
            overlays=[{"kind": "line", **line, "color": "#22c55e", "width": 2}],
            branch="found",
            message=f"{outputs['inliers']}/{count} points, RMS {outputs['residual_rms']:.3f}px",
        )


class FitCirclePointsTool(Tool):
    key = "fit_circle_points"
    label = "Fit circle from points"
    description = "Fits a circle to points or the first contour, with optional outlier rejection."
    category = "measure"
    icon = "Circle"
    params = [
        CALIBRATION_PARAM,
        Param("method", "Method", kind="select", default="lsq", options=METHOD_OPTIONS),
        Param("ransac_tol", "RANSAC tolerance", kind="number", default=2.0, minimum=0.1, maximum=100, unit="px", teach=True),
    ]
    inputs = [Port("points", "Points", "points", required=False), Port("contours", "Contours", "contours", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("circle", "Circle", "any", semantic="circle"), Port("cx", "Centre X", "number"), Port("cy", "Centre Y", "number"),
        Port("r", "Radius", "number"), Port("diameter", "Diameter", "number"),
        Port("residual_rms", "Residual RMS", "number"), Port("inliers", "Inliers", "number"), Port("count", "Count", "number"),
        Port("cx_world", "Centre X (world)", "number"), Port("cy_world", "Centre Y (world)", "number"),
        Port("r_world", "Radius (world)", "number"), Port("diameter_world", "Diameter (world)", "number"), Port("unit", "Unit", "string"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        points = _as_points(ctx.inputs.get("points") if ctx.inputs.get("points") is not None else ctx.inputs.get("contours"))
        count = len(points)
        span = _point_span(points)
        if count < 3 or span < 1e-9:
            return _ng("Need at least three distinct points", count)
        if str(ctx.param("method", "lsq")) == "ransac":
            fitted = locate.fit_circle_ransac(points, tol=ctx.number("ransac_tol", 2.0))
            if fitted is None:
                return _ng("No circle could be fitted", count)
            circle, inliers = fitted
            used = points[np.asarray(inliers, dtype=bool)]
        else:
            circle = locate.fit_circle_lsq(points)
            inliers = np.ones(count, dtype=bool)
            used = points
        if circle is None or circle[2] > 50.0 * max(1e-9, span):
            return _ng("The points are too close to a line to fit a circle", count)
        cx, cy, r = circle
        out_circle = {"cx": cx, "cy": cy, "r": r}
        outputs: dict[str, Any] = {
            "circle": out_circle, "cx": cx, "cy": cy, "r": r, "diameter": r * 2.0,
            "residual_rms": _circle_residual(used, circle), "inliers": int(np.count_nonzero(inliers)), "count": count,
        }
        outputs.update(world_outputs(ctx, points={("cx", "cy"): (cx, cy)}, lengths={"r": (r, (cx, cy)), "diameter": (r * 2.0, (cx, cy))}))
        return Result(
            outputs=outputs,
            overlays=[{"kind": "circle", "cx": cx, "cy": cy, "r": r, "color": "#22c55e", "width": 2}],
            branch="found",
            message=f"{outputs['inliers']}/{count} points, r {r:.3f}px, RMS {outputs['residual_rms']:.3f}px",
        )


class FitEllipsePointsTool(Tool):
    key = "fit_ellipse_points"
    label = "Fit ellipse from points"
    description = "Fits an ellipse to points or the first contour."
    category = "measure"
    icon = "CircleDashed"
    params = [CALIBRATION_PARAM]
    inputs = [Port("points", "Points", "points", required=False), Port("contours", "Contours", "contours", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("ellipse", "Ellipse", "any", semantic="ellipse"), Port("cx", "Centre X", "number"), Port("cy", "Centre Y", "number"),
        Port("major", "Major axis", "number"), Port("minor", "Minor axis", "number"), Port("angle", "Angle", "number"),
        Port("residual_rms", "Residual RMS", "number"), Port("count", "Count", "number"),
        Port("cx_world", "Centre X (world)", "number"), Port("cy_world", "Centre Y (world)", "number"),
        Port("major_world", "Major axis (world)", "number"), Port("minor_world", "Minor axis (world)", "number"),
        Port("angle_world", "Angle (world)", "number"), Port("unit", "Unit", "string"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        points = _as_points(ctx.inputs.get("points") if ctx.inputs.get("points") is not None else ctx.inputs.get("contours"))
        count = len(points)
        if count < 5 or _point_span(points) < 1e-9:
            return _ng("Need at least five distinct points", count)
        try:
            (cx, cy), (d1, d2), raw_angle = cv2.fitEllipse(points.astype(np.float32).reshape(-1, 1, 2))
        except cv2.error:
            return _ng("No ellipse could be fitted", count)
        if not all(np.isfinite([cx, cy, d1, d2, raw_angle])) or min(d1, d2) <= 0:
            return _ng("No ellipse could be fitted", count)
        major, minor = (float(d1), float(d2)) if d1 >= d2 else (float(d2), float(d1))
        angle = float(raw_angle + (90.0 if d2 > d1 else 0.0))
        angle = ((angle + 180.0) % 360.0) - 180.0
        theta = math.radians(angle)
        ct, st = math.cos(theta), math.sin(theta)
        rel = points - np.array([cx, cy], dtype=np.float64)
        xr = rel[:, 0] * ct + rel[:, 1] * st
        yr = -rel[:, 0] * st + rel[:, 1] * ct
        radial = np.sqrt((xr / max(major / 2.0, 1e-9)) ** 2 + (yr / max(minor / 2.0, 1e-9)) ** 2)
        residual = float(math.sqrt(float(np.mean((radial - 1.0) ** 2))))
        ellipse = {"cx": float(cx), "cy": float(cy), "major": major, "minor": minor, "angle": angle}
        outputs: dict[str, Any] = {"ellipse": ellipse, **ellipse, "residual_rms": residual, "count": count}
        outputs.update(world_outputs(ctx, points={("cx", "cy"): (cx, cy)}, lengths={"major": (major, (cx, cy)), "minor": (minor, (cx, cy))},
                                     angles={"angle": (angle, (cx, cy))}))
        ts = np.linspace(0.0, 2.0 * math.pi, 80, endpoint=False)
        ca, sa = math.cos(theta), math.sin(theta)
        local = np.column_stack([np.cos(ts) * major / 2.0, np.sin(ts) * minor / 2.0])
        poly = np.column_stack([cx + local[:, 0] * ca - local[:, 1] * sa, cy + local[:, 0] * sa + local[:, 1] * ca])
        return Result(
            outputs=outputs,
            overlays=[{"kind": "polyline", "points": poly.tolist(), "color": "#22c55e", "width": 2}],
            branch="found",
            message=f"{count} points, {major:.3f}×{minor:.3f}px, RMS {residual:.4f}",
        )


TOOLS = [FitLinePointsTool(), FitCirclePointsTool(), FitEllipsePointsTool()]
