"""contours 工具鏈：輪廓萃取 → 篩選 → 幾何 → 比對。

`contours` 埠型別早就有（blob／dl_instance／yolo_segment 都會吐），但一直缺「單獨拿輪廓來算」的工具。
這一組補完後，形位公差（gdt_measure）與輪廓缺陷掃描才有完整的資料來源。

慣例（四個工具一致）：
- 輪廓一律是全圖座標的 (N, 1, 2) 陣列清單；輸入可以是 int32／float32 陣列或 [[x, y], …] 清單（_as_contours 統一）。
- 多條輪廓的數值走 `list` 埠（每條一項），另有 `first_*` number 埠（第一條）方便直接接判定工具。
- `area` 是**像素數**（把輪廓填滿數像素），與 blob 的 area 同一個定義；凸度（solidity）用輪廓幾何面積／凸包面積（同一套幾何才自洽）。
- 找不到輪廓不是錯誤：`count=0`、走 `not_found` 分支。
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.detect import _binarize
from apps.vision.tools.builtin.locate import read_asset_image, to_gray
from apps.vision.tools.roi import crop, mask_for, region_overlay

MODE_OPTIONS = [
    {"value": "external", "label": "Outer contours only"},
    {"value": "list", "label": "All contours (holes too, flat)"},
    {"value": "ccomp", "label": "Outer contours and their holes"},
    {"value": "tree", "label": "Full hierarchy"},
]
_MODES = {"external": cv2.RETR_EXTERNAL, "list": cv2.RETR_LIST, "ccomp": cv2.RETR_CCOMP, "tree": cv2.RETR_TREE}
SORT_OPTIONS = [
    {"value": "area", "label": "Area (large to small)"},
    {"value": "perimeter", "label": "Perimeter (long to short)"},
    {"value": "x", "label": "X (left to right)"},
    {"value": "y", "label": "Y (top to bottom)"},
    {"value": "none", "label": "Keep the input order"},
]
MATCH_METHOD_OPTIONS = [
    {"value": "i1", "label": "I1 (sum of |1/mA − 1/mB|)"},
    {"value": "i2", "label": "I2 (sum of |mA − mB|)"},
    {"value": "i3", "label": "I3 (max relative difference)"},
]
_MATCH_METHODS = {"i1": cv2.CONTOURS_MATCH_I1, "i2": cv2.CONTOURS_MATCH_I2, "i3": cv2.CONTOURS_MATCH_I3}


def _as_contours(value: Any) -> list[np.ndarray]:
    """contours 埠的各種寫法 → list[np.ndarray (N,1,2) float32]。單一陣列也接受。"""
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        value = [value] if value.ndim in (2, 3) else []
    out: list[np.ndarray] = []
    for item in value:
        try:
            arr = np.asarray(item, dtype=np.float32).reshape(-1, 1, 2)
        except (TypeError, ValueError):
            continue
        if len(arr) >= 1:
            out.append(arr)
    return out


def _int_contour(cnt: np.ndarray) -> np.ndarray:
    """cv2 需要 int32 輪廓的函式（convexityDefects、drawContours）用；已是 int32 就直接回。"""
    return cnt if cnt.dtype == np.int32 else np.round(cnt).astype(np.int32)


def pixel_area(cnt: np.ndarray) -> float:
    """輪廓填滿後的像素數（與 blob.area 同定義）。"""
    ic = _int_contour(cnt)
    x, y, w, h = cv2.boundingRect(ic)
    if w <= 0 or h <= 0:
        return 0.0
    buf = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(buf, [ic - np.array([x, y], dtype=np.int32)], -1, 255, -1)
    return float(cv2.countNonZero(buf))


def centroid(cnt: np.ndarray) -> tuple[float, float]:
    m = cv2.moments(cnt)
    if m["m00"] > 0:
        return float(m["m10"] / m["m00"]), float(m["m01"] / m["m00"])
    pts = cnt.reshape(-1, 2)
    return float(pts[:, 0].mean()), float(pts[:, 1].mean())


def min_rect(cnt: np.ndarray) -> tuple[float, float, float, float, float]:
    """最小外接矩形 (cx, cy, w, h, angle)；w 為長邊、angle 為長邊方向（度，畫面順時針為正，−90～90）。"""
    if len(cnt) < 3:
        x, y, w, h = cv2.boundingRect(_int_contour(cnt))
        return x + w / 2, y + h / 2, float(max(w, h)), float(min(w, h)), 0.0
    (cx, cy), (rw, rh), angle = cv2.minAreaRect(cnt)
    if rw < rh:
        rw, rh = rh, rw
        angle += 90.0
    angle = ((angle + 90.0) % 180.0) - 90.0
    return float(cx), float(cy), float(rw), float(rh), float(angle)


def convexity_defects(cnt: np.ndarray, min_depth: float) -> tuple[list[dict[str, float]], float]:
    """深度 ≥ min_depth 的凸缺陷：[{x, y, depth, start:[x,y], end:[x,y]}]（全圖座標）與最大深度。"""
    if len(cnt) < 4:
        return [], 0.0
    ic = _int_contour(cnt)
    hull = cv2.convexHull(ic, returnPoints=False)
    if hull is None or len(hull) < 3:
        return [], 0.0
    try:
        defects = cv2.convexityDefects(ic, hull)
    except cv2.error:
        return [], 0.0
    out: list[dict[str, Any]] = []
    deepest = 0.0
    if defects is None:
        return out, deepest
    for s, e, f, d in defects.reshape(-1, 4):
        depth = float(d) / 256.0
        deepest = max(deepest, depth)
        if depth >= min_depth:
            out.append({"x": float(ic[f, 0, 0]), "y": float(ic[f, 0, 1]), "depth": round(depth, 2),
                        "start": [float(ic[s, 0, 0]), float(ic[s, 0, 1])], "end": [float(ic[e, 0, 0]), float(ic[e, 0, 1])]})
    return out, deepest


def describe(cnt: np.ndarray, min_defect_depth: float = 3.0) -> dict[str, Any]:
    """一條輪廓的完整幾何（contour_geometry 的每項）。"""
    area = pixel_area(cnt)
    geo_area = float(cv2.contourArea(cnt))
    perimeter = float(cv2.arcLength(cnt, True))
    cx, cy = centroid(cnt)
    rcx, rcy, rw, rh, angle = min_rect(cnt)
    (ccx, ccy), cr = cv2.minEnclosingCircle(cnt)
    hull = cv2.convexHull(cnt)
    hull_area = float(cv2.contourArea(hull))
    convexity = min(1.0, geo_area / hull_area) if hull_area > 0 else 0.0
    circularity = min(1.0, 4 * math.pi * geo_area / (perimeter**2)) if perimeter > 0 else 0.0
    defects, max_depth = convexity_defects(cnt, min_defect_depth)
    hu = cv2.HuMoments(cv2.moments(cnt)).reshape(-1)
    return {
        "area": area, "geometric_area": round(geo_area, 2), "perimeter": round(perimeter, 2), "cx": round(cx, 2), "cy": round(cy, 2),
        "rect": {"cx": round(rcx, 2), "cy": round(rcy, 2), "w": round(rw, 2), "h": round(rh, 2), "angle": round(angle, 2)},
        "circle": {"cx": round(float(ccx), 2), "cy": round(float(ccy), 2), "r": round(float(cr), 2)},
        "hull_area": round(hull_area, 2), "convexity": round(convexity, 4), "circularity": round(circularity, 4),
        "aspect": round(rw / rh, 3) if rh > 0 else 0.0,
        "defect_count": len(defects), "max_defect_depth": round(max_depth, 2), "defects": defects,
        "hu": [float(v) for v in hu], "points": int(len(cnt)),
    }


def _contours_overlay(contours: list[np.ndarray], color: str = "#22c55e", label: str = "") -> dict[str, Any]:
    ov: dict[str, Any] = {"kind": "contours", "contours": [c.reshape(-1, 2).tolist() for c in contours], "color": color, "width": 1}
    if label:
        ov["label"] = label
    return ov


# ---------------------------------------------------------------------------
# contour_find
# ---------------------------------------------------------------------------
class ContourFindTool(Tool):
    key = "contour_find"
    label = "Contour find"
    description = (
        "Traces the outlines in a binary image (a grayscale input is thresholded first): outer contours only, or holes as well. "
        "The contours feed Contour filter, Contour geometry, Contour match and the tolerance tools; coordinates are in the input image."
    )
    category = "measure"
    icon = "PenTool"
    params = [
        Param("roi", "Region", kind="roi", help_text="Leave blank for the whole image."),
        Param("threshold_method", "Threshold", kind="select", default="otsu", options=[
            {"value": "otsu", "label": "Otsu (automatic)"}, {"value": "fixed", "label": "Fixed"}, {"value": "none", "label": "The input is already a mask (anything non-zero is foreground)"},
        ]),
        Param("threshold", "Threshold", kind="number", default=128, minimum=0, maximum=255, visible_when={"param": "threshold_method", "in": ["fixed"]}, teach=True),
        Param("polarity", "Foreground", kind="select", default="bright", options=[{"value": "bright", "label": "Bright objects"}, {"value": "dark", "label": "Dark objects"}]),
        Param("mode", "Retrieval", kind="select", default="external", options=MODE_OPTIONS),
        Param("approx", "Simplify", kind="boolean", default=True, help_text="On: straight runs keep only their end points (CHAIN_APPROX_SIMPLE). Off: every boundary pixel."),
        Param("min_points", "Min points", kind="number", default=4, minimum=1, help_text="Contours with fewer points are dropped."),
        Param("min_area", "Min area", kind="number", default=0, minimum=0, unit="px²", help_text="0 = keep everything.", teach=True),
        Param("max_count", "Max results", kind="number", default=500, minimum=1, maximum=20000),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("contours", "Contours", "contours"), Port("count", "Count", "number"),
        Port("areas", "Areas", "list"), Port("first_area", "First area", "number"),
        Port("centers", "Centres", "points"), Port("first_cx", "First centre X", "number"), Port("first_cy", "First centre Y", "number"),
        Port("mask", "Mask", "image"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        gray = to_gray(image)
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        mask = _binarize(np.ascontiguousarray(c.image), ctx.param("threshold_method", "otsu"), ctx.number("threshold", 128), ctx.param("polarity", "bright"), c.mask)
        if c.mask is not None:
            mask = cv2.bitwise_and(mask, c.mask)
        mode = _MODES.get(str(ctx.param("mode", "external")), cv2.RETR_EXTERNAL)
        approx = cv2.CHAIN_APPROX_SIMPLE if ctx.flag("approx", True) else cv2.CHAIN_APPROX_NONE
        found, _ = cv2.findContours(mask, mode, approx)
        min_points = max(1, ctx.integer("min_points", 4))
        min_area = ctx.number("min_area", 0)
        offset = np.array([c.x0, c.y0], dtype=np.int32)
        contours: list[np.ndarray] = []
        areas: list[float] = []
        for cnt in found:
            if len(cnt) < min_points:
                continue
            area = pixel_area(cnt)
            if min_area > 0 and area < min_area:
                continue
            contours.append(cnt + offset)
            areas.append(area)
        order = sorted(range(len(contours)), key=lambda i: -areas[i])[: ctx.integer("max_count", 500)]
        contours = [contours[i] for i in order]
        areas = [areas[i] for i in order]
        centers = [list(centroid(cnt)) for cnt in contours]
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        if contours:
            overlays.append(_contours_overlay(contours))
        return Result(
            outputs={"contours": contours, "count": len(contours), "areas": areas, "first_area": areas[0] if areas else 0.0,
                     "centers": centers, "first_cx": centers[0][0] if centers else float("nan"), "first_cy": centers[0][1] if centers else float("nan"),
                     "mask": mask},
            overlays=overlays, branch="found" if contours else "not_found", status="ok" if contours else "ng",
            message=f"{len(contours)} contours",
        )


# ---------------------------------------------------------------------------
# contour_filter
# ---------------------------------------------------------------------------
class ContourFilterTool(Tool):
    key = "contour_filter"
    label = "Contour filter"
    description = (
        "Keeps the contours that pass area, perimeter, convexity, aspect-ratio and position limits, then sorts them. "
        "Put it between Contour find and the geometry or match tools to drop noise, holes and the parts you are not measuring."
    )
    category = "measure"
    icon = "Filter"
    params = [
        Param("min_area", "Min area", kind="number", default=0, minimum=0, unit="px²", teach=True),
        Param("max_area", "Max area", kind="number", default=0, minimum=0, unit="px²", help_text="0 = no limit.", teach=True),
        Param("min_perimeter", "Min perimeter", kind="number", default=0, minimum=0, unit="px", group="More limits"),
        Param("max_perimeter", "Max perimeter", kind="number", default=0, minimum=0, unit="px", help_text="0 = no limit.", group="More limits"),
        Param("min_convexity", "Min convexity", kind="range", default=0, minimum=0, maximum=1, step=0.01, group="More limits", help_text="Area over convex-hull area; 1 for a convex shape."),
        Param("max_convexity", "Max convexity", kind="range", default=1, minimum=0, maximum=1, step=0.01, group="More limits"),
        Param("min_aspect", "Min aspect ratio", kind="number", default=0, minimum=0, step=0.1, group="More limits", help_text="Long side over short side of the minimum-area rectangle."),
        Param("max_aspect", "Max aspect ratio", kind="number", default=0, minimum=0, step=0.1, help_text="0 = no limit.", group="More limits"),
        Param("roi", "Keep only inside", kind="roi", group="More limits", help_text="Only contours whose centroid lies inside this region are kept."),
        Param("sort_by", "Sort by", kind="select", default="area", options=SORT_OPTIONS),
        Param("max_count", "Max results", kind="number", default=100, minimum=1, maximum=20000, help_text="After sorting, keep at most this many."),
        Param("min_count", "Min passing count", kind="number", default=1, minimum=0, group="Verdict", help_text="Fewer contours than this is an NG."),
    ]
    inputs = [Port("contours", "Contours", "contours"), Port("roi", "Keep only inside (dynamic)", "region", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("contours", "Contours", "contours"), Port("count", "Count", "number"), Port("rejected", "Rejected count", "number"),
        Port("areas", "Areas", "list"), Port("first_area", "First area", "number"),
        Port("centers", "Centres", "points"), Port("first_cx", "First centre X", "number"), Port("first_cy", "First centre Y", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        contours = _as_contours(ctx.inputs.get("contours"))
        min_area, max_area = ctx.number("min_area", 0), ctx.number("max_area", 0)
        min_p, max_p = ctx.number("min_perimeter", 0), ctx.number("max_perimeter", 0)
        min_cv, max_cv = ctx.number("min_convexity", 0), ctx.number("max_convexity", 1)
        min_asp, max_asp = ctx.number("min_aspect", 0), ctx.number("max_aspect", 0)
        region = ctx.roi()
        inside_mask = None
        if region is not None:
            bx = int(max(p[0] for p in _region_extent(region))) + 2
            by = int(max(p[1] for p in _region_extent(region))) + 2
            inside_mask = mask_for(region, max(1, bx), max(1, by))
        kept: list[tuple[np.ndarray, float, float, tuple[float, float]]] = []
        rejected = 0
        for cnt in contours:
            area = pixel_area(cnt)
            perimeter = float(cv2.arcLength(cnt, True))
            cx, cy = centroid(cnt)
            ok = True
            if area < min_area or (max_area > 0 and area > max_area):
                ok = False
            elif perimeter < min_p or (max_p > 0 and perimeter > max_p):
                ok = False
            elif min_cv > 0 or max_cv < 1:
                geo = float(cv2.contourArea(cnt))
                hull = float(cv2.contourArea(cv2.convexHull(cnt)))
                conv = min(1.0, geo / hull) if hull > 0 else 0.0
                ok = min_cv <= conv <= max_cv
            if ok and (min_asp > 0 or max_asp > 0):
                _, _, rw, rh, _ = min_rect(cnt)
                aspect = rw / rh if rh > 0 else 0.0
                ok = aspect >= min_asp and (max_asp <= 0 or aspect <= max_asp)
            if ok and inside_mask is not None:
                ix, iy = int(round(cx)), int(round(cy))
                ok = 0 <= iy < inside_mask.shape[0] and 0 <= ix < inside_mask.shape[1] and inside_mask[iy, ix] > 0
            if ok:
                kept.append((cnt, area, perimeter, (cx, cy)))
            else:
                rejected += 1
        sort_by = str(ctx.param("sort_by", "area"))
        keyf = {"area": lambda k: -k[1], "perimeter": lambda k: -k[2], "x": lambda k: k[3][0], "y": lambda k: k[3][1]}.get(sort_by)
        if keyf is not None:
            kept.sort(key=keyf)
        kept = kept[: ctx.integer("max_count", 100)]
        out = [k[0] for k in kept]
        areas = [k[1] for k in kept]
        centers = [[k[3][0], k[3][1]] for k in kept]
        overlays: list[dict[str, Any]] = [region_overlay(region, label="inside")] if region else []
        if out:
            overlays.append(_contours_overlay(out))
        count = len(out)
        return Result(
            outputs={"contours": out, "count": count, "rejected": rejected, "areas": areas, "first_area": areas[0] if areas else 0.0,
                     "centers": centers, "first_cx": centers[0][0] if centers else float("nan"), "first_cy": centers[0][1] if centers else float("nan")},
            overlays=overlays, branch="found" if count else "not_found", status="ok" if count >= ctx.integer("min_count", 1) else "ng",
            message=f"{count} kept, {rejected} rejected",
        )


def _region_extent(region: dict[str, Any]) -> list[tuple[float, float]]:
    """region 的幾個極端點（給 mask_for 決定畫多大）。"""
    shape = region.get("shape")
    if shape == "rect":
        return [(region["x"] + region["w"], region["y"] + region["h"])]
    if shape in ("rotated_rect",):
        d = math.hypot(region["w"], region["h"]) / 2
        return [(region["cx"] + d, region["cy"] + d)]
    if shape == "circle":
        return [(region["cx"] + region["r"], region["cy"] + region["r"])]
    if shape == "annulus":
        return [(region["cx"] + region["r_outer"], region["cy"] + region["r_outer"])]
    if shape == "ellipse":
        d = max(region["rx"], region["ry"])
        return [(region["cx"] + d, region["cy"] + d)]
    if shape in ("polygon", "polyline"):
        pts = np.asarray(region["points"], dtype=np.float64)
        return [(float(pts[:, 0].max()), float(pts[:, 1].max()))]
    if shape == "line":
        return [(max(region["x1"], region["x2"]), max(region["y1"], region["y2"]))]
    if shape == "point":
        return [(region["x"], region["y"])]
    if shape == "composite":
        pts: list[tuple[float, float]] = []
        for op in region.get("ops", []):
            pts.extend(_region_extent(op.get("region") or {}))
        return pts or [(1.0, 1.0)]
    return [(1.0, 1.0)]


# ---------------------------------------------------------------------------
# contour_geometry
# ---------------------------------------------------------------------------
class ContourGeometryTool(Tool):
    key = "contour_geometry"
    label = "Contour geometry"
    description = (
        "Measures every contour: area, perimeter, centroid, minimum-area rectangle with its angle, enclosing circle, convex-hull "
        "area and convexity, convexity defects (a chipped corner, a bite out of an edge, a foreign body caught in the outline — "
        "counted and the deepest one reported), circularity and Hu moments. Lists carry one entry per contour; the first_ ports carry the first contour."
    )
    category = "measure"
    icon = "Pentagon"
    params = [
        Param("defect_depth", "Defect depth", kind="number", default=3, minimum=0, step=0.5, unit="px", teach=True,
              help_text="A dent in the outline deeper than this, measured from the convex hull, counts as a convexity defect."),
        Param("max_contours", "Max contours", kind="number", default=200, minimum=1, maximum=20000, help_text="Only the first N contours are measured."),
    ]
    inputs = [Port("contours", "Contours", "contours"), Port("image", "Image (for display)", "image", required=False)]
    outputs = [
        Port("geometry", "Geometry", "list"), Port("count", "Count", "number"),
        Port("areas", "Areas", "list"), Port("perimeters", "Perimeters", "list"), Port("centers", "Centres", "points"),
        Port("rects", "Min-area rectangles", "list"), Port("circles", "Enclosing circles", "list"),
        Port("convexities", "Convexities", "list"), Port("defect_counts", "Defect counts", "list"), Port("defect_points", "Defect points", "points"),
        Port("first_area", "First area", "number"), Port("first_perimeter", "First perimeter", "number"),
        Port("first_cx", "First centre X", "number"), Port("first_cy", "First centre Y", "number"),
        Port("first_w", "First length", "number"), Port("first_h", "First width", "number"), Port("first_angle", "First angle", "number"),
        Port("first_r", "First enclosing radius", "number"), Port("first_convexity", "First convexity", "number"),
        Port("first_circularity", "First circularity", "number"),
        Port("first_defects", "First defect count", "number"), Port("first_max_defect_depth", "First deepest defect", "number"),
        Port("total_defects", "Total defect count", "number"), Port("max_defect_depth", "Deepest defect", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        contours = _as_contours(ctx.inputs.get("contours"))[: ctx.integer("max_contours", 200)]
        depth = ctx.number("defect_depth", 3)
        rows = [describe(cnt, depth) for cnt in contours]
        overlays: list[dict[str, Any]] = []
        if contours:
            overlays.append(_contours_overlay(contours))
        defect_points: list[list[float]] = []
        for i, g in enumerate(rows):
            r = g["rect"]
            overlays.append({"kind": "rect", "x": r["cx"] - r["w"] / 2, "y": r["cy"] - r["h"] / 2, "w": r["w"], "h": r["h"], "angle": r["angle"],
                             "color": "#38bdf8", "width": 1, "dash": True, "label": f"#{i + 1} A={g['area']:.0f}"})
            for d in g["defects"]:
                defect_points.append([d["x"], d["y"]])
                overlays.append({"kind": "point", "x": d["x"], "y": d["y"], "color": "#ef4444", "label": f"{d['depth']:.1f}px"})
        first = rows[0] if rows else None
        total_defects = sum(g["defect_count"] for g in rows)
        max_depth = max((g["max_defect_depth"] for g in rows), default=0.0)
        nan = float("nan")
        return Result(
            outputs={
                "geometry": rows, "count": len(rows),
                "areas": [g["area"] for g in rows], "perimeters": [g["perimeter"] for g in rows], "centers": [[g["cx"], g["cy"]] for g in rows],
                "rects": [g["rect"] for g in rows], "circles": [g["circle"] for g in rows],
                "convexities": [g["convexity"] for g in rows], "defect_counts": [g["defect_count"] for g in rows], "defect_points": defect_points,
                "first_area": first["area"] if first else 0.0, "first_perimeter": first["perimeter"] if first else 0.0,
                "first_cx": first["cx"] if first else nan, "first_cy": first["cy"] if first else nan,
                "first_w": first["rect"]["w"] if first else 0.0, "first_h": first["rect"]["h"] if first else 0.0, "first_angle": first["rect"]["angle"] if first else 0.0,
                "first_r": first["circle"]["r"] if first else 0.0, "first_convexity": first["convexity"] if first else 0.0,
                "first_circularity": first["circularity"] if first else 0.0,
                "first_defects": first["defect_count"] if first else 0, "first_max_defect_depth": first["max_defect_depth"] if first else 0.0,
                "total_defects": total_defects, "max_defect_depth": max_depth,
            },
            overlays=overlays, status="ok",
            message=(f"{len(rows)} contours, first A={first['area']:.0f} P={first['perimeter']:.1f} conv={first['convexity']:.3f}, {total_defects} defects" if first else "no contours"),
        )


# ---------------------------------------------------------------------------
# contour_match
# ---------------------------------------------------------------------------
def template_contour(ctx: ToolContext) -> np.ndarray:
    """範本輪廓：`reference` 埠優先（另一個 contour_find 的輸出，取第一條）；否則從 `template` 資產影像取最大外輪廓。"""
    ref = _as_contours(ctx.inputs.get("reference"))
    if ref:
        return ref[0]
    if not ctx.param("template"):
        raise ToolError("Connect a reference contour or choose a template image asset")
    tpl = read_asset_image(ctx, "template", gray=True)
    mask = _binarize(np.ascontiguousarray(tpl), ctx.param("template_threshold", "otsu"), ctx.number("threshold", 128), ctx.param("polarity", "bright"), None)
    found, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found = [c for c in found if len(c) >= 4]
    if not found:
        raise ToolError("No shape was found in the template image")
    return max(found, key=cv2.contourArea)


class ContourMatchTool(Tool):
    key = "contour_match"
    label = "Contour match"
    description = (
        "Compares each contour with a reference shape by Hu-moment distance, which ignores position, scale and rotation. "
        "The reference is a contour from another Contour find (the reference port) or the largest shape in a template image. "
        "Below the distance limit is a match — for sorting parts by silhouette or catching a wrong or deformed one."
    )
    category = "measure"
    icon = "Shapes"
    params = [
        Param("template", "Template image", kind="asset", accept="image", help_text="Used when the reference port is not connected; the largest bright shape after thresholding is the reference."),
        Param("template_threshold", "Template threshold", kind="select", default="otsu", options=[
            {"value": "otsu", "label": "Otsu (automatic)"}, {"value": "fixed", "label": "Fixed"}, {"value": "none", "label": "The template is already a mask"},
        ], group="Template"),
        Param("threshold", "Threshold", kind="number", default=128, minimum=0, maximum=255, visible_when={"param": "template_threshold", "in": ["fixed"]}, group="Template"),
        Param("polarity", "Template foreground", kind="select", default="bright", options=[{"value": "bright", "label": "Bright shape"}, {"value": "dark", "label": "Dark shape"}], group="Template"),
        Param("method", "Method", kind="select", default="i1", options=MATCH_METHOD_OPTIONS),
        Param("max_distance", "Max distance", kind="number", default=0.1, minimum=0, step=0.01, teach=True,
              help_text="A contour at or below this distance matches. Identical shapes score near 0; try 0.05 to 0.3."),
        Param("min_matches", "Min matches", kind="number", default=1, minimum=0, group="Verdict", help_text="Fewer matching contours than this is an NG."),
    ]
    inputs = [Port("contours", "Contours", "contours"), Port("reference", "Reference contour", "contours", required=False), Port("image", "Image (for display)", "image", required=False)]
    outputs = [
        flow_out("match", "Match", "ok"), flow_out("no_match", "No match", "critical"),
        Port("distances", "Distances", "list"), Port("distance", "Best distance", "number"), Port("best_index", "Best index", "number"),
        Port("match_flag", "Match", "bool"), Port("match_count", "Match count", "number"),
        Port("matched", "Matching contours", "contours"), Port("best", "Best contour", "contours"),
        Port("first_distance", "First distance", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        contours = _as_contours(ctx.inputs.get("contours"))
        ref = template_contour(ctx)
        method = _MATCH_METHODS.get(str(ctx.param("method", "i1")), cv2.CONTOURS_MATCH_I1)
        limit = ctx.number("max_distance", 0.1)
        distances: list[float] = []
        for cnt in contours:
            if len(cnt) < 3:
                distances.append(float("inf"))
                continue
            distances.append(float(cv2.matchShapes(ref, cnt, method, 0.0)))
        matched_idx = [i for i, d in enumerate(distances) if d <= limit]
        best_index = int(min(range(len(distances)), key=lambda i: distances[i])) if distances else -1
        best = distances[best_index] if best_index >= 0 else float("nan")
        overlays: list[dict[str, Any]] = []
        if contours:
            overlays.append(_contours_overlay([contours[i] for i in matched_idx], "#22c55e", "match") if matched_idx else _contours_overlay(contours, "#ef4444"))
            for i, d in enumerate(distances):
                cx, cy = centroid(contours[i])
                overlays.append({"kind": "text", "x": cx, "y": cy, "text": f"{d:.3f}", "color": "#22c55e" if i in matched_idx else "#ef4444"})
        count = len(matched_idx)
        clean = [(d if math.isfinite(d) else None) for d in distances]
        return Result(
            outputs={"distances": clean, "distance": best, "best_index": best_index, "match_flag": bool(matched_idx), "match_count": count,
                     "matched": [contours[i] for i in matched_idx], "best": [contours[best_index]] if best_index >= 0 else [],
                     "first_distance": clean[0] if clean else float("nan")},
            overlays=overlays, branch="match" if matched_idx else "no_match", status="ok" if count >= ctx.integer("min_matches", 1) else "ng",
            message=f"best {best:.4f}, {count} of {len(contours)} match" if contours else "no contours",
        )


TOOLS = [ContourFindTool(), ContourFilterTool(), ContourGeometryTool(), ContourMatchTool()]
