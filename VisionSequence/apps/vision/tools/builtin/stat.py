"""統計良品比對（defect_stat）：與 N 張良品建的逐像素 mean／std 模型比對，偏離幾倍標準差就是缺陷。

與 defect_diff（單張良品絕對差）的差別：每個像素有自己的正常範圍——紋理區 std 大、平坦區 std 小——
所以門檻以「幾倍 σ」而不是「幾個灰階」表達，打光波動與材質紋理不會逼使用者把門檻放鬆到抓不到真缺陷。
`min_sigma_floor` 是關鍵：均勻區 std 趨近 0，除下去會炸出滿畫面假缺陷，deviation = |img − mean| / max(std, floor)。

對齊：影像用相位相關對到模型的 mean（一次 warpAffine 把影像搬到模型座標系），缺陷座標再搬回來；
模型（npz 資產）由 apps/vision/stattpl.py 載入並在模組層快取。
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from apps.vision import stattpl
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.detect import ROI_SHAPES, _hanning, analyze_blobs
from apps.vision.tools.builtin.locate import to_gray
from apps.vision.tools.roi import crop, region_overlay

DIRECTION_OPTIONS = [
    {"value": "both", "label": "Darker or brighter"},
    {"value": "darker", "label": "Darker than normal only"},
    {"value": "brighter", "label": "Brighter than normal only"},
]


def read_model(ctx: ToolContext, key: str = "model") -> dict[str, Any]:
    try:
        return stattpl.from_asset(ctx.param(key), ctx.asset_path)
    except stattpl.StatTemplateError as exc:
        raise ToolError(str(exc)) from None


class DefectStatTool(Tool):
    key = "defect_stat"
    label = "Statistical defects"
    description = (
        "Compares the picture with a statistical template built from many good parts: every pixel has its own mean and spread, "
        "so textured areas are allowed to vary and flat areas are held tight. Anything that strays more than a few standard deviations "
        "from normal is a defect. Far steadier than a single golden image under changing light and part texture."
    )
    category = "detect"
    icon = "SquareStack"
    heavy = True
    params = [
        Param("model", "Statistical template", kind="asset", accept="file", required=True,
              help_text="Built from good images with POST /vision/assets/stat-template or manage.py stat_template (an .npz file asset)."),
        Param("roi", "Region", kind="roi", shapes=ROI_SHAPES, teach=True, help_text="Must be the same size as the region the template was built on; blank uses the whole image."),
        Param("align", "Aligned", kind="select", default="phase", options=[{"value": "none", "label": "No alignment"}, {"value": "phase", "label": "Phase correlation (translation)"}]),
        Param("sigma", "Sigma threshold", kind="number", default=3.0, minimum=0.5, maximum=50, step=0.5, teach=True,
              help_text="How many standard deviations from normal count as a defect. 3 is a good start; raise it if good parts are flagged."),
        Param("min_sigma_floor", "Minimum spread", kind="number", default=3.0, minimum=0, maximum=100, step=0.5, unit="grey",
              help_text="The standard deviation is never taken below this, so perfectly uniform areas do not flag single-level noise."),
        Param("min_area", "Min defect area", kind="number", default=20, minimum=0, unit="px²", teach=True),
        Param("direction", "Direction", kind="select", default="both", options=DIRECTION_OPTIONS, teach=True),
        Param("border", "Ignore border", kind="number", default=4, minimum=0, unit="px", help_text="Alignment leaves false differences at the border; ignore this many pixels."),
        Param("morph", "Opening kernel", kind="number", default=3, minimum=0, maximum=31, group="Advanced"),
        Param("max_count", "Max results", kind="number", default=100, minimum=1, maximum=5000, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("ok", "Clean", "ok"), flow_out("defect", "Defective", "critical"),
        Port("count", "Count", "number"), Port("total_area", "Total area", "number"), Port("max_sigma", "Max deviation", "number"),
        Port("defect_mask", "Defect mask", "image"), Port("deviation", "Deviation image", "image"), Port("regions", "Defects", "list"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        model = read_model(ctx)
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        sub = np.ascontiguousarray(c.image)
        mean = model["mean"]
        if sub.shape != mean.shape:
            raise ToolError(f"The region is {sub.shape[1]}×{sub.shape[0]} but the statistical template was built on {mean.shape[1]}×{mean.shape[0]}; draw the same region the template was built with")
        align = ctx.param("align", "phase")
        dx = dy = 0.0
        resp = 0.0
        work = sub
        if align == "phase" and min(sub.shape) >= 8:
            # phaseCorrelate 帶 window 時會就地改寫 DFT 最佳尺寸的輸入：模型的 mean 是快取共用的，一定要給複本
            (sx, sy), resp = cv2.phaseCorrelate(np.array(mean, copy=True), sub.astype(np.float32), _hanning(sub.shape[1], sub.shape[0]))
            dx, dy = float(sx), float(sy)
            if dx or dy:
                # 把影像搬到模型座標系（一次 warp），缺陷再搬回來
                m = np.array([[1, 0, -dx], [0, 1, -dy]], dtype=np.float32)
                work = cv2.warpAffine(sub, m, (sub.shape[1], sub.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        direction = str(ctx.param("direction", "both"))
        dev = stattpl.deviation_map(work, model, ctx.number("min_sigma_floor", 3.0), direction)
        valid = model["valid"]
        sigma = ctx.number("sigma", 3.0)
        mask = cv2.compare(dev, float(sigma), cv2.CMP_GT)
        cv2.bitwise_and(mask, valid, dst=mask)
        if c.mask is not None:
            cv2.bitwise_and(mask, c.mask, dst=mask)
        b = ctx.integer("border", 4)
        if b > 0 and mask.shape[0] > 2 * b and mask.shape[1] > 2 * b:
            mask[:b, :] = 0
            mask[-b:, :] = 0
            mask[:, :b] = 0
            mask[:, -b:] = 0
        k = ctx.integer("morph", 3)
        if k >= 2:
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        max_sigma = float(cv2.minMaxLoc(dev, mask=valid)[1]) if valid.any() else float(dev.max())
        blobs, contours = analyze_blobs(mask, min_area=ctx.number("min_area", 20))
        order = sorted(range(len(blobs)), key=lambda i: -blobs[i]["area"])[: ctx.integer("max_count", 100)]
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        defects = []
        for i in order:
            d = dict(blobs[i])
            # 模型座標 → 影像座標：加回對齊位移與裁切偏移
            d["cx"] = round(d["cx"] + dx + c.x0, 2)
            d["cy"] = round(d["cy"] + dy + c.y0, 2)
            d["bbox"] = [round(d["bbox"][0] + dx + c.x0, 1), round(d["bbox"][1] + dy + c.y0, 1), d["bbox"][2], d["bbox"][3]]
            x0, y0, w, h = d["bbox"]
            xi, yi = int(round(d["bbox"][0] - dx - c.x0)), int(round(d["bbox"][1] - dy - c.y0))
            d["peak_sigma"] = round(float(dev[max(0, yi) : yi + h, max(0, xi) : xi + w].max()) if h > 0 and w > 0 else 0.0, 2)
            defects.append(d)
            overlays.append({"kind": "rect", "x": x0, "y": y0, "w": w, "h": h, "color": "#ef4444", "width": 2, "label": f"{d['peak_sigma']:.1f}σ {d['area']:.0f}px"})
        full_mask = np.zeros(gray.shape, dtype=np.uint8)
        full_dev = np.zeros(gray.shape, dtype=np.uint8)
        if dx or dy:
            back = np.array([[1, 0, dx], [0, 1, dy]], dtype=np.float32)
            mask = cv2.warpAffine(mask, back, (mask.shape[1], mask.shape[0]), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            dev_img = cv2.warpAffine(dev, back, (dev.shape[1], dev.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        else:
            dev_img = dev
        full_mask[c.y0 : c.y0 + mask.shape[0], c.x0 : c.x0 + mask.shape[1]] = mask
        # 偏離影像：1σ＝32 灰階（8σ 飽和），給人看與給 threshold 接
        full_dev[c.y0 : c.y0 + dev_img.shape[0], c.x0 : c.x0 + dev_img.shape[1]] = cv2.convertScaleAbs(dev_img, alpha=32.0)
        count = len(defects)
        return Result(
            outputs={"count": count, "total_area": float(sum(d["area"] for d in defects)), "max_sigma": round(max_sigma, 2),
                     "defect_mask": full_mask, "deviation": full_dev, "regions": defects},
            overlays=overlays, branch="defect" if count else "ok", status="ng" if count else "ok",
            message=f"{count} defects, max {max_sigma:.1f}σ" + (f", aligned dx={dx:.1f} dy={dy:.1f}" if align == "phase" else ""),
            detail={"dx": round(dx, 2), "dy": round(dy, 2), "response": round(resp, 4), "samples": int(model.get("n", 0))},
        )


TOOLS = [DefectStatTool()]
