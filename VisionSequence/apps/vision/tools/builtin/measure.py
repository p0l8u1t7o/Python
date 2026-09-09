"""量測工具：卡尺、距離、夾角、灰階統計、像素校正、直方圖；杯件量測：圓弧／橢圓擬合、壁厚、同心度、倒角、公差判定。"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from apps.vision import calib
from apps.vision.tools import accel, defects
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.physical import CALIBRATION_PARAM, world_outputs, read_mapping
from apps.vision.tools.builtin.preprocess import read_calibration
from apps.vision.tools.builtin.locate import (
    CaliperHit,
    POLARITY_OPTIONS,
    _as_rotated_rect,
    arc_geometry,
    caliper_points,
    caliper_series,
    find_edges_1d,
    find_edges_rows,
    fit_circle_lsq,
    fit_points_line,
    hit_points,
    pick_pair,
    line_geometry,
    fit_circle_points,
    fit_line_ransac,
    radial_edge_points,
    smooth_profile,
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


_CALIPER_SORT_OPTIONS = [
    {"value": "score", "label": "Score"},
    {"value": "position", "label": "Position"},
    {"value": "contrast", "label": "Contrast"},
]


def _pair_candidates(edges: list[tuple[float, float]], pair_polarity: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """依邊緣對極性產生所有可用候選，保留原始掃描方向順序。"""
    if pair_polarity == "any":
        return [(a, b) for i, a in enumerate(edges) for b in edges[i + 1 :]]
    first_positive = pair_polarity == "bright"
    return [(a, b) for a, b in zip(edges[:-1], edges[1:]) if (a[1] > 0) == first_positive and (b[1] > 0) != first_positive]


def _caliper_candidate_score(
    position: float,
    contrast: float,
    width: float,
    *,
    expected_position: float,
    position_weight: float,
    contrast_weight: float,
    expected_width: float,
    width_weight: float,
) -> float:
    """卡尺候選分數；0 權重時以對比作為排序分數。"""
    if position_weight == 0 and contrast_weight == 0 and width_weight == 0:
        return float(contrast)
    score = float(contrast_weight) * float(contrast)
    if expected_position > 0 and position_weight:
        score -= float(position_weight) * abs(float(position) - float(expected_position))
    if expected_width > 0 and width_weight:
        score -= float(width_weight) * abs(float(width) - float(expected_width))
    return float(score)


def _round_float(value: float, digits: int = 3) -> float | None:
    if not np.isfinite(value):
        return None
    return round(float(value), digits)


def _rect_long_profile(image: np.ndarray, region: dict[str, Any]) -> tuple[np.ndarray, Any, bool]:
    """矩形 ROI 擺正後沿長邊平均，回傳剖面、Crop 與長邊方向。"""
    rr = _as_rotated_rect(region)
    c = crop(image, rr, upright=True)
    if c.image.size == 0 or min(c.image.shape[:2]) < 2:
        raise ToolError("The region is too small or falls outside the image")
    h, w = c.image.shape[:2]
    horizontal = w >= h
    # cv2.reduce 以 double 累加再除，與舊版 CaliperTool 完全同一路徑。
    profile = cv2.reduce(np.ascontiguousarray(c.image), 0 if horizontal else 1, cv2.REDUCE_AVG, dtype=cv2.CV_64F).reshape(-1)
    return profile, c, horizontal


def _profile_peaks(profile: np.ndarray, polarity: str, min_prominence: float, min_distance: int, smoothing: int) -> list[dict[str, float | str]]:
    """在一維剖面找亮峰／暗峰，prominence 以左右谷值估計。"""
    raw = np.asarray(profile, dtype=np.float64)
    smooth = smooth_profile(raw, smoothing).astype(np.float64)
    if len(smooth) < 3:
        return []
    signs = [("bright", 1.0), ("dark", -1.0)] if polarity == "both" else [(polarity, 1.0 if polarity == "bright" else -1.0)]
    candidates: list[dict[str, float | str]] = []
    for name, sign in signs:
        signal = smooth * sign
        left = np.r_[-np.inf, signal[:-1]]
        right = np.r_[signal[1:], -np.inf]
        for i in np.where((signal >= left) & (signal > right))[0]:
            li = i
            while li > 0 and signal[li - 1] <= signal[li]:
                li -= 1
            ri = i
            while ri < len(signal) - 1 and signal[ri + 1] <= signal[ri]:
                ri += 1
            base = max(float(signal[li]), float(signal[ri]))
            prominence = float(signal[i] - base)
            if prominence < min_prominence:
                continue
            pos = float(i)
            if 0 < i < len(signal) - 1:
                a, b, cval = signal[i - 1], signal[i], signal[i + 1]
                denom = a - 2 * b + cval
                if abs(denom) > 1e-9:
                    pos += float(np.clip(0.5 * (a - cval) / denom, -0.5, 0.5))
            half = float(signal[i] - prominence / 2.0)
            wl = float(i)
            while wl > li and signal[int(math.floor(wl))] > half:
                wl -= 1.0
            wr = float(i)
            while wr < ri and signal[int(math.ceil(wr))] > half:
                wr += 1.0
            candidates.append({
                "position": pos,
                "value": float(raw[int(np.clip(round(pos), 0, len(raw) - 1))]),
                "prominence": prominence,
                "width": max(0.0, wr - wl),
                "polarity": name,
            })
    candidates.sort(key=lambda item: float(item["prominence"]), reverse=True)
    kept: list[dict[str, float | str]] = []
    min_dist = max(0, int(min_distance))
    for item in candidates:
        if all(abs(float(item["position"]) - float(other["position"])) >= min_dist for other in kept):
            kept.append(item)
    return kept


class CaliperTool(Tool):
    key = "caliper"
    label = "Caliper"
    description = "Projects a grey profile along the long side of a rectangle, finds a pair of edges and measures the width in pixels."
    category = "measure"
    icon = "Ruler"
    params = [
        CALIBRATION_PARAM,
        Param("roi", "Region", kind="roi", required=True, shapes=["rotated_rect", "rect"], help_text="Scans along the long side, averaging across the short side to beat noise."),
        Param("polarity", "Edge polarity", kind="select", default="any", options=POLARITY_OPTIONS, teach=True),
        Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("max_results", "Max results", kind="number", default=1, minimum=1, maximum=200,
              help_text="Returns the first N edge-pair candidates in edges. The single width and edge ports still use the first result."),
        Param("sort_by", "Sort by", kind="select", default="score", options=_CALIPER_SORT_OPTIONS,
              help_text="score uses contrast minus weighted position or width error; position is near-to-far along the scan; contrast is grey-level change per pixel."),
        Param("edge_pair", "Pick edge pair", kind="select", default="first_last", options=[
            {"value": "first_last", "label": "First and last"},
            {"value": "widest", "label": "Widest pair"},
            {"value": "narrowest", "label": "Narrowest adjacent pair"},
            {"value": "strongest", "label": "Two strongest"},
        ]),
        Param("pair_polarity", "Edge pair polarity", kind="select", default="any", options=[
            {"value": "any", "label": "Any"}, {"value": "bright", "label": "Bright band (dark to light, then light to dark)"}, {"value": "dark", "label": "Dark band (light to dark, then dark to light)"},
        ], help_text="Constrains the polarity order of a pair, so measuring a bright or dark bar does not latch onto a neighbouring noise edge."),
        Param("expected_position", "Expected position", kind="number", default=0, minimum=0, unit="px", teach=True,
              help_text="Expected candidate centre along the scan direction; 0 disables the position term."),
        Param("position_weight", "Position weight", kind="number", default=0, minimum=0,
              help_text="Score penalty per pixel away from expected_position."),
        Param("contrast_weight", "Contrast weight", kind="number", default=0, minimum=0,
              help_text="Score gain per grey-level-per-pixel of edge contrast. With all weights at 0, score falls back to contrast."),
        Param("expected_width", "Expected width", kind="number", default=0, minimum=0, unit="px", teach=True,
              help_text="Expected edge-pair width in px. Legacy single-result mode still uses it to pick the closest width; with width_weight > 0 it also contributes a score penalty per px of width error."),
        Param("width_weight", "Width weight", kind="number", default=0, minimum=0,
              help_text="Score penalty per pixel away from expected_width for edge-pair candidates."),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        Port("width_world", "Width (world)", "number"),
        Port("edge1_x_world", "Edge 1 X (world)", "number"),
        Port("edge1_y_world", "Edge 1 Y (world)", "number"),
        Port("edge2_x_world", "Edge 2 X (world)", "number"),
        Port("edge2_y_world", "Edge 2 Y (world)", "number"),
        Port("unit", "Unit", "string"),
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
        profile, c, horizontal = _rect_long_profile(image, region)
        h, w = c.image.shape[:2]
        edges = find_edges_1d(profile, ctx.param("polarity", "any"), ctx.number("edge_threshold", 20), ctx.integer("smoothing", 3))
        overlays = [region_overlay(region, label="caliper")]
        nan = float("nan")
        prof_list = np.round(profile, 1).tolist()
        if len(edges) < 2:
            return Result(outputs={"width": nan, "edge1_x": nan, "edge1_y": nan, "edge2_x": nan, "edge2_y": nan,
                                   "edges": [], "profile": prof_list},
                          overlays=overlays, status="ng", message=f"Fewer than two edges ({len(edges)})")
        sort_by = str(ctx.param("sort_by", "score"))
        max_results = max(1, ctx.integer("max_results", 1))
        expected_position = ctx.number("expected_position", 0)
        position_weight = ctx.number("position_weight", 0)
        contrast_weight = ctx.number("contrast_weight", 0)
        expected_width = ctx.number("expected_width", 0)
        width_weight = ctx.number("width_weight", 0)
        legacy_single = (
            max_results == 1
            and sort_by == "score"
            and expected_position <= 0
            and position_weight == 0
            and contrast_weight == 0
            and width_weight == 0
        )
        if legacy_single:
            pairs = [pick_pair(edges, ctx.param("edge_pair", "first_last"), ctx.param("pair_polarity", "any"), expected_width)]
        else:
            pairs = _pair_candidates(edges, ctx.param("pair_polarity", "any"))
        pairs = [p for p in pairs if p is not None]
        if not pairs:
            return Result(outputs={"width": nan, "edge1_x": nan, "edge1_y": nan, "edge2_x": nan, "edge2_y": nan,
                                   "edges": [], "profile": prof_list},
                          overlays=overlays, status="ng", message="No edge pair matches the polarity")
        mid = (h if horizontal else w) / 2

        def candidate(pair: tuple[tuple[float, float], tuple[float, float]]) -> dict[str, Any]:
            (p1, g1), (p2, g2) = pair
            position = (p1 + p2) / 2.0
            width = abs(p2 - p1)
            contrast = abs(g1) + abs(g2)
            score = _caliper_candidate_score(
                position, contrast, width,
                expected_position=expected_position,
                position_weight=position_weight,
                contrast_weight=contrast_weight,
                expected_width=expected_width,
                width_weight=width_weight,
            )
            if horizontal:
                e1, e2 = c.to_full(p1, mid), c.to_full(p2, mid)
            else:
                e1, e2 = c.to_full(mid, p1), c.to_full(mid, p2)
            return {
                "position": round(float(position), 3),
                "contrast": round(float(contrast), 3),
                "score": round(float(score), 3),
                "width": round(float(width), 3),
                "edge1_position": round(float(p1), 3),
                "edge1_contrast": round(float(g1), 3),
                "edge1_x": round(float(e1[0]), 3),
                "edge1_y": round(float(e1[1]), 3),
                "edge2_position": round(float(p2), 3),
                "edge2_contrast": round(float(g2), 3),
                "edge2_x": round(float(e2[0]), 3),
                "edge2_y": round(float(e2[1]), 3),
                "_pair": pair,
                "_points": (e1, e2),
            }

        candidates = [candidate(p) for p in pairs]
        if not legacy_single:
            if sort_by == "position":
                candidates.sort(key=lambda item: (item["position"], -item["score"]))
            elif sort_by == "contrast":
                candidates.sort(key=lambda item: (-item["contrast"], item["position"]))
            else:
                candidates.sort(key=lambda item: (-item["score"], item["position"]))
        candidates = candidates[:max_results]
        chosen = candidates[0]
        (p1, _), (p2, _) = chosen["_pair"]
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
                     "edges": [{k: v for k, v in item.items() if not k.startswith("_")} for item in candidates], "profile": prof_list,
                     **world_outputs(ctx, points={("edge1_x", "edge1_y"): e1, ("edge2_x", "edge2_y"): e2},
                                     lengths={"width": (width, ((e1[0] + e2[0]) / 2, (e1[1] + e2[1]) / 2))})},
            overlays=overlays, message=f"Width {width:.2f}px ({len(edges)} edges)",
        )


class PeakSearchTool(Tool):
    key = "peak_search"
    label = "Peak search"
    description = "Projects a grey profile along the long side of a rectangle and finds bright or dark peaks."
    category = "measure"
    icon = "Activity"
    params = [
        Param("roi", "Region", kind="roi", required=True, shapes=["rotated_rect", "rect"],
              help_text="Scans along the long side, averaging across the short side."),
        Param("polarity", "Peak polarity", kind="select", default="bright", options=[
            {"value": "bright", "label": "Bright peaks"},
            {"value": "dark", "label": "Dark peaks"},
            {"value": "both", "label": "Bright and dark peaks"},
        ], teach=True),
        Param("min_prominence", "Minimum prominence", kind="number", default=20, minimum=0, maximum=255, teach=True,
              help_text="Required peak height above the local baseline in grey levels."),
        Param("min_distance", "Minimum distance", kind="number", default=5, minimum=0, maximum=1000, unit="px"),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
        Param("max_results", "Max results", kind="number", default=10, minimum=1, maximum=1000),
        Param("sort_by", "Sort by", kind="select", default="position", options=[
            {"value": "position", "label": "Position"},
            {"value": "prominence", "label": "Prominence"},
            {"value": "value", "label": "Value"},
        ]),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("peaks", "Peaks", "list"), Port("count", "Count", "number"),
        Port("first_x", "First X", "number"), Port("first_y", "First Y", "number"),
        Port("first_position", "First position", "number"),
        Port("profile", "Profile", "list"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        profile, c, horizontal = _rect_long_profile(image, region)
        h, w = c.image.shape[:2]
        mid = (h if horizontal else w) / 2.0
        peaks = _profile_peaks(
            profile,
            str(ctx.param("polarity", "bright")),
            ctx.number("min_prominence", 20),
            ctx.integer("min_distance", 5),
            ctx.integer("smoothing", 3),
        )
        sort_by = str(ctx.param("sort_by", "position"))
        if sort_by == "prominence":
            peaks.sort(key=lambda item: (-float(item["prominence"]), float(item["position"])))
        elif sort_by == "value":
            peaks.sort(key=lambda item: (-float(item["value"]), float(item["position"])))
        else:
            peaks.sort(key=lambda item: float(item["position"]))
        max_results = max(1, ctx.integer("max_results", 10))
        out: list[dict[str, Any]] = []
        overlays = [region_overlay(region, label="peaks")]
        for item in peaks[:max_results]:
            pos = float(item["position"])
            x, y = c.to_full(pos, mid) if horizontal else c.to_full(mid, pos)
            peak = {
                "x": round(float(x), 3),
                "y": round(float(y), 3),
                "position": round(pos, 3),
                "value": round(float(item["value"]), 3),
                "prominence": round(float(item["prominence"]), 3),
                "width": round(float(item["width"]), 3),
            }
            if ctx.param("polarity", "bright") == "both":
                peak["polarity"] = item["polarity"]
            out.append(peak)
            overlays.append({"kind": "point", "x": x, "y": y, "color": "#22c55e", "label": f"{pos:.1f}"})
        if not out:
            nan = float("nan")
            return Result(
                outputs={"peaks": [], "count": 0, "first_x": nan, "first_y": nan, "first_position": nan,
                         "profile": np.round(profile, 1).tolist()},
                overlays=overlays,
                status="ng",
                branch="not_found",
                message="No peaks found",
            )
        first = out[0]
        return Result(
            outputs={"peaks": out, "count": len(out), "first_x": first["x"], "first_y": first["y"],
                     "first_position": first["position"], "profile": np.round(profile, 1).tolist()},
            overlays=overlays,
            branch="found",
            message=f"{len(out)} peaks",
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
        CALIBRATION_PARAM,
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
    outputs = [
        Port("distance_world", "Distance (world)", "number"), Port("unit", "Unit", "string"),
        Port("distance", "Distance", "number"), Port("dx", "dx", "number"), Port("dy", "dy", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        mode = str(ctx.param("mode", "euclid"))
        raw_a, raw_b = ctx.inputs.get("a"), ctx.inputs.get("b")
        shape_a, shape_b = _as_line(raw_a) or _as_circle(raw_a), _as_line(raw_b) or _as_circle(raw_b)
        if shape_a is not None or shape_b is not None:
            return _shape_distance(raw_a, raw_b, mode, ctx)
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
        return Result(outputs={"distance": d, "dx": dx, "dy": dy,
                               **world_outputs(ctx, lengths={"distance": (d, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))})}, overlays=overlays, message=f"{d:.2f}px")


def _shape_distance(raw_a: Any, raw_b: Any, mode: str, ctx: ToolContext) -> Result:
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
    return Result(outputs={"distance": d, "dx": dx, "dy": dy,
                           **world_outputs(ctx, lengths={"distance": (d, ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2))})}, overlays=overlays, message=f"{d:.2f}px")


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


SHARPNESS_METHODS = [
    {
        "value": "laplacian",
        "label": "Laplacian variance",
        "help_text": "General-purpose focus and motion-blur score. It reacts strongly to fine edges and texture.",
    },
    {
        "value": "gradient",
        "label": "Gradient energy",
        "help_text": "Tenengrad-style squared gradient energy. Use it when stable edges dominate the region.",
    },
    {
        "value": "autocorrelation",
        "label": "Autocorrelation drop",
        "help_text": "Compares one- and two-pixel neighbour correlation. Use it when sensor noise would otherwise lift edge-energy scores.",
    },
]


def _masked_values(image: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    return image.reshape(-1) if mask is None else image[mask > 0]


def _masked_stats(image: np.ndarray, mask: np.ndarray | None) -> tuple[float, float, int]:
    valid = int(image.size) if mask is None else int(cv2.countNonZero(mask))
    if valid <= 0:
        return 0.0, 0.0, 0
    mean, std = cv2.meanStdDev(np.ascontiguousarray(image), mask)
    return float(mean[0, 0]), float(std[0, 0] ** 2), valid


def _sharpness_noise(gray: np.ndarray, mask: np.ndarray | None) -> float:
    # 現場光量不足時，感測器雜訊會把高頻能量撐高，讓清晰度分數看起來比實際更好。
    # 這裡用 3x3 中值濾波後的殘差 MAD 估計獨立高頻雜訊，方便把雜訊與真正邊緣分開監看。
    med = accel.median_blur(np.ascontiguousarray(gray), 3)
    residual = gray.astype(np.float32, copy=False) - med.astype(np.float32, copy=False)
    vals = _masked_values(residual, mask)
    if vals.size == 0:
        return 0.0
    center = float(np.median(vals))
    mad = float(np.median(np.abs(vals - center)))
    return 1.4826 * mad


def _lag_covariance(delta: np.ndarray, dx: int, dy: int, mask: np.ndarray | None) -> float:
    h, w = delta.shape[:2]
    if w <= abs(dx) or h <= abs(dy):
        return 0.0
    a = delta[max(0, dy): h + min(0, dy), max(0, dx): w + min(0, dx)]
    b = delta[max(0, -dy): h - max(0, dy), max(0, -dx): w - max(0, dx)]
    if mask is not None:
        ma = mask[max(0, dy): h + min(0, dy), max(0, dx): w + min(0, dx)] > 0
        mb = mask[max(0, -dy): h - max(0, dy), max(0, -dx): w - max(0, dx)] > 0
        sel = ma & mb
        if not np.any(sel):
            return 0.0
        return float(np.mean(a[sel] * b[sel]))
    return float(np.mean(a * b))


def _sharpness_score(gray: np.ndarray, mask: np.ndarray | None, method: str, normalize: bool) -> float:
    mean, contrast, count = _masked_stats(gray, mask)
    if count < 9:
        raise ToolError("The region has too few pixels")
    src = np.ascontiguousarray(gray)
    if method == "laplacian":
        response = cv2.Laplacian(src, cv2.CV_16S, ksize=3)
        _, raw, _ = _masked_stats(response, mask)
        scale = contrast if normalize else 1.0
    elif method == "gradient":
        gx, gy = cv2.spatialGradient(src, ksize=3)
        energy = gx.astype(np.float32)
        np.multiply(energy, energy, out=energy)
        gy2 = gy.astype(np.float32)
        energy += gy2 * gy2
        raw = float(cv2.sumElems(energy)[0]) if mask is None else float(energy[mask > 0].sum())
        scale = count * contrast if normalize else 1.0
    elif method == "autocorrelation":
        # 自相關要看多個位移的協方差，會比單次卷積多幾趟陣列掃描；換來的是對獨立雜訊較不敏感。
        delta = src.astype(np.float32) - mean
        lag1 = _lag_covariance(delta, 1, 0, mask) + _lag_covariance(delta, 0, 1, mask)
        lag2 = _lag_covariance(delta, 2, 0, mask) + _lag_covariance(delta, 0, 2, mask)
        raw = max(0.0, lag1 - lag2)
        scale = 2.0 * contrast if normalize else 1.0
    else:
        raise ToolError("Unknown sharpness method")
    if normalize:
        return raw / max(scale, 1e-6)
    return raw


class SharpnessTool(Tool):
    key = "sharpness"
    label = "Sharpness"
    description = "Scores focus and motion blur in a region, with optional pass limits and a noise estimate."
    category = "measure"
    icon = "Focus"
    params = [
        Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon"], help_text="Leave blank for the whole image."),
        Param("method", "Method", kind="select", default="laplacian", options=SHARPNESS_METHODS,
              help_text="Laplacian variance is the general default; gradient energy suits stable edges; autocorrelation is less sensitive to random noise."),
        Param("normalize", "Normalize by contrast", kind="boolean", default=True,
              help_text="On, the score is per-pixel response energy divided by the region grey-level variance: px^-4 for Laplacian, px^-2 for gradient, and a unitless correlation drop for autocorrelation."),
        Param("min_score", "Minimum score", kind="number", default=0, minimum=0, teach=True,
              help_text="0 disables the lower pass limit. Scores below this take the NG branch."),
        Param("max_score", "Maximum score", kind="number", default=0, minimum=0, teach=True,
              help_text="0 disables the upper pass limit. Scores above this take the NG branch, useful when noise or over-sharpening raises the score."),
        Param("noise_estimate", "Estimate noise", kind="boolean", default=False,
              help_text="Also reports a robust high-frequency noise level. Low light can raise sharpness scores through noise instead of real detail."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        Port("score", "Score", "number"),
        Port("noise", "Noise", "number"),
        Port("method", "Method", "string"),
        flow_out("ok", "Pass", "ok"),
        flow_out("ng", "Out of range", "critical"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        method = str(ctx.param("method", "laplacian"))
        normalize = ctx.flag("normalize", True)
        score = _sharpness_score(c.image, c.mask, method, normalize)
        noise = _sharpness_noise(c.image, c.mask) if ctx.flag("noise_estimate", False) else None
        min_score = ctx.number("min_score", 0)
        max_score = ctx.number("max_score", 0)
        ok = (min_score <= 0 or score >= min_score) and (max_score <= 0 or score <= max_score)
        label = f"sharpness {score:.3g}"
        overlay = region_overlay(region, label=label) if region else {"kind": "rect", "x": 0, "y": 0, "w": image.shape[1], "h": image.shape[0], "color": "#38bdf8", "width": 1, "dash": True, "label": label}
        message = f"Score {score:.4g}"
        if noise is not None:
            message += f", noise {noise:.3g}"
        return Result(
            outputs={"score": score, "noise": noise, "method": method},
            overlays=[overlay],
            branch="ok" if ok else "ng",
            status="ok" if ok else "ng",
            message=message,
        )



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
        CALIBRATION_PARAM,
        Param("roi", "Region", kind="roi", required=True, shapes=["annulus", "polygon", "rotated_rect", "circle", "rect"], help_text="Circle, ring or polygon: scan radially outwards from the centre. Rectangle: place calipers along the long side."),
        *_EDGE_PARAMS,
        Param("ransac", "RANSAC outlier rejection", kind="boolean", default=True),
        Param("ransac_tol", "RANSAC tolerance", kind="number", default=2, minimum=0.5, maximum=50, unit="px", group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        Port("radius_world", "Radius (world)", "number"),
        Port("cx_world", "Centre X (world)", "number"),
        Port("cy_world", "Centre Y (world)", "number"),
        Port("start_angle_world", "Start Angle (world)", "number"),
        Port("end_angle_world", "End Angle (world)", "number"),
        Port("unit", "Unit", "string"),
        Port("radius", "Radius", "number"), Port("cx", "Centre X", "number"), Port("cy", "Centre Y", "number"),
        Port("residual_rms", "Residual RMS", "number"), Port("points", "Edge points", "points"),
        Port("start_angle", "Start angle", "number"), Port("end_angle", "End angle", "number"),
        Port("circle", "Circle", "any"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        pts = _region_edge_points(ctx, image, region)
        overlays = [region_overlay(region, label="arc roi")]
        nan = float("nan")
        ng = {"radius": nan, "cx": nan, "cy": nan, "residual_rms": nan, "points": pts.round(2).tolist(), "start_angle": nan, "end_angle": nan, "circle": None}
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
        chord_pts = good if len(good) >= 3 else pts
        span = float(np.hypot(*(chord_pts.max(axis=0) - chord_pts.min(axis=0)))) + 1.0
        # 弓高（sagitta）：內點的跨距當弦長，圓在弦中點鼓起多少；不到 1.5 px 就是一條直線，不是弧（外點不算，會把弦撐大而漏判）
        # （極性選反只剩零星幾點時，半徑會爆成幾千像素、圓心跑到影像外，以前仍判 ok 並把圓心畫出去）
        sagitta = r - math.sqrt(max(0.0, r * r - (span / 2.0) ** 2))
        if not math.isfinite(r) or sagitta < 1.5:
            overlays.append({"kind": "points", "points": pts.round(2).tolist(), "color": "#ef4444"})
            return Result(outputs=ng, overlays=overlays, status="ng", message=f"Arc fit is degenerate (R={r:.0f}px over a {span:.0f}px chord bulges only {sagitta:.2f}px); the edge points are nearly straight")
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
            outputs={"radius": r, "cx": cx, "cy": cy, "residual_rms": rms, "points": pts.round(2).tolist(), "start_angle": start, "end_angle": end,
                     "circle": {"cx": round(float(cx), 4), "cy": round(float(cy), 4), "r": round(float(r), 4)},
                     **world_outputs(ctx, points={("cx", "cy"): (cx, cy)}, lengths={"radius": (r, (cx, cy))},
                                     angles={"start_angle": (start, (cx, cy)), "end_angle": (end, (cx, cy))})},
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


def _edge_trend_reference(ctx: ToolContext) -> tuple[str, tuple, dict[str, Any] | None]:
    """取得 edge_trend 的參考幾何；上游幾何優先於畫布 ROI。"""
    line = _line(ctx.inputs.get("line"))
    if line is not None:
        return "line", line, {"kind": "line", "x1": line[0], "y1": line[1], "x2": line[2], "y2": line[3], "color": "#38bdf8", "dash": True}
    circle_in = ctx.inputs.get("circle")
    if isinstance(circle_in, dict) and all(k in circle_in for k in ("cx", "cy", "r")):
        circle = (float(circle_in["cx"]), float(circle_in["cy"]), float(circle_in["r"]), 0.0, 360.0)
        return "arc", circle, {"kind": "circle", "cx": circle[0], "cy": circle[1], "r": circle[2], "color": "#38bdf8", "dash": True}
    region = ctx.roi()
    if region is None:
        raise ToolError("Draw a region along the edge, or wire a line or a circle in from a locate step")
    shape = str(region.get("shape") or "")
    if shape in ("circle", "annulus"):
        cx, cy = float(region["cx"]), float(region["cy"])
        radius = float(region.get("r", region.get("r_outer", 0)) or 0)
        if shape == "annulus":
            radius = (float(region["r_inner"]) + float(region["r_outer"])) / 2
        return "arc", (cx, cy, radius, float(region.get("a0", 0) or 0), float(region.get("a1", 360) or 360)), region_overlay(region, label="trend")
    if shape in ("rect", "rotated_rect"):
        if shape == "rect":
            cx = float(region["x"]) + float(region["w"]) / 2
            cy = float(region["y"]) + float(region["h"]) / 2
            rw, rh, angle = float(region["w"]), float(region["h"]), 0.0
        else:
            cx, cy = float(region["cx"]), float(region["cy"])
            rw, rh, angle = float(region["w"]), float(region["h"]), float(region.get("angle", 0))
        horizontal = rw >= rh
        length = rw if horizontal else rh
        rad = math.radians(angle)
        ux, uy = (math.cos(rad), math.sin(rad)) if horizontal else (-math.sin(rad), math.cos(rad))
        half = length / 2.0
        line = (cx - ux * half, cy - uy * half, cx + ux * half, cy + uy * half)
        return "line", line, region_overlay(region, label="trend")
    raise ToolError("The region has to be a rectangle, circle or annulus")


def _edge_trend_baseline(ctx: ToolContext, hits: list[CaliperHit], series: np.ndarray, kind: str, wrap: bool) -> np.ndarray:
    """依選定模式產生每把卡尺的 offset 基線。"""
    mode = str(ctx.param("baseline", "fit"))
    n = len(series)
    finite = np.isfinite(series)
    if mode == "reference":
        return np.zeros(n) if finite.any() else np.full(n, np.nan)
    if mode == "median":
        return defects.moving_median(series, ctx.integer("window", 9), wrap)
    if finite.sum() < 3:
        return np.full(n, float(np.nanmedian(series)) if finite.any() else np.nan)
    points = np.asarray(hit_points(hits), dtype=np.float64)
    if kind == "arc" and len(points) >= 5:
        fitted = fit_circle_lsq(points)
        if fitted is not None:
            fx, fy, radius = fitted
            out = np.full(n, np.nan)
            for i, h in enumerate(hits):
                if h.found:
                    out[i] = -(math.hypot(h.cx - fx, h.cy - fy) - radius)
            return out
    if kind == "line" and len(points) >= 2:
        fitted = fit_points_line(points, ransac=True, tol=max(1.0, ctx.number("max_deviation", 2.0) * 1.5))
        if fitted is not None:
            vx, vy, x0, y0, _ = fitted
            nx, ny = -vy, vx
            out = np.full(n, np.nan)
            for i, h in enumerate(hits):
                if h.found:
                    out[i] = -((h.cx - x0) * nx + (h.cy - y0) * ny)
            return out
    return np.full(n, float(np.nanmedian(series)))


class EdgeTrendTool(Tool):
    key = "edge_trend"
    label = "Edge trend"
    description = "Lays calipers along a straight or round edge and returns the per-caliper offset trend, widths in pair mode, missing indices and summary statistics."
    category = "measure"
    icon = "Activity"
    params = [
        Param("roi", "Reference", kind="roi", shapes=["rect", "rotated_rect", "circle", "annulus"],
              help_text="Draw along the edge when no upstream line or circle is connected. Wired geometry takes priority."),
        Param("calipers", "Calipers", kind="number", default=60, minimum=3, maximum=1000, teach=True),
        Param("search", "Search range", kind="number", default=20, minimum=2, maximum=2000, unit="px", teach=True),
        Param("caliper_width", "Caliper width", kind="number", default=3, minimum=1, maximum=99, unit="px",
              help_text="Averaging width along the edge."),
        Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("mode", "Mode", kind="select", default="single", options=[
            {"value": "single", "label": "Single edge"}, {"value": "pair", "label": "Edge pair"},
        ]),
        Param("polarity", "Edge polarity", kind="select", default="any", options=POLARITY_OPTIONS, teach=True,
              visible_when={"param": "mode", "in": ["single"]}),
        Param("pair_polarity", "Pair polarity", kind="select", default="any", options=[
            {"value": "any", "label": "Any"}, {"value": "bright", "label": "Bright band"}, {"value": "dark", "label": "Dark band"},
        ], teach=True, visible_when={"param": "mode", "in": ["pair"]}),
        Param("baseline", "Baseline", kind="select", default="fit", options=[
            {"value": "fit", "label": "Fit to found edge"},
            {"value": "median", "label": "Moving median"},
            {"value": "reference", "label": "Reference geometry"},
        ], help_text="Offsets are hit offset minus this baseline, in px."),
        Param("max_deviation", "Max deviation", kind="number", default=2.0, minimum=0, step=0.1, unit="px", teach=True,
              help_text="Maximum absolute offset trend before taking the NG branch; 0 disables the limit."),
        Param("window", "Median window", kind="number", default=9, minimum=3, maximum=999, group="Advanced",
              visible_when={"param": "baseline", "in": ["median"]}),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
        Param("edge_select", "Which edge", kind="select", default="strongest", options=_EDGE_SELECT_OPTIONS, group="Advanced",
              visible_when={"param": "mode", "in": ["single"]}),
    ]
    inputs = [
        Port("image", "Image", "image"),
        Port("roi", "Region (dynamic)", "region", required=False),
        Port("line", "Reference line", "any", required=False),
        Port("circle", "Reference circle", "any", required=False),
    ]
    outputs = [
        flow_out("ok", "In trend", "ok"), flow_out("ng", "Out of trend", "critical"),
        Port("offsets", "Offsets", "list"), Port("widths", "Widths", "list"), Port("positions", "Positions", "list"),
        Port("points", "Edge points", "points"), Port("missing", "Missing indices", "list"),
        Port("mean", "Mean", "number"), Port("std", "Std dev", "number"), Port("min", "Min", "number"),
        Port("max", "Max", "number"), Port("range", "Range", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        kind, geometry, reference_overlay = _edge_trend_reference(ctx)
        count = ctx.integer("calipers", 60)
        wrap = kind == "arc" and abs(float(geometry[4]) - float(geometry[3])) >= 359.9
        if kind == "line":
            centers, scan, tangent, positions = line_geometry(*geometry, count)
        else:
            cx, cy, radius, a0, a1 = geometry
            centers, scan, tangent, positions = arc_geometry(cx, cy, radius, count, a0=a0, a1=a1)
        pair = str(ctx.param("mode", "single")) == "pair"
        hits = caliper_series(
            image, centers, scan, tangent, positions,
            search=ctx.number("search", 20), height=ctx.number("caliper_width", 3),
            polarity=str(ctx.param("polarity", "any")), threshold=ctx.number("edge_threshold", 20),
            smoothing=ctx.integer("smoothing", 3), mode="pair" if pair else "single",
            select=str(ctx.param("edge_select", "strongest")),
            pair_polarity=str(ctx.param("pair_polarity", "any")),
        )
        raw_offsets = np.array([h.offset if h.found else np.nan for h in hits], dtype=np.float64)
        baseline = _edge_trend_baseline(ctx, hits, raw_offsets, kind, wrap)
        offsets = raw_offsets - baseline
        finite = offsets[np.isfinite(offsets)]
        nan = float("nan")
        stats = {
            "mean": float(finite.mean()) if len(finite) else nan,
            "std": float(finite.std()) if len(finite) else nan,
            "min": float(finite.min()) if len(finite) else nan,
            "max": float(finite.max()) if len(finite) else nan,
            "range": float(finite.max() - finite.min()) if len(finite) else nan,
        }
        limit = ctx.number("max_deviation", 2.0)
        worst = float(np.max(np.abs(finite))) if len(finite) else nan
        ok = bool(len(finite)) and (limit <= 0 or worst <= limit)
        over = np.isfinite(offsets) & (limit > 0) & (np.abs(offsets) > limit)
        missing = [int(h.index) for h in hits if not h.found]
        points = [[round(h.x, 2), round(h.y, 2)] for h in hits if h.found]
        overlays: list[dict[str, Any]] = [reference_overlay] if reference_overlay else []
        good_points = [[round(h.x, 2), round(h.y, 2)] for h in hits if h.found and not over[h.index]]
        bad_points = [[round(h.x, 2), round(h.y, 2)] for h in hits if h.found and over[h.index]]
        if good_points:
            overlays.append({"kind": "points", "points": good_points, "color": "#22c55e"})
        if bad_points:
            overlays.append({"kind": "points", "points": bad_points, "color": "#ef4444"})
        if pair:
            second = [[round(h.x2, 2), round(h.y2, 2)] for h in hits if h.found]
            if second:
                overlays.append({"kind": "points", "points": second, "color": "#a78bfa"})
        if missing:
            overlays.append({"kind": "points", "points": [[round(h.cx, 2), round(h.cy, 2)] for h in hits if not h.found], "color": "#64748b"})
        return Result(
            outputs={
                "offsets": [None if not np.isfinite(v) else round(float(v), 4) for v in offsets],
                "widths": [None if not h.found else round(float(h.width), 4) for h in hits] if pair else [],
                "positions": [round(float(p), 4) for p in positions],
                "points": points,
                "missing": missing,
                **{k: (_round_float(v, 4) if np.isfinite(v) else nan) for k, v in stats.items()},
            },
            overlays=overlays, branch="ok" if ok else "ng", status="ok" if ok else "ng",
            message=(f"trend {stats['mean']:.2f}±{stats['std']:.2f}px, max {worst:.2f}px ({len(missing)} missing)"
                     if len(finite) else f"no edge trend ({len(missing)} missing)"),
            detail={"baseline": ctx.param("baseline", "fit"), "found": int(sum(h.found for h in hits)), "total": len(hits)},
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
        # 交點離邊緣點雲太遠＝兩條線幾乎平行、或方向選項選到了另一條邊：量到的角度沒有意義，判 ng 而不是把交點畫到幾萬像素外
        span = float(np.hypot(*(pts.max(axis=0) - pts.min(axis=0)))) + 1.0
        centre = pts.mean(axis=0)
        far = bool(np.isfinite(ix)) and float(np.hypot(ix - centre[0], iy - centre[1])) > 3.0 * span + 50.0
        overlays += [
            {"kind": "points", "points": pts[inl1].round(2).tolist(), "color": "#38bdf8"},
            {"kind": "points", "points": rest[inl2].round(2).tolist(), "color": "#22c55e"},
            {"kind": "points", "points": rest[~inl2].round(2).tolist(), "color": "#ef4444"},
            {"kind": "line", "x1": line1["x1"], "y1": line1["y1"], "x2": line1["x2"], "y2": line1["y2"], "color": "#38bdf8", "width": 2, "label": "Main edge"},
            {"kind": "line", "x1": line2["x1"], "y1": line2["y1"], "x2": line2["x2"], "y2": line2["y2"], "color": "#22c55e", "width": 2, "label": f"{angle:.1f}° L={line2['length']:.1f}"},
        ]
        if far:
            return Result(
                outputs={**ng_out, "line1": line1, "line2": line2, "points": pts.round(2).tolist()}, overlays=overlays, status="ng",
                message=f"The two fitted edges are nearly parallel (intersection {float(np.hypot(ix - centre[0], iy - centre[1])):.0f} px away); check the direction and threshold",
            )
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


def offset_points(points: Any, dx: float, dy: float) -> list[list[float]]:
    """複製點集並整體平移，不修改上游輸入。"""
    arr = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    return (arr + np.array([dx, dy], dtype=np.float64)).round(4).tolist()


def offset_matches(matches: Any, dx: float, dy: float) -> list[dict[str, Any]]:
    """複製比對結果並平移常見座標欄位。"""
    if not isinstance(matches, list):
        raise ToolError("Matches must be a list")
    shifted: list[dict[str, Any]] = []
    for item in matches:
        if not isinstance(item, dict):
            raise ToolError("Each match must be a dictionary")
        m = dict(item)
        for x_key, y_key in (("x", "y"), ("cx", "cy"), ("x1", "y1"), ("x2", "y2")):
            if x_key in m and y_key in m:
                m[x_key] = round(float(m[x_key]) + dx, 4)
                m[y_key] = round(float(m[y_key]) + dy, 4)
        for key in ("points", "corners"):
            if key in m and m[key] is not None:
                m[key] = offset_points(m[key], dx, dy)
        shifted.append(m)
    return shifted


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
        CALIBRATION_PARAM,
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
            {"value": "offset", "label": "Offset points or matches"},
        ]),
        Param("offset", "Offset", kind="number", default=0, unit="px", teach=True,
              visible_when={"param": "mode", "in": ["parallel"]},
              help_text="How far to move the line sideways when no point is wired in. Positive is to the right of the line's direction."),
        Param("angle", "Angle", kind="number", default=0, unit="°", teach=True,
              visible_when={"param": "mode", "in": ["rotate"]},
              help_text="Clockwise on screen, like every other angle on the platform."),
        Param("offset_x", "Offset X", kind="number", default=0, unit="px", teach=True,
              visible_when={"param": "mode", "in": ["offset"]},
              help_text="X shift to apply when the offset_x input is not wired."),
        Param("offset_y", "Offset Y", kind="number", default=0, unit="px", teach=True,
              visible_when={"param": "mode", "in": ["offset"]},
              help_text="Y shift to apply when the offset_y input is not wired."),
        Param("sign", "Sign", kind="select", default="add", options=[
            {"value": "add", "label": "Add"},
            {"value": "subtract", "label": "Subtract"},
        ], visible_when={"param": "mode", "in": ["offset"]},
              help_text="Add restores crop-local coordinates to the original image; subtract maps original-image coordinates back into the crop."),
    ]
    inputs = [
        Port("a", "A (line / point)", "any", required=False),
        Port("b", "B (line / point)", "any", required=False),
        Port("c", "C (point)", "any", required=False),
        Port("points", "Points", "points", required=False),
        Port("matches", "Matches", "matches", required=False),
        Port("offset_x", "Offset X", "number", required=False),
        Port("offset_y", "Offset Y", "number", required=False),
    ]
    outputs = [
        Port("x_world", "X (world)", "number"),
        Port("y_world", "Y (world)", "number"),
        Port("distance_world", "Distance (world)", "number"),
        Port("angle_world", "Angle (world)", "number"),
        Port("unit", "Unit", "string"),
        Port("x", "X", "number"), Port("y", "Y", "number"), Port("distance", "Distance", "number"),
        Port("angle", "Angle", "number"), Port("line", "Line", "any"), Port("circle", "Circle", "any"),
        Port("points", "Points", "points"), Port("matches", "Matches", "matches"), Port("count", "Count", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        result = self._pixel_result(ctx)
        if ctx.param("mode", "intersect") == "offset" or not ctx.param("calibration") or result.status != "ok":
            return result
        values = result.outputs
        at = (values["x"], values["y"])
        mode = ctx.param("mode", "intersect")
        result.outputs.update(world_outputs(ctx, points={("x", "y"): at},
                                           lengths={"distance": (values["distance"], at)},
                                           angles={"angle": (values["angle"], at)}))
        if mode in ("intersect", "rotate"):
            # 夾角與旋轉量是兩個方向之差，標定自身的旋轉不應加進去。
            _, mapping = read_mapping(ctx)
            if mode == "intersect":
                directions = [line_angle(_need_line(ctx.inputs.get(key), key)) for key in ("a", "b")]
            else:
                point = _need_point(ctx.inputs.get("a"), "A")
                pivot = _as_point(ctx.inputs.get("b")) or (0.0, 0.0)
                at = pivot
                initial = math.degrees(math.atan2(point[1] - pivot[1], point[0] - pivot[0]))
                directions = [initial, initial + values["angle"]]
            first, second = [calib.angle_to_world(mapping["matrix"], angle, at) for angle in directions]
            delta = (second - first + 180) % 360 - 180
            result.outputs["angle_world"] = min(abs(delta), 180 - abs(delta)) if mode == "intersect" else delta
        elif mode in ("midpoint", "point_line", "project", "circle_3pts"):
            result.outputs["angle_world"] = None
        return result

    def _pixel_result(self, ctx: ToolContext) -> Result:
        """保留原始十二種模式的像素輸出與標記。"""
        mode = str(ctx.param("mode", "intersect"))
        a, b, c = ctx.inputs.get("a"), ctx.inputs.get("b"), ctx.inputs.get("c")
        blank = {"x": 0.0, "y": 0.0, "distance": 0.0, "angle": 0.0, "line": None, "circle": None}

        if mode == "offset":
            dx = float(ctx.inputs["offset_x"]) if ctx.inputs.get("offset_x") is not None else ctx.number("offset_x", 0)
            dy = float(ctx.inputs["offset_y"]) if ctx.inputs.get("offset_y") is not None else ctx.number("offset_y", 0)
            if ctx.param("sign", "add") == "subtract":
                dx, dy = -dx, -dy
            if ctx.inputs.get("points") is not None:
                points = offset_points(ctx.inputs.get("points"), dx, dy)
                first = points[0] if points else [0.0, 0.0]
                return Result(outputs={**blank, "points": points, "matches": [], "count": len(points), "x": first[0], "y": first[1]},
                              overlays=[{"kind": "points", "points": points, "color": "#22c55e"}] if points else [],
                              message=f"{len(points)} points offset ({dx:g}, {dy:g})")
            if ctx.inputs.get("matches") is not None:
                matches = offset_matches(ctx.inputs.get("matches"), dx, dy)
                best = matches[0] if matches else {}
                x = float(best.get("cx", best.get("x", 0.0)) or 0.0)
                y = float(best.get("cy", best.get("y", 0.0)) or 0.0)
                return Result(outputs={**blank, "points": [], "matches": matches, "count": len(matches), "x": x, "y": y},
                              message=f"{len(matches)} matches offset ({dx:g}, {dy:g})")
            return Result(status="ng", outputs={**blank, "points": [], "matches": [], "count": 0},
                          message="Wire points or matches to offset")

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


def _frame_matrix(frame: Any) -> np.ndarray:
    """像素轉自訂座標：先移原點、旋轉負角度，再除以比例。"""
    try:
        x, y = map(float, frame["origin"])
        angle, scale = float(frame["angle"]), float(frame["scale"])
        if not np.isfinite([x, y, angle, scale]).all() or scale <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ToolError("A coordinate frame needs a finite origin, angle and positive scale") from None
    rad = math.radians(angle)
    c, s = math.cos(rad) / scale, math.sin(rad) / scale
    return np.array([[c, s, -c * x - s * y], [-s, c, s * x - c * y], [0, 0, 1]], dtype=np.float64)


class CoordinateTool(Tool):
    """由原點與有向基準建立座標系；角度正值為畫面順時針。"""

    key = "coordinate"
    label = "Coordinate frame"
    description = "Define an origin and X axis from a point and angle, two points, or a directed line. Wire the frame to real-world coordinates."
    category = "measure"
    icon = "Axis3d"
    params = [
        Param("mode", "Define by", kind="select", default="point_angle", options=[
            {"value": "point_angle", "label": "Point and angle"},
            {"value": "two_points", "label": "Two points"},
            {"value": "line", "label": "Directed line"},
        ]),
        Param("origin_x", "Origin X", kind="number", teach=True, unit="px",
              visible_when={"param": "mode", "in": ["point_angle", "two_points"]},
              help_text="Used with Origin Y when the point input is not connected."),
        Param("origin_y", "Origin Y", kind="number", teach=True, unit="px",
              visible_when={"param": "mode", "in": ["point_angle", "two_points"]}),
        Param("axis_angle", "X axis angle", kind="number", default=0, teach=True, unit="°",
              visible_when={"param": "mode", "in": ["point_angle"]},
              help_text="Clockwise on screen. Used when the angle input is not connected."),
    ]
    inputs = [
        Port("point", "Origin point", "any", required=False),
        Port("angle", "X axis angle", "number", required=False),
        Port("point2", "Point on X axis", "any", required=False),
        Port("line", "Directed line", "any", required=False),
    ]
    outputs = [
        Port("frame", "Coordinate frame", "any"), Port("origin_x", "Origin X", "number"),
        Port("origin_y", "Origin Y", "number"), Port("angle", "X axis angle", "number"),
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        mode = ctx.param("mode", "point_angle")
        try:
            if mode == "line":
                line = _line(ctx.inputs.get("line"))
                if line is None:
                    raise ValueError
                origin, tip = line[:2], line[2:]
            elif mode in ("point_angle", "two_points"):
                origin = (_point(ctx.inputs["point"]) if "point" in ctx.inputs else
                          _point(None, (ctx.param("origin_x"), ctx.param("origin_y"))))
                tip = _point(ctx.inputs.get("point2")) if mode == "two_points" else None
            else:
                raise ValueError
            if origin is None or not np.isfinite(origin).all():
                raise ValueError
            if mode == "point_angle":
                angle = float(ctx.inputs["angle"] if "angle" in ctx.inputs else ctx.param("axis_angle", 0))
            else:
                if tip is None or not np.isfinite(tip).all() or math.dist(origin, tip) <= 1e-12:
                    raise ValueError
                angle = math.degrees(math.atan2(tip[1] - origin[1], tip[0] - origin[0]))
            if not math.isfinite(angle):
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            return Result(status="ng", branch="not_found", message="No valid origin and X axis were provided",
                          outputs={"frame": None, "origin_x": None, "origin_y": None, "angle": None})
        x, y = origin
        rad = math.radians(angle)
        c, s = 40 * math.cos(rad), 40 * math.sin(rad)
        return Result(outputs={"frame": {"origin": [x, y], "angle": angle, "scale": 1.0},
                               "origin_x": x, "origin_y": y, "angle": angle}, branch="found",
                      overlays=[{"kind": "point", "x": x, "y": y, "label": "Origin", "color": "#f59e0b"},
                                {"kind": "line", "x1": x, "y1": y, "x2": x + c, "y2": y + s, "label": "X", "color": "#ef4444"},
                                {"kind": "line", "x1": x, "y1": y, "x2": x - s, "y2": y + c, "label": "Y", "color": "#22c55e"}],
                      message=f"Origin ({x:.3f}, {y:.3f}), X axis {angle:.3f}°")


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
        Param("mode", "Direction", kind="select", default="to_world", options=[
            {"value": "to_world", "label": "To world"}, {"value": "to_pixel", "label": "To pixels"},
        ], help_text="To pixels treats x/y/points as world or frame coordinates; x/y/points_world outputs then contain image pixels. Lengths and angles follow the same direction."),
        Param("calibration", "Calibration", kind="asset", accept="calibration", required=False, group="Advanced",
              help_text="Optional. Without calibration, outputs use pixels in the connected frame. With no frame, coordinates are unchanged."),
        Param("decimals", "Decimals", kind="number", default=3, minimum=0, maximum=6, step=1, group="advanced"),
    ]
    inputs = [
        Port("frame", "Coordinate frame", "any", required=False),
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
        mode = ctx.param("mode", "to_world")
        if mode not in ("to_world", "to_pixel"):
            raise ToolError("Direction must be to_world or to_pixel")
        reverse = mode == "to_pixel"
        world: dict[str, Any] = {}
        matrix = np.eye(3)
        unit = "px"
        if ctx.param("calibration"):
            payload = read_calibration(ctx)
            # 保留既有 world 優先行為，機構專用資產則使用 robot。
            world = payload.get("world") or payload.get("robot")
            if not world:
                raise ToolError("That calibration only corrects the lens: add a board, a known distance or robot points to get coordinates")
            matrix = np.asarray(world["matrix"], dtype=np.float64)
            unit = payload.get("unit", "mm")
        frame = ctx.inputs.get("frame")
        if "frame" in ctx.inputs and frame is None:
            return Result(status="ng", message="The coordinate frame is unavailable")
        if frame is not None:
            matrix = matrix @ _frame_matrix(frame)
        if reverse:
            try:
                matrix = np.linalg.inv(matrix)
            except np.linalg.LinAlgError:
                raise ToolError("The coordinate mapping is not invertible") from None
            unit = "px"
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
        if pts is None and frame is None and not ctx.param("calibration") and not reverse:
            raise ToolError("No calibration is selected: wire a coordinate frame or select a calibration to convert a length or angle")

        outputs: dict[str, Any] = {"scale": float(world.get("mm_per_px") or 0)}
        if frame is not None or reverse or not ctx.param("calibration"):
            outputs["scale"] = calib.scale_at(matrix, (0.0, 0.0))
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
                    overlay_point = mapped[i] if reverse else src[i]
                    overlays.append({"kind": "point", "x": float(overlay_point[0]), "y": float(overlay_point[1]), "color": "#22c55e",
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
    CaliperTool(), PeakSearchTool(), DistanceTool(), AngleTool(), IntensityTool(), CalibrationTool(), HistogramTool(), SharpnessTool(), ToWorldTool(),
    FitArcTool(), FitEllipseTool(), WallThicknessTool(), ConcentricityTool(), ChamferAngleTool(), ToleranceJudgeTool(),
    EdgeTrendTool(), LineProfileTool(), ColorStatsTool(), GeometryTool(), PointsMergeTool(), CoordinateTool(),
]
