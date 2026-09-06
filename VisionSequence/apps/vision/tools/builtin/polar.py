"""極座標展開（polar_unwrap）與座標還原（polar_restore）。

圓周類檢測（瓶蓋螺紋、齒輪齒數、軸承滾珠、O-ring 缺口、環形焊道、圓形標籤字元）先把環帶
「攤平」成一張寬＝角度、高＝半徑的長條圖，再接既有的 threshold／blob／caliper／find_line／
line_profile；下游在展開圖上找到的點與輪廓用 polar_restore 換回原圖座標，才能畫在原圖上給現場看。

角度慣例與平台一致：影像座標 y 向下，角度正值＝畫面順時針（atan2(dy, dx)）。
展開圖第 u 欄對應角度 θ_u = start + dir·u·step，第 v 列對應半徑 r_v = r_inner + v·radial_step；
還原就是 (cx + r cos θ, cy + r sin θ)，取樣點本身往返誤差為 0。

取樣走 cv2.remap：map 依 (cx, cy, r_inner, r_outer, 扇形, 起始角, 方向, 步進, 內插) 快取在模組層
（轉成定點 map，remap 比浮點 map 快），同一個 ROI 每次 run 只剩純 remap 的成本。
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError
from apps.vision.tools.roi import region_overlay

ANGLE_STEP_OPTIONS = [
    {"value": "auto", "label": "Auto (1 px of arc at the outer radius)"},
    {"value": "0.5", "label": "0.5°"},
    {"value": "1", "label": "1°"},
    {"value": "2", "label": "2°"},
]
DIRECTION_OPTIONS = [
    {"value": "ccw", "label": "Counter-clockwise"},
    {"value": "cw", "label": "Clockwise"},
]
INTERPOLATION_OPTIONS = [
    {"value": "nearest", "label": "Nearest"},
    {"value": "linear", "label": "Linear"},
    {"value": "cubic", "label": "Cubic"},
]
_INTERP = {"nearest": cv2.INTER_NEAREST, "linear": cv2.INTER_LINEAR, "cubic": cv2.INTER_CUBIC}

#: 定點 remap map 的快取：幾何鍵 → (map1, map2)。一組 1280×960 環帶（r 200～300、auto 步進）約 1.5 MB。
_MAP_CACHE: "OrderedDict[tuple[Any, ...], tuple[np.ndarray, np.ndarray]]" = OrderedDict()
_MAP_CACHE_MAX = 8
_MAP_LOCK = threading.Lock()


def clear_map_cache() -> None:
    with _MAP_LOCK:
        _MAP_CACHE.clear()


def step_degrees(choice: Any, r_outer: float) -> float:
    """角度步進（度）。auto＝外緣弧長恰為 1 px：360 / (2π·r_outer)。"""
    text = str(choice if choice not in (None, "") else "auto").strip().lower()
    if text == "auto":
        return 360.0 / (2.0 * math.pi * max(1.0, float(r_outer)))
    try:
        value = float(text)
    except ValueError:
        value = 0.0
    return value if value > 0 else 360.0 / (2.0 * math.pi * max(1.0, float(r_outer)))


def geometry_from_region(region: dict[str, Any]) -> tuple[float, float, float, float, float | None, float | None]:
    """circle／annulus ROI → (cx, cy, r_inner, r_outer, a0, a1)；其他形狀 → ToolError。"""
    shape = region.get("shape")
    if shape == "circle":
        return float(region["cx"]), float(region["cy"]), 0.0, float(region["r"]), None, None
    if shape == "annulus":
        a0, a1 = region.get("a0"), region.get("a1")
        if a0 is None or a1 is None:
            a0 = a1 = None
        return float(region["cx"]), float(region["cy"]), float(region["r_inner"]), float(region["r_outer"]), (None if a0 is None else float(a0)), (None if a1 is None else float(a1))
    raise ToolError(f"Polar unwrap needs a circle or annulus region, got '{shape}'")


def mapping_dict(cx: float, cy: float, r_inner: float, r_outer: float, *, a0: float | None, a1: float | None,
                 start_angle: float, direction: str, step_deg: float, radial_step: float) -> dict[str, Any]:
    """展開圖的幾何描述（polar_unwrap 的 mapping 輸出＝polar_restore 的輸入）：含展開圖尺寸。"""
    direction = "cw" if str(direction).lower() == "cw" else "ccw"
    step_deg = float(step_deg)
    radial_step = max(1e-6, float(radial_step))
    if a0 is None or a1 is None:
        span = 360.0
        width = max(1, int(round(span / step_deg)))
        start = float(start_angle)
        sector = False
    else:
        start, end = float(a0), float(a1)
        if end <= start:
            end += 360.0
        span = end - start
        width = max(1, int(round(span / step_deg)) + 1)
        # 扇形：順時針從 a0 到 a1；逆時針展開時左緣是 a1
        start = start if direction == "cw" else end
        sector = True
    height = max(1, int(math.floor((r_outer - r_inner) / radial_step + 1e-9)) + 1)
    return {
        "cx": float(cx), "cy": float(cy), "r_inner": float(r_inner), "r_outer": float(r_outer),
        "a0": a0, "a1": a1, "sector": sector, "span": span,
        "start_angle": start, "direction": direction, "step_deg": step_deg, "radial_step": radial_step,
        "width": int(width), "height": int(height),
    }


def _sign(direction: str) -> float:
    return 1.0 if direction == "cw" else -1.0


def polar_to_image(points: np.ndarray, m: dict[str, Any]) -> np.ndarray:
    """展開圖座標 (u, v) → 原圖座標 (x, y)。points 為 (N, 2) 浮點。"""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    theta = np.radians(float(m["start_angle"]) + _sign(m["direction"]) * pts[:, 0] * float(m["step_deg"]))
    radius = float(m["r_inner"]) + pts[:, 1] * float(m["radial_step"])
    out = np.empty_like(pts)
    out[:, 0] = float(m["cx"]) + radius * np.cos(theta)
    out[:, 1] = float(m["cy"]) + radius * np.sin(theta)
    return out


def image_to_polar(points: np.ndarray, m: dict[str, Any]) -> np.ndarray:
    """原圖座標 (x, y) → 展開圖座標 (u, v)（測試與 ROI 換算用；角度落在 [0, span) 內）。"""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    dx, dy = pts[:, 0] - float(m["cx"]), pts[:, 1] - float(m["cy"])
    theta = np.degrees(np.arctan2(dy, dx))
    rel = (_sign(m["direction"]) * (theta - float(m["start_angle"]))) % 360.0
    out = np.empty_like(pts)
    out[:, 0] = rel / float(m["step_deg"])
    out[:, 1] = (np.hypot(dx, dy) - float(m["r_inner"])) / float(m["radial_step"])
    return out


def _maps(m: dict[str, Any], interpolation: str) -> tuple[np.ndarray, np.ndarray]:
    key = (m["cx"], m["cy"], m["r_inner"], m["r_outer"], m["a0"], m["a1"], m["start_angle"], m["direction"],
           round(m["step_deg"], 9), m["radial_step"], m["width"], m["height"], interpolation == "nearest")
    with _MAP_LOCK:
        hit = _MAP_CACHE.get(key)
        if hit is not None:
            _MAP_CACHE.move_to_end(key)
            return hit
    us = np.arange(m["width"], dtype=np.float64)
    vs = np.arange(m["height"], dtype=np.float64)
    theta = np.radians(float(m["start_angle"]) + _sign(m["direction"]) * us * float(m["step_deg"]))
    radius = float(m["r_inner"]) + vs * float(m["radial_step"])
    map_x = (float(m["cx"]) + radius[:, None] * np.cos(theta)[None, :]).astype(np.float32)
    map_y = (float(m["cy"]) + radius[:, None] * np.sin(theta)[None, :]).astype(np.float32)
    map1, map2 = cv2.convertMaps(map_x, map_y, cv2.CV_16SC2, nninterpolation=(interpolation == "nearest"))
    with _MAP_LOCK:
        _MAP_CACHE[key] = (map1, map2)
        _MAP_CACHE.move_to_end(key)
        while len(_MAP_CACHE) > _MAP_CACHE_MAX:
            _MAP_CACHE.popitem(last=False)
    return map1, map2


def unwrap(image: np.ndarray, m: dict[str, Any], interpolation: str = "linear") -> np.ndarray:
    """依 mapping 展開影像（寬＝角度、高＝半徑；內圈在上）。多位深與彩色原樣進出。"""
    map1, map2 = _maps(m, interpolation)
    return cv2.remap(image, map1, map2, _INTERP.get(interpolation, cv2.INTER_LINEAR), borderMode=cv2.BORDER_CONSTANT, borderValue=0)


class PolarUnwrapTool(Tool):
    key = "polar_unwrap"
    label = "Polar unwrap"
    description = (
        "Flattens a ring into a strip — width is angle, height is radius, the inner radius at the top. Threads, gear teeth, "
        "bearing balls, O-ring nicks and text on a round label become straight rows that the ordinary threshold, blob, caliper "
        "and line tools can read. Feed its mapping output into Polar restore to put results back on the original picture."
    )
    category = "preprocess"
    icon = "Radius"
    accepts = ("u8", "u16", "f32")
    params = [
        Param("roi", "Ring", kind="roi", shapes=["annulus", "circle"], required=True, teach=True,
              help_text="The ring to unwrap. An annulus with start and end angles unwraps only that sector."),
        Param("angle_step", "Angle step", kind="select", default="auto", options=ANGLE_STEP_OPTIONS,
              help_text="Degrees per output column. Auto keeps the outer edge at one pixel per column, so nothing is under-sampled."),
        Param("radial_step", "Radial step", kind="number", default=1, minimum=0.1, maximum=50, step=0.1, unit="px", help_text="Pixels per output row."),
        Param("direction", "Direction", kind="select", default="ccw", options=DIRECTION_OPTIONS,
              help_text="Which way around the ring the strip runs, as seen on screen."),
        Param("start_angle", "Start angle", kind="number", default=0, minimum=-360, maximum=360, unit="°", teach=True,
              help_text="Where the left edge of the strip sits (0 = 3 o'clock, positive = clockwise). Ignored for a sector, which starts at its own angles."),
        Param("interpolation", "Interpolation", kind="select", default="linear", options=INTERPOLATION_OPTIONS, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Ring (dynamic)", "region", required=False)]
    outputs = [
        Port("image", "Unwrapped", "image"),
        Port("mapping", "Mapping", "any"),
        Port("cx", "Centre X", "number"), Port("cy", "Centre Y", "number"),
        Port("r_inner", "Inner radius", "number"), Port("r_outer", "Outer radius", "number"),
        Port("step_deg", "Degrees per column", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        region = ctx.roi()
        if region is None:
            raise ToolError("No ring is set")
        cx, cy, r_inner, r_outer, a0, a1 = geometry_from_region(region)
        if r_outer - r_inner < 1:
            raise ToolError("The ring must be at least 1 px wide")
        m = mapping_dict(cx, cy, r_inner, r_outer, a0=a0, a1=a1, start_angle=ctx.number("start_angle", 0), direction=ctx.param("direction", "ccw"),
                         step_deg=step_degrees(ctx.param("angle_step", "auto"), r_outer), radial_step=ctx.number("radial_step", 1))
        if m["width"] * m["height"] > 50_000_000:
            raise ToolError("The unwrapped strip would be too large; use a coarser angle or radial step")
        interpolation = str(ctx.param("interpolation", "linear"))
        out = unwrap(image, m, interpolation)
        t = math.radians(m["start_angle"])
        overlays = [
            region_overlay(region, label="ring"),
            {"kind": "line", "x1": cx + r_inner * math.cos(t), "y1": cy + r_inner * math.sin(t), "x2": cx + r_outer * math.cos(t), "y2": cy + r_outer * math.sin(t),
             "color": "#f59e0b", "width": 2, "label": "start"},
        ]
        return Result(
            outputs={"image": out, "mapping": m, "cx": cx, "cy": cy, "r_inner": r_inner, "r_outer": r_outer, "step_deg": m["step_deg"]},
            overlays=overlays,
            message=f"{m['width']}×{m['height']}, {m['step_deg']:.3f}°/px, {m['direction']}",
        )


def _as_points(value: Any) -> np.ndarray:
    """points 埠的各種寫法（[[x, y]]、[{x, y}]、[{cx, cy}]、(N,1,2) 陣列）→ (N, 2) 浮點。"""
    if value is None:
        return np.zeros((0, 2), dtype=np.float64)
    if isinstance(value, np.ndarray):
        return value.reshape(-1, 2).astype(np.float64)
    rows: list[list[float]] = []
    for item in value:
        if isinstance(item, dict):
            x = item.get("x", item.get("cx"))
            y = item.get("y", item.get("cy"))
            if x is None or y is None:
                continue
            rows.append([float(x), float(y)])
        else:
            try:
                rows.append([float(item[0]), float(item[1])])
            except (TypeError, IndexError, ValueError):
                continue
    return np.asarray(rows, dtype=np.float64).reshape(-1, 2)


def _mapping_from_ctx(ctx: ToolContext) -> dict[str, Any]:
    """mapping 埠優先；沒接時用 cx／cy／r_inner 數值埠＋本工具的參數重建（要與展開時的設定一致）。"""
    given = ctx.inputs.get("mapping")
    if isinstance(given, dict) and "step_deg" in given and "cx" in given:
        return given
    values = {}
    for k in ("cx", "cy", "r_inner"):
        v = ctx.inputs.get(k)
        if v is None:
            raise ToolError("Connect the mapping output of Polar unwrap, or the centre and inner radius numbers")
        values[k] = float(v)
    r_outer = ctx.inputs.get("r_outer")
    r_outer = float(r_outer) if r_outer is not None else ctx.number("r_outer", 0)
    if r_outer <= values["r_inner"]:
        raise ToolError("The outer radius must be larger than the inner radius")
    return mapping_dict(values["cx"], values["cy"], values["r_inner"], r_outer, a0=None, a1=None, start_angle=ctx.number("start_angle", 0),
                        direction=ctx.param("direction", "ccw"), step_deg=step_degrees(ctx.param("angle_step", "auto"), r_outer), radial_step=ctx.number("radial_step", 1))


class PolarRestoreTool(Tool):
    key = "polar_restore"
    label = "Polar restore"
    description = (
        "Puts points and contours found on an unwrapped strip back onto the original picture, so a defect located after "
        "Polar unwrap can be marked where it really is. Connect the mapping output of Polar unwrap; the numbers and the "
        "settings here are only a fallback when that is not available."
    )
    category = "preprocess"
    icon = "RotateCcw"
    params = [
        Param("r_outer", "Outer radius", kind="number", default=0, minimum=0, unit="px", group="Without mapping", help_text="Only used when the mapping port is not connected."),
        Param("angle_step", "Angle step", kind="select", default="auto", options=ANGLE_STEP_OPTIONS, group="Without mapping"),
        Param("radial_step", "Radial step", kind="number", default=1, minimum=0.1, maximum=50, step=0.1, unit="px", group="Without mapping"),
        Param("direction", "Direction", kind="select", default="ccw", options=DIRECTION_OPTIONS, group="Without mapping"),
        Param("start_angle", "Start angle", kind="number", default=0, minimum=-360, maximum=360, unit="°", group="Without mapping"),
    ]
    inputs = [
        Port("image", "Original image (for display)", "image", required=False),
        Port("mapping", "Mapping", "any", required=False),
        Port("points", "Points (strip)", "points", required=False),
        Port("contours", "Contours (strip)", "contours", required=False),
        Port("cx", "Centre X", "number", required=False), Port("cy", "Centre Y", "number", required=False),
        Port("r_inner", "Inner radius", "number", required=False), Port("r_outer", "Outer radius", "number", required=False),
    ]
    outputs = [
        Port("points", "Points", "points"), Port("contours", "Contours", "contours"),
        Port("count", "Count", "number"), Port("first_x", "First X", "number"), Port("first_y", "First Y", "number"),
        Port("first_angle", "First angle", "number"), Port("first_radius", "First radius", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        m = _mapping_from_ctx(ctx)
        pts = _as_points(ctx.inputs.get("points"))
        restored_pts = polar_to_image(pts, m) if len(pts) else pts
        contours_in = ctx.inputs.get("contours") or []
        restored_contours: list[np.ndarray] = []
        overlays: list[dict[str, Any]] = []
        for cnt in contours_in:
            arr = np.asarray(cnt, dtype=np.float64).reshape(-1, 2)
            if len(arr) == 0:
                continue
            back = polar_to_image(arr, m).astype(np.float32).reshape(-1, 1, 2)
            restored_contours.append(back)
        if restored_contours:
            overlays.append({"kind": "contours", "contours": [c.reshape(-1, 2).tolist() for c in restored_contours], "color": "#22c55e", "width": 1})
        if len(restored_pts):
            overlays.append({"kind": "points", "points": restored_pts.tolist(), "color": "#f59e0b"})
        count = len(restored_pts) + len(restored_contours)
        first_x = first_y = first_angle = first_radius = float("nan")
        if len(restored_pts):
            first_x, first_y = float(restored_pts[0, 0]), float(restored_pts[0, 1])
        elif restored_contours:
            c0 = restored_contours[0].reshape(-1, 2)
            first_x, first_y = float(c0[:, 0].mean()), float(c0[:, 1].mean())
        if not math.isnan(first_x):
            first_angle = math.degrees(math.atan2(first_y - m["cy"], first_x - m["cx"]))
            first_radius = math.hypot(first_x - m["cx"], first_y - m["cy"])
        return Result(
            outputs={"points": restored_pts.tolist(), "contours": restored_contours, "count": count,
                     "first_x": first_x, "first_y": first_y, "first_angle": first_angle, "first_radius": first_radius},
            overlays=overlays,
            message=f"{len(restored_pts)} points, {len(restored_contours)} contours restored" if count else "nothing to restore",
        )


TOOLS = [PolarUnwrapTool(), PolarRestoreTool()]
