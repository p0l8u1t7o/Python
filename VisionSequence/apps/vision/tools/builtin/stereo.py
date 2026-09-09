"""雙視野高度量測工具：左相機分割、右相機只供視差。"""

from __future__ import annotations

import math
import threading
from typing import Any, Callable

import cv2
import numpy as np

from apps.vision import calib
from apps.vision.tools import accel
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.preprocess import read_calibration, to_gray

PREPROCESS_OPTIONS = [
    {"value": "none", "label": "None"},
    {"value": "clahe", "label": "CLAHE"},
    {"value": "sobel", "label": "Sobel"},
    {"value": "laplacian", "label": "Laplacian"},
]
STAT_OPTIONS = [{"value": "mean", "label": "Mean"}, {"value": "median", "label": "Median"}]

_MATCHERS: dict[tuple[int, int, int, bool], tuple[Any, Any, Any]] = {}
_MATCHERS_LOCK = threading.Lock()
_WLS_WARNED = False


def _preprocess(image: np.ndarray, mode: str) -> np.ndarray:
    gray = to_gray(image)
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    mode = mode.lower()
    if mode == "clahe":
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    if mode == "sobel":
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        return cv2.normalize(cv2.magnitude(gx, gy), None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    if mode == "laplacian":
        lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
        return cv2.normalize(np.abs(lap), None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    return gray


def _matcher(min_disp: int, num_disp: int, block: int, use_wls: bool) -> tuple[Any, Any, Any]:
    block = max(3, int(block) | 1)
    num_disp = max(16, int(math.ceil(num_disp / 16)) * 16)
    key = (int(min_disp), num_disp, block, bool(use_wls and hasattr(cv2, "ximgproc")))
    with _MATCHERS_LOCK:
        hit = _MATCHERS.get(key)
    if hit is not None:
        return hit
    p1 = 8 * 3 * block * block
    p2 = 32 * 3 * block * block
    left = cv2.StereoSGBM_create(
        minDisparity=int(min_disp),
        numDisparities=num_disp,
        blockSize=block,
        P1=p1,
        P2=p2,
        disp12MaxDiff=1,
        uniquenessRatio=15,
        speckleWindowSize=200,
        speckleRange=2,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
    )
    right = wls = None
    if key[3]:
        right = cv2.ximgproc.createRightMatcher(left)
        wls = cv2.ximgproc.createDisparityWLSFilter(left)
        wls.setLambda(8000)
        wls.setSigmaColor(1.5)
    item = (left, right, wls)
    with _MATCHERS_LOCK:
        if len(_MATCHERS) > 16:
            _MATCHERS.pop(next(iter(_MATCHERS)))
        _MATCHERS[key] = item
    return item


def _bbox(match: dict[str, Any]) -> tuple[int, int, int, int]:
    if isinstance(match.get("bbox"), list) and len(match["bbox"]) >= 4:
        x, y, w, h = (float(v) for v in match["bbox"][:4])
    else:
        x = float(match.get("x", float(match.get("cx", 0)) - float(match.get("w", 0)) / 2))
        y = float(match.get("y", float(match.get("cy", 0)) - float(match.get("h", 0)) / 2))
        w = float(match.get("w", 0))
        h = float(match.get("h", 0))
        if (w <= 0 or h <= 0) and isinstance(match.get("polygon"), list):
            pts = np.asarray(match["polygon"], dtype=np.float32).reshape(-1, 2)
            x, y, w, h = cv2.boundingRect(pts)
    return int(math.floor(x)), int(math.floor(y)), int(math.ceil(w)), int(math.ceil(h))


def _mask(match: dict[str, Any], x0: int, y0: int, w: int, h: int) -> np.ndarray:
    mask = np.zeros((h, w), dtype=np.uint8)
    poly = match.get("polygon")
    if isinstance(poly, list) and len(poly) >= 3:
        pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
        pts[:, 0] -= x0
        pts[:, 1] -= y0
        cv2.fillPoly(mask, [np.round(pts).astype(np.int32)], 255)
    else:
        x, y, bw, bh = _bbox(match)
        x1, y1 = max(0, x - x0), max(0, y - y0)
        x2, y2 = min(w, x + bw - x0), min(h, y + bh - y0)
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 255
    return mask


def _velocity(match: dict[str, Any]) -> tuple[float, float] | None:
    try:
        vx, vy = float(match.get("vx")), float(match.get("vy"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(vx) or not math.isfinite(vy) or (abs(vx) < 1e-12 and abs(vy) < 1e-12):
        return None
    return vx, vy


def measure_matches(
    left_image: np.ndarray,
    right_image: np.ndarray,
    matches: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    min_disparity: int,
    num_disparities: int,
    block_size: int,
    scale: float,
    preprocess: str,
    stat: str,
    min_valid_ratio: float,
    use_wls: bool,
    dt_ms: float | None,
    motion_compensation: bool,
    z_from_ref: bool = True,
    log_warning: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """對每個 match 的分割面估視差；回傳複製後的 match，不改上游資料。"""
    global _WLS_WARNED
    if left_image.shape[:2] != right_image.shape[:2]:
        raise ToolError("Left and right images must be the same size")
    h, w = left_image.shape[:2]
    rect = calib.stereo_rectify(payload, (w, h))
    if rect.get("rectified"):
        left_rect, right_rect = left_image, right_image
    else:
        map_l, map_r = rect["left"], rect["right"]
        left_rect = accel.remap(left_image, map_l[0], map_l[1], cv2.INTER_LINEAR, border_mode=cv2.BORDER_CONSTANT)
        right_rect = accel.remap(right_image, map_r[0], map_r[1], cv2.INTER_LINEAR, border_mode=cv2.BORDER_CONSTANT)
    left_gray = _preprocess(left_rect, preprocess)
    right_gray = _preprocess(right_rect, preprocess)
    requested_wls = bool(use_wls)
    if requested_wls and not hasattr(cv2, "ximgproc") and not _WLS_WARNED:
        _WLS_WARNED = True
        if log_warning:
            log_warning("Filtered disparity is unavailable in this installation; using standard stereo matching")
    use_wls = requested_wls and hasattr(cv2, "ximgproc")
    min_disparity = int(min_disparity)
    num_disparities = max(16, int(math.ceil(num_disparities / 16)) * 16)
    block_size = max(3, int(block_size) | 1)
    scale = min(1.0, max(0.05, float(scale or 1.0)))
    work_min_disparity = int(round(min_disparity * scale))
    work_num_disparities = max(16, int(math.ceil(num_disparities * scale / 16)) * 16)
    matcher, right_matcher, wls_filter = _matcher(work_min_disparity, work_num_disparities, block_size, use_wls)
    min_valid_ratio = min(1.0, max(0.0, float(min_valid_ratio)))
    max_disp = min_disparity + num_disparities
    required_width = max(8, max(0, work_min_disparity) + work_num_disparities + block_size + 2)
    z_ref = (payload.get("stereo") or {}).get("z_ref") if z_from_ref else None
    out: list[dict[str, Any]] = []
    for match in matches:
        item = dict(match)
        x, y, bw, bh = _bbox(item)
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        bw = max(1, min(w - x, bw))
        bh = max(1, min(h - y, bh))
        vel = _velocity(item)
        compensated = False
        dx = dy = 0.0
        if motion_compensation and vel is not None and dt_ms is not None:
            # dt 有號（右 − 左）：右相機晚拍 dt 時，物體在右影像裡比左影像多走了 v·dt，所以把右 ROI 內容往 −v·dt 移回去
            dx, dy = -vel[0] * float(dt_ms), -vel[1] * float(dt_ms)
            compensated = abs(dx) > 1e-6 or abs(dy) > 1e-6
        extra = int(math.ceil(max(abs(dx), abs(dy)))) + 2
        x0 = max(0, x - max_disp - extra)
        y0 = max(0, y - extra)
        x1 = min(w, x + bw + extra)
        y1 = min(h, y + bh + extra)
        if x1 - x0 <= max(8, block_size) or y1 - y0 <= max(8, block_size):
            item.update({"z": None, "distance_mm": None, "disparity": None, "valid_ratio": 0.0, "compensated": compensated})
            out.append(item)
            continue
        l_roi = left_gray[y0:y1, x0:x1]
        r_roi = right_gray[y0:y1, x0:x1]
        if compensated:
            m = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]], dtype=np.float32)
            r_roi = cv2.warpAffine(r_roi, m, (r_roi.shape[1], r_roi.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        obj_mask = _mask(item, x0, y0, x1 - x0, y1 - y0)
        if scale != 1.0:
            size = (max(1, int(round(l_roi.shape[1] * scale))), max(1, int(round(l_roi.shape[0] * scale))))
            l_work = cv2.resize(l_roi, size, interpolation=cv2.INTER_LINEAR)
            r_work = cv2.resize(r_roi, size, interpolation=cv2.INTER_LINEAR)
            mask_work = cv2.resize(obj_mask, size, interpolation=cv2.INTER_NEAREST) > 0
        else:
            l_work, r_work, mask_work = l_roi, r_roi, obj_mask > 0
        if l_work.shape[1] <= required_width or l_work.shape[0] <= block_size or int(mask_work.sum()) == 0:
            item.update({"z": None, "distance_mm": None, "disparity": None, "valid_ratio": 0.0, "compensated": compensated})
            out.append(item)
            continue
        try:
            disp = matcher.compute(l_work, r_work)
            if use_wls and right_matcher is not None and wls_filter is not None:
                disp_r = right_matcher.compute(r_work, l_work)
                disp = wls_filter.filter(disp, l_work, None, disp_r)
        except cv2.error:
            item.update({"z": None, "distance_mm": None, "disparity": None, "valid_ratio": 0.0, "compensated": compensated})
            out.append(item)
            continue
        values = disp.astype(np.float32) / 16.0 / scale
        valid = mask_work & (values > float(min_disparity) + 0.1) & (values < float(max_disp) - 0.1)
        denom = int(mask_work.sum())
        valid_ratio = float(valid.sum() / denom) if denom else 0.0
        if denom == 0 or valid_ratio < min_valid_ratio or not valid.any():
            item.update({"z": None, "distance_mm": None, "disparity": None, "valid_ratio": round(valid_ratio, 4), "compensated": compensated})
            out.append(item)
            continue
        pixels = values[valid]
        disparity = float(np.median(pixels) if stat == "median" else np.mean(pixels))
        distance = float(rect["baseline_mm"] * rect["focal_px"] / disparity) if disparity > 0 else None
        z = None
        if distance is not None and z_ref:
            z = float(z_ref["Z0_mm"]) + (float(z_ref["d0_mm"]) - distance) * float(z_ref.get("scale", 1.0))
        item.update({
            "z": round(z, 4) if z is not None else None,
            "distance_mm": round(distance, 4) if distance is not None else None,
            "disparity": round(disparity, 4),
            "valid_ratio": round(valid_ratio, 4),
            "compensated": compensated,
        })
        out.append(item)
    return out


class StereoDepthTool(Tool):
    key = "stereo_depth"
    label = "Stereo depth"
    description = "Measures camera distance and robot Z from a stereo image pair inside each segmented object mask."
    category = "measure"
    icon = "Layers3"
    heavy = True
    params = [
        Param("calibration", "Calibration", kind="asset", accept="calibration", required=True),
        Param("min_disparity", "Min disparity", kind="number", default=0, step=1, group="Stereo"),
        Param("num_disparities", "Disparity range", kind="number", default=128, minimum=16, step=16, group="Stereo", teach=True),
        Param("block_size", "Block size", kind="number", default=5, minimum=3, maximum=31, step=2, group="Stereo", teach=True),
        Param("scale", "ROI scale", kind="number", default=0.5, minimum=0.05, maximum=1.0, step=0.05, group="Stereo"),
        Param("use_wls", "Filtered disparity", kind="boolean", default=False, group="Advanced"),
        Param("preprocess", "Preprocess", kind="select", default="none", options=PREPROCESS_OPTIONS, group="Advanced"),
        Param("stat", "Statistic", kind="select", default="mean", options=STAT_OPTIONS, group="Advanced"),
        Param("min_valid_ratio", "Min valid ratio", kind="range", default=0.25, minimum=0, maximum=1, step=0.01, group="Verdict", teach=True),
        Param("motion_compensation", "Motion compensation", kind="boolean", default=True, group="Advanced"),
    ]
    inputs = [
        Port("image", "Left image", "image"),
        Port("image_right", "Right image", "image"),
        Port("matches", "Matches", "matches"),
        Port("dt_ms", "Pair offset", "number", required=False),
    ]
    outputs = [
        flow_out("ok", "Depth measured", "ok"),
        flow_out("ng", "No valid depth", "critical"),
        Port("matches", "Matches with depth", "matches"),
        Port("z", "First Z", "number", required=False),
        Port("ok", "OK", "bool"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        left = ctx.require_image("image")
        right = ctx.require_image("image_right")
        raw = ctx.inputs.get("matches")
        if not isinstance(raw, list):
            raise ToolError("Connect matches from segmentation, detection or tracking")
        payload = read_calibration(ctx)
        try:
            measured = measure_matches(
                left, right, [dict(m) for m in raw if isinstance(m, dict)], payload,
                min_disparity=ctx.integer("min_disparity", 0),
                num_disparities=ctx.integer("num_disparities", 128),
                block_size=ctx.integer("block_size", 5),
                scale=ctx.number("scale", 0.5),
                preprocess=str(ctx.param("preprocess", "none") or "none"),
                stat=str(ctx.param("stat", "mean") or "mean"),
                min_valid_ratio=ctx.number("min_valid_ratio", 0.25),
                use_wls=ctx.flag("use_wls", False),
                dt_ms=float(ctx.inputs["dt_ms"]) if ctx.inputs.get("dt_ms") is not None else None,
                motion_compensation=ctx.flag("motion_compensation", True),
                log_warning=lambda msg: ctx.log(msg, level="warning"),
            )
        except calib.CalibError as exc:
            raise ToolError(str(exc)) from None
        good = [m for m in measured if m.get("distance_mm") is not None]
        overlays = []
        for item in measured:
            centroid = item.get("centroid")
            x = y = None
            if isinstance(centroid, list) and len(centroid) >= 2:
                x, y = float(centroid[0]), float(centroid[1])
            elif item.get("cx") is not None and item.get("cy") is not None:
                x, y = float(item["cx"]), float(item["cy"])
            if x is None or y is None:
                bx, by, bw, _bh = _bbox(item)
                x, y = bx + bw / 2, by
            z = item.get("z")
            text = f"Z {z:.2f}" if isinstance(z, (int, float)) else "Z --"
            overlays.append({"kind": "text", "x": x, "y": y, "text": text, "color": "#22c55e" if item.get("distance_mm") is not None else "#ef4444"})
        z0 = good[0].get("z") if good else None
        warnings = []
        if not (payload.get("stereo") or {}).get("z_ref"):
            warnings.append("No height reference is set; robot Z is empty")
        if any(not m.get("compensated") for m in measured) and ctx.inputs.get("dt_ms") is not None and ctx.flag("motion_compensation", True):
            warnings.append("Some objects had no velocity, so motion compensation was skipped")
        return Result(
            outputs={"matches": measured, "z": z0, "ok": bool(good)},
            overlays=overlays,
            branch="ok" if good else "ng",
            status="ok" if good else "ng",
            message=f"{len(good)}/{len(measured)} depths" + ("; no height reference" if warnings and not (payload.get("stereo") or {}).get("z_ref") else ""),
            detail={"warnings": warnings} if warnings else {},
        )


TOOLS = [StereoDepthTool()]
