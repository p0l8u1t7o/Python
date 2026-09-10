"""散亂單字元：元件合併、旋轉外框與固定影像模板分類。"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from apps.vision import fixed_images
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.lists import _sort_matches
from apps.vision.tools.builtin.locate import fit_circle_lsq, to_gray
from apps.vision.tools.builtin.preprocess import _local_thresholds
from apps.vision.tools.hist import otsu_from_hist
from apps.vision.tools.roi import crop


def _binary(image: np.ndarray, method: str, polarity: str, threshold: float, window: int, k: float) -> np.ndarray:
    """先把文字轉成暗色，兩種極性共用同一組區域門檻。"""
    gray = to_gray(image)
    dark = gray if polarity == "dark_on_light" else 255 - gray
    if method == "otsu":
        level = otsu_from_hist(np.bincount(dark.ravel(), minlength=256))
    elif method == "sauvola":
        level = _local_thresholds(dark, "sauvola", window, k)
    else:
        level = threshold
    return np.asarray(dark <= level, dtype=np.uint8) * 255


def _tile(mask: np.ndarray) -> np.ndarray:
    """保留長寬比與白邊，建立可比較的固定大小字元。"""
    ys, xs = np.nonzero(mask > 127)
    out = np.zeros((48, 48), np.uint8)
    if not len(xs):
        return out
    sub = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    scale = 40 / max(sub.shape)
    w, h = max(1, round(sub.shape[1] * scale)), max(1, round(sub.shape[0] * scale))
    out[(48 - h) // 2:(48 - h) // 2 + h, (48 - w) // 2:(48 - w) // 2 + w] = cv2.resize(sub, (w, h), interpolation=cv2.INTER_AREA)
    return out


def _upright(mask: np.ndarray, rect: tuple) -> np.ndarray:
    """角度正值為畫面順時針，旋回後只取該元件外框。"""
    (cx, cy), (w, h), angle = rect
    matrix = cv2.getRotationMatrix2D((cx, cy), angle, 1)
    size = (max(1, int(math.ceil(w)) + 3), max(1, int(math.ceil(h)) + 3))
    matrix[:, 2] += np.array([size[0] / 2 - cx, size[1] / 2 - cy])
    return cv2.warpAffine(mask, matrix, size)


def _arc_order(chars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """以最大空白角為起點，沿畫面順時針排序；退化點集回閱讀順序。"""
    fit = fit_circle_lsq(np.asarray([[c["cx"], c["cy"]] for c in chars], dtype=np.float64)) if len(chars) >= 3 else None
    if fit is None:
        return _sort_matches(chars, "xy", False)
    cx, cy, _ = fit
    angles = np.mod([math.atan2(c["cy"] - cy, c["cx"] - cx) for c in chars], 2 * math.pi)
    indices = np.argsort(angles, kind="stable")
    gaps = np.diff(np.r_[angles[indices], angles[indices[0]] + 2 * math.pi])
    start = (int(np.argmax(gaps)) + 1) % len(chars)
    return [chars[i] for i in np.roll(indices, -start)]


class CharDetectTool(Tool):
    key = "char_detect"
    label = "Individual characters"
    description = "Finds separate or curved characters, merges nearby strokes, and optionally labels each character from sample pictures."
    category = "detect"
    icon = "ScanText"
    params = [
        Param("roi", "Region", kind="roi"),
        Param("method", "Threshold method", kind="select", default="otsu", teach=True, options=[
            {"value": "otsu", "label": "Automatic"}, {"value": "sauvola", "label": "Local contrast"}, {"value": "fixed", "label": "Fixed"}]),
        Param("polarity", "Character polarity", kind="select", default="dark_on_light", teach=True, options=[
            {"value": "dark_on_light", "label": "Dark on light"}, {"value": "light_on_dark", "label": "Light on dark"}]),
        Param("threshold", "Threshold", kind="number", default=127, minimum=0, maximum=255, teach=True),
        Param("window", "Local window", kind="number", default=31, minimum=3, maximum=255, step=2, teach=True),
        Param("k", "Local contrast factor", kind="number", default=0.2, minimum=-2, maximum=2, step=0.05, teach=True),
        Param("height_min", "Minimum character height", kind="number", default=8, minimum=1, unit="px", teach=True),
        Param("height_max", "Maximum character height", kind="number", default=200, minimum=1, unit="px", teach=True),
        Param("aspect_min", "Minimum width / height", kind="number", default=0.1, minimum=0.01, teach=True),
        Param("aspect_max", "Maximum width / height", kind="number", default=2, minimum=0.01, teach=True),
        Param("area_min", "Minimum ink area", kind="number", default=10, minimum=1, unit="px", teach=True),
        Param("area_max", "Maximum ink area", kind="number", default=40000, minimum=1, unit="px", teach=True),
        Param("merge_gap", "Merge strokes within", kind="number", default=0, minimum=0, maximum=50, unit="px", teach=True,
              help_text="Maximum blank gap in pixels. Keep this smaller than the gap between characters."),
        Param("classifier", "Classification", kind="select", default="none", options=[
            {"value": "none", "label": "Boxes only"}, {"value": "templates", "label": "Character samples"}]),
        Param("templates", "Character samples", kind="images", help_text="One character per picture. The first character of its filename is the label."),
        Param("order", "Order", kind="select", default="reading", options=[
            {"value": "reading", "label": "Reading order"}, {"value": "arc", "label": "Clockwise arc"}, {"value": "none", "label": "Unsorted"}],
              help_text="Arc order starts after the largest angular gap. Collinear centres use reading order."),
        Param("expected_text", "Expected text", kind="text", default="", teach=True),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("ok", "OK", "ok"), flow_out("ng", "Text differs", "critical"), flow_out("not_found", "No characters", "critical"),
               Port("chars", "Characters", "list"), Port("text", "Text", "string"), Port("count", "Count", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        method, polarity = str(ctx.param("method", "otsu")), str(ctx.param("polarity", "dark_on_light"))
        classifier, order = str(ctx.param("classifier", "none")), str(ctx.param("order", "reading"))
        if method not in {"otsu", "sauvola", "fixed"} or polarity not in {"dark_on_light", "light_on_dark"}:
            raise ToolError("Select a valid threshold method and character polarity")
        if classifier not in {"none", "templates"} or order not in {"reading", "arc", "none"}:
            raise ToolError("Select a valid classification and order")
        expected = str(ctx.param("expected_text", ""))
        if expected and classifier == "none":
            raise ToolError("Expected text requires character samples")
        limits = [(ctx.number(a, low), ctx.number(b, high)) for a, b, low, high in (
            ("height_min", "height_max", 8, 200), ("aspect_min", "aspect_max", 0.1, 2), ("area_min", "area_max", 10, 40000))]
        if any(low <= 0 or high < low for low, high in limits):
            raise ToolError("Character limits must be positive and maximum must be at least minimum")
        window = min(255, max(3, ctx.integer("window", 31))) | 1
        args = (method, polarity, ctx.number("threshold", 127), window, ctx.number("k", 0.2))
        samples = []
        if classifier == "templates":
            refs = ctx.param("templates") or []
            if not isinstance(refs, list) or not refs:
                raise ToolError("Add character sample pictures before classification")
            for ref in refs:
                name = str(ref.get("name", "")) if isinstance(ref, dict) else ""
                try:
                    sample = fixed_images.load(str(ref.get("id", ""))) if isinstance(ref, dict) else None
                except fixed_images.FixedImageError:
                    sample = None
                if sample is None:
                    raise ToolError(f"Character sample '{name}' is missing; add it again")
                if not name:
                    raise ToolError("Character samples need a filename starting with their label")
                tile = _tile(_binary(sample, *args))
                if not tile.any():
                    raise ToolError(f"Character sample '{name}' contains no foreground")
                samples.append((name[0], tile))
        c = crop(image, ctx.roi())
        chars = []
        if c.image.size:
            mask = _binary(c.image, *args)
            if c.mask is not None:
                mask[c.mask == 0] = 0
            # 膨脹只決定元件歸屬；面積、外框與分類一律使用原始筆畫。
            gap = min(50, max(0, ctx.integer("merge_gap", 0)))
            connected = cv2.dilate(mask, np.ones((gap + 1, gap + 1), np.uint8)) if gap else mask
            n, labels, stats, _ = cv2.connectedComponentsWithStats(connected, connectivity=8)
            for index in range(1, n):
                x, y, w, h = stats[index, :4]
                local = np.asarray((labels[y:y+h, x:x+w] == index) & (mask[y:y+h, x:x+w] != 0), dtype=np.uint8) * 255
                area = int(np.count_nonzero(local))
                if not limits[2][0] <= area <= limits[2][1]:
                    continue
                pts = cv2.findNonZero(local)
                (cx, cy), (rw, rh), angle = cv2.minAreaRect(pts)
                if angle > 45:
                    rw, rh, angle = rh, rw, angle - 90
                if min(rw, rh) <= 0:
                    continue
                if not limits[0][0] <= rh + 1 <= limits[0][1] or not limits[1][0] <= (rw + 1) / (rh + 1) <= limits[1][1]:
                    continue
                label, score = "", 0.0
                if samples:
                    tile = _tile(_upright(local, ((cx, cy), (rw, rh), angle)))
                    for turns in range(4):
                        candidate = np.ascontiguousarray(np.rot90(tile, turns))
                        for sample_label, sample_tile in samples:
                            value = float(cv2.matchTemplate(candidate, sample_tile, cv2.TM_CCOEFF_NORMED)[0, 0])
                            if value > score:
                                label, score = sample_label, value
                polygon = c.points_to_full(cv2.boxPoints(((cx + x, cy + y), (rw + 1, rh + 1), angle))).tolist()
                full_x, full_y = c.to_full(cx + x, cy + y)
                chars.append({"label": label, "score": round(score, 6), "cx": full_x, "cy": full_y,
                              "w": rw + 1, "h": rh + 1, "angle": angle, "polygon": polygon})
        if order == "reading":
            chars = _sort_matches(chars, "xy", False)
        elif order == "arc" and chars:
            chars = _arc_order(chars)
        text = "".join(ch["label"] for ch in chars)
        bad = bool(expected and text != expected)
        return Result(outputs={"chars": chars, "text": text, "count": len(chars)},
                      overlays=[{"kind": "polygon", "points": ch["polygon"], "color": "#ef4444" if bad else "#22c55e", "label": ch["label"]} for ch in chars],
                      status="ng" if bad or not chars else "ok", branch="not_found" if not chars else "ng" if bad else "ok",
                      message="No characters found" if not chars else f"{len(chars)} characters: {text}")


TOOLS = [CharDetectTool()]
