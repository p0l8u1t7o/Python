"""多光源序列取像與影像融合工具。"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from apps.comm.writers import CommError, get_writer
from apps.vision.capture.hub import CaptureError
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.messages import Msg

MAX_STEPS = 8


@dataclass(frozen=True)
class LightStep:
    channel: int
    brightness: int
    exposure_us: float | None
    azimuth: float
    elevation: float


def _parse_steps(text: str, value_max: int = 255) -> list[LightStep]:
    steps: list[LightStep] = []
    for lineno, raw in enumerate(str(text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) > 5:
            raise ToolError(Msg.of("multi_light_grab.step_too_many_columns", "Step line {line} has too many columns", line=lineno))
        while len(parts) < 5:
            parts.append("")
        index = len(steps)
        try:
            channel = int(parts[0]) if parts[0] else index + 1
            brightness = int(round(float(parts[1]))) if parts[1] else value_max
            exposure = float(parts[2]) if parts[2] else None
            azimuth = float(parts[3]) if parts[3] else float(index * 90)
            elevation = float(parts[4]) if parts[4] else 30.0
        except ValueError:
            raise ToolError(Msg.of("multi_light_grab.step_bad_format", "Step line {line} must be channel,brightness[,exposure_us][,azimuth][,elevation]",
                                   line=lineno)) from None
        if channel < 1:
            raise ToolError(Msg.of("multi_light_grab.step_bad_channel", "Step line {line} has an invalid light channel", line=lineno))
        if brightness < 0 or brightness > value_max:
            raise ToolError(Msg.of("multi_light_grab.step_bad_brightness", "Step line {line} brightness is outside 0..{max}", line=lineno, max=value_max))
        if exposure is not None and exposure <= 0:
            exposure = None
        steps.append(LightStep(channel, brightness, exposure, azimuth, elevation))
        if len(steps) > MAX_STEPS:
            raise ToolError(Msg.of("multi_light_grab.too_many_steps", "At most {max} light steps are allowed", max=MAX_STEPS))
    if not steps:
        raise ToolError(Msg.of("multi_light_grab.no_steps", "Write at least one light step"))
    return steps


def _timeout_branch(ctx: ToolContext, source_id: Any, reason: str, timed_out: bool) -> Result | None:
    if ctx.param("on_timeout", "error") == "ng" and timed_out:
        if reason:
            msg = Msg.of("multi_light_grab.timed_out_reason", "Image source {source} timed out: {reason}", source=source_id, reason=reason)
        else:
            msg = Msg.of("multi_light_grab.timed_out", "Image source {source} timed out", source=source_id)
        return Result(status="ng", branch="timeout", message=msg)
    return None


def _no_image(source_id: Any, reason: Any) -> Msg:
    """來源沒有回影像（有原因就附上）。"""
    if reason:
        return Msg.of("multi_light_grab.no_image_reason", "Image source {source} returned no image: {reason}", source=source_id, reason=reason)
    return Msg.of("multi_light_grab.no_image", "Image source {source} returned no image", source=source_id)


def _send_light(writer: Any, channel: int, value: Any, mode: str, timeout: float | None) -> dict[str, Any]:
    send = getattr(writer, "set_light", None)
    if send is not None:
        return dict(send(channel, value, mode, timeout=timeout))
    raw = 0 if mode == "off" else value
    out = writer.write({str(channel): raw}, timeout=timeout)
    return {"channel": channel, "value": raw, "mode": mode, **dict(out)}


def _remember(writer: Any, channels: set[int]) -> dict[int, int]:
    state = getattr(writer, "channel_values", None)
    if isinstance(state, dict):
        return {ch: int(state.get(ch, 0) or 0) for ch in channels}
    raw = getattr(writer, "state", None)
    if isinstance(raw, dict):
        out: dict[int, int] = {}
        for ch in channels:
            value = raw.get(str(ch), raw.get(ch, 0))
            try:
                out[ch] = int(round(float(value)))
            except (TypeError, ValueError):
                out[ch] = 0
        return out
    return {ch: 0 for ch in channels}


def _deadline(ctx: ToolContext) -> float:
    try:
        return float(ctx.context.get("_deadline") or 0)
    except (TypeError, ValueError):
        return 0.0


def _check_deadline(ctx: ToolContext) -> None:
    end = _deadline(ctx)
    if end > 0 and time.perf_counter() > end:
        raise ToolError(Msg.of("multi_light_grab.run_timed_out", "the run timed out"))


def _sleep_ms(ctx: ToolContext, ms: float, warnings: list[str]) -> None:
    if ms <= 0:
        return
    capped = min(ms, 2000.0)
    if capped < ms:
        msg = "Light settle time was capped at 2000 ms for one step"
        ctx.log(msg, level="warning")
        warnings.append(msg)
    time.sleep(capped / 1000.0)
    _check_deadline(ctx)


class MultiLightGrabTool(Tool):
    key = "multi_light_grab"
    label = "Multi-light grab"
    description = "Grabs a short sequence from one source while changing a light channel for each frame, then returns the frames and light angles for fusion or photometric stereo."
    category = "source"
    icon = "Lightbulb"
    allows_unconnected = True
    connection_params = ("connection",)
    params = [
        Param("source", "Image source", kind="source", required=True),
        Param("connection", "Light connection", kind="text", required=True,
              help_text="The name of a light-controller connection under External integration > Device connections."),
        Param("steps", "Light steps", kind="multiline", required=True, default="1,255,,0,30\n2,255,,90,30\n3,255,,180,30",
              teach=True,
              help_text="One step per line: channel,brightness[,exposure_us][,azimuth][,elevation]. Blank optional cells use defaults; 1 to 8 steps are allowed."),
        Param("settle_ms", "Settle", kind="number", default=0, minimum=0, maximum=2000, step=1, unit="ms", teach=True,
              help_text="Delay after light command and before exposure. 0 uses the light connection lead time; each step is capped at 2000 ms."),
        Param("after", "After grab", kind="select", default="off", options=[
            {"value": "off", "label": "Turn touched channels off"},
            {"value": "keep", "label": "Keep the last step"},
            {"value": "restore", "label": "Restore remembered brightness"},
        ]),
        Param("on_timeout", "On timeout", kind="select", default="error", options=[
            {"value": "error", "label": "Raise an error"},
            {"value": "ng", "label": "Mark NG and use the timeout branch"},
        ]),
        Param("timeout_ms", "Timeout", kind="number", default=0, minimum=0, maximum=30000, step=1, unit="ms", group="Advanced"),
        Param("required", "Required light", kind="boolean", default=False,
              help_text="Fail the run when the light connection cannot be used. Off means grab without light commands and log a warning."),
    ]
    inputs = [Port("image", "Input image (optional)", "image", required=False)]
    outputs = [
        Port("images", "Images", "list"), Port("image", "Image 1", "image"), Port("image_1", "Image 2", "image", required=False),
        Port("image_2", "Image 3", "image", required=False), Port("image_3", "Image 4", "image", required=False),
        Port("azimuths", "Azimuths", "list"), Port("elevations", "Elevations", "list"),
        Port("count", "Count", "number"), Port("duration_ms", "Duration", "number"),
        flow_out("timeout", "Timeout", "critical"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        started = time.perf_counter()
        wired = ctx.image("image")
        if isinstance(wired, np.ndarray):
            steps = _parse_steps(str(ctx.param("steps", "") or "1,255,,0,30\n2,255,,90,30\n3,255,,180,30\n4,255,,270,30"))
            images = [np.ascontiguousarray(wired.copy()) for _ in steps]
            outputs: dict[str, Any] = {
                "images": images,
                "image": images[0],
                "azimuths": [s.azimuth for s in steps],
                "elevations": [s.elevation for s in steps],
                "count": len(images),
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
            for idx, key in enumerate(("image_1", "image_2", "image_3"), start=1):
                if len(images) > idx:
                    outputs[key] = images[idx]
            return Result(
                outputs=outputs,
                message=Msg.of("multi_light_grab.wired", "{n} frames from wired image {w}x{h}", n=len(images), w=wired.shape[1], h=wired.shape[0]),
                detail={"wired": True, "lit": False, "warnings": ["Wired image input was repeated for the light sequence"]},
            )
        source_id = ctx.param("source")
        if not source_id:
            raise ToolError(Msg.of("multi_light_grab.no_source", "Choose an image source"))
        writer = get_writer(str(ctx.param("connection", "")).strip())
        required = ctx.flag("required", False)
        lit = writer is not None
        warnings: list[str] = []
        if writer is None:
            msg = Msg.of("multi_light_grab.connection_missing", "Connection '{name}' is not open or does not exist", name=ctx.param('connection', ''))
            if required:
                raise ToolError(msg)
            ctx.log(f"Multi-light grab degraded: {msg}", level="warning")
            warnings.append(msg)
        value_max = int(getattr(writer, "value_max", 255) or 255) if writer is not None else 255
        steps = _parse_steps(str(ctx.param("steps", "") or ""), value_max)
        timeout_s = (ctx.number("timeout_ms", 0) / 1000.0) or None
        strobe = str(getattr(writer, "strobe", "steady") or "steady").lower() == "strobe" if writer is not None else False
        lead_ms = float(getattr(writer, "lead_time_ms", 0) or 0) if writer is not None else 0.0
        settle_ms = ctx.number("settle_ms", 0)
        if settle_ms <= 0:
            settle_ms = lead_ms
        from apps.vision.capture.grabber import capture_grabber_for_source

        grabber, reason = capture_grabber_for_source(source_id)
        images: list[np.ndarray] = []
        light_results: list[dict[str, Any]] = []
        remembered = _remember(writer, {s.channel for s in steps}) if writer is not None else {}
        input_image = ctx.context.get("_input_image")
        if grabber is None and reason == "missing" and isinstance(input_image, np.ndarray):
            msg = f"Image source {source_id} is unavailable; reusing the supplied image for all {len(steps)} light steps"
            ctx.log(msg, level="warning")
            warnings.append(msg)
            images = [input_image.copy() for _ in steps]
        elif grabber is None and reason == "not_capture":
            msg = f"Non-capture source {source_id} is reused for all {len(steps)} light steps"
            ctx.log(msg, level="warning")
            warnings.append(msg)
            image = ctx.grab(str(source_id))
            if image is None:
                from apps.vision import sources

                image = sources.grab_by_id(source_id)
            if image is None:
                from apps.vision.sources import last_error_of, last_timeout_of

                reason_text = last_error_of(source_id)
                timeout = bool(last_timeout_of(source_id))
                branch = _timeout_branch(ctx, source_id, reason_text, timeout)
                if branch is not None:
                    return branch
                raise ToolError(_no_image(source_id, reason_text))
            images = [image.copy() for _ in steps]
        else:
            if grabber is None:
                raise ToolError(Msg.of("multi_light_grab.camera_unavailable", "Capture camera {source} is not available: {reason}", source=source_id, reason=reason))
            try:
                for step in steps:
                    _check_deadline(ctx)
                    if writer is not None:
                        light_results.append(_send_light(writer, step.channel, step.brightness, "brightness", timeout_s))
                        if strobe:
                            light_results.append(_send_light(writer, step.channel, step.brightness, "on", timeout_s))
                    _sleep_ms(ctx, settle_ms, warnings)
                    if step.exposure_us is not None:
                        grabber.set_params_once({"exposure_us": step.exposure_us}, timeout=timeout_s)
                    frame = grabber.grab_fresh(timeout=timeout_s)
                    if frame is None:
                        branch = _timeout_branch(ctx, source_id, str(getattr(grabber, "last_error", "") or ""), bool(getattr(grabber, "timed_out", False)))
                        if branch is not None:
                            return branch
                        raise ToolError(_no_image(source_id, grabber.last_error))
                    images.append(frame)
                    if writer is not None and strobe:
                        light_results.append(_send_light(writer, step.channel, step.brightness, "off", timeout_s))
            except (CommError, CaptureError) as exc:
                raise ToolError(str(exc)) from None
            finally:
                if writer is not None:
                    self._after(ctx, writer, steps, remembered, timeout_s, warnings)
        if not images:
            raise ToolError(Msg.of("multi_light_grab.no_images", "No images were grabbed"))
        outputs: dict[str, Any] = {
            "images": images,
            "image": images[0],
            "azimuths": [s.azimuth for s in steps],
            "elevations": [s.elevation for s in steps],
            "count": len(images),
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
        for idx, key in enumerate(("image_1", "image_2", "image_3"), start=1):
            if len(images) > idx:
                outputs[key] = images[idx]
        detail = {"lit": lit, "strobe": strobe, "warnings": warnings, "light_results": light_results}
        return Result(outputs=outputs, message=Msg.of("multi_light_grab.grabbed", "{n} frames, lit={lit}", n=len(images), lit=str(lit).lower()), detail=detail)

    @staticmethod
    def _after(ctx: ToolContext, writer: Any, steps: list[LightStep], remembered: dict[int, int], timeout: float | None, warnings: list[str]) -> None:
        mode = str(ctx.param("after", "off") or "off").lower()
        channels = list(dict.fromkeys(step.channel for step in steps))
        if mode == "keep":
            return
        try:
            if mode == "restore":
                for ch in channels:
                    _send_light(writer, ch, remembered.get(ch, 0), "brightness", timeout)
            else:
                for ch in channels:
                    _send_light(writer, ch, 0, "off", timeout)
        except Exception as exc:  # noqa: BLE001 - 收尾失敗要讓使用者知道，但不遮掉已完成的取像
            msg = f"Light after-action failed: {exc}"
            ctx.log(msg, level="warning")
            warnings.append(msg)


def _collect_images(ctx: ToolContext) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    raw = ctx.inputs.get("images")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, np.ndarray):
                out.append(item)
            elif isinstance(item, (list, tuple)):
                out.extend(x for x in item if isinstance(x, np.ndarray))
    if out:
        # 與 photometric_stereo 同一條規則：接了 images 清單就以它為準，單張埠不再疊上去（否則同時接會重複計入）
        return out
    for key in ("image", "image_1", "image_2", "image_3"):
        image = ctx.image(key)
        if image is not None:
            out.append(image)
    if not out:
        raise ToolError(Msg.of("multi_light_fuse.no_images", "Wire images into images or image/image_1..3"))
    return out


def _check_shapes(images: list[np.ndarray]) -> None:
    h0, w0 = images[0].shape[:2]
    c0 = images[0].shape[2:] if images[0].ndim == 3 else ()
    for index, image in enumerate(images[1:], start=2):
        if image.shape[:2] != (h0, w0) or (image.shape[2:] if image.ndim == 3 else ()) != c0:
            h, w = image.shape[:2]
            raise ToolError(Msg.of("multi_light_fuse.size_mismatch", "Image {index} is {w}x{h} but image 1 is {w0}x{h0}; all pictures must be the same size",
                                   index=index, w=w, h=h, w0=w0, h0=h0))


def _u8(arr: np.ndarray) -> np.ndarray:
    if arr.dtype == np.uint8:
        return np.ascontiguousarray(arr)
    return np.clip(np.rint(arr), 0, 255).astype(np.uint8)


def _parse_angles(raw: Any) -> list[float]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = [x.strip() for x in raw.split(",") if x.strip()]
    try:
        return [float(x) for x in raw]
    except (TypeError, ValueError):
        raise ToolError(Msg.of("multi_light_fuse.bad_azimuths", "Azimuths must be a list of numbers")) from None


def _normalize_signed(arr: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(arr.reshape(-1)[::16] if arr.size > 65536 else arr.reshape(-1), (2, 98))
    span = max(abs(float(lo)), abs(float(hi)), 1e-6)
    return cv2.convertScaleAbs(arr, alpha=127.0 / span, beta=128.0)


class MultiLightFuseTool(Tool):
    key = "multi_light_fuse"
    label = "Multi-light fuse"
    description = "Fuses pictures from a multi-light sequence into one image for reflection removal, shadow contrast, directional texture or averaging."
    category = "preprocess"
    icon = "Layers"
    heavy = True
    params = [
        Param("mode", "Mode", kind="select", default="reflection", options=[
            {"value": "reflection", "label": "Reflection removal"},
            {"value": "shadow", "label": "Shadow relief"},
            {"value": "direction", "label": "Directional enhancement"},
            {"value": "mean", "label": "Mean"},
        ], help_text="Per pixel: reflection is the median across frames, or the minimum when there are only two; shadow is max-min; mean is the arithmetic mean; direction Sobel-filters each gray frame, weights gx/gy by the step azimuth, then projects the accumulated gradient to angle."),
        Param("azimuths", "Azimuths", kind="json", default=[0, 90, 180, 270],
              help_text="Light angles in degrees for direction mode. A connected azimuths port overrides this parameter."),
        Param("angle", "Direction", kind="number", default=0, unit="deg",
              help_text="Direction to emphasise in direction mode; 0 means the +x direction."),
        Param("halo_removal", "Halo removal", kind="boolean", default=False,
              help_text="For reflection mode, subtract a large blurred background from the median result and add back the median level."),
        Param("halo_size", "Halo size", kind="number", default=81, minimum=3, maximum=1001, step=2, unit="px", group="Advanced"),
        Param("normalize", "Normalise direction", kind="boolean", default=True, group="Advanced",
              help_text="For direction mode, image is always 8-bit; gradient stays float32 and is raw when this is off."),
    ]
    inputs = [
        Port("images", "Images", "image", required=False, multiple=True),
        Port("image", "Image 1", "image", required=False), Port("image_1", "Image 2", "image", required=False),
        Port("image_2", "Image 3", "image", required=False), Port("image_3", "Image 4", "image", required=False),
        Port("azimuths", "Azimuths", "list", required=False),
    ]
    outputs = [Port("image", "Image", "image"), Port("gradient", "Gradient", "image", required=False)]

    def execute(self, ctx: ToolContext) -> Result:
        images = _collect_images(ctx)
        _check_shapes(images)
        mode = str(ctx.param("mode", "reflection") or "reflection").lower()
        stack = np.stack([im.astype(np.float32) for im in images], axis=0)
        outputs: dict[str, Any] = {}
        if mode == "reflection":
            fused = stack.min(axis=0) if len(images) <= 2 else np.median(stack, axis=0)
            if ctx.flag("halo_removal", False):
                size = max(3, ctx.integer("halo_size", 81) | 1)
                bg = cv2.GaussianBlur(fused, (size, size), 0)
                fused = fused - bg + float(np.median(fused))
            image = _u8(fused)
        elif mode == "shadow":
            image = _u8(stack.max(axis=0) - stack.min(axis=0))
        elif mode == "mean":
            image = _u8(stack.mean(axis=0))
        elif mode == "direction":
            raw_angles = ctx.inputs.get("azimuths") if ctx.inputs.get("azimuths") is not None else ctx.param("azimuths", [0, 90, 180, 270])
            azimuths = _parse_angles(raw_angles)
            if len(azimuths) < len(images):
                raise ToolError(Msg.of("multi_light_fuse.too_few_azimuths", "{n} pictures but only {m} azimuths", n=len(images), m=len(azimuths)))
            acc_x = np.zeros(images[0].shape[:2], dtype=np.float32)
            acc_y = np.zeros_like(acc_x)
            for image0, az in zip(images, azimuths, strict=False):
                gray = image0 if image0.ndim == 2 else cv2.cvtColor(image0, cv2.COLOR_BGR2GRAY)
                gray = gray.astype(np.float32)
                gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3, scale=1.0 / 8.0)
                gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3, scale=1.0 / 8.0)
                rad = math.radians(float(az))
                acc_x += gx * math.cos(rad)
                acc_y += gy * math.sin(rad)
            target = math.radians(ctx.number("angle", 0))
            gradient = (acc_x * math.cos(target) + acc_y * math.sin(target)).astype(np.float32)
            outputs["gradient"] = np.ascontiguousarray(gradient)
            image = _normalize_signed(gradient) if ctx.flag("normalize", True) else _u8(gradient)
        else:
            raise ToolError(Msg.of("multi_light_fuse.bad_mode", "Mode must be reflection, shadow, direction or mean"))
        outputs["image"] = image
        return Result(outputs=outputs, message=Msg.of("multi_light_fuse.fused", "{mode}, {n} frames", mode=mode, n=len(images)))


TOOLS = [MultiLightGrabTool(), MultiLightFuseTool()]
