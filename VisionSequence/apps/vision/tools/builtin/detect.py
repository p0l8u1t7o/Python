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
from apps.vision.tools.hist import masked_hist, otsu_from_hist
from apps.vision.tools.roi import crop, region_overlay

ROI_SHAPES = ["rect", "rotated_rect", "circle", "ellipse", "annulus", "polygon"]


def _binarize(gray: np.ndarray, method: str, threshold: float, polarity: str, roi_mask: np.ndarray | None = None) -> np.ndarray:
    """灰階 → 0/255 前景遮罩；polarity=dark 時暗物件為前景。

    Otsu 在非矩形 ROI 時只用遮罩內像素算門檻（外框角落落在 ROI 外的其他灰階不會污染門檻）。
    """
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    flag = cv2.THRESH_BINARY_INV if polarity == "dark" else cv2.THRESH_BINARY
    if method == "fixed":
        _, mask = cv2.threshold(gray, threshold, 255, flag)
    elif method == "none":
        mask = (gray > 0).astype(np.uint8) * 255
        if polarity == "dark":
            mask = cv2.bitwise_not(mask)
    elif roi_mask is not None:
        _, mask = cv2.threshold(gray, otsu_from_hist(masked_hist(gray, roi_mask)), 255, flag)
    else:
        _, mask = cv2.threshold(gray, 0, 255, flag | cv2.THRESH_OTSU)
    return mask


def _prefilter_small(mask: np.ndarray, min_area: float) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    """雜訊很多的遮罩先用連通元件把「外接框面積 < min_area」的元件清掉，再取輪廓。

    findContours 對幾萬個單像素雜訊要 40 ms（每個輪廓都是一個 Python 物件），
    connectedComponentsWithStats 只要 6 ms。外接框面積是 contourArea 的上界，
    所以被清掉的元件本來就會被 min_area 篩掉，結果與原本完全相同。
    乾淨的遮罩不該付這 2.5 ms：先抽樣列數水平方向的 0/255 轉換密度，只有雜訊密時才做。

    回傳 (遮罩, labels, stats)：有算連通元件時一併回傳（濾掉的元件在 labels 仍是原標籤但遮罩已為 0，
    保留的元件標籤不變），analyze_blobs 拿來算像素面積就不必再跑一次。
    """
    if min_area < 4 or mask.shape[0] < 16 or mask.shape[1] < 16:
        return mask, None, None
    rows = np.ascontiguousarray(mask[::8])
    transitions = cv2.countNonZero(cv2.absdiff(rows[:, 1:], rows[:, :-1]))
    if transitions < 0.02 * rows.size:
        return mask, None, None
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return mask, labels, stats
    bbox_area = stats[:, cv2.CC_STAT_WIDTH].astype(np.int64) * stats[:, cv2.CC_STAT_HEIGHT]
    keep = bbox_area >= min_area
    keep[0] = False
    if keep[1:].all():
        return mask, labels, stats
    kept = np.nonzero(keep)[0]
    if len(kept) <= 64:
        out = np.zeros_like(mask)
        for i in kept.tolist():
            x, y, w, h = (int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
            win = labels[y : y + h, x : x + w] == i
            out[y : y + h, x : x + w][win] = 255
        return out, labels, stats
    lut = np.where(keep, 255, 0).astype(np.uint8)
    return lut[labels], labels, stats


def analyze_blobs(mask: np.ndarray, *, min_area: float = 0, max_area: float = 0, min_circularity: float = 0,
                  external_only: bool = True, fill_holes: bool = False) -> tuple[list[dict[str, Any]], list[np.ndarray]]:
    """從二值遮罩取輪廓並計算幾何特徵；座標為遮罩座標。

    area 是**像素數**（連通元件統計），與粒子分析軟體一致；cv2.contourArea 是輪廓多邊形的幾何面積，
    小粒子會少算約半個周長（1 像素粒子是 0、2×2 是 1）。external_only／fill_holes 時面積含孔洞，否則扣掉孔洞。
    圓形度仍用輪廓幾何面積與周長（兩者同一套幾何定義才自洽）。
    """
    mask, labels, stats = _prefilter_small(mask, min_area)
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    blobs: list[dict[str, Any]] = []
    kept: list[np.ndarray] = []
    if not contours:
        return blobs, kept
    hier = hierarchy[0]
    with_holes = external_only or fill_holes
    # 像素面積的來源：預濾已算好連通元件就直接用；輪廓很多（雜訊）或要扣孔洞時跑一次連通元件；
    # 乾淨遮罩、少量 blob 則逐個把外輪廓填進外接框數像素（免掉整張圖的 2～3 ms）。
    if labels is None and (len(contours) > 64 or not with_holes):
        _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for i, cnt in enumerate(contours):
        if hier[i][3] != -1:
            continue  # 洞不算 blob
        if labels is not None:
            px, py = int(cnt[0][0][0]), int(cnt[0][0][1])
            area = float(stats[labels[py, px], cv2.CC_STAT_AREA])
        else:
            area = -1.0
        if area < 0 or (with_holes and hier[i][2] != -1):
            # 含孔洞的面積：把外輪廓填滿數像素（外接框大小的暫存）
            x, y, w, h = cv2.boundingRect(cnt)
            filled = np.zeros((h, w), dtype=np.uint8)
            cv2.drawContours(filled, [cnt - np.array([x, y], dtype=cnt.dtype)], -1, 255, -1)
            area = float(cv2.countNonZero(filled))
        if area < min_area or (max_area > 0 and area > max_area):
            continue
        perimeter = float(cv2.arcLength(cnt, True))
        geo_area = float(cv2.contourArea(cnt))
        circularity = float(4 * math.pi * geo_area / (perimeter**2)) if perimeter > 0 else 0.0
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


def _watershed_split(mask: np.ndarray, min_radius: float = 0.0) -> np.ndarray:
    """距離轉換＋分水嶺把黏連粒子切開。

    種子＝距離轉換的區域極大值（視窗約 2×最小粒子半徑），不是全圖最大值的一半：大小粒子混在一張圖時
    小粒子也有自己的種子，兩顆等大且重疊的粒子頸部距離值高於半徑一半時也切得開。
    極大值先膨脹一點再取連通元件，長條粒子沿中軸的多個極大值會合併成一顆種子。
    """
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    if dist.max() <= 0:
        return mask
    k = max(3, int(2 * max(1.5, min_radius) + 1) | 1)
    local_max = cv2.dilate(dist, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    peaks = ((dist >= local_max - 1e-6) & (dist >= max(1.0, 0.5 * min_radius))).astype(np.uint8) * 255
    peaks = cv2.dilate(peaks, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k // 2 * 2 + 1, k // 2 * 2 + 1)))
    peaks = cv2.bitwise_and(peaks, mask)
    n, markers = cv2.connectedComponents(peaks)
    if n <= 2:  # 只有一顆種子：切不開，原樣返回
        return mask
    markers = markers + 1
    markers[(mask > 0) & (peaks == 0)] = 0
    cv2.watershed(cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), markers)
    out = mask.copy()
    out[markers == -1] = 0
    return out


class BlobTool(Tool):
    key = "blob"
    label = "Blob analysis"
    description = "Connected component and contour analysis: area, centre, bounding box and circularity, with filtering and sorting by area and circularity. A grayscale input is thresholded automatically."
    category = "detect"
    icon = "Shapes"
    params = [
        Param("roi", "Region", kind="roi", shapes=ROI_SHAPES, help_text="Leave blank for the whole image."),
        Param("threshold_method", "Threshold", kind="select", default="otsu", options=[
            {"value": "otsu", "label": "Otsu (automatic)"}, {"value": "fixed", "label": "Fixed"}, {"value": "none", "label": "The input is already a mask (anything non-zero is foreground)"},
        ]),
        Param("threshold", "Threshold", kind="number", default=128, minimum=0, maximum=255, visible_when={"param": "threshold_method", "in": ["fixed"]}),
        Param("polarity", "Foreground", kind="select", default="bright", options=[{"value": "bright", "label": "Bright objects"}, {"value": "dark", "label": "Dark objects"}]),
        Param("min_area", "Min area", kind="number", default=50, minimum=0, unit="px²", teach=True),
        Param("max_area", "Max area", kind="number", default=0, minimum=0, unit="px²", help_text="0 means no limit.", teach=True),
        Param("min_circularity", "Min circularity", kind="range", default=0, minimum=0, maximum=1, step=0.01, help_text="4πA/P², 1 for a perfect circle.", teach=True),
        Param("max_count", "Max results", kind="number", default=100, minimum=1, maximum=5000),
        Param("sort_by", "Sort by", kind="select", default="area", options=[
            {"value": "area", "label": "Area (large to small)"}, {"value": "x", "label": "X (left to right)"}, {"value": "y", "label": "Y (top to bottom)"}, {"value": "circularity", "label": "Circularity (high to low)"},
        ]),
        Param("separate", "Split touching particles", kind="boolean", default=False, group="Advanced", help_text="A distance transform plus watershed splits touching particles before measuring; the seed window comes from the particle radius implied by the minimum area."),
        Param("fill_holes", "Fill holes", kind="boolean", default=False, group="Advanced"),
        Param("external_only", "Outer contours only", kind="boolean", default=True, group="Advanced", help_text="Turn off and holes are subtracted from the area."),
        Param("min_count", "Min passing count", kind="number", default=1, minimum=0, group="Verdict", help_text="Fewer blobs than this is an NG."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("found", "Found", "ok"), flow_out("not_found", "Not found", "critical"),
        Port("blobs", "Blobs", "matches"), Port("count", "Count", "number"),
        Port("largest_area", "Max area", "number"), Port("total_area", "Total area", "number"),
        Port("contours", "Contour", "contours"), Port("centers", "Centres", "points"), Port("mask", "Mask", "image"),
        Port("first_cx", "First centre X", "number"), Port("first_cy", "First centre Y", "number"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        gray = to_gray(image)
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        polarity = ctx.param("polarity", "bright")
        mask = _binarize(np.ascontiguousarray(c.image), ctx.param("threshold_method", "otsu"), ctx.number("threshold", 128), polarity, c.mask)
        if c.mask is not None:
            mask = cv2.bitwise_and(mask, c.mask)
        if ctx.flag("separate"):
            mask = _watershed_split(mask, math.sqrt(max(0.0, ctx.number("min_area", 50)) / math.pi))
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
        for b, cnt in zip(blobs, full_contours):
            b["cx"] += c.x0
            b["cy"] += c.y0
            b["bbox"] = [b["bbox"][0] + c.x0, b["bbox"][1] + c.y0, b["bbox"][2], b["bbox"][3]]
            # NI 粒子量測對照：周長／方向／伸長比（fitEllipse 需要至少 5 點）
            b["perimeter"] = round(float(cv2.arcLength(cnt, True)), 2)
            if len(cnt) >= 5:
                _, (d1, d2), ang = cv2.fitEllipse(cnt)
                minor = min(d1, d2)
                b["orientation"] = round(float(ang), 2)
                b["elongation"] = round(float(max(d1, d2) / minor), 3) if minor > 0 else 0.0
            else:
                b["orientation"] = 0.0
                b["elongation"] = 1.0
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
            message=f"{count} blobs" + (f", max {blobs[0]['area'] if sort_by == 'area' else max(b['area'] for b in blobs):.0f}px²" if blobs else ""),
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
        # phaseCorrelate 帶 window 時會就地改寫「尺寸已是 DFT 最佳尺寸」的輸入（1280×960、640×480 都是）；
        # template_f32 是快取共用的前處理結果，給複本，否則第二次起就對著被視窗壓過的範本在對齊。
        tpl_f = np.array(template_f32, copy=True) if template_f32 is not None else template.astype(np.float32)
        (dx, dy), resp = cv2.phaseCorrelate(image.astype(np.float32), tpl_f, win)
        m = np.array([[1, 0, -dx], [0, 1, -dy]], dtype=np.float32)
        return cv2.warpAffine(template, m, (image.shape[1], image.shape[0]), borderMode=cv2.BORDER_REPLICATE), {"dx": float(-dx), "dy": float(-dy), "response": float(resp)}
    if method == "ecc":
        warp = np.eye(2, 3, dtype=np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4)
        try:
            _, warp = cv2.findTransformECC(image, template, warp, cv2.MOTION_EUCLIDEAN, criteria, None, 5)
        except cv2.error as exc:
            raise ToolError(f"ECC alignment failed: {str(exc).splitlines()[-1][:120]}") from None
        aligned = cv2.warpAffine(template, warp, (image.shape[1], image.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
        return aligned, {"dx": float(warp[0, 2]), "dy": float(warp[1, 2]), "dtheta": float(math.degrees(math.atan2(warp[1, 0], warp[0, 0])))}
    return template, {}


class DefectDiffTool(Tool):
    key = "defect_diff"
    label = "Difference defects"
    description = "Aligns to a golden template then takes the grey difference (absdiff, threshold, morphology); what differs is the defect."
    category = "detect"
    icon = "Diff"
    params = [
        Param("template", "Golden template", kind="asset", accept="image", required=True),
        Param("roi", "Region", kind="roi", shapes=ROI_SHAPES, help_text="Blank uses the whole image. The template must be the same size as the image, or it is scaled to match."),
        Param("align", "Aligned", kind="select", default="phase", options=[
            {"value": "none", "label": "No alignment"}, {"value": "phase", "label": "Phase correlation (translation)"}, {"value": "ecc", "label": "ECC (translation and rotation)"},
        ]),
        Param("blur", "Pre-blur kernel", kind="number", default=3, minimum=0, maximum=31, group="Advanced"),
        Param("threshold", "Difference threshold", kind="number", default=40, minimum=1, maximum=255, teach=True),
        Param("morph", "Opening kernel", kind="number", default=3, minimum=0, maximum=31, group="Advanced"),
        Param("min_area", "Min defect area", kind="number", default=30, minimum=0, unit="px²", teach=True),
        Param("max_count", "Max results", kind="number", default=100, minimum=1, maximum=5000),
        Param("border", "Ignore border", kind="number", default=4, minimum=0, unit="px", group="Advanced", help_text="Alignment leaves false differences at the border; ignore this many pixels."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("ok", "Clean", "ok"), flow_out("defect", "Defective", "critical"),
        Port("defects", "Defects", "matches"), Port("count", "Count", "number"), Port("total_area", "Total area", "number"),
        Port("defect_mask", "Defect mask", "image"), Port("diff", "Difference image", "image"),
    ]
    heavy = True

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        template = read_asset_image(ctx, "template")
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
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
            message=f"{count} defects" + (f", aligned dx={info.get('dx', 0):.1f} dy={info.get('dy', 0):.1f}" if info else ""),
            detail=info,
        )


class BarcodeTool(Tool):
    key = "barcode"
    label = "Barcode / QR"
    description = "Decodes QR codes and 1D barcodes (EAN, UPC, Code128 and friends)."
    category = "detect"
    icon = "QrCode"
    params = [
        Param("roi", "Region", kind="roi", shapes=["rect"], help_text="Leave blank for the whole image."),
        Param("types", "Type", kind="select", default="all", options=[{"value": "all", "label": "QR and 1D barcodes"}, {"value": "qr", "label": "QR only"}, {"value": "1d", "label": "1D barcodes only"}]),
        Param("expected", "Expected content", kind="text", default="", help_text="When set, the content must match exactly to take the match branch."),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [
        flow_out("found", "Found / matched", "ok"), flow_out("not_found", "Not found / no match", "critical"),
        Port("texts", "Contents", "list"), Port("count", "Count", "number"), Port("first", "First content", "string"), Port("codes", "Detail", "matches"),
    ]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
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
                    ctx.log("No barcode decoder is available in this environment", level="warn")
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
            message=(f"{len(texts)}: {', '.join(t[:30] for t in texts)}" if texts else "No code decoded") + ("" if matched or not texts else f" (expected {expected})"),
        )


class TextPresenceTool(Tool):
    key = "text_presence"
    label = "Print presence"
    description = "Whether the stroke ratio in the region (foreground after adaptive thresholding) reaches the threshold — the way to tell whether printing or a label is there."
    category = "detect"
    icon = "Type"
    params = [
        Param("roi", "Region", kind="roi", required=True, shapes=ROI_SHAPES),
        Param("polarity", "Text colour", kind="select", default="dark", options=[{"value": "dark", "label": "Dark text"}, {"value": "bright", "label": "Light text"}]),
        Param("block", "Adaptive block (odd)", kind="number", default=31, minimum=3, maximum=255, step=2, group="Advanced"),
        Param("c", "Adaptive constant C", kind="number", default=10, minimum=-100, maximum=100, group="Advanced"),
        Param("min_ratio", "Min stroke ratio", kind="range", default=0.03, minimum=0, maximum=1, step=0.005, teach=True),
        Param("max_ratio", "Max stroke ratio", kind="range", default=0.6, minimum=0, maximum=1, step=0.005, help_text="Above this it is treated as smearing or a solid block.", teach=True),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("present", "Yes", "ok"), flow_out("absent", "No", "critical"), Port("ratio", "Stroke ratio", "number"), Port("is_present", "Printed", "bool"), Port("mask", "Stroke mask", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        if region is None:
            raise ToolError("No region is set")
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
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
                      branch="present" if present else "absent", status="ok" if present else "ng", message=f"Stroke ratio {ratio * 100:.1f}% → {'present' if present else 'absent'}")


def _hex_to_bgr(value: str) -> tuple[int, int, int]:
    s = str(value or "").strip().lstrip("#")
    if len(s) != 6:
        raise ToolError(f"Malformed colour: {value!r}")
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        raise ToolError(f"Malformed colour: {value!r}") from None
    return b, g, r


class ColorCheckTool(Tool):
    key = "color_check"
    label = "Colour check"
    description = "Whether the distance between the region's mean colour and the target colour, in RGB or HSV, is within tolerance."
    category = "detect"
    icon = "Palette"
    params = [
        Param("roi", "Region", kind="roi", shapes=ROI_SHAPES, help_text="Leave blank for the whole image."),
        Param("color", "Target colour", kind="color", required=True, default="#ff0000"),
        Param("space", "Colour space", kind="select", default="rgb", options=[{"value": "rgb", "label": "RGB Euclidean distance (0-441)"}, {"value": "hsv", "label": "HSV (mostly hue)"}]),
        Param("tolerance", "Tolerance", kind="number", default=60, minimum=0, help_text="RGB uses Euclidean distance. HSV uses hue difference (0–180, weighted by saturation) plus saturation and value differences divided by four.", teach=True),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("match", "Match", "ok"), flow_out("mismatch", "No match", "critical"), Port("distance", "Distance", "number"), Port("is_match", "Match", "bool"), Port("mean_hex", "Mean colour", "string"), Port("mean_bgr", "Mean BGR", "list"), Port("mean_hsv", "Mean HSV", "list")]

    def execute(self, ctx: ToolContext) -> Result:
        image = ctx.require_image()
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        region = ctx.roi()
        c = crop(image, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
        mean = cv2.mean(np.ascontiguousarray(c.image), mask=c.mask)[:3]
        mean_bgr = np.array(mean, dtype=np.float32)
        target = np.array(_hex_to_bgr(ctx.param("color", "#ff0000")), dtype=np.float32)
        mean_hsv = cv2.cvtColor(mean_bgr.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2HSV).reshape(3).astype(float)
        if ctx.param("space", "rgb") == "hsv":
            tgt_hsv = cv2.cvtColor(target.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2HSV).reshape(3).astype(float)
            dh = abs(mean_hsv[0] - tgt_hsv[0])
            dh = min(dh, 180 - dh)
            # 灰／低飽和色的色相沒有意義：色相差以兩者較低的飽和度加權，灰目標對灰區域不會因色相亂數判不符
            dh *= min(mean_hsv[1], tgt_hsv[1]) / 255.0
            distance = float(math.sqrt(dh**2 + ((mean_hsv[1] - tgt_hsv[1]) / 4) ** 2 + ((mean_hsv[2] - tgt_hsv[2]) / 4) ** 2))
        else:
            distance = float(np.linalg.norm(mean_bgr - target))
        match = distance <= ctx.number("tolerance", 60)
        mean_hex = "#{:02x}{:02x}{:02x}".format(int(round(mean[2])), int(round(mean[1])), int(round(mean[0])))
        overlays = [region_overlay(region, color="#22c55e" if match else "#ef4444", label=f"{mean_hex} d={distance:.1f}")] if region else []
        return Result(
            outputs={"distance": distance, "is_match": match, "mean_hex": mean_hex, "mean_bgr": [round(float(v), 1) for v in mean], "mean_hsv": [round(float(v), 1) for v in mean_hsv]},
            overlays=overlays, branch="match" if match else "mismatch", status="ok" if match else "ng", message=f"Mean {mean_hex}, distance {distance:.1f} → {'match' if match else 'no match'}",
        )


class EdgeDensityTool(Tool):
    key = "edge_density"
    label = "Edge density"
    description = "The ratio of Canny edge pixels in the region. A scratch or smear on a smooth surface pushes it up."
    category = "detect"
    icon = "Activity"
    params = [
        Param("roi", "Region", kind="roi", shapes=ROI_SHAPES, help_text="Leave blank for the whole image."),
        Param("canny_low", "Canny low", kind="number", default=50, minimum=0, maximum=500),
        Param("canny_high", "Canny high", kind="number", default=150, minimum=0, maximum=500),
        Param("blur", "Pre-blur kernel", kind="number", default=3, minimum=0, maximum=31, group="Advanced"),
        Param("max_ratio", "Max passing ratio", kind="range", default=0.05, minimum=0, maximum=1, step=0.001, teach=True),
    ]
    inputs = [Port("image", "Image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("ok", "Pass", "ok"), flow_out("ng", "Over limit", "critical"), Port("ratio", "Edge ratio", "number"), Port("edge_pixels", "Edge pixels", "number"), Port("edges", "Edge image", "image")]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
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
                      branch="ok" if ok else "ng", status="ok" if ok else "ng", message=f"Edge ratio {ratio * 100:.2f}%")


class PixelCountTool(Tool):
    key = "pixel_count"
    label = "Pixel count"
    description = "Foreground pixel count and ratio inside the region, from a mask or from grayscale thresholded at the given level."
    category = "detect"
    icon = "Grid3x3"
    params = [
        Param("roi", "Region", kind="roi", shapes=ROI_SHAPES, help_text="Leave blank for the whole image."),
        Param("threshold", "Threshold", kind="number", default=128, minimum=0, maximum=255, help_text="Pixels at or above this grey level are foreground; leave the default when the input is already a 0/255 mask."),
        Param("min_count", "Min passing pixels", kind="number", default=0, minimum=0, teach=True),
        Param("max_count", "Max passing pixels", kind="number", default=0, minimum=0, help_text="0 means no limit.", teach=True),
    ]
    inputs = [Port("image", "Mask / image", "image"), Port("roi", "Region (dynamic)", "region", required=False)]
    outputs = [flow_out("ok", "Pass", "ok"), flow_out("ng", "Fail", "critical"), Port("count", "Pixel count", "number"), Port("ratio", "Scale", "number"), Port("total", "Region pixels", "number")]

    def execute(self, ctx: ToolContext) -> Result:
        gray = to_gray(ctx.require_image())
        region = ctx.roi()
        c = crop(gray, region)
        if c.image.size == 0:
            raise ToolError("The region falls outside the image")
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
                      branch="ok" if ok else "ng", status="ok" if ok else "ng", message=f"{n} px ({ratio * 100:.2f}%)")


TOOLS = [BlobTool(), DefectDiffTool(), BarcodeTool(), TextPresenceTool(), ColorCheckTool(), EdgeDensityTool(), PixelCountTool()]
