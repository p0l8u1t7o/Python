"""量測工具：卡尺、距離、夾角、灰階統計、像素校正、直方圖；杯件量測：圓弧／橢圓擬合、壁厚、同心度、倒角、公差判定。"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.locate import (
    POLARITY_OPTIONS,
    _as_rotated_rect,
    caliper_points,
    find_edges_1d,
    find_edges_rows,
    fit_circle_points,
    fit_line_ransac,
    radial_edge_points,
    to_gray,
)
from apps.vision.tools.hist import otsu_from_hist as _otsu_from_hist
from apps.vision.tools.roi import crop, region_center, region_overlay


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


def _pick_pair(edges: list[tuple[float, float]], mode: str, pair_polarity: str, expected: float) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """依模式挑一對邊緣。pair_polarity 限制兩個邊緣的梯度符號（亮條＝先正後負、暗條＝先負後正）；
    expected > 0 時改挑寬度最接近期望值的一對（同寬時取較強者）。"""
    if pair_polarity == "any":
        cands = [(a, b) for i, a in enumerate(edges) for b in edges[i + 1 :]]
    else:
        first_pos = pair_polarity == "bright"
        cands = [(a, b) for i, a in enumerate(edges) for b in edges[i + 1 :] if (a[1] > 0) == first_pos and (b[1] > 0) != first_pos]
    if not cands:
        return None
    if expected > 0:
        return min(cands, key=lambda p: (abs((p[1][0] - p[0][0]) - expected), -(abs(p[0][1]) + abs(p[1][1]))))
    if pair_polarity == "any":
        if mode == "narrowest":
            return min(zip(edges[:-1], edges[1:]), key=lambda p: p[1][0] - p[0][0])
        if mode == "strongest":
            top = sorted(edges, key=lambda e: -abs(e[1]))[:2]
            return tuple(sorted(top, key=lambda e: e[0]))  # type: ignore[return-value]
        return edges[0], edges[-1]
    if mode == "narrowest":
        return min(cands, key=lambda p: p[1][0] - p[0][0])
    if mode == "strongest":
        return max(cands, key=lambda p: abs(p[0][1]) + abs(p[1][1]))
    if mode == "widest":
        return max(cands, key=lambda p: p[1][0] - p[0][0])
    first = cands[0][0]
    return first, max((b for a, b in cands if a is first), key=lambda e: e[0])


class CaliperTool(Tool):
    key = "caliper"
    label = "卡尺"
    description = "在矩形區域內沿長邊投影灰階剖面，找一對邊緣並量測寬度（像素）。"
    category = "measure"
    icon = "Ruler"
    params = [
        Param("roi", "區域", kind="roi", required=True, shapes=["rotated_rect", "rect"], help_text="沿長邊方向掃描，短邊方向取平均以抗雜訊。"),
        Param("polarity", "邊緣極性", kind="select", default="any", options=POLARITY_OPTIONS, teach=True),
        Param("edge_threshold", "邊緣門檻", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("edge_pair", "取邊緣對", kind="select", default="first_last", options=[
            {"value": "first_last", "label": "第一個與最後一個"},
            {"value": "widest", "label": "最寬的一對"},
            {"value": "narrowest", "label": "最窄的一對（相鄰）"},
            {"value": "strongest", "label": "最強的兩個"},
        ]),
        Param("pair_polarity", "邊緣對極性", kind="select", default="any", options=[
            {"value": "any", "label": "不限"}, {"value": "bright", "label": "亮條（暗→亮、亮→暗）"}, {"value": "dark", "label": "暗條（亮→暗、暗→亮）"},
        ], help_text="限制成對邊緣的極性順序：量亮條／暗條的寬度時不會配到旁邊的雜訊邊緣。"),
        Param("expected_width", "期望寬度", kind="number", default=0, minimum=0, unit="px", help_text="大於 0 時改挑「寬度最接近此值」的邊緣對（優先於取邊緣對模式）。"),
        Param("smoothing", "剖面平滑", kind="number", default=3, minimum=1, maximum=31, group="進階"),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [
        Port("width", "寬度", "number"),
        Port("edge1_x", "邊緣1 X", "number"), Port("edge1_y", "邊緣1 Y", "number"),
        Port("edge2_x", "邊緣2 X", "number"), Port("edge2_y", "邊緣2 Y", "number"),
        Port("edges", "所有邊緣位置", "list"), Port("profile", "剖面", "list"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("沒有設定區域")
        rr = _as_rotated_rect(region)
        c = crop(image, rr, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 2:
            raise ToolError("區域太小或落在影像外")
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
                          overlays=overlays, status="ng", message=f"邊緣不足兩個（{len(edges)}）")
        pair = _pick_pair(edges, ctx.param("edge_pair", "first_last"), ctx.param("pair_polarity", "any"), ctx.number("expected_width", 0))
        if pair is None:
            return Result(outputs={"width": nan, "edge1_x": nan, "edge1_y": nan, "edge2_x": nan, "edge2_y": nan,
                                   "edges": [round(e[0], 2) for e in edges], "profile": prof_list},
                          overlays=overlays, status="ng", message="沒有符合極性的邊緣對")
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
            overlays=overlays, message=f"寬度 {width:.2f}px（{len(edges)} 個邊緣）",
        )


class DistanceTool(Tool):
    key = "distance"
    label = "距離"
    description = "兩點距離（像素）。點可為 {x,y} / [x,y]，或分別接 ax, ay, bx, by 四個數值。"
    category = "measure"
    icon = "MoveHorizontal"
    params = [
        Param("mode", "量測", kind="select", default="euclid", options=[
            {"value": "euclid", "label": "直線距離"}, {"value": "dx", "label": "X 方向距離"}, {"value": "dy", "label": "Y 方向距離"},
        ]),
    ]
    inputs = [
        Port("image", "影像", "image", required=False),
        Port("a", "點 A", "any", required=False), Port("b", "點 B", "any", required=False),
        Port("ax", "A.x", "number", required=False), Port("ay", "A.y", "number", required=False),
        Port("bx", "B.x", "number", required=False), Port("by", "B.y", "number", required=False),
    ]
    outputs = [Port("distance", "距離", "number"), Port("dx", "dx", "number"), Port("dy", "dy", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        a = _point(ctx.inputs.get("a"), (ctx.inputs.get("ax"), ctx.inputs.get("ay")))
        b = _point(ctx.inputs.get("b"), (ctx.inputs.get("bx"), ctx.inputs.get("by")))
        if a is None or b is None:
            raise ToolError("需要兩個點：接 a/b 或 ax,ay,bx,by")
        if not all(np.isfinite([*a, *b])):
            return Result(outputs={"distance": float("nan"), "dx": float("nan"), "dy": float("nan")}, status="ng", message="輸入點無效（上游可能沒找到）")
        dx, dy = b[0] - a[0], b[1] - a[1]
        mode = ctx.param("mode", "euclid")
        d = abs(dx) if mode == "dx" else abs(dy) if mode == "dy" else math.hypot(dx, dy)
        overlays = [
            {"kind": "point", "x": a[0], "y": a[1], "color": "#38bdf8", "label": "A"},
            {"kind": "point", "x": b[0], "y": b[1], "color": "#38bdf8", "label": "B"},
            {"kind": "line", "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1], "color": "#f59e0b", "width": 2, "label": f"{d:.2f}px"},
        ]
        return Result(outputs={"distance": d, "dx": dx, "dy": dy}, overlays=overlays, message=f"{d:.2f}px")


class AngleTool(Tool):
    key = "angle"
    label = "夾角"
    description = "兩條直線的夾角（度）。直線可為 {x1,y1,x2,y2} 或分別接八個數值。"
    category = "measure"
    icon = "TriangleRight"
    params = [
        Param("range", "角度範圍", kind="select", default="0_90", options=[
            {"value": "0_90", "label": "0 ~ 90（不分方向）"}, {"value": "0_180", "label": "0 ~ 180"}, {"value": "signed", "label": "-180 ~ 180（帶號）"},
        ]),
    ]
    inputs = [
        Port("image", "影像", "image", required=False),
        Port("a", "直線 A", "any", required=False), Port("b", "直線 B", "any", required=False),
        Port("ax1", "A.x1", "number", required=False), Port("ay1", "A.y1", "number", required=False),
        Port("ax2", "A.x2", "number", required=False), Port("ay2", "A.y2", "number", required=False),
        Port("bx1", "B.x1", "number", required=False), Port("by1", "B.y1", "number", required=False),
        Port("bx2", "B.x2", "number", required=False), Port("by2", "B.y2", "number", required=False),
    ]
    outputs = [Port("angle_deg", "夾角", "number"), Port("angle_a", "A 角度", "number"), Port("angle_b", "B 角度", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        i = ctx.inputs
        la = _line(i.get("a")) or _line([i.get("ax1"), i.get("ay1"), i.get("ax2"), i.get("ay2")])
        lb = _line(i.get("b")) or _line([i.get("bx1"), i.get("by1"), i.get("bx2"), i.get("by2")])
        if la is None or lb is None:
            raise ToolError("需要兩條直線：接 a/b 或八個端點數值")
        if not all(np.isfinite([*la, *lb])):
            return Result(outputs={"angle_deg": float("nan"), "angle_a": float("nan"), "angle_b": float("nan")}, status="ng", message="輸入直線無效")
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
        raise ToolError("區域落在影像外")
    sub = c.image if c.image.dtype == np.uint8 else np.clip(c.image, 0, 255).astype(np.uint8)
    mask = c.mask if c.mask is None else np.ascontiguousarray(c.mask)
    hist = cv2.calcHist([np.ascontiguousarray(sub)], [0], mask, [256], [0, 256]).reshape(-1).astype(np.float64)
    if hist.sum() <= 0:
        raise ToolError("區域內沒有像素")
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
    label = "灰階統計"
    description = "區域內的灰階平均、標準差、最小、最大、中位數。"
    category = "measure"
    icon = "Sun"
    params = [Param("roi", "區域", kind="roi", shapes=["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon", "point"], help_text="留空則整張影像；點＝單一像素。")]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [Port("mean", "平均", "number"), Port("std", "標準差", "number"), Port("min", "最小", "number"), Port("max", "最大", "number"), Port("median", "中位數", "number"), Port("pixels", "像素數", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        hist, region = _roi_hist(ctx)
        outputs = _hist_stats(hist)
        mean, std = outputs["mean"], outputs["std"]
        overlays = [region_overlay(region, label=f"mean {mean:.1f}")] if region else []
        return Result(outputs=outputs, overlays=overlays, message=f"平均 {mean:.1f} ± {std:.1f}")


class CalibrationTool(Tool):
    key = "calibration"
    label = "像素校正"
    description = "把像素量測值換算成毫米：直接給每像素 mm，或用「已知距離」（像素數 ↔ 實際 mm）算比例。也可縮放點列表。"
    category = "measure"
    icon = "Scale"
    params = [
        Param("mode", "校正方式", kind="select", default="pixel_size", options=[
            {"value": "pixel_size", "label": "每像素 mm"}, {"value": "known_distance", "label": "已知距離"},
        ]),
        Param("pixel_size_mm", "每像素 mm", kind="number", default=0.01, minimum=0, step=0.0001, unit="mm/px", visible_when={"param": "mode", "in": ["pixel_size"]}),
        Param("px_distance", "像素距離", kind="number", default=100, minimum=0, unit="px", visible_when={"param": "mode", "in": ["known_distance"]}),
        Param("real_mm", "實際距離", kind="number", default=1, minimum=0, unit="mm", visible_when={"param": "mode", "in": ["known_distance"]}),
        Param("power", "次方", kind="select", default="1", options=[{"value": "1", "label": "長度（×k）"}, {"value": "2", "label": "面積（×k²）"}], help_text="面積量測請選 k²。"),
    ]
    inputs = [Port("value", "像素值", "number", required=False), Port("points", "點列表", "points", required=False)]
    outputs = [Port("mm", "毫米", "number"), Port("scale", "比例", "number"), Port("points_mm", "點列表（mm）", "points")]

    def execute(self, ctx: ToolContext) -> Result:
        if ctx.param("mode", "pixel_size") == "known_distance":
            px = ctx.number("px_distance", 0)
            if px <= 0:
                raise ToolError("像素距離必須大於 0")
            k = ctx.number("real_mm", 0) / px
        else:
            k = ctx.number("pixel_size_mm", 0)
        if k <= 0:
            raise ToolError("比例必須大於 0")
        power = 2 if str(ctx.param("power", "1")) == "2" else 1
        value = ctx.inputs.get("value")
        mm = float("nan")
        if value is not None:
            try:
                mm = float(value) * (k**power)
            except (TypeError, ValueError):
                raise ToolError(f"輸入不是數值：{value!r}") from None
        pts = ctx.inputs.get("points")
        pts_mm: list[list[float]] = []
        if pts is not None:
            arr = np.asarray(pts, dtype=np.float64).reshape(-1, 2) * k
            pts_mm = arr.tolist()
        if value is None and pts is None:
            raise ToolError("沒有輸入：接 value 或 points")
        return Result(outputs={"mm": mm, "scale": k, "points_mm": pts_mm}, message=(f"{mm:.4f} mm" if value is not None else f"k={k:.5f}"))


class HistogramTool(Tool):
    key = "histogram"
    label = "直方圖"
    description = "區域內 256 階灰階直方圖與峰值。"
    category = "measure"
    icon = "BarChart3"
    params = [
        Param("roi", "區域", kind="roi", shapes=["rect", "rotated_rect", "circle", "annulus", "polygon"], help_text="留空則整張影像。"),
        Param("normalize", "正規化（比例）", kind="boolean", default=False),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [Port("histogram", "直方圖", "list"), Port("peak", "峰值灰階", "number"), Port("peak_count", "峰值數量", "number"), Port("otsu", "Otsu 門檻", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        hist, region = _roi_hist(ctx)
        peak = int(hist.argmax())
        peak_count = float(hist[peak])
        otsu = _otsu_from_hist(hist)
        if ctx.flag("normalize"):
            hist = hist / max(1.0, hist.sum())
        overlays = [region_overlay(region, label=f"peak {peak}")] if region else []
        return Result(outputs={"histogram": hist.tolist(), "peak": peak, "peak_count": peak_count, "otsu": float(otsu)}, overlays=overlays, message=f"峰值 {peak}，Otsu {otsu:g}")



# ---------------------------------------------------------------------------
# 杯件量測：圓弧／橢圓擬合、壁厚、同心度、倒角、公差判定
# ---------------------------------------------------------------------------
_EDGE_SELECT_OPTIONS = [{"value": "strongest", "label": "最強"}, {"value": "first", "label": "第一個"}, {"value": "last", "label": "最後一個"}]


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
    if shape in ("circle", "annulus", "polygon"):
        cx, cy = origin if origin is not None else region_center(region)
        a0 = a1 = None
        mask, off = None, (0, 0)
        if shape == "circle":
            r_in, r_out = 0.0, float(region["r"])
        elif shape == "annulus":
            r_in, r_out = float(region["r_inner"]), float(region["r_outer"])
            a0, a1 = region.get("a0"), region.get("a1")
        else:
            pts = np.asarray(region["points"], dtype=np.float64)
            r_in, r_out = 0.0, float(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy).max())
            c = crop(image, region)
            mask, off = c.mask, (c.x0, c.y0)
            if origin is None:
                polarity = "any"
        if r_out - r_in < 3:
            raise ToolError("區域半徑太小")
        pts_out = radial_edge_points(image, cx, cy, r_in, r_out, num, polarity, thr, sel, smoothing, mask=mask, mask_offset=off, a0=a0, a1=a1)
        return np.asarray(pts_out, dtype=np.float64).reshape(-1, 2)
    if shape in ("rect", "rotated_rect"):
        rr = _as_rotated_rect(region)
        c = crop(image, rr, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 3:
            raise ToolError("區域太小或落在影像外")
        pts_local, _ = caliper_points(c.image, num, polarity, thr, sel, smoothing)
        if not pts_local:
            return np.zeros((0, 2), dtype=np.float64)
        return c.points_to_full(np.asarray([(p[0], p[1]) for p in pts_local]))
    raise ToolError(f"不支援 {shape} 區域")


_RADIAL_SHAPES = ("circle", "annulus", "polygon")


def _refined_points(ctx: ToolContext, image: np.ndarray, region: dict[str, Any], center: tuple[float, float]) -> np.ndarray | None:
    """重掃精修：擬合中心偏離掃描原點 0.5px 以上時，從擬合中心再掃一次（掃描線與邊緣垂直、多邊形套用極性）。"""
    if not ctx.flag("refine", True) or region.get("shape") not in _RADIAL_SHAPES:
        return None
    ox, oy = region_center(region)
    if math.hypot(center[0] - ox, center[1] - oy) <= 0.5:
        return None
    return _region_edge_points(ctx, image, region, origin=center)


_EDGE_PARAMS = [
    Param("polarity", "邊緣極性", kind="select", default="any", options=POLARITY_OPTIONS, teach=True),
    Param("edge_threshold", "邊緣門檻", kind="number", default=20, minimum=1, maximum=255, teach=True),
    Param("num_rays", "掃描線數", kind="number", default=36, minimum=6, maximum=720, help_text="圓／環／多邊形為徑向掃描線數，矩形為卡尺數。"),
    Param("edge_select", "取哪個邊緣", kind="select", default="strongest", options=_EDGE_SELECT_OPTIONS),
    Param("refine", "重掃精修", kind="boolean", default=True, group="進階", help_text="擬合後以擬合中心重掃一次：ROI 偏心或多邊形 ROI 時精度明顯較好。"),
    Param("smoothing", "剖面平滑", kind="number", default=3, minimum=1, maximum=31, group="進階"),
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
    label = "圓弧擬合"
    description = "在區域內找邊緣點並以最小平方（可 RANSAC）擬合圓弧：R 角、杯口圓角的半徑與圓心。"
    category = "measure"
    icon = "Spline"
    params = [
        Param("roi", "區域", kind="roi", required=True, shapes=["annulus", "polygon", "rotated_rect", "circle", "rect"], help_text="圓／環／多邊形：由中心往外徑向掃描；矩形：沿長邊放卡尺。"),
        *_EDGE_PARAMS,
        Param("ransac", "RANSAC 剔除離群", kind="boolean", default=True),
        Param("ransac_tol", "RANSAC 容差", kind="number", default=2, minimum=0.5, maximum=50, unit="px", group="進階"),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [
        Port("radius", "半徑", "number"), Port("cx", "圓心 X", "number"), Port("cy", "圓心 Y", "number"),
        Port("residual_rms", "殘差 RMS", "number"), Port("points", "邊緣點", "points"),
        Port("start_angle", "起角", "number"), Port("end_angle", "終角", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("沒有設定區域")
        pts = _region_edge_points(ctx, image, region)
        overlays = [region_overlay(region, label="arc roi")]
        nan = float("nan")
        ng = {"radius": nan, "cx": nan, "cy": nan, "residual_rms": nan, "points": pts.round(2).tolist(), "start_angle": nan, "end_angle": nan}
        if len(pts) < 3:
            return Result(outputs=ng, overlays=overlays, status="ng", message=f"邊緣點不足（{len(pts)}）")
        use_ransac, tol = ctx.flag("ransac", True), ctx.number("ransac_tol", 2)
        circle, inliers = fit_circle_points(pts, use_ransac, tol)
        if circle is not None:
            pts2 = _refined_points(ctx, image, region, (circle[0], circle[1]))
            if pts2 is not None and len(pts2) >= 3:
                circle2, inliers2 = fit_circle_points(pts2, use_ransac, tol)
                if circle2 is not None and int(inliers2.sum()) >= max(3, int(0.5 * inliers.sum())):
                    pts, circle, inliers = pts2, circle2, inliers2
        if circle is None:
            return Result(outputs=ng, overlays=overlays, status="ng", message="擬合失敗")
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
            overlays=overlays, message=f"R={r:.2f}px 圓心 ({cx:.1f}, {cy:.1f})，{int(inliers.sum())}/{len(pts)} 點，RMS {rms:.2f}px，{start:.0f}°→{end:.0f}°",
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
    label = "橢圓擬合"
    description = "在區域內找邊緣點並以直接最小平方（Direct）擬合橢圓；roundness = 短軸／長軸（1 為正圓），用來量杯口橢圓度。"
    category = "measure"
    icon = "Egg"
    params = [
        Param("roi", "區域", kind="roi", required=True, shapes=["annulus", "circle", "polygon", "rotated_rect", "rect"]),
        *_EDGE_PARAMS,
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [
        Port("cx", "中心 X", "number"), Port("cy", "中心 Y", "number"),
        Port("a", "長半軸", "number"), Port("b", "短半軸", "number"), Port("angle", "長軸角度", "number"),
        Port("roundness", "圓度 b/a", "number"), Port("residual_rms", "殘差 RMS", "number"), Port("points", "邊緣點", "points"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("沒有設定區域")
        pts = _region_edge_points(ctx, image, region)
        overlays = [region_overlay(region, label="ellipse roi")]
        nan = float("nan")
        ng = {"cx": nan, "cy": nan, "a": nan, "b": nan, "angle": nan, "roundness": nan, "residual_rms": nan, "points": pts.round(2).tolist()}
        if len(pts) < 5:
            return Result(outputs=ng, overlays=overlays, status="ng", message=f"邊緣點不足（{len(pts)}，橢圓至少 5 點）")
        fitted = _fit_ellipse(pts)
        if fitted is not None:
            pts2 = _refined_points(ctx, image, region, (fitted[0], fitted[1]))
            if pts2 is not None and len(pts2) >= max(5, len(pts) // 2):
                fitted2 = _fit_ellipse(pts2)
                if fitted2 is not None:
                    pts, fitted = pts2, fitted2
        if fitted is None:
            return Result(outputs=ng, overlays=overlays, status="ng", message="擬合失敗")
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
            overlays=overlays, message=f"a={a:.2f} b={b:.2f} 圓度 {roundness:.3f}，{len(pts)} 點，RMS {rms:.2f}px",
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
            raise ToolError("線段太短")
        return {"shape": "rotated_rect", "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2, "w": length, "h": max(3.0, band), "angle": math.degrees(math.atan2(y2 - y1, x2 - x1))}
    return _as_rotated_rect(region)


class WallThicknessTool(Tool):
    key = "wall_thickness"
    label = "壁厚"
    description = "沿矩形／線段區域放多條卡尺，每條找「外緣→內緣」成對邊緣，量壁厚（像素）並給最小／最大／平均。"
    category = "measure"
    icon = "Layers"
    params = [
        Param("roi", "區域", kind="roi", required=True, shapes=["rotated_rect", "rect", "line"], help_text="長邊沿著壁的走向；卡尺沿短邊由「外」向「內」掃描（矩形上→下／左→右）。線段 ROI 以線為長邊。"),
        Param("polarity", "外緣極性", kind="select", default="any", options=POLARITY_OPTIONS, teach=True, help_text="沿掃描方向遇到外緣時的灰階變化；內緣自動取相反極性。"),
        Param("edge_threshold", "邊緣門檻", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("num_calipers", "卡尺數", kind="number", default=10, minimum=1, maximum=500),
        Param("max_thickness", "最大壁厚", kind="number", default=0, minimum=0, unit="px", help_text="0 表示不限；配對時內緣距外緣不得超過此值。"),
        Param("band", "線段掃描寬", kind="number", default=10, minimum=3, unit="px", group="進階", help_text="ROI 為線段時，取線兩側共此寬度做平均。"),
        Param("smoothing", "剖面平滑", kind="number", default=3, minimum=1, maximum=31, group="進階"),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [
        Port("thickness", "壁厚（平均）", "number"), Port("min", "最小", "number"), Port("max", "最大", "number"),
        Port("mean", "平均", "number"), Port("std", "標準差", "number"), Port("count", "有效卡尺數", "number"),
        Port("profile", "各卡尺壁厚", "list"), Port("pairs", "邊緣對", "list"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("沒有設定區域")
        rr = _as_wall_rect(region, ctx.number("band", 10))
        c = crop(image, rr, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 3:
            raise ToolError("區域太小或落在影像外")
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
                          overlays=overlays, status="ng", message="沒有找到成對的邊緣")
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
            overlays=overlays, message=f"壁厚 {mean:.2f}px（min {arr.min():.2f} / max {arr.max():.2f}，{len(thick)}/{len(centers)} 條卡尺）",
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
    label = "同心度"
    description = "兩個圓（例如外徑與內徑）圓心的偏移量；GD&T 同心度 = 2×偏移。接 find_circle 的 cx/cy/r 或 {cx,cy,r}。"
    category = "measure"
    icon = "Target"
    params = [
        Param("max_deviation", "最大偏移", kind="number", default=5, minimum=0, unit="px", teach=True, help_text="圓心距離超過此值走 ng 分支。"),
    ]
    inputs = [
        Port("image", "影像", "image", required=False),
        Port("a", "圓 A", "any", required=False), Port("b", "圓 B", "any", required=False),
        Port("ax", "A 圓心 X", "number", required=False), Port("ay", "A 圓心 Y", "number", required=False), Port("ar", "A 半徑", "number", required=False),
        Port("bx", "B 圓心 X", "number", required=False), Port("by", "B 圓心 Y", "number", required=False), Port("br", "B 半徑", "number", required=False),
    ]
    outputs = [
        flow_out("ok", "合格", "ok"), flow_out("ng", "超差", "critical"),
        Port("deviation", "偏移量", "number"), Port("dx", "dx", "number"), Port("dy", "dy", "number"),
        Port("concentricity", "同心度（2×偏移）", "number"), Port("verdict", "判定", "string"), Port("in_spec", "合格", "bool"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        i = ctx.inputs
        a = _circle(i.get("a"), (i.get("ax"), i.get("ay"), i.get("ar")))
        b = _circle(i.get("b"), (i.get("bx"), i.get("by"), i.get("br")))
        if a is None or b is None:
            raise ToolError("需要兩個圓：接 a/b 或 ax,ay,(ar),bx,by,(br)")
        nan = float("nan")
        if not all(np.isfinite([a[0], a[1], b[0], b[1]])):
            return Result(outputs={"deviation": nan, "dx": nan, "dy": nan, "concentricity": nan, "verdict": "ng", "in_spec": False},
                          branch="ng", status="ng", message="輸入圓無效（上游可能沒找到）")
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
            message=f"圓心偏移 {dev:.2f}px（dx {dx:.2f}, dy {dy:.2f}）{'≤' if ok else '>'} {max_dev:g}",
        )


def _line_from_fit(vx: float, vy: float, x0: float, y0: float, pts: np.ndarray) -> dict[str, float]:
    """把 (方向, 一點) 與其內點投影成線段端點。"""
    t = (pts[:, 0] - x0) * vx + (pts[:, 1] - y0) * vy
    t0, t1 = float(t.min()), float(t.max())
    x1, y1, x2, y2 = x0 + vx * t0, y0 + vy * t0, x0 + vx * t1, y0 + vy * t1
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "angle": math.degrees(math.atan2(y2 - y1, x2 - x1)), "length": t1 - t0}


class ChamferAngleTool(Tool):
    key = "chamfer_angle"
    label = "倒角"
    description = "在旋轉矩形區域內以卡尺找輪廓邊緣點，RANSAC 擬合第一條直線後排除其內點再擬合第二條；輸出兩線夾角與倒角段長度。"
    category = "measure"
    icon = "CornerDownRight"
    params = [
        Param("roi", "區域", kind="roi", required=True, shapes=["rotated_rect", "rect"], help_text="長邊沿著輪廓走向、要同時包住主邊與倒角段；卡尺沿短邊掃描。"),
        Param("polarity", "邊緣極性", kind="select", default="any", options=POLARITY_OPTIONS, teach=True),
        Param("edge_threshold", "邊緣門檻", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("num_calipers", "卡尺數", kind="number", default=40, minimum=4, maximum=500),
        Param("direction", "取哪個邊緣", kind="select", default="first", options=[{"value": "first", "label": "第一個"}, {"value": "last", "label": "最後一個"}, {"value": "strongest", "label": "最強"}]),
        Param("ransac_tol", "RANSAC 容差", kind="number", default=1.5, minimum=0.3, maximum=50, unit="px", group="進階"),
        Param("min_points", "第二段最少點數", kind="number", default=3, minimum=2, maximum=100, group="進階"),
        Param("smoothing", "剖面平滑", kind="number", default=3, minimum=1, maximum=31, group="進階"),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [
        Port("angle_deg", "夾角", "number"), Port("length", "倒角長度", "number"),
        Port("line1", "主邊", "any"), Port("line2", "倒角邊", "any"),
        Port("ix", "交點 X", "number"), Port("iy", "交點 Y", "number"), Port("points", "邊緣點", "points"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("沒有設定區域")
        rr = _as_rotated_rect(region)
        c = crop(image, rr, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 3:
            raise ToolError("區域太小或落在影像外")
        pts_local, _ = caliper_points(c.image, ctx.integer("num_calipers", 40), ctx.param("polarity", "any"),
                                      ctx.number("edge_threshold", 20), ctx.param("direction", "first"), ctx.integer("smoothing", 3))
        overlays = [region_overlay(region, label="chamfer")]
        nan = float("nan")
        ng_out = {"angle_deg": nan, "length": nan, "line1": None, "line2": None, "ix": nan, "iy": nan}
        pts = c.points_to_full(np.asarray([(p[0], p[1]) for p in pts_local])) if pts_local else np.zeros((0, 2))
        min_pts = max(2, ctx.integer("min_points", 3))
        if len(pts) < 2 + min_pts:
            return Result(outputs={**ng_out, "points": pts.round(2).tolist()}, overlays=overlays, status="ng", message=f"邊緣點不足（{len(pts)}）")
        tol = ctx.number("ransac_tol", 1.5)
        first = fit_line_ransac(pts, tol=tol, iterations=300)
        if first is None:
            return Result(outputs={**ng_out, "points": pts.round(2).tolist()}, overlays=overlays, status="ng", message="第一段擬合失敗")
        (vx1, vy1, x01, y01), inl1 = first
        rest = pts[~inl1]
        if len(rest) < min_pts:
            return Result(outputs={**ng_out, "points": pts.round(2).tolist()}, overlays=overlays, status="ng", message=f"排除主邊後剩 {len(rest)} 點，找不到倒角段")
        second = fit_line_ransac(rest, tol=tol, iterations=300, seed=1)
        if second is None:
            return Result(outputs={**ng_out, "points": pts.round(2).tolist()}, overlays=overlays, status="ng", message="第二段擬合失敗")
        (vx2, vy2, x02, y02), inl2 = second
        if int(inl2.sum()) < min_pts:
            return Result(outputs={**ng_out, "points": pts.round(2).tolist()}, overlays=overlays, status="ng", message=f"倒角段內點不足（{int(inl2.sum())}）")
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
            {"kind": "line", "x1": line1["x1"], "y1": line1["y1"], "x2": line1["x2"], "y2": line1["y2"], "color": "#38bdf8", "width": 2, "label": "主邊"},
            {"kind": "line", "x1": line2["x1"], "y1": line2["y1"], "x2": line2["x2"], "y2": line2["y2"], "color": "#22c55e", "width": 2, "label": f"{angle:.1f}° L={line2['length']:.1f}"},
        ]
        if np.isfinite(ix):
            overlays.append({"kind": "point", "x": ix, "y": iy, "color": "#f59e0b"})
        return Result(
            outputs={"angle_deg": angle, "length": line2["length"], "line1": line1, "line2": line2, "ix": ix, "iy": iy, "points": pts.round(2).tolist()},
            overlays=overlays, message=f"倒角 {angle:.2f}°，長 {line2['length']:.1f}px（主邊 {int(inl1.sum())} 點／倒角 {int(inl2.sum())} 點）",
        )


class ToleranceJudgeTool(Tool):
    key = "tolerance_judge"
    label = "公差判定"
    description = "量測值是否在「標稱 ＋上偏差／＋下偏差」內；判定連同標稱值、上下限、圖面出處一起寫進 run.outputs.tolerances，供 Cpk 與追溯。"
    category = "measure"
    icon = "ClipboardCheck"
    params = [
        Param("nominal", "標稱值", kind="number", required=True, default=0, teach=True),
        Param("upper_tol", "上偏差", kind="number", default=0.1, teach=True, help_text="帶號；上限 = 標稱 + 上偏差。"),
        Param("lower_tol", "下偏差", kind="number", default=-0.1, teach=True, help_text="帶號（通常為負）；下限 = 標稱 + 下偏差。"),
        Param("unit", "單位", kind="text", default="mm"),
        Param("spec_source", "圖面出處", kind="text", default="", help_text="例如「圖號 A-102 尺寸 ⌀12」。"),
        Param("name", "尺寸名稱", kind="text", default="", help_text="寫進 outputs.tolerances 的 name；留空用節點標籤。"),
    ]
    inputs = [Port("value", "量測值", "number")]
    outputs = [
        flow_out("pass", "合格", "ok"), flow_out("fail", "超差", "critical"),
        Port("verdict", "判定", "string"), Port("deviation", "偏差（值−標稱）", "number"), Port("in_spec", "合格", "bool"),
        Port("nominal", "標稱", "number"), Port("upper", "上限", "number"), Port("lower", "下限", "number"), Port("spec_source", "圖面出處", "string"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        raw = ctx.inputs.get("value")
        try:
            v = float(raw)
        except (TypeError, ValueError):
            raise ToolError(f"輸入不是數值：{raw!r}") from None
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
        msg = (f"{v:.4g}{unit} 偏差 {deviation:+.4g}（{lower:.4g} ~ {upper:.4g}）→ {verdict.upper()}" if valid else f"量測值無效（{raw!r}）→ FAIL")
        return Result(
            outputs={"verdict": verdict, "deviation": deviation, "in_spec": ok, "nominal": nominal, "upper": upper, "lower": lower, "spec_source": source},
            branch=verdict, status="ok" if ok else "ng", message=msg, context={"_outputs": outputs},
        )




class LineProfileTool(Tool):
    key = "line_profile"
    label = "線剖面"
    description = "沿著線（或折線）取灰階值，輸出剖面序列與統計；抓斷差、亮暗帶、掃描線缺陷。"
    category = "measure"
    icon = "Activity"
    accepts = ("u8", "u16", "f32")
    params = [
        Param("roi", "線", kind="roi", shapes=["line", "polyline"], required=True, teach=True),
        Param("samples", "取樣點數", kind="number", default=0, minimum=0, maximum=10000, help_text="0 = 每像素一點。"),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "線（動態）", "region", required=False)]
    outputs = [
        Port("values", "剖面值", "list"), Port("mean", "平均", "number"), Port("std", "標準差", "number"),
        Port("min", "最小", "number"), Port("max", "最大", "number"), Port("length", "長度", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        region = ctx.roi()
        if not region:
            raise ToolError("需要線（line／polyline）ROI")
        if region.get("shape") == "line":
            pts = [[float(region["x1"]), float(region["y1"])], [float(region["x2"]), float(region["y2"])]]
        elif region.get("shape") in ("polyline", "polygon"):
            pts = [[float(x), float(y)] for x, y in (region.get("points") or [])]
        else:
            raise ToolError(f"線剖面不支援 '{region.get('shape')}' ROI")
        if len(pts) < 2:
            raise ToolError("至少要兩個點")
        seg = np.diff(np.asarray(pts, dtype=np.float64), axis=0)
        seg_len = np.hypot(seg[:, 0], seg[:, 1])
        total = float(seg_len.sum())
        if total < 1:
            raise ToolError("線長度為 0")
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
        return Result(outputs=stats, overlays=overlays, message=f"{n} 點，mean {stats['mean']:.1f}")


class ColorStatsTool(Tool):
    key = "color_stats"
    label = "色彩統計"
    description = "區域內 RGB 與 HSV 的平均／標準差、主色相與平均色；供顏色驗證與上下游邏輯判斷。"
    category = "measure"
    icon = "Palette"
    params = [Param("roi", "區域", kind="roi", shapes=["rect", "rotated_rect", "circle", "annulus", "polygon", "ellipse"], help_text="留空則整張影像。")]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [
        Port("mean_r", "R 平均", "number"), Port("mean_g", "G 平均", "number"), Port("mean_b", "B 平均", "number"),
        Port("mean_h", "色相平均", "number"), Port("mean_s", "飽和度平均", "number"), Port("mean_v", "明度平均", "number"),
        Port("std_v", "明度標準差", "number"), Port("hex", "平均色", "string"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("區域落在影像外")
        mask = c.mask if c.mask is not None else np.full(c.image.shape[:2], 255, np.uint8)
        sel = c.image[mask > 0]
        if not len(sel):
            raise ToolError("區域內沒有像素")
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


class GeometryTool(Tool):
    key = "geometry"
    label = "幾何計算"
    description = "解析幾何：兩線交點、點到線垂距、兩點中點、點在線上的投影。線＝{x1,y1,x2,y2}、點＝[x,y] 或 {x,y}（接找線／找圓等工具的輸出）。"
    category = "measure"
    icon = "Ruler"
    params = [
        Param("mode", "計算", kind="select", default="intersect", options=[
            {"value": "intersect", "label": "兩線交點"}, {"value": "point_line", "label": "點到線垂距"},
            {"value": "midpoint", "label": "兩點中點"}, {"value": "project", "label": "點投影到線"},
        ]),
    ]
    inputs = [Port("a", "A（線／點）", "any"), Port("b", "B（線／點）", "any")]
    outputs = [Port("x", "X", "number"), Port("y", "Y", "number"), Port("distance", "距離", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        mode = ctx.param("mode", "intersect")
        a, b = ctx.inputs.get("a"), ctx.inputs.get("b")
        if mode == "intersect":
            la, lb = _as_line(a), _as_line(b)
            if not la or not lb:
                raise ToolError("兩線交點需要兩條線 {x1,y1,x2,y2}")
            x1, y1, x2, y2 = la
            x3, y3, x4, y4 = lb
            denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            if abs(denom) < 1e-9:
                return Result(status="ng", message="兩線平行，沒有交點", outputs={"x": 0.0, "y": 0.0, "distance": 0.0})
            px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
            py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
            overlays = [{"kind": "point", "x": px, "y": py, "label": "交點"}]
            return Result(outputs={"x": round(px, 2), "y": round(py, 2), "distance": 0.0}, overlays=overlays, message=f"({px:.1f}, {py:.1f})")
        if mode == "midpoint":
            pa, pb = _as_point(a), _as_point(b)
            if not pa or not pb:
                raise ToolError("中點需要兩個點")
            mx, my = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
            d = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
            return Result(outputs={"x": round(mx, 2), "y": round(my, 2), "distance": round(d, 2)},
                          overlays=[{"kind": "point", "x": mx, "y": my, "label": "中點"}], message=f"({mx:.1f}, {my:.1f})")
        # point_line / project：a=點、b=線
        pa, lb = _as_point(a), _as_line(b)
        if not pa and _as_point(b) and _as_line(a):  # 接反了也行
            pa, lb = _as_point(b), _as_line(a)
        if not pa or not lb:
            raise ToolError("需要一個點與一條線")
        x1, y1, x2, y2 = lb
        dx, dy = x2 - x1, y2 - y1
        norm = dx * dx + dy * dy
        if norm < 1e-9:
            raise ToolError("線的兩端點重合")
        t = ((pa[0] - x1) * dx + (pa[1] - y1) * dy) / norm
        px, py = x1 + t * dx, y1 + t * dy
        d = math.hypot(pa[0] - px, pa[1] - py)
        overlays = [{"kind": "line", "x1": pa[0], "y1": pa[1], "x2": px, "y2": py, "label": f"{d:.1f}px"}]
        return Result(outputs={"x": round(px, 2), "y": round(py, 2), "distance": round(d, 2)}, overlays=overlays,
                      message=f"垂距 {d:.2f}px" if mode == "point_line" else f"投影 ({px:.1f}, {py:.1f})")


TOOLS = [
    CaliperTool(), DistanceTool(), AngleTool(), IntensityTool(), CalibrationTool(), HistogramTool(),
    FitArcTool(), FitEllipseTool(), WallThicknessTool(), ConcentricityTool(), ChamferAngleTool(), ToleranceJudgeTool(),
    LineProfileTool(), ColorStatsTool(), GeometryTool(),
]
