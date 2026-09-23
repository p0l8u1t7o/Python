"""
範例檢測模組：亮點計數 (Blob Count)

示範檢測模組的完整結構 (模組開發指南 docs/module-development-guide.md)：
  - 模組宣告、參數結構、判定規格、品質規則、疊圖樣式、物件排行表、顯示文字
  - run()：只使用 ctx 提供的輸入 (吸收量影像、像素尺寸、檢測區域)，回傳統一結果格式
  - judge()：依配方判定規格判定
量測內容：吸收量影像中半徑範圍內的亮圓 (例如焊球) 數量與直徑。
門檻以影像自身的響應分布為基準，不使用絕對灰階 (開發規範第 1 條)。
"""
import math

import cv2
import numpy as np

from xrayvision.core.io import KIND_RAW16, KIND_RGB8
from xrayvision.core.plugin import (JUDGE_FAIL, JUDGE_NOT_JUDGED, JUDGE_PASS, STATUS_NO_RESULT, STATUS_OK,
                                    Finding, InspectionModule, ModuleResult, Param)
from xrayvision.core.quality import QualityRule
from xrayvision.core.units import add_um

_KINDS = (KIND_RAW16, KIND_RGB8)


class BlobCount(InspectionModule):
    module_id = "blob_count"
    version = "1.0.0"
    names = {"zh-TW": "亮點計數（範例）", "en": "Blob Count (Example)"}
    supported_kinds = _KINDS
    params = (
        Param("radius_min_px", "float", 20.0, {"zh-TW": "半徑搜尋下限", "en": "Radius search minimum"},
              min=3.0, max=500.0, unit="px"),
        Param("radius_max_px", "float", 100.0, {"zh-TW": "半徑搜尋上限", "en": "Radius search maximum"},
              min=3.0, max=500.0, unit="px"),
        Param("threshold", "float", 0.3,
              {"zh-TW": "偵測門檻（最強響應的比例）", "en": "Detection threshold (ratio of strongest response)"},
              min=0.05, max=0.9, unit="ratio", advanced=True),
    )
    judgment_params = (
        Param("count_min", "int", None, {"zh-TW": "數量下限", "en": "Minimum count"}, min=0, max=100000),
        Param("count_max", "int", None, {"zh-TW": "數量上限", "en": "Maximum count"}, min=0, max=100000),
    )
    quality_rules = (
        QualityRule("blob_count.found", warn_below=1, fail_below=1, kinds=_KINDS),
    )
    overlay_styles = {"blob": {"color": (0, 200, 255), "thickness": 2}}
    finding_table = dict(category="blob", sort="diameter_px", limit=10, columns=("diameter_px",))
    repeat_anchor = "blob"
    repeat_keys = ("diameter_px",)
    translations = {
        "zh-TW": {"module.blob_count": "亮點計數（範例）", "metric.blob_count.found": "偵測到的亮點數",
                  "finding.blob": "亮點", "measure.diameter_px": "直徑 (px)", "measure.diameter_um": "直徑 (µm)",
                  "summary.count": "數量", "summary.mean_diameter_px": "平均直徑 (px)",
                  "reason.count_below_min": "數量低於下限", "reason.count_above_max": "數量高於上限",
                  "reason.no_blobs_found": "未偵測到亮點", "ui.layer.blob": "亮點"},
        "en": {"module.blob_count": "Blob Count (Example)", "metric.blob_count.found": "Blobs found",
               "finding.blob": "Blob", "measure.diameter_px": "Diameter (px)", "measure.diameter_um": "Diameter (µm)",
               "summary.count": "Count", "summary.mean_diameter_px": "Mean diameter (px)",
               "reason.count_below_min": "Count below the minimum", "reason.count_above_max": "Count above the maximum",
               "reason.no_blobs_found": "No blobs found", "ui.layer.blob": "Blobs"},
    }

    def run(self, ctx, params):
        A = ctx.prepared.absorption.astype(np.float32)
        lo, hi = sorted((params["radius_min_px"], params["radius_max_px"]))
        blobs = [b for b in detect(A, lo, hi, params["threshold"]) if ctx.in_region(b[0], b[1])]  # 區域外不量測
        result = ModuleResult(module_id=self.module_id, module_version=self.version, status=STATUS_OK,
                              params=dict(params))
        for i, (x, y, r) in enumerate(blobs, 1):
            meas = add_um(dict(diameter_px=2 * r), ctx.pixel_size_um)
            result.findings.append(Finding(id=i, category="blob", measurements=meas,
                                           geometry={"blob": dict(type="circle", x=x, y=y, r=r)}))
        result.metrics = {f"{self.module_id}.found": len(blobs)}
        result.summary = dict(count=len(blobs),
                              mean_diameter_px=float(np.mean([2 * b[2] for b in blobs])) if blobs else 0.0)
        if not blobs:
            result.status = STATUS_NO_RESULT
            result.reasons.append("no_blobs_found")
        return result

    def judge(self, result, spec, pixel_size_um=None):
        lo, hi = spec.get("count_min"), spec.get("count_max")
        if lo is None and hi is None:
            return JUDGE_NOT_JUDGED, []
        n = (result.summary or {}).get("count", 0)
        if lo is not None and n < lo:
            return JUDGE_FAIL, ["count_below_min"]
        if hi is not None and n > hi:
            return JUDGE_FAIL, ["count_above_max"]
        return JUDGE_PASS, []


def detect(A, r_min, r_max, rel):
    """尺度空間 LoG：每個像素取最佳尺度，取局部極大；門檻為最強響應的 rel 倍 (相對門檻)"""
    best = np.full(A.shape, -np.inf, np.float32)
    arg = np.zeros(A.shape, np.float32)
    for r in np.geomspace(r_min, r_max, 12):
        s = r / math.sqrt(2)
        lap = -cv2.Laplacian(cv2.GaussianBlur(A, (0, 0), s), cv2.CV_32F, ksize=3) * s * s
        m = lap > best
        best[m], arg[m] = lap[m], r
    k = max(3, int(r_min)) | 1
    peaks = np.argwhere((best >= cv2.dilate(best, np.ones((k, k), np.uint8)) - 1e-12) & (best > 0))
    if not len(peaks):
        return []
    resp = best[peaks[:, 0], peaks[:, 1]]
    out = []
    for i in np.argsort(-resp):
        if resp[i] < rel * resp.max():
            break
        y, x = peaks[i]
        r = float(arg[y, x])
        if all(math.hypot(x - bx, y - by) > 0.8 * max(r, br) for bx, by, br in out):
            out.append((float(x), float(y), r))
    return out
