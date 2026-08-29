"""影像來源工具。"""

from __future__ import annotations

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError


class ImageSourceTool(Tool):
    key = "image_source"
    label = "影像來源"
    description = "從設定的影像來源抓一張影像；API 直接送圖時（POST run 附影像）優先使用送來的影像。"
    category = "source"
    icon = "Camera"
    allows_unconnected = True
    params = [
        Param("source_id", "影像來源", kind="source", required=False, help_text="留空則只接受 API 送來的影像。"),
        Param("mode", "取像模式", kind="select", default="auto", options=[
            {"value": "auto", "label": "暫存／API 送圖優先，否則從來源庫抓"},
            {"value": "source", "label": "一律從來源抓"},
            {"value": "input", "label": "只用暫存影像（試跑上傳或 API 送圖；沒有就報錯）"},
        ]),
        Param("convert", "色彩", kind="select", default="keep", options=[
            {"value": "keep", "label": "維持原樣"},
            {"value": "gray", "label": "轉灰階"},
            {"value": "bgr", "label": "轉彩色（BGR）"},
        ]),
    ]
    inputs: list[Port] = []
    outputs = [Port("image", "影像", "image"), Port("width", "寬", "number"), Port("height", "高", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        mode = ctx.param("mode", "auto")
        image = None
        used = ""
        if mode in ("auto", "input"):
            candidate = ctx.context.get("_input_image")
            if isinstance(candidate, np.ndarray):
                image = candidate
                used = "input"
        if image is None and mode in ("auto", "source"):
            source_id = ctx.param("source_id")
            if not source_id:
                raise ToolError("沒有設定影像來源，且沒有暫存／送入的影像")
            image = ctx.grab(str(source_id))
            used = f"source:{source_id}"
            if image is None:
                raise ToolError(f"影像來源 {source_id} 沒有回傳影像")
        if image is None:
            raise ToolError("沒有暫存影像：請先在頂列「上傳暫存影像」或由 API 送圖")
        convert = ctx.param("convert", "keep")
        if convert == "gray" and image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif convert == "bgr" and image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        h, w = image.shape[:2]
        return Result(outputs={"image": image, "width": w, "height": h}, message=f"{w}×{h} 來自 {used}")


TOOLS = [ImageSourceTool()]
