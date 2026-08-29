"""檢測／識別工具：Blob、差異缺陷、條碼、有無印字、顏色、邊緣密度、像素計數。"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from typing import Any, Callable

import cv2
import numpy as np

from apps.vision.tools.base import Param, Port, Result, Tool, ToolContext, ToolError, flow_out
from apps.vision.tools.builtin.locate import read_asset_image, to_gray
from apps.vision.tools.roi import crop, region_overlay

ROI_SHAPES = ["rect", "rotated_rect", "circle", "annulus", "polygon"]


def _binarize(gray: np.ndarray, method: str, threshold: float, polarity: str) -> np.ndarray:
    """灰階 → 0/255 前景遮罩；polarity=dark 時暗物件為前景。"""
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    flag = cv2.THRESH_BINARY_INV if polarity == "dark" else cv2.THRESH_BINARY
    if method == "fixed":
        _, mask = cv2.threshold(gray, threshold, 255, flag)
    elif method == "none":
        mask = (gray > 0).astype(np.uint8) * 255
        if polarity == "dark":
            mask = cv2.bitwise_not(mask)
    else:
        _, mask = cv2.threshold(gray, 0, 255, flag | cv2.THRESH_OTSU)
    return mask


def _prefilter_small(mask: np.ndarray, min_area: float) -> np.ndarray:
    """雜訊很多的遮罩先用連通元件把「外接框面積 < min_area」的元件清掉，再取輪廓。

    findContours 對幾萬個單像素雜訊要 40 ms（每個輪廓都是一個 Python 物件），
    connectedComponentsWithStats 只要 6 ms。外接框面積是 contourArea 的上界，
    所以被清掉的元件本來就會被 min_area 篩掉，結果與原本完全相同。
    乾淨的遮罩不該付這 2.5 ms：先抽樣列數水平方向的 0/255 轉換密度，只有雜訊密時才做。
    """
    if min_area < 4 or mask.shape[0] < 16 or mask.shape[1] < 16:
        return mask
    rows = np.ascontiguousarray(mask[::8])
    transitions = cv2.countNonZero(cv2.absdiff(rows[:, 1:], rows[:, :-1]))
    if transitions < 0.02 * rows.size:
        return mask
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return mask
    bbox_area = stats[:, cv2.CC_STAT_WIDTH].astype(np.int64) * stats[:, cv2.CC_STAT_HEIGHT]
    keep = bbox_area >= min_area
    keep[0] = False
    if keep[1:].all():
        return mask
    kept = np.nonzero(keep)[0]
    if len(kept) <= 64:
        out = np.zeros_like(mask)
        for i in kept.tolist():
            x, y, w, h = (int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
            win = labels[y : y + h, x : x + w] == i
            out[y : y + h, x : x + w][win] = 255
        return out
    lut = np.where(keep, 255, 0).astype(np.uint8)
    return lut[labels]


def analyze_blobs(mask: np.ndarray, *, min_area: float = 0, max_area: float = 0, min_circularity: float = 0,
                  external_only: bool = True, fill_holes: bool = False) -> tuple[list[dict[str, Any]], list[np.ndarray]]:
    """從二值遮罩取輪廓並計算幾何特徵；座標為遮罩座標。"""
    mode = cv2.RETR_EXTERNAL if external_only or fill_holes else cv2.RETR_CCOMP
    contours, hierarchy = cv2.findContours(_prefilter_small(mask, min_area), mode, cv2.CHAIN_APPROX_SIMPLE)
    blobs: list[dict[str, Any]] = []
    kept: list[np.ndarray] = []
    for i, cnt in enumerate(contours):
        if hierarchy is not None and mode == cv2.RETR_CCOMP and hierarchy[0][i][3] != -1:
            continue  # 洞不算 blob
        area = float(cv2.contourArea(cnt))
        if not fill_holes and hierarchy is not None and mode == cv2.RETR_CCOMP:
            child = hierarchy[0][i][2]
            while child != -1:
                area -= float(cv2.contourArea(contours[child]))
                child = hierarchy[0][child][0]
        if area < min_area or (max_area > 0 and area > max_area):
            continue
        perimeter = float(cv2.arcLength(cnt, True))
        circularity = float(4 * math.pi * area / (perimeter**2)) if perimeter > 0 else 0.0
        circularity = min(circularity, 1.0)
        if circularity < min_circularity:
            continue
        m = cv2.moments(cnt)
        if m["m00"] > 0:
            cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
        else:
            cx, cy = float(cnt[:, 0, 0].mean()), float(cnt[:, 0, 1].mean())
        x, y, w, h = cv2.boundingRect(cnt)
        angle = 0.0
        rw, rh = float(w), float(h)
        if len(cnt) >= 5:
            (_, _), (rw, rh), angle = cv2.minAreaRect(cnt)
            if rw < rh:
                rw, rh = rh, rw
                angle = angle + 90
            angle = ((angle + 90) % 180) - 90
        blobs.append({
            "cx": round(float(cx), 2), "cy": round(float(cy), 2), "area": area, "w": round(rw, 2), "h": round(rh, 2),
            "angle": round(float(angle), 2), "circularity": round(circularity, 4), "perimeter": round(perimeter, 2),
            "bbox": [int(x), int(y), int(w), int(h)],
        })
        kept.append(cnt)
    return blobs, kept


class BlobTool(Tool):
    key = "blob"
    label = "Blob 分析"
    description = "連通區域／輪廓分析：面積、中心、外接矩形、圓形度；可依面積與圓形度篩選並排序。灰階輸入會自動二值化。"
    category = "detect"
    icon = "Shapes"
    params = [
        Param("roi", "區域", kind="roi", shapes=ROI_SHAPES, help_text="留空則整張影像。"),
        Param("threshold_method", "二值化", kind="select", default="otsu", options=[
            {"value": "otsu", "label": "Otsu 自動"}, {"value": "fixed", "label": "固定門檻"}, {"value": "none", "label": "輸入已是遮罩（非 0 即前景）"},
        ]),
        Param("threshold", "門檻", kind="number", default=128, minimum=0, maximum=255, visible_when={"param": "threshold_method", "in": ["fixed"]}),
        Param("polarity", "前景", kind="select", default="bright", options=[{"value": "bright", "label": "亮物件"}, {"value": "dark", "label": "暗物件"}]),
        Param("min_area", "最小面積", kind="number", default=50, minimum=0, unit="px²", teach=True),
        Param("max_area", "最大面積", kind="number", default=0, minimum=0, unit="px²", help_text="0 表示不限。", teach=True),
        Param("min_circularity", "最小圓形度", kind="range", default=0, minimum=0, maximum=1, step=0.01, help_text="4πA/P²，正圓為 1。", teach=True),
        Param("max_count", "最多輸出", kind="number", default=100, minimum=1, maximum=5000),
        Param("sort_by", "排序", kind="select", default="area", options=[
            {"value": "area", "label": "面積（大→小）"}, {"value": "x", "label": "X（左→右）"}, {"value": "y", "label": "Y（上→下）"}, {"value": "circularity", "label": "圓形度（高→低）"},
        ]),
        Param("fill_holes", "填滿孔洞", kind="boolean", default=False, group="進階"),
        Param("external_only", "只取最外層輪廓", kind="boolean", default=True, group="進階", help_text="關閉時面積會扣掉孔洞。"),
        Param("min_count", "合格最少數量", kind="number", default=1, minimum=0, group="判定", help_text="找到的 blob 少於此值判 NG。"),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [
        flow_out("found", "找到", "ok"), flow_out("not_found", "沒找到", "critical"),
        Port("blobs", "Blob 列表", "matches"), Port("count", "數量", "number"),
        Port("largest_area", "最大面積", "number"), Port("total_area", "總面積", "number"),
        Port("contours", "輪廓", "contours"), Port("centers", "中心點", "points"), Port("mask", "遮罩", "image"),
        Port("first_cx", "第一個中心 X", "number"), Port("first_cy", "第一個中心 Y", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        gray = to_gray(image)
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("區域落在影像外")
        polarity = ctx.param("polarity", "bright")
        mask = _binarize(np.ascontiguousarray(c.image), ctx.param("threshold_method", "otsu"), ctx.number("threshold", 128), polarity)
        if c.mask is not None:
            mask = cv2.bitwise_and(mask, c.mask)
        blobs, contours = analyze_blobs(
            mask, min_area=ctx.number("min_area", 50), max_area=ctx.number("max_area", 0),
            min_circularity=ctx.number("min_circularity", 0), external_only=ctx.flag("external_only", True), fill_holes=ctx.flag("fill_holes"),
        )
        sort_by = ctx.param("sort_by", "area")
        keyf = {"area": lambda b: -b["area"], "x": lambda b: b["cx"], "y": lambda b: b["cy"], "circularity": lambda b: -b["circularity"]}[sort_by if sort_by in ("area", "x", "y", "circularity") else "area"]
        order = sorted(range(len(blobs)), key=lambda i: keyf(blobs[i]))[: ctx.integer("max_count", 100)]
        blobs = [blobs[i] for i in order]
        contours = [contours[i] for i in order]
        # 換回全圖座標
        offset = np.array([c.x0, c.y0], dtype=np.int32)
        full_contours = [cnt + offset for cnt in contours]
        for b in blobs:
            b["cx"] += c.x0
            b["cy"] += c.y0
            b["bbox"] = [b["bbox"][0] + c.x0, b["bbox"][1] + c.y0, b["bbox"][2], b["bbox"][3]]
        out_mask = np.zeros(gray.shape, dtype=np.uint8)
        if full_contours:
            cv2.drawContours(out_mask, full_contours, -1, 255, -1)
            if not ctx.flag("fill_holes"):
                out_mask[c.y0 : c.y0 + mask.shape[0], c.x0 : c.x0 + mask.shape[1]] &= mask
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        if full_contours:
            overlays.append({"kind": "contours", "contours": [cnt.reshape(-1, 2).tolist() for cnt in full_contours], "color": "#22c55e", "width": 1})
        for i, b in enumerate(blobs):
            overlays.append({"kind": "point", "x": b["cx"], "y": b["cy"], "color": "#f59e0b", "label": f"#{i + 1} A={b['area']:.0f}"})
        count = len(blobs)
        ok = count >= ctx.integer("min_count", 1)
        return Result(
            outputs={
                "blobs": blobs, "count": count,
                "largest_area": max((b["area"] for b in blobs), default=0.0), "total_area": float(sum(b["area"] for b in blobs)),
                "contours": full_contours, "centers": [[b["cx"], b["cy"]] for b in blobs], "mask": out_mask,
                "first_cx": blobs[0]["cx"] if blobs else float("nan"), "first_cy": blobs[0]["cy"] if blobs else float("nan"),
            },
            overlays=overlays, branch="found" if count else "not_found", status="ok" if ok else "ng",
            message=f"{count} 個 blob" + (f"，最大 {blobs[0]['area'] if sort_by == 'area' else max(b['area'] for b in blobs):.0f}px²" if blobs else ""),
        )


_HANNING: dict[tuple[int, int], np.ndarray] = {}
_PREPARED: "OrderedDict[tuple[Any, ...], tuple[np.ndarray, np.ndarray, np.ndarray | None]]" = OrderedDict()
_PREP_LOCK = threading.Lock()


def _hanning(w: int, h: int) -> np.ndarray:
    win = _HANNING.get((w, h))
    if win is None:
        win = cv2.createHanningWindow((w, h), cv2.CV_32F)
        if len(_HANNING) > 8:
            _HANNING.clear()
        _HANNING[(w, h)] = win
    return win


def _prepared_template(template: np.ndarray, key: tuple[Any, ...], build: "Callable[[], tuple[np.ndarray, np.ndarray | None]]") -> tuple[np.ndarray, np.ndarray | None]:
    """良品範本的前處理（縮放／裁切／模糊／轉 float32）在同一組參數下每次都相同，快取 16 組。

    快取同時抓著原範本陣列的參考並以身分比對（資產快取回的是同一個物件），
    所以範本檔更新後解碼出新陣列時不會誤用舊的前處理結果。
    """
    with _PREP_LOCK:
        hit = _PREPARED.get(key)
        if hit is not None and hit[0] is template:
            _PREPARED.move_to_end(key)
            return hit[1], hit[2]
    value = build()
    with _PREP_LOCK:
        _PREPARED[key] = (template, value[0], value[1])
        while len(_PREPARED) > 16:
            _PREPARED.popitem(last=False)
    return value


def _align(image: np.ndarray, template: np.ndarray, method: str, template_f32: np.ndarray | None = None) -> tuple[np.ndarray, dict[str, float]]:
    """把範本對齊到影像（回傳對齊後的範本與位移資訊）。"""
    if method == "phase":
        win = _hanning(image.shape[1], image.shape[0])
        tpl_f = template_f32 if template_f32 is not None else template.astype(np.float32)
        (dx, dy), resp = cv2.phaseCorrelate(image.astype(np.float32), tpl_f, win)
        m = np.array([[1, 0, -dx], [0, 1, -dy]], dtype=np.float32)
        return cv2.warpAffine(template, m, (image.shape[1], image.shape[0]), borderMode=cv2.BORDER_REPLICATE), {"dx": float(-dx), "dy": float(-dy), "response": float(resp)}
    if method == "ecc":
        warp = np.eye(2, 3, dtype=np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4)
        try:
            _, warp = cv2.findTransformECC(image, template, warp, cv2.MOTION_EUCLIDEAN, criteria, None, 5)
        except cv2.error as exc:
            raise ToolError(f"ECC 對齊失敗：{str(exc).splitlines()[-1][:120]}") from None
        aligned = cv2.warpAffine(template, warp, (image.shape[1], image.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
        return aligned, {"dx": float(warp[0, 2]), "dy": float(warp[1, 2]), "dtheta": float(math.degrees(math.atan2(warp[1, 0], warp[0, 0])))}
    return template, {}


class DefectDiffTool(Tool):
    key = "defect_diff"
    label = "差異缺陷"
    description = "與良品範本對齊後做灰階差異（absdiff → 門檻 → 形態學），差異區域即缺陷。"
    category = "detect"
    icon = "Diff"
    params = [
        Param("template", "良品範本", kind="asset", accept="image", required=True),
        Param("roi", "區域", kind="roi", shapes=ROI_SHAPES, help_text="留空則整張影像。範本需與影像同尺寸（或會被縮放到相同尺寸）。"),
        Param("align", "對齊", kind="select", default="phase", options=[
            {"value": "none", "label": "不對齊"}, {"value": "phase", "label": "相位相關（平移）"}, {"value": "ecc", "label": "ECC（平移＋旋轉）"},
        ]),
        Param("blur", "前置高斯模糊核", kind="number", default=3, minimum=0, maximum=31, group="進階"),
        Param("threshold", "差異門檻", kind="number", default=40, minimum=1, maximum=255, teach=True),
        Param("morph", "形態學開運算核", kind="number", default=3, minimum=0, maximum=31, group="進階"),
        Param("min_area", "最小缺陷面積", kind="number", default=30, minimum=0, unit="px²", teach=True),
        Param("max_count", "最多輸出", kind="number", default=100, minimum=1, maximum=5000),
        Param("border", "忽略邊界", kind="number", default=4, minimum=0, unit="px", group="進階", help_text="對齊後邊界會有假差異，忽略此寬度。"),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [
        flow_out("ok", "無缺陷", "ok"), flow_out("defect", "有缺陷", "critical"),
        Port("defects", "缺陷列表", "matches"), Port("count", "數量", "number"), Port("total_area", "總面積", "number"),
        Port("defect_mask", "缺陷遮罩", "image"), Port("diff", "差異影像", "image"),
    ]
    heavy = True

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        template = read_asset_image(ctx, "template")
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("區域落在影像外")
        sub = np.ascontiguousarray(c.image)
        k = ctx.integer("blur", 3)
        if k >= 3:
            k |= 1
        align = ctx.param("align", "phase")

        def build() -> tuple[np.ndarray, np.ndarray | None]:
            tpl = template
            if tpl.shape != sub.shape:
                if region is None or tpl.shape != gray.shape:
                    tpl = cv2.resize(tpl, (sub.shape[1], sub.shape[0]), interpolation=cv2.INTER_AREA)
                else:
                    tpl = np.ascontiguousarray(crop(tpl, region).image)
            if k >= 3:
                tpl = cv2.GaussianBlur(tpl, (k, k), 0)
            return tpl, (tpl.astype(np.float32) if align == "phase" else None)

        # 快取鍵：範本尺寸＋裁切位置／尺寸＋模糊核＋對齊法（範本本身以物件身分比對）
        tpl_b, tpl_f32 = _prepared_template(template, (template.shape, c.x0, c.y0, sub.shape, k, align), build)
        sub_b = cv2.GaussianBlur(sub, (k, k), 0) if k >= 3 else sub
        aligned, info = _align(sub_b, tpl_b, align, tpl_f32)
        diff = cv2.absdiff(sub_b, aligned)
        _, mask = cv2.threshold(diff, ctx.number("threshold", 40), 255, cv2.THRESH_BINARY)
        m = ctx.integer("morph", 3)
        if m >= 2:
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (m, m)))
        b = ctx.integer("border", 4)
        if b > 0 and mask.shape[0] > 2 * b and mask.shape[1] > 2 * b:
            mask[:b, :] = 0
            mask[-b:, :] = 0
            mask[:, :b] = 0
            mask[:, -b:] = 0
        if c.mask is not None:
            mask = cv2.bitwise_and(mask, c.mask)
        blobs, contours = analyze_blobs(mask, min_area=ctx.number("min_area", 30))
        order = sorted(range(len(blobs)), key=lambda i: -blobs[i]["area"])[: ctx.integer("max_count", 100)]
        defects = []
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        for i in order:
            d = dict(blobs[i])
            d["cx"] += c.x0
            d["cy"] += c.y0
            d["bbox"] = [d["bbox"][0] + c.x0, d["bbox"][1] + c.y0, d["bbox"][2], d["bbox"][3]]
            defects.append(d)
            overlays.append({"kind": "rect", "x": d["bbox"][0], "y": d["bbox"][1], "w": d["bbox"][2], "h": d["bbox"][3], "color": "#ef4444", "width": 2, "label": f"{d['area']:.0f}"})
        full_mask = np.zeros(gray.shape, dtype=np.uint8)
        full_diff = np.zeros(gray.shape, dtype=np.uint8)
        full_mask[c.y0 : c.y0 + mask.shape[0], c.x0 : c.x0 + mask.shape[1]] = mask
        full_diff[c.y0 : c.y0 + diff.shape[0], c.x0 : c.x0 + diff.shape[1]] = diff
        count = len(defects)
        return Result(
            outputs={"defects": defects, "count": count, "total_area": float(sum(d["area"] for d in defects)), "defect_mask": full_mask, "diff": full_diff},
            overlays=overlays, branch="defect" if count else "ok", status="ng" if count else "ok",
            message=f"{count} 個缺陷" + (f"，對齊 dx={info.get('dx', 0):.1f} dy={info.get('dy', 0):.1f}" if info else ""),
            detail=info,
        )


class BarcodeTool(Tool):
    key = "barcode"
    label = "條碼 / QR"
    description = "解碼 QR code 與一維條碼（EAN/UPC/Code128 等；需 OpenCV 有 barcode 模組）。"
    category = "detect"
    icon = "QrCode"
    params = [
        Param("roi", "區域", kind="roi", shapes=["rect"], help_text="留空則整張影像。"),
        Param("types", "類型", kind="select", default="all", options=[{"value": "all", "label": "QR + 一維條碼"}, {"value": "qr", "label": "只 QR"}, {"value": "1d", "label": "只一維條碼"}]),
        Param("expected", "期望內容", kind="text", default="", help_text="不為空時，內容需完全相同才走「符合」分支。"),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [
        flow_out("found", "找到／符合", "ok"), flow_out("not_found", "沒找到／不符", "critical"),
        Port("texts", "內容列表", "list"), Port("count", "數量", "number"), Port("first", "第一個內容", "string"), Port("codes", "詳細", "matches"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("區域落在影像外")
        sub = np.ascontiguousarray(c.image)
        types = ctx.param("types", "all")
        codes: list[dict[str, Any]] = []
        if types in ("all", "qr"):
            try:
                ok, infos, pts, _ = cv2.QRCodeDetector().detectAndDecodeMulti(sub)
            except cv2.error:
                ok, infos, pts = False, [], None
            if ok and pts is not None:
                for text, quad in zip(infos, pts):
                    if text:
                        codes.append({"text": str(text), "type": "QR", "points": c.points_to_full(np.asarray(quad).reshape(-1, 2)).round(1).tolist()})
        if types in ("all", "1d"):
            try:
                detector = cv2.barcode.BarcodeDetector()
                result = detector.detectAndDecodeMulti(sub)
            except (AttributeError, cv2.error):
                result = None
                if types == "1d":
                    ctx.log("此 OpenCV 沒有 barcode 模組", level="warn")
            if result:
                ok, infos, kinds, pts = (result + (None,))[:4] if len(result) == 3 else result
                if ok and pts is not None:
                    for i, text in enumerate(infos):
                        if text:
                            kind = str(kinds[i]) if kinds is not None and i < len(kinds) else "1D"
                            codes.append({"text": str(text), "type": kind, "points": c.points_to_full(np.asarray(pts[i]).reshape(-1, 2)).round(1).tolist()})
        texts = [cd["text"] for cd in codes]
        overlays: list[dict[str, Any]] = [region_overlay(region, label="roi")] if region else []
        for cd in codes:
            overlays.append({"kind": "polygon", "points": cd["points"], "color": "#22c55e", "width": 2, "label": cd["text"][:40]})
        expected = str(ctx.param("expected", "") or "")
        matched = bool(texts) and (not expected or expected in texts)
        return Result(
            outputs={"texts": texts, "count": len(texts), "first": texts[0] if texts else "", "codes": codes},
            overlays=overlays, branch="found" if matched else "not_found", status="ok" if matched else "ng",
            message=(f"{len(texts)} 個：{', '.join(t[:30] for t in texts)}" if texts else "沒有解出條碼") + ("" if matched or not texts else f"（期望 {expected}）"),
        )


class TextPresenceTool(Tool):
    key = "text_presence"
    label = "有無印字"
    description = "區域內筆劃像素比例（自適應二值化後的前景比例）是否達門檻，用來判斷有無印字／標籤。"
    category = "detect"
    icon = "Type"
    params = [
        Param("roi", "區域", kind="roi", required=True, shapes=ROI_SHAPES),
        Param("polarity", "字色", kind="select", default="dark", options=[{"value": "dark", "label": "深色字"}, {"value": "bright", "label": "淺色字"}]),
        Param("block", "自適應區塊（奇數）", kind="number", default=31, minimum=3, maximum=255, step=2, group="進階"),
        Param("c", "自適應常數 C", kind="number", default=10, minimum=-100, maximum=100, group="進階"),
        Param("min_ratio", "最小筆劃比例", kind="range", default=0.03, minimum=0, maximum=1, step=0.005, teach=True),
        Param("max_ratio", "最大筆劃比例", kind="range", default=0.6, minimum=0, maximum=1, step=0.005, help_text="超過視為污損或整片色塊。", teach=True),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [flow_out("present", "有", "ok"), flow_out("absent", "無", "critical"), Port("ratio", "筆劃比例", "number"), Port("is_present", "有印字", "bool"), Port("mask", "筆劃遮罩", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("沒有設定區域")
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("區域落在影像外")
        b = max(3, ctx.integer("block", 31)) | 1
        flag = cv2.THRESH_BINARY_INV if ctx.param("polarity", "dark") == "dark" else cv2.THRESH_BINARY
        mask = cv2.adaptiveThreshold(np.ascontiguousarray(c.image), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, flag, b, ctx.number("c", 10))
        total = c.image.size
        if c.mask is not None:
            mask = cv2.bitwise_and(mask, c.mask)
            total = int(np.count_nonzero(c.mask))
        ratio = float(np.count_nonzero(mask)) / max(1, total)
        present = ctx.number("min_ratio", 0.03) <= ratio <= ctx.number("max_ratio", 0.6)
        full = np.zeros(gray.shape, dtype=np.uint8)
        full[c.y0 : c.y0 + mask.shape[0], c.x0 : c.x0 + mask.shape[1]] = mask
        return Result(outputs={"ratio": ratio, "is_present": present, "mask": full},
                      overlays=[region_overlay(region, color="#22c55e" if present else "#ef4444", label=f"{ratio * 100:.1f}%")],
                      branch="present" if present else "absent", status="ok" if present else "ng", message=f"筆劃比例 {ratio * 100:.1f}% → {'有' if present else '無'}")


def _hex_to_bgr(value: str) -> tuple[int, int, int]:
    s = str(value or "").strip().lstrip("#")
    if len(s) != 6:
        raise ToolError(f"顏色格式錯誤：{value!r}")
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        raise ToolError(f"顏色格式錯誤：{value!r}") from None
    return b, g, r


class ColorCheckTool(Tool):
    key = "color_check"
    label = "顏色檢查"
    description = "區域內平均顏色與目標色的距離（RGB 或 HSV 空間）是否在容差內。"
    category = "detect"
    icon = "Palette"
    params = [
        Param("roi", "區域", kind="roi", shapes=ROI_SHAPES, help_text="留空則整張影像。"),
        Param("color", "目標色", kind="color", required=True, default="#ff0000"),
        Param("space", "比較空間", kind="select", default="rgb", options=[{"value": "rgb", "label": "RGB 歐氏距離（0~441）"}, {"value": "hsv", "label": "HSV（色相為主）"}]),
        Param("tolerance", "容差", kind="number", default=60, minimum=0, help_text="RGB：歐氏距離；HSV：色相差（0~180）加權距離。", teach=True),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [flow_out("match", "符合", "ok"), flow_out("mismatch", "不符", "critical"), Port("distance", "距離", "number"), Port("is_match", "符合", "bool"), Port("mean_hex", "平均色", "string"), Port("mean_bgr", "平均 BGR", "list"), Port("mean_hsv", "平均 HSV", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("區域落在影像外")
        mean = cv2.mean(np.ascontiguousarray(c.image), mask=c.mask)[:3]
        mean_bgr = np.array(mean, dtype=np.float32)
        target = np.array(_hex_to_bgr(ctx.param("color", "#ff0000")), dtype=np.float32)
        mean_hsv = cv2.cvtColor(mean_bgr.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2HSV).reshape(3).astype(float)
        if ctx.param("space", "rgb") == "hsv":
            tgt_hsv = cv2.cvtColor(target.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2HSV).reshape(3).astype(float)
            dh = abs(mean_hsv[0] - tgt_hsv[0])
            dh = min(dh, 180 - dh)
            distance = float(math.sqrt(dh**2 + ((mean_hsv[1] - tgt_hsv[1]) / 4) ** 2 + ((mean_hsv[2] - tgt_hsv[2]) / 4) ** 2))
        else:
            distance = float(np.linalg.norm(mean_bgr - target))
        match = distance <= ctx.number("tolerance", 60)
        mean_hex = "#{:02x}{:02x}{:02x}".format(int(round(mean[2])), int(round(mean[1])), int(round(mean[0])))
        overlays = [region_overlay(region, color="#22c55e" if match else "#ef4444", label=f"{mean_hex} d={distance:.1f}")] if region else []
        return Result(
            outputs={"distance": distance, "is_match": match, "mean_hex": mean_hex, "mean_bgr": [round(float(v), 1) for v in mean], "mean_hsv": [round(float(v), 1) for v in mean_hsv]},
            overlays=overlays, branch="match" if match else "mismatch", status="ok" if match else "ng", message=f"平均 {mean_hex}，距離 {distance:.1f} → {'符合' if match else '不符'}",
        )


class EdgeDensityTool(Tool):
    key = "edge_density"
    label = "邊緣密度"
    description = "區域內 Canny 邊緣像素比例；平滑表面出現刮痕、髒污時比例會升高。"
    category = "detect"
    icon = "Activity"
    params = [
        Param("roi", "區域", kind="roi", shapes=ROI_SHAPES, help_text="留空則整張影像。"),
        Param("canny_low", "Canny 低門檻", kind="number", default=50, minimum=0, maximum=500),
        Param("canny_high", "Canny 高門檻", kind="number", default=150, minimum=0, maximum=500),
        Param("blur", "前置高斯核", kind="number", default=3, minimum=0, maximum=31, group="進階"),
        Param("max_ratio", "合格最大比例", kind="range", default=0.05, minimum=0, maximum=1, step=0.001, teach=True),
    ]
    inputs = [Port("image", "影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [flow_out("ok", "合格", "ok"), flow_out("ng", "超標", "critical"), Port("ratio", "邊緣比例", "number"), Port("edge_pixels", "邊緣像素數", "number"), Port("edges", "邊緣影像", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("區域落在影像外")
        sub = np.ascontiguousarray(c.image)
        k = ctx.integer("blur", 3)
        if k >= 3:
            sub = cv2.GaussianBlur(sub, (k | 1, k | 1), 0)
        edges = cv2.Canny(sub, ctx.number("canny_low", 50), ctx.number("canny_high", 150))
        total = sub.size
        if c.mask is not None:
            edges = cv2.bitwise_and(edges, c.mask)
            total = int(np.count_nonzero(c.mask))
        n = int(np.count_nonzero(edges))
        ratio = n / max(1, total)
        ok = ratio <= ctx.number("max_ratio", 0.05)
        full = np.zeros(gray.shape, dtype=np.uint8)
        full[c.y0 : c.y0 + edges.shape[0], c.x0 : c.x0 + edges.shape[1]] = edges
        overlays = [region_overlay(region, color="#22c55e" if ok else "#ef4444", label=f"{ratio * 100:.2f}%")] if region else []
        return Result(outputs={"ratio": ratio, "edge_pixels": n, "edges": full}, overlays=overlays,
                      branch="ok" if ok else "ng", status="ok" if ok else "ng", message=f"邊緣比例 {ratio * 100:.2f}%")


class PixelCountTool(Tool):
    key = "pixel_count"
    label = "像素計數"
    description = "遮罩（或灰階以門檻二值化後）在區域內的前景像素數與比例。"
    category = "detect"
    icon = "Grid3x3"
    params = [
        Param("roi", "區域", kind="roi", shapes=ROI_SHAPES, help_text="留空則整張影像。"),
        Param("threshold", "門檻", kind="number", default=128, minimum=0, maximum=255, help_text="大於等於此灰階算前景；輸入已是 0/255 遮罩時維持預設即可。"),
        Param("min_count", "合格最少像素", kind="number", default=0, minimum=0, teach=True),
        Param("max_count", "合格最多像素", kind="number", default=0, minimum=0, help_text="0 表示不限。", teach=True),
    ]
    inputs = [Port("image", "遮罩／影像", "image"), Port("roi", "區域（動態）", "region", required=False)]
    outputs = [flow_out("ok", "合格", "ok"), flow_out("ng", "不合格", "critical"), Port("count", "像素數", "number"), Port("ratio", "比例", "number"), Port("total", "區域像素數", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("區域落在影像外")
        fg = c.image >= ctx.number("threshold", 128)
        total = c.image.size
        if c.mask is not None:
            fg &= c.mask > 0
            total = int(np.count_nonzero(c.mask))
        n = int(np.count_nonzero(fg))
        ratio = n / max(1, total)
        lo, hi = ctx.integer("min_count", 0), ctx.integer("max_count", 0)
        ok = n >= lo and (hi <= 0 or n <= hi)
        overlays = [region_overlay(region, color="#22c55e" if ok else "#ef4444", label=f"{n}px")] if region else []
        return Result(outputs={"count": n, "ratio": ratio, "total": total}, overlays=overlays,
                      branch="ok" if ok else "ng", status="ok" if ok else "ng", message=f"{n} px（{ratio * 100:.2f}%）")


TOOLS = [BlobTool(), DefectDiffTool(), BarcodeTool(), TextPresenceTool(), ColorCheckTool(), EdgeDensityTool(), PixelCountTool()]
