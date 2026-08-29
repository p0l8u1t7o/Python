"""影像前處理工具。全部 OpenCV，盡量零拷貝。"""

from __future__ import annotations

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError
from apps.vision.tools.roi import crop, region_overlay


def to_gray(image: np.ndarray) -> np.ndarray:
    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


class GrayscaleTool(Tool):
    key = "grayscale"
    label = "灰階"
    description = "彩色轉灰階；已是灰階則直通。"
    icon = "Contrast"

    def execute(self, ctx: ToolContext) -> Result:
        return Result(outputs={"image": to_gray(ctx.require_image())})


class CropTool(Tool):
    key = "crop"
    label = "裁切 ROI"
    description = "裁出區域成為新影像（旋轉矩形會擺正）。下游工具在小圖上跑會快很多。"
    icon = "Crop"
    params = [Param("roi", "區域", kind="roi", required=True, shapes=["rect", "rotated_rect"])]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [Port("image", "影像", "image"), Port("offset_x", "偏移 X", "number"), Port("offset_y", "偏移 Y", "number")]

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
    label = "平滑 / 去雜訊"
    description = "高斯、中值、雙邊或均值濾波。"
    icon = "Droplets"
    params = [
        Param("method", "方法", kind="select", default="gaussian", options=[
            {"value": "gaussian", "label": "高斯"}, {"value": "median", "label": "中值"},
            {"value": "bilateral", "label": "雙邊（保邊）"}, {"value": "box", "label": "均值"},
        ]),
        Param("ksize", "核大小（奇數）", kind="number", default=5, minimum=1, maximum=99, step=2),
        Param("sigma", "Sigma（高斯／雙邊）", kind="number", default=0, minimum=0, maximum=200, group="進階"),
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
    label = "二值化"
    description = "固定門檻、Otsu 自動、或自適應（區域）二值化；輸出 0/255 遮罩。"
    icon = "SlidersHorizontal"
    params = [
        Param("method", "方法", kind="select", default="otsu", options=[
            {"value": "fixed", "label": "固定門檻"}, {"value": "otsu", "label": "Otsu 自動"},
            {"value": "adaptive_mean", "label": "自適應（均值）"}, {"value": "adaptive_gaussian", "label": "自適應（高斯）"},
            {"value": "range", "label": "灰階範圍"},
        ]),
        Param("threshold", "門檻", kind="number", default=128, minimum=0, maximum=255, visible_when={"param": "method", "in": ["fixed"]}, teach=True),
        Param("low", "下限", kind="number", default=0, minimum=0, maximum=255, visible_when={"param": "method", "in": ["range"]}, teach=True),
        Param("high", "上限", kind="number", default=128, minimum=0, maximum=255, visible_when={"param": "method", "in": ["range"]}, teach=True),
        Param("block", "區塊大小（奇數）", kind="number", default=31, minimum=3, maximum=255, step=2, visible_when={"param": "method", "in": ["adaptive_mean", "adaptive_gaussian"]}, teach=True),
        Param("c", "常數 C", kind="number", default=5, minimum=-100, maximum=100, visible_when={"param": "method", "in": ["adaptive_mean", "adaptive_gaussian"]}, teach=True),
        Param("invert", "反相（暗物件為前景）", kind="boolean", default=False),
    ]
    outputs = [Port("image", "遮罩", "image"), Port("threshold_used", "實際門檻", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        method = ctx.param("method", "otsu")
        inv = ctx.flag("invert")
        used = 0.0
        if method == "otsu":
            used, out = cv2.threshold(gray, 0, 255, (cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY) | cv2.THRESH_OTSU)
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
    label = "形態學"
    description = "侵蝕、膨脹、開、閉、梯度、頂帽、黑帽。"
    icon = "Shapes"
    params = [
        Param("op", "運算", kind="select", default="open", options=[
            {"value": "erode", "label": "侵蝕"}, {"value": "dilate", "label": "膨脹"}, {"value": "open", "label": "開運算"},
            {"value": "close", "label": "閉運算"}, {"value": "gradient", "label": "梯度"}, {"value": "tophat", "label": "頂帽"}, {"value": "blackhat", "label": "黑帽"},
        ]),
        Param("shape", "核形狀", kind="select", default="rect", options=[{"value": "rect", "label": "矩形"}, {"value": "ellipse", "label": "橢圓"}, {"value": "cross", "label": "十字"}]),
        Param("ksize", "核大小", kind="number", default=3, minimum=1, maximum=99),
        Param("iterations", "次數", kind="number", default=1, minimum=1, maximum=20),
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
    label = "縮放"
    description = "依比例或指定尺寸縮放；大圖先縮小再處理是最有效的加速。"
    icon = "Scaling"
    params = [
        Param("scale", "比例", kind="number", default=0.5, minimum=0.01, maximum=8, step=0.05),
        Param("width", "寬（0 = 用比例）", kind="number", default=0, minimum=0),
        Param("height", "高（0 = 用比例）", kind="number", default=0, minimum=0),
        Param("interpolation", "插值", kind="select", default="area", options=[
            {"value": "area", "label": "區域（縮小）"}, {"value": "linear", "label": "線性"}, {"value": "nearest", "label": "最近"}, {"value": "cubic", "label": "三次"},
        ]),
    ]
    outputs = [Port("image", "影像", "image"), Port("scale_x", "比例 X", "number"), Port("scale_y", "比例 Y", "number")]

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
    label = "色彩空間 / 通道"
    description = "轉 HSV/Lab 或抽出單一通道，作為色彩檢測的前處理。"
    icon = "Palette"
    params = [
        Param("mode", "輸出", kind="select", default="hsv_s", options=[
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
    label = "色彩範圍遮罩"
    description = "HSV 範圍內的像素為 255（支援 H 跨 0 的紅色）。"
    icon = "Pipette"
    params = [
        Param("h_low", "H 下限", kind="number", default=0, minimum=0, maximum=179, teach=True),
        Param("h_high", "H 上限", kind="number", default=179, minimum=0, maximum=179, teach=True),
        Param("s_low", "S 下限", kind="number", default=0, minimum=0, maximum=255, teach=True),
        Param("s_high", "S 上限", kind="number", default=255, minimum=0, maximum=255, teach=True),
        Param("v_low", "V 下限", kind="number", default=0, minimum=0, maximum=255, teach=True),
        Param("v_high", "V 上限", kind="number", default=255, minimum=0, maximum=255, teach=True),
    ]
    outputs = [Port("image", "遮罩", "image"), Port("ratio", "覆蓋比例", "number")]

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


class HistogramEqTool(Tool):
    key = "hist_eq"
    label = "對比增強"
    description = "直方圖等化或 CLAHE（區域對比）。"
    icon = "BarChart3"
    params = [
        Param("method", "方法", kind="select", default="clahe", options=[{"value": "clahe", "label": "CLAHE"}, {"value": "global", "label": "全域等化"}]),
        Param("clip", "CLAHE clip", kind="number", default=2.0, minimum=0.1, maximum=40, step=0.1),
        Param("tile", "CLAHE 格數", kind="number", default=8, minimum=1, maximum=64),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        if ctx.param("method", "clahe") == "global":
            return Result(outputs={"image": cv2.equalizeHist(gray)})
        t = ctx.integer("tile", 8)
        clahe = cv2.createCLAHE(clipLimit=ctx.number("clip", 2.0), tileGridSize=(t, t))
        return Result(outputs={"image": clahe.apply(gray)})


class ArithmeticTool(Tool):
    key = "arithmetic"
    label = "影像運算"
    description = "兩張影像相加／相減／差異／AND／OR，或單張的反相、亮度對比調整。"
    icon = "Calculator"
    params = [
        Param("op", "運算", kind="select", default="absdiff", options=[
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
    label = "套用遮罩"
    description = "只保留遮罩為 255 的像素（其餘設為指定灰階）。"
    icon = "Layers"
    params = [Param("fill", "遮罩外填值", kind="number", default=0, minimum=0, maximum=255)]
    inputs = [Port("image", "影像", "image"), Port("mask", "遮罩", "image")]

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


class EdgeTool(Tool):
    key = "edges"
    label = "邊緣（Canny / Sobel）"
    description = "邊緣影像；Canny 輸出二值邊緣，Sobel/Laplacian 輸出梯度強度。"
    category = "preprocess"
    icon = "Activity"
    params = [
        Param("method", "方法", kind="select", default="canny", options=[{"value": "canny", "label": "Canny"}, {"value": "sobel", "label": "Sobel"}, {"value": "laplacian", "label": "Laplacian"}]),
        Param("low", "Canny 低門檻", kind="number", default=50, minimum=0, maximum=1000, visible_when={"param": "method", "in": ["canny"]}),
        Param("high", "Canny 高門檻", kind="number", default=150, minimum=0, maximum=1000, visible_when={"param": "method", "in": ["canny"]}),
        Param("ksize", "核大小", kind="number", default=3, minimum=1, maximum=7, step=2),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        method = ctx.param("method", "canny")
        k = ctx.integer("ksize", 3)
        if k % 2 == 0:
            k += 1
        if method == "canny":
            out = cv2.Canny(gray, ctx.number("low", 50), ctx.number("high", 150), apertureSize=min(7, max(3, k)))
        elif method == "sobel":
            gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=k)
            gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=k)
            out = cv2.convertScaleAbs(cv2.magnitude(gx, gy))
        else:
            out = cv2.convertScaleAbs(cv2.Laplacian(gray, cv2.CV_32F, ksize=k))
        return Result(outputs={"image": out})


class RotateFlipTool(Tool):
    key = "rotate_flip"
    label = "旋轉 / 翻轉"
    description = "90 度倍數旋轉、任意角度旋轉、水平／垂直翻轉。"
    icon = "RotateCw"
    params = [
        Param("angle", "角度（順時針）", kind="number", default=0, minimum=-360, maximum=360),
        Param("flip", "翻轉", kind="select", default="none", options=[{"value": "none", "label": "不翻"}, {"value": "h", "label": "水平"}, {"value": "v", "label": "垂直"}, {"value": "hv", "label": "水平＋垂直"}]),
        Param("keep_size", "維持尺寸", kind="boolean", default=True),
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


TOOLS = [
    GrayscaleTool(), CropTool(), BlurTool(), ThresholdTool(), MorphologyTool(), ResizeTool(),
    ColorConvertTool(), ColorRangeTool(), HistogramEqTool(), ArithmeticTool(), MaskApplyTool(), EdgeTool(), RotateFlipTool(),
]
