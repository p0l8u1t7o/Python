"""形狀比對工具（shape_match）：以梯度方向為特徵的幾何比對，取代 NCC 在光照變化、遮擋、雜亂背景下的失效。

模型是 apps/vision/shapemodel.py 的資產（POST /vision/assets/shape-model 或 manage.py shape_model 建）；
輸出 `matches` 與 template_match 同格式（x, y, w, h, cx, cy, score, angle ＋ scale），可直接接 shape_align。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np

from apps.vision import shapemodel
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.locate import to_gray
from apps.vision.tools.roi import crop, region_overlay

POLARITY_OPTIONS = [
    {"value": "use_polarity", "label": "Use polarity (dark-on-light stays dark-on-light)"},
    {"value": "ignore_polarity", "label": "Ignore polarity (also finds the inverted part)"},
]
MODEL_SOURCE_OPTIONS = [
    {"value": "asset", "label": "Asset"},
    {"value": "builtin", "label": "Built-in mark"},
]
BUILTIN_SHAPE_OPTIONS = [
    {"value": "cross", "label": "Cross"},
    {"value": "square_outline", "label": "Square outline"},
    {"value": "disc", "label": "Disc"},
]

_BUILTIN_MODEL_CACHE: "OrderedDict[tuple[str, int, int], dict[str, Any]]" = OrderedDict()
_BUILTIN_MODEL_CACHE_MAX = 32
_BUILTIN_LOCK = threading.Lock()


def read_model(ctx: ToolContext, key: str = "model") -> dict[str, Any]:
    if str(ctx.param("model_source", "asset")) == "builtin":
        return builtin_model(
            str(ctx.param("builtin_shape", "cross")),
            ctx.integer("builtin_size", 48),
            ctx.integer("builtin_line_width", 6),
        )
    try:
        return shapemodel.from_asset(ctx.param(key), ctx.asset_path)
    except shapemodel.ShapeModelError as exc:
        raise ToolError(str(exc)) from None


def clear_builtin_model_cache() -> None:
    """測試用：清掉內建 Mark 形狀模型快取。"""
    with _BUILTIN_LOCK:
        _BUILTIN_MODEL_CACHE.clear()


def _builtin_key(shape: str, size: int, line_width: int) -> tuple[str, int, int]:
    shape = shape if shape in {o["value"] for o in BUILTIN_SHAPE_OPTIONS} else "cross"
    size = int(np.clip(size, 8, 512))
    line_width = int(np.clip(line_width, 1, max(1, size // 2)))
    return shape, size, line_width


def builtin_template(shape: str, size: int, line_width: int) -> np.ndarray:
    """合成乾淨的內建 Mark 樣板，後續仍交給 shapemodel.teach() 建模。"""
    shape, size, line_width = _builtin_key(shape, size, line_width)
    pad = max(8, line_width * 3)
    side = size + pad * 2
    img = np.full((side, side), 30, dtype=np.uint8)
    c = side // 2
    half = size // 2
    if shape == "cross":
        cv2.line(img, (c - half, c), (c + half, c), 220, line_width, lineType=cv2.LINE_8)
        cv2.line(img, (c, c - half), (c, c + half), 220, line_width, lineType=cv2.LINE_8)
    elif shape == "square_outline":
        cv2.rectangle(img, (c - half, c - half), (c + half, c + half), 220, line_width, lineType=cv2.LINE_8)
    else:
        cv2.circle(img, (c, c), half, 220, -1, lineType=cv2.LINE_8)
    return cv2.GaussianBlur(img, (3, 3), 0.4)


def builtin_model(shape: str, size: int, line_width: int) -> dict[str, Any]:
    """依圖形種類與尺寸參數快取 shapemodel.teach() 產物。"""
    cache_key = _builtin_key(shape, size, line_width)
    with _BUILTIN_LOCK:
        hit = _BUILTIN_MODEL_CACHE.get(cache_key)
        if hit is not None:
            _BUILTIN_MODEL_CACHE.move_to_end(cache_key)
            return hit
    try:
        model = shapemodel.teach(builtin_template(*cache_key), contrast_low=None, contrast_high=None, min_contrast=4.0, max_points=1024)
    except shapemodel.ShapeModelError as exc:
        raise ToolError(str(exc)) from None
    with _BUILTIN_LOCK:
        _BUILTIN_MODEL_CACHE[cache_key] = model
        _BUILTIN_MODEL_CACHE.move_to_end(cache_key)
        while len(_BUILTIN_MODEL_CACHE) > _BUILTIN_MODEL_CACHE_MAX:
            _BUILTIN_MODEL_CACHE.popitem(last=False)
    return model


class ShapeMatchTool(Tool):
    key = "shape_match"
    label = "Shape match"
    description = (
        "Finds a taught shape by the direction of its edges rather than by grey values, so it keeps working when the light changes, "
        "part of the object is hidden, the background is cluttered or the part turns through any angle. Teach the model from a good "
        "picture on the assets page; the matches feed Locate offset like Template match does."
    )
    category = "locate"
    icon = "Shapes"
    heavy = True
    accepts = ("u8",)
    params = [
        Param("model_source", "Model source", kind="select", default="asset", options=MODEL_SOURCE_OPTIONS,
              help_text="Use an uploaded taught shape model asset, or synthesize a built-in fiducial mark model in memory."),
        Param("model", "Shape model", kind="asset", accept="file", required=True,
              visible_when={"param": "model_source", "in": ["asset"]},
              help_text="Built from an image asset with POST /vision/assets/shape-model or manage.py shape_model (an .npz file asset)."),
        Param("builtin_shape", "Built-in shape", kind="select", default="cross", options=BUILTIN_SHAPE_OPTIONS,
              visible_when={"param": "model_source", "in": ["builtin"]}, help_text="Cross, square outline or solid disc mark."),
        Param("builtin_size", "Mark size", kind="number", default=48, minimum=8, maximum=512, step=1,
              visible_when={"param": "model_source", "in": ["builtin"]}, help_text="Outer diameter or side length in pixels.", teach=True),
        Param("builtin_line_width", "Line width", kind="number", default=6, minimum=1, maximum=128, step=1,
              visible_when={"param": "model_source", "in": ["builtin"]}, help_text="Stroke width for cross and square outline marks.", teach=True),
        Param("roi", "Search region", kind="roi", shapes=["rect", "rotated_rect", "polygon"], help_text="Leave blank for the whole image."),
        Param("min_score", "Min score", kind="range", default=0.7, minimum=0, maximum=1, step=0.01, teach=True,
              help_text="1 = every model edge matches. Occlusion lowers it in proportion: a quarter hidden scores about 0.75."),
        Param("max_matches", "Max matches", kind="number", default=1, minimum=1, maximum=500, teach=True),
        Param("angle_start", "Angle start", kind="number", default=-180, minimum=-360, maximum=360, unit="°", teach=True),
        Param("angle_extent", "Angle extent", kind="number", default=360, minimum=0.1, maximum=360, unit="°", teach=True,
              help_text="Search from angle start over this range. A narrow range is faster."),
        Param("scale_min", "Scale min", kind="number", default=1.0, minimum=0.2, maximum=5, step=0.01, group="Scale"),
        Param("scale_max", "Scale max", kind="number", default=1.0, minimum=0.2, maximum=5, step=0.01, group="Scale", help_text="Equal to scale min = no scale search."),
        Param("max_overlap", "Max overlap", kind="range", default=0.5, minimum=0, maximum=1, step=0.05, group="Advanced", help_text="Two results whose boxes overlap more than this are one object; the weaker is dropped."),
        Param("greediness", "Greediness", kind="range", default=0.7, minimum=0, maximum=1, step=0.05, group="Advanced",
              help_text="How early a hopeless candidate is abandoned. 1 is fastest but may miss a partly hidden part; 0 is exhaustive."),
        Param("subpixel", "Sub-pixel refinement", kind="boolean", default=True, group="Advanced"),
        Param("polarity", "Polarity", kind="select", default="use_polarity", options=POLARITY_OPTIONS, group="Advanced"),
        Param("min_contrast", "Min contrast", kind="number", default=0, minimum=0, maximum=255, group="Advanced", help_text="Edges weaker than this in the search image are ignored; 0 = the model's own value."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Search region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("matches", "Matches", "matches"), Port("count", "Count", "number"),
        Port("best_x", "Best X", "number"), Port("best_y", "Best Y", "number"), Port("best_angle", "Best angle", "number"),
        Port("best_scale", "Best scale", "number"), Port("best_score", "Best score", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        model = read_model(ctx)
        min_score = float(np.clip(ctx.number("min_score", 0.7), 0.0, 1.0))
        angle_extent = ctx.number("angle_extent", 360)
        scale_min, scale_max = ctx.number("scale_min", 1.0), ctx.number("scale_max", 1.0)
        if angle_extent <= 0:
            raise ToolError("Angle extent must be positive")
        if scale_min <= 0 or scale_min > scale_max:
            raise ToolError("Scale min must be positive and not larger than scale max")
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        search = np.ascontiguousarray(c.image)
        if c.mask is not None:
            # 多邊形搜尋區：遮罩外填 0（沒有邊緣＝不計分）
            search = np.where(c.mask > 0, search, 0).astype(np.uint8)
        contrast = ctx.number("min_contrast", 0) or None
        try:
            found, info = shapemodel.find(
                search, model, min_score=min_score, max_matches=ctx.integer("max_matches", 1),
                angle_start=ctx.number("angle_start", -180), angle_extent=angle_extent, scale_min=scale_min, scale_max=scale_max,
                max_overlap=ctx.number("max_overlap", 0.5), greediness=float(np.clip(ctx.number("greediness", 0.7), 0.0, 1.0)),
                subpixel=ctx.flag("subpixel", True), polarity=ctx.param("polarity", "use_polarity") != "ignore_polarity", min_contrast=contrast,
            )
        except shapemodel.ShapeModelError as exc:
            raise ToolError(str(exc)) from None
        mw, mh = float(model["width"]), float(model["height"])
        matches: list[dict[str, Any]] = []
        overlays: list[dict[str, Any]] = [region_overlay(region, label="search")] if region else []
        for i, m in enumerate(found):
            cx, cy = c.to_full(m["cx"], m["cy"])
            angle = m["angle"]
            scale = m["scale"]
            w, h = mw * scale, mh * scale
            matches.append({"x": round(cx - w / 2, 2), "y": round(cy - h / 2, 2), "w": round(w, 2), "h": round(h, 2),
                            "cx": round(cx, 2), "cy": round(cy, 2), "score": round(m["score"], 4), "angle": round(angle, 2), "scale": round(scale, 4)})
            colour = "#22c55e" if i == 0 else "#15803d"
            outline = shapemodel.model_outline(model, m["cx"], m["cy"], angle, scale)
            overlays.append({"kind": "points", "points": [list(c.to_full(px, py)) for px, py in outline], "color": colour})
            overlays.append({"kind": "rect", "x": cx - w / 2, "y": cy - h / 2, "w": w, "h": h, "angle": angle, "color": colour, "width": 1, "dash": True})
            overlays.append({"kind": "point", "x": cx, "y": cy, "color": colour, "label": f"{m['score']:.2f} @ {angle:.1f}°" + (f" ×{scale:.2f}" if abs(scale - 1) > 1e-6 else "")})
        best = matches[0] if matches else None
        nan = float("nan")
        return Result(
            outputs={"matches": matches, "count": len(matches),
                     "best_x": best["cx"] if best else nan, "best_y": best["cy"] if best else nan, "best_angle": best["angle"] if best else 0.0,
                     "best_scale": best["scale"] if best else 1.0, "best_score": best["score"] if best else 0.0},
            overlays=overlays, branch="found" if matches else "not_found", status="ok" if matches else "ng",
            message=(f"{len(matches)} matches, best {best['score']:.3f} @ ({best['cx']:.1f}, {best['cy']:.1f}) {best['angle']:.1f}°" if best else "not found"),
            detail={k: v for k, v in info.items() if k != "per_level"} | {"per_level": info.get("per_level", [])},
        )


TOOLS = [ShapeMatchTool()]

