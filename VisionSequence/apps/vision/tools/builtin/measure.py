"""量測工具：卡尺、距離、夾角、灰階統計、像素校正、直方圖；杯件量測：圓弧／橢圓擬合、壁厚、同心度、倒角、公差判定。"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from apps.vision import calib
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.preprocess import read_calibration
from apps.vision.tools.builtin.locate import (
    POLARITY_OPTIONS,
    _as_rotated_rect,
    caliper_points,
    find_edges_1d,
    find_edges_rows,
    pick_pair,
    fit_circle_points,
    fit_line_ransac,
    radial_edge_points,
    to_gray,
)
from apps.vision.tools.hist import otsu_from_hist as _otsu_from_hist
from apps.vision.tools.roi import crop, extent as roi_extent, region_center, region_overlay


def _point(value: Any, fallback: tuple[Any, Any] | None = None) -> tuple[float, float] | None:
    """接受 {x,y} / {cx,cy} / [x,y] / 兩個數值。"""
    if isinstance(value, dict):
        x = value.get("x", value.get("cx"))
        y = value.get("y", value.get("cy"))
        if x is not None and y is not None:
            return float(x), float(y)
    if isinstance(value, (list, tuple, np.ndarray)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    if fallback is not None and fallback[0] is not None and fallback[1] is not None:
        try:
            return float(fallback[0]), float(fallback[1])
        except (TypeError, ValueError):
            return None
    return None


def _line(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, dict):
        try:
            return float(value["x1"]), float(value["y1"]), float(value["x2"]), float(value["y2"])
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple, np.ndarray)) and len(value) == 4:
        try:
            return tuple(float(v) for v in value)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        a, b = _point(value[0]), _point(value[1])
        if a and b:
            return a[0], a[1], b[0], b[1]
    return None


class CaliperTool(Tool):
    key = "caliper"
    label = "Caliper"
    description = "Projects a grey profile along the long side of a rectangle, finds a pair of edges and measures the width in pixels."
    category = "measure"
    icon = "Ruler"
    params = [
        Param("roi", "Region", kind="roi", required=True, shapes=["rotated_rect", "rect"], help_text="Scans along the long side, averaging across the short side to beat noise."),
        Param("polarity", "Edge polarity", kind="select", default="any", options=POLARITY_OPTIONS, teach=True),
        Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("edge_pair", "Pick edge pair", kind="select", default="first_last", options=[
            {"value": "first_last", "label": "First and last"},
            {"value": "widest", "label": "Widest pair"},
            {"value": "narrowest", "label": "Narrowest adjacent pair"},
            {"value": "strongest", "label": "Two strongest"},
        ]),
        Param("pair_polarity", "Edge pair polarity", kind="select", default="any", options=[
            {"value": "any", "label": "Any"}, {"value": "bright", "label": "Bright band (dark to light, then light to dark)"}, {"value": "dark", "label": "Dark band (light to dark, then dark to light)"},
        ], help_text="Constrains the polarity order of a pair, so measuring a bright or dark bar does not latch onto a neighbouring noise edge."),
        Param("expected_width", "Expected width", kind="number", default=0, minimum=0, unit="px", help_text="Above 0, picks the edge pair whose width is closest to this instead of following the pair mode."),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        Port("width", "Width", "number"),
        Port("edge1_x", "Edge 1 X", "number"), Port("edge1_y", "Edge 1 Y", "number"),
        Port("edge2_x", "Edge 2 X", "number"), Port("edge2_y", "Edge 2 Y", "number"),
        Port("edges", "All edge positions", "list"), Port("profile", "Profile", "list"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        rr = _as_rotated_rect(region)
        c = crop(image, rr, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 2:
            raise ToolError("The region is too small or falls outside the image")
        h, w = c.image.shape[:2]
        horizontal = w >= h
        # cv2.reduce 以 double 累加再除，與 numpy mean 對 uint8 結果相同。
        profile = cv2.reduce(np.ascontiguousarray(c.image), 0 if horizontal else 1, cv2.REDUCE_AVG, dtype=cv2.CV_64F).reshape(-1)
        edges = find_edges_1d(profile, ctx.param("polarity", "any"), ctx.number("edge_threshold", 20), ctx.integer("smoothing", 3))
        overlays = [region_overlay(region, label="caliper")]
        nan = float("nan")
        prof_list = np.round(profile, 1).tolist()
        if len(edges) < 2:
            return Result(outputs={"width": nan, "edge1_x": nan, "edge1_y": nan, "edge2_x": nan, "edge2_y": nan,
                                   "edges": [round(e[0], 2) for e in edges], "profile": prof_list},
                          overlays=overlays, status="ng", message=f"Fewer than two edges ({len(edges)})")
        pair = pick_pair(edges, ctx.param("edge_pair", "first_last"), ctx.param("pair_polarity", "any"), ctx.number("expected_width", 0))
        if pair is None:
            return Result(outputs={"width": nan, "edge1_x": nan, "edge1_y": nan, "edge2_x": nan, "edge2_y": nan,
                                   "edges": [round(e[0], 2) for e in edges], "profile": prof_list},
                          overlays=overlays, status="ng", message="No edge pair matches the polarity")
        (p1, _), (p2, _) = pair
        mid = (h if horizontal else w) / 2
        if horizontal:
            e1, e2 = c.to_full(p1, mid), c.to_full(p2, mid)
            seg1 = (c.to_full(p1, 0), c.to_full(p1, h))
            seg2 = (c.to_full(p2, 0), c.to_full(p2, h))
        else:
            e1, e2 = c.to_full(mid, p1), c.to_full(mid, p2)
            seg1 = (c.to_full(0, p1), c.to_full(w, p1))
            seg2 = (c.to_full(0, p2), c.to_full(w, p2))
        width = abs(p2 - p1)
        overlays += [
            {"kind": "line", "x1": seg1[0][0], "y1": seg1[0][1], "x2": seg1[1][0], "y2": seg1[1][1], "color": "#22c55e", "width": 2},
            {"kind": "line", "x1": seg2[0][0], "y1": seg2[0][1], "x2": seg2[1][0], "y2": seg2[1][1], "color": "#22c55e", "width": 2},
            {"kind": "line", "x1": e1[0], "y1": e1[1], "x2": e2[0], "y2": e2[1], "color": "#f59e0b", "width": 1, "label": f"{width:.2f}px"},
        ]
        return Result(
            outputs={"width": width, "edge1_x": e1[0], "edge1_y": e1[1], "edge2_x": e2[0], "edge2_y": e2[1],
                     "edges": [round(e[0], 2) for e in edges], "profile": prof_list},
            overlays=overlays, message=f"Width {width:.2f}px ({len(edges)} edges)",
        )


class DistanceTool(Tool):
    key = "distance"
    label = "Distance"
    description = (
        "The distance between two things, in pixels. Two points is the usual case, but A and B may also be a line or a circle: "
        "the gap between a hole and an edge, the clearance between two holes, how far a boss is from a datum line. A point is "
        "{x,y} or [x,y] (or four separate numbers), a line is {x1,y1,x2,y2}, a circle is {cx,cy,r}."
    )
    category = "measure"
    icon = "MoveHorizontal"
    params = [
        Param("mode", "Measure", kind="select", default="euclid", options=[
            {"value": "euclid", "label": "Straight-line distance"},
            {"value": "dx", "label": "Distance in X"},
            {"value": "dy", "label": "Distance in Y"},
            {"value": "nearest", "label": "Closest points (edge to edge)"},
            {"value": "farthest", "label": "Furthest points"},
            {"value": "centers", "label": "Centre to centre"},
        ], help_text="The last three matter when A or B is a circle or a line: a circle's edge, not its centre, is usually what the drawing calls out."),
    ]
    inputs = [
        Port("image", "Image", "image", required=False),
        Port("a", "Point A", "any", required=False), Port("b", "Point B", "any", required=False),
        Port("ax", "A.x", "number", required=False), Port("ay", "A.y", "number", required=False),
        Port("bx", "B.x", "number", required=False), Port("by", "B.y", "number", required=False),
    ]
    outputs = [Port("distance", "Distance", "number"), Port("dx", "dx", "number"), Port("dy", "dy", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        mode = str(ctx.param("mode", "euclid"))
        raw_a, raw_b = ctx.inputs.get("a"), ctx.inputs.get("b")
        shape_a, shape_b = _as_line(raw_a) or _as_circle(raw_a), _as_line(raw_b) or _as_circle(raw_b)
        if shape_a is not None or shape_b is not None:
            return _shape_distance(raw_a, raw_b, mode)
        a = _point(raw_a, (ctx.inputs.get("ax"), ctx.inputs.get("ay")))
        b = _point(raw_b, (ctx.inputs.get("bx"), ctx.inputs.get("by")))
        if a is None or b is None:
            raise ToolError("Two points are needed: wire a/b, or ax, ay, bx, by")
        if not all(np.isfinite([*a, *b])):
            return Result(outputs={"distance": float("nan"), "dx": float("nan"), "dy": float("nan")}, status="ng", message="The input point is not valid (the upstream step may have found nothing)")
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = abs(dx) if mode == "dx" else abs(dy) if mode == "dy" else math.hypot(dx, dy)
        overlays = [
            {"kind": "point", "x": a[0], "y": a[1], "color": "#38bdf8", "label": "A"},
            {"kind": "point", "x": b[0], "y": b[1], "color": "#38bdf8", "label": "B"},
            {"kind": "line", "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1], "color": "#f59e0b", "width": 2, "label": f"{d:.2f}px"},
        ]
        return Result(outputs={"distance": d, "dx": dx, "dy": dy}, overlays=overlays, message=f"{d:.2f}px")


def _shape_distance(raw_a: Any, raw_b: Any, mode: str) -> Result:
    """A 或 B 是圓或直線時的量法。回的兩個端點就是量到的那一段，畫出來一眼看得懂。"""
    a_line, a_circle, a_point = _as_line(raw_a), _as_circle(raw_a), _as_point(raw_a)
    b_line, b_circle, b_point = _as_line(raw_b), _as_circle(raw_b), _as_point(raw_b)
    far = mode == "farthest"
    centers = mode == "centers"

    def circle_to_point(circle: tuple[float, float, float], point: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
        cx, cy, r = circle
        span = math.hypot(point[0] - cx, point[1] - cy)
        if span < 1e-9:
            return (cx + r, cy), point
        ux, uy = (point[0] - cx) / span, (point[1] - cy) / span
        sign = -1.0 if far else 1.0
        return (cx + sign * ux * r, cy + sign * uy * r), point

    if a_circle and b_circle:
        (ax, ay, ar), (bx, by, br) = a_circle, b_circle
        span = math.hypot(bx - ax, by - ay)
        if centers or span < 1e-9:
            pa, pb = (ax, ay), (bx, by)
        else:
            ux, uy = (bx - ax) / span, (by - ay) / span
            sa, sb = (-1.0, 1.0) if far else (1.0, -1.0)
            pa, pb = (ax + sa * ux * ar, ay + sa * uy * ar), (bx + sb * ux * br, by + sb * uy * br)
    elif a_circle and (b_line or b_point):
        if b_line:
            foot = point_to_line((a_circle[0], a_circle[1]), b_line)[:2]
            pa, pb = (circle_to_point(a_circle, foot)[0], foot) if not centers else ((a_circle[0], a_circle[1]), foot)
        else:
            pa, pb = (circle_to_point(a_circle, b_point) if not centers else ((a_circle[0], a_circle[1]), b_point))
    elif b_circle and (a_line or a_point):
        if a_line:
            foot = point_to_line((b_circle[0], b_circle[1]), a_line)[:2]
            pb, pa = (circle_to_point(b_circle, foot)[0], foot) if not centers else ((b_circle[0], b_circle[1]), foot)
        else:
            pb, pa = (circle_to_point(b_circle, a_point) if not centers else ((b_circle[0], b_circle[1]), a_point))
    elif a_line and b_line:
        # 兩條線：量 B 的中點到 A 的垂距（平行時就是間距，不平行時是「在那一點的間距」）
        mid = ((b_line[0] + b_line[2]) / 2, (b_line[1] + b_line[3]) / 2)
        foot = point_to_line(mid, a_line)[:2]
        pa, pb = foot, mid
    elif a_line and b_point:
        pa, pb = point_to_line(b_point, a_line)[:2], b_point
    elif b_line and a_point:
        pa, pb = a_point, point_to_line(a_point, b_line)[:2]
    else:
        raise ToolError("Wire a point, a line {x1,y1,x2,y2} or a circle {cx,cy,r} into both A and B")

    dx, dy = pb[0] - pa[0], pb[1] - pa[1]
    d = abs(dx) if mode == "dx" else abs(dy) if mode == "dy" else math.hypot(dx, dy)
    overlays = [
        {"kind": "line", "x1": pa[0], "y1": pa[1], "x2": pb[0], "y2": pb[1], "color": "#f59e0b", "width": 2, "label": f"{d:.2f}px"},
        {"kind": "point", "x": pa[0], "y": pa[1], "color": "#38bdf8", "label": "A"},
        {"kind": "point", "x": pb[0], "y": pb[1], "color": "#38bdf8", "label": "B"},
    ]
    return Result(outputs={"distance": d, "dx": dx, "dy": dy}, overlays=overlays, message=f"{d:.2f}px")


class AngleTool(Tool):
    key = "angle"
    label = "Angle"
    description = "The angle between two lines, in degrees. A line may be {x1,y1,x2,y2} or eight separate numbers."
    category = "measure"
    icon = "TriangleRight"
    params = [
        Param("range", "Angle range", kind="select", default="0_90", options=[
            {"value": "0_90", "label": "0 to 90 (undirected)"}, {"value": "0_180", "label": "0 ~ 180"}, {"value": "signed", "label": "-180 to 180 (signed)"},
        ]),
    ]
    inputs = [
        Port("image", "Image", "image", required=False),
        Port("a", "Line A", "any", required=False), Port("b", "Line B", "any", required=False),
        Port("ax1", "A.x1", "number", required=False), Port("ay1", "A.y1", "number", required=False),
        Port("ax2", "A.x2", "number", required=False), Port("ay2", "A.y2", "number", required=False),
        Port("bx1", "B.x1", "number", required=False), Port("by1", "B.y1", "number", required=False),
        Port("bx2", "B.x2", "number", required=False), Port("by2", "B.y2", "number", required=False),
    ]
    outputs = [Port("angle_deg", "Angle", "number"), Port("angle_a", "A angle", "number"), Port("angle_b", "B angle", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        i = ctx.inputs
        la = _line(i.get("a")) or _line([i.get("ax1"), i.get("ay1"), i.get("ax2"), i.get("ay2")])
        lb = _line(i.get("b")) or _line([i.get("bx1"), i.get("by1"), i.get("bx2"), i.get("by2")])
        if la is None or lb is None:
            raise ToolError("Two lines are needed: wire a/b, or eight endpoint numbers")
        if not all(np.isfinite([*la, *lb])):
            return Result(outputs={"angle_deg": float("nan"), "angle_a": float("nan"), "angle_b": float("nan")}, status="ng", message="The input line is not valid")
        aa = math.degrees(math.atan2(la[3] - la[1], la[2] - la[0]))
        ab = math.degrees(math.atan2(lb[3] - lb[1], lb[2] - lb[0]))
        diff = (ab - aa + 180) % 360 - 180
        mode = ctx.param("range", "0_90")
        if mode == "0_90":
            ang = abs(diff) % 180
            ang = min(ang, 180 - ang)
        elif mode == "0_180":
            ang = abs(diff)
        else:
            ang = diff
        overlays = [
            {"kind": "line", "x1": la[0], "y1": la[1], "x2": la[2], "y2": la[3], "color": "#38bdf8", "width": 2, "label": "A"},
            {"kind": "line", "x1": lb[0], "y1": lb[1], "x2": lb[2], "y2": lb[3], "color": "#f59e0b", "width": 2, "label": f"B  {ang:.2f}°"},
        ]
        return Result(outputs={"angle_deg": ang, "angle_a": aa, "angle_b": ab}, overlays=overlays, message=f"{ang:.2f}°")


def _roi_hist(ctx: ToolContext) -> tuple[np.ndarray, dict[str, Any] | None]:
    """ROI 內灰階的 256 階直方圖（float64 計數），非矩形只算遮罩內。

    一次 cv2.calcHist（帶遮罩）就能推出平均／標準差／極值／中位數，
    比把像素抽成一維再用 numpy 算快 10 倍（1280×960 約 0.5 ms）。
    """
    image = to_gray(ctx.require_image())
    region = ctx.roi()
    c = crop(image, region)
    if c.image.size == 0:
        raise ToolError("The region falls outside the image")
    sub = c.image if c.image.dtype == np.uint8 else np.clip(c.image, 0, 255).astype(np.uint8)
    mask = c.mask if c.mask is None else np.ascontiguousarray(c.mask)
    hist = cv2.calcHist([np.ascontiguousarray(sub)], [0], mask, [256], [0, 256]).reshape(-1).astype(np.float64)
    if hist.sum() <= 0:
        raise ToolError("The region has no pixels")
    return hist, region


def _hist_stats(hist: np.ndarray) -> dict[str, float | int]:
    levels = np.arange(256, dtype=np.float64)
    n = hist.sum()
    mean = float((hist * levels).sum() / n)
    var = float((hist * (levels - mean) ** 2).sum() / n)
    nz = np.nonzero(hist)[0]
    cum = np.cumsum(hist)
    # 與 np.median 相同：偶數個取中間兩個的平均。
    n_int = int(n)
    lo = int(np.searchsorted(cum, (n_int - 1) // 2 + 1))
    hi = int(np.searchsorted(cum, n_int // 2 + 1))
    return {"mean": mean, "std": math.sqrt(max(0.0, var)), "min": float(nz[0]), "max": float(nz[-1]), "median": (lo + hi) / 2.0, "pixels": n_int}


class IntensityTool(Tool):
    key = "intensity"
    label = "Grayscale statistics"
    description = "Mean, standard deviation, minimum, maximum and median grey level in the region."
    category = "measure"
    icon = "Sun"
    params = [Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon", "point"], help_text="Blank uses the whole image; a point means a single pixel.")]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [Port("mean", "Mean", "number"), Port("std", "Std dev", "number"), Port("min", "Min", "number"), Port("max", "Max", "number"), Port("median", "Median", "number"), Port("pixels", "Pixel count", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        hist, region = _roi_hist(ctx)
        outputs = _hist_stats(hist)
        mean, std = outputs["mean"], outputs["std"]
        overlays = [region_overlay(region, label=f"mean {mean:.1f}")] if region else []
        return Result(outputs=outputs, overlays=overlays, message=f"Mean {mean:.1f} ± {std:.1f}")


class CalibrationTool(Tool):
    key = "calibration"
    label = "Pixel calibration"
    description = "Converts pixel measurements to millimetres, either from a direct mm-per-pixel figure or from a known distance (pixels against real millimetres). It can scale a list of points too."
    category = "measure"
    icon = "Scale"
    params = [
        Param("mode", "Calibration mode", kind="select", default="pixel_size", options=[
            {"value": "pixel_size", "label": "mm per pixel"}, {"value": "known_distance", "label": "Known distance"},
            {"value": "asset", "label": "From a calibration"},
        ]),
        Param("calibration", "Calibration", kind="asset", accept="calibration", visible_when={"param": "mode", "in": ["asset"]},
              help_text="Made on the Calibration page. Use this instead of typing a number: re-calibrating the station updates every flow at once."),
        Param("pixel_size_mm", "mm per pixel", kind="number", default=0.01, minimum=0, step=0.0001, unit="mm/px", visible_when={"param": "mode", "in": ["pixel_size"]}),
        Param("px_distance", "Pixel distance", kind="number", default=100, minimum=0, unit="px", visible_when={"param": "mode", "in": ["known_distance"]}),
        Param("real_mm", "Real distance", kind="number", default=1, minimum=0, unit="mm", visible_when={"param": "mode", "in": ["known_distance"]}),
        Param("power", "Power", kind="select", default="1", options=[{"value": "1", "label": "Length (x k)"}, {"value": "2", "label": "Area (x k squared)"}], help_text="Choose k² for area measurements."),
    ]
    inputs = [Port("value", "Pixel values", "number", required=False), Port("points", "Points", "points", required=False)]
    outputs = [Port("mm", "Millimetres", "number"), Port("scale", "Scale", "number"), Port("points_mm", "Points (mm)", "points")]

    def execute(self, ctx: ToolContext) -> Result:
        mode = ctx.param("mode", "pixel_size")
        if mode == "known_distance":
            px = ctx.number("px_distance", 0)
            if px <= 0:
                raise ToolError("The pixel distance must be greater than 0")
            k = ctx.number("real_mm", 0) / px
        elif mode == "asset":
            payload = read_calibration(ctx)
            world = payload.get("world")
            if not world:
                raise ToolError("That calibration has no scale yet: add a board, a known distance or robot points to it")
            k = float(world.get("mm_per_px") or 0)
        else:
            k = ctx.number("pixel_size_mm", 0)
        if k <= 0:
            raise ToolError("The scale must be greater than 0")
        power = 2 if str(ctx.param("power", "1")) == "2" else 1
        value = ctx.inputs.get("value")
        mm = float("nan")
        if value is not None:
            try:
                mm = float(value) * (k**power)
            except (TypeError, ValueError):
                raise ToolError(f"The input is not a number: {value!r}") from None
        pts = ctx.inputs.get("points")
        pts_mm: list[list[float]] = []
        if pts is not None:
            arr = np.asarray(pts, dtype=np.float64).reshape(-1, 2) * k
            pts_mm = arr.tolist()
        if value is None and pts is None:
            raise ToolError("No input: wire value or points")
        return Result(outputs={"mm": mm, "scale": k, "points_mm": pts_mm}, message=(f"{mm:.4f} mm" if value is not None else f"k={k:.5f}"))


class HistogramTool(Tool):
    key = "histogram"
    label = "Histogram"
    description = "A 256-bin grey histogram of the region, with its peak."
    category = "measure"
    icon = "BarChart3"
    params = [
        Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect", "circle", "annulus", "polygon"], help_text="Leave blank for the whole image."),
        Param("normalize", "Normalised (ratio)", kind="boolean", default=False),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [Port("histogram", "Histogram", "list"), Port("peak", "Peak grey level", "number"), Port("peak_count", "Peak count", "number"), Port("otsu", "Otsu threshold", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        hist, region = _roi_hist(ctx)
        peak = int(hist.argmax())
        peak_count = float(hist[peak])
        otsu = _otsu_from_hist(hist)
        if ctx.flag("normalize"):
            hist = hist / max(1.0, hist.sum())
        overlays = [region_overlay(region, label=f"peak {peak}")] if region else []
        return Result(outputs={"histogram": hist.tolist(), "peak": peak, "peak_count": peak_count, "otsu": float(otsu)}, overlays=overlays, message=f"Peak {peak}, Otsu {otsu:g}")



# ---------------------------------------------------------------------------
# 杯件量測：圓弧／橢圓擬合、壁厚、同心度、倒角、公差判定
# ---------------------------------------------------------------------------
_EDGE_SELECT_OPTIONS = [{"value": "strongest", "label": "Strongest"}, {"value": "first", "label": "First"}, {"value": "last", "label": "Last"}]


def _region_edge_points(ctx: ToolContext, image: np.ndarray, region: dict[str, Any], origin: tuple[float, float] | None = None) -> np.ndarray:
    """依 ROI 形狀取邊緣點：圓／圓環（含扇形 a0/a1）／多邊形走徑向掃描，矩形／旋轉矩形走卡尺。回傳 (N,2) 全圖座標。

    origin 給定時（重掃精修）改從該點發射掃描線。多邊形 ROI 的第一次掃描以頂點平均為原點且不分極性
    （原點可能落在工件外，極性無從定義），重掃時才套用使用者的極性。
    """
    polarity = ctx.param("polarity", "any")
    thr = ctx.number("edge_threshold", 20)
    sel = ctx.param("edge_select", "strongest")
    smoothing = ctx.integer("smoothing", 3)
    num = max(6, ctx.integer("num_rays", 36))
    shape = region.get("shape")
    if shape in ("circle", "annulus", "polygon", "composite"):
        cx, cy = origin if origin is not None else region_center(region)
        a0 = a1 = None
        mask, off = None, (0, 0)
        if shape == "circle":
            r_in, r_out = 0.0, float(region["r"])
        elif shape == "annulus":
            r_in, r_out = float(region["r_inner"]), float(region["r_outer"])
            a0, a1 = region.get("a0"), region.get("a1")
        else:
            # 多邊形／組合區域：掃到最遠角落，遮罩決定哪些邊緣點算數
            if shape == "polygon":
                pts = np.asarray(region["points"], dtype=np.float64)
            else:
                x0, y0, x1, y1 = roi_extent(region)
                pts = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float64)
            r_in, r_out = 0.0, float(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy).max())
            c = crop(image, region)
            mask, off = c.mask, (c.x0, c.y0)
            if origin is None:
                polarity = "any"
        if r_out - r_in < 3:
            raise ToolError("The region radius is too small")
        pts_out = radial_edge_points(image, cx, cy, r_in, r_out, num, polarity, thr, sel, smoothing, mask=mask, mask_offset=off, a0=a0, a1=a1)
        return np.asarray(pts_out, dtype=np.float64).reshape(-1, 2)
    if shape in ("rect", "rotated_rect"):
        rr = _as_rotated_rect(region)
        c = crop(image, rr, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 3:
            raise ToolError("The region is too small or falls outside the image")
        pts_local, _ = caliper_points(c.image, num, polarity, thr, sel, smoothing)
        if not pts_local:
            return np.zeros((0, 2), dtype=np.float64)
        return c.points_to_full(np.asarray([(p[0], p[1]) for p in pts_local]))
    raise ToolError(f"A {shape} region is not supported")


_RADIAL_SHAPES = ("circle", "annulus", "polygon", "composite")


def _refined_points(ctx: ToolContext, image: np.ndarray, region: dict[str, Any], center: tuple[float, float]) -> np.ndarray | None:
    """重掃精修：擬合中心偏離掃描原點 0.5px 以上時，從擬合中心再掃一次（掃描線與邊緣垂直、多邊形套用極性）。"""
    if not ctx.flag("refine", True) or region.get("shape") not in _RADIAL_SHAPES:
        return None
    ox, oy = region_center(region)
    if math.hypot(center[0] - ox, center[1] - oy) <= 0.5:
        return None
    return _region_edge_points(ctx, image, region, origin=center)


_EDGE_PARAMS = [
    Param("polarity", "Edge polarity", kind="select", default="any", options=POLARITY_OPTIONS, teach=True),
    Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, teach=True),
    Param("num_rays", "Scan lines", kind="number", default=36, minimum=6, maximum=720, help_text="Radial scan lines for a circle, ring or polygon; calipers for a rectangle."),
    Param("edge_select", "Which edge", kind="select", default="strongest", options=_EDGE_SELECT_OPTIONS),
    Param("refine", "Rescan refine", kind="boolean", default=True, group="Advanced", help_text="Rescan from the fitted centre after fitting: noticeably more accurate for an off-centre or polygon ROI."),
    Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
]


def _arc_span(angles: np.ndarray) -> tuple[float, float]:
    """從一組角度（度）找出它們覆蓋的圓弧：以最大空隙為缺口，回傳 (起角, 終角)，逆時針（影像座標）方向。"""
    a = np.sort(np.mod(angles, 360.0))
    if len(a) == 1:
        return float(a[0]), float(a[0])
    gaps = np.diff(np.r_[a, a[0] + 360.0])
    if gaps.max() < 2.0 * 360.0 / len(a):
        return 0.0, 360.0  # 沒有明顯缺口：整圈
    i = int(gaps.argmax())
    start = float(a[(i + 1) % len(a)])
    end = float(a[i])
    if end < start:
        end += 360.0
    return start, end


class FitArcTool(Tool):
    key = "fit_arc"
    label = "Fit arc"
    description = "Finds edge points in the region and fits an arc by least squares, optionally with RANSAC: the radius and centre of a fillet or a rim."
    category = "measure"
    icon = "Spline"
    params = [
        Param("roi", "Region", kind="roi", required=True, shapes=["annulus", "polygon", "rotated_rect", "circle", "rect"], help_text="Circle, ring or polygon: scan radially outwards from the centre. Rectangle: place calipers along the long side."),
        *_EDGE_PARAMS,
        Param("ransac", "RANSAC outlier rejection", kind="boolean", default=True),
        Param("ransac_tol", "RANSAC tolerance", kind="number", default=2, minimum=0.5, maximum=50, unit="px", group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        Port("radius", "Radius", "number"), Port("cx", "Centre X", "number"), Port("cy", "Centre Y", "number"),
        Port("residual_rms", "Residual RMS", "number"), Port("points", "Edge points", "points"),
        Port("start_angle", "Start angle", "number"), Port("end_angle", "End angle", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        pts = _region_edge_points(ctx, image, region)
        overlays = [region_overlay(region, label="arc roi")]
        nan = float("nan")
        ng = {"radius": nan, "cx": nan, "cy": nan, "residual_rms": nan, "points": pts.round(2).tolist(), "start_angle": nan, "end_angle": nan}
        if len(pts) < 3:
            return Result(outputs=ng, overlays=overlays, status="ng", message=f"Too few edge points ({len(pts)})")
        use_ransac, tol = ctx.flag("ransac", True), ctx.number("ransac_tol", 2)
        circle, inliers = fit_circle_points(pts, use_ransac, tol)
        if circle is not None:
            pts2 = _refined_points(ctx, image, region, (circle[0], circle[1]))
            if pts2 is not None and len(pts2) >= 3:
                circle2, inliers2 = fit_circle_points(pts2, use_ransac, tol)
                if circle2 is not None and int(inliers2.sum()) >= max(3, int(0.5 * inliers.sum())):
                    pts, circle, inliers = pts2, circle2, inliers2
        if circle is None:
            return Result(outputs=ng, overlays=overlays, status="ng", message="Fit failed")
        ng["points"] = pts.round(2).tolist()
        cx, cy, r = circle
        good = pts[inliers]
        resid = np.hypot(good[:, 0] - cx, good[:, 1] - cy) - r
        rms = float(np.sqrt((resid**2).mean())) if len(good) else nan
        start, end = _arc_span(np.degrees(np.arctan2(good[:, 1] - cy, good[:, 0] - cx)))
        arc = [[cx + r * math.cos(math.radians(t)), cy + r * math.sin(math.radians(t))] for t in np.linspace(start, end, 48)]
        overlays += [
            {"kind": "points", "points": good.round(2).tolist(), "color": "#22c55e"},
            {"kind": "points", "points": pts[~inliers].round(2).tolist(), "color": "#ef4444"},
            {"kind": "polyline", "points": arc, "color": "#22c55e", "width": 2, "label": f"R={r:.2f}"},
            {"kind": "point", "x": cx, "y": cy, "color": "#f59e0b"},
        ]
        return Result(
            outputs={"radius": r, "cx": cx, "cy": cy, "residual_rms": rms, "points": pts.round(2).tolist(), "start_angle": start, "end_angle": end},
            overlays=overlays, message=f"R={r:.2f}px centre ({cx:.1f}, {cy:.1f}), {int(inliers.sum())}/{len(pts)} points, RMS {rms:.2f}px, {start:.0f}°→{end:.0f}°",
        )


def _fit_ellipse(pts: np.ndarray) -> tuple[float, float, float, float, float] | None:
    """橢圓擬合：Direct（Fitzgibbon）對部分弧的偏差遠小於 cv2.fitEllipse 的最小平方版；失敗才退回。回傳 (cx, cy, w, h, angle)。"""
    arr = pts.astype(np.float32)
    for fn in (cv2.fitEllipseDirect, cv2.fitEllipse):
        try:
            (cx, cy), (w, h), ang = fn(arr)
        except cv2.error:
            continue
        if all(np.isfinite([cx, cy, w, h, ang])) and w > 0 and h > 0:
            return float(cx), float(cy), float(w), float(h), float(ang)
    return None


class FitEllipseTool(Tool):
    key = "fit_ellipse"
    label = "Fit ellipse"
    description = "Finds edge points in the region and fits an ellipse by direct least squares. Roundness is the minor axis over the major one (1 is a perfect circle) — the way to measure how oval a rim is."
    category = "measure"
    icon = "Egg"
    params = [
        Param("roi", "Region", kind="roi", required=True, shapes=["annulus", "circle", "polygon", "rotated_rect", "rect"]),
        *_EDGE_PARAMS,
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        Port("cx", "Centre X", "number"), Port("cy", "Centre Y", "number"),
        Port("a", "Semi-major axis", "number"), Port("b", "Semi-minor axis", "number"), Port("angle", "Major axis angle", "number"),
        Port("roundness", "Roundness b/a", "number"), Port("residual_rms", "Residual RMS", "number"), Port("points", "Edge points", "points"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        pts = _region_edge_points(ctx, image, region)
        overlays = [region_overlay(region, label="ellipse roi")]
        nan = float("nan")
        ng = {"cx": nan, "cy": nan, "a": nan, "b": nan, "angle": nan, "roundness": nan, "residual_rms": nan, "points": pts.round(2).tolist()}
        if len(pts) < 5:
            return Result(outputs=ng, overlays=overlays, status="ng", message=f"Too few edge points ({len(pts)}; an ellipse needs at least 5)")
        fitted = _fit_ellipse(pts)
        if fitted is not None:
            pts2 = _refined_points(ctx, image, region, (fitted[0], fitted[1]))
            if pts2 is not None and len(pts2) >= max(5, len(pts) // 2):
                fitted2 = _fit_ellipse(pts2)
                if fitted2 is not None:
                    pts, fitted = pts2, fitted2
        if fitted is None:
            return Result(outputs=ng, overlays=overlays, status="ng", message="Fit failed")
        ng["points"] = pts.round(2).tolist()
        cx, cy, w, h, ang = fitted
        # fitEllipse 的 angle 是 w 軸方向；長半軸取兩者較大者，角度跟著調整。
        if w >= h:
            a, b, angle = w / 2, h / 2, float(ang)
        else:
            a, b, angle = h / 2, w / 2, float(ang) + 90.0
        angle = (angle + 90) % 180 - 90
        # 殘差：把點轉到橢圓座標，沿徑向的距離 |ρ(1 − 1/s)|，s = sqrt((x/a)²+(y/b)²)
        t = math.radians(angle)
        dx, dy = pts[:, 0] - cx, pts[:, 1] - cy
        u = dx * math.cos(t) + dy * math.sin(t)
        v = -dx * math.sin(t) + dy * math.cos(t)
        s = np.hypot(u / a, v / b)
        rho = np.hypot(u, v)
        resid = np.where(s > 1e-9, rho * np.abs(1 - 1 / np.maximum(s, 1e-9)), rho)
        rms = float(np.sqrt((resid**2).mean()))
        roundness = float(b / a) if a > 0 else nan
        overlays += [
            {"kind": "points", "points": pts.round(2).tolist(), "color": "#22c55e"},
            {"kind": "polygon", "points": [[cx + a * math.cos(p) * math.cos(t) - b * math.sin(p) * math.sin(t), cy + a * math.cos(p) * math.sin(t) + b * math.sin(p) * math.cos(t)] for p in np.linspace(0, 2 * math.pi, 72, endpoint=False)], "color": "#22c55e", "width": 2, "label": f"b/a={roundness:.3f}"},
            {"kind": "line", "x1": cx - a * math.cos(t), "y1": cy - a * math.sin(t), "x2": cx + a * math.cos(t), "y2": cy + a * math.sin(t), "color": "#f59e0b"},
            {"kind": "point", "x": float(cx), "y": float(cy), "color": "#f59e0b"},
        ]
        return Result(
            outputs={"cx": float(cx), "cy": float(cy), "a": float(a), "b": float(b), "angle": angle, "roundness": roundness, "residual_rms": rms, "points": pts.round(2).tolist()},
            overlays=overlays, message=f"a={a:.2f} b={b:.2f} roundness {roundness:.3f}, {len(pts)} points, RMS {rms:.2f}px",
        )


def _band_profiles(crop_img: np.ndarray, num: int, *, along_long: bool = False) -> tuple[np.ndarray, np.ndarray, bool]:
    """沿長邊等距切 num 條帶，每條帶沿長邊平均成一條剖面（短邊方向）。回傳 (profiles, 帶中心, horizontal)。

    along_long=True（線段 ROI）則反過來：沿短邊切帶、剖面沿長邊，horizontal 回傳的是「剖面是否沿 x」。
    """
    h, w = crop_img.shape[:2]
    horizontal = w >= h
    if along_long:
        horizontal = not horizontal
    length = w if horizontal else h
    num = max(1, min(num, length))
    band = max(1, length // num)
    centers = np.linspace(band / 2, length - band / 2, num)
    profiles = []
    for cpos in centers:
        a, b = int(max(0, cpos - band / 2)), int(min(length, cpos + band / 2 + 1))
        sub = crop_img[:, a:b] if horizontal else crop_img[a:b, :]
        profiles.append(cv2.reduce(np.ascontiguousarray(sub), 1 if horizontal else 0, cv2.REDUCE_AVG, dtype=cv2.CV_64F).reshape(-1))
    return np.asarray(profiles, dtype=np.float32), centers, horizontal


def _as_wall_rect(region: dict[str, Any], band: float) -> dict[str, Any]:
    """line ROI → 以線為長邊、寬 band 的旋轉矩形；矩形類直接轉 rotated_rect。"""
    if region.get("shape") == "line":
        x1, y1, x2, y2 = float(region["x1"]), float(region["y1"]), float(region["x2"]), float(region["y2"])
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 3:
            raise ToolError("The segment is too short")
        return {"shape": "rotated_rect", "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2, "w": length, "h": max(3.0, band), "angle": math.degrees(math.atan2(y2 - y1, x2 - x1))}
    return _as_rotated_rect(region)


class WallThicknessTool(Tool):
    key = "wall_thickness"
    label = "Wall thickness"
    description = "Places calipers along a rectangle or line, each finding an outer-to-inner edge pair, and measures wall thickness in pixels with its minimum, maximum and mean."
    category = "measure"
    icon = "Layers"
    params = [
        Param("roi", "Region", kind="roi", required=True, shapes=["rotated_rect", "rect", "line"], help_text="The long side follows the wall; calipers scan across the short side from outside in (top to bottom or left to right for a rectangle). A line ROI uses the line as the long side."),
        Param("polarity", "Outer edge polarity", kind="select", default="any", options=POLARITY_OPTIONS, teach=True, help_text="How the grey level changes at the outer edge along the scan; the inner edge takes the opposite polarity automatically."),
        Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("num_calipers", "Calipers", kind="number", default=10, minimum=1, maximum=500),
        Param("max_thickness", "Max wall thickness", kind="number", default=0, minimum=0, unit="px", help_text="0 means no limit; when pairing, the inner edge may not be further than this from the outer one."),
        Param("band", "Scan band width", kind="number", default=10, minimum=3, unit="px", group="Advanced", help_text="For a line ROI, average this total width across the line."),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        Port("thickness", "Wall thickness (mean)", "number"), Port("min", "Min", "number"), Port("max", "Max", "number"),
        Port("mean", "Mean", "number"), Port("std", "Std dev", "number"), Port("count", "Valid calipers", "number"),
        Port("profile", "Thickness per caliper", "list"), Port("pairs", "Edge pair", "list"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        rr = _as_wall_rect(region, ctx.number("band", 10))
        c = crop(image, rr, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 3:
            raise ToolError("The region is too small or falls outside the image")
        profiles, centers, horizontal = _band_profiles(c.image, ctx.integer("num_calipers", 10), along_long=region.get("shape") == "line")
        polarity = ctx.param("polarity", "any")
        thr = ctx.number("edge_threshold", 20)
        max_t = ctx.number("max_thickness", 0)
        thick: list[float] = []
        pairs: list[list[list[float]]] = []
        for cpos, edges in zip(centers, find_edges_rows(profiles, "any", thr, ctx.integer("smoothing", 3))):
            outer = None
            for i, (pos, g) in enumerate(edges):
                if polarity == "dark_to_light" and g <= 0:
                    continue
                if polarity == "light_to_dark" and g >= 0:
                    continue
                # 內緣：第一個極性相反的邊緣（壁是一段亮或暗的帶）
                inner = next(((p2, g2) for p2, g2 in edges[i + 1 :] if (g2 > 0) != (g > 0) and (max_t <= 0 or p2 - pos <= max_t)), None)
                if inner is not None:
                    outer = (pos, g, inner[0])
                    break
            if outer is None:
                continue
            pos, _, pos2 = outer
            p1 = c.to_full(cpos, pos) if horizontal else c.to_full(pos, cpos)
            p2 = c.to_full(cpos, pos2) if horizontal else c.to_full(pos2, cpos)
            thick.append(float(pos2 - pos))
            pairs.append([[round(p1[0], 2), round(p1[1], 2)], [round(p2[0], 2), round(p2[1], 2)]])
        overlays = [region_overlay(region, label="wall")]
        nan = float("nan")
        if not thick:
            return Result(outputs={"thickness": nan, "min": nan, "max": nan, "mean": nan, "std": nan, "count": 0, "profile": [], "pairs": []},
                          overlays=overlays, status="ng", message="No edge pair was found")
        arr = np.asarray(thick)
        for (x1, y1), (x2, y2) in pairs:
            overlays.append({"kind": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": "#22c55e", "width": 2})
        overlays.append({"kind": "points", "points": [p[0] for p in pairs], "color": "#38bdf8"})
        overlays.append({"kind": "points", "points": [p[1] for p in pairs], "color": "#f59e0b"})
        mean = float(arr.mean())
        overlays.append({"kind": "text", "x": pairs[0][0][0], "y": pairs[0][0][1] - 8, "text": f"t={mean:.2f}px", "color": "#22c55e"})
        return Result(
            outputs={"thickness": mean, "min": float(arr.min()), "max": float(arr.max()), "mean": mean, "std": float(arr.std()), "count": len(thick),
                     "profile": [round(t, 2) for t in thick], "pairs": pairs},
            overlays=overlays, message=f"Wall thickness {mean:.2f}px (min {arr.min():.2f} / max {arr.max():.2f}, {len(thick)}/{len(centers)} calipers)",
        )


def _circle(value: Any, fallback: tuple[Any, Any, Any]) -> tuple[float, float, float] | None:
    """接受 {cx,cy,r} / [cx,cy,r] 或三個數值（find_circle 的 cx/cy/r）。"""
    if isinstance(value, dict):
        try:
            return float(value.get("cx", value.get("x"))), float(value.get("cy", value.get("y"))), float(value.get("r", value.get("radius", 0)))
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple, np.ndarray)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1]), float(value[2]) if len(value) > 2 else 0.0
        except (TypeError, ValueError):
            return None
    if fallback[0] is not None and fallback[1] is not None:
        try:
            return float(fallback[0]), float(fallback[1]), float(fallback[2] or 0)
        except (TypeError, ValueError):
            return None
    return None


class ConcentricityTool(Tool):
    key = "concentricity"
    label = "Concentricity"
    description = "The offset between the centres of two circles, such as an outer and an inner diameter. GD&T concentricity is twice the offset. Wire it to find_circle's cx/cy/r, or pass {cx,cy,r}."
    category = "measure"
    icon = "Target"
    params = [
        Param("max_deviation", "Max offset", kind="number", default=5, minimum=0, unit="px", teach=True, help_text="A centre distance above this takes the NG branch."),
    ]
    inputs = [
        Port("image", "Image", "image", required=False),
        Port("a", "Circle A", "any", required=False), Port("b", "Circle B", "any", required=False),
        Port("ax", "A centre X", "number", required=False), Port("ay", "A centre Y", "number", required=False), Port("ar", "A radius", "number", required=False),
        Port("bx", "B centre X", "number", required=False), Port("by", "B centre Y", "number", required=False), Port("br", "B radius", "number", required=False),
    ]
    outputs = [
        flow_out("ok", "Pass", "ok"), flow_out("ng", "Out of tolerance", "critical"),
        Port("deviation", "Offset", "number"), Port("dx", "dx", "number"), Port("dy", "dy", "number"),
        Port("concentricity", "Concentricity (2 × offset)", "number"), Port("verdict", "Verdict", "string"), Port("in_spec", "Pass", "bool"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        i = ctx.inputs
        a = _circle(i.get("a"), (i.get("ax"), i.get("ay"), i.get("ar")))
        b = _circle(i.get("b"), (i.get("bx"), i.get("by"), i.get("br")))
        if a is None or b is None:
            raise ToolError("Two circles are needed: wire a/b, or ax, ay, (ar), bx, by, (br)")
        nan = float("nan")
        if not all(np.isfinite([a[0], a[1], b[0], b[1]])):
            return Result(outputs={"deviation": nan, "dx": nan, "dy": nan, "concentricity": nan, "verdict": "ng", "in_spec": False},
                          branch="ng", status="ng", message="The input circle is not valid (the upstream step may have found nothing)")
        dx, dy = b[0] - a[0], b[1] - a[1]
        dev = math.hypot(dx, dy)
        max_dev = ctx.number("max_deviation", 5)
        ok = dev <= max_dev
        color = "#22c55e" if ok else "#ef4444"
        overlays = [
            {"kind": "circle", "cx": a[0], "cy": a[1], "r": a[2], "color": "#38bdf8", "width": 1, "label": "A"},
            {"kind": "circle", "cx": b[0], "cy": b[1], "r": b[2], "color": "#f59e0b", "width": 1, "label": "B"},
            {"kind": "point", "x": a[0], "y": a[1], "color": "#38bdf8"},
            {"kind": "point", "x": b[0], "y": b[1], "color": "#f59e0b"},
            {"kind": "line", "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1], "color": color, "width": 2, "label": f"{dev:.2f}px"},
        ]
        return Result(
            outputs={"deviation": dev, "dx": dx, "dy": dy, "concentricity": 2 * dev, "verdict": "ok" if ok else "ng", "in_spec": ok},
            overlays=overlays, branch="ok" if ok else "ng", status="ok" if ok else "ng",
            message=f"Centre offset {dev:.2f}px (dx {dx:.2f}, dy {dy:.2f}) {'≤' if ok else '>'} {max_dev:g}",
        )


def _line_from_fit(vx: float, vy: float, x0: float, y0: float, pts: np.ndarray) -> dict[str, float]:
    """把 (方向, 一點) 與其內點投影成線段端點。"""
    t = (pts[:, 0] - x0) * vx + (pts[:, 1] - y0) * vy
    t0, t1 = float(t.min()), float(t.max())
    x1, y1, x2, y2 = x0 + vx * t0, y0 + vy * t0, x0 + vx * t1, y0 + vy * t1
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "angle": math.degrees(math.atan2(y2 - y1, x2 - x1)), "length": t1 - t0}


class ChamferAngleTool(Tool):
    key = "chamfer_angle"
    label = "Chamfer"
    description = "Finds contour edge points with calipers inside a rotated rectangle, fits the first line with RANSAC, removes its inliers and fits the second; outputs the angle between them and the chamfer length."
    category = "measure"
    icon = "CornerDownRight"
    params = [
        Param("roi", "Region", kind="roi", required=True, shapes=["rotated_rect", "rect"], help_text="The long side follows the contour and must cover both the main edge and the chamfer; calipers scan across the short side."),
        Param("polarity", "Edge polarity", kind="select", default="any", options=POLARITY_OPTIONS, teach=True),
        Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("num_calipers", "Calipers", kind="number", default=40, minimum=4, maximum=500),
        Param("direction", "Which edge", kind="select", default="first", options=[{"value": "first", "label": "First"}, {"value": "last", "label": "Last"}, {"value": "strongest", "label": "Strongest"}]),
        Param("ransac_tol", "RANSAC tolerance", kind="number", default=1.5, minimum=0.3, maximum=50, unit="px", group="Advanced"),
        Param("min_points", "Min points for the second line", kind="number", default=3, minimum=2, maximum=100, group="Advanced"),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        Port("angle_deg", "Angle", "number"), Port("length", "Chamfer length", "number"),
        Port("line1", "Main edge", "any"), Port("line2", "Chamfer edge", "any"),
        Port("ix", "Intersection X", "number"), Port("iy", "Intersection Y", "number"), Port("points", "Edge points", "points"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        rr = _as_rotated_rect(region)
        c = crop(image, rr, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 3:
            raise ToolError("The region is too small or falls outside the image")
        pts_local, _ = caliper_points(c.image, ctx.integer("num_calipers", 40), ctx.param("polarity", "any"),
                                      ctx.number("edge_threshold", 20), ctx.param("direction", "first"), ctx.integer("smoothing", 3))
        overlays = [region_overlay(region, label="chamfer")]
        nan = float("nan")
        ng_out = {"angle_deg": nan, "length": nan, "line1": None, "line2": None, "ix": nan, "iy": nan}
        pts = c.points_to_full(np.asarray([(p[0], p[1]) for p in pts_local])) if pts_local else np.zeros((0, 2))
        min_pts = max(2, ctx.integer("min_points", 3))
        if len(pts) < 2 + min_pts:
            return Result(outputs={**ng_out, "points": pts.round(2).tolist()}, overlays=overlays, status="ng", message=f"Too few edge points ({len(pts)})")
        tol = ctx.number("ransac_tol", 1.5)
        first = fit_line_ransac(pts, tol=tol, iterations=300)
        if first is None:
            return Result(outputs={**ng_out, "points": pts.round(2).tolist()}, overlays=overlays, status="ng", message="Fitting the first line failed")
        (vx1, vy1, x01, y01), inl1 = first
        rest = pts[~inl1]
        if len(rest) < min_pts:
            return Result(outputs={**ng_out, "points": pts.round(2).tolist()}, overlays=overlays, status="ng", message=f"{len(rest)} points remain after removing the main edge; no chamfer was found")
        second = fit_line_ransac(rest, tol=tol, iterations=300, seed=1)
        if second is None:
            return Result(outputs={**ng_out, "points": pts.round(2).tolist()}, overlays=overlays, status="ng", message="Fitting the second line failed")
        (vx2, vy2, x02, y02), inl2 = second
        if int(inl2.sum()) < min_pts:
            return Result(outputs={**ng_out, "points": pts.round(2).tolist()}, overlays=overlays, status="ng", message=f"Too few inliers on the chamfer ({int(inl2.sum())})")
        line1 = _line_from_fit(vx1, vy1, x01, y01, pts[inl1])
        line2 = _line_from_fit(vx2, vy2, x02, y02, rest[inl2])
        diff = abs((line2["angle"] - line1["angle"] + 180) % 360 - 180) % 180
        angle = min(diff, 180 - diff)
        # 交點
        det = vx1 * vy2 - vy1 * vx2
        if abs(det) > 1e-9:
            t = ((x02 - x01) * vy2 - (y02 - y01) * vx2) / det
            ix, iy = x01 + vx1 * t, y01 + vy1 * t
        else:
            ix, iy = nan, nan
        overlays += [
            {"kind": "points", "points": pts[inl1].round(2).tolist(), "color": "#38bdf8"},
            {"kind": "points", "points": rest[inl2].round(2).tolist(), "color": "#22c55e"},
            {"kind": "points", "points": rest[~inl2].round(2).tolist(), "color": "#ef4444"},
            {"kind": "line", "x1": line1["x1"], "y1": line1["y1"], "x2": line1["x2"], "y2": line1["y2"], "color": "#38bdf8", "width": 2, "label": "Main edge"},
            {"kind": "line", "x1": line2["x1"], "y1": line2["y1"], "x2": line2["x2"], "y2": line2["y2"], "color": "#22c55e", "width": 2, "label": f"{angle:.1f}° L={line2['length']:.1f}"},
        ]
        if np.isfinite(ix):
            overlays.append({"kind": "point", "x": ix, "y": iy, "color": "#f59e0b"})
        return Result(
            outputs={"angle_deg": angle, "length": line2["length"], "line1": line1, "line2": line2, "ix": ix, "iy": iy, "points": pts.round(2).tolist()},
            overlays=overlays, message=f"Chamfer {angle:.2f}°, length {line2['length']:.1f}px ({int(inl1.sum())} points on the main edge, {int(inl2.sum())} on the chamfer)",
        )


class ToleranceJudgeTool(Tool):
    key = "tolerance_judge"
    label = "Tolerance check"
    description = "Whether a measurement lies within nominal plus the upper and lower deviations. The verdict is written into run.outputs.tolerances together with the nominal, the limits and the drawing reference, ready for Cpk and traceability."
    category = "measure"
    icon = "ClipboardCheck"
    params = [
        Param("nominal", "Nominal", kind="number", required=True, default=0, teach=True),
        Param("upper_tol", "Upper deviation", kind="number", default=0.1, teach=True, help_text="Signed; the upper limit is nominal + this."),
        Param("lower_tol", "Lower deviation", kind="number", default=-0.1, teach=True, help_text="Signed, normally negative; the lower limit is nominal + this."),
        Param("unit", "Unit", kind="text", default="mm"),
        Param("spec_source", "Drawing reference", kind="text", default="", help_text="For example: drawing A-102, dimension ⌀ 12."),
        Param("name", "Dimension name", kind="text", default="", help_text="The name written into outputs.tolerances; blank uses the step's label."),
    ]
    inputs = [Port("value", "Measured", "number")]
    outputs = [
        flow_out("pass", "Pass", "ok"), flow_out("fail", "Out of tolerance", "critical"),
        Port("verdict", "Verdict", "string"), Port("deviation", "Deviation (value − nominal)", "number"), Port("in_spec", "Pass", "bool"),
        Port("nominal", "Nominal", "number"), Port("upper", "Upper", "number"), Port("lower", "Lower", "number"), Port("spec_source", "Drawing reference", "string"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        raw = ctx.inputs.get("value")
        try:
            v = float(raw)
        except (TypeError, ValueError):
            raise ToolError(f"The input is not a number: {raw!r}") from None
        nominal = ctx.number("nominal", 0)
        upper = nominal + ctx.number("upper_tol", 0.1)
        lower = nominal + ctx.number("lower_tol", -0.1)
        if lower > upper:
            lower, upper = upper, lower
        unit = str(ctx.param("unit", "mm") or "")
        source = str(ctx.param("spec_source", "") or "")
        name = str(ctx.param("name", "") or ctx.node.get("label") or ctx.node.get("id") or "")
        valid = math.isfinite(v)
        ok = valid and lower <= v <= upper
        deviation = v - nominal if valid else float("nan")
        entry = {"name": name, "value": v if valid else None, "nominal": nominal, "upper": upper, "lower": lower, "unit": unit, "spec_source": source, "in_spec": ok}
        outputs = dict(ctx.context.get("_outputs") or {})
        tolerances = [t for t in (outputs.get("tolerances") or []) if isinstance(t, dict) and t.get("name") != name]
        outputs["tolerances"] = tolerances + [entry]
        verdict = "pass" if ok else "fail"
        msg = (f"{v:.4g}{unit} deviation {deviation:+.4g} ({lower:.4g} to {upper:.4g}) -> {verdict.upper()}" if valid else f"The measurement is invalid ({raw!r}) -> FAIL")
        return Result(
            outputs={"verdict": verdict, "deviation": deviation, "in_spec": ok, "nominal": nominal, "upper": upper, "lower": lower, "spec_source": source},
            branch=verdict, status="ok" if ok else "ng", message=msg, context={"_outputs": outputs},
        )




class LineProfileTool(Tool):
    key = "line_profile"
    label = "Line profile"
    description = "Samples grey levels along a line or polyline and outputs the profile and its statistics: steps, bright and dark bands, scan-line defects."
    category = "measure"
    icon = "Activity"
    accepts = ("u8", "u16", "f32")
    params = [
        Param("roi", "Line", kind="roi", shapes=["line", "polyline"], required=True, teach=True),
        Param("samples", "Sample points", kind="number", default=0, minimum=0, maximum=10000, help_text="0 = one sample per pixel."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Line (dynamic)", "region", required=False)]
    outputs = [
        Port("values", "Profile values", "list"), Port("mean", "Mean", "number"), Port("std", "Std dev", "number"),
        Port("min", "Min", "number"), Port("max", "Max", "number"), Port("length", "Length", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        region = ctx.roi()
        if not region:
            raise ToolError("A line or polyline ROI is required")
        if region.get("shape") == "line":
            pts = [[float(region["x1"]), float(region["y1"])], [float(region["x2"]), float(region["y2"])]]
        elif region.get("shape") in ("polyline", "polygon"):
            pts = [[float(x), float(y)] for x, y in (region.get("points") or [])]
        else:
            raise ToolError(f"Line profile does not support a '{region.get('shape')}' ROI")
        if len(pts) < 2:
            raise ToolError("At least two points are needed")
        seg = np.diff(np.asarray(pts, dtype=np.float64), axis=0)
        seg_len = np.hypot(seg[:, 0], seg[:, 1])
        total = float(seg_len.sum())
        if total < 1:
            raise ToolError("The line has zero length")
        n = ctx.integer("samples", 0) or int(round(total))
        n = max(2, min(10000, n))
        # 沿折線等距取樣（雙線性）
        t = np.linspace(0.0, total, n)
        cum = np.concatenate([[0.0], np.cumsum(seg_len)])
        xs = np.interp(t, cum, [p[0] for p in pts])
        ys = np.interp(t, cum, [p[1] for p in pts])
        h, w = gray.shape[:2]
        maps_x = np.clip(xs, 0, w - 1).astype(np.float32).reshape(1, -1)
        maps_y = np.clip(ys, 0, h - 1).astype(np.float32).reshape(1, -1)
        values = cv2.remap(gray.astype(np.float32), maps_x, maps_y, cv2.INTER_LINEAR).reshape(-1)
        stats = {
            "values": [round(float(v), 3) for v in values],
            "mean": round(float(values.mean()), 3), "std": round(float(values.std()), 3),
            "min": round(float(values.min()), 3), "max": round(float(values.max()), 3),
            "length": round(total, 2),
        }
        overlays = [region_overlay(region, label=f"profile n={n}")]
        return Result(outputs=stats, overlays=overlays, message=f"{n} points, mean {stats['mean']:.1f}")


class ColorStatsTool(Tool):
    key = "color_stats"
    label = "Colour statistics"
    description = "Mean and standard deviation of RGB and HSV in the region, plus the dominant hue and mean colour, for colour verification and downstream logic."
    category = "measure"
    icon = "Palette"
    params = [Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect", "circle", "annulus", "polygon", "ellipse"], help_text="Leave blank for the whole image.")]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        Port("mean_r", "R mean", "number"), Port("mean_g", "G mean", "number"), Port("mean_b", "B mean", "number"),
        Port("mean_h", "H mean", "number"), Port("mean_s", "S mean", "number"), Port("mean_v", "V mean", "number"),
        Port("std_v", "V std dev", "number"), Port("hex", "Mean colour", "string"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        mask = c.mask if c.mask is not None else np.full(c.image.shape[:2], 255, np.uint8)
        sel = c.image[mask > 0]
        if not len(sel):
            raise ToolError("The region has no pixels")
        mean_bgr = sel.reshape(-1, 3).mean(axis=0)
        hsv = cv2.cvtColor(c.image, cv2.COLOR_BGR2HSV)
        hsel = hsv[mask > 0].reshape(-1, 3).astype(np.float32)
        # 色相是圓的：用向量平均（H 值域 0~179）
        ang = hsel[:, 0] / 180.0 * 2 * np.pi
        mean_h = float((np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) % (2 * np.pi)) / (2 * np.pi) * 180.0)
        outputs = {
            "mean_r": round(float(mean_bgr[2]), 1), "mean_g": round(float(mean_bgr[1]), 1), "mean_b": round(float(mean_bgr[0]), 1),
            "mean_h": round(mean_h, 1), "mean_s": round(float(hsel[:, 1].mean()), 1), "mean_v": round(float(hsel[:, 2].mean()), 1),
            "std_v": round(float(hsel[:, 2].std()), 2),
            "hex": "#%02x%02x%02x" % (int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0])),
        }
        overlays = [region_overlay(region, label=outputs["hex"])] if region else []
        return Result(outputs=outputs, overlays=overlays, message=f"{outputs['hex']} H{outputs['mean_h']:.0f}")


def _as_line(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, dict) and all(k in value for k in ("x1", "y1", "x2", "y2")):
        return float(value["x1"]), float(value["y1"]), float(value["x2"]), float(value["y2"])
    return None


def _as_point(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict) and "x" in value and "y" in value:
        return float(value["x"]), float(value["y"])
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# 幾何作圖（純函式：好測，AI 助手與其他工具也用得到）
# ---------------------------------------------------------------------------
#: 作圖產生的直線畫多長（線本身是無限長的，這只是拿來顯示與傳遞的一段）。
LINE_SPAN = 200.0


def _as_circle(value: Any) -> tuple[float, float, float] | None:
    """接受 {cx,cy,r}、{x,y,r} 或 region 的 circle。"""
    if not isinstance(value, dict):
        return None
    r = value.get("r", value.get("radius"))
    x = value.get("cx", value.get("x"))
    y = value.get("cy", value.get("y"))
    if r is None or x is None or y is None:
        return None
    try:
        return float(x), float(y), float(r)
    except (TypeError, ValueError):
        return None


def _line_dict(x1: float, y1: float, x2: float, y2: float) -> dict[str, float]:
    return {"x1": round(x1, 4), "y1": round(y1, 4), "x2": round(x2, 4), "y2": round(y2, 4)}


def _unit(line: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = line
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-9:
        raise ToolError("The line's two ends are the same point")
    return dx / length, dy / length


def line_through(px: float, py: float, ux: float, uy: float, span: float = LINE_SPAN) -> dict[str, float]:
    """過一點、方向為 (ux, uy) 的直線（畫成 ±span 的一段）。"""
    return _line_dict(px - ux * span, py - uy * span, px + ux * span, py + uy * span)


def parallel_line(line: tuple[float, float, float, float], *, through: tuple[float, float] | None = None, offset: float = 0.0) -> dict[str, float]:
    """平行線：給點就過那個點，否則往法線方向平移 offset（正值＝法線 (−uy, ux) 的方向）。"""
    ux, uy = _unit(line)
    if through is not None:
        return line_through(through[0], through[1], ux, uy)
    cx, cy = (line[0] + line[2]) / 2, (line[1] + line[3]) / 2
    return line_through(cx - uy * offset, cy + ux * offset, ux, uy)


def perpendicular_line(line: tuple[float, float, float, float], through: tuple[float, float]) -> dict[str, float]:
    """過一點、與這條線垂直的直線。"""
    ux, uy = _unit(line)
    return line_through(through[0], through[1], -uy, ux)


def perpendicular_bisector(a: tuple[float, float], b: tuple[float, float]) -> dict[str, float]:
    """兩點的中垂線。"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if math.hypot(dx, dy) < 1e-9:
        raise ToolError("The two points are the same")
    return perpendicular_line((a[0], a[1], b[0], b[1]), ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))


def bisector_line(la: tuple[float, float, float, float], lb: tuple[float, float, float, float]) -> dict[str, float]:
    """兩條線的角平分線（過交點；平行時退回中線）。"""
    ua = _unit(la)
    ub = _unit(lb)
    cross = ua[0] * ub[1] - ua[1] * ub[0]
    if abs(cross) < 1e-9:
        return median_line(la, lb)
    point = intersect_lines(la, lb)
    if point is None:
        return median_line(la, lb)
    # 兩個單位方向相加＝夾角的角平分線方向（方向相反時取差）
    sign = 1.0 if ua[0] * ub[0] + ua[1] * ub[1] >= 0 else -1.0
    dx, dy = ua[0] + sign * ub[0], ua[1] + sign * ub[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        raise ToolError("The two lines have no bisector")
    return line_through(point[0], point[1], dx / length, dy / length)


def median_line(la: tuple[float, float, float, float], lb: tuple[float, float, float, float]) -> dict[str, float]:
    """兩條（大致平行的）線的中線：方向取平均，位置取兩線中點的中點。"""
    ua, ub = _unit(la), _unit(lb)
    sign = 1.0 if ua[0] * ub[0] + ua[1] * ub[1] >= 0 else -1.0
    dx, dy = ua[0] + sign * ub[0], ua[1] + sign * ub[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        raise ToolError("The two lines point in opposite directions")
    mx = (la[0] + la[2] + lb[0] + lb[2]) / 4
    my = (la[1] + la[3] + lb[1] + lb[3]) / 4
    return line_through(mx, my, dx / length, dy / length)


def intersect_lines(la: tuple[float, float, float, float], lb: tuple[float, float, float, float]) -> tuple[float, float] | None:
    """兩條線的交點；平行回 None。"""
    x1, y1, x2, y2 = la
    x3, y3, x4, y4 = lb
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    return px, py


def circle_from_three(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> dict[str, float]:
    """三點定圓（外心）。三點共線時 ToolError。"""
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        raise ToolError("The three points are on one line, so no circle passes through them")
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return {"cx": round(ux, 4), "cy": round(uy, 4), "r": round(math.hypot(ax - ux, ay - uy), 4)}


def rotate_point(point: tuple[float, float], pivot: tuple[float, float], degrees: float) -> tuple[float, float]:
    """繞一點旋轉（**角度正值＝畫面順時針**，與平台其他地方同向）。"""
    rad = math.radians(degrees)
    cos, sin = math.cos(rad), math.sin(rad)
    dx, dy = point[0] - pivot[0], point[1] - pivot[1]
    return pivot[0] + dx * cos - dy * sin, pivot[1] + dx * sin + dy * cos


def line_angle(line: tuple[float, float, float, float]) -> float:
    """直線的角度（度，畫面順時針為正，範圍 −90~90）。"""
    ux, uy = _unit(line)
    return (math.degrees(math.atan2(uy, ux)) + 90) % 180 - 90


def point_to_line(point: tuple[float, float], line: tuple[float, float, float, float]) -> tuple[float, float, float]:
    """點到直線：回 (垂足 x, 垂足 y, 距離)。"""
    x1, y1, x2, y2 = line
    dx, dy = x2 - x1, y2 - y1
    norm = dx * dx + dy * dy
    if norm < 1e-9:
        raise ToolError("The line's two ends are the same point")
    t = ((point[0] - x1) * dx + (point[1] - y1) * dy) / norm
    px, py = x1 + t * dx, y1 + t * dy
    return px, py, math.hypot(point[0] - px, point[1] - py)


class GeometryTool(Tool):
    key = "geometry"
    label = "Geometry"
    description = (
        "Works out the geometry the drawing calls for but the picture does not show: where two lines meet, the perpendicular "
        "distance from a point to a line, a line parallel or perpendicular to another, the line halfway between two edges, the "
        "bisector of a corner, the circle through three points, or a point turned about another. Wire lines and points in from "
        "find-line, find-circle or caliper; the line and circle outputs go straight into the next step."
    )
    category = "measure"
    icon = "Ruler"
    params = [
        Param("mode", "Compute", kind="select", default="intersect", options=[
            {"value": "intersect", "label": "Where two lines meet"},
            {"value": "point_line", "label": "Perpendicular distance from a point to a line"},
            {"value": "midpoint", "label": "Midpoint of two points"},
            {"value": "project", "label": "Projection of a point onto a line"},
            {"value": "line_2pts", "label": "The line through two points"},
            {"value": "parallel", "label": "A line parallel to this one"},
            {"value": "perpendicular", "label": "A line at right angles to this one"},
            {"value": "perp_bisector", "label": "The line halfway between two points"},
            {"value": "median", "label": "The line halfway between two lines"},
            {"value": "bisector", "label": "The line that halves a corner"},
            {"value": "circle_3pts", "label": "The circle through three points"},
            {"value": "rotate", "label": "Turn a point about another"},
        ]),
        Param("offset", "Offset", kind="number", default=0, unit="px", teach=True,
              visible_when={"param": "mode", "in": ["parallel"]},
              help_text="How far to move the line sideways when no point is wired in. Positive is to the right of the line's direction."),
        Param("angle", "Angle", kind="number", default=0, unit="°", teach=True,
              visible_when={"param": "mode", "in": ["rotate"]},
              help_text="Clockwise on screen, like every other angle on the platform."),
    ]
    inputs = [
        Port("a", "A (line / point)", "any"),
        Port("b", "B (line / point)", "any", required=False),
        Port("c", "C (point)", "any", required=False),
    ]
    outputs = [
        Port("x", "X", "number"), Port("y", "Y", "number"), Port("distance", "Distance", "number"),
        Port("angle", "Angle", "number"), Port("line", "Line", "any"), Port("circle", "Circle", "any"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        mode = str(ctx.param("mode", "intersect"))
        a, b, c = ctx.inputs.get("a"), ctx.inputs.get("b"), ctx.inputs.get("c")
        blank = {"x": 0.0, "y": 0.0, "distance": 0.0, "angle": 0.0, "line": None, "circle": None}

        if mode == "intersect":
            la, lb = _need_line(a, "A"), _need_line(b, "B")
            point = intersect_lines(la, lb)
            if point is None:
                return Result(status="ng", message="The lines are parallel and never meet", outputs=blank)
            angle = abs(line_angle(la) - line_angle(lb))
            angle = min(angle, 180 - angle)
            return Result(outputs={**blank, "x": round(point[0], 2), "y": round(point[1], 2), "angle": round(angle, 3)},
                          overlays=[{"kind": "point", "x": point[0], "y": point[1], "label": "Intersection"}],
                          message=f"({point[0]:.1f}, {point[1]:.1f}), {angle:.2f}°")

        if mode == "midpoint":
            pa, pb = _need_point(a, "A"), _need_point(b, "B")
            mx, my = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
            d = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
            return Result(outputs={**blank, "x": round(mx, 2), "y": round(my, 2), "distance": round(d, 2)},
                          overlays=[{"kind": "point", "x": mx, "y": my, "label": "midpoint"}], message=f"({mx:.1f}, {my:.1f})")

        if mode == "line_2pts":
            pa, pb = _need_point(a, "A"), _need_point(b, "B")
            line = _line_dict(pa[0], pa[1], pb[0], pb[1])
            angle = line_angle((pa[0], pa[1], pb[0], pb[1]))
            return Result(outputs={**blank, "line": line, "angle": round(angle, 3), "x": round((pa[0] + pb[0]) / 2, 2), "y": round((pa[1] + pb[1]) / 2, 2),
                                   "distance": round(math.hypot(pb[0] - pa[0], pb[1] - pa[1]), 2)},
                          overlays=[{"kind": "line", **line, "label": f"{angle:.1f}°"}], message=f"{angle:.2f}°")

        if mode in ("parallel", "perpendicular"):
            la = _need_line(a, "A")
            through = _as_point(b)
            if mode == "perpendicular" and through is None:
                raise ToolError("Wire the point the line has to pass through into B")
            line = (parallel_line(la, through=through, offset=ctx.number("offset"))
                    if mode == "parallel" else perpendicular_line(la, through))
            return _line_result(line, blank)

        if mode == "perp_bisector":
            line = perpendicular_bisector(_need_point(a, "A"), _need_point(b, "B"))
            return _line_result(line, blank)

        if mode in ("median", "bisector"):
            la, lb = _need_line(a, "A"), _need_line(b, "B")
            line = median_line(la, lb) if mode == "median" else bisector_line(la, lb)
            return _line_result(line, blank)

        if mode == "circle_3pts":
            circle = circle_from_three(_need_point(a, "A"), _need_point(b, "B"), _need_point(c, "C"))
            return Result(outputs={**blank, "circle": circle, "x": circle["cx"], "y": circle["cy"], "distance": circle["r"]},
                          overlays=[{"kind": "circle", "cx": circle["cx"], "cy": circle["cy"], "r": circle["r"], "label": f"r={circle['r']:.2f}"}],
                          message=f"({circle['cx']:.1f}, {circle['cy']:.1f}) r={circle['r']:.2f}")

        if mode == "rotate":
            pa = _need_point(a, "A")
            pivot = _as_point(b) or (0.0, 0.0)
            degrees = ctx.number("angle")
            x, y = rotate_point(pa, pivot, degrees)
            return Result(outputs={**blank, "x": round(x, 3), "y": round(y, 3), "angle": degrees,
                                   "distance": round(math.hypot(x - pivot[0], y - pivot[1]), 3)},
                          overlays=[{"kind": "point", "x": pivot[0], "y": pivot[1], "color": "#38bdf8", "label": "pivot"},
                                    {"kind": "point", "x": x, "y": y, "label": f"{degrees:.1f}°"}],
                          message=f"({x:.1f}, {y:.1f})")

        # point_line / project：a=點、b=線（接反了也行）
        pa, lb = _as_point(a), _as_line(b)
        if not pa and _as_point(b) and _as_line(a):
            pa, lb = _as_point(b), _as_line(a)
        if not pa or not lb:
            raise ToolError("A point and a line are needed")
        px, py, d = point_to_line(pa, lb)
        overlays = [{"kind": "line", "x1": pa[0], "y1": pa[1], "x2": px, "y2": py, "label": f"{d:.1f}px"}]
        return Result(outputs={**blank, "x": round(px, 2), "y": round(py, 2), "distance": round(d, 2)}, overlays=overlays,
                      message=f"Perpendicular distance {d:.2f}px" if mode == "point_line" else f"projection ({px:.1f}, {py:.1f})")


def _need_line(value: Any, which: str) -> tuple[float, float, float, float]:
    line = _as_line(value)
    if line is None:
        raise ToolError(f"Input {which} has to be a line {{x1,y1,x2,y2}} — wire it from find-line or the line output of another geometry step")
    return line


def _need_point(value: Any, which: str) -> tuple[float, float]:
    point = _as_point(value)
    if point is None:
        raise ToolError(f"Input {which} has to be a point [x, y] — wire it from find-circle, caliper or a blob centre")
    return point


def _line_result(line: dict[str, float], blank: dict[str, Any]) -> Result:
    angle = line_angle((line["x1"], line["y1"], line["x2"], line["y2"]))
    return Result(
        outputs={**blank, "line": line, "angle": round(angle, 3),
                 "x": round((line["x1"] + line["x2"]) / 2, 2), "y": round((line["y1"] + line["y2"]) / 2, 2)},
        overlays=[{"kind": "line", **line, "color": "#22c55e", "label": f"{angle:.1f}°"}],
        message=f"{angle:.2f}°",
    )


class PointsMergeTool(Tool):
    key = "points_merge"
    label = "Point set"
    description = (
        "Collects points from several steps into one set, so a single fit or measurement covers the lot: the edge points of "
        "four calipers fitted to one line, the hole centres of a whole row. Each input takes one point or a list of points."
    )
    category = "measure"
    icon = "Spline"
    params = [
        Param("unique", "Drop repeats", kind="boolean", default=False, help_text="Points closer together than a tenth of a pixel count as one."),
    ]
    inputs = [
        Port("a", "A", "any"), Port("b", "B", "any", required=False),
        Port("c", "C", "any", required=False), Port("d", "D", "any", required=False),
        Port("image", "Image", "image", required=False),
    ]
    outputs = [Port("points", "Points", "points"), Port("count", "Count", "number"),
               Port("cx", "Centre X", "number"), Port("cy", "Centre Y", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        points: list[list[float]] = []
        for key in ("a", "b", "c", "d"):
            points += _point_list(ctx.inputs.get(key))
        if ctx.flag("unique"):
            seen: list[list[float]] = []
            for p in points:
                if not any(abs(p[0] - q[0]) < 0.1 and abs(p[1] - q[1]) < 0.1 for q in seen):
                    seen.append(p)
            points = seen
        if not points:
            return Result(status="ng", outputs={"points": [], "count": 0, "cx": float("nan"), "cy": float("nan")},
                          message="No points came in (the steps above may have found nothing)")
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        return Result(
            outputs={"points": points, "count": len(points), "cx": round(cx, 3), "cy": round(cy, 3)},
            overlays=[{"kind": "points", "points": points, "color": "#22c55e"},
                      {"kind": "point", "x": cx, "y": cy, "color": "#f59e0b", "label": "centre"}],
            message=f"{len(points)} points, centre ({cx:.1f}, {cy:.1f})",
        )


def _point_list(value: Any) -> list[list[float]]:
    """一個點、一串點、或帶 x/y 的字典清單 → [[x, y], ...]（認不得的安靜略過）。"""
    if value is None:
        return []
    single = _as_point(value)
    if single is not None and not isinstance(value, (list, tuple, np.ndarray)):
        return [[single[0], single[1]]]
    out: list[list[float]] = []
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1, 2) if value.ndim >= 2 and value.shape[-1] == 2 else None
        return [[float(x), float(y)] for x, y in flat] if flat is not None else []
    if isinstance(value, (list, tuple)):
        if single is not None and all(isinstance(v, (int, float, np.floating, np.integer)) for v in value[:2]):
            return [[single[0], single[1]]]
        for item in value:
            out += _point_list(item)
    return out


class ToWorldTool(Tool):
    key = "to_world"
    label = "Real-world coordinates"
    description = (
        "Turns pixel positions into the coordinates the machine works in: millimetres on the table, or the numbers a robot "
        "expects. Wire a position in and read X and Y out; lengths and angles are converted with the same calibration."
    )
    category = "measure"
    icon = "Axis3d"
    params = [
        Param("calibration", "Calibration", kind="asset", accept="calibration", required=True,
              help_text="Made on the Calibration page. Teach it once per station; every flow follows."),
        Param("decimals", "Decimals", kind="number", default=3, minimum=0, maximum=6, step=1, group="advanced"),
    ]
    inputs = [
        Port("points", "Points", "points", required=False),
        Port("x", "X (pixels)", "number", required=False), Port("y", "Y (pixels)", "number", required=False),
        Port("value", "Pixel length", "number", required=False),
        Port("angle", "Angle (image)", "number", required=False),
    ]
    outputs = [
        Port("points_world", "Points (real world)", "points"),
        Port("x", "X", "number"), Port("y", "Y", "number"),
        Port("length", "Length", "number"), Port("angle", "Angle (real world)", "number"),
        Port("scale", "Scale", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        payload = read_calibration(ctx)
        world = payload.get("world")
        if not world:
            raise ToolError("That calibration only corrects the lens: add a board, a known distance or robot points to get coordinates")
        matrix = world["matrix"]
        unit = payload.get("unit", "mm")
        digits = max(0, min(6, ctx.integer("decimals", 3)))

        pts = ctx.inputs.get("points")
        value = ctx.inputs.get("value")
        angle_in = ctx.inputs.get("angle")
        px_x, px_y = ctx.inputs.get("x"), ctx.inputs.get("y")
        if pts is None and px_x is not None and px_y is not None:
            # 單點以 x／y 數值埠進來（find_circle.cx/cy、shape_match.best_x/best_y）
            try:
                pts = [[float(px_x), float(px_y)]]
            except (TypeError, ValueError):
                raise ToolError("x and y must be numbers") from None
        if pts is None and value is None and angle_in is None:
            raise ToolError("No input: wire points (or x and y), a pixel length or an angle")

        outputs: dict[str, Any] = {"scale": float(world.get("mm_per_px") or 0)}
        overlays: list[dict[str, Any]] = []
        parts: list[str] = []
        centre: tuple[float, float] | None = None
        if pts is not None:
            src = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
            mapped = calib.apply(matrix, src)
            outputs["points_world"] = mapped.tolist()
            if len(mapped):
                centre = (float(src[0, 0]), float(src[0, 1]))
                outputs["x"], outputs["y"] = float(mapped[0, 0]), float(mapped[0, 1])
                parts.append(f"({outputs['x']:.{digits}f}, {outputs['y']:.{digits}f}) {unit}")
                # 標記畫在輸入影像的全圖座標上，文字寫世界座標——現場一眼就能對照
                for i in range(min(len(src), 32)):
                    overlays.append({"kind": "point", "x": float(src[i, 0]), "y": float(src[i, 1]), "color": "#22c55e",
                                     "label": f"{mapped[i, 0]:.{digits}f}, {mapped[i, 1]:.{digits}f}"})
        if value is not None:
            try:
                px_len = float(value)
            except (TypeError, ValueError):
                raise ToolError(f"The pixel length is not a number: {value!r}") from None
            at = centre if centre is not None else _image_centre(ctx)
            outputs["length"] = px_len * calib.scale_at(matrix, at)
            parts.append(f"{outputs['length']:.{digits}f} {unit}")
        if angle_in is not None:
            try:
                deg = float(angle_in)
            except (TypeError, ValueError):
                raise ToolError(f"The angle is not a number: {angle_in!r}") from None
            at = centre if centre is not None else _image_centre(ctx)
            outputs["angle"] = calib.angle_to_world(matrix, deg, at)
            parts.append(f"{outputs['angle']:.2f}°")
        return Result(outputs=outputs, overlays=overlays, message=" · ".join(parts) or "no values")


def _image_centre(ctx: ToolContext) -> tuple[float, float]:
    """沒有具體位置時用影像中心估比例（透視標定下比例會隨位置變）。"""
    image = ctx.image("_image") if ctx.inputs.get("_image") is not None else None
    if image is None:
        image = ctx.image("image")
    if image is None:
        return (0.0, 0.0)
    h, w = image.shape[:2]
    return (w / 2.0, h / 2.0)


TOOLS = [
    CaliperTool(), DistanceTool(), AngleTool(), IntensityTool(), CalibrationTool(), HistogramTool(), ToWorldTool(),
    FitArcTool(), FitEllipseTool(), WallThicknessTool(), ConcentricityTool(), ChamferAngleTool(), ToleranceJudgeTool(),
    LineProfileTool(), ColorStatsTool(), GeometryTool(), PointsMergeTool(),
]
