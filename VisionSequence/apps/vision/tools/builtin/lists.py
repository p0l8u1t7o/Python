"""框與清單的後處理工具。"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.roi import extent, mask_for, region_overlay


MERGE_MODES = [{"value": "iou", "label": "IoU"}, {"value": "centre_distance", "label": "Centre distance"}]
MERGE_KEEP = [{"value": "highest_score", "label": "Highest score"}, {"value": "largest", "label": "Largest"}, {"value": "first", "label": "First"}]
ROI_MODES = [{"value": "inside", "label": "Inside ROI"}, {"value": "outside", "label": "Outside ROI"}]
SORT_BY = [
    {"value": "value", "label": "Value"}, {"value": "x", "label": "X"}, {"value": "y", "label": "Y"},
    {"value": "xy", "label": "Reading order"}, {"value": "score", "label": "Score"}, {"value": "label", "label": "Label"},
]


def _value_list(ctx: ToolContext) -> list[Any]:
    values = ctx.inputs.get("values")
    if not isinstance(values, list):
        raise ToolError("Connect a values list")
    return list(values)


def _boxes(ctx: ToolContext) -> list[dict[str, Any]]:
    raw = ctx.inputs.get("matches")
    if not isinstance(raw, list):
        if "values" in ctx.inputs:
            raise ToolError("This tool needs matches with cx/cy/w/h boxes, not values")
        raise ToolError("Connect a matches list")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ToolError(f"Match {i} is not an object")
        box = dict(item)
        try:
            if "w" in box and "h" in box:
                w = float(box["w"])
                h = float(box["h"])
                if "cx" in box and "cy" in box:
                    cx, cy = float(box["cx"]), float(box["cy"])
                    x, y = cx - w / 2, cy - h / 2
                elif "x" in box and "y" in box:
                    x, y = float(box["x"]), float(box["y"])
                    cx, cy = x + w / 2, y + h / 2
                else:
                    raise TypeError
            elif isinstance(box.get("bbox"), list) and len(box["bbox"]) >= 4:
                x, y, w, h = (float(v) for v in box["bbox"][:4])
                cx, cy = x + w / 2, y + h / 2
            else:
                raise TypeError
        except (TypeError, ValueError):
            raise ToolError(f"Match {i} must have cx/cy/w/h, x/y/w/h, or bbox") from None
        if w <= 0 or h <= 0:
            raise ToolError(f"Match {i} has a non-positive size")
        box.update({"x": round(x, 3), "y": round(y, 3), "w": round(w, 3), "h": round(h, 3), "cx": round(cx, 3), "cy": round(cy, 3)})
        box["bbox"] = [round(x, 3), round(y, 3), round(w, 3), round(h, 3)]
        out.append(box)
    return out


def _area(m: dict[str, Any]) -> float:
    return float(m["w"]) * float(m["h"])


def _score(m: dict[str, Any]) -> float:
    try:
        return float(m.get("score", 0))
    except (TypeError, ValueError):
        return 0.0


def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax2, ay2 = float(a["x"]) + float(a["w"]), float(a["y"]) + float(a["h"])
    bx2, by2 = float(b["x"]) + float(b["w"]), float(b["y"]) + float(b["h"])
    iw = max(0.0, min(ax2, bx2) - max(float(a["x"]), float(b["x"])))
    ih = max(0.0, min(ay2, by2) - max(float(a["y"]), float(b["y"])))
    inter = iw * ih
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def _same_merge_group(a: dict[str, Any], b: dict[str, Any], mode: str, threshold: float) -> bool:
    if mode == "centre_distance":
        return math.hypot(float(a["cx"]) - float(b["cx"]), float(a["cy"]) - float(b["cy"])) <= threshold
    return _iou(a, b) >= threshold


def _representative(group: list[dict[str, Any]], keep: str) -> dict[str, Any]:
    if keep == "largest":
        return max(group, key=_area)
    if keep == "first":
        return group[0]
    return max(group, key=_score)


def _merge_group(group: list[dict[str, Any]], keep: str) -> dict[str, Any]:
    rep = dict(_representative(group, keep))
    x1 = min(float(m["x"]) for m in group)
    y1 = min(float(m["y"]) for m in group)
    x2 = max(float(m["x"]) + float(m["w"]) for m in group)
    y2 = max(float(m["y"]) + float(m["h"]) for m in group)
    rep.update({"x": round(x1, 3), "y": round(y1, 3), "w": round(x2 - x1, 3), "h": round(y2 - y1, 3),
                "cx": round((x1 + x2) / 2, 3), "cy": round((y1 + y2) / 2, 3), "merged": len(group)})
    rep["bbox"] = [rep["x"], rep["y"], rep["w"], rep["h"]]
    return rep


def _rect_overlays(matches: list[dict[str, Any]], color: str = "#22c55e") -> list[dict[str, Any]]:
    return [
        {"kind": "rect", "x": m["x"], "y": m["y"], "w": m["w"], "h": m["h"], "angle": m.get("angle", 0),
         "color": color, "width": 2, **({"label": str(m.get("label"))} if m.get("label") else {})}
        for m in matches
    ]


def _inside(region: dict[str, Any], x: float, y: float) -> bool:
    _, _, ex1, ey1 = extent(region)
    w, h = max(1, int(math.ceil(ex1)) + 2), max(1, int(math.ceil(ey1)) + 2)
    mask = mask_for(region, w, h)
    ix, iy = int(round(x)), int(round(y))
    return 0 <= iy < mask.shape[0] and 0 <= ix < mask.shape[1] and bool(mask[iy, ix])


def _labels(text: Any) -> set[str]:
    return {p.strip() for line in str(text or "").splitlines() for p in line.split(",") if p.strip()}


def _cluster_1d(values: list[float], k: int) -> list[float]:
    if k <= 1:
        return [float(np.median(values))]
    arr = np.asarray(values, dtype=np.float64)
    lo, hi = float(arr.min()), float(arr.max())
    centers = np.linspace(lo, hi, k)
    for _ in range(30):
        dist = np.abs(arr[:, None] - centers[None, :])
        labels = dist.argmin(axis=1)
        nxt = centers.copy()
        for i in range(k):
            pts = arr[labels == i]
            if len(pts):
                nxt[i] = float(np.median(pts))
        if np.allclose(nxt, centers):
            break
        centers = nxt
    centers.sort()
    return [float(v) for v in centers]


def _pitch(centers: list[float], fallback: float) -> float:
    if len(centers) < 2:
        return fallback
    diffs = [b - a for a, b in zip(centers, centers[1:]) if b > a]
    return float(np.median(diffs)) if diffs else fallback


def _sort_matches(matches: list[dict[str, Any]], by: str, descending: bool) -> list[dict[str, Any]]:
    if by == "xy" and matches:
        row = max(2.0, min(float(m["h"]) for m in matches) / 2)

        def key(m: dict[str, Any]) -> tuple[int, float]:
            return round(float(m["cy"]) / row), float(m["cx"])
    elif by == "x":
        def key(m: dict[str, Any]) -> float:
            return float(m["cx"])
    elif by == "y":
        def key(m: dict[str, Any]) -> float:
            return float(m["cy"])
    elif by == "score":
        key = _score
    elif by == "label":
        def key(m: dict[str, Any]) -> str:
            return str(m.get("label", ""))
    elif by == "value":
        def key(m: dict[str, Any]) -> Any:
            return m.get("value", "")
    else:
        def key(m: dict[str, Any]) -> float:
            return float(m["cx"])
    return sorted((dict(m) for m in matches), key=key, reverse=descending)


class BoxesMergeTool(Tool):
    key = "boxes_merge"
    label = "Merge boxes"
    description = "Merges overlapping match boxes by IoU or centre distance, optionally only within the same label."
    category = "logic"
    icon = "Combine"
    params = [
        Param("mode", "Mode", kind="select", default="iou", options=MERGE_MODES),
        Param("threshold", "Threshold", kind="number", default=0.5, minimum=0, teach=True),
        Param("same_label_only", "Same label only", kind="boolean", default=False),
        Param("keep", "Keep metadata from", kind="select", default="highest_score", options=MERGE_KEEP),
    ]
    inputs = [Port("matches", "Matches", "matches", required=False), Port("values", "Values", "list", required=False), Port("image", "Image (for display)", "image", required=False)]
    outputs = [Port("matches", "Merged matches", "matches"), Port("count", "Count", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        matches = _boxes(ctx)
        mode = str(ctx.param("mode", "iou"))
        threshold = ctx.number("threshold", 0.5)
        parent = list(range(len(matches)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, a in enumerate(matches):
            for j in range(i + 1, len(matches)):
                b = matches[j]
                if ctx.flag("same_label_only") and str(a.get("label", "")) != str(b.get("label", "")):
                    continue
                if _same_merge_group(a, b, mode, threshold):
                    parent[find(j)] = find(i)
        groups: dict[int, list[dict[str, Any]]] = {}
        for i, m in enumerate(matches):
            groups.setdefault(find(i), []).append(m)
        out = [_merge_group(group, str(ctx.param("keep", "highest_score"))) for _, group in sorted(groups.items())]
        return Result(outputs={"matches": out, "count": len(out)}, overlays=_rect_overlays(out), message=f"{len(matches)} -> {len(out)} boxes")


class BoxesFilterTool(Tool):
    key = "boxes_filter"
    label = "Filter boxes"
    description = "Filters match boxes by size, area, aspect ratio, score, label and whether the centre is inside or outside a region."
    category = "logic"
    icon = "Filter"
    params = [
        Param("min_width", "Min width", kind="number", default=0, minimum=0, group="Size", teach=True),
        Param("max_width", "Max width", kind="number", default=0, minimum=0, group="Size", teach=True),
        Param("min_height", "Min height", kind="number", default=0, minimum=0, group="Size", teach=True),
        Param("max_height", "Max height", kind="number", default=0, minimum=0, group="Size", teach=True),
        Param("min_area", "Min area", kind="number", default=0, minimum=0, group="Size", teach=True),
        Param("max_area", "Max area", kind="number", default=0, minimum=0, group="Size", teach=True),
        Param("min_aspect", "Min aspect", kind="number", default=0, minimum=0, group="Shape"),
        Param("max_aspect", "Max aspect", kind="number", default=0, minimum=0, group="Shape"),
        Param("min_score", "Min score", kind="range", default=0, minimum=0, maximum=1, step=0.01, teach=True),
        Param("max_score", "Max score", kind="range", default=1, minimum=0, maximum=1, step=0.01),
        Param("labels", "Labels", kind="multiline", default="", help_text="Comma-separated or one label per line. Blank keeps all."),
        Param("roi", "Position ROI", kind="roi", shapes=["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon"]),
        Param("roi_mode", "ROI mode", kind="select", default="inside", options=ROI_MODES),
    ]
    inputs = [Port("matches", "Matches", "matches", required=False), Port("values", "Values", "list", required=False), Port("roi", "Position ROI (dynamic)", "region", required=False), Port("image", "Image (for display)", "image", required=False)]
    outputs = [Port("matches", "Filtered matches", "matches"), Port("count", "Count", "number"), Port("removed", "Removed", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        matches = _boxes(ctx)
        keep_labels = _labels(ctx.param("labels", ""))
        region = ctx.roi()
        out: list[dict[str, Any]] = []
        for m in matches:
            area = _area(m)
            aspect = float(m["w"]) / float(m["h"])
            ok = (
                float(m["w"]) >= ctx.number("min_width", 0)
                and (ctx.number("max_width", 0) <= 0 or float(m["w"]) <= ctx.number("max_width", 0))
                and float(m["h"]) >= ctx.number("min_height", 0)
                and (ctx.number("max_height", 0) <= 0 or float(m["h"]) <= ctx.number("max_height", 0))
                and area >= ctx.number("min_area", 0)
                and (ctx.number("max_area", 0) <= 0 or area <= ctx.number("max_area", 0))
                and aspect >= ctx.number("min_aspect", 0)
                and (ctx.number("max_aspect", 0) <= 0 or aspect <= ctx.number("max_aspect", 0))
                and ctx.number("min_score", 0) <= _score(m) <= ctx.number("max_score", 1)
                and (not keep_labels or str(m.get("label", "")) in keep_labels)
            )
            if ok and region is not None:
                hit = _inside(region, float(m["cx"]), float(m["cy"]))
                ok = hit if str(ctx.param("roi_mode", "inside")) == "inside" else not hit
            if ok:
                out.append(m)
        removed = len(matches) - len(out)
        overlays = ([region_overlay(region, label=str(ctx.param("roi_mode", "inside")))] if region else []) + _rect_overlays(out)
        return Result(outputs={"matches": out, "count": len(out), "removed": removed}, overlays=overlays, message=f"{len(out)} kept, {removed} removed")


class ArrayCorrectTool(Tool):
    key = "array_correct"
    label = "Correct array"
    description = "Fills missing cells in a rows by columns grid of boxes and reports the missing indices and estimated positions."
    category = "logic"
    icon = "Grid3x3"
    params = [
        Param("rows", "Rows", kind="number", default=1, minimum=1, maximum=200, teach=True),
        Param("cols", "Columns", kind="number", default=1, minimum=1, maximum=200, teach=True),
        Param("tolerance", "Tolerance", kind="number", default=0.35, minimum=0, teach=True, help_text="Pixels when >= 1; otherwise a fraction of the grid pitch."),
    ]
    inputs = [Port("matches", "Matches", "matches", required=False), Port("values", "Values", "list", required=False), Port("image", "Image (for display)", "image", required=False)]
    outputs = [flow_out("ok", "Complete", "ok"), flow_out("ng", "Missing", "critical"), Port("matches", "Corrected matches", "matches"), Port("missing", "Missing cells", "list"), Port("ok", "Complete", "bool"), Port("ng", "Has missing", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        matches = _boxes(ctx)
        rows, cols = ctx.integer("rows", 1), ctx.integer("cols", 1)
        if rows <= 0 or cols <= 0:
            raise ToolError("Rows and columns must be positive")
        if not matches:
            raise ToolError("array_correct needs at least one match to infer the grid")
        xs = [float(m["cx"]) for m in matches]
        ys = [float(m["cy"]) for m in matches]
        col_centers = _cluster_1d(xs, cols)
        row_centers = _cluster_1d(ys, rows)
        pitch_x = _pitch(col_centers, float(np.median([m["w"] for m in matches])))
        pitch_y = _pitch(row_centers, float(np.median([m["h"] for m in matches])))
        allowed = ctx.number("tolerance", 0.35)
        allowed_x = allowed if allowed >= 1 else allowed * max(pitch_x, 1.0)
        allowed_y = allowed if allowed >= 1 else allowed * max(pitch_y, 1.0)
        cells: dict[tuple[int, int], dict[str, Any]] = {}
        for m in matches:
            r = min(range(rows), key=lambda i: abs(float(m["cy"]) - row_centers[i]))
            c = min(range(cols), key=lambda i: abs(float(m["cx"]) - col_centers[i]))
            if abs(float(m["cx"]) - col_centers[c]) > allowed_x or abs(float(m["cy"]) - row_centers[r]) > allowed_y:
                continue
            prev = cells.get((r, c))
            if prev is None or _score(m) > _score(prev):
                item = dict(m)
                item.update({"grid_row": r, "grid_col": c, "grid_index": r * cols + c, "filled": bool(item.get("filled", False))})
                cells[(r, c)] = item
        med_w = float(np.median([m["w"] for m in matches]))
        med_h = float(np.median([m["h"] for m in matches]))
        missing: list[dict[str, Any]] = []
        out: list[dict[str, Any]] = []
        for r in range(rows):
            for c in range(cols):
                idx = r * cols + c
                item = cells.get((r, c))
                if item is not None:
                    out.append(item)
                    continue
                cx, cy = col_centers[c], row_centers[r]
                item = {"cx": round(cx, 3), "cy": round(cy, 3), "w": round(med_w, 3), "h": round(med_h, 3),
                        "x": round(cx - med_w / 2, 3), "y": round(cy - med_h / 2, 3), "score": 0.0,
                        "label": "filled", "filled": True, "grid_row": r, "grid_col": c, "grid_index": idx}
                item["bbox"] = [item["x"], item["y"], item["w"], item["h"]]
                missing.append({"index": idx, "row": r, "col": c, "cx": item["cx"], "cy": item["cy"], "x": item["x"], "y": item["y"], "w": item["w"], "h": item["h"]})
                out.append(item)
        ok = not missing
        return Result(outputs={"matches": out, "missing": missing, "ok": ok, "ng": not ok}, overlays=_rect_overlays(out, "#22c55e") + _rect_overlays([m for m in out if m.get("filled")], "#ef4444"),
                      branch="ok" if ok else "ng", status="ok" if ok else "ng", message=f"{len(missing)} missing of {rows * cols}")


class ListSortTool(Tool):
    key = "list_sort"
    label = "Sort list"
    description = "Sorts values or match boxes by value, position, score or label."
    category = "logic"
    icon = "ArrowDownAZ"
    params = [
        Param("by", "Sort by", kind="select", default="xy", options=SORT_BY),
        Param("descending", "Descending", kind="boolean", default=False),
    ]
    inputs = [Port("matches", "Matches", "matches", required=False), Port("values", "Values", "list", required=False)]
    outputs = [Port("matches", "Sorted matches", "matches"), Port("values", "Sorted values", "list"), Port("count", "Count", "number"), Port("first", "First", "any")]

    def execute(self, ctx: ToolContext) -> Result:
        has_matches = "matches" in ctx.inputs
        has_values = "values" in ctx.inputs
        if has_matches and has_values:
            raise ToolError("Connect either matches or values, not both")
        by = str(ctx.param("by", "xy"))
        desc = ctx.flag("descending")
        if has_matches:
            matches = _sort_matches(_boxes(ctx), by, desc)
            return Result(outputs={"matches": matches, "values": [], "count": len(matches), "first": matches[0] if matches else None},
                          overlays=_rect_overlays(matches), message=f"{len(matches)} sorted by {by}")
        values = _value_list(ctx)
        if by != "value":
            raise ToolError("Values can only be sorted by value")
        try:
            sorted_values = sorted(values, reverse=desc)
        except TypeError:
            sorted_values = sorted(values, key=lambda v: str(v), reverse=desc)
        return Result(outputs={"matches": [], "values": sorted_values, "count": len(sorted_values), "first": sorted_values[0] if sorted_values else None},
                      message=f"{len(sorted_values)} sorted by value")


TOOLS = [BoxesMergeTool(), BoxesFilterTool(), ArrayCorrectTool(), ListSortTool()]
