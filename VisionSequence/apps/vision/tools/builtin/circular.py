"""圓形卡尺（circular_caliper）與序列缺陷偵測（profile_defect）：沿圓周放 N 把徑向卡尺找崩邊、缺口、毛刺。

沖壓件毛邊、藥錠崩邊、齒輪、刀具刃口都要「沿一圈量半徑」；既有 caliper 只量一組平行邊、find_circle 只回擬合圓。
- circular_caliper：由 annulus ROI 的圓心向外發射 N 條掃描線，每條在切向平均 caliper_width 個樣本降噪，找一個邊緣點 → 半徑序列
  （找不到的位置為 null）＋ 全圖座標的邊緣點；離群半徑（MAD 的 outlier_sigma 倍）視為未找到。runout＝max−min＝徑向跳動。
- profile_defect：吃一維序列（radii 或 line_profile 剖面），對基線（擬合圓／滑動中位數／擬合直線／平均）看偏離，
  連續 ≥ min_width 點超過門檻的區段就是缺陷；**卡尺打空（null）也算缺陷**——大缺口會讓卡尺完全找不到邊，最容易漏判。
  有 points 就把缺陷區段畫回原圖圓周（紅色弧段）。
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.defects import moving_median, robust_outliers, seg_indices, seg_len, segments
from apps.vision.tools.builtin.locate import POLARITY_OPTIONS, find_edges_rows, fit_circle_lsq, pick_edge, sector_thetas, to_gray
from apps.vision.tools.roi import region_overlay

SELECT_OPTIONS = [{"value": "first", "label": "First (innermost)"}, {"value": "last", "label": "Last (outermost)"}, {"value": "strongest", "label": "Strongest"}]


def radial_profiles(image: np.ndarray, cx: float, cy: float, r_in: float, r_out: float, thetas: np.ndarray, width: int) -> tuple[np.ndarray, np.ndarray]:
    """N 條徑向掃描線的剖面 (N, S)：每條在切向取 width 個平行樣本平均（降噪）。回 (profiles, radii)。"""
    n_samples = int(math.ceil(r_out - r_in)) + 1
    radii = np.linspace(r_in, r_out, n_samples, dtype=np.float32)
    width = max(1, int(width))
    offs = (np.arange(width, dtype=np.float32) - (width - 1) / 2.0)
    cos_t, sin_t = np.cos(thetas)[:, None, None], np.sin(thetas)[:, None, None]
    # 切向單位向量 (−sin, cos)：每條線 width 個平行位移
    map_x = (cx + cos_t * radii[None, None, :] - sin_t * offs[None, :, None]).astype(np.float32).reshape(-1, n_samples)
    map_y = (cy + sin_t * radii[None, None, :] + cos_t * offs[None, :, None]).astype(np.float32).reshape(-1, n_samples)
    sampled = cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    profiles = sampled.reshape(len(thetas), width, n_samples).astype(np.float32).mean(axis=1)
    return profiles, radii


class CircularCaliperTool(Tool):
    key = "circular_caliper"
    label = "Circular caliper"
    description = (
        "Puts a ring of radial calipers around a circular edge and measures the radius at every angle. The radius sequence shows "
        "chips, nicks, burrs and out-of-round at a glance, and the run-out (max minus min) is the radial deviation. Feed the values "
        "into Profile defects to turn the sequence into counted defects."
    )
    category = "measure"
    icon = "CircleDashed"
    params = [
        Param("roi", "Search ring", kind="roi", shapes=["annulus", "circle"], required=True, teach=True, help_text="The ring must cover the edge; with start and end angles only that sector is measured."),
        Param("caliper_count", "Calipers", kind="number", default=72, minimum=6, maximum=3600, teach=True),
        Param("caliper_width", "Caliper width", kind="number", default=5, minimum=1, maximum=51, unit="px", help_text="Tangential width averaged per caliper, to beat noise."),
        Param("edge_threshold", "Edge threshold", kind="number", default=20, minimum=1, maximum=255, teach=True),
        Param("polarity", "Polarity", kind="select", default="any", options=POLARITY_OPTIONS, teach=True, help_text="Grey change from the inside outwards."),
        Param("edge_select", "Edge select", kind="select", default="first", options=SELECT_OPTIONS, teach=True),
        Param("outlier_sigma", "Outlier sigma", kind="number", default=3, minimum=0, maximum=20, step=0.5, help_text="Radii further than this many robust sigmas from the median are treated as not found. 0 = keep all."),
        Param("smoothing", "Profile smoothing", kind="number", default=3, minimum=1, maximum=15, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Search ring (dynamic)", "region", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("radii", "Radii", "list"), Port("angles", "Angles", "list"), Port("points", "Edge points", "points"),
        Port("mean_r", "Mean radius", "number"), Port("min_r", "Min radius", "number"), Port("max_r", "Max radius", "number"), Port("runout", "Run-out", "number"),
        Port("missing_count", "Missing", "number"), Port("outlier_count", "Outliers", "number"), Port("all_points", "Points per caliper", "points"),
        Port("cx", "Centre X", "number"), Port("cy", "Centre Y", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No search ring is set")
        shape = region.get("shape")
        if shape == "circle":
            cx, cy, r_in, r_out, a0, a1 = float(region["cx"]), float(region["cy"]), 0.0, float(region["r"]), None, None
        elif shape == "annulus":
            cx, cy, r_in, r_out = float(region["cx"]), float(region["cy"]), float(region["r_inner"]), float(region["r_outer"])
            a0, a1 = region.get("a0"), region.get("a1")
            if a0 is None or a1 is None:
                a0 = a1 = None
        else:
            raise ToolError(f"Circular caliper needs a circle or annulus region, got '{shape}'")
        if r_out - r_in < 3:
            raise ToolError("The ring is too thin (at least 3 px)")
        n = max(6, ctx.integer("caliper_count", 72))
        thetas = sector_thetas(n, a0, a1)
        profiles, radii_axis = radial_profiles(image, cx, cy, r_in, r_out, thetas, ctx.integer("caliper_width", 5))
        edges = find_edges_rows(profiles, ctx.param("polarity", "any"), ctx.number("edge_threshold", 20), ctx.integer("smoothing", 3))
        select = ctx.param("edge_select", "first")
        step = (r_out - r_in) / max(1, len(radii_axis) - 1)
        radii = np.full(n, np.nan, dtype=np.float64)
        for i, row in enumerate(edges):
            e = pick_edge(row, select)
            if e is not None:
                radii[i] = r_in + e[0] * step
        # 離群只影響 mean／min／max／runout 的統計；radii 與點都保留（缺口本身就是離群，profile_defect 要看得到）
        outliers = robust_outliers(radii, ctx.number("outlier_sigma", 3))
        valid = np.isfinite(radii)
        stat_ok = valid & ~outliers
        all_pts = [[float(cx + math.cos(thetas[i]) * radii[i]), float(cy + math.sin(thetas[i]) * radii[i])] if valid[i] else None for i in range(n)]
        pts = [p for p in all_pts if p is not None]
        angles = [round(float(math.degrees(t)), 3) for t in thetas]
        missing = int((~valid).sum())
        overlays: list[dict[str, Any]] = [region_overlay(region, label="ring"), {"kind": "point", "x": cx, "y": cy, "color": "#38bdf8"}]
        if pts:
            overlays.append({"kind": "points", "points": pts, "color": "#22c55e"})
        for i in np.nonzero(~valid)[0][:200]:
            rr = float(np.nanmedian(radii)) if valid.any() else (r_in + r_out) / 2
            overlays.append({"kind": "line", "x1": cx + math.cos(thetas[i]) * (rr - 4), "y1": cy + math.sin(thetas[i]) * (rr - 4),
                             "x2": cx + math.cos(thetas[i]) * (rr + 4), "y2": cy + math.sin(thetas[i]) * (rr + 4), "color": "#ef4444", "width": 2})
        nan = float("nan")
        if stat_ok.sum() >= 3:
            v = radii[stat_ok]
            mean_r, min_r, max_r = float(v.mean()), float(v.min()), float(v.max())
            runout = max_r - min_r
        elif valid.sum() >= 3:
            v = radii[valid]
            mean_r, min_r, max_r = float(v.mean()), float(v.min()), float(v.max())
            runout = max_r - min_r
        else:
            mean_r = min_r = max_r = runout = nan
        found = valid.sum() >= 3
        return Result(
            outputs={"radii": [None if not valid[i] else round(float(radii[i]), 3) for i in range(n)], "angles": angles, "points": pts, "all_points": all_pts,
                     "mean_r": round(mean_r, 3) if found else nan, "min_r": round(min_r, 3) if found else nan, "max_r": round(max_r, 3) if found else nan,
                     "runout": round(runout, 3) if found else nan, "missing_count": missing, "outlier_count": int(outliers.sum()), "cx": cx, "cy": cy},
            overlays=overlays, branch="found" if found else "not_found", status="ok" if found else "ng",
            message=(f"r {mean_r:.2f} ({min_r:.2f}–{max_r:.2f}), run-out {runout:.2f}, {missing} missing, {int(outliers.sum())} outliers of {n}" if found else f"only {int(valid.sum())} edges found of {n}"),
        )


# ---------------------------------------------------------------------------
# profile_defect
# ---------------------------------------------------------------------------
BASELINE_OPTIONS = [
    {"value": "fit_circle", "label": "Fitted circle (radii from Circular caliper)"},
    {"value": "median", "label": "Moving median"},
    {"value": "fit_line", "label": "Fitted line"},
    {"value": "mean", "label": "Mean"},
]
MODE_OPTIONS = [{"value": "absolute", "label": "Absolute (units of the values)"}, {"value": "sigma", "label": "Sigma (multiples of the robust spread)"}]
DIRECTION_OPTIONS = [{"value": "both", "label": "Both"}, {"value": "inward", "label": "Inward (dents, nicks, gaps)"}, {"value": "outward", "label": "Outward (burrs, bumps)"}]


def _as_values(value: Any) -> np.ndarray:
    if value is None:
        return np.zeros(0, dtype=np.float64)
    out = []
    for v in value:
        try:
            out.append(float("nan") if v is None else float(v))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return np.asarray(out, dtype=np.float64)


def _as_points(value: Any) -> np.ndarray | None:
    """points／all_points：[[x, y] | None, …] → (N, 2)，None 變 NaN。"""
    if value is None:
        return None
    rows = []
    for item in value:
        if item is None:
            rows.append([np.nan, np.nan])
            continue
        try:
            rows.append([float(item[0]), float(item[1])])
        except (TypeError, IndexError, ValueError):
            rows.append([np.nan, np.nan])
    arr = np.asarray(rows, dtype=np.float64).reshape(-1, 2)
    return arr if len(arr) else None


class ProfileDefectTool(Tool):
    key = "profile_defect"
    label = "Profile defects"
    description = (
        "Finds the stretches of a one-dimensional sequence — the radii from Circular caliper, or a line profile — that stray from the "
        "baseline: nicks and gaps (inward), burrs and bumps (outward). A caliper that found no edge at all counts as a defect too, "
        "because a large chip makes the edge vanish. With the edge points connected, each defect is drawn on the original picture."
    )
    category = "measure"
    icon = "Activity"
    params = [
        Param("baseline", "Baseline", kind="select", default="fit_circle", options=BASELINE_OPTIONS,
              help_text="What 'normal' is: a circle fitted to the edge points (needs the points), a moving median, a fitted line or the mean."),
        Param("window", "Window", kind="number", default=9, minimum=3, maximum=999, help_text="Moving-median window length in points."),
        Param("threshold", "Threshold", kind="number", default=3, minimum=0, step=0.1, teach=True, help_text="Deviation that counts as a defect (values' units, or sigmas)."),
        Param("threshold_mode", "Threshold mode", kind="select", default="absolute", options=MODE_OPTIONS, teach=True),
        Param("min_width", "Min width", kind="number", default=2, minimum=1, teach=True, help_text="Consecutive points a defect must span; blocks single-point noise."),
        Param("direction", "Direction", kind="select", default="both", options=DIRECTION_OPTIONS, teach=True),
        Param("max_defects", "Max defects", kind="number", default=0, minimum=0, teach=True, help_text="More than this is an NG; 0 = any defect is an NG."),
        Param("wrap", "Circular sequence", kind="boolean", default=True, help_text="The last point joins the first (a full ring). Off for a line profile."),
        Param("missing_as_defect", "Missing counts as defect", kind="boolean", default=True, help_text="Positions with no value (a caliper that found nothing) are treated as inward defects."),
    ]
    inputs = [Port("values", "Values", "list"), Port("points", "Points", "points", required=False), Port("image", "Image (for display)", "image", required=False)]
    outputs = [
        flow_out("ok", "Clean", "ok"), flow_out("defect", "Defective", "critical"),
        Port("count", "Count", "number"), Port("defects", "Defects", "list"), Port("max_deviation", "Max deviation", "number"),
        Port("baseline_values", "Baseline", "list"), Port("deviation", "Deviation", "list"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        values = _as_values(ctx.inputs.get("values"))
        n = len(values)
        if n < 3:
            raise ToolError("At least three values are needed")
        pts = _as_points(ctx.inputs.get("points"))
        wrap = ctx.flag("wrap", True)
        mode = str(ctx.param("baseline", "fit_circle"))
        finite = np.isfinite(values)
        baseline = np.full(n, np.nan)
        detail: dict[str, Any] = {"baseline": mode}
        if mode == "fit_circle" and pts is not None and finite.sum() >= 3:
            # all_points 與 values 對齊（缺的為 NaN）；只接 points（只有找到的點）時依「有值」的順序對齊
            if len(pts) == n:
                aligned = pts
            else:
                aligned = np.full((n, 2), np.nan)
                idx = np.nonzero(finite)[0]
                take = min(len(idx), len(pts))
                aligned[idx[:take]] = pts[:take]
            good = finite & np.isfinite(aligned).all(axis=1)
            circle = fit_circle_lsq(aligned[good]) if good.sum() >= 3 else None
            if circle is not None:
                ccx, ccy, cr = circle
                detail.update({"cx": round(ccx, 3), "cy": round(ccy, 3), "r": round(cr, 3)})
                # 基線＝擬合圓在該點的半徑：值 − (點到擬合圓心的距離 − 擬合半徑)
                baseline[good] = values[good] - (np.hypot(aligned[good, 0] - ccx, aligned[good, 1] - ccy) - cr)
            else:
                mode = "median"
        if mode == "median" or (mode == "fit_circle" and not np.isfinite(baseline).any()):
            baseline = moving_median(values, ctx.integer("window", 9), wrap)
            detail["baseline"] = "median"
        elif mode == "fit_line":
            x = np.arange(n, dtype=np.float64)
            if finite.sum() >= 2:
                a, b = np.polyfit(x[finite], values[finite], 1)
                baseline = a * x + b
                detail.update({"slope": round(float(a), 5), "intercept": round(float(b), 4)})
        elif mode == "mean":
            baseline[:] = float(values[finite].mean()) if finite.any() else np.nan
        dev = values - baseline
        thr = ctx.number("threshold", 3)
        if ctx.param("threshold_mode", "absolute") == "sigma":
            d_ok = dev[np.isfinite(dev)]
            spread = float(np.median(np.abs(d_ok - np.median(d_ok))) * 1.4826) if len(d_ok) else 0.0
            if spread < 1e-6 and len(d_ok) > 1:
                spread = float(d_ok.std())  # 多數值完全相同時 MAD 為 0：退回標準差，才不會把一切都當缺陷
            spread = max(spread, 1e-6)
            thr = thr * spread
            detail["sigma"] = round(spread, 4)
        detail["threshold"] = round(float(thr), 4)
        direction = str(ctx.param("direction", "both"))
        inward = np.isfinite(dev) & (dev < -thr)
        outward = np.isfinite(dev) & (dev > thr)
        missing = ~finite
        flag = np.zeros(n, dtype=bool)
        if direction in ("both", "inward"):
            flag |= inward
        if direction in ("both", "outward"):
            flag |= outward
        if ctx.flag("missing_as_defect", True) and direction != "outward":
            flag |= missing
        min_width = max(1, ctx.integer("min_width", 2))
        defects: list[dict[str, Any]] = []
        overlays: list[dict[str, Any]] = []
        for seg in segments(flag, wrap):
            width = seg_len(seg, n)
            if width < min_width:
                continue
            ids = seg_indices(seg, n)
            seg_dev = dev[ids]
            has_missing = bool(missing[ids].any())
            if np.isfinite(seg_dev).any():
                k = int(np.nanargmax(np.abs(np.where(np.isfinite(seg_dev), seg_dev, 0.0))))
                peak_i, peak_v = int(ids[k]), float(seg_dev[k])
            else:
                peak_i, peak_v = int(ids[len(ids) // 2]), float("nan")
            kind = "inward" if (has_missing and not np.isfinite(peak_v)) or (np.isfinite(peak_v) and peak_v < 0) else "outward"
            d = {"start": int(seg[0]), "end": int(seg[1]), "width": int(width), "peak_index": peak_i, "peak_deviation": round(peak_v, 3) if np.isfinite(peak_v) else None,
                 "direction": kind, "missing": has_missing}
            defects.append(d)
            if pts is not None and len(pts) == n:
                seg_pts = pts[ids][np.isfinite(pts[ids]).all(axis=1)]
                if len(seg_pts) >= 2:
                    overlays.append({"kind": "polyline", "points": seg_pts.tolist(), "color": "#ef4444", "width": 3, "label": f"{kind} {abs(peak_v):.1f}" if np.isfinite(peak_v) else "missing"})
                elif len(seg_pts) == 1:
                    overlays.append({"kind": "point", "x": float(seg_pts[0, 0]), "y": float(seg_pts[0, 1]), "color": "#ef4444", "label": kind})
        max_dev = float(np.nanmax(np.abs(dev))) if np.isfinite(dev).any() else float("nan")
        count = len(defects)
        limit = ctx.integer("max_defects", 0)
        ok = count == 0 if limit <= 0 else count <= limit
        return Result(
            outputs={"count": count, "defects": defects, "max_deviation": round(max_dev, 3) if np.isfinite(max_dev) else max_dev,
                     "baseline_values": [None if not np.isfinite(b) else round(float(b), 3) for b in baseline],
                     "deviation": [None if not np.isfinite(v) else round(float(v), 3) for v in dev]},
            overlays=overlays, branch="ok" if ok else "defect", status="ok" if ok else "ng",
            message=f"{count} defects, max deviation {max_dev:.2f}" if np.isfinite(max_dev) else f"{count} defects",
            detail=detail,
        )


TOOLS = [CircularCaliperTool(), ProfileDefectTool()]
