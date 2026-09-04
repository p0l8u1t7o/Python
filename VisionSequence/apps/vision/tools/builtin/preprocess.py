"""影像前處理工具。盡量零拷貝。"""

from __future__ import annotations

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError
from apps.vision.tools.roi import crop, region_overlay


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
            raise ToolError("沒有設定區域")
        c = crop(image, region, upright=True)
        if c.image.size == 0:
            raise ToolError("區域落在影像外")
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
            {"value": "gaussian", "label": "高斯"}, {"value": "median", "label": "中值"},
            {"value": "bilateral", "label": "雙邊（保邊）"}, {"value": "box", "label": "均值"},
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
            out = cv2.medianBlur(image, k)
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
            {"value": "fixed", "label": "固定門檻"}, {"value": "otsu", "label": "Otsu 自動"},
            {"value": "triangle", "label": "Triangle 自動"},
            {"value": "adaptive_mean", "label": "自適應（均值）"}, {"value": "adaptive_gaussian", "label": "自適應（高斯）"},
            {"value": "range", "label": "灰階範圍"},
        ]),
        Param("threshold", "Threshold", kind="number", default=128, minimum=0, maximum=255, visible_when={"param": "method", "in": ["fixed"]}, teach=True),
        Param("low", "Lower", kind="number", default=0, minimum=0, maximum=255, visible_when={"param": "method", "in": ["range"]}, teach=True),
        Param("high", "Upper", kind="number", default=128, minimum=0, maximum=255, visible_when={"param": "method", "in": ["range"]}, teach=True),
        Param("block", "Block size (odd)", kind="number", default=31, minimum=3, maximum=255, step=2, visible_when={"param": "method", "in": ["adaptive_mean", "adaptive_gaussian"]}, teach=True),
        Param("c", "Constant C", kind="number", default=5, minimum=-100, maximum=100, visible_when={"param": "method", "in": ["adaptive_mean", "adaptive_gaussian"]}, teach=True),
        Param("invert", "Invert (dark objects are foreground)", kind="boolean", default=False),
    ]
    outputs = [Port("image", "Mask", "image"), Port("threshold_used", "Threshold used", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        method = ctx.param("method", "otsu")
        inv = ctx.flag("invert")
        used = 0.0
        if method == "otsu":
            used, out = cv2.threshold(gray, 0, 255, (cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY) | cv2.THRESH_OTSU)
        elif method == "triangle":
            used, out = cv2.threshold(gray, 0, 255, (cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY) | cv2.THRESH_TRIANGLE)
        elif method in ("adaptive_mean", "adaptive_gaussian"):
            b = max(3, ctx.integer("block", 31))
            if b % 2 == 0:
                b += 1
            out = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C if method == "adaptive_mean" else cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY, b, ctx.number("c", 5))
        elif method == "range":
            out = cv2.inRange(gray, int(ctx.number("low", 0)), int(ctx.number("high", 128)))
            if inv:
                out = cv2.bitwise_not(out)
        else:
            used = ctx.number("threshold", 128)
            _, out = cv2.threshold(gray, used, 255, cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY)
        return Result(outputs={"image": out, "threshold_used": float(used)}, message=f"{method} t={used:g}")


class MorphologyTool(Tool):
    key = "morphology"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Morphology"
    description = "Erode, dilate, open, close, gradient, top hat, black hat."
    icon = "Shapes"
    params = [
        Param("op", "Operation", kind="select", default="open", options=[
            {"value": "erode", "label": "侵蝕"}, {"value": "dilate", "label": "膨脹"}, {"value": "open", "label": "開運算"},
            {"value": "close", "label": "閉運算"}, {"value": "gradient", "label": "梯度"}, {"value": "tophat", "label": "頂帽"}, {"value": "blackhat", "label": "黑帽"},
        ]),
        Param("shape", "Kernel shape", kind="select", default="rect", options=[{"value": "rect", "label": "矩形"}, {"value": "ellipse", "label": "橢圓"}, {"value": "cross", "label": "十字"}]),
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
            {"value": "area", "label": "區域（縮小）"}, {"value": "linear", "label": "線性"}, {"value": "nearest", "label": "最近"}, {"value": "cubic", "label": "三次"},
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


class ColorConvertTool(Tool):
    key = "color_convert"
    label = "Colour space / channel"
    description = "Convert to HSV or Lab, or pull out a single channel, as preparation for a colour check."
    icon = "Palette"
    params = [
        Param("mode", "Output", kind="select", default="hsv_s", options=[
            {"value": "bgr_b", "label": "B 通道"}, {"value": "bgr_g", "label": "G 通道"}, {"value": "bgr_r", "label": "R 通道"},
            {"value": "hsv_h", "label": "HSV：H"}, {"value": "hsv_s", "label": "HSV：S"}, {"value": "hsv_v", "label": "HSV：V"},
            {"value": "lab_l", "label": "Lab：L"}, {"value": "lab_a", "label": "Lab：a"}, {"value": "lab_b", "label": "Lab：b"},
            {"value": "hsv", "label": "整張 HSV（3 通道）"},
        ]),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        mode = ctx.param("mode", "hsv_s")
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
        return Result(outputs={"image": mask, "ratio": ratio}, message=f"覆蓋 {ratio*100:.2f}%")


class ArithmeticTool(Tool):
    key = "arithmetic"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Image maths"
    description = "Add, subtract, difference, AND or OR two images, or invert and adjust brightness and contrast on one."
    icon = "Calculator"
    params = [
        Param("op", "Operation", kind="select", default="absdiff", options=[
            {"value": "absdiff", "label": "絕對差 |A-B|"}, {"value": "add", "label": "A+B"}, {"value": "subtract", "label": "A-B"},
            {"value": "and", "label": "A AND B"}, {"value": "or", "label": "A OR B"}, {"value": "xor", "label": "A XOR B"},
            {"value": "invert", "label": "反相 A"}, {"value": "gain", "label": "A×gain + bias"},
        ]),
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
            raise ToolError("此運算需要第二張影像 B")
        if a.shape != b.shape:
            if a.ndim != b.ndim:
                b = to_gray(b) if a.ndim == 2 else cv2.cvtColor(b, cv2.COLOR_GRAY2BGR)
            if a.shape[:2] != b.shape[:2]:
                b = cv2.resize(b, (a.shape[1], a.shape[0]))
        fn = {"absdiff": cv2.absdiff, "add": cv2.add, "subtract": cv2.subtract, "and": cv2.bitwise_and, "or": cv2.bitwise_or, "xor": cv2.bitwise_xor}[op]
        return Result(outputs={"image": fn(a, b)})


class MaskApplyTool(Tool):
    key = "apply_mask"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Apply mask"
    description = "Keep only the pixels where the mask is 255; the rest become the fill grey level."
    icon = "Layers"
    params = [Param("fill", "Fill outside mask", kind="number", default=0, minimum=0, maximum=255)]
    inputs = [Port("image", "Image", "image"), Port("mask", "Mask", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        mask = to_gray(ctx.require_image("mask"))
        if mask.shape[:2] != image.shape[:2]:
            mask = cv2.resize(mask, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST)
        fill = ctx.integer("fill", 0)
        # copyTo（新配置的目的地會先清零）比 bitwise_and(mask=) 快約 40%；要填值時直接以填值為底再覆蓋。
        if fill:
            out = np.full_like(image, fill)
            cv2.copyTo(image, mask, out)
        else:
            out = cv2.copyTo(image, mask)
        return Result(outputs={"image": out})


class RotateFlipTool(Tool):
    key = "rotate_flip"
    accepts = ("u8", "u16", "f32")  # cv2 原生支援多位深，原樣進出
    label = "Rotate / flip"
    description = "Rotate by a multiple of 90°, rotate by any angle, or flip horizontally or vertically."
    icon = "RotateCw"
    params = [
        Param("angle", "Angle (clockwise)", kind="number", default=0, minimum=-360, maximum=360),
        Param("flip", "Flip", kind="select", default="none", options=[{"value": "none", "label": "不翻"}, {"value": "h", "label": "水平"}, {"value": "v", "label": "垂直"}, {"value": "hv", "label": "水平＋垂直"}]),
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
            {"value": "u8", "label": "8 位元（U8）"}, {"value": "u16", "label": "16 位元（U16）"}, {"value": "f32", "label": "浮點（SGL）"},
        ]),
        Param("scale", "To 8-bit", kind="select", default="shift", options=[
            {"value": "shift", "label": "等比例（16-bit 右移 8）"}, {"value": "minmax", "label": "min-max 拉伸"}, {"value": "clip", "label": "直接裁切"},
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
            {"value": "linear", "label": "線性（亮度／對比）"}, {"value": "power", "label": "Gamma（次方）"},
            {"value": "log", "label": "對數（暗部展開）"}, {"value": "exp", "label": "指數（亮部展開）"},
            {"value": "sqrt", "label": "開根號"}, {"value": "square", "label": "平方"}, {"value": "invert", "label": "反相"},
            {"value": "equalize", "label": "直方圖等化"}, {"value": "clahe", "label": "CLAHE（區域對比）"},
        ]),
        Param("clip", "CLAHE clip", kind="number", default=2.0, minimum=0.1, maximum=40, step=0.1, visible_when={"param": "mode", "in": ["clahe"]}),
        Param("tile", "CLAHE tiles", kind="number", default=8, minimum=1, maximum=64, visible_when={"param": "mode", "in": ["clahe"]}),
        Param("brightness", "Brightness", kind="range", default=0, minimum=-100, maximum=100, step=1, visible_when={"param": "mode", "in": ["linear"]}, teach=True),
        Param("contrast", "Contrast", kind="range", default=1.0, minimum=0.1, maximum=3.0, step=0.05, visible_when={"param": "mode", "in": ["linear"]}, teach=True),
        Param("gamma", "Gamma", kind="range", default=1.0, minimum=0.1, maximum=5.0, step=0.05, visible_when={"param": "mode", "in": ["power"]}, teach=True),
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


class FilterTool(Tool):
    key = "filter"
    label = "Convolution filter"
    description = "Convolution and edge filters: sharpen, Canny edges, Laplacian, Sobel and Prewitt gradients, high pass, emboss, or a custom 3×3 kernel as JSON. Use the blur tool for smoothing."
    category = "preprocess"
    icon = "Grid3x3"
    params = [
        Param("method", "Method", kind="select", default="sharpen", options=[
            {"value": "sharpen", "label": "銳利化"}, {"value": "canny", "label": "Canny 邊緣（二值）"}, {"value": "laplacian", "label": "Laplacian"},
            {"value": "gradient", "label": "梯度強度（Sobel）"}, {"value": "sobel_x", "label": "Sobel X"}, {"value": "sobel_y", "label": "Sobel Y"},
            {"value": "prewitt", "label": "Prewitt 梯度"}, {"value": "highpass", "label": "高通"}, {"value": "emboss", "label": "浮雕"},
            {"value": "custom", "label": "自訂 3×3"},
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
            out = cv2.filter2D(image, -1, kernel)
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
            out = cv2.filter2D(to_gray(image), -1, kernel)
        else:
            raw = ctx.param("kernel")
            try:
                kernel = np.asarray(raw, dtype=np.float32)
                if kernel.shape != (3, 3):
                    raise ValueError
            except (TypeError, ValueError):
                raise ToolError("自訂 kernel 必須是 3×3 數字陣列") from None
            out = cv2.filter2D(image, -1, kernel)
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
            {"value": "lowpass", "label": "低通（保留大結構）"}, {"value": "highpass", "label": "高通（保留邊緣／細紋，以中灰 128 為零點）"},
        ]),
        Param("style", "Mode", kind="select", default="attenuate", options=[
            {"value": "truncate", "label": "截斷"}, {"value": "attenuate", "label": "高斯衰減"},
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
            raise ToolError("透視校正需要 4 個點的多邊形 ROI")
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


TOOLS = [
    GrayscaleTool(), CropTool(), BlurTool(), ThresholdTool(), MorphologyTool(), ResizeTool(),
    ColorConvertTool(), ColorRangeTool(), ArithmeticTool(), MaskApplyTool(), RotateFlipTool(),
    ConvertDepthTool(), LutTool(), FilterTool(), FftFilterTool(), WarpPerspectiveTool(),
]
