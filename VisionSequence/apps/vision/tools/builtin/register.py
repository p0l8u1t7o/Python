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


def _reference(sess, image, size, kh, kw, angle, identity=None):
    """在相同輸入尺寸的背景畫布抽參考特徵，保留邊界脈絡；依內容與工作尺寸快取。"""
    key = (sess, identity, hashlib.sha256(image.tobytes()).digest(), image.shape, size, kh, kw, angle)
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


def _classes(ctx, positives):
    """明確類別清單保留零計數；舊圖名只在啟用類別功能後轉成類別。"""
    names = [line.strip() for line in str(ctx.param('classes') or '').splitlines() if line.strip()]
    text = str(ctx.param('class_limits') or '').strip()
    active = bool(names or text or any(':' in label for label, _ in positives))
    if len(names) != len(set(names)) or any(':' in name or ',' in name for name in names):
        raise ToolError("Use unique class names without colons or commas")
    mapped = [(label.split(':', 1)[0].strip() if ':' in label else 'default', image) for label, image in positives]
    for label, _ in mapped:
        if not label or (names and label not in names):
            raise ToolError("Each registered picture must name a listed class")
    classes = names or list(dict.fromkeys(label for label, _ in mapped))
    limits = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            label, bounds = line.split(':')
            label = label.strip()
            lo, hi = (int(value.strip()) for value in bounds.split(','))
            if label not in classes or label in limits or not 0 <= lo <= hi:
                raise ValueError
        except (ValueError, TypeError):
            raise ToolError("Enter each listed class once as class:minimum,maximum with nonnegative ordered counts") from None
        limits[label] = (lo, hi)
    return mapped if active else positives, classes, limits, active


class RegisterDetect(Tool):
    key = "register_detect"
    label = "Registration detection"
    description = "Find, count or check for parts using a few cropped example pictures, without training. Add lookalikes to exclude unwanted parts."
    category = "dl"
    icon = "ScanSearch"
    heavy = True
    params = [
        Param("classes", "Classes", kind="multiline", default="", help_text="Optional class names, one per line. Name each picture class:example. Unprefixed pictures share the default class; without class settings their original labels are preserved."),
        Param("class_limits", "Accepted counts by class", kind="multiline", default="", teach=True, help_text="One class:minimum,maximum per line. Applied in Count mode in addition to the total count limits."),
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
        Port("counts", "Counts by class", "any"),
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
        positives, classes, limits, multiclass = _classes(ctx, positives)
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
        counts = dict.fromkeys(classes, 0)
        for match in kept:
            label = match['label'] if multiclass else 'default'
            counts[label] = counts.get(label, 0) + 1
        count = len(kept)
        present = bool(count)
        accepted = present if mode == "detect" else (ctx.integer("min_count", 1) <= count <= ctx.integer("max_count_ok", 50) if mode == "count" else present == (ctx.param("expected", "present") == "present"))
        if mode == "count":
            accepted = accepted and all(lo <= counts.get(label, 0) <= hi for label, (lo, hi) in limits.items())
        branch = ("found" if present else "not_found") if mode == "detect" else ("ok" if accepted else "ng")
        best = kept[0] if kept else {}
        overlays = [{"kind": "rect", "x": m['x'], "y": m['y'], "w": m['w'], "h": m['h'], "angle": m['angle'], "color": "#22c55e", "width": 2, "label": f"{m['label']} {m['score']:.2f}"} for m in kept]
        return Result(outputs={"matches": kept, "count": count, "counts": counts, "present": present, "best_score": best.get('score', 0.0), "best_x": best.get('cx', float('nan')), "best_y": best.get('cy', float('nan'))}, overlays=overlays, branch=branch, status="ok" if accepted else "ng", message=f"{count} matches")

    def _search(self, ctx, c, region, sess, scene, size, positives, negatives, scales):
        found = []
        comparisons = []
        multiclass = bool(str(ctx.param('classes') or '').strip() or str(ctx.param('class_limits') or '').strip() or any(':' in str(item.get('name', '')) for item in ctx.param('registrations')))
        height, width = c.image.shape[:2]
        sy, sx = height / scene.shape[0], width / scene.shape[1]
        span, step = abs(ctx.number("angle_range", 0)), ctx.number("angle_step", 0)
        if span > 180 or (span and step > 0 and 2 * span / step > 720):
            raise ToolError("Use an angle range up to 180 degrees and at most 721 angles")
        angles = sorted(set([0.0] + (np.arange(-span, span + 1e-6, step).tolist() if span and step > 0 else [])))
        for index, (label, image) in enumerate(positives):
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
                    ref = _reference(sess, image, size, kh, kw, angle, ctx.param('registrations')[index]['id'])
                    scores = _similarity(scene, ref)
                    if multiclass:
                        comparisons.append((label, scores, kh, kw))
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
        if multiclass:
            # 在同一中心查所有其他類別，包含未達候選門檻者；分數差保留正負。
            for match in found:
                if c.inverse is None:
                    lx, ly = match['cx'] - c.x0, match['cy'] - c.y0
                else:
                    lx, ly = cv2.invertAffineTransform(c.inverse) @ np.array([match['cx'], match['cy'], 1])
                competitors = []
                for label, scores, kh, kw in comparisons:
                    x, y = round(lx / sx - kw / 2), round(ly / sy - kh / 2)
                    if label != match['label'] and 0 <= y < scores.shape[0] and 0 <= x < scores.shape[1]:
                        competitors.append((float(scores[y, x]), label))
                score, label = max(competitors, default=(0.0, ''))
                match.update(runner_up=label, runner_up_score=score, margin=match['score'] - score)
        return found


_PATCH_CACHE: OrderedDict = OrderedDict()


def _patches(sess, image, size, identity):
    """每張固定影像獨立快取，追加註冊圖不重算已存在的網格。"""
    key = (sess, identity, size, image.shape, hashlib.sha256(image.tobytes()).digest())
    with _LOCK:
        if key in _PATCH_CACHE:
            _PATCH_CACHE.move_to_end(key)
            return _PATCH_CACHE[key]
    value = _grid(sess, image, size)
    value = value / np.maximum(np.linalg.norm(value, axis=2, keepdims=True), 1e-12)
    value.setflags(write=False)
    with _LOCK:
        _PATCH_CACHE[key] = value
        while len(_PATCH_CACHE) > 64:
            _PATCH_CACHE.popitem(last=False)
    return value


def _prototypes(patches, k=8):
    """確定性的最遠點初始化與 k-means；不修改共用亂數種子。"""
    points = np.concatenate(patches).astype(np.float32)
    # 限制教導成本並以固定等距取樣保持可重現。
    if len(points) > 8192:
        points = points[np.linspace(0, len(points) - 1, 8192, dtype=int)]
    centers = [points[0]]
    distance = np.full(len(points), np.inf)
    for _ in range(1, min(k, len(points))):
        distance = np.minimum(distance, np.sum((points - centers[-1]) ** 2, axis=1))
        if float(distance.max()) < 1e-10:
            break
        centers.append(points[int(distance.argmax())])
    centers = np.array(centers)
    for _ in range(20):
        labels = np.argmin(np.sum((points[:, None] - centers) ** 2, axis=2), axis=1)
        updated = np.array([points[labels == i].mean(axis=0) if np.any(labels == i) else center for i, center in enumerate(centers)])
        if np.allclose(updated, centers, atol=1e-6):
            break
        centers = updated
    return centers / np.maximum(np.linalg.norm(centers, axis=1, keepdims=True), 1e-12)


class RegisterSegment(Tool):
    key = "register_segment"
    label = "Registration segmentation"
    description = "Segment similar textures from a few cropped examples and optional background pictures, without training."
    category = "dl"
    icon = "ScanSearch"
    heavy = True
    params = [
        Param("registrations", "Registered pictures", kind="images", required=True, teach=True, help_text="Target crops. Optionally add a same-size picture named exactly crop-name#mask, with nonzero foreground. Without a mask the entire crop is foreground."),
        Param("negatives", "Background pictures", kind="images", teach=True, help_text="Optional background examples. Masked-out crop patches also supply background; without either, background similarity is zero."),
        Param("roi", "Search region", kind="roi", shapes=["rect", "rotated_rect"], teach=True, help_text="Features use an 8-pixel grid at a working size of 320. Boundaries are approximate; reduce the search region for small targets."),
        Param("min_margin", "Minimum similarity margin", kind="range", default=0.15, minimum=-2, maximum=2, step=0.01, teach=True, help_text="Nearest foreground similarity minus nearest background similarity; larger values keep fewer pixels."),
        Param("cleanup", "Cleanup radius", kind="number", default=1, minimum=0, maximum=20, teach=True, unit="px"),
        Param("min_area", "Minimum region area", kind="number", default=64, minimum=0, teach=True, unit="px²"),
        Param("mode", "Mode", kind="select", default="presence", options=[{"value": "presence", "label": "Presence"}, {"value": "area_range", "label": "Total area range"}]),
        Param("min_area_total", "Minimum total area", kind="number", default=0, minimum=0, teach=True, unit="px²"),
        Param("max_area_total", "Maximum total area", kind="number", default=1000000000, minimum=0, teach=True, unit="px²"),
        *[param for param in RegisterDetect.params if param.key in ('device', 'backbone_path')],
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Search region", "region", required=False)]
    outputs = [flow_out("ok", "Accepted", "ok"), flow_out("ng", "Rejected", "critical"),
               Port("mask", "Mask", "image"), Port("regions", "Regions", "list"),
               Port("area", "Total area", "number"), Port("count", "Count", "number"), Port("present", "Present", "bool")]

    def execute(self, ctx: ToolContext) -> Result:
        for param in self.params:
            if param.kind in ('number', 'range'):
                value = ctx.number(param.key, param.default)
                if not math.isfinite(value) or value < param.minimum or (param.maximum is not None and value > param.maximum):
                    raise ToolError(f"{param.label} is outside the allowed range")
        mode = ctx.param('mode', 'presence')
        if mode not in ('presence', 'area_range'):
            raise ToolError("Choose a valid segmentation mode")
        if ctx.number('min_area_total', 0) > ctx.number('max_area_total', 1000000000):
            raise ToolError("The accepted area range is reversed")
        positives, negatives = _images(ctx, 'registrations'), _images(ctx, 'negatives')
        pictures = {name: image for name, image in positives}
        if len(pictures) != len(positives):
            raise ToolError("Use unique registered picture names")
        targets = [(name, image) for name, image in positives if not name.endswith('#mask')]
        if not targets:
            raise ToolError("Add at least one registered target picture")
        if any(name.endswith('#mask') and name[:-5] not in pictures for name in pictures):
            raise ToolError("Each mask must have a matching target picture")
        source = ctx.require_image()
        c = crop(source, ctx.roi(), upright=True)
        path = str(ctx.param('backbone_path') or anomaly.backbone_path())
        if not os.path.isfile(path):
            raise ToolError("The feature model for registration segmentation is not installed: install the deep learning pack")
        try:
            sess = anomaly.session_for(path, path=path, device=str(ctx.param('device', 'auto')))
        except anomaly.AnomalyError:
            raise ToolError("The feature model could not be loaded; check the deep learning pack and device setting") from None
        declared = sess.get_inputs()[0].shape[-1]
        size = declared if isinstance(declared, int) else 320
        foreground, background = [], []
        ids = {name: item['id'] for (name, _), item in zip(positives, ctx.param('registrations'))}
        for name, image in targets:
            grid = _patches(sess, image, size, ids[name])
            mask = pictures.get(name + '#mask')
            if mask is None:
                selected = np.ones(grid.shape[:2], bool)
            else:
                if mask.shape[:2] != image.shape[:2]:
                    raise ToolError("A registration mask must match its target picture size")
                binary = np.any(mask != 0, axis=2) if mask.ndim == 3 else mask != 0
                selected = cv2.resize(binary.astype(np.float32), (grid.shape[1], grid.shape[0]), interpolation=cv2.INTER_AREA) >= 0.5
            if not selected.any():
                raise ToolError("Each target mask must include foreground patches")
            foreground.append(grid[selected])
            if (~selected).any():
                background.append(grid[~selected])
        for (_, image), item in zip(negatives, ctx.param('negatives') or []):
            grid = _patches(sess, image, size, item['id'])
            background.append(grid.reshape(-1, grid.shape[-1]))
        fg = _prototypes(foreground)
        bg = _prototypes(background) if background else None
        mask = np.zeros(source.shape[:2], np.uint8)
        if c.image.size:
            grid = _grid(sess, c.image, size)
            grid /= np.maximum(np.linalg.norm(grid, axis=2, keepdims=True), 1e-12)
            margin = np.max(grid @ fg.T, axis=2)
            if bg is not None:
                margin -= np.max(grid @ bg.T, axis=2)
            score = cv2.resize(margin, (c.image.shape[1], c.image.shape[0]), interpolation=cv2.INTER_LINEAR)
            local = (score >= ctx.number('min_margin', 0.15)).astype(np.uint8) * 255
            radius = ctx.integer('cleanup', 1)
            if radius:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
                local = cv2.morphologyEx(cv2.morphologyEx(local, cv2.MORPH_OPEN, kernel), cv2.MORPH_CLOSE, kernel)
            if c.mask is not None:
                local[c.mask == 0] = 0
            if c.inverse is not None:
                mask = cv2.warpAffine(local, c.inverse, (source.shape[1], source.shape[0]), flags=cv2.INTER_NEAREST)
            else:
                mask[c.y0:c.y0 + local.shape[0], c.x0:c.x0 + local.shape[1]] = local
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        regions, overlays = [], []
        for index in range(1, count):
            x, y, w, h, area = (int(value) for value in stats[index])
            if area < ctx.number('min_area', 64):
                mask[labels == index] = 0
                continue
            component = (labels[y:y + h, x:x + w] == index).astype(np.uint8)
            contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE, offset=(x, y))
            points = [contour.reshape(-1, 2).tolist() for contour in contours]
            regions.append({'contours': points, 'area': area, 'x': x, 'y': y, 'w': w, 'h': h})
            overlays.append({'kind': 'contours', 'contours': points, 'color': '#22c55e', 'width': 2})
        area = int(np.count_nonzero(mask))
        present = bool(regions)
        accepted = present if mode == 'presence' else ctx.number('min_area_total', 0) <= area <= ctx.number('max_area_total', 1000000000)
        return Result(outputs={'mask': mask, 'regions': regions, 'area': area, 'count': len(regions), 'present': present},
                      overlays=overlays, status='ok' if accepted else 'ng', branch='ok' if accepted else 'ng', message=f"{len(regions)} regions, area {area} px")


TOOLS = [RegisterDetect(), RegisterSegment()]
