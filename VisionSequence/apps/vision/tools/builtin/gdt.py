"""形位公差（gdt_measure）：直線度、平面度（2D 投影）、真圓度、平行度、垂直度、傾斜度——照 ISO 1101 的定義，不自創。

- 直線度／平面度：包容所有點的**最小寬度平行帶**（凸包＋旋轉卡尺：帶的一邊必與凸包某條邊重合），不是最小二乘殘差近似。
- 真圓度：**最小區域圓 MZC**（包容所有點的兩個同心圓半徑差最小）——以最小二乘圓（Taubin＋幾何精修）為起點做 Nelder–Mead；
  detail 同時給 LSC 的半徑差，現場爭議時拿得出來。
- 平行度／垂直度／傾斜度：以 b 為基準方向（垂直度轉 90°、傾斜度轉 reference_angle），量 a 的點到「沿基準方向的直線」的偏差帶寬度；
  a 只是一條線（兩端點）時退化為 |Δθ|×線長。
每個 mode 的 detail 回傳方法名稱與中間量（擬合參數、極值點索引）。
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.contours import _as_contours
from apps.vision.tools.builtin.locate import fit_circle_lsq

MODE_OPTIONS = [
    {"value": "straightness", "label": "Straightness (points)"},
    {"value": "flatness", "label": "Flatness (points, 2D projection)"},
    {"value": "roundness", "label": "Roundness (points)"},
    {"value": "parallelism", "label": "Parallelism (a against datum b)"},
    {"value": "perpendicularity", "label": "Perpendicularity (a against datum b)"},
    {"value": "angularity", "label": "Angularity (a against datum b at the reference angle)"},
]
UNIT_OPTIONS = [{"value": "px", "label": "Pixels"}, {"value": "mm", "label": "Millimetres (scale from the calibration tool)"}]
POINT_MODES = ("straightness", "flatness", "roundness")
DATUM_MODES = ("parallelism", "perpendicularity", "angularity")


def _points(value: Any) -> np.ndarray:
    if value is None:
        return np.zeros((0, 2), dtype=np.float64)
    if isinstance(value, dict) and "x1" in value:
        return np.array([[value["x1"], value["y1"]], [value["x2"], value["y2"]]], dtype=np.float64)
    if isinstance(value, dict) and "points" in value:
        value = value["points"]
    if isinstance(value, np.ndarray) and value.ndim == 3:
        value = [value]
    if isinstance(value, (list, tuple)) and len(value) and np.ndim(value[0]) >= 2:
        # contours 埠（contour_find／contour_filter）：照「first」慣例取第一條輪廓的點
        cnts = _as_contours(value)
        return cnts[0].reshape(-1, 2).astype(np.float64) if cnts else np.zeros((0, 2), dtype=np.float64)
    rows = []
    for p in value:
        if isinstance(p, dict):
            if "x" in p and "y" in p:
                rows.append([float(p["x"]), float(p["y"])])
            elif "cx" in p and "cy" in p:
                rows.append([float(p["cx"]), float(p["cy"])])
            continue
        try:
            rows.append([float(p[0]), float(p[1])])
        except (TypeError, IndexError, ValueError):
            continue
    return np.asarray(rows, dtype=np.float64).reshape(-1, 2)


def _direction(value: Any) -> tuple[float, float] | None:
    """基準方向（單位向量）：line dict、兩點以上的點集（主方向 PCA）、或 {"angle": deg}。"""
    if isinstance(value, dict) and "angle" in value and "x1" not in value:
        t = math.radians(float(value["angle"]))
        return math.cos(t), math.sin(t)
    if isinstance(value, (int, float)):
        t = math.radians(float(value))
        return math.cos(t), math.sin(t)
    pts = _points(value)
    if len(pts) < 2:
        return None
    if len(pts) == 2:
        d = pts[1] - pts[0]
    else:
        c = pts - pts.mean(axis=0)
        _, _, vt = np.linalg.svd(c, full_matrices=False)
        d = vt[0]
    n = float(np.hypot(d[0], d[1]))
    if n < 1e-9:
        return None
    return float(d[0] / n), float(d[1] / n)


def _fold(angle: float) -> float:
    """線的方向角折到 (−90, 90]（線沒有頭尾）。"""
    a = (angle + 90.0) % 180.0 - 90.0
    return 90.0 if a == -90.0 else a


def min_zone_band(pts: np.ndarray) -> dict[str, Any]:
    """最小寬度平行帶（旋轉卡尺）：帶的一邊必與凸包某條邊重合 → 對每條邊取所有點的最大距離，取最小。"""
    if len(pts) < 2:
        raise ToolError("At least two points are needed")
    if len(pts) == 2:
        return {"width": 0.0, "angle": _fold(math.degrees(math.atan2(pts[1, 1] - pts[0, 1], pts[1, 0] - pts[0, 0]))), "extreme": [0, 1], "method": "rotating calipers"}
    hull = cv2.convexHull(pts.astype(np.float32)).reshape(-1, 2).astype(np.float64)
    if len(hull) < 3:
        # 共線：寬度 0，方向為兩端連線
        d = pts[np.argmax(np.linalg.norm(pts - pts[0], axis=1))] - pts[0]
        return {"width": 0.0, "angle": _fold(math.degrees(math.atan2(d[1], d[0]))), "extreme": [0, int(np.argmax(np.linalg.norm(pts - pts[0], axis=1)))], "method": "rotating calipers"}
    best = None
    for i in range(len(hull)):
        a, b = hull[i], hull[(i + 1) % len(hull)]
        d = b - a
        n = float(np.hypot(d[0], d[1]))
        if n < 1e-9:
            continue
        normal = np.array([-d[1], d[0]]) / n
        dist = (pts - a) @ normal
        width = float(dist.max() - dist.min())
        if best is None or width < best["width"]:
            best = {"width": width, "angle": math.degrees(math.atan2(d[1], d[0])), "extreme": [int(np.argmin(dist)), int(np.argmax(dist))], "method": "rotating calipers"}
    if best is None:
        return {"width": 0.0, "angle": 0.0, "extreme": [0, 0], "method": "rotating calipers"}
    best["angle"] = _fold(best["angle"])
    return best


def _radial_span(c: np.ndarray, pts: np.ndarray) -> float:
    r = np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1])
    return float(r.max() - r.min())


def min_zone_circle(pts: np.ndarray) -> dict[str, Any]:
    """最小區域圓（MZC）：以最小二乘圓為起點，Nelder–Mead 最小化 max r − min r。"""
    if len(pts) < 3:
        raise ToolError("At least three points are needed for roundness")
    lsq = fit_circle_lsq(pts)
    if lsq is None:
        raise ToolError("The points do not describe a circle")
    cx, cy, r = lsq
    extent = float(np.hypot(*(pts.max(axis=0) - pts.min(axis=0)))) + 1e-9
    if not np.isfinite(r) or r > 50.0 * extent:
        # 點幾乎共線：圓半徑爆成點雲跨距的幾十倍以上，兩個同心圓的環寬會小到誤判「合格」——這裡沒有圓可量
        raise ToolError("The points are nearly collinear, so roundness is undefined; use straightness for a straight edge")
    start = np.array([cx, cy], dtype=np.float64)
    lsc = _radial_span(start, pts)
    try:
        from scipy.optimize import minimize

        res = minimize(lambda c: _radial_span(c, pts), start, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": 400})
        centre = res.x if res.fun <= lsc + 1e-9 else start
    except ImportError:  # pragma: no cover - scipy 是平台依賴
        centre = start
    rr = np.hypot(pts[:, 0] - centre[0], pts[:, 1] - centre[1])
    return {"width": float(rr.max() - rr.min()), "cx": float(centre[0]), "cy": float(centre[1]), "r_min": float(rr.min()), "r_max": float(rr.max()),
            "extreme": [int(np.argmin(rr)), int(np.argmax(rr))], "lsc": {"cx": float(cx), "cy": float(cy), "r": float(r), "width": lsc}, "method": "MZC (minimum zone), LSC as fallback"}


def datum_band(a_pts: np.ndarray, direction: tuple[float, float]) -> dict[str, Any]:
    """a 的點到「沿基準方向」的偏差帶寬度：投影到基準法向，max − min。"""
    if len(a_pts) < 2:
        raise ToolError("Feature a needs at least two points (a line or a points list)")
    normal = np.array([-direction[1], direction[0]])
    d = a_pts @ normal
    return {"width": float(d.max() - d.min()), "extreme": [int(np.argmin(d)), int(np.argmax(d))], "datum_angle": _fold(math.degrees(math.atan2(direction[1], direction[0])))}


class GdtMeasureTool(Tool):
    key = "gdt_measure"
    label = "Form and position tolerance"
    description = (
        "Geometric tolerances the way the drawing states them (ISO 1101): straightness and flatness as the narrowest band that holds "
        "every point, roundness as the narrowest ring between two concentric circles, and parallelism, perpendicularity and angularity "
        "of a feature against a datum. Reports the deviation, whether it is within tolerance, and the method and extreme points behind it."
    )
    category = "measure"
    icon = "Ruler"
    params = [
        Param("mode", "Tolerance", kind="select", default="straightness", options=MODE_OPTIONS),
        Param("tolerance", "Tolerance zone", kind="number", default=1.0, minimum=0, step=0.01, teach=True, help_text="Width of the zone the deviation must stay within (pixels, or millimetres with a scale)."),
        Param("unit", "Unit", kind="select", default="px", options=UNIT_OPTIONS),
        Param("mm_per_px", "mm per pixel", kind="number", default=0, minimum=0, step=0.0001, visible_when={"param": "unit", "in": ["mm"]}, help_text="Leave 0 and connect the scale input from the calibration tool."),
        Param("reference_angle", "Reference angle", kind="number", default=0, minimum=-180, maximum=180, unit="°", teach=True, visible_when={"param": "mode", "in": ["angularity"]},
              help_text="The angle feature a should make with datum b (positive = clockwise on screen)."),
    ]
    inputs = [
        Port("points", "Points", "points", required=False),
        Port("a", "Feature a", "any", required=False, accepts_semantics=("line",)),
        Port("b", "Datum b", "any", required=False, accepts_semantics=("line",)),
        Port("scale", "Scale (mm per pixel)", "number", required=False),
        Port("image", "Image (for display)", "image", required=False),
    ]
    outputs = [
        flow_out("pass", "Pass", "ok"), flow_out("fail", "Fail", "critical"),
        Port("deviation", "Deviation", "number"), Port("in_spec", "In spec", "bool"), Port("unit", "Unit", "string"), Port("tolerance", "Tolerance", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        mode = str(ctx.param("mode", "straightness"))
        tol = ctx.number("tolerance", 1.0)
        unit = str(ctx.param("unit", "px"))
        scale = 1.0
        if unit == "mm":
            s = ctx.inputs.get("scale")
            try:
                scale = float(s) if s is not None else ctx.number("mm_per_px", 0)
            except (TypeError, ValueError):
                raise ToolError("The scale must be a number (mm per pixel)") from None
            if scale <= 0:
                raise ToolError("Millimetre mode needs a scale: connect the calibration tool's scale output or set mm per pixel")
        overlays: list[dict[str, Any]] = []
        detail: dict[str, Any] = {"mode": mode}
        if mode in POINT_MODES:
            pts = _points(ctx.inputs.get("points") if ctx.inputs.get("points") is not None else ctx.inputs.get("a"))
            if len(pts) < (3 if mode == "roundness" else 2):
                raise ToolError("Connect the points to evaluate (find_line.points, find_circle.points or circular_caliper.points)")
            info = min_zone_circle(pts) if mode == "roundness" else min_zone_band(pts)
            width_px = float(info["width"])
            detail.update({k: v for k, v in info.items() if k != "extreme"})
            detail["extreme_index"] = info["extreme"]
            overlays.append({"kind": "points", "points": pts.round(2).tolist(), "color": "#22c55e"})
            for i in info["extreme"]:
                overlays.append({"kind": "point", "x": float(pts[i, 0]), "y": float(pts[i, 1]), "color": "#ef4444"})
            if mode == "roundness":
                overlays.append({"kind": "circle", "cx": info["cx"], "cy": info["cy"], "r": info["r_min"], "color": "#f59e0b", "width": 1, "dash": True})
                overlays.append({"kind": "circle", "cx": info["cx"], "cy": info["cy"], "r": info["r_max"], "color": "#f59e0b", "width": 1, "dash": True})
            else:
                t = math.radians(info["angle"])
                d = np.array([math.cos(t), math.sin(t)])
                n = np.array([-d[1], d[0]])
                c = pts.mean(axis=0)
                half = float(np.hypot(*(pts.max(axis=0) - pts.min(axis=0)))) / 2 + 10
                for i in info["extreme"]:
                    off = float((pts[i] - c) @ n)
                    p0, p1 = c + n * off - d * half, c + n * off + d * half
                    overlays.append({"kind": "line", "x1": float(p0[0]), "y1": float(p0[1]), "x2": float(p1[0]), "y2": float(p1[1]), "color": "#f59e0b", "width": 1, "dash": True})
        elif mode in DATUM_MODES:
            a_pts = _points(ctx.inputs.get("a"))
            direction = _direction(ctx.inputs.get("b"))
            if len(a_pts) < 2 or direction is None:
                raise ToolError("Connect feature a (a line or points) and datum b (a line, points or an angle)")
            if mode == "perpendicularity":
                direction = (-direction[1], direction[0])
            elif mode == "angularity":
                t = math.radians(ctx.number("reference_angle", 0))
                direction = (direction[0] * math.cos(t) - direction[1] * math.sin(t), direction[0] * math.sin(t) + direction[1] * math.cos(t))
            info = datum_band(a_pts, direction)
            width_px = float(info["width"])
            detail.update({"datum_angle": round(info["datum_angle"], 3), "extreme_index": info["extreme"], "method": "band about the datum direction",
                           "feature_points": int(len(a_pts))})
            if len(a_pts) == 2:
                detail["feature_length"] = round(float(np.linalg.norm(a_pts[1] - a_pts[0])), 3)
                detail["angle_difference"] = round(math.degrees(math.asin(min(1.0, width_px / max(1e-9, detail["feature_length"])))), 4)
            overlays.append({"kind": "points" if len(a_pts) > 2 else "line", **({"points": a_pts.round(2).tolist()} if len(a_pts) > 2 else {"x1": float(a_pts[0, 0]), "y1": float(a_pts[0, 1]), "x2": float(a_pts[1, 0]), "y2": float(a_pts[1, 1])}), "color": "#22c55e", "width": 2})
            c = a_pts.mean(axis=0)
            d = np.array(direction)
            half = float(np.linalg.norm(a_pts.max(axis=0) - a_pts.min(axis=0))) / 2 + 10
            overlays.append({"kind": "line", "x1": float(c[0] - d[0] * half), "y1": float(c[1] - d[1] * half), "x2": float(c[0] + d[0] * half), "y2": float(c[1] + d[1] * half), "color": "#38bdf8", "width": 1, "dash": True, "label": "datum"})
        else:
            raise ToolError(f"Unknown tolerance mode '{mode}'")
        deviation = width_px * scale
        in_spec = deviation <= tol
        detail["deviation_px"] = round(width_px, 4)
        return Result(
            outputs={"deviation": round(deviation, 6), "in_spec": bool(in_spec), "unit": unit, "tolerance": tol},
            overlays=overlays, branch="pass" if in_spec else "fail", status="ok" if in_spec else "ng",
            message=f"{mode}: {deviation:.4f} {unit} (tolerance {tol:g}) — {'in spec' if in_spec else 'OUT of spec'}",
            detail=detail,
        )


TOOLS = [GdtMeasureTool()]
