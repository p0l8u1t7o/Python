"""DL 異常檢測工具（dl_anomaly）：與 anomaly trainer 訓練的記憶庫比對，回異常分數圖、遮罩與區域。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from apps.vision.dl import anomaly
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.detect import ROI_SHAPES, analyze_blobs
from apps.vision.tools.roi import crop, region_overlay

DEVICE_OPTIONS = [{"value": "auto", "label": "Auto (GPU when available)"}, {"value": "cpu", "label": "CPU"}, {"value": "cuda", "label": "CUDA"}]


class DlAnomalyTool(Tool):
    key = "dl_anomaly"
    label = "DL anomaly detection"
    description = (
        "Scores how unlike the taught good parts each area of the picture is, using a model trained on good pictures alone. "
        "Anything above the threshold is an anomaly — scratches, dents, missing or extra material — without ever having shown it a defect. "
        "The score map is the thing to look at when setting the threshold."
    )
    category = "dl"
    icon = "ScanEye"
    heavy = True
    params = [
        Param("model", "Anomaly model", kind="asset", accept="model", required=True, help_text="Trained on the teaching page with the anomaly model kind."),
        Param("roi", "Region", kind="roi", shapes=ROI_SHAPES, teach=True, help_text="Leave blank for the whole image; the region is resized to the model's input size."),
        Param("threshold", "Threshold", kind="number", default=0, minimum=0, step=0.05, teach=True, help_text="Anomaly score above which a pixel is defective. 0 = the automatic threshold stored in the model."),
        Param("min_area", "Min defect area", kind="number", default=30, minimum=0, unit="px²", teach=True),
        Param("device", "Device", kind="select", default="auto", options=DEVICE_OPTIONS),
        Param("max_count", "Max results", kind="number", default=100, minimum=1, maximum=5000, group="Advanced"),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("ok", "Clean", "ok"), flow_out("defect", "Defective", "critical"),
        Port("score", "Max score", "number"), Port("count", "Count", "number"), Port("total_area", "Total area", "number"),
        Port("score_map", "Score map", "image"), Port("mask", "Mask", "image"), Port("regions", "Regions", "list"), Port("threshold_used", "Threshold used", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        asset_id = ctx.param("model")
        if not asset_id:
            raise ToolError("No anomaly model is set")
        path = ctx.asset_path(str(asset_id))
        if not path:
            raise ToolError(f"Asset {asset_id} not found")
        try:
            model = anomaly.load(path)
            sess = anomaly.backbone_session(model, path, str(ctx.param("device", "auto")))
        except anomaly.AnomalyError as exc:
            raise ToolError(str(exc)) from None
        image = ctx.require_image()
        region = ctx.roi()
        c = crop(image, region, upright=True)
        if c.image.size == 0 or min(c.image.shape[:2]) < 8:
            raise ToolError("The region falls outside the image or is too small")
        sub = np.ascontiguousarray(c.image)
        try:
            smap, max_score = anomaly.infer(model, sess, sub, sub.shape[:2])
        except anomaly.AnomalyError as exc:
            raise ToolError(str(exc)) from None
        threshold = ctx.number("threshold", 0) or float(model["meta"].get("threshold", 0) or 0)
        if threshold <= 0:
            raise ToolError("The model has no automatic threshold; set one on the tool")
        mask = cv2.compare(smap, float(threshold), cv2.CMP_GT)
        if c.mask is not None:
            cv2.bitwise_and(mask, c.mask, dst=mask)
        blobs, _ = analyze_blobs(mask, min_area=ctx.number("min_area", 30))
        order = sorted(range(len(blobs)), key=lambda i: -blobs[i]["area"])[: ctx.integer("max_count", 100)]
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        regions = []
        for i in order:
            d = dict(blobs[i])
            x0, y0, w, h = d["bbox"]
            peak = float(smap[max(0, y0) : y0 + h, max(0, x0) : x0 + w].max()) if w > 0 and h > 0 else 0.0
            fx, fy = c.to_full(d["cx"], d["cy"])
            d["cx"], d["cy"] = round(fx, 2), round(fy, 2)
            corner = c.to_full(x0, y0)
            d["bbox"] = [round(corner[0], 1), round(corner[1], 1), w, h]
            d["peak_score"] = round(peak, 4)
            regions.append(d)
            overlays.append({"kind": "rect", "x": corner[0], "y": corner[1], "w": w, "h": h, "angle": float(region.get("angle", 0)) if region and region.get("shape") == "rotated_rect" else 0.0,
                             "color": "#ef4444", "width": 2, "label": f"{peak:.2f} {d['area']:.0f}px"})
        # 熱圖：門檻映到 128（中灰），2× 門檻飽和；在 ROI 外為 0
        heat = cv2.convertScaleAbs(smap, alpha=128.0 / threshold)
        full_heat = np.zeros(image.shape[:2], dtype=np.uint8)
        full_mask = np.zeros(image.shape[:2], dtype=np.uint8)
        if c.inverse is None:
            full_heat[c.y0 : c.y0 + heat.shape[0], c.x0 : c.x0 + heat.shape[1]] = heat
            full_mask[c.y0 : c.y0 + mask.shape[0], c.x0 : c.x0 + mask.shape[1]] = mask
        else:
            # 旋轉矩形：把結果貼回原圖座標
            m = cv2.invertAffineTransform(c.inverse)
            full_heat = cv2.warpAffine(heat, c.inverse, (image.shape[1], image.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            full_mask = cv2.warpAffine(mask, c.inverse, (image.shape[1], image.shape[0]), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            del m
        count = len(regions)
        return Result(
            outputs={"score": round(max_score, 4), "count": count, "total_area": float(sum(r["area"] for r in regions)), "score_map": full_heat, "mask": full_mask,
                     "regions": regions, "threshold_used": round(float(threshold), 4)},
            overlays=overlays, branch="defect" if count else "ok", status="ng" if count else "ok",
            message=f"score {max_score:.2f} vs {threshold:.2f}, {count} regions",
            detail={"threshold": round(float(threshold), 4), "bank": int(len(model["bank"])), "input_size": int(model["meta"].get("input_size", 320))},
        )


TOOLS = [DlAnomalyTool()]
