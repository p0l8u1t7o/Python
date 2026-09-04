"""影像來源工具。"""

from __future__ import annotations

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError


class ImageSourceTool(Tool):
    key = "image_source"
    label = "Image source"
    description = "Grabs one frame from the configured image source. An image attached to POST run takes priority over the source."
    category = "source"
    icon = "Camera"
    allows_unconnected = True
    params = [
        Param("source_id", "Image source", kind="source", required=False, help_text="Leave blank to accept only images sent through the API."),
        Param("mode", "Capture mode", kind="select", default="auto", options=[
            {"value": "auto", "label": "暫存／API 送圖優先，否則從來源庫抓"},
            {"value": "source", "label": "一律從來源抓"},
            {"value": "input", "label": "只用暫存影像（試跑上傳或 API 送圖；沒有就報錯）"},
        ]),
        Param("convert", "Colour", kind="select", default="keep", options=[
            {"value": "keep", "label": "維持原樣"},
            {"value": "gray", "label": "轉灰階"},
            {"value": "bgr", "label": "轉彩色（BGR）"},
        ]),
    ]
    inputs: list[Port] = []
    outputs = [Port("image", "Image", "image"), Port("width", "Width", "number"), Port("height", "Height", "number")]

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
                raise ToolError("No image source is set and no scratch or pushed image is available")
            image = ctx.grab(str(source_id))
            used = f"source:{source_id}"
            if image is None:
                from apps.vision.sources import last_error_of  # 來源自己知道的原因（例如擷取端未連線、資料夾讀完）

                reason = last_error_of(source_id)
                raise ToolError(f"Image source {source_id} returned no image" + (f"：{reason}" if reason else ""))
        if image is None:
            raise ToolError("No scratch image: upload one from the toolbar, or push an image through the API")
        convert = ctx.param("convert", "keep")
        if convert == "gray" and image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif convert == "bgr" and image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        h, w = image.shape[:2]
        return Result(outputs={"image": image, "width": w, "height": h}, message=f"{w}×{h} from {used}")


TOOLS = [ImageSourceTool()]
