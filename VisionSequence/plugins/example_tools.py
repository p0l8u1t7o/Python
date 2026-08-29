"""外掛工具範例：.env 設 VISION_TOOL_PLUGINS=plugins.example_tools 即載入。"""

from __future__ import annotations

import cv2

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out, register
from apps.vision.tools.roi import crop, region_overlay


class DarkRatioTool(Tool):
    key = "dark_ratio"
    label = "暗區比例（範例外掛）"
    description = "ROI 內灰階低於門檻的像素比例，超過允許比例走不良分支。"
    category = "detect"
    icon = "Moon"
    params = [
        Param("roi", "區域", kind="roi", shapes=["rect", "rotated_rect", "circle", "polygon"]),
        Param("threshold", "門檻", kind="number", default=80, minimum=0, maximum=255),
        Param("max_ratio", "允許比例", kind="number", default=0.1, minimum=0, maximum=1, step=0.01),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [Port("ratio", "比例", "number"), flow_out("pass", "通過", "ok"), flow_out("fail", "不良", "critical")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        region = ctx.roi()
        c = crop(image, region, upright=True)
        if c.image.size == 0:
            raise ToolError("ROI 在影像外")
        pixels = c.image[c.mask > 0] if c.mask is not None else c.image
        ratio = float((pixels < ctx.number("threshold", 80)).mean()) if pixels.size else 0.0
        ok = ratio <= ctx.number("max_ratio", 0.1)
        overlays = [region_overlay(region, label=f"dark {ratio * 100:.1f}%")] if region else []
        return Result(outputs={"ratio": ratio}, branch="pass" if ok else "fail", status="ok" if ok else "ng", overlays=overlays, message=f"暗區 {ratio * 100:.1f}%")


register(DarkRatioTool())
