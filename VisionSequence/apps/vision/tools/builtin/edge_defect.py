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

from apps.vision import fixed_images
from apps.vision.tools import defects
from apps.vision.tools.base import TRANSFORM_IN, Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.contours import _binarize, pixel_area
from apps.vision.tools.builtin.locate import (
    CaliperHit,
    arc_geometry,
    caliper_series,
    fit_circle_lsq,
    fit_points_line,
    hit_points,
    line_geometry,
    polyline_geometry,
    to_gray,
)
from apps.vision.tools.messages import Msg
from apps.vision.tools.roi import apply_transform, crop, region_overlay

#: 缺陷種類（產品表面用得到的字）。
DEFECT_TYPES = ("dislocation", "fracture", "step", "width")
#: 缺陷的顏色（畫在影像上）。
_COLORS = {"dislocation": "#f59e0b", "fracture": "#ef4444", "step": "#a855f7", "width": "#0ea5e9"}


def teach_contour(image: np.ndarray, roi: dict[str, Any] | None = None, simplify: float = 2.0) -> list[list[float]]:
    """從良品影像教出最外層輪廓點集。

    輸入影像會轉灰階後用既有 `contour_find` 的二值化規則（Otsu、亮物件）取外輪廓；
    `roi` 可限制教導範圍，回傳點一律是原影像座標。`simplify` 是 `approxPolyDP` 的像素公差。
    回傳值可直接存成 `edge_model_defect.model` 的 `points`。
    """
    gray = to_gray(image)
    c = crop(gray, roi)
    if c.image.size == 0:
        return []
    mask = _binarize(np.ascontiguousarray(c.image), "otsu", 128, "bright", c.mask)
    if c.mask is not None:
        mask = cv2.bitwise_and(mask, c.mask)
    found, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    found = [cnt for cnt in found if len(cnt) >= 3]
    if not found:
        return []
    cnt = max(found, key=pixel_area)
    eps = max(0.0, float(simplify or 0.0))
    if eps > 0:
        cnt = cv2.approxPolyDP(cnt, eps, True)
    pts = c.points_to_full(cnt.reshape(-1, 2)).astype(np.float64)
    if len(pts) >= 3 and cv2.contourArea(pts.astype(np.float32), oriented=True) > 0:
        pts = pts[::-1]
    return [[round(float(x), 3), round(float(y), 3)] for x, y in pts]


def _model_payload(value: Any, image_shape: tuple[int, ...] | None = None) -> dict[str, Any] | None:
    """整理輪廓模型 JSON；支援正式 dict 與純 points list。"""
    if value in (None, "", []):
        return None
    if isinstance(value, dict):
        points = value.get("points")
        closed = bool(value.get("closed", True))
        size = value.get("image_size") or value.get("size")
        version = int(value.get("version", 1) or 1)
    else:
        points, closed, size, version = value, True, None, 1
    try:
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    except (TypeError, ValueError):
        return None
    if len(pts) < 2:
        return None
    if closed and len(pts) >= 3 and cv2.contourArea(pts.astype(np.float32), oriented=True) > 0:
        pts = pts[::-1]
    if not size and image_shape is not None:
        size = [int(image_shape[1]), int(image_shape[0])]
    return {
        "version": version,
        "image_size": [int(size[0]), int(size[1])] if isinstance(size, (list, tuple)) and len(size) >= 2 else None,
        "closed": closed,
        "points": [[float(x), float(y)] for x, y in pts],
    }


def teach_contour_model(image: np.ndarray, roi: dict[str, Any] | None = None, simplify: float = 2.0) -> tuple[dict[str, Any] | None, list[list[float]]]:
    """把教導輪廓包成 edge_model_defect 執行期自動教導使用的同一份 model JSON。"""
    points = teach_contour(image, roi=roi, simplify=simplify)
    if len(points) < 3:
        return None, points
    model = _model_payload({"version": 1, "image_size": [image.shape[1], image.shape[0]], "closed": True, "points": points})
    return model, points


def _reference_model(ctx: ToolContext, roi: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    """從 reference 固定影像自動教一次輪廓模型；只回本次結果，不寫回節點參數。"""
    refs = ctx.param("reference") or []
    if not isinstance(refs, list) or not refs:
        return None, False
    first = refs[0]
    image_id = first.get("id") if isinstance(first, dict) else ""
    image = fixed_images.load(str(image_id or ""))
    if image is None:
        raise ToolError(Msg.of("edge_defect.reference_missing", "The reference picture is missing; add it again"))
    model, _points = teach_contour_model(image, roi=roi, simplify=ctx.number("teach_simplify", 2.0))
    return model, True


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
        raise ToolError(Msg.of("edge_defect.no_reference", "Draw a region along the edge, or wire a line or a circle in from a locate step"))
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
    raise ToolError(Msg.of("edge_defect.bad_shape", "The region has to be a rectangle (a straight edge) or a circle (a round edge)"))


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
        Param("filter_fractures", "Apply minimum length to gaps", kind="boolean", default=False,
              help_text="Apply the minimum caliper count to every fault, including stretches with no edge."),
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
        Param("closed_sequence", "Closed sequence", kind="boolean", default=False, group="Advanced",
              help_text="Join the ends of a straight scan of an unwrapped full ring. The reference line must span exactly one full period. Seam-crossing geometry may extend past the strip end; restore it with the original mapping."),
        Param("edge_select", "Which edge", kind="select", default="strongest", options=[
            {"value": "strongest", "label": "Strongest"}, {"value": "first", "label": "First"}, {"value": "last", "label": "Last"},
        ], group="Advanced", visible_when={"param": "mode", "in": ["single"]}),
    ]
    inputs = [
        Port("image", "Image", "image"),
        Port("roi", "Region (dynamic)", "region", required=False),
        Port("line", "Ideal line", "any", required=False, accepts_semantics=("line",)),
        Port("circle", "Ideal circle", "any", required=False, accepts_semantics=("circle",)),
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
        period = None
        if kind == "line":
            if bool(ctx.param("closed_sequence", False)):
                # 封閉直線的終點代表下一圈起點，不重複取樣；保留週期向量供跨縫幾何解包。
                period = np.asarray(geometry[2:4], dtype=float) - np.asarray(geometry[:2], dtype=float)
                if np.linalg.norm(period) < 1:
                    raise ToolError(Msg.of("edge_defect.closed_too_short", "A closed sequence needs a reference line at least 1 px long"))
                centers, scan, tangent, positions = (v[:-1] for v in line_geometry(*geometry, count + 1))
                wrap = True
            else:
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
        if ctx.flag("filter_fractures") and not pair and ctx.param("direction", "both") != "both" and found.any():
            # 打空的卡尺沒有 offset；以已找到邊的兩側灰階辨別中心落在材料側或背景側。
            points = np.array([[h.x, h.y] for h in hits if h.found], dtype=np.float32)
            normals = np.asarray(scan[found], dtype=np.float32)
            before = points - normals * 3
            after = points + normals * 3
            def sample(points: np.ndarray) -> np.ndarray:
                return cv2.remap(image, points[:, 0].astype(np.float32), points[:, 1].astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).ravel()
            lo, hi = float(np.median(sample(before))), float(np.median(sample(after)))
            if abs(hi - lo) >= ctx.number("edge_threshold", 20):
                at_center = sample(np.asarray(centers, dtype=np.float32))
                inward = (at_center - (lo + hi) / 2) * (hi - lo) > 0
                keep = inward if ctx.param("direction") == "inward" else ~inward
                for i, fault in enumerate(kinds):
                    if fault == "fracture" and not keep[i]:
                        flags[i] = False
        runs = self._runs(ctx, flags, kinds, wrap)
        items = self._describe(runs, hits, deviation, series, positions, pair, period=period)
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
            message=(Msg.of("edge_defect.faults", "{n} faults, worst {worst:.2f}px over {longest:.1f}px", n=len(items), worst=worst, longest=longest)
                     if items else Msg.of("edge_defect.clean", "clean ({found}/{total} calipers found the edge)", found=int(found.sum()), total=len(hits))),
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
            step_mask = step_flags(series, step)
            if wrap and ctx.param("closed_sequence", False) and len(series) > 1:
                if np.isfinite(series[0]) and np.isfinite(series[-1]) and abs(series[0] - series[-1]) > step:
                    step_mask[0] = step_mask[-1] = True
            for i in np.nonzero(step_mask)[0]:
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
        min_width = ctx.number("min_width", 2) if ctx.flag("filter_fractures") else ctx.integer("min_width", 2)
        out: list[tuple[int, int, str]] = []
        for start, end in defects.segments(flags, wrap):
            indices = defects.seg_indices((start, end), n)
            kind_counts: dict[str, int] = {}
            for i in indices:
                kind_counts[kinds[i]] = kind_counts.get(kinds[i], 0) + 1
            worst = max(kind_counts, key=lambda k: (k == "fracture", kind_counts[k]))
            if len(indices) < min_width and (worst != "fracture" or ctx.flag("filter_fractures")):
                continue
            out.append((start, end, worst or "dislocation"))
        return out

    @staticmethod
    def _describe(runs: list[tuple[int, int, str]], hits: list[CaliperHit], deviation: np.ndarray,
                  series: np.ndarray, positions: np.ndarray, pair: bool, *, period: np.ndarray | None = None) -> list[dict[str, Any]]:
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
                if period is not None and end < start and i < start:
                    for point in points[-(2 if pair and h.found else 1):]:
                        point[0] += period[0]
                        point[1] += period[1]
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
            if period is not None:
                # 解包後再取中心與起訖，避免跨縫缺口的中心被算到半圈之外。
                # 少數過渡點可能落在缺口肩部，中心採解包點的中位數，避免外框把徑向中心拉偏。
                items[-1]["centre"] = np.median(np.asarray(points, dtype=float), axis=0).tolist()
                items[-1]["span"] = [points[0], points[-1]]
        return items


def _model_message(auto_taught: bool, items: list[dict[str, Any]], worst: float, found: int, total: int) -> Msg:
    """edge_model_defect 的一行摘要（英文與改寫前逐字相同）。"""
    if auto_taught:
        if items:
            return Msg.of("edge_model_defect.auto_faults", "auto-taught contour, {n} faults, worst {worst:.2f}px", n=len(items), worst=worst)
        return Msg.of("edge_model_defect.auto_clean", "auto-taught contour, clean ({found}/{total} calipers found the edge)", found=found, total=total)
    if items:
        return Msg.of("edge_model_defect.faults", "{n} faults, worst {worst:.2f}px", n=len(items), worst=worst)
    return Msg.of("edge_model_defect.clean", "clean ({found}/{total} calipers found the edge)", found=found, total=total)


class EdgeModelDefectTool(Tool):
    key = "edge_model_defect"
    label = "Edge model defects"
    description = (
        "Learns a good part outline as a point model, then places normal calipers along that outline on every run. "
        "Each found edge point is compared with the model: inward runs are missing material, outward runs are extra material, "
        "and consecutive missing calipers are chips or breaks. Use it for stamped, gasket, toothed or otherwise free-form outlines."
    )
    category = "detect"
    icon = "Spline"
    params = [
        Param("mode", "Edge mode", kind="select", default="single", options=[
            {"value": "single", "label": "One edge"}, {"value": "pair", "label": "A pair of edges"},
        ], teach=True),
        Param("pair_polarity", "Band polarity", kind="select", default="any", options=[
            {"value": "any", "label": "Either"}, {"value": "bright", "label": "Bright band"},
            {"value": "dark", "label": "Dark band"},
        ], visible_when={"param": "mode", "in": ["pair"]}, teach=True),
        Param("width_min", "Minimum band width", kind="number", default=0, minimum=0, unit="px", teach=True,
              visible_when={"param": "mode", "in": ["pair"]}, help_text="0 disables the lower width limit."),
        Param("width_max", "Maximum band width", kind="number", default=0, minimum=0, unit="px", teach=True,
              visible_when={"param": "mode", "in": ["pair"]}, help_text="0 disables the upper width limit."),
        Param("roi", "Teaching region", kind="roi", shapes=["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon"],
              help_text="Optional region used only when automatically teaching from the reference picture. Leave blank to teach from the whole reference."),
        Param("model", "Contour model", kind="json", default=None,
              help_text=("JSON object: {version:1, image_size:[width,height], closed:true, points:[[x,y],...]}. "
                         "Points are taught image coordinates. For a closed model, points are normalised so positive offsets point outward.")),
        Param("reference", "Reference picture", kind="images",
              help_text="Optional good part picture. If the model is empty, the first picture is used to teach the contour for this run."),
        Param("calipers", "Calipers", kind="number", default=160, minimum=4, maximum=10000,
              help_text="How many places along the model outline are checked. More finds smaller faults and takes longer."),
        Param("search", "Search range", kind="number", default=24, minimum=2, maximum=2000, unit="px", teach=True,
              help_text="Total distance each normal caliper searches across the model outline."),
        Param("caliper_width", "Caliper width", kind="number", default=3, minimum=1, maximum=99, unit="px",
              help_text="Averaged along the outline tangent to quieten noise."),
        Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("polarity", "Edge polarity", kind="select", default="light_to_dark", options=[
            {"value": "any", "label": "Either"}, {"value": "dark_to_light", "label": "Dark to light"}, {"value": "light_to_dark", "label": "Light to dark"},
        ], teach=True),
        Param("edge_select", "Which edge", kind="select", default="strongest", options=[
            {"value": "strongest", "label": "Strongest"}, {"value": "first", "label": "First"}, {"value": "last", "label": "Last"},
        ], group="Advanced"),
        Param("threshold", "Out by more than", kind="number", default=2.0, minimum=0, step=0.1, unit="px", teach=True,
              help_text="A stretch further than this from the taught outline is a fault."),
        Param("min_width", "At least this many calipers", kind="number", default=2, minimum=1, teach=True,
              help_text="Stops single-caliper noise being called a fault."),
        Param("direction", "Which side counts", kind="select", default="both", options=[
            {"value": "both", "label": "Either side"}, {"value": "inward", "label": "Only missing material"}, {"value": "outward", "label": "Only extra material"},
        ], teach=True),
        Param("fracture_run", "A break is this many calipers with no edge", kind="number", default=2, minimum=0, teach=True,
              help_text="A caliper that finds no edge at all usually means the edge is gone there. 0 turns this off."),
        Param("step_threshold", "A step between neighbours over", kind="number", default=0, minimum=0, step=0.1, unit="px", teach=True,
              help_text="A sudden jump from one caliper to the next. 0 turns this off."),
        Param("max_defects", "More faults than this is a reject", kind="number", default=0, minimum=0, teach=True,
              help_text="0 = any fault is a reject."),
        Param("teach_simplify", "Teaching simplification", kind="number", default=2.0, minimum=0, step=0.1, unit="px", group="Advanced",
              help_text="Polygon approximation tolerance used only when the model is empty and a reference picture teaches the contour."),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=31, group="Advanced"),
    ]
    inputs = [
        Port("image", "Image", "image"),
        Port("roi", "Teaching region (dynamic)", "region", required=False),
    ]
    outputs = [
        flow_out("ok", "Clean", "ok"), flow_out("defect", "Faults found", "critical"),
        Port("count", "How many", "number"), Port("defects", "Faults", "list"),
        Port("max_deviation", "Worst deviation", "number"),
        Port("points", "Edge points", "points"), Port("deviations", "Deviations", "list"),
        Port("missing", "Missing indices", "list"), Port("image", "Image", "image"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        teach_roi = ctx.roi()
        model = _model_payload(ctx.param("model"), image.shape)
        auto_taught = False
        if model is None:
            model, auto_taught = _reference_model(ctx, teach_roi)
        if model is None:
            return Result(
                outputs={"count": 0, "defects": [], "max_deviation": 0.0, "points": [], "deviations": [], "missing": [], "image": image},
                overlays=[],
                branch="defect", status="ng",
                message=Msg.of("edge_model_defect.no_model", "No contour model is set, and no reference picture could teach one"),
            )
        points = model["points"]
        closed = bool(model.get("closed", True))
        region = {"shape": "polygon" if closed else "polyline", "points": points}
        if TRANSFORM_IN in ctx.inputs:
            transform = ctx.inputs.get(TRANSFORM_IN)
            if transform is None:
                ctx.fixture_missing = True
            else:
                region = apply_transform(region, transform)
        moved_points = region.get("points") or []
        count = max(4, ctx.integer("calipers", 160))
        centers, scan, tangent, positions = polyline_geometry(moved_points, closed, count=count)
        wrap = closed
        if len(centers) == 0:
            return Result(
                outputs={"count": 0, "defects": [], "max_deviation": 0.0, "points": [], "deviations": [], "missing": [], "image": image},
                overlays=[region_overlay(region, label="model")],
                branch="defect", status="ng", message=Msg.of("edge_model_defect.too_short", "The contour model is too short to sample"),
            )
        pair = str(ctx.param("mode", "single")) == "pair"
        hits = caliper_series(
            image, centers, scan, tangent, positions,
            search=ctx.number("search", 24), height=ctx.number("caliper_width", 3),
            polarity="any" if pair else str(ctx.param("polarity", "light_to_dark")), threshold=ctx.number("edge_threshold", 20),
            smoothing=ctx.integer("smoothing", 3), mode="pair" if pair else "single",
            select=str(ctx.param("edge_select", "strongest")),
            pair_polarity=str(ctx.param("pair_polarity", "any")),
        )
        series = np.array([h.width if pair else h.offset for h in hits], dtype=np.float64)
        found = np.array([h.found for h in hits], dtype=bool)
        series[~found] = np.nan
        baseline = np.zeros(len(series), dtype=np.float64)
        if pair:
            baseline[:] = float(np.nanmedian(series)) if found.any() else np.nan
        deviation = series - baseline
        flags, kinds = EdgeDefectTool._flags(ctx, deviation, found, series, pair, wrap)
        if pair:
            # 成對量的是寬度；偏離中位數也屬寬度缺陷，保留共用的斷裂與階差分類。
            kinds = ["width" if kind == "dislocation" else kind for kind in kinds]
        runs = EdgeDefectTool._runs(ctx, flags, kinds, wrap)
        items = self._describe_model(runs, hits, deviation, positions, wrap, pair=pair)
        limit = ctx.integer("max_defects", 0)
        bad = len(items) > limit if limit else bool(items)
        hit_points_out = [[round(h.x, 2), round(h.y, 2)] for h in hits if h.found]
        missing = [int(i) for i in np.nonzero(~found)[0]]
        overlays: list[dict[str, Any]] = [region_overlay(region, label="model")]
        overlays.append({"kind": "points", "points": hit_points_out, "color": "#22c55e"})
        if pair:
            overlays.append({"kind": "points", "points": [[h.x2, h.y2] for h in hits if h.found], "color": "#22c55e"})
        for item in items:
            rect = item.get("rect")
            if rect:
                overlays.append({
                    "kind": "rect", "x": rect["cx"] - rect["w"] / 2, "y": rect["cy"] - rect["h"] / 2,
                    "w": rect["w"], "h": rect["h"], "angle": rect["angle"],
                    "color": _COLORS.get(item["type"], "#ef4444"), "width": 2, "label": item["type"],
                })
        worst = max((abs(i["max_deviation"] or 0.0) for i in items), default=0.0)
        return Result(
            outputs={
                "count": len(items), "defects": items, "max_deviation": round(float(worst), 4),
                "points": hit_points_out,
                "deviations": [None if not np.isfinite(v) else round(float(v), 4) for v in deviation],
                "missing": missing, "image": image,
            },
            overlays=overlays, branch="defect" if bad else "ok", status="ng" if bad else "ok",
            message=_model_message(auto_taught, items, worst, int(found.sum()), len(hits)),
            detail={"model": {"image_size": model.get("image_size"), "closed": closed, "points": len(points)}, "auto_taught": auto_taught},
        )

    @staticmethod
    def _describe_model(runs: list[tuple[int, int, str]], hits: list[CaliperHit], deviation: np.ndarray,
                        positions: np.ndarray, wrap: bool, *, pair: bool = False) -> list[dict[str, Any]]:
        """任意輪廓缺陷段描述；沿邊長度用模型弧長座標，不用端點直線距離。"""
        n = len(hits)
        total = float(positions[-1] + (positions[1] - positions[0])) if wrap and len(positions) > 1 else float(positions[-1] if len(positions) else 0.0)
        items: list[dict[str, Any]] = []
        for start, end, kind in runs:
            indices = defects.seg_indices((start, end), n)
            pts: list[list[float]] = []
            for i in indices:
                h = hits[i]
                pts.append([h.x, h.y] if h.found else [h.cx, h.cy])
                if pair and h.found:
                    pts.append([h.x2, h.y2])
            values = np.array([deviation[i] for i in indices], dtype=np.float64)
            finite = values[np.isfinite(values)]
            peak = float(finite[np.argmax(np.abs(finite))]) if len(finite) else float("nan")
            if end >= start:
                length = float(positions[end] - positions[start])
            else:
                length = float(total - positions[start] + positions[end])
            if len(indices) > 1 and len(positions) > 1:
                length += float(np.median(np.diff(positions[: min(len(positions), max(2, len(positions)))])))
            rect = defect_rect(np.asarray(pts, dtype=np.float64))
            area = float(rect["w"] * rect["h"]) if rect else 0.0
            items.append({
                "type": kind, "start": int(start), "end": int(end), "count": len(indices),
                "length": round(max(0.0, length), 3), "area": round(area, 3),
                "max_deviation": round(peak, 4) if np.isfinite(peak) else None,
                "peak": round(peak, 4) if np.isfinite(peak) else None,
                "direction": ("outward" if peak > 0 else "inward") if np.isfinite(peak) else "missing",
                "position": round(float(positions[start]), 3),
                "rect": rect,
            })
        return items


TOOLS = [EdgeDefectTool(), EdgeModelDefectTool()]
