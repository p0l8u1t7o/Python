"""零訓練註冊式檢測：裁切圖的空間特徵網格與搜尋圖滑窗比對。"""

from __future__ import annotations

import hashlib
import math
import os
import threading
from collections import OrderedDict

import cv2
import numpy as np

from apps.vision import fixed_images
from apps.vision.dl import anomaly
from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.roi import crop


_CACHE: OrderedDict = OrderedDict()
_LOCK = threading.Lock()


def _grid(sess, image, size):
    try:
        feats, (h, w) = anomaly.extract(sess, image, size)
        return feats.reshape(h, w, -1)
    except Exception:  # noqa: BLE001 - 模型檔不相容或裝置推論失敗時，不外露底層技術訊息。
        raise ToolError("The feature model could not process this picture; check the installed pack and device setting") from None


def _reference(sess, image, size, kh, kw, angle):
    """在相同輸入尺寸的背景畫布抽參考特徵，保留邊界脈絡；依內容與工作尺寸快取。"""
    key = (sess, hashlib.sha256(image.tobytes()).digest(), image.shape, size, kh, kw, angle)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    border = np.concatenate((image[0], image[-1], image[:, 0], image[:, -1]))
    background = tuple(float(v) for v in np.median(border, axis=0))
    if angle:
        h, w = image.shape[:2]
        mat = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1)
        bw = int(math.ceil(abs(w * mat[0, 0]) + abs(h * mat[0, 1])))
        bh = int(math.ceil(abs(h * mat[0, 0]) + abs(w * mat[0, 1])))
        mat[:, 2] += [(bw - w) / 2, (bh - h) / 2]
        image = cv2.warpAffine(image, mat, (bw, bh), borderValue=background)
    canvas = np.empty((size, size, 3), np.uint8)
    canvas[:] = background
    # 網格對齊並儘量遠離畫布邊緣，避免 padding 造成參考與搜尋的差異。
    ox, oy = min(4, size // 8 - kw), min(4, size // 8 - kh)
    canvas[oy * 8:(oy + kh) * 8, ox * 8:(ox + kw) * 8] = cv2.resize(image, (kw * 8, kh * 8), interpolation=cv2.INTER_AREA)
    feat = _grid(sess, canvas, size)[oy:oy + kh, ox:ox + kw].copy()
    feat /= max(float(np.linalg.norm(feat)), 1e-12)
    with _LOCK:
        _CACHE[key] = feat
        while len(_CACHE) > 64:
            _CACHE.popitem(last=False)
    return feat


def _similarity(scene, reference):
    """逐通道相關累加；整個滑窗 L2 正規化，避免攤平成巨大視窗陣列。"""
    kh, kw = reference.shape[:2]
    corr = np.zeros((scene.shape[0] - kh + 1, scene.shape[1] - kw + 1), np.float32)
    for ch in range(scene.shape[2]):
        corr += cv2.matchTemplate(scene[:, :, ch], reference[:, :, ch], cv2.TM_CCORR)
    energy = np.sum(scene * scene, axis=2)
    sums = cv2.matchTemplate(energy, np.ones((kh, kw), np.float32), cv2.TM_CCORR)
    return np.clip(corr / np.sqrt(np.maximum(sums, 1e-12)), -1, 1)


def _iou(a, b):
    """旋轉矩形的交並比，用於跨註冊圖、尺度與角度抑制。"""
    ra = ((a['cx'], a['cy']), (a['w'], a['h']), a['angle'])
    rb = ((b['cx'], b['cy']), (b['w'], b['h']), b['angle'])
    _, points = cv2.rotatedRectangleIntersection(ra, rb)
    area = abs(cv2.contourArea(points)) if points is not None else 0.0
    return area / max(a['w'] * a['h'] + b['w'] * b['h'] - area, 1e-12)


def _images(ctx, key):
    items = ctx.param(key) or []
    if not isinstance(items, list):
        raise ToolError("Choose a list of registered pictures")
    out = []
    for item in items:
        image = fixed_images.load(str(item.get('id', ''))) if isinstance(item, dict) else None
        if image is None:
            raise ToolError("A registered picture is missing; add it again")
        out.append((str(item.get('name') or item['id']), image))
    return out


class RegisterDetect(Tool):
    key = "register_detect"
    label = "Registration detection"
    description = "Find, count or check for parts using a few cropped example pictures, without training. Add lookalikes to exclude unwanted parts."
    category = "dl"
    icon = "ScanSearch"
    heavy = True
    params = [
        Param("registrations", "Registered pictures", kind="images", required=True, teach=True, help_text="One cropped target per picture. Include a small background margin; use fewer than ten examples."),
        Param("negatives", "Excluded pictures", kind="images", help_text="Optional cropped lookalikes that must not count."),
        Param("roi", "Search region", kind="roi", shapes=["rect", "rotated_rect"], teach=True),
        Param("mode", "Mode", kind="select", default="detect", options=[{"value": "detect", "label": "Detect"}, {"value": "count", "label": "Count"}, {"value": "presence", "label": "Presence"}]),
        Param("scales", "Sizes to search", default="1.0", help_text="Relative sizes separated by commas, for example 0.8,1.0,1.25."),
        Param("angle_range", "Angle range", kind="number", default=0, minimum=0, maximum=180, unit="°", help_text="Search both directions from zero. Zero disables rotation."),
        Param("angle_step", "Angle step", kind="number", default=0, minimum=0, maximum=180, unit="°", help_text="Spacing between angles. Zero disables rotation."),
        Param("min_similarity", "Minimum similarity", kind="range", default=0.7, minimum=0, maximum=1, step=0.01, teach=True),
        Param("max_count", "Max results", kind="number", default=50, minimum=1, maximum=5000),
        Param("nms_overlap", "Maximum overlap", kind="range", default=0.3, minimum=0, maximum=1, step=0.01, group="Advanced"),
        Param("min_size", "Minimum side length", kind="number", default=0, minimum=0, unit="px", help_text="Both sides must meet this limit. Zero means no limit."),
        Param("max_size", "Maximum side length", kind="number", default=0, minimum=0, unit="px", help_text="Neither side may exceed this limit. Zero means no limit."),
        Param("min_count", "Minimum accepted count", kind="number", default=1, minimum=0, visible_when={"param": "mode", "in": ["count"]}),
        Param("max_count_ok", "Maximum accepted count", kind="number", default=50, minimum=0, visible_when={"param": "mode", "in": ["count"]}),
        Param("expected", "Expected state", kind="select", default="present", options=[{"value": "present", "label": "Present"}, {"value": "absent", "label": "Absent"}], visible_when={"param": "mode", "in": ["presence"]}),
        Param("device", "Device", kind="select", default="auto", options=[{"value": "auto", "label": "Automatic"}, {"value": "cpu", "label": "Processor"}, {"value": "cuda", "label": "Graphics processor"}]),
        Param("backbone_path", "Feature model file", kind="text", required=False, group="Advanced", visible_when={"param": "device", "in": []}, help_text="Internal test override. Leave blank to use the installed feature model."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Search region", "region", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "warn"),
        flow_out("ok", "Accepted", "ok"), flow_out("ng", "Rejected", "critical"),
        Port("matches", "Matches", "matches"), Port("count", "Count", "number"),
        Port("best_score", "Best similarity", "number"), Port("best_x", "Best X", "number"), Port("best_y", "Best Y", "number"), Port("present", "Present", "bool"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        for param in self.params:
            if param.kind in ("number", "range"):
                value = ctx.number(param.key, param.default)
                if not math.isfinite(value) or (param.minimum is not None and value < param.minimum) or (param.maximum is not None and value > param.maximum):
                    raise ToolError(f"{param.label} is outside the allowed range")
        positives, negatives = _images(ctx, "registrations"), _images(ctx, "negatives")
        if not positives:
            raise ToolError("Add at least one registered picture")
        path = str(ctx.param("backbone_path") or anomaly.backbone_path())
        if not os.path.isfile(path):
            raise ToolError("The feature model for registration detection is not installed: install the deep learning pack")
        try:
            scales = list(dict.fromkeys(float(s.strip()) for s in str(ctx.param("scales", "1.0")).split(',')))
            if not scales or len(scales) > 32 or any(not math.isfinite(s) or s <= 0 for s in scales):
                raise ValueError
        except (ValueError, TypeError):
            raise ToolError("Enter up to 32 positive sizes separated by commas") from None
        mode = ctx.param("mode", "detect")
        if mode not in ("detect", "count", "presence"):
            raise ToolError("Choose a valid detection mode")
        if ctx.param("expected", "present") not in ("present", "absent"):
            raise ToolError("Choose an expected state")
        if ctx.number("min_count", 1) > ctx.number("max_count_ok", 50):
            raise ToolError("The accepted count range is reversed")
        region = ctx.roi()
        c = crop(ctx.require_image(), region, upright=True)
        found = []
        if c.image.size:
            try:
                sess = anomaly.session_for(path, path=path, device=str(ctx.param("device", "auto")))
                # 正式動態模型固定以 320 工作；測試模型尊重宣告的固定尺寸。
                declared = sess.get_inputs()[0].shape[-1]
                size = declared if isinstance(declared, int) else 320
                scene = _grid(sess, c.image, size)
                found = self._search(ctx, c, region, sess, scene, size, positives, negatives, scales)
            except anomaly.AnomalyError:
                raise ToolError("The feature model could not be loaded; check the deep learning pack and device setting") from None
        kept = []
        for match in sorted(found, key=lambda m: -m['score']):
            if all(_iou(match, other) <= ctx.number("nms_overlap", 0.3) for other in kept):
                kept.append(match)
                if len(kept) >= max(1, ctx.integer("max_count", 50)):
                    break
        count = len(kept)
        present = bool(count)
        accepted = present if mode == "detect" else (ctx.integer("min_count", 1) <= count <= ctx.integer("max_count_ok", 50) if mode == "count" else present == (ctx.param("expected", "present") == "present"))
        branch = ("found" if present else "not_found") if mode == "detect" else ("ok" if accepted else "ng")
        best = kept[0] if kept else {}
        overlays = [{"kind": "rect", "x": m['x'], "y": m['y'], "w": m['w'], "h": m['h'], "angle": m['angle'], "color": "#22c55e", "width": 2, "label": f"{m['label']} {m['score']:.2f}"} for m in kept]
        return Result(outputs={"matches": kept, "count": count, "present": present, "best_score": best.get('score', 0.0), "best_x": best.get('cx', float('nan')), "best_y": best.get('cy', float('nan'))}, overlays=overlays, branch=branch, status="ok" if accepted else "ng", message=f"{count} matches")

    def _search(self, ctx, c, region, sess, scene, size, positives, negatives, scales):
        found = []
        height, width = c.image.shape[:2]
        sy, sx = height / scene.shape[0], width / scene.shape[1]
        span, step = abs(ctx.number("angle_range", 0)), ctx.number("angle_step", 0)
        if span > 180 or (span and step > 0 and 2 * span / step > 720):
            raise ToolError("Use an angle range up to 180 degrees and at most 721 angles")
        angles = sorted(set([0.0] + (np.arange(-span, span + 1e-6, step).tolist() if span and step > 0 else [])))
        for label, image in positives:
            for scale in scales:
                h, w = image.shape[0] * scale, image.shape[1] * scale
                if min(h, w) < ctx.number("min_size", 0) or (ctx.number("max_size", 0) and max(h, w) > ctx.number("max_size", 0)):
                    continue
                for angle in angles:
                    rad = math.radians(angle)
                    bw, bh = abs(w * math.cos(rad)) + abs(h * math.sin(rad)), abs(h * math.cos(rad)) + abs(w * math.sin(rad))
                    if bw > width or bh > height:
                        continue
                    kw, kh = max(1, round(bw / sx)), max(1, round(bh / sy))
                    ref = _reference(sess, image, size, kh, kw, angle)
                    scores = _similarity(scene, ref)
                    peaks = (scores >= ctx.number("min_similarity", 0.7)) & (scores >= cv2.dilate(scores, np.ones((3, 3), np.uint8)))
                    # 相同分數的平台只取一個代表，避免均勻背景形成大量重複候選。
                    _, components = cv2.connectedComponents(peaks.astype(np.uint8))
                    neg_maps = [_similarity(scene, _reference(sess, neg, size, kh, kw, angle)) for _, neg in negatives] if peaks.any() else []
                    for component in range(1, int(components.max()) + 1):
                        ys, xs = np.where(components == component)
                        idx = int(np.argmax(scores[ys, xs]))
                        y, x = int(ys[idx]), int(xs[idx])
                        score = float(scores[y, x])
                        if any(float(n[y, x]) >= score for n in neg_maps):
                            continue
                        lx, ly = (x + kw / 2) * sx, (y + kh / 2) * sy
                        if lx - bw / 2 < 0 or ly - bh / 2 < 0 or lx + bw / 2 > width or ly + bh / 2 > height:
                            continue
                        cx, cy = c.to_full(lx, ly)
                        total_angle = angle + (float(region.get('angle', 0)) if c.inverse is not None else 0)
                        found.append({"cx": cx, "cy": cy, "x": cx - w / 2, "y": cy - h / 2, "w": w, "h": h, "angle": total_angle, "score": score, "label": label})
        return found


TOOLS = [RegisterDetect()]
