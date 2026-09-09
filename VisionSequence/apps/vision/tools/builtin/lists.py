"""框與清單的後處理工具。"""

from __future__ import annotations

import math
import re
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
OVERLAP_METRICS = [{"value": "iou", "label": "IoU"}, {"value": "a_area", "label": "Overlap / A area"}]
OVERLAP_MODES = [{"value": "any", "label": "Any overlap is OK"}, {"value": "none", "label": "No overlap is OK"}]
FILTER_OPS = [
    {"value": "gt", "label": ">"},
    {"value": "ge", "label": ">="},
    {"value": "lt", "label": "<"},
    {"value": "le", "label": "<="},
    {"value": "eq", "label": "="},
    {"value": "ne", "label": "!="},
    {"value": "between", "label": "Between"},
    {"value": "in", "label": "In list"},
    {"value": "regex", "label": "Regex"},
    {"value": "nonempty", "label": "Non-empty"},
]
PICK_BY = [
    {"value": "index", "label": "Index"},
    {"value": "first", "label": "First"},
    {"value": "last", "label": "Last"},
    {"value": "min", "label": "Minimum"},
    {"value": "max", "label": "Maximum"},
    {"value": "nearest", "label": "Nearest to point"},
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


def _boxes_from_value(raw: Any, port: str) -> list[dict[str, Any]]:
    proxy = ToolContext(
        run_id="", flow_id=0, node={"params": {}}, inputs={"matches": raw},
        context={}, moment=0.0, log=lambda *a, **k: None, asset_path=lambda aid: None, grab=lambda sid: None,
    )
    try:
        return _boxes(proxy)
    except ToolError as exc:
        raise ToolError(f"{port}: {exc}") from None


def _data_input(ctx: ToolContext) -> tuple[str, list[Any]]:
    has_matches = "matches" in ctx.inputs
    has_values = "values" in ctx.inputs
    if has_matches and has_values:
        raise ToolError("Connect either matches or values, not both")
    if has_matches:
        return "matches", _boxes(ctx)
    if has_values:
        return "values", _value_list(ctx)
    raise ToolError("Connect a values or matches list")


def _pick_input(ctx: ToolContext) -> tuple[str, list[Any]]:
    present = [key for key in ("values", "matches", "points") if key in ctx.inputs]
    if len(present) > 1:
        raise ToolError("Connect only one of values, matches or points")
    if not present:
        raise ToolError("Connect values, matches or points")
    key = present[0]
    if key == "matches":
        return key, _boxes(ctx)
    if key == "values":
        return key, _value_list(ctx)
    points = ctx.inputs.get("points")
    try:
        arr = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    except (TypeError, ValueError):
        raise ToolError("Points must be a list of [x, y] pairs") from None
    return key, [[float(x), float(y)] for x, y in arr]


def _field_value(item: Any, field: str) -> Any:
    if isinstance(item, dict):
        if field:
            return item.get(field)
        return item.get("value", item.get("score", item.get("cx")))
    return item


def _number_or_none(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _truthy_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _split_choices(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {str(v) for v in value}
    return {p.strip() for line in str(value or "").splitlines() for p in line.split(",") if p.strip()}


def _passes_filter(actual: Any, op: str, value: Any, value2: Any) -> bool:
    if op == "nonempty":
        return _truthy_nonempty(actual)
    if op == "regex":
        try:
            return re.search(str(value or ""), str(actual or "")) is not None
        except re.error:
            return False
    if op == "in":
        return str(actual) in _split_choices(value)
    left = _number_or_none(actual)
    right = _number_or_none(value)
    if left is not None and right is not None:
        if op == "gt":
            return left > right
        if op == "ge":
            return left >= right
        if op == "lt":
            return left < right
        if op == "le":
            return left <= right
        if op == "between":
            high = _number_or_none(value2)
            if high is None:
                return False
            lo, hi = sorted((right, high))
            return lo <= left <= hi
        if op == "eq":
            return left == right
        if op == "ne":
            return left != right
    if op == "eq":
        return str(actual) == str(value)
    if op == "ne":
        return str(actual) != str(value)
    return False


def _parse_classes(text: Any) -> list[tuple[str, float | None, float | None]]:
    classes: list[tuple[str, float | None, float | None]] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            raise ToolError("Each class must be name:lower,upper")
        name, bounds = line.split(":", 1)
        parts = [p.strip() for p in bounds.split(",")]
        if len(parts) != 2:
            raise ToolError("Each class must have lower and upper bounds")
        lo = None if parts[0] == "" else _number_or_none(parts[0])
        hi = None if parts[1] == "" else _number_or_none(parts[1])
        if (parts[0] and lo is None) or (parts[1] and hi is None):
            raise ToolError("Class bounds must be numeric or blank")
        classes.append((name.strip() or f"class_{len(classes) + 1}", lo, hi))
    if not classes:
        raise ToolError("At least one class is required")
    return classes


def _point_of(item: Any) -> tuple[float, float] | None:
    if isinstance(item, dict):
        x = item.get("cx", item.get("x"))
        y = item.get("cy", item.get("y"))
    elif isinstance(item, (list, tuple, np.ndarray)) and len(item) >= 2:
        x, y = item[0], item[1]
    else:
        return None
    try:
        out = float(x), float(y)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out).all() else None


def _overlap_ratio(a: dict[str, Any], b: dict[str, Any], metric: str) -> float:
    ax2, ay2 = float(a["x"]) + float(a["w"]), float(a["y"]) + float(a["h"])
    bx2, by2 = float(b["x"]) + float(b["w"]), float(b["y"]) + float(b["h"])
    iw = max(0.0, min(ax2, bx2) - max(float(a["x"]), float(b["x"])))
    ih = max(0.0, min(ay2, by2) - max(float(a["y"]), float(b["y"])))
    inter = iw * ih
    if metric == "a_area":
        denom = _area(a)
    else:
        denom = _area(a) + _area(b) - inter
    return inter / denom if denom > 0 else 0.0


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


class BoxesOverlapTool(Tool):
    key = "boxes_overlap"
    label = "Box overlap"
    description = "Compares match boxes and reports the strongest overlap for each A box."
    category = "logic"
    icon = "PanelsTopLeft"
    params = [
        Param("metric", "Metric", kind="select", default="iou", options=OVERLAP_METRICS),
        Param("min_overlap", "Minimum overlap", kind="range", default=0.5, minimum=0, maximum=1, step=0.01, teach=True),
        Param("mode", "OK mode", kind="select", default="any", options=OVERLAP_MODES),
    ]
    inputs = [
        Port("matches", "A matches", "matches", required=False),
        Port("matches_b", "B matches", "matches", required=False),
        Port("image", "Image (for display)", "image", required=False),
    ]
    outputs = [
        flow_out("ok", "OK", "ok"), flow_out("ng", "NG", "critical"),
        Port("matches", "A matches with overlap", "matches"),
        Port("count", "Count", "number"),
        Port("pairs", "Overlap pairs", "list"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        a_matches = _boxes(ctx)
        b_raw = ctx.inputs.get("matches_b")
        b_matches = _boxes_from_value(b_raw, "matches_b") if isinstance(b_raw, list) and b_raw else a_matches
        metric = str(ctx.param("metric", "iou"))
        threshold = ctx.number("min_overlap", 0.5)
        out: list[dict[str, Any]] = []
        pairs: list[tuple[int, int, float]] = []
        for i, a in enumerate(a_matches):
            best_j = -1
            best = 0.0
            for j, b in enumerate(b_matches):
                if b_matches is a_matches and i == j:
                    continue
                ratio = _overlap_ratio(a, b, metric)
                if ratio > best:
                    best, best_j = ratio, j
            item = dict(a)
            item["overlap"] = round(best, 6)
            item["overlap_index"] = best_j if best_j >= 0 else None
            out.append(item)
            if best_j >= 0 and best >= threshold:
                pairs.append((i, best_j, round(best, 6)))
        count = len(pairs)
        ok = (count > 0) if str(ctx.param("mode", "any")) == "any" else (count == 0)
        overlays = _rect_overlays(a_matches, "#38bdf8") + _rect_overlays(b_matches, "#f59e0b")
        return Result(
            outputs={"matches": out, "count": count, "pairs": pairs},
            overlays=overlays,
            status="ok" if ok else "ng",
            branch="ok" if ok else "ng",
            message=f"{count} overlapping boxes",
        )


class ListFilterTool(Tool):
    key = "list_filter"
    label = "Filter list"
    description = "Filters values or matches by one condition and reports kept indices."
    category = "logic"
    icon = "ListFilter"
    params = [
        Param("field", "Match field", kind="text", default="value", help_text="Used when filtering matches. Blank uses value, score or cx."),
        Param("op", "Condition", kind="select", default="gt", options=FILTER_OPS),
        Param("value", "Value", kind="text", default="0", teach=True),
        Param("value2", "Second value", kind="text", default="", teach=True, visible_when={"param": "op", "in": ["between"]}),
    ]
    inputs = [
        Port("values", "Values", "list", required=False),
        Port("matches", "Matches", "matches", required=False),
        Port("image", "Image (for display)", "image", required=False),
    ]
    outputs = [
        Port("values", "Filtered values", "list"),
        Port("matches", "Filtered matches", "matches"),
        Port("count", "Count", "number"),
        Port("removed", "Removed", "number"),
        Port("indices", "Kept indices", "list"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        kind, items = _data_input(ctx)
        field = str(ctx.param("field", "value") or "")
        op = str(ctx.param("op", "gt"))
        kept: list[Any] = []
        indices: list[int] = []
        for i, item in enumerate(items):
            if _passes_filter(_field_value(item, field) if kind == "matches" else item, op, ctx.param("value", "0"), ctx.param("value2", "")):
                kept.append(dict(item) if isinstance(item, dict) else item)
                indices.append(i)
        removed = len(items) - len(kept)
        outputs = {
            "values": kept if kind == "values" else [],
            "matches": kept if kind == "matches" else [],
            "count": len(kept),
            "removed": removed,
            "indices": indices,
        }
        return Result(
            outputs=outputs,
            overlays=_rect_overlays(outputs["matches"]) if kind == "matches" else [],
            status="ok" if kept else "ng",
            message=f"{len(kept)} kept, {removed} removed",
        )


class ListClassifyTool(Tool):
    key = "list_classify"
    label = "Classify list"
    description = "Classifies values or match fields into named numeric ranges."
    category = "logic"
    icon = "Tags"
    params = [
        Param("field", "Match field", kind="text", default="value", help_text="Used when classifying matches. Blank uses value, score or cx."),
        Param("classes", "Classes", kind="multiline", default="low:,10\nmid:10,20\nhigh:20,", teach=True,
              help_text="One class per line: name:lower,upper. Lower is included, upper is excluded; blank means unbounded."),
    ]
    inputs = [
        Port("values", "Values", "list", required=False),
        Port("matches", "Matches", "matches", required=False),
        Port("image", "Image (for display)", "image", required=False),
    ]
    outputs = [
        Port("labels", "Labels", "list"),
        Port("counts", "Counts", "any"),
        Port("matches", "Classified matches", "matches"),
        Port("dominant", "Dominant class", "string"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        kind, items = _data_input(ctx)
        classes = _parse_classes(ctx.param("classes", ""))
        field = str(ctx.param("field", "value") or "")
        labels: list[str] = []
        counts = {name: 0 for name, _, _ in classes}
        counts["other"] = 0
        out_matches: list[dict[str, Any]] = []
        for item in items:
            value = _field_value(item, field) if kind == "matches" else item
            number = _number_or_none(value)
            label = "other"
            if number is not None:
                for name, lo, hi in classes:
                    if (lo is None or number >= lo) and (hi is None or number < hi):
                        label = name
                        break
            labels.append(label)
            counts[label] = counts.get(label, 0) + 1
            if kind == "matches":
                entry = dict(item)
                entry["class"] = label
                out_matches.append(entry)
        dominant = max(counts.items(), key=lambda kv: (kv[1], kv[0] != "other"))[0] if counts else "other"
        return Result(
            outputs={"labels": labels, "counts": counts, "matches": out_matches, "dominant": dominant},
            overlays=_rect_overlays(out_matches) if kind == "matches" else [],
            status="ok" if labels else "ng",
            message=f"{len(labels)} classified",
        )


class ListPickTool(Tool):
    key = "list_pick"
    label = "Pick from list"
    description = "Picks one value, match or point by index, position, value or nearest point."
    category = "logic"
    icon = "MousePointerClick"
    params = [
        Param("by", "Pick by", kind="select", default="first", options=PICK_BY),
        Param("index", "Index", kind="number", default=0, minimum=0),
        Param("field", "Value field", kind="text", default="value", help_text="Used for min and max on matches. Blank uses value, score or cx."),
        Param("x", "Target X", kind="number", default=0, teach=True, visible_when={"param": "by", "in": ["nearest"]}),
        Param("y", "Target Y", kind="number", default=0, teach=True, visible_when={"param": "by", "in": ["nearest"]}),
    ]
    inputs = [
        Port("values", "Values", "list", required=False),
        Port("matches", "Matches", "matches", required=False),
        Port("points", "Points", "points", required=False),
        Port("image", "Image (for display)", "image", required=False),
    ]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("value", "Picked value", "any"),
        Port("index", "Index", "number"),
    ]

    def _not_found(self, message: str) -> Result:
        return Result(outputs={"value": None, "index": None}, status="ng", branch="not_found", message=message)

    def execute(self, ctx: ToolContext) -> Result:
        kind, items = _pick_input(ctx)
        if not items:
            return self._not_found("No items to pick")
        by = str(ctx.param("by", "first"))
        field = str(ctx.param("field", "value") or "")
        idx: int | None
        if by == "first":
            idx = 0
        elif by == "last":
            idx = len(items) - 1
        elif by == "index":
            idx = ctx.integer("index", 0)
            if idx < 0 or idx >= len(items):
                return self._not_found("Index is outside the list")
        elif by in ("min", "max"):
            scored = [(_number_or_none(_field_value(item, field)), i) for i, item in enumerate(items)]
            scored = [(score, i) for score, i in scored if score is not None]
            if not scored:
                return self._not_found("No numeric item to pick")
            idx = (min if by == "min" else max)(scored, key=lambda pair: pair[0])[1]
        elif by == "nearest":
            tx, ty = ctx.number("x", 0), ctx.number("y", 0)
            pts = [(_point_of(item), i) for i, item in enumerate(items)]
            pts = [(pt, i) for pt, i in pts if pt is not None]
            if not pts:
                return self._not_found("No point-like item to pick")
            idx = min(pts, key=lambda pair: math.hypot(pair[0][0] - tx, pair[0][1] - ty))[1]
        else:
            return self._not_found("Unknown pick mode")
        value = dict(items[idx]) if isinstance(items[idx], dict) else list(items[idx]) if kind == "points" else items[idx]
        point = _point_of(value)
        overlays = [{"kind": "point", "x": point[0], "y": point[1], "color": "#22c55e", "label": "picked"}] if point else []
        return Result(outputs={"value": value, "index": idx}, overlays=overlays, branch="found", message=f"Picked index {idx}")


TOOLS = [
    BoxesMergeTool(), BoxesFilterTool(), ArrayCorrectTool(), ListSortTool(),
    BoxesOverlapTool(), ListFilterTool(), ListClassifyTool(), ListPickTool(),
]
