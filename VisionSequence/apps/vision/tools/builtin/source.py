"""影像來源工具。"""

from __future__ import annotations

import time

import cv2
import numpy as np

from apps.vision.capture.hub import CaptureError, FrameMeta, hub
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
        Param("frames", "Frames", kind="number", default=1, minimum=1, maximum=32, step=1,
              help_text="1 keeps the old behaviour. A larger value grabs a fresh batch in one run; image is still the first frame and images is the list."),
        Param("frames_timeout_ms", "Frames timeout", kind="number", default=0, minimum=0, maximum=30000, step=1, unit="ms", group="Advanced",
              help_text="0 uses the source timeout. For capture sources this timeout is applied to each requested frame in the batch."),
        Param("exposure_us", "Exposure", kind="number", default=0, minimum=0, step=1, unit="us", teach=True, visible_when={"param": "mode", "in": ["auto", "source"]},
              help_text="Blank or 0 leaves the camera unchanged."),
        Param("gain_db", "Gain", kind="number", default=0, minimum=0, step=0.1, unit="dB", teach=True, visible_when={"param": "mode", "in": ["auto", "source"]},
              help_text="Blank or 0 leaves the camera unchanged."),
    ]
    inputs: list[Port] = []
    outputs = [Port("image", "Image", "image"), Port("images", "Images", "list"), Port("width", "Width", "number"), Port("height", "Height", "number"), Port("applied", "Applied camera settings", "any"),
               flow_out("timeout", "Timeout", "critical")]

    def execute(self, ctx: ToolContext) -> Result:
        mode = ctx.param("mode", "auto")
        image = None
        used = ""
        applied: dict[str, object] = {}
        warnings: list[str] = []
        batch: list[np.ndarray] = []
        if mode in ("auto", "input"):
            candidate = ctx.context.get("_input_image")
            if isinstance(candidate, np.ndarray):
                image = candidate
                used = "input"
                frames = max(1, ctx.integer("frames", 1))
                batch = [image.copy() for _ in range(frames)] if frames > 1 else [image]
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
            frames = max(1, ctx.integer("frames", 1))
            if frames > 1:
                from apps.vision.capture.grabber import capture_grabber_for_source

                grabber, reason = capture_grabber_for_source(source_id)
                timeout_s = (ctx.number("frames_timeout_ms", 0) / 1000.0) or None
                if grabber is None:
                    msg = f"Frame batch uses the same non-capture source image {frames} times" if reason == "not_capture" else f"Frame batch could not use capture mode for source {source_id}: {reason}"
                    ctx.log(msg, level="warning")
                    warnings.append(msg)
                    gt0 = time.perf_counter()
                    image = ctx.grab(str(source_id))
                    _add_grab_ms(ctx, (time.perf_counter() - gt0) * 1000.0)
                    batch = [image.copy() for _ in range(frames)] if isinstance(image, np.ndarray) else []
                else:
                    for _ in range(frames):
                        gt0 = time.perf_counter()
                        frame = grabber.grab_fresh(timeout=timeout_s)
                        _add_grab_ms(ctx, (time.perf_counter() - gt0) * 1000.0)
                        if frame is None:
                            image = None
                            break
                        batch.append(frame)
                        _record_capture_timing(ctx, grabber.last_meta)
                    image = batch[0] if batch else None
            else:
                gt0 = time.perf_counter()
                image = ctx.grab(str(source_id))
                _add_grab_ms(ctx, (time.perf_counter() - gt0) * 1000.0)
                _record_source_timing(ctx, source_id)
                batch = [image] if isinstance(image, np.ndarray) else []
            used = f"source:{source_id}"
            if image is None:
                from apps.vision.sources import last_error_of, last_timeout_of  # 來源自己知道的原因（例如擷取端未連線、資料夾讀完）

                reason = last_error_of(source_id)
                timed_out = bool(last_timeout_of(source_id))
                if frames > 1 and "grabber" in locals() and grabber is not None:
                    reason = str(getattr(grabber, "last_error", "") or reason)
                    timed_out = bool(getattr(grabber, "timed_out", False))
                if ctx.param("on_timeout", "error") == "ng" and timed_out:
                    msg = f"Image source {source_id} timed out" + (f": {reason}" if reason else "")
                    return Result(status="ng", branch="timeout", message=msg)
                raise ToolError(f"Image source {source_id} returned no image" + (f": {reason}" if reason else ""))
        if image is None:
            raise ToolError("No scratch image: upload one from the toolbar, or push an image through the API")
        convert = ctx.param("convert", "keep")
        if convert == "gray" and image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            batch = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame for frame in batch]
        elif convert == "bgr" and image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            batch = [cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR) if frame.ndim == 2 else frame for frame in batch]
        h, w = image.shape[:2]
        detail = {"warnings": warnings} if warnings else {}
        message = f"{w}×{h} from {used}" + ("; camera settings warning" if warnings else "")
        if len(batch) > 1:
            message += f", {len(batch)} frames"
        return Result(outputs={"image": image, "images": batch, "width": w, "height": h, "applied": applied}, message=message, detail=detail)


def _camera_params(ctx: ToolContext) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in ("exposure_us", "gain_db"):
        value = ctx.number(name, 0)
        if value:
            out[name] = value
    return out


def _add_grab_ms(ctx: ToolContext, ms: float) -> None:
    ctx.context["_timing_grab_ms"] = float(ctx.context.get("_timing_grab_ms") or 0.0) + max(0.0, float(ms))


def _record_source_timing(ctx: ToolContext, source_id: object) -> None:
    from apps.vision.capture.grabber import capture_grabber_for_source

    grabber, _reason = capture_grabber_for_source(source_id)
    if grabber is not None:
        _record_capture_timing(ctx, grabber.last_meta)


def _record_capture_timing(ctx: ToolContext, meta: FrameMeta | None, *, key: str = "image") -> None:
    if meta is None:
        return
    now_perf = time.perf_counter()
    now_wall = time.time()
    item = {
        "key": key,
        "seq": meta.seq,
        "frame_age_ms": max(0.0, (now_perf - meta.received_perf) * 1000.0),
        "captured_at": meta.captured_at,
        "received_at": meta.received_at,
    }
    if meta.captured_at is not None:
        item["since_capture_ms"] = max(0.0, (now_wall - meta.captured_at) * 1000.0)
    frames = ctx.context.setdefault("_timing_frames", [])
    if isinstance(frames, list):
        frames.append(item)


class StereoGrabTool(Tool):
    key = "stereo_grab"
    label = "Stereo grab"
    description = "Grabs a left and right image for a stereo pair, using simultaneous capture requests when both sources are capture-client cameras."
    category = "source"
    icon = "PanelTop"
    allows_unconnected = True
    params = [
        Param("left", "Left source", kind="source", required=True),
        Param("right", "Right source", kind="source", required=True),
        Param("timeout_ms", "Timeout", kind="number", default=1000, minimum=50, maximum=30000, step=1, unit="ms"),
        Param("max_dt_ms", "Max pair offset", kind="number", default=10, minimum=0, maximum=1000, step=0.1, unit="ms", teach=True),
        Param("on_timeout", "On timeout", kind="select", default="error", options=[
            {"value": "error", "label": "Raise an error"},
            {"value": "ng", "label": "Mark NG and use the timeout branch"},
        ]),
    ]
    inputs: list[Port] = []
    outputs = [
        Port("image", "Left image", "image"),
        Port("image_right", "Right image", "image"),
        Port("dt_ms", "Pair offset", "number"),
        Port("captured_at", "Captured at", "number", required=False),
        flow_out("timeout", "Timeout", "critical"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        left_id = ctx.param("left")
        right_id = ctx.param("right")
        if not left_id or not right_id:
            raise ToolError("Choose both stereo sources")
        timeout = max(0.05, ctx.number("timeout_ms", 1000) / 1000.0)
        from apps.vision.capture.grabber import capture_grabber_for_source

        left_g, left_reason = capture_grabber_for_source(left_id)
        right_g, right_reason = capture_grabber_for_source(right_id)
        warnings: list[str] = []
        started = time.perf_counter()
        supplied = ctx.context.get("_input_image")
        if left_g is None and right_g is None and isinstance(supplied, np.ndarray):
            left = supplied
            right = supplied.copy()
            _add_grab_ms(ctx, (time.perf_counter() - started) * 1000.0)
            return Result(
                outputs={"image": left, "image_right": right, "dt_ms": None, "captured_at": None},
                message=f"left {left.shape[1]}x{left.shape[0]}, right {right.shape[1]}x{right.shape[0]}",
            )
        if left_g is not None and right_g is not None and left_g.client == right_g.client:
            try:
                left_frame, right_frame, dt_ms = hub.request_pair(left_g.client, left_g.channel, right_g.channel, timeout=timeout)
            except CaptureError as exc:
                _add_grab_ms(ctx, (time.perf_counter() - started) * 1000.0)
                if ctx.param("on_timeout", "error") == "ng" and exc.code == "timeout":
                    return Result(status="ng", branch="timeout", message=f"Stereo grab timed out: {exc}")
                raise ToolError(str(exc)) from None
            left = left_g.accept_frame(left_frame)
            right = right_g.accept_frame(right_frame)
            _add_grab_ms(ctx, (time.perf_counter() - started) * 1000.0)
            _record_capture_timing(ctx, left_frame.meta, key="left")
            _record_capture_timing(ctx, right_frame.meta, key="right")
            captured_at = left_frame.meta.captured_at
        else:
            if left_g is not None or right_g is not None:
                warnings.append("Capture sources are on different clients; frames were requested independently")
            left = _grab_one(ctx, left_id, left_g, timeout, "left")
            right = _grab_one(ctx, right_id, right_g, timeout, "right")
            dt_ms = None
            captured_at = None
            if left is None or right is None:
                if ctx.param("on_timeout", "error") == "ng" and (_timed_out(left_id) or _timed_out(right_id) or (left_g and left_g.timed_out) or (right_g and right_g.timed_out)):
                    return Result(status="ng", branch="timeout", message="Stereo grab timed out")
                reason = left_reason if left is None else right_reason
                raise ToolError("Stereo source returned no image" + (f": {reason}" if reason else ""))
        max_dt = ctx.number("max_dt_ms", 10)
        if dt_ms is not None and max_dt > 0 and dt_ms > max_dt:
            msg = f"Stereo pair offset {dt_ms:.2f} ms is over {max_dt:.2f} ms"
            ctx.log(msg, level="warning")
            warnings.append(msg)
        h, w = left.shape[:2]
        rh, rw = right.shape[:2]
        return Result(
            outputs={"image": left, "image_right": right, "dt_ms": dt_ms, "captured_at": captured_at},
            message=f"left {w}x{h}, right {rw}x{rh}" + (f", dt {dt_ms:.2f} ms" if dt_ms is not None else ""),
            detail={"warnings": warnings} if warnings else {},
        )


def _grab_one(ctx: ToolContext, source_id: object, grabber, timeout: float, key: str) -> np.ndarray | None:
    gt0 = time.perf_counter()
    if grabber is not None:
        image = grabber.grab_fresh(timeout=timeout)
        _record_capture_timing(ctx, grabber.last_meta, key=key)
    else:
        image = ctx.grab(str(source_id))
        _record_source_timing(ctx, source_id)
    _add_grab_ms(ctx, (time.perf_counter() - gt0) * 1000.0)
    return image


def _timed_out(source_id: object) -> bool:
    from apps.vision.sources import last_timeout_of

    return bool(last_timeout_of(source_id))


TOOLS = [ImageSourceTool(), StereoGrabTool()]
