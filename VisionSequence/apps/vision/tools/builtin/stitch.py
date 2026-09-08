"""多相機影像拼接工具。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from apps.vision import calib, fixed_images
from apps.vision.tools import accel
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError

IMAGE_PORTS = ("image_1", "image_2", "image_3", "image_4")
BLENDS = ("mean", "min", "max", "uncover")


@dataclass(frozen=True)
class StitchInput:
    image: np.ndarray
    label: str


def _fixed_image_inputs(ctx: ToolContext) -> list[StitchInput]:
    raw = ctx.param("images") or []
    if not isinstance(raw, list):
        raise ToolError("Fixed pictures must be an image list")
    out: list[StitchInput] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        image = fixed_images.load(str(item["id"]))
        if image is None:
            raise ToolError(f"Fixed picture {index} is missing")
        out.append(StitchInput(image, str(item.get("name") or f"fixed {index}")))
    return out


def _inputs(ctx: ToolContext) -> list[StitchInput]:
    live = [StitchInput(image, key) for key in IMAGE_PORTS if (image := ctx.image(key)) is not None]
    return live or _fixed_image_inputs(ctx)


def _shape_text(image: np.ndarray) -> str:
    h, w = image.shape[:2]
    suffix = "" if image.ndim == 2 else f"x{image.shape[2]}"
    return f"{w}x{h}{suffix} {image.dtype}"


def _check_compatible(images: list[StitchInput]) -> None:
    first = images[0].image
    for index, item in enumerate(images[1:], start=2):
        image = item.image
        if image.dtype != first.dtype or image.ndim != first.ndim or (image.ndim == 3 and image.shape[2] != first.shape[2]):
            raise ToolError(f"Image {index} ({item.label}) is {_shape_text(image)}, but image 1 is {_shape_text(first)}")


def _trimmed(images: list[StitchInput], trim: int) -> list[StitchInput]:
    if trim <= 0:
        return images
    out: list[StitchInput] = []
    for index, item in enumerate(images, start=1):
        h, w = item.image.shape[:2]
        if trim * 2 >= w or trim * 2 >= h:
            raise ToolError(f"Image {index} ({item.label}) is too small for trim {trim}px")
        out.append(StitchInput(item.image[trim:h - trim, trim:w - trim], item.label))
    return out


def _empty_like(height: int, width: int, sample: np.ndarray) -> np.ndarray:
    shape = (height, width) if sample.ndim == 2 else (height, width, sample.shape[2])
    return np.zeros(shape, dtype=sample.dtype)


def _blend(canvas: np.ndarray, counts: np.ndarray, accum: np.ndarray | None, patch: np.ndarray, mask: np.ndarray, x: int, y: int, mode: str) -> None:
    h, w = patch.shape[:2]
    roi = canvas[y:y + h, x:x + w]
    count_roi = counts[y:y + h, x:x + w]
    if mode == "mean":
        assert accum is not None
        acc_roi = accum[y:y + h, x:x + w]
        mask_b = mask if patch.ndim == 2 else mask[..., None]
        acc_roi += np.where(mask_b, patch.astype(np.float32), 0.0)
        count_roi += mask.astype(np.uint16)
        return
    if mode == "uncover":
        if patch.ndim == 2:
            roi[mask] = patch[mask]
        else:
            roi[mask] = patch[mask]
        count_roi += mask.astype(np.uint16)
        return
    fresh = mask & (count_roi == 0)
    overlap = mask & (count_roi > 0)
    if patch.ndim == 2:
        roi[fresh] = patch[fresh]
        if mode == "min":
            roi[overlap] = np.minimum(roi[overlap], patch[overlap])
        else:
            roi[overlap] = np.maximum(roi[overlap], patch[overlap])
    else:
        roi[fresh] = patch[fresh]
        if mode == "min":
            roi[overlap] = np.minimum(roi[overlap], patch[overlap])
        else:
            roi[overlap] = np.maximum(roi[overlap], patch[overlap])
    count_roi += mask.astype(np.uint16)


def _finish_blend(canvas: np.ndarray, counts: np.ndarray, accum: np.ndarray | None, mode: str) -> np.ndarray:
    if mode != "mean":
        return canvas
    assert accum is not None
    denom = np.maximum(counts, 1).astype(np.float32)
    if canvas.ndim == 3:
        denom = denom[..., None]
    out = accum / denom
    if np.issubdtype(canvas.dtype, np.integer):
        info = np.iinfo(canvas.dtype)
        out = np.clip(np.rint(out), info.min, info.max).astype(canvas.dtype)
    else:
        out = out.astype(canvas.dtype)
    return np.ascontiguousarray(out)


def _grid_offsets(count: int, rows: int, cols: int, order: str, step_x: int, step_y: int) -> list[dict[str, int]]:
    offsets: list[dict[str, int]] = []
    for index in range(count):
        if order == "column_major":
            row = index % rows
            col = index // rows
        else:
            row = index // cols
            col = index % cols
        offsets.append({"index": index + 1, "x": int(col * step_x), "y": int(row * step_y)})
    return offsets


def stitch_grid(images: list[StitchInput], *, rows: int, cols: int, order: str, trim: int, blend: str, overlap_x: int, overlap_y: int) -> Result:
    if rows < 1 or cols < 1:
        raise ToolError("Rows and columns must be positive")
    if order not in ("row_major", "column_major"):
        raise ToolError("Order must be row_major or column_major")
    if len(images) != rows * cols:
        raise ToolError(f"Grid is {rows}x{cols}, so it needs {rows * cols} pictures; got {len(images)}")
    images = _trimmed(images, max(0, trim))
    _check_compatible(images)
    h0, w0 = images[0].image.shape[:2]
    for index, item in enumerate(images[1:], start=2):
        h, w = item.image.shape[:2]
        if (w, h) != (w0, h0):
            raise ToolError(f"Image {index} ({item.label}) is {w}x{h} after trim, but image 1 is {w0}x{h0}; grid stitching never resizes inputs")
    overlap_x = max(0, min(int(overlap_x), w0 - 1))
    overlap_y = max(0, min(int(overlap_y), h0 - 1))
    step_x, step_y = w0 - overlap_x, h0 - overlap_y
    out_w = cols * w0 - (cols - 1) * overlap_x
    out_h = rows * h0 - (rows - 1) * overlap_y
    canvas = _empty_like(out_h, out_w, images[0].image)
    counts = np.zeros((out_h, out_w), dtype=np.uint16)
    accum = np.zeros(canvas.shape, dtype=np.float32) if blend == "mean" else None
    offsets = _grid_offsets(len(images), rows, cols, order, step_x, step_y)
    mask = np.ones((h0, w0), dtype=bool)
    for item, off in zip(images, offsets, strict=True):
        _blend(canvas, counts, accum, item.image, mask, off["x"], off["y"], blend)
    out = _finish_blend(canvas, counts, accum, blend)
    return Result(
        outputs={"image": out, "count": len(images), "width": out_w, "height": out_h, "offsets": offsets, "origin": [0.0, 0.0], "scale": 1.0},
        message=f"grid {rows}x{cols}, {out_w}x{out_h}, {blend}",
    )


def _load_calibration(ctx: ToolContext, index: int) -> dict[str, Any] | None:
    asset = ctx.param(f"calibration_{index}", "")
    if not asset:
        return None
    try:
        return calib.from_asset(asset, ctx.asset_path)
    except calib.CalibError as exc:
        raise ToolError(f"Calibration {index}: {exc}") from None


def _matrix_from_calibrations(payloads: list[dict[str, Any] | None], index: int) -> np.ndarray:
    payload = payloads[index]
    if payload and payload.get("world"):
        return np.asarray(payload["world"]["matrix"], dtype=np.float64).reshape(3, 3)
    if index == 0:
        return np.eye(3, dtype=np.float64)
    base = payloads[0]
    mapping = (payload or {}).get("mapping") if payload else None
    if not mapping:
        raise ToolError(f"Image {index + 1} needs a calibration with world or mapping data")
    matrix = np.asarray(mapping["matrix"], dtype=np.float64).reshape(3, 3)
    if base and base.get("world"):
        matrix = np.asarray(base["world"]["matrix"], dtype=np.float64).reshape(3, 3) @ matrix
    return matrix


def _plane_scale(payloads: list[dict[str, Any] | None], matrices: list[np.ndarray], images: list[StitchInput], requested: float) -> float:
    if requested > 0:
        return float(requested)
    for payload in payloads:
        world = (payload or {}).get("world") if payload else None
        if world and float(world.get("mm_per_px") or 0) > 0:
            return float(world["mm_per_px"])
    values = [
        calib.scale_at(matrix, (item.image.shape[1] / 2, item.image.shape[0] / 2))
        for matrix, item in zip(matrices, images, strict=True)
    ]
    values = [v for v in values if math.isfinite(v) and v > 0]
    return min(values) if values else 1.0


def _bounds(images: list[StitchInput], matrices: list[np.ndarray]) -> tuple[float, float, float, float]:
    corners = []
    for item, matrix in zip(images, matrices, strict=True):
        h, w = item.image.shape[:2]
        corners.append(calib.apply(matrix, [[0, 0], [w, 0], [w, h], [0, h]]))
    pts = np.vstack(corners)
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def _warp_to_plane(image: np.ndarray, matrix: np.ndarray, *, origin: tuple[float, float], scale: float, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.indices((height, width), dtype=np.float32)
    world = np.column_stack([
        origin[0] + xx.reshape(-1).astype(np.float64) * scale,
        origin[1] + yy.reshape(-1).astype(np.float64) * scale,
    ])
    inv = np.linalg.inv(matrix)
    src = calib.apply(inv, world).reshape(height, width, 2).astype(np.float32)
    map_x = np.ascontiguousarray(src[..., 0])
    map_y = np.ascontiguousarray(src[..., 1])
    h, w = image.shape[:2]
    valid = (map_x >= 0) & (map_x <= w - 1) & (map_y >= 0) & (map_y <= h - 1)
    warped = accel.remap(image, map_x, map_y, cv2.INTER_LINEAR, border_mode=cv2.BORDER_CONSTANT)
    return warped, valid


def stitch_homography(images: list[StitchInput], ctx: ToolContext, *, blend: str, scale: float) -> Result:
    _check_compatible(images)
    payloads = [_load_calibration(ctx, i + 1) for i in range(len(images))]
    matrices = [_matrix_from_calibrations(payloads, i) for i in range(len(images))]
    if payloads[0] is None and any((p or {}).get("world") for p in payloads[1:]):
        raise ToolError("Image 1 needs a world calibration when other images use world calibrations")
    plane_scale = _plane_scale(payloads, matrices, images, scale)
    if not math.isfinite(plane_scale) or plane_scale <= 0:
        raise ToolError("Scale must be positive")
    min_x, min_y, max_x, max_y = _bounds(images, matrices)
    out_w = max(1, int(math.ceil((max_x - min_x) / plane_scale)))
    out_h = max(1, int(math.ceil((max_y - min_y) / plane_scale)))
    canvas = _empty_like(out_h, out_w, images[0].image)
    counts = np.zeros((out_h, out_w), dtype=np.uint16)
    accum = np.zeros(canvas.shape, dtype=np.float32) if blend == "mean" else None
    for item, matrix in zip(images, matrices, strict=True):
        warped, mask = _warp_to_plane(item.image, matrix, origin=(min_x, min_y), scale=plane_scale, width=out_w, height=out_h)
        _blend(canvas, counts, accum, warped, mask, 0, 0, blend)
    out = _finish_blend(canvas, counts, accum, blend)
    world_origin_px = [float(-min_x / plane_scale), float(-min_y / plane_scale)]
    return Result(
        outputs={"image": out, "count": len(images), "width": out_w, "height": out_h, "offsets": [], "origin": world_origin_px, "scale": plane_scale},
        detail={"covered_pixels": int(np.count_nonzero(counts)), "world_top_left": [min_x, min_y]},
        message=f"homography {len(images)} pictures, {out_w}x{out_h}, scale {plane_scale:g}",
    )


class StitchImagesTool(Tool):
    key = "stitch_images"
    label = "Image stitching"
    description = (
        "Combines 2 to 4 camera pictures. Use grid mode for fixed camera arrays with no perspective difference; "
        "use homography mode when each picture has a world calibration, or when images 2-4 have a camera mapping into image 1."
    )
    category = "preprocess"
    icon = "PanelsTopLeft"
    heavy = True
    accepts = ("u8", "u16", "f32")
    params = [
        Param("images", "Fixed pictures", kind="images", required=False,
              help_text="Fallback source: if no image_1 to image_4 ports are connected, these fixed pictures are stitched in list order. Live flows should connect image_1 to image_4."),
        Param("mode", "Mode", kind="select", default="grid", options=[{"value": "grid", "label": "Grid"}, {"value": "homography", "label": "Homography"}]),
        Param("rows", "Rows", kind="number", default=1, minimum=1, visible_when={"param": "mode", "in": ["grid"]}),
        Param("cols", "Columns", kind="number", default=2, minimum=1, visible_when={"param": "mode", "in": ["grid"]}),
        Param("order", "Order", kind="select", default="row_major", options=[
            {"value": "row_major", "label": "Row major"}, {"value": "column_major", "label": "Column major"},
        ], visible_when={"param": "mode", "in": ["grid"]}),
        Param("trim", "Trim edges", kind="number", default=0, minimum=0, unit="px", visible_when={"param": "mode", "in": ["grid"]}),
        Param("overlap_x", "Horizontal overlap", kind="number", default=0, minimum=0, unit="px", group="Advanced", visible_when={"param": "mode", "in": ["grid"]}),
        Param("overlap_y", "Vertical overlap", kind="number", default=0, minimum=0, unit="px", group="Advanced", visible_when={"param": "mode", "in": ["grid"]}),
        Param("blend", "Blend", kind="select", default="uncover", options=[
            {"value": "mean", "label": "Mean"}, {"value": "min", "label": "Minimum"},
            {"value": "max", "label": "Maximum"}, {"value": "uncover", "label": "Uncover"},
        ]),
        Param("calibration_1", "Calibration 1", kind="asset", accept="calibration", visible_when={"param": "mode", "in": ["homography"]}),
        Param("calibration_2", "Calibration 2", kind="asset", accept="calibration", visible_when={"param": "mode", "in": ["homography"]}),
        Param("calibration_3", "Calibration 3", kind="asset", accept="calibration", visible_when={"param": "mode", "in": ["homography"]}),
        Param("calibration_4", "Calibration 4", kind="asset", accept="calibration", visible_when={"param": "mode", "in": ["homography"]}),
        Param("scale", "Plane scale", kind="number", default=0, minimum=0, unit="unit/px", visible_when={"param": "mode", "in": ["homography"]},
              help_text="World units per output pixel. Leave 0 to use the first world calibration scale, or 1 px/px for camera mapping into image 1."),
    ]
    inputs = [
        Port("image_1", "Image 1", "image", required=False), Port("image_2", "Image 2", "image", required=False),
        Port("image_3", "Image 3", "image", required=False), Port("image_4", "Image 4", "image", required=False),
    ]
    outputs = [
        Port("image", "Image", "image"), Port("count", "Pictures", "number"), Port("width", "Width", "number"),
        Port("height", "Height", "number"), Port("offsets", "Grid offsets", "list"), Port("origin", "World origin", "any"),
        Port("scale", "Scale", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        images = _inputs(ctx)
        if len(images) < 2:
            raise ToolError("At least two pictures are needed; connect image_1 to image_4 or add fixed pictures")
        if len(images) > 4:
            raise ToolError("At most four pictures can be stitched")
        blend = str(ctx.param("blend", "uncover"))
        if blend not in BLENDS:
            raise ToolError("Blend must be mean, min, max or uncover")
        mode = str(ctx.param("mode", "grid"))
        if mode == "homography":
            return stitch_homography(images, ctx, blend=blend, scale=ctx.number("scale", 0))
        if mode != "grid":
            raise ToolError("Mode must be grid or homography")
        return stitch_grid(
            images, rows=max(1, ctx.integer("rows", 1)), cols=max(1, ctx.integer("cols", 2)),
            order=str(ctx.param("order", "row_major")), trim=max(0, ctx.integer("trim", 0)), blend=blend,
            overlap_x=ctx.integer("overlap_x", 0), overlap_y=ctx.integer("overlap_y", 0),
        )


TOOLS = [StitchImagesTool()]
