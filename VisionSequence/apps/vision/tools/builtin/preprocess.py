"""影像前處理工具。盡量零拷貝。"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np

from apps.vision import calib
from apps.vision import fixed_images
from apps.vision.tools import accel
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.locate import reference_image
from apps.vision.tools.roi import bounding_rect, crop, region_overlay


_COMPARE_CODES = {
    "ge": cv2.CMP_GE,
    "le": cv2.CMP_LE,
    "eq": cv2.CMP_EQ,
    "ne": cv2.CMP_NE,
}


def read_calibration(ctx: ToolContext, key: str = "calibration") -> dict:
    """標定參數（asset）→ payload；壞掉或沒選都翻成給使用者看的訊息。"""
    try:
        return calib.from_asset(ctx.param(key), ctx.asset_path)
    except calib.CalibError as exc:
        raise ToolError(str(exc)) from None


def to_gray(image: np.ndarray) -> np.ndarray:
    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


class GrayscaleTool(Tool):
    key = "grayscale"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Grayscale"
    description = "Colour to grayscale; already-grey images pass through."
    icon = "Contrast"

    def execute(self, ctx: ToolContext) -> Result:
        return Result(outputs={"image": to_gray(ctx.require_image())})


class CropTool(Tool):
    key = "crop"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Crop ROI"
    description = "Crops the region into a new image, straightening a rotated rectangle. Downstream tools are far faster on the smaller frame."
    icon = "Crop"
    params = [Param("roi", "Region", kind="roi", required=True, shapes=["rect", "rotated_rect"])]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [Port("image", "Image", "image"), Port("offset_x", "Offset X", "number"), Port("offset_y", "Offset Y", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        c = crop(image, region, upright=True)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        return Result(
            outputs={"image": np.ascontiguousarray(c.image), "offset_x": c.x0, "offset_y": c.y0},
            overlays=[region_overlay(region, label="crop")],
            message=f"{c.image.shape[1]}×{c.image.shape[0]}",
        )


class BlurTool(Tool):
    key = "blur"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Blur / denoise"
    description = "Gaussian, median, bilateral or box filter."
    icon = "Droplets"
    params = [
        Param("method", "Method", kind="select", default="gaussian", options=[
            {"value": "gaussian", "label": "Gaussian"}, {"value": "median", "label": "Median"},
            {"value": "bilateral", "label": "Bilateral (edge preserving)"}, {"value": "box", "label": "Mean"},
        ]),
        Param("ksize", "Kernel size (odd)", kind="number", default=5, minimum=1, maximum=99, step=2),
        Param("sigma", "Sigma (Gaussian / bilateral)", kind="number", default=0, minimum=0, maximum=200, group="Advanced"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        k = max(1, ctx.integer("ksize", 5))
        if k % 2 == 0:
            k += 1
        method = ctx.param("method", "gaussian")
        sigma = ctx.number("sigma", 0)
        if method == "median":
            out = accel.median_blur(image, k)
        elif method == "bilateral":
            out = cv2.bilateralFilter(image, k, sigma or 50, sigma or 50)
        elif method == "box":
            out = cv2.blur(image, (k, k))
        else:
            out = cv2.GaussianBlur(image, (k, k), sigma)
        return Result(outputs={"image": out})


class ThresholdTool(Tool):
    key = "threshold"
    label = "Threshold"
    description = "Fixed, automatic (Otsu) or adaptive (local) thresholding; outputs a 0/255 mask."
    icon = "SlidersHorizontal"
    params = [
        Param("method", "Method", kind="select", default="otsu", options=[
            {"value": "fixed", "label": "Fixed"}, {"value": "otsu", "label": "Otsu (automatic)"},
            {"value": "triangle", "label": "Triangle (automatic)"},
            {"value": "adaptive_mean", "label": "Adaptive (mean)"}, {"value": "adaptive_gaussian", "label": "Adaptive (Gaussian)"},
            {"value": "sauvola", "label": "Sauvola (local mean and contrast)"},
            {"value": "niblack", "label": "Niblack (local mean plus k sigma)"},
            {"value": "range", "label": "Grey range"},
        ], help_text="Sauvola uses mean * (1 + k * (std / 128 - 1)), so flat background moves toward the local mean and textured areas get a wider threshold. Niblack uses mean + k * std, a direct local mean plus contrast offset."),
        Param("threshold", "Threshold", kind="number", default=128, minimum=0, maximum=255, visible_when={"param": "method", "in": ["fixed"]}, teach=True),
        Param("low", "Lower", kind="number", default=0, minimum=0, maximum=255, visible_when={"param": "method", "in": ["range"]}, teach=True),
        Param("high", "Upper", kind="number", default=128, minimum=0, maximum=255, visible_when={"param": "method", "in": ["range"]}, teach=True),
        Param("block", "Block size (odd)", kind="number", default=31, minimum=3, maximum=255, step=2, visible_when={"param": "method", "in": ["adaptive_mean", "adaptive_gaussian"]}, teach=True),
        Param("c", "Constant C", kind="number", default=5, minimum=-100, maximum=100, visible_when={"param": "method", "in": ["adaptive_mean", "adaptive_gaussian"]}, teach=True),
        Param("window", "Window size (odd)", kind="number", default=31, minimum=3, maximum=255, step=2, visible_when={"param": "method", "in": ["sauvola", "niblack"]}),
        Param("k", "k", kind="number", default=0.2, minimum=-2, maximum=2, step=0.05, visible_when={"param": "method", "in": ["sauvola", "niblack"]}),
        Param("compare", "Compare", kind="select", default="", options=[
            {"value": "ge", "label": "Pixel >= threshold"},
            {"value": "le", "label": "Pixel <= threshold"},
            {"value": "eq", "label": "Pixel == threshold"},
            {"value": "ne", "label": "Pixel != threshold"},
        ], help_text="Leave unchanged to keep the legacy threshold meaning. Set this only when equality or the opposite comparison matters."),
        Param("offset", "Threshold offset", kind="number", teach=True, default=0, minimum=-255, maximum=255,
              help_text="Added to the threshold after it is calculated."),
        Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon", "composite"], required=False),
        Param("outside_roi", "Outside ROI", kind="select", default="black", options=[
            {"value": "black", "label": "Black"},
            {"value": "keep", "label": "Keep original grey"},
        ]),
        Param("invert", "Invert (dark objects are foreground)", kind="boolean", default=False),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [Port("image", "Mask", "image"), Port("threshold_used", "Threshold used", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        area = crop(gray, region) if region is not None else None
        work = area.image if area is not None else gray
        method = ctx.param("method", "otsu")
        inv = ctx.flag("invert")
        compare = str(ctx.params["compare"]) if "compare" in ctx.params and ctx.param("compare") in _COMPARE_CODES else ""
        threshold_offset = ctx.number("offset", 0) if "offset" in ctx.params else 0.0
        used = 0.0
        if method == "otsu":
            used, out = cv2.threshold(work, 0, 255, (cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY) | cv2.THRESH_OTSU)
            if compare or threshold_offset:
                out = _threshold_compare(work, used + threshold_offset, compare, inv)
        elif method == "triangle":
            used, out = cv2.threshold(work, 0, 255, (cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY) | cv2.THRESH_TRIANGLE)
            if compare or threshold_offset:
                out = _threshold_compare(work, used + threshold_offset, compare, inv)
        elif method in ("adaptive_mean", "adaptive_gaussian"):
            b = max(3, ctx.integer("block", 31))
            if b % 2 == 0:
                b += 1
            if compare:
                thresholds = _adaptive_thresholds(work, method, b, ctx.number("c", 5)) + threshold_offset
                out = _threshold_compare(work, thresholds, compare, inv)
            else:
                out = cv2.adaptiveThreshold(work, 255, cv2.ADAPTIVE_THRESH_MEAN_C if method == "adaptive_mean" else cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY, b, ctx.number("c", 5) - threshold_offset)
        elif method in ("sauvola", "niblack"):
            w = max(3, ctx.integer("window", 31))
            if w % 2 == 0:
                w += 1
            thresholds = _local_thresholds(work, method, w, ctx.number("k", 0.2)) + threshold_offset
            out = _threshold_compare(work, thresholds, compare, inv)
        elif method == "range":
            off = int(round(threshold_offset))
            out = cv2.inRange(work, int(ctx.number("low", 0)) + off, int(ctx.number("high", 128)) + off)
            if inv:
                out = cv2.bitwise_not(out)
        else:
            used = ctx.number("threshold", 128)
            if compare or threshold_offset:
                out = _threshold_compare(work, used + threshold_offset, compare, inv)
            else:
                _, out = cv2.threshold(work, used, 255, cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY)
        if area is not None:
            full = gray.copy() if ctx.param("outside_roi", "black") == "keep" else np.zeros_like(gray)
            if area.mask is not None:
                current = full[area.y0 : area.y0 + area.image.shape[0], area.x0 : area.x0 + area.image.shape[1]].copy()
                cv2.copyTo(out, area.mask, current)
                full[area.y0 : area.y0 + area.image.shape[0], area.x0 : area.x0 + area.image.shape[1]] = current
            else:
                full[area.y0 : area.y0 + out.shape[0], area.x0 : area.x0 + out.shape[1]] = out
            out = full
        return Result(outputs={"image": out, "threshold_used": float(used)}, message=f"{method} t={used:g}")


def _threshold_compare(image: np.ndarray, threshold: float | np.ndarray, compare: str, invert: bool) -> np.ndarray:
    """依比較方式產生 0/255 遮罩；compare 空值保留舊版大於門檻語意。"""
    if compare:
        out = cv2.compare(image.astype(np.float32), threshold, _COMPARE_CODES[compare])
        return cv2.bitwise_not(out) if invert else out
    if isinstance(threshold, np.ndarray):
        out = cv2.compare(image.astype(np.float32), threshold.astype(np.float32), cv2.CMP_LE if invert else cv2.CMP_GT)
        return out
    _, out = cv2.threshold(image, float(threshold), 255, cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY)
    return out


def _adaptive_thresholds(image: np.ndarray, method: str, block: int, c_value: float) -> np.ndarray:
    """取得自適應門檻圖；只供新比較模式使用，避免改動舊版路徑。"""
    src = image.astype(np.float32)
    if method == "adaptive_gaussian":
        mean = cv2.GaussianBlur(src, (block, block), 0, borderType=cv2.BORDER_REPLICATE)
    else:
        mean = cv2.boxFilter(src, cv2.CV_32F, (block, block), normalize=True, borderType=cv2.BORDER_REPLICATE)
    return mean - float(c_value)


def _local_thresholds(image: np.ndarray, method: str, window: int, k_value: float) -> np.ndarray:
    """Sauvola 與 Niblack 的區域門檻圖。"""
    src = image.astype(np.float32)
    mean = cv2.boxFilter(src, cv2.CV_32F, (window, window), normalize=True, borderType=cv2.BORDER_REPLICATE)
    mean_sq = cv2.boxFilter(src * src, cv2.CV_32F, (window, window), normalize=True, borderType=cv2.BORDER_REPLICATE)
    std = cv2.sqrt(np.maximum(mean_sq - mean * mean, 0.0))
    k = float(k_value)
    if method == "sauvola":
        return mean * (1.0 + k * (std / 128.0 - 1.0))
    return mean + k * std


class MorphologyTool(Tool):
    key = "morphology"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Morphology"
    description = "Erode, dilate, open, close, gradient, top hat, black hat."
    icon = "Shapes"
    params = [
        Param("op", "Operation", kind="select", default="open", options=[
            {"value": "erode", "label": "Erode"}, {"value": "dilate", "label": "Dilate"}, {"value": "open", "label": "Open"},
            {"value": "close", "label": "Close"}, {"value": "gradient", "label": "Gradient"}, {"value": "tophat", "label": "Top hat"}, {"value": "blackhat", "label": "Black hat"},
        ]),
        Param("shape", "Kernel shape", kind="select", default="rect", options=[{"value": "rect", "label": "Rectangle"}, {"value": "ellipse", "label": "Ellipse"}, {"value": "cross", "label": "Cross"}]),
        Param("ksize", "Kernel size", kind="number", default=3, minimum=1, maximum=99),
        Param("iterations", "Iterations", kind="number", default=1, minimum=1, maximum=20),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        k = max(1, ctx.integer("ksize", 3))
        shape = {"rect": cv2.MORPH_RECT, "ellipse": cv2.MORPH_ELLIPSE, "cross": cv2.MORPH_CROSS}[ctx.param("shape", "rect")]
        kernel = cv2.getStructuringElement(shape, (k, k))
        op = ctx.param("op", "open")
        it = ctx.integer("iterations", 1)
        if op == "erode":
            out = cv2.erode(image, kernel, iterations=it)
        elif op == "dilate":
            out = cv2.dilate(image, kernel, iterations=it)
        else:
            code = {"open": cv2.MORPH_OPEN, "close": cv2.MORPH_CLOSE, "gradient": cv2.MORPH_GRADIENT, "tophat": cv2.MORPH_TOPHAT, "blackhat": cv2.MORPH_BLACKHAT}[op]
            out = cv2.morphologyEx(image, code, kernel, iterations=it)
        return Result(outputs={"image": out})


class ResizeTool(Tool):
    key = "resize"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Scale"
    description = "Scale by ratio or to a given size. Shrinking a large frame before processing is the single most effective speed-up."
    icon = "Scaling"
    params = [
        Param("scale", "Scale", kind="number", default=0.5, minimum=0.01, maximum=8, step=0.05),
        Param("width", "Width (0 = use scale)", kind="number", default=0, minimum=0),
        Param("height", "Height (0 = use scale)", kind="number", default=0, minimum=0),
        Param("interpolation", "Interpolation", kind="select", default="area", options=[
            {"value": "area", "label": "Area (shrinking)"}, {"value": "linear", "label": "Linear"}, {"value": "nearest", "label": "Nearest"}, {"value": "cubic", "label": "Cubic"},
        ]),
    ]
    outputs = [Port("image", "Image", "image"), Port("scale_x", "Scale X", "number"), Port("scale_y", "Scale Y", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        h, w = image.shape[:2]
        tw, th = ctx.integer("width", 0), ctx.integer("height", 0)
        if tw or th:
            if not tw:
                tw = int(w * th / h)
            if not th:
                th = int(h * tw / w)
        else:
            s = ctx.number("scale", 0.5)
            tw, th = max(1, int(w * s)), max(1, int(h * s))
        interp = {"area": cv2.INTER_AREA, "linear": cv2.INTER_LINEAR, "nearest": cv2.INTER_NEAREST, "cubic": cv2.INTER_CUBIC}[ctx.param("interpolation", "area")]
        out = cv2.resize(image, (tw, th), interpolation=interp)
        return Result(outputs={"image": out, "scale_x": tw / w, "scale_y": th / h}, message=f"{w}×{h} → {tw}×{th}")


COLOR_SPACE_OPTIONS = [
    {"value": "hsv", "label": "HSV"},
    {"value": "lab", "label": "Lab"},
]
_SEGMENT_COLORS = ["#ef4444", "#22c55e", "#3b82f6", "#f59e0b", "#a855f7", "#14b8a6", "#f97316", "#ec4899"]


def _as_bgr(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image


def _colour_space(image: np.ndarray, space: str) -> np.ndarray:
    bgr = _as_bgr(image)
    if space == "lab":
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    if space != "hsv":
        raise ToolError("Colour space must be hsv or lab")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)


def _parse_segments(text: Any) -> list[tuple[str, tuple[int, int, int, int, int, int]]]:
    segments: list[tuple[str, tuple[int, int, int, int, int, int]]] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            raise ToolError("Each segment must be name:h_low,h_high,s_low,s_high,v_low,v_high")
        name, values = line.split(":", 1)
        parts = [p.strip() for p in values.split(",")]
        if len(parts) != 6:
            raise ToolError("Each segment must have six numeric limits")
        try:
            nums = tuple(int(round(float(p))) for p in parts)
        except ValueError:
            raise ToolError("Segment limits must be numeric") from None
        segments.append(((name.strip() or f"class_{len(segments) + 1}")[:80], nums))
    if not segments:
        raise ToolError("At least one colour segment is required")
    if len(segments) > 65535:
        raise ToolError("At most 65535 colour segments are supported")
    return segments


def _range_mask(converted: np.ndarray, limits: tuple[int, int, int, int, int, int], space: str) -> np.ndarray:
    a0, a1, b0, b1, c0, c1 = limits
    if space == "hsv":
        a0, a1 = int(np.clip(a0, 0, 179)), int(np.clip(a1, 0, 179))
    else:
        a0, a1 = int(np.clip(a0, 0, 255)), int(np.clip(a1, 0, 255))
    b0, b1 = int(np.clip(b0, 0, 255)), int(np.clip(b1, 0, 255))
    c0, c1 = int(np.clip(c0, 0, 255)), int(np.clip(c1, 0, 255))
    if space == "hsv" and a0 > a1:
        return cv2.inRange(converted, (a0, b0, c0), (179, b1, c1)) | cv2.inRange(converted, (0, b0, c0), (a1, b1, c1))
    return cv2.inRange(converted, (a0, b0, c0), (a1, b1, c1))


def _clean_colour_mask(mask: np.ndarray, min_area: float, smooth: int) -> np.ndarray:
    out = mask
    if smooth >= 2:
        k = max(3, smooth | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        out = cv2.morphologyEx(out, cv2.MORPH_OPEN, kernel)
        out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, kernel)
    if min_area <= 1:
        return out
    n, labels, stats, _ = cv2.connectedComponentsWithStats(out, connectivity=8)
    if n <= 1:
        return out
    keep = stats[:, cv2.CC_STAT_AREA] >= float(min_area)
    keep[0] = False
    return np.where(keep[labels], 255, 0).astype(np.uint8)


class ColorSegmentTool(Tool):
    key = "color_segment"
    label = "Multi-colour segment"
    description = "Segments several HSV or Lab ranges in one pass and outputs an integer label map for Label map blobs."
    icon = "Tags"
    params = [
        Param("segments", "Segments", kind="multiline", required=True, default="red:170,10,80,255,80,255\ngreen:45,85,60,255,60,255\nblue:95,130,60,255,60,255",
              help_text="One segment per line: name:H_low,H_high,S_low,S_high,V_low,V_high. In HSV, H_low > H_high wraps through 0/180, which is how red ranges are usually written."),
        Param("space", "Colour space", kind="select", default="hsv", options=COLOR_SPACE_OPTIONS),
        Param("min_area", "Min area", kind="number", default=0, minimum=0, unit="px簡", teach=True),
        Param("smooth", "Smooth", kind="number", default=0, minimum=0, maximum=99, help_text="0 keeps the raw mask; 3 or larger applies open and close morphology."),
        Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon", "composite"], help_text="Leave blank for the whole image."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [Port("labels", "Label map", "image"), Port("areas", "Areas", "list"), Port("classes", "Classes", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        space = str(ctx.param("space", "hsv")).lower()
        converted = _colour_space(np.ascontiguousarray(c.image), space)
        segments = _parse_segments(ctx.param("segments", ""))
        local_dtype = np.uint16 if len(segments) > 255 else np.uint8
        local_labels = np.zeros(c.image.shape[:2], dtype=local_dtype)
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        classes: list[str] = []
        areas: list[dict[str, Any]] = []
        min_area = ctx.number("min_area", 0)
        smooth = max(0, ctx.integer("smooth", 0))
        for idx, (name, limits) in enumerate(segments, start=1):
            mask = _clean_colour_mask(_range_mask(converted, limits, space), min_area, smooth)
            if c.mask is not None:
                mask = cv2.bitwise_and(mask, c.mask)
            write = (mask > 0) & (local_labels == 0)
            local_labels[write] = idx
            final = (local_labels == idx).astype(np.uint8) * 255
            area = int(np.count_nonzero(final))
            classes.append(name)
            areas.append({"class_id": idx, "label": name, "area": area})
            contours, _ = cv2.findContours(final, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                offset = np.array([c.x0, c.y0], dtype=np.int32)
                overlays.append({
                    "kind": "contours",
                    "contours": [(cnt + offset).reshape(-1, 2).tolist() for cnt in contours],
                    "color": _SEGMENT_COLORS[(idx - 1) % len(_SEGMENT_COLORS)],
                    "width": 1,
                    "label": name,
                })
        labels = np.zeros(image.shape[:2], dtype=local_labels.dtype)
        labels[c.y0 : c.y0 + local_labels.shape[0], c.x0 : c.x0 + local_labels.shape[1]] = local_labels
        total = sum(a["area"] for a in areas)
        return Result(outputs={"labels": labels, "areas": areas, "classes": classes}, overlays=overlays,
                      message=f"{len(classes)} classes, {total} px")


def _colour_hist(image: np.ndarray, space: str, bins: int, mask: np.ndarray | None = None) -> np.ndarray:
    converted = _colour_space(np.ascontiguousarray(image), space)
    if space == "hsv":
        hist = cv2.calcHist([converted], [0, 1], mask, [bins, bins], [0, 180, 0, 256])
    else:
        hist = cv2.calcHist([converted], [1, 2], mask, [bins, bins], [0, 256, 0, 256])
    total = float(hist.sum())
    if total <= 0:
        raise ToolError("The colour histogram has no pixels")
    return (hist / total).astype(np.float32)


def _hist_signature(hist: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(hist > 0)
    if len(xs) == 0:
        return np.zeros((0, 3), dtype=np.float32)
    return np.column_stack([hist[ys, xs], xs.astype(np.float32), ys.astype(np.float32)]).astype(np.float32)


_COLOR_HIST_CACHE: "OrderedDict[tuple[Any, ...], tuple[np.ndarray, np.ndarray]]" = OrderedDict()
_COLOR_HIST_LOCK = threading.Lock()


def _sample_hist(sample: dict[str, Any], space: str, bins: int) -> tuple[np.ndarray, np.ndarray]:
    image_id = str(sample.get("id") or "")
    key = (image_id, space, bins)
    with _COLOR_HIST_LOCK:
        hit = _COLOR_HIST_CACHE.get(key)
        if hit is not None:
            _COLOR_HIST_CACHE.move_to_end(key)
            return hit
    image = fixed_images.load(image_id)
    if image is None:
        raise ToolError(f"Sample image '{sample.get('name') or image_id}' could not be loaded")
    hist = _colour_hist(image, space, bins)
    sig = _hist_signature(hist)
    with _COLOR_HIST_LOCK:
        _COLOR_HIST_CACHE[key] = (hist, sig)
        while len(_COLOR_HIST_CACHE) > 32:
            _COLOR_HIST_CACHE.popitem(last=False)
    return hist, sig


def _hist_similarity(hist: np.ndarray, sig: np.ndarray, sample_hist: np.ndarray, sample_sig: np.ndarray, metric: str) -> float:
    if metric == "earth_mover":
        if sig.size == 0 or sample_sig.size == 0:
            return 0.0
        distance = cv2.EMD(sig, sample_sig, cv2.DIST_L2)[0]
        max_distance = math.sqrt(2.0) * max(1, hist.shape[0] - 1)
        return float(np.clip(1.0 - distance / max_distance, 0.0, 1.0))
    return float(np.minimum(hist, sample_hist).sum())


class ColorClassifyTool(Tool):
    key = "color_classify"
    label = "Sample colour classify"
    description = "Compares the ROI colour histogram with fixed image samples and returns the closest sample label."
    icon = "Palette"
    params = [
        Param("samples", "Samples", kind="images", required=True),
        Param("space", "Colour space", kind="select", default="hsv", options=COLOR_SPACE_OPTIONS),
        Param("bins", "Bins", kind="number", default=16, minimum=2, maximum=64),
        Param("metric", "Metric", kind="select", default="histogram_intersection", options=[
            {"value": "histogram_intersection", "label": "Histogram intersection"},
            {"value": "earth_mover", "label": "Earth mover"},
        ]),
        Param("min_similarity", "Min similarity", kind="range", default=0.75, minimum=0, maximum=1, step=0.01, teach=True),
        Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon", "composite"], help_text="Leave blank for the whole image."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("ok", "Pass", "ok"), flow_out("ng", "Below similarity", "critical"),
        Port("label", "Label", "string"), Port("similarity", "Similarity", "number"), Port("ranking", "Ranking", "list"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        samples = ctx.param("samples", [])
        if not isinstance(samples, list) or not samples:
            raise ToolError("At least one sample image is required")
        image = ctx.require_image()
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        space = str(ctx.param("space", "hsv")).lower()
        bins = max(2, min(64, ctx.integer("bins", 16)))
        metric = str(ctx.param("metric", "histogram_intersection"))
        hist = _colour_hist(c.image, space, bins, c.mask)
        sig = _hist_signature(hist)
        ranking: list[dict[str, Any]] = []
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            sample_hist, sample_sig = _sample_hist(sample, space, bins)
            label = str(sample.get("name") or sample.get("id") or "")
            ranking.append({
                "id": str(sample.get("id") or ""),
                "label": label,
                "similarity": round(_hist_similarity(hist, sig, sample_hist, sample_sig, metric), 6),
            })
        if not ranking:
            raise ToolError("No usable sample images were provided")
        ranking.sort(key=lambda item: float(item["similarity"]), reverse=True)
        top = ranking[0]
        similarity = float(top["similarity"])
        ok = similarity >= ctx.number("min_similarity", 0.75)
        label = str(top["label"])
        overlays = [region_overlay(region, color="#22c55e" if ok else "#ef4444", label=f"{label} {similarity:.3f}")] if region else []
        return Result(
            outputs={"label": label, "similarity": similarity, "ranking": ranking[:3]},
            overlays=overlays, branch="ok" if ok else "ng", status="ok" if ok else "ng",
            message=f"{label} {similarity:.3f}" if ok else f"{label} {similarity:.3f} below minimum",
        )


class ColorConvertTool(Tool):
    key = "color_convert"
    label = "Colour space / channel"
    description = "Convert to HSV or Lab, pull out a single channel, or merge three grayscale channels into colour."
    icon = "Palette"
    params = [
        Param("mode", "Output", kind="select", default="hsv_s", options=[
            {"value": "bgr_b", "label": "B channel"}, {"value": "bgr_g", "label": "G channel"}, {"value": "bgr_r", "label": "R channel"},
            {"value": "hsv_h", "label": "HSV: H"}, {"value": "hsv_s", "label": "HSV: S"}, {"value": "hsv_v", "label": "HSV: V"},
            {"value": "lab_l", "label": "Lab: L"}, {"value": "lab_a", "label": "Lab: a"}, {"value": "lab_b", "label": "Lab: b"},
            {"value": "hsv", "label": "Whole HSV (3 channels)"}, {"value": "merge_rgb", "label": "Merge R/G/B grayscale"},
        ]),
    ]
    inputs = [
        Port("image", "Image", "image", required=False),
        Port("r", "R grayscale", "image", required=False),
        Port("g", "G grayscale", "image", required=False),
        Port("b", "B grayscale", "image", required=False),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        mode = ctx.param("mode", "hsv_s")
        if mode == "merge_rgb":
            channels = {key: ctx.image(key) for key in ("r", "g", "b")}
            refs = [img for img in channels.values() if img is not None]
            if not refs:
                raise ToolError("Merge RGB needs at least one grayscale channel")
            shape = refs[0].shape[:2]
            dtype = refs[0].dtype
            merged: dict[str, np.ndarray] = {}
            for key, img in channels.items():
                if img is None:
                    merged[key] = np.zeros(shape, dtype=dtype)
                    continue
                gray = to_gray(img)
                if gray.shape[:2] != shape:
                    raise ToolError(
                        f"Merge RGB channel '{key}' is {gray.shape[1]}x{gray.shape[0]} but the first channel is {shape[1]}x{shape[0]}"
                    )
                merged[key] = gray.astype(dtype, copy=False)
            return Result(outputs={"image": cv2.merge([merged["b"], merged["g"], merged["r"]])}, message=f"merged {shape[1]}x{shape[0]}")
        image = ctx.require_image()
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if mode == "hsv":
            return Result(outputs={"image": cv2.cvtColor(image, cv2.COLOR_BGR2HSV)})
        space, ch = mode.split("_")
        idx = {"b": 0, "g": 1, "r": 2, "h": 0, "s": 1, "v": 2, "l": 0, "a": 1}[ch] if space != "lab" or ch != "b" else 2
        if space == "hsv":
            conv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        elif space == "lab":
            conv = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        else:
            conv = image
        return Result(outputs={"image": np.ascontiguousarray(conv[:, :, idx])})


class ColorRangeTool(Tool):
    key = "color_range"
    label = "Colour range mask"
    description = "Pixels inside the HSV range become 255 (a hue range wrapping through 0, as red does, is supported)."
    icon = "Pipette"
    params = [
        Param("h_low", "H min", kind="number", default=0, minimum=0, maximum=179, teach=True),
        Param("h_high", "H max", kind="number", default=179, minimum=0, maximum=179, teach=True),
        Param("s_low", "S min", kind="number", default=0, minimum=0, maximum=255, teach=True),
        Param("s_high", "S max", kind="number", default=255, minimum=0, maximum=255, teach=True),
        Param("v_low", "V min", kind="number", default=0, minimum=0, maximum=255, teach=True),
        Param("v_high", "V max", kind="number", default=255, minimum=0, maximum=255, teach=True),
    ]
    outputs = [Port("image", "Mask", "image"), Port("ratio", "Coverage", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hl, hh = ctx.integer("h_low", 0), ctx.integer("h_high", 179)
        lo = (0, ctx.integer("s_low", 0), ctx.integer("v_low", 0))
        hi = (179, ctx.integer("s_high", 255), ctx.integer("v_high", 255))
        if hl <= hh:
            mask = cv2.inRange(hsv, (hl, lo[1], lo[2]), (hh, hi[1], hi[2]))
        else:
            mask = cv2.inRange(hsv, (hl, lo[1], lo[2]), (179, hi[1], hi[2])) | cv2.inRange(hsv, (0, lo[1], lo[2]), (hh, hi[1], hi[2]))
        ratio = float(cv2.countNonZero(mask)) / mask.size
        return Result(outputs={"image": mask, "ratio": ratio}, message=f"Coverage {ratio*100:.2f}%")


class ArithmeticTool(Tool):
    key = "arithmetic"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Image maths"
    description = "Add, subtract, difference, min, max, mean, weighted blend, AND, OR or XOR two images, or invert and adjust brightness and contrast on one."
    icon = "Calculator"
    params = [
        Param("op", "Operation", kind="select", default="absdiff", options=[
            {"value": "absdiff", "label": "Absolute difference |A-B|"}, {"value": "add", "label": "A+B"}, {"value": "subtract", "label": "A-B"},
            {"value": "min", "label": "Minimum"}, {"value": "max", "label": "Maximum"}, {"value": "mean", "label": "Mean"},
            {"value": "weighted", "label": "Weighted A+B"},
            {"value": "and", "label": "A AND B"}, {"value": "or", "label": "A OR B"}, {"value": "xor", "label": "A XOR B"},
            {"value": "invert", "label": "Invert A"}, {"value": "gain", "label": "A×gain + bias"},
        ]),
        Param("weight", "Weight A", kind="range", default=0.5, minimum=0, maximum=1, step=0.05, visible_when={"param": "op", "in": ["weighted"]}),
        Param("gain", "gain", kind="number", default=1.0, step=0.1, visible_when={"param": "op", "in": ["gain"]}),
        Param("bias", "bias", kind="number", default=0, visible_when={"param": "op", "in": ["gain"]}),
    ]
    inputs = [Port("a", "A", "image"), Port("b", "B", "image", required=False)]

    def execute(self, ctx: ToolContext) -> Result:
        a = ctx.require_image("a")
        b = ctx.image("b")
        op = ctx.param("op", "absdiff")
        if op == "invert":
            return Result(outputs={"image": cv2.bitwise_not(a)})
        if op == "gain":
            return Result(outputs={"image": cv2.convertScaleAbs(a, alpha=ctx.number("gain", 1.0), beta=ctx.number("bias", 0))})
        if b is None:
            raise ToolError("This operation needs a second image B")
        if a.shape != b.shape:
            if a.ndim != b.ndim:
                b = to_gray(b) if a.ndim == 2 else cv2.cvtColor(b, cv2.COLOR_GRAY2BGR)
            if a.shape[:2] != b.shape[:2]:
                b = cv2.resize(b, (a.shape[1], a.shape[0]))
        if op == "min":
            return Result(outputs={"image": cv2.min(a, b)})
        if op == "max":
            return Result(outputs={"image": cv2.max(a, b)})
        if op == "mean":
            return Result(outputs={"image": cv2.addWeighted(a, 0.5, b, 0.5, 0)})
        if op == "weighted":
            weight = min(1.0, max(0.0, ctx.number("weight", 0.5)))
            return Result(outputs={"image": cv2.addWeighted(a, weight, b, 1.0 - weight, 0)})
        fn = {"absdiff": cv2.absdiff, "add": cv2.add, "subtract": cv2.subtract, "and": cv2.bitwise_and, "or": cv2.bitwise_or, "xor": cv2.bitwise_xor}[op]
        return Result(outputs={"image": fn(a, b)})


class MaskApplyTool(Tool):
    key = "apply_mask"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Apply mask"
    description = "Keep only the pixels where the mask is 255, or fill either side of the mask with a grey level."
    icon = "Layers"
    params = [
        Param("side", "Fill side", kind="select", default="outside", options=[
            {"value": "outside", "label": "Outside mask"},
            {"value": "inside", "label": "Inside mask"},
        ]),
        Param("fill_value", "Fill value", kind="number", default=0, minimum=0, maximum=255),
        Param("fill", "Fill outside mask", kind="number", default=0, minimum=0, maximum=255, group="Compatibility"),
    ]
    inputs = [Port("image", "Image", "image"), Port("mask", "Mask", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        mask = to_gray(ctx.require_image("mask"))
        if mask.shape[:2] != image.shape[:2]:
            mask = cv2.resize(mask, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST)
        fill = ctx.integer("fill_value", ctx.integer("fill", 0)) if "fill_value" in ctx.params else ctx.integer("fill", 0)
        if ctx.param("side", "outside") == "inside":
            out = image.copy()
            paint = np.full_like(image, fill)
            cv2.copyTo(paint, mask, out)
            return Result(outputs={"image": out})
        # copyTo（新配置的目的地會先清零）比 bitwise_and(mask=) 快約 40%；要填值時直接以填值為底再覆蓋。
        if fill:
            out = np.full_like(image, fill)
            cv2.copyTo(image, mask, out)
        else:
            out = cv2.copyTo(image, mask)
        return Result(outputs={"image": out})


class PasteBackTool(Tool):
    key = "paste_back"
    accepts = ("u8", "u16", "f32")
    label = "Paste back"
    description = "Pastes a processed ROI image back onto a larger image, clipping at the image boundary."
    category = "preprocess"
    icon = "ClipboardPaste"
    params = [
        Param("x", "X", kind="number", default=0),
        Param("y", "Y", kind="number", default=0),
        Param("region", "Region", kind="roi", required=False, shapes=["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon", "composite"]),
        Param("mode", "Mode", kind="select", default="replace", options=[
            {"value": "replace", "label": "Replace"},
            {"value": "blend", "label": "Blend"},
            {"value": "masked", "label": "Masked"},
        ]),
        Param("alpha", "Alpha", kind="range", default=0.5, minimum=0, maximum=1, step=0.05, visible_when={"param": "mode", "in": ["blend"]}),
    ]
    inputs = [
        Port("image", "Base image", "image"),
        Port("patch", "Patch", "image"),
        Port("region", "Region", "region", required=False),
        Port("mask", "Mask", "image", required=False),
    ]
    outputs = [Port("image", "Image", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        base = ctx.require_image()
        patch = _match_image_shape(ctx.require_image("patch"), base)
        region = ctx.roi("region")
        x = ctx.integer("x", 0)
        y = ctx.integer("y", 0)
        if region is not None:
            x, y, _, _ = bounding_rect(region, base.shape[1], base.shape[0])
        out = base.copy()
        h, w = base.shape[:2]
        ph, pw = patch.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w, x + pw), min(h, y + ph)
        if x0 >= x1 or y0 >= y1:
            return Result(outputs={"image": out}, message="outside")
        sx0, sy0 = x0 - x, y0 - y
        sx1, sy1 = sx0 + (x1 - x0), sy0 + (y1 - y0)
        src = patch[sy0:sy1, sx0:sx1]
        dst = out[y0:y1, x0:x1]
        mode = str(ctx.param("mode", "replace"))
        if mode == "blend":
            alpha = min(1.0, max(0.0, ctx.number("alpha", 0.5)))
            out[y0:y1, x0:x1] = cv2.addWeighted(src, alpha, dst, 1.0 - alpha, 0)
        elif mode == "masked":
            mask = ctx.image("mask")
            if mask is None:
                mask = np.full((ph, pw), 255, dtype=np.uint8)
            mask = to_gray(mask)
            if mask.shape[:2] != (ph, pw):
                mask = cv2.resize(mask, (pw, ph), interpolation=cv2.INTER_NEAREST)
            cv2.copyTo(src, mask[sy0:sy1, sx0:sx1], dst)
        else:
            out[y0:y1, x0:x1] = src
        return Result(outputs={"image": out}, message=f"{x0},{y0} {x1 - x0}x{y1 - y0}")


def _match_image_shape(image: np.ndarray, like: np.ndarray) -> np.ndarray:
    if image.ndim == like.ndim:
        return image.astype(like.dtype, copy=False)
    if like.ndim == 2:
        return to_gray(image).astype(like.dtype, copy=False)
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR).astype(like.dtype, copy=False)


class RotateFlipTool(Tool):
    key = "rotate_flip"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Rotate / flip"
    description = "Rotate by a multiple of 90°, rotate by any angle, or flip horizontally or vertically."
    icon = "RotateCw"
    params = [
        Param("angle", "Angle (clockwise)", kind="number", default=0, minimum=-360, maximum=360),
        Param("flip", "Flip", kind="select", default="none", options=[{"value": "none", "label": "None"}, {"value": "h", "label": "Horizontal"}, {"value": "v", "label": "Vertical"}, {"value": "hv", "label": "Horizontal and vertical"}]),
        Param("keep_size", "Keep size", kind="boolean", default=True),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        angle = ctx.number("angle", 0) % 360
        if angle == 90:
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        elif angle == 180:
            image = cv2.rotate(image, cv2.ROTATE_180)
        elif angle == 270:
            image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif angle:
            h, w = image.shape[:2]
            m = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
            if ctx.flag("keep_size", True):
                image = cv2.warpAffine(image, m, (w, h), borderMode=cv2.BORDER_REPLICATE)
            else:
                cos, sin = abs(m[0, 0]), abs(m[0, 1])
                nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
                m[0, 2] += nw / 2 - w / 2
                m[1, 2] += nh / 2 - h / 2
                image = cv2.warpAffine(image, m, (nw, nh), borderMode=cv2.BORDER_REPLICATE)
        flip = ctx.param("flip", "none")
        if flip == "h":
            image = cv2.flip(image, 1)
        elif flip == "v":
            image = cv2.flip(image, 0)
        elif flip == "hv":
            image = cv2.flip(image, -1)
        return Result(outputs={"image": image})


class ConvertDepthTool(Tool):
    key = "convert_depth"
    label = "Convert bit depth"
    description = "Converts between 8-bit, 16-bit and floating-point images. Going to 8-bit you may right-shift (linear and predictable) or min-max stretch (using the full range)."
    category = "preprocess"
    icon = "Binary"
    accepts = ("u8", "u16", "f32")
    params = [
        Param("to", "Target depth", kind="select", default="u8", options=[
            {"value": "u8", "label": "8-bit (U8)"}, {"value": "u16", "label": "16-bit (U16)"}, {"value": "f32", "label": "Float (SGL)"},
        ]),
        Param("scale", "To 8-bit", kind="select", default="shift", options=[
            {"value": "shift", "label": "Proportional (16-bit shifted right by 8)"}, {"value": "minmax", "label": "min-max stretch"}, {"value": "clip", "label": "Clip"},
        ], visible_when={"param": "to", "in": ["u8"]}),
    ]
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("image", "Image", "image"), Port("depth", "Bit depth", "string")]

    def execute(self, ctx: ToolContext) -> Result:
        from apps.vision.tools import imgfmt

        image = ctx.require_image()
        to = ctx.param("to", "u8")
        if to == "u8":
            scale = ctx.param("scale", "shift")
            if image.dtype == np.uint8:
                out = image
            elif scale == "clip":
                out = np.clip(image, 0, 255).astype(np.uint8)
            elif scale == "minmax":
                x = image.astype(np.float32)
                lo, hi = float(np.nanmin(x)), float(np.nanmax(x))
                out = np.clip((x - lo) * (255.0 / (hi - lo) if hi > lo else 1.0), 0, 255).astype(np.uint8)
            else:
                out = imgfmt.normalize_u8(image)
        elif to == "u16":
            if image.dtype == np.uint16:
                out = image
            elif image.dtype == np.uint8:
                out = image.astype(np.uint16) << 8
            else:
                x = image.astype(np.float32)
                lo, hi = float(np.nanmin(x)), float(np.nanmax(x))
                out = np.clip((x - lo) * (65535.0 / (hi - lo) if hi > lo else 1.0), 0, 65535).astype(np.uint16)
        else:
            out = image.astype(np.float32)
        return Result(outputs={"image": out, "depth": imgfmt.depth_of(out)}, message=f"→ {imgfmt.depth_of(out)}")


class LutTool(Tool):
    key = "lut"
    label = "Look-up table (LUT)"
    description = "Grey mapping and contrast enhancement: linear (brightness and contrast), gamma, log, exponential, square, square root, invert, histogram equalisation and CLAHE. Look-up mappings are applied per channel on colour images."
    category = "preprocess"
    icon = "Spline"
    params = [
        Param("mode", "Convert", kind="select", default="linear", options=[
            {"value": "linear", "label": "Linear (brightness / contrast)"}, {"value": "power", "label": "Gamma (power)"},
            {"value": "log", "label": "Log (opens up the shadows)"}, {"value": "exp", "label": "Exponential (opens up the highlights)"},
            {"value": "sqrt", "label": "Square root"}, {"value": "square", "label": "Square"}, {"value": "invert", "label": "Invert"},
            {"value": "equalize", "label": "Histogram equalisation"}, {"value": "clahe", "label": "CLAHE (local contrast)"},
            {"value": "normalize_ratio", "label": "Percentile stretch"},
            {"value": "normalize_std", "label": "Mean / standard deviation normalisation"},
        ]),
        Param("clip", "CLAHE clip", kind="number", default=2.0, minimum=0.1, maximum=40, step=0.1, visible_when={"param": "mode", "in": ["clahe"]}),
        Param("tile", "CLAHE tiles", kind="number", default=8, minimum=1, maximum=64, visible_when={"param": "mode", "in": ["clahe"]}),
        Param("brightness", "Brightness", kind="range", default=0, minimum=-100, maximum=100, step=1, visible_when={"param": "mode", "in": ["linear"]}, teach=True),
        Param("contrast", "Contrast", kind="range", default=1.0, minimum=0.1, maximum=3.0, step=0.05, visible_when={"param": "mode", "in": ["linear"]}, teach=True),
        Param("gamma", "Gamma", kind="range", default=1.0, minimum=0.1, maximum=5.0, step=0.05, visible_when={"param": "mode", "in": ["power"]}, teach=True),
        Param("low_percent", "Low percentile", kind="number", default=1, minimum=0, maximum=100, step=0.1, visible_when={"param": "mode", "in": ["normalize_ratio"]}, teach=True),
        Param("high_percent", "High percentile", kind="number", default=99, minimum=0, maximum=100, step=0.1, visible_when={"param": "mode", "in": ["normalize_ratio"]}, teach=True),
        Param("target_mean", "Target mean", kind="number", default=128, minimum=0, maximum=255, step=1, visible_when={"param": "mode", "in": ["normalize_std"]}, teach=True),
        Param("target_std", "Target standard deviation", kind="number", default=40, minimum=0, maximum=128, step=1, visible_when={"param": "mode", "in": ["normalize_std"]}, teach=True),
    ]
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("image", "Image", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        # 舊「對比增強」（hist_eq）併入：參數名 method、值 global → equalize
        mode = ctx.param("mode", "") or ctx.param("method", "") or "linear"
        if mode == "global":
            mode = "equalize"
        if mode == "equalize":
            return Result(outputs={"image": cv2.equalizeHist(to_gray(image))}, message=mode)
        if mode == "clahe":
            t = max(1, ctx.integer("tile", 8))
            clahe = cv2.createCLAHE(clipLimit=ctx.number("clip", 2.0), tileGridSize=(t, t))
            return Result(outputs={"image": clahe.apply(to_gray(image))}, message=mode)
        if mode == "normalize_ratio":
            low = min(100.0, max(0.0, ctx.number("low_percent", 1)))
            high = min(100.0, max(0.0, ctx.number("high_percent", 99)))
            if high < low:
                low, high = high, low
            lo, hi = np.percentile(image.astype(np.float32), [low, high])
            scale = 255.0 / (float(hi) - float(lo)) if hi > lo else 1.0
            out = np.clip((image.astype(np.float32) - float(lo)) * scale, 0, 255).astype(np.uint8)
            return Result(outputs={"image": out}, message=f"{mode} {low:g}-{high:g}%")
        if mode == "normalize_std":
            src = image.astype(np.float32)
            mean, std = float(src.mean()), float(src.std())
            target_mean = ctx.number("target_mean", 128)
            target_std = max(0.0, ctx.number("target_std", 40))
            out = np.full(src.shape, target_mean, dtype=np.float32) if std < 1e-9 else (src - mean) * (target_std / std) + target_mean
            return Result(outputs={"image": np.clip(np.rint(out), 0, 255).astype(np.uint8)}, message=f"{mode} mean={target_mean:g} std={target_std:g}")
        x = np.arange(256, dtype=np.float32)
        if mode == "linear":
            table = (x - 128.0) * ctx.number("contrast", 1.0) + 128.0 + ctx.number("brightness", 0.0)
        elif mode == "power":
            table = np.power(x / 255.0, ctx.number("gamma", 1.0)) * 255.0
        elif mode == "log":
            table = np.log1p(x) * (255.0 / np.log1p(255.0))
        elif mode == "exp":
            table = (np.expm1(x / 255.0 * 4.0)) * (255.0 / np.expm1(4.0))
        elif mode == "sqrt":
            table = np.sqrt(x / 255.0) * 255.0
        elif mode == "square":
            table = np.square(x / 255.0) * 255.0
        else:
            table = 255.0 - x
        lut = np.clip(table, 0, 255).astype(np.uint8)
        return Result(outputs={"image": cv2.LUT(image, lut)}, message=mode)


#: 旋轉異向核的快取（參數相同就重用；一組 12 個 21×21 的核算一次約 1 ms，每張影像都算太浪費）。
_SURFACE_KERNELS: dict[tuple, tuple[np.ndarray, ...]] = {}
#: 快取上限（參數是使用者調的，不會有幾百組）。
_KERNEL_CACHE_MAX = 32


def surface_kernels(width: int, height: int, directions: int, sigma: float) -> tuple[np.ndarray, ...]:
    """一組沿不同方向的細長「線偵測」核（跨線方向是二階高斯導數，沿線方向是高斯平滑）。

    刮傷、髮絲、細裂紋在灰階上是一條「比周圍暗（或亮）一點」的細長帶子，一般的邊緣濾波
    會被工件本身的紋理淹掉；沿著缺陷方向平均、跨著缺陷方向取二階導數，就只留下細長的東西。
    `directions` 個方向平均分佈在 0~180°（線沒有方向性，180° 之後會重複）。
    """
    key = (width, height, directions, round(float(sigma), 4))
    cached = _SURFACE_KERNELS.get(key)
    if cached is not None:
        return cached
    half_w, half_h = width // 2, height // 2
    ys, xs = np.mgrid[-half_h:half_h + 1, -half_w:half_w + 1].astype(np.float32)
    along = max(0.6, height / 4.0)  # 沿線方向的平滑量：核愈長平滑愈多
    kernels: list[np.ndarray] = []
    for i in range(directions):
        theta = math.pi * i / directions
        cos, sin = math.cos(theta), math.sin(theta)
        # u＝跨線方向、v＝沿線方向（畫面座標 y 向下，角度順時針為正）
        u = xs * cos + ys * sin
        v = -xs * sin + ys * cos
        # 中心正、兩側負：亮的細線回正值、暗的細線回負值（工具再依 polarity 取號）
        across = (1.0 / sigma ** 2 - u * u / sigma ** 4) * np.exp(-(u * u) / (2 * sigma * sigma))
        kernel = across * np.exp(-(v * v) / (2 * along * along))
        kernel -= kernel.mean()  # 零均值：平坦區域回 0，才不會被整體亮度帶著走
        norm = float(np.abs(kernel).sum())
        kernels.append((kernel / norm * 2.0).astype(np.float32) if norm > 1e-9 else kernel.astype(np.float32))
    if len(_SURFACE_KERNELS) >= _KERNEL_CACHE_MAX:
        _SURFACE_KERNELS.clear()
    _SURFACE_KERNELS[key] = tuple(kernels)
    return _SURFACE_KERNELS[key]


class SurfaceFilterTool(Tool):
    key = "surface_filter"
    label = "Surface defect filter"
    description = (
        "Brings out scratches, hairs and fine cracks on a surface that has its own texture. A plain edge filter finds the "
        "texture as well; this one averages along the defect and differentiates across it, at several angles, and keeps the "
        "strongest answer — so a long thin mark stands out and the grain does not. Threshold the result, or judge the peak."
    )
    category = "preprocess"
    icon = "Scan"
    params = [
        Param("polarity", "Look for", kind="select", default="dark", options=[
            {"value": "dark", "label": "Darker than the surface (the usual scratch)"},
            {"value": "bright", "label": "Brighter than the surface"},
            {"value": "any", "label": "Either"},
        ], teach=True),
        Param("width", "Defect width", kind="number", default=3, minimum=1, maximum=31, step=2, unit="px", teach=True,
              help_text="Roughly how many pixels across the mark is. Too small and the texture comes through; too large and a fine scratch is lost."),
        Param("length", "Defect length", kind="number", default=15, minimum=3, maximum=63, step=2, unit="px", teach=True,
              help_text="How far the mark runs. Longer averages more of the surface away, but a short mark then disappears too."),
        Param("directions", "Directions", kind="number", default=8, minimum=2, maximum=32, step=1,
              help_text="How many angles to try, spread over half a turn. More is slower and only slightly better; 8 covers most work."),
        Param("gain", "Gain", kind="number", default=8.0, minimum=0.1, maximum=100, step=0.1, teach=True,
              help_text="Multiplies the answer before it becomes a picture. Turn it up until the mark is clearly visible and the surface stays dark."),
        Param("offset", "Offset", kind="number", default=0, minimum=-255, maximum=255, group="Advanced",
              help_text="Added to every pixel of the answer."),
        Param("roi", "Region", kind="roi", shapes=["rect", "rotated_rect", "circle", "annulus", "polygon"], required=False,
              help_text="Only this area is filtered; the rest of the picture comes through untouched."),
    ]
    inputs = [Port("image", "Image", "image"), Port("region", "Region", "region", required=False)]
    outputs = [
        Port("image", "Filtered", "image"),
        Port("max_response", "Strongest", "number"),
        Port("mean_response", "Average", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        region = ctx.roi()
        area = None if region is None else crop(gray, region)
        crop_img = gray if area is None else area.image
        if crop_img.size == 0:
            raise ToolError("The region falls outside the picture")
        width = max(1, ctx.integer("width", 3) | 1)
        length = max(3, ctx.integer("length", 15) | 1)
        directions = min(32, max(2, ctx.integer("directions", 8)))
        sigma = max(0.5, width / 2.0)
        # 核只要蓋到 ±3σ 就夠（再寬只是多算），高度就是缺陷長度
        kernels = surface_kernels(2 * int(round(3 * sigma)) + 1, length, directions, sigma)
        polarity = str(ctx.param("polarity", "dark"))
        # 直接餵 8-bit 進去、輸出 float：先轉成 float32 會讓每一趟多讀四倍記憶體（實測慢 30%）
        source = crop_img
        best: np.ndarray | None = None
        for kernel in kernels:
            response = accel.filter2d(source, cv2.CV_32F, kernel)
            if polarity == "dark":
                response = -response
            elif polarity == "any":
                response = np.abs(response)
            best = response if best is None else np.maximum(best, response)
        assert best is not None
        peak = float(best.max())
        average = float(best.mean())
        scaled = np.clip(best * ctx.number("gain", 8.0) + ctx.number("offset"), 0, 255).astype(np.uint8)
        if region is None:
            out = scaled
        else:
            # 只處理區域內：其餘照原樣傳下去（下游還看得到工件，不是一片黑）
            out = gray.copy()
            h, w = crop_img.shape[:2]
            patch = out[area.y0:area.y0 + h, area.x0:area.x0 + w]
            # 非矩形區域：只換遮罩之內的像素，其餘照原樣（下游還看得到工件，不是一片黑）
            patch[:] = scaled if area.mask is None else np.where(area.mask > 0, scaled, patch)
        return Result(
            outputs={"image": out, "max_response": round(peak, 4), "mean_response": round(average, 4)},
            overlays=[region_overlay(region)] if region is not None else [],
            message=f"peak {peak:.3f}, average {average:.3f} ({directions} directions)",
        )


class FilterTool(Tool):
    key = "filter"
    label = "Convolution filter"
    description = "Convolution and edge filters: sharpen, Canny edges, Laplacian, Sobel and Prewitt gradients, high pass, emboss, or a custom 3×3 kernel as JSON. Use the blur tool for smoothing."
    category = "preprocess"
    icon = "Grid3x3"
    params = [
        Param("method", "Method", kind="select", default="sharpen", options=[
            {"value": "sharpen", "label": "Sharpen"}, {"value": "canny", "label": "Canny edges (binary)"}, {"value": "laplacian", "label": "Laplacian"},
            {"value": "gradient", "label": "Gradient magnitude (Sobel)"}, {"value": "sobel_x", "label": "Sobel X"}, {"value": "sobel_y", "label": "Sobel Y"},
            {"value": "prewitt", "label": "Prewitt gradient"}, {"value": "highpass", "label": "High pass"}, {"value": "emboss", "label": "Emboss"},
            {"value": "custom", "label": "Custom 3x3"},
        ]),
        Param("strength", "Strength", kind="range", default=1.0, minimum=0.1, maximum=3.0, step=0.1, visible_when={"param": "method", "in": ["sharpen"]}, teach=True),
        Param("low", "Canny low", kind="number", default=50, minimum=0, maximum=1000, visible_when={"param": "method", "in": ["canny"]}, teach=True),
        Param("high", "Canny high", kind="number", default=150, minimum=0, maximum=1000, visible_when={"param": "method", "in": ["canny"]}, teach=True),
        Param("ksize", "Kernel size", kind="number", default=3, minimum=1, maximum=7, step=2, visible_when={"param": "method", "in": ["canny", "laplacian", "gradient", "sobel_x", "sobel_y"]}),
        Param("kernel", "Custom kernel", kind="json", default=[[0, -1, 0], [-1, 5, -1], [0, -1, 0]], visible_when={"param": "method", "in": ["custom"]}, help_text="A 3×3 array of numbers."),
    ]
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("image", "Image", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        method = ctx.param("method", "sharpen")
        if method == "sobel":
            method = "gradient"  # 舊「邊緣」工具（edges）併入後的別名
        ksize = ctx.integer("ksize", 3)
        if ksize % 2 == 0:
            ksize += 1
        ksize = min(7, max(1, ksize))
        if method == "sharpen":
            k = float(ctx.number("strength", 1.0))
            kernel = np.array([[0, -k, 0], [-k, 1 + 4 * k, -k], [0, -k, 0]], dtype=np.float32)
            out = accel.filter2d(image, -1, kernel)
        elif method == "canny":
            out = cv2.Canny(to_gray(image), ctx.number("low", 50), ctx.number("high", 150), apertureSize=max(3, ksize))
        elif method == "laplacian":
            out = cv2.convertScaleAbs(cv2.Laplacian(to_gray(image), cv2.CV_32F, ksize=ksize))
        elif method in ("gradient", "sobel_x", "sobel_y"):
            g = to_gray(image)
            gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=ksize)
            gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=ksize)
            if method == "sobel_x":
                out = cv2.convertScaleAbs(gx)
            elif method == "sobel_y":
                out = cv2.convertScaleAbs(gy)
            else:
                out = cv2.convertScaleAbs(cv2.magnitude(gx, gy))
        elif method == "prewitt":
            g = to_gray(image).astype(np.float32)
            kx = np.array([[-1, 0, 1], [-1, 0, 1], [-1, 0, 1]], dtype=np.float32)
            gx = cv2.filter2D(g, -1, kx)
            gy = cv2.filter2D(g, -1, kx.T)
            out = cv2.convertScaleAbs(cv2.magnitude(gx, gy))
        elif method == "highpass":
            g = to_gray(image)
            out = cv2.convertScaleAbs(g.astype(np.float32) - cv2.GaussianBlur(g, (0, 0), 3).astype(np.float32) + 128.0)
        elif method == "emboss":
            kernel = np.array([[-2, -1, 0], [-1, 1, 1], [0, 1, 2]], dtype=np.float32)
            out = accel.filter2d(to_gray(image), -1, kernel)
        else:
            raw = ctx.param("kernel")
            try:
                kernel = np.asarray(raw, dtype=np.float32)
                if kernel.shape != (3, 3):
                    raise ValueError
            except (TypeError, ValueError):
                raise ToolError("A custom kernel must be a 3×3 array of numbers") from None
            out = accel.filter2d(image, -1, kernel)
        return Result(outputs={"image": out}, message=method)


class FftFilterTool(Tool):
    key = "fft_filter"
    label = "Frequency filter (FFT)"
    description = "Frequency-domain filtering: low pass to remove periodic texture and noise, high pass to keep edges, either truncated or Gaussian-attenuated. It also outputs the spectrum for inspection."
    category = "preprocess"
    icon = "AudioWaveform"
    heavy = True
    accepts = ("u8", "u16", "f32")
    params = [
        Param("mode", "Filter", kind="select", default="lowpass", options=[
            {"value": "lowpass", "label": "Low pass (keeps the large structures)"}, {"value": "highpass", "label": "High pass (keeps edges and fine texture, with mid grey 128 as zero)"},
        ]),
        Param("style", "Mode", kind="select", default="attenuate", options=[
            {"value": "truncate", "label": "Truncate"}, {"value": "attenuate", "label": "Gaussian attenuation"},
        ]),
        Param("cutoff", "Cut-off (radius ratio)", kind="range", default=0.1, minimum=0.01, maximum=1.0, step=0.01, teach=True),
    ]
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("image", "Image", "image"), Port("spectrum", "Spectrum", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        gray = to_gray(image)
        x = gray.astype(np.float32)
        f = np.fft.fftshift(np.fft.fft2(x))
        h, w = x.shape
        yy, xx = np.ogrid[:h, :w]
        r = np.hypot(yy - h / 2.0, xx - w / 2.0) / (min(h, w) / 2.0)
        cutoff = max(0.01, ctx.number("cutoff", 0.1))
        if ctx.param("style", "attenuate") == "truncate":
            mask = (r <= cutoff).astype(np.float32)
        else:
            mask = np.exp(-(r / cutoff) ** 2).astype(np.float32)
        if ctx.param("mode", "lowpass") == "highpass":
            mask = 1.0 - mask
        out_f = np.fft.ifft2(np.fft.ifftshift(f * mask))
        # 取實部（取絕對值會把高通的負響應翻正，邊緣兩側都變亮）；高通以中灰為零點讓正負響應都看得到，浮點保留帶號。
        out = out_f.real.astype(np.float32)
        highpass = ctx.param("mode", "lowpass") == "highpass"
        if gray.dtype == np.uint8:
            out = np.clip(out + (128.0 if highpass else 0.0), 0, 255).astype(np.uint8)
        elif gray.dtype == np.uint16:
            out = np.clip(out + (32768.0 if highpass else 0.0), 0, 65535).astype(np.uint16)
        spectrum = np.log1p(np.abs(f))
        spectrum = (spectrum / spectrum.max() * 255.0).astype(np.uint8) if spectrum.max() > 0 else np.zeros_like(gray, dtype=np.uint8)
        return Result(outputs={"image": out, "spectrum": spectrum}, message=f"{ctx.param('mode', 'lowpass')} r={cutoff:g}")


class WarpPerspectiveTool(Tool):
    key = "warp_perspective"
    label = "Perspective correction"
    description = "Flattens a quadrilateral into a rectangle: straighten a panel or label shot at an angle before measuring it."
    category = "preprocess"
    icon = "Frame"
    accepts = ("u8", "u16", "f32")
    params = [
        Param("roi", "Source quadrilateral", kind="roi", shapes=["polygon"], required=True, teach=True, help_text="Draw four points (only the first four are used)."),
        Param("width", "Output width", kind="number", default=0, minimum=0, help_text="0 = derived from the edge length."),
        Param("height", "Output height", kind="number", default=0, minimum=0),
    ]
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("image", "Image", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        region = ctx.roi()
        pts = (region or {}).get("points") or []
        if len(pts) < 4:
            raise ToolError("Perspective correction needs a four-point polygon ROI")
        src = np.array(pts[:4], dtype=np.float32)
        # 依「左上、右上、右下、左下」排序（點可依任意順序畫）
        c = src.mean(axis=0)
        angles = np.arctan2(src[:, 1] - c[1], src[:, 0] - c[0])
        src = src[np.argsort(angles)]
        top = src[np.argsort(src[:, 1])][:2]
        tl = top[np.argmin(top[:, 0])]
        start = int(np.where((src == tl).all(axis=1))[0][0])
        src = np.roll(src, -start, axis=0)
        w_out = int(ctx.number("width", 0)) or int(round(max(np.linalg.norm(src[1] - src[0]), np.linalg.norm(src[2] - src[3]))))
        h_out = int(ctx.number("height", 0)) or int(round(max(np.linalg.norm(src[3] - src[0]), np.linalg.norm(src[2] - src[1]))))
        w_out, h_out = max(2, w_out), max(2, h_out)
        dst = np.array([[0, 0], [w_out - 1, 0], [w_out - 1, h_out - 1], [0, h_out - 1]], dtype=np.float32)
        matrix = cv2.getPerspectiveTransform(src, dst)
        out = cv2.warpPerspective(image, matrix, (w_out, h_out))
        return Result(outputs={"image": out}, overlays=[region_overlay(region, label="src")], message=f"{w_out}×{h_out}")


class UndistortTool(Tool):
    key = "undistort"
    accepts = ("u8", "u16", "f32")
    label = "Lens correction"
    description = (
        "Straightens what the lens bent, using a calibration. A wide-angle or short working distance makes straight edges "
        "bow outwards near the corners; measure on the corrected image and the numbers stop drifting across the field of view."
    )
    category = "preprocess"
    icon = "Aperture"
    params = [
        Param("mode", "Mode", kind="select", default="calibration", options=[
            {"value": "calibration", "label": "Calibration"},
            {"value": "manual", "label": "Manual"},
        ]),
        Param("calibration", "Calibration", kind="asset", accept="calibration", required=False, visible_when={"param": "mode", "in": ["calibration"]},
              help_text="Made on the Calibration page from a few pictures of a board. The same calibration also drives Real-world coordinates."),
        Param("alpha", "Frame kept", kind="range", default=0, minimum=0, maximum=1, step=0.05,
              help_text="0 = cut away every black border (zoom so all pixels are real image); 1 = keep the whole frame with black corners; in between keeps that share."),
        Param("keep_edges", "Keep the whole frame", kind="boolean", default=False, group="Advanced",
              help_text="Older flows: the same as alpha 1. Ignored when alpha is above 0."),
        Param("k1", "K1", kind="number", default=0, step=0.001, visible_when={"param": "mode", "in": ["manual"]}, teach=True),
        Param("k2", "K2", kind="number", default=0, step=0.001, visible_when={"param": "mode", "in": ["manual"]}, teach=True),
        Param("cx", "Centre X", kind="number", default=0, visible_when={"param": "mode", "in": ["manual"]}),
        Param("cy", "Centre Y", kind="number", default=0, visible_when={"param": "mode", "in": ["manual"]}),
        Param("scale", "Scale", kind="number", default=1, minimum=0.01, maximum=100, step=0.05, visible_when={"param": "mode", "in": ["manual"]}),
    ]
    inputs = [Port("image", "Image", "image")]
    outputs = [Port("image", "Image", "image"), Port("mm_per_pixel", "mm per pixel", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        if ctx.param("mode", "calibration") == "manual":
            image = ctx.require_image()
            alpha = ctx.number("alpha", 0)
            if alpha <= 0 and ctx.flag("keep_edges"):
                alpha = 1.0
            k1 = ctx.number("k1", 0)
            k2 = ctx.number("k2", 0)
            out = _manual_undistort(
                image,
                k1=k1,
                k2=k2,
                cx=ctx.param("cx", None),
                cy=ctx.param("cy", None),
                scale=ctx.number("scale", 1),
                alpha=alpha,
            )
            return Result(outputs={"image": out, "mm_per_pixel": float("nan")}, message=f"Manual k1={k1:g} k2={k2:g}")
        payload = read_calibration(ctx)
        image = ctx.require_image()
        alpha = ctx.number("alpha", 0)
        if alpha <= 0 and ctx.flag("keep_edges"):
            alpha = 1.0
        try:
            out = calib.undistort(image, payload, alpha=alpha)
        except calib.CalibError as exc:
            raise ToolError(str(exc)) from None
        lens = payload["lens"]
        world = payload.get("world") or {}
        mm_per_px = float(world.get("mm_per_px") or 0) or float("nan")
        return Result(outputs={"image": out, "mm_per_pixel": mm_per_px},
                      message=f"Corrected ({lens['views']} views, {lens['rms']:.2f} px, alpha {alpha:.2f})" + (f", {mm_per_px:.4f} {payload.get('unit', 'mm')}/px" if mm_per_px == mm_per_px else ""))


_MANUAL_UNDISTORT_MAPS: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}
_MANUAL_UNDISTORT_LOCK = threading.Lock()


def _manual_undistort(image: np.ndarray, *, k1: float, k2: float, cx: Any, cy: Any, scale: float, alpha: float) -> np.ndarray:
    h, w = image.shape[:2]
    k1 = float(k1)
    k2 = float(k2)
    if abs(k1) < 1e-12 and abs(k2) < 1e-12:
        return image.copy()
    try:
        centre_x = float(cx)
    except (TypeError, ValueError):
        centre_x = (w - 1) / 2.0
    try:
        centre_y = float(cy)
    except (TypeError, ValueError):
        centre_y = (h - 1) / 2.0
    focal = max(1e-6, float(scale)) * max(w, h)
    cam = np.array([[focal, 0.0, centre_x], [0.0, focal, centre_y], [0.0, 0.0, 1.0]], dtype=np.float64)
    dist = np.array([k1, k2, 0.0, 0.0, 0.0], dtype=np.float64)
    alpha = min(1.0, max(0.0, float(alpha)))
    key = (w, h, round(focal, 6), round(centre_x, 6), round(centre_y, 6), round(k1, 8), round(k2, 8), round(alpha, 3))
    with _MANUAL_UNDISTORT_LOCK:
        maps = _MANUAL_UNDISTORT_MAPS.get(key)
    if maps is None:
        new_cam, _ = cv2.getOptimalNewCameraMatrix(cam, dist, (w, h), alpha, (w, h))
        maps = cv2.initUndistortRectifyMap(cam, dist, None, new_cam, (w, h), cv2.CV_16SC2)
        with _MANUAL_UNDISTORT_LOCK:
            if len(_MANUAL_UNDISTORT_MAPS) > 8:
                _MANUAL_UNDISTORT_MAPS.pop(next(iter(_MANUAL_UNDISTORT_MAPS)))
            _MANUAL_UNDISTORT_MAPS[key] = maps
    return accel.remap(image, maps[0], maps[1], cv2.INTER_LINEAR, border_mode=cv2.BORDER_CONSTANT)


# ---------------------------------------------------------------------------
# 平場／陰影校正
# ---------------------------------------------------------------------------
SHADING_MODE_OPTIONS = [
    {"value": "flat_field", "label": "Flat field (white reference)"},
    {"value": "dark_flat", "label": "Dark and flat references"},
    {"value": "estimate", "label": "Estimate the background from the image"},
]

#: 增益圖快取：(flat 路徑, dark 路徑, 影像通道數, 目標亮度) → (flat 物件, dark 物件, gain f32, 零值比例)。
#: 參考影像由 read_asset_image 依 mtime／size 快取，這裡以物件身分比對即可跟著失效。
_GAIN_CACHE: "OrderedDict[tuple[Any, ...], tuple[Any, Any, np.ndarray, float]]" = OrderedDict()
_GAIN_LOCK = threading.Lock()


def shading_gain(flat: np.ndarray, dark: np.ndarray | None, target: float) -> tuple[np.ndarray, float]:
    """增益圖：gain = target / (flat − dark)，target 0＝(flat − dark) 的平均；參考值 < 1 的位置增益設 1，回報其比例。"""
    base = flat.astype(np.float32)
    if dark is not None:
        base = base - dark.astype(np.float32)
    bad = base < 1.0
    zero_ratio = float(bad.mean()) if base.size else 0.0
    level = float(target) if target > 0 else float(base[~bad].mean()) if (~bad).any() else 1.0
    gain = np.empty_like(base)
    np.divide(level, base, out=gain, where=~bad)
    gain[bad] = 1.0
    return gain, zero_ratio


def _mean_level(image: np.ndarray) -> float:
    """整張平均灰階（cv2.mean 一趟 SIMD，比 ndarray.mean 快 5 倍；彩色取三通道平均）。"""
    m = cv2.mean(image)
    return float(m[0]) if image.ndim == 2 else float((m[0] + m[1] + m[2]) / 3.0)


def _to_depth(out: np.ndarray, like: np.ndarray) -> np.ndarray:
    """float32 結果回到輸入位深（u8 用 convertScaleAbs 一趟四捨五入飽和；u16 夾到範圍；f32 原樣）。"""
    if like.dtype == np.uint8:
        return cv2.convertScaleAbs(out)
    if like.dtype == np.uint16:
        return np.clip(out, 0, 65535, out=out).astype(np.uint16)
    return out


class ShadingCorrectTool(Tool):
    key = "shading_correct"
    label = "Shading correction"
    description = (
        "Evens out uneven lighting. Divide by a picture of a plain white board taken under the same light (flat field), optionally "
        "after subtracting a dark frame, or estimate the background from the image itself with a large blur. Fixed thresholds then hold "
        "across the whole field of view instead of only in the middle."
    )
    category = "preprocess"
    icon = "SunDim"
    accepts = ("u8", "u16", "f32")
    params = [
        Param("mode", "Mode", kind="select", default="flat_field", options=SHADING_MODE_OPTIONS),
        Param("flat", "White reference", kind="asset", accept="image", visible_when={"param": "mode", "in": ["flat_field", "dark_flat"]},
              help_text="A picture of a uniform white board at the working resolution. Upload it as an image asset."),
        Param("dark", "Dark reference", kind="asset", accept="image", visible_when={"param": "mode", "in": ["dark_flat"]},
              help_text="A picture with the lens capped; removes the sensor's fixed offset."),
        Param("blur_sigma", "Background blur", kind="number", default=51, minimum=3, maximum=501, step=2, unit="px", visible_when={"param": "mode", "in": ["estimate"]},
              help_text="How wide the background estimate is. Larger than the features you want to keep."),
        Param("target_level", "Target level", kind="number", default=0, minimum=0, help_text="The grey level the white reference is mapped to (a plain board comes out at this value); 0 = the reference's own mean. When estimating, the mean level of the output; 0 = the image's own mean."),
    ]
    inputs = [Port("image", "Image", "image"), Port("flat_image", "White reference picture", "image", required=False), Port("dark_image", "Dark reference picture", "image", required=False)]
    outputs = [Port("image", "Image", "image"), Port("mean_before", "Mean before", "number"), Port("mean_after", "Mean after", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        mode = str(ctx.param("mode", "flat_field"))
        target = ctx.number("target_level", 0)
        before = _mean_level(image)
        if mode == "estimate":
            # 背景是平滑的：縮小 4 倍再模糊、放大回來（1280×960 σ=51 從 12 ms 降到 1 ms 級），結果與全解析度模糊只差取樣誤差
            sigma = max(3.0, ctx.number("blur_sigma", 51))
            h, w = image.shape[:2]
            ds = 4 if min(h, w) >= 256 else 1
            f = image.astype(np.float32)
            small = cv2.resize(f, (max(1, w // ds), max(1, h // ds)), interpolation=cv2.INTER_AREA) if ds > 1 else f
            k = max(3, int(sigma / ds)) | 1
            background = cv2.GaussianBlur(small, (k, k), sigma / ds / 3.0, borderType=cv2.BORDER_REPLICATE)
            if ds > 1:
                background = cv2.resize(background, (w, h), interpolation=cv2.INTER_LINEAR)
            level = target if target > 0 else before
            cv2.subtract(f, background, dst=f)
            f += np.float32(level)
            out = _to_depth(f, image)
            return Result(outputs={"image": out, "mean_before": before, "mean_after": _mean_level(out)}, message=f"estimate σ={sigma:g}")
        gray = image.ndim == 2
        flat = reference_image(ctx, "flat_image", "flat", gray=gray)
        dark = reference_image(ctx, "dark_image", "dark", gray=gray) if mode == "dark_flat" else None
        for name, ref in (("white", flat), ("dark", dark)):
            if ref is None:
                continue
            if ref.shape[:2] != image.shape[:2]:
                raise ToolError(f"The {name} reference is {ref.shape[1]}×{ref.shape[0]} but the image is {image.shape[1]}×{image.shape[0]}; retake the reference at the working resolution")
            if ref.ndim != image.ndim:
                raise ToolError(f"The {name} reference is {'grayscale' if ref.ndim == 2 else 'colour'} but the image is {'grayscale' if gray else 'colour'}")
        key = (ctx.param("flat"), ctx.param("dark") if dark is not None else None, image.ndim, float(target))
        with _GAIN_LOCK:
            hit = _GAIN_CACHE.get(key)
            if hit is not None and hit[0] is flat and hit[1] is dark:
                _GAIN_CACHE.move_to_end(key)
                gain, zero_ratio = hit[2], hit[3]
            else:
                hit = None
        if hit is None:
            gain, zero_ratio = shading_gain(flat, dark, target)
            with _GAIN_LOCK:
                _GAIN_CACHE[key] = (flat, dark, gain, zero_ratio)
                while len(_GAIN_CACHE) > 8:
                    _GAIN_CACHE.popitem(last=False)
        # 每幀一次乘法：cv2.multiply 直接吃 u8／u16 輸入產 float32（不先 astype 多跑一趟）
        if dark is not None:
            f = cv2.subtract(image, dark, dtype=cv2.CV_32F)
            cv2.multiply(f, gain, dst=f)
        else:
            f = cv2.multiply(image, gain, dtype=cv2.CV_32F)
        out = _to_depth(f, image)
        detail = {"zero_ratio": round(zero_ratio, 6), "gain_min": round(float(gain.min()), 4), "gain_max": round(float(gain.max()), 4)}
        return Result(outputs={"image": out, "mean_before": before, "mean_after": _mean_level(out)}, detail=detail,
                      message=f"{mode}: gain {detail['gain_min']:.2f}–{detail['gain_max']:.2f}" + (f", {zero_ratio:.1%} unusable reference pixels" if zero_ratio else ""))


TOOLS = [
    GrayscaleTool(), CropTool(), BlurTool(), ThresholdTool(), MorphologyTool(), ResizeTool(),
    ColorSegmentTool(), ColorClassifyTool(), ColorConvertTool(), ColorRangeTool(), ArithmeticTool(), MaskApplyTool(), PasteBackTool(), RotateFlipTool(),
    ConvertDepthTool(), LutTool(), FilterTool(), SurfaceFilterTool(), FftFilterTool(), SurfaceFilterTool(), WarpPerspectiveTool(), UndistortTool(), ShadingCorrectTool(),
]
