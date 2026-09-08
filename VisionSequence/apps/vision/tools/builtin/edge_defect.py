"""邊緣缺陷：沿一條參考邊（直線或圓弧）佈卡尺，把「不該有的」找出來並分類。

現場講的是缺口、崩邊、毛刺、斷裂、階差、寬度不對——這些其實是同一件事的不同樣子：
**沿著理想的邊等距量一排，看哪幾段偏離**。所以這個工具只做四件事：

1. 沿參考邊佈卡尺（`locate.caliper_series`，直線與圓弧共用一條程式路徑）
2. 把結果變成一條序列（單邊＝偏離理想邊多少，成對＝兩邊之間有多寬）
3. 基線 → 偏差 → 門檻 → 連續超標的串成一段（`tools/defects.py`，與序列缺陷同一套）
4. 每一段分類（偏移／斷裂／階差／寬度）並算出它的外框、長度與面積

參考邊可以是畫布上畫的 ROI（矩形→直線、圓／圓環→圓弧），也可以接上游找線／找圓的結果——
量的是「離理想邊多遠」，理想邊當然可以由前一步決定。
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from apps.vision.tools import defects
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.locate import (
    CaliperHit,
    arc_geometry,
    caliper_series,
    fit_circle_lsq,
    fit_points_line,
    hit_points,
    line_geometry,
    to_gray,
)
from apps.vision.tools.roi import region_overlay

#: 缺陷種類（產品表面用得到的字）。
DEFECT_TYPES = ("dislocation", "fracture", "step", "width")
#: 缺陷的顏色（畫在影像上）。
_COLORS = {"dislocation": "#f59e0b", "fracture": "#ef4444", "step": "#a855f7", "width": "#0ea5e9"}


def step_flags(values: np.ndarray, threshold: float) -> np.ndarray:
    """階差：相鄰兩把卡尺之間跳了多少。回與序列等長的布林（跳變的那兩個位置都標記）。

    偏移是「一整段都偏了」，階差是「這裡忽然接不上」——一個看絕對值、一個看一階差分，
    兩種在現場是不同的不良（貼合錯位 vs. 邊緣崩一個角），所以分開判。
    """
    out = np.zeros(len(values), dtype=bool)
    if len(values) < 2 or threshold <= 0:
        return out
    jump = np.abs(np.diff(values))
    bad = np.isfinite(jump) & (jump > threshold)
    out[:-1] |= bad
    out[1:] |= bad
    return out


def defect_rect(points: np.ndarray) -> dict[str, float] | None:
    """一段缺陷涵蓋的點 → 最小外接矩形（全圖座標，角度依平台慣例：順時針為正）。"""
    pts = np.asarray([p for p in points if np.all(np.isfinite(p))], dtype=np.float32)
    if len(pts) < 2:
        return None
    (cx, cy), (w, h), angle = cv2.minAreaRect(pts)
    return {"shape": "rotated_rect", "cx": round(float(cx), 3), "cy": round(float(cy), 3),
            "w": round(float(max(w, 1.0)), 3), "h": round(float(max(h, 1.0)), 3), "angle": round(float(angle), 3)}


def _reference(ctx: ToolContext, image: np.ndarray) -> tuple[str, tuple, dict[str, Any] | None]:
    """參考邊：上游接進來的線／圓優先，其次畫布上畫的 ROI。回 (kind, 幾何參數, 要畫的標記)。"""
    line = ctx.inputs.get("line")
    circle = ctx.inputs.get("circle")
    if isinstance(circle, dict) and all(k in circle for k in ("cx", "cy", "r")):
        return "arc", (float(circle["cx"]), float(circle["cy"]), float(circle["r"]), 0.0, 360.0), \
            {"kind": "circle", "cx": float(circle["cx"]), "cy": float(circle["cy"]), "r": float(circle["r"]), "color": "#38bdf8", "dash": True}
    if isinstance(line, dict) and all(k in line for k in ("x1", "y1", "x2", "y2")):
        ends = (float(line["x1"]), float(line["y1"]), float(line["x2"]), float(line["y2"]))
        return "line", ends, {"kind": "line", **{k: ends[i] for i, k in enumerate(("x1", "y1", "x2", "y2"))}, "color": "#38bdf8", "dash": True}
    region = ctx.roi()
    if region is None:
        raise ToolError("Draw a region along the edge, or wire a line or a circle in from a locate step")
    shape = str(region.get("shape") or "")
    if shape in ("circle", "annulus"):
        cx, cy = float(region["cx"]), float(region["cy"])
        radius = float(region.get("r", region.get("r_outer", 0)) or 0)
        if shape == "annulus":
            radius = (float(region["r_inner"]) + float(region["r_outer"])) / 2
        a0 = float(region.get("a0", 0) or 0)
        a1 = float(region.get("a1", 360) or 360)
        return "arc", (cx, cy, radius, a0, a1), region_overlay(region, label="reference")
    if shape in ("rect", "rotated_rect"):
        if shape == "rect":
            cx = float(region["x"]) + float(region["w"]) / 2
            cy = float(region["y"]) + float(region["h"]) / 2
            rw, rh, ang = float(region["w"]), float(region["h"]), 0.0
        else:
            cx, cy = float(region["cx"]), float(region["cy"])
            rw, rh, ang = float(region["w"]), float(region["h"]), float(region.get("angle", 0))
        horizontal = rw >= rh
        length = rw if horizontal else rh
        rad = math.radians(ang)
        ux, uy = (math.cos(rad), math.sin(rad)) if horizontal else (-math.sin(rad), math.cos(rad))
        half = length / 2
        ends = (cx - ux * half, cy - uy * half, cx + ux * half, cy + uy * half)
        return "line", ends, region_overlay(region, label="reference")
    raise ToolError("The region has to be a rectangle (a straight edge) or a circle (a round edge)")


class EdgeDefectTool(Tool):
    key = "edge_defect"
    label = "Edge defects"
    description = (
        "Checks a whole edge at once instead of measuring it at one place: calipers are laid along the edge — straight or "
        "round — and every stretch that strays from the ideal edge is reported with what kind of fault it is. A nick or a burr "
        "is a run that sits too far in or out, a chip is a run where the edge vanished altogether, a mismatch is a sudden step "
        "between neighbours, and with a pair of edges the width itself is checked. Each fault comes back with its box, its "
        "length along the edge and its area, so the judgement can be on the worst one or on how many there are."
    )
    category = "detect"
    icon = "Waves"
    params = [
        Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect", "circle", "annulus"],
              help_text="Along a straight edge draw a rectangle (the long side runs along the edge); round an edge draw a circle or a ring. A line or circle wired in from a locate step wins over this."),
        Param("mode", "What each caliper looks for", kind="select", default="single", options=[
            {"value": "single", "label": "One edge"}, {"value": "pair", "label": "A pair of edges (a rib, a groove, a gap)"},
        ]),
        Param("polarity", "Edge polarity", kind="select", default="any", options=[
            {"value": "any", "label": "Either"}, {"value": "dark_to_light", "label": "Dark to light"}, {"value": "light_to_dark", "label": "Light to dark"},
        ], visible_when={"param": "mode", "in": ["single"]}, teach=True),
        Param("pair_polarity", "The band between the edges is", kind="select", default="any", options=[
            {"value": "any", "label": "Either"}, {"value": "bright", "label": "Brighter"}, {"value": "dark", "label": "Darker"},
        ], visible_when={"param": "mode", "in": ["pair"]}, teach=True),
        Param("calipers", "Calipers", kind="number", default=60, minimum=4, maximum=1000,
              help_text="How many places along the edge are checked. More finds smaller faults and takes longer."),
        Param("search", "Search range", kind="number", default=20, minimum=2, maximum=2000, unit="px", teach=True,
              help_text="How far either side of the ideal edge each caliper looks."),
        Param("caliper_width", "Caliper width", kind="number", default=3, minimum=1, maximum=99, unit="px",
              help_text="Averaged along the edge to quieten noise."),
        Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("baseline", "The ideal edge is", kind="select", default="fit", options=[
            {"value": "fit", "label": "Fitted to what was found (a line or a circle)"},
            {"value": "median", "label": "A moving median (follows a gentle curve)"},
            {"value": "reference", "label": "Exactly the region or the wired-in shape"},
        ], help_text="Fitted suits a part that moves; the region itself suits a fixture where the edge must be in one place."),
        Param("window", "Median window", kind="number", default=9, minimum=3, maximum=999, group="Advanced",
              visible_when={"param": "baseline", "in": ["median"]}),
        Param("threshold", "Out by more than", kind="number", default=2.0, minimum=0, step=0.1, unit="px", teach=True,
              help_text="A stretch further than this from the ideal edge is a fault."),
        Param("min_width", "At least this many calipers", kind="number", default=2, minimum=1, teach=True,
              help_text="Stops single-caliper noise being called a fault."),
        Param("direction", "Which side counts", kind="select", default="both", options=[
            {"value": "both", "label": "Either side"}, {"value": "inward", "label": "Only missing material"}, {"value": "outward", "label": "Only extra material"},
        ], teach=True),
        Param("fracture_run", "A break is this many calipers with no edge", kind="number", default=2, minimum=1, teach=True,
              help_text="A caliper that finds no edge at all usually means the edge is gone there. 0 turns this off."),
        Param("step_threshold", "A step between neighbours over", kind="number", default=0, minimum=0, step=0.1, unit="px", teach=True,
              help_text="A sudden jump from one caliper to the next: a mismatch or a broken corner. 0 turns this off."),
        Param("width_min", "Width at least", kind="number", default=0, minimum=0, unit="px", teach=True,
              visible_when={"param": "mode", "in": ["pair"]}, help_text="0 = do not check."),
        Param("width_max", "Width at most", kind="number", default=0, minimum=0, unit="px", teach=True,
              visible_when={"param": "mode", "in": ["pair"]}, help_text="0 = do not check."),
        Param("max_defects", "More faults than this is a reject", kind="number", default=0, minimum=0, teach=True,
              help_text="0 = any fault is a reject."),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
        Param("edge_select", "Which edge", kind="select", default="strongest", options=[
            {"value": "strongest", "label": "Strongest"}, {"value": "first", "label": "First"}, {"value": "last", "label": "Last"},
        ], group="Advanced", visible_when={"param": "mode", "in": ["single"]}),
    ]
    inputs = [
        Port("image", "Image", "image"),
        Port("roi", "Region (dynamic)", "region", required=False),
        Port("line", "Ideal line", "any", required=False),
        Port("circle", "Ideal circle", "any", required=False),
    ]
    outputs = [
        flow_out("ok", "Clean", "ok"), flow_out("defect", "Faults found", "critical"),
        Port("count", "How many", "number"), Port("defects", "Faults", "list"),
        Port("max_deviation", "Worst deviation", "number"), Port("max_size", "Longest fault", "number"),
        Port("total_area", "Total area", "number"),
        Port("points", "Edge points", "points"), Port("deviation", "Deviation", "list"), Port("widths", "Widths", "list"),
        Port("image", "Image", "image"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        kind, geometry, reference_overlay = _reference(ctx, image)
        count = ctx.integer("calipers", 60)
        wrap = kind == "arc" and abs(geometry[4] - geometry[3]) >= 359.9
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
        series = np.array([h.width if pair else h.offset for h in hits], dtype=np.float64)
        series[[not h.found for h in hits]] = np.nan
        baseline = self._baseline(ctx, hits, series, kind, geometry, wrap, pair)
        deviation = series - baseline
        found = np.array([h.found for h in hits], dtype=bool)
        flags, kinds = self._flags(ctx, deviation, found, series, pair, wrap)
        runs = self._runs(ctx, flags, kinds, wrap)
        items = self._describe(runs, hits, deviation, series, positions, pair)
        limit = ctx.integer("max_defects", 0)
        bad = len(items) > limit if limit else bool(items)
        overlays: list[dict[str, Any]] = [reference_overlay] if reference_overlay else []
        overlays.append({"kind": "points", "points": [[round(h.x, 2), round(h.y, 2)] for h in hits if h.found], "color": "#22c55e"})
        if pair:
            overlays.append({"kind": "points", "points": [[round(h.x2, 2), round(h.y2, 2)] for h in hits if h.found], "color": "#a78bfa"})
        for item in items:
            if item["rect"]:
                overlays.append({**item["rect"], "kind": "rect" if item["rect"]["angle"] == 0 else "rect",
                                 "x": item["rect"]["cx"] - item["rect"]["w"] / 2, "y": item["rect"]["cy"] - item["rect"]["h"] / 2,
                                 "w": item["rect"]["w"], "h": item["rect"]["h"], "angle": item["rect"]["angle"],
                                 "color": _COLORS.get(item["type"], "#ef4444"), "width": 2, "label": item["type"]})
        worst = max((abs(i["peak"] or 0.0) for i in items), default=0.0)
        longest = max((i["size"] for i in items), default=0.0)
        return Result(
            outputs={
                "count": len(items), "defects": items,
                "max_deviation": round(float(worst), 4), "max_size": round(float(longest), 4),
                "total_area": round(float(sum(i["area"] for i in items)), 4),
                "points": [[round(h.x, 2), round(h.y, 2)] for h in hits if h.found],
                "deviation": [None if not np.isfinite(v) else round(float(v), 4) for v in deviation],
                "widths": [None if not h.found else round(float(h.width), 4) for h in hits] if pair else [],
                "image": image,
            },
            overlays=overlays, branch="defect" if bad else "ok", status="ng" if bad else "ok",
            message=(f"{len(items)} faults, worst {worst:.2f}px over {longest:.1f}px"
                     if items else f"clean ({int(found.sum())}/{len(hits)} calipers found the edge)"),
        )

    # -- 內部 ---------------------------------------------------------------
    @staticmethod
    def _baseline(ctx: ToolContext, hits: list[CaliperHit], series: np.ndarray, kind: str,
                  geometry: tuple, wrap: bool, pair: bool) -> np.ndarray:
        """理想邊：擬合、滑動中位數，或就是參考幾何本身（offset 的 0）。

        成對模式量的是**寬度**，理想值是「這條邊平常多寬」——所以基線一律取中位數
        （或滑動中位數），不會去擬合一條線。寬度的絕對上下限另外用 width_min／width_max 判。
        """
        mode = str(ctx.param("baseline", "fit"))
        n = len(series)
        if mode == "median":
            return defects.moving_median(series, ctx.integer("window", 9), wrap)
        if pair:
            return np.full(n, float(np.nanmedian(series)) if np.isfinite(series).any() else np.nan)
        if mode == "reference":
            return np.zeros(n) if not np.isnan(series).all() else np.full(n, np.nan)
        # fit：單邊沿直線用擬合線、沿圓弧用擬合圓；成對就用中位數寬度
        finite = np.isfinite(series)
        if finite.sum() < 3:
            return np.full(n, float(np.nanmedian(series)) if finite.any() else np.nan)
        points = np.asarray(hit_points(hits), dtype=np.float64)
        if kind == "arc" and len(points) >= 5:
            fitted = fit_circle_lsq(points)
            if fitted is not None:
                fx, fy, radius = fitted
                out = np.full(n, np.nan)
                for i, h in enumerate(hits):
                    if not h.found:
                        continue
                    # 卡尺中心到擬合圓的距離差，就是這一把的理想 offset
                    out[i] = -(math.hypot(h.cx - fx, h.cy - fy) - radius)
                return out
        if kind == "line" and len(points) >= 2:
            fitted = fit_points_line(points, ransac=True, tol=max(1.0, ctx.number("threshold", 2.0) * 2))
            if fitted is not None:
                vx, vy, x0, y0, _ = fitted
                nx, ny = -vy, vx
                out = np.full(n, np.nan)
                for i, h in enumerate(hits):
                    if h.found:
                        signed = (h.cx - x0) * nx + (h.cy - y0) * ny
                        out[i] = -signed
                return out
        return np.full(n, float(np.nanmedian(series)))

    @staticmethod
    def _flags(ctx: ToolContext, deviation: np.ndarray, found: np.ndarray, series: np.ndarray,
               pair: bool, wrap: bool) -> tuple[np.ndarray, list[str]]:
        """每個位置是不是缺陷，以及它是哪一種（同一個位置可能兩種都中，取第一個成立的）。"""
        n = len(deviation)
        threshold = ctx.number("threshold", 2.0)
        direction = str(ctx.param("direction", "both"))
        kinds = [""] * n
        flags = np.zeros(n, dtype=bool)
        if threshold > 0:
            over = np.isfinite(deviation) & (np.abs(deviation) > threshold)
            if direction == "inward":
                over &= deviation < 0
            elif direction == "outward":
                over &= deviation > 0
            for i in np.nonzero(over)[0]:
                flags[i], kinds[i] = True, "dislocation"
        step = ctx.number("step_threshold", 0)
        if step > 0:
            for i in np.nonzero(step_flags(series, step))[0]:
                if not flags[i]:
                    flags[i], kinds[i] = True, "step"
        if pair:
            low, high = ctx.number("width_min", 0), ctx.number("width_max", 0)
            bad_width = np.zeros(n, dtype=bool)
            if low > 0:
                bad_width |= np.isfinite(series) & (series < low)
            if high > 0:
                bad_width |= np.isfinite(series) & (series > high)
            for i in np.nonzero(bad_width)[0]:
                if not flags[i]:
                    flags[i], kinds[i] = True, "width"
        run = ctx.integer("fracture_run", 2)
        if run > 0:
            missing = ~found
            for start, end in defects.segments(missing, wrap):
                if defects.seg_len((start, end), n) >= run:
                    for i in defects.seg_indices((start, end), n):
                        flags[i], kinds[i] = True, "fracture"
        return flags, kinds

    @staticmethod
    def _runs(ctx: ToolContext, flags: np.ndarray, kinds: list[str], wrap: bool) -> list[tuple[int, int, str]]:
        """連續的缺陷位置串成一段；太短的丟掉（單點雜訊）。"""
        n = len(flags)
        min_width = ctx.integer("min_width", 2)
        out: list[tuple[int, int, str]] = []
        for start, end in defects.segments(flags, wrap):
            indices = defects.seg_indices((start, end), n)
            kind_counts: dict[str, int] = {}
            for i in indices:
                kind_counts[kinds[i]] = kind_counts.get(kinds[i], 0) + 1
            worst = max(kind_counts, key=lambda k: (k == "fracture", kind_counts[k]))
            if len(indices) < min_width and worst != "fracture":
                continue
            out.append((start, end, worst or "dislocation"))
        return out

    @staticmethod
    def _describe(runs: list[tuple[int, int, str]], hits: list[CaliperHit], deviation: np.ndarray,
                  series: np.ndarray, positions: np.ndarray, pair: bool) -> list[dict[str, Any]]:
        """每一段缺陷的完整描述：外框、沿邊長度、面積、最嚴重的那一點。"""
        n = len(hits)
        items: list[dict[str, Any]] = []
        for start, end, kind in runs:
            indices = defects.seg_indices((start, end), n)
            points: list[list[float]] = []
            for i in indices:
                h = hits[i]
                if h.found:
                    points.append([h.x, h.y])
                    if pair:
                        points.append([h.x2, h.y2])
                else:
                    points.append([h.cx, h.cy])  # 打空的位置用卡尺中心，缺口才框得起來
            values = np.array([deviation[i] for i in indices], dtype=np.float64)
            finite = values[np.isfinite(values)]
            peak = float(finite[np.argmax(np.abs(finite))]) if len(finite) else float("nan")
            span = float(np.hypot(*(np.asarray(points[-1]) - np.asarray(points[0])))) if len(points) >= 2 else 0.0
            rect = defect_rect(np.asarray(points, dtype=np.float64))
            area = float(rect["w"] * rect["h"]) if rect else 0.0
            items.append({
                "type": kind, "start": int(start), "end": int(end), "count": len(indices),
                "size": round(span, 3), "area": round(area, 3),
                "peak": round(peak, 4) if np.isfinite(peak) else None,
                "direction": ("outward" if peak > 0 else "inward") if np.isfinite(peak) else "missing",
                "position": round(float(positions[start]), 3),
                "rect": rect,
            })
        return items


TOOLS = [EdgeDefectTool()]
