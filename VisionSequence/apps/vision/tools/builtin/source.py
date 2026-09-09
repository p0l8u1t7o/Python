"""影像來源工具。"""

from __future__ import annotations

import cv2
import numpy as np

from apps.vision.capture.hub import CaptureError
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out


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
            {"value": "auto", "label": "A scratch or pushed image first, otherwise grab from the source"},
            {"value": "source", "label": "Always grab from the source"},
            {"value": "input", "label": "Only a scratch image (uploaded for a preview or pushed through the API); an error if there is none"},
        ]),
        Param("convert", "Colour", kind="select", default="keep", options=[
            {"value": "keep", "label": "Leave as it is"},
            {"value": "gray", "label": "Convert to grayscale"},
            {"value": "bgr", "label": "Convert to colour (BGR)"},
        ]),
        Param("on_timeout", "On timeout", kind="select", default="error", options=[
            {"value": "error", "label": "Raise an error"},
            {"value": "ng", "label": "Mark NG and use the timeout branch"},
        ]),
        Param("exposure_us", "Exposure", kind="number", default=0, minimum=0, step=1, unit="us", teach=True, visible_when={"param": "mode", "in": ["auto", "source"]},
              help_text="Blank or 0 leaves the camera unchanged."),
        Param("gain_db", "Gain", kind="number", default=0, minimum=0, step=0.1, unit="dB", teach=True, visible_when={"param": "mode", "in": ["auto", "source"]},
              help_text="Blank or 0 leaves the camera unchanged."),
    ]
    inputs: list[Port] = []
    outputs = [Port("image", "Image", "image"), Port("width", "Width", "number"), Port("height", "Height", "number"), Port("applied", "Applied camera settings", "any"),
               flow_out("timeout", "Timeout", "critical")]

    def execute(self, ctx: ToolContext) -> Result:
        mode = ctx.param("mode", "auto")
        image = None
        used = ""
        applied: dict[str, object] = {}
        warnings: list[str] = []
        if mode in ("auto", "input"):
            candidate = ctx.context.get("_input_image")
            if isinstance(candidate, np.ndarray):
                image = candidate
                used = "input"
        if image is None and mode in ("auto", "source"):
            source_id = ctx.param("source_id")
            if not source_id:
                raise ToolError("No image source is set and no scratch or pushed image is available")
            wanted = _camera_params(ctx)
            if wanted:
                from apps.vision.capture.grabber import capture_grabber_for_source

                grabber, reason = capture_grabber_for_source(source_id)
                if grabber is None:
                    msg = f"Camera settings ignored for non-capture source {source_id}" if reason == "not_capture" else f"Camera settings ignored for source {source_id}: {reason}"
                    ctx.log(msg, level="warning")
                    warnings.append(msg)
                else:
                    try:
                        result = grabber.set_params_once(wanted)
                    except CaptureError as exc:
                        msg = f"Camera settings failed: {exc}"
                        ctx.log(msg, level="warning")
                        warnings.append(msg)
                    else:
                        applied.update(result.get("applied") or {})
                        errors = result.get("errors") or {}
                        if errors:
                            msg = "Camera settings warning: " + ", ".join(f"{k}: {v}" for k, v in errors.items())
                            ctx.log(msg, level="warning")
                            warnings.append(msg)
            image = ctx.grab(str(source_id))
            used = f"source:{source_id}"
            if image is None:
                from apps.vision.sources import last_error_of, last_timeout_of  # 來源自己知道的原因（例如擷取端未連線、資料夾讀完）

                reason = last_error_of(source_id)
                if ctx.param("on_timeout", "error") == "ng" and last_timeout_of(source_id):
                    msg = f"Image source {source_id} timed out" + (f": {reason}" if reason else "")
                    return Result(status="ng", branch="timeout", message=msg)
                raise ToolError(f"Image source {source_id} returned no image" + (f": {reason}" if reason else ""))
        if image is None:
            raise ToolError("No scratch image: upload one from the toolbar, or push an image through the API")
        convert = ctx.param("convert", "keep")
        if convert == "gray" and image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif convert == "bgr" and image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        h, w = image.shape[:2]
        detail = {"warnings": warnings} if warnings else {}
        message = f"{w}×{h} from {used}" + ("; camera settings warning" if warnings else "")
        return Result(outputs={"image": image, "width": w, "height": h, "applied": applied}, message=message, detail=detail)


def _camera_params(ctx: ToolContext) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in ("exposure_us", "gain_db"):
        value = ctx.number(name, 0)
        if value:
            out[name] = value
    return out


TOOLS = [ImageSourceTool()]
