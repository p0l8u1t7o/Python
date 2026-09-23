"""
判定彙整：各檢測模組依配方判定規格判定，平台再彙整為影像判定 (規劃書第 6 節)。

影像判定優先順序：
  影像品質不足 (品質閘門不合格) > 不合格 > 需複判 > 合格 > 未判定
其他規則：
  - 模組執行錯誤或無法判定 → 需複判
  - 非原始影像 (8-bit 轉存) → 最多為需複判 (不輸出正式合格／不合格)
  - 未驗證的檢測模組 → 該模組判定最多為需複判 (規劃書 PLAN-002 第 3.6 節)
  - 所有模組都未設定判定規格 → 未判定 (只提供量測值)
"""
from . import plugin
from .plugin import (JUDGE_FAIL, JUDGE_NOT_JUDGED, JUDGE_PASS, JUDGE_QUALITY, JUDGE_REVIEW, STATUS_ERROR,
                     STATUS_NO_RESULT)
from .quality import FAIL as QUALITY_FAIL

_RANK = {JUDGE_NOT_JUDGED: 0, JUDGE_PASS: 1, JUDGE_REVIEW: 2, JUDGE_FAIL: 3, JUDGE_QUALITY: 4}


def judge_modules(result, recipe):
    """對每個模組結果填入 judgment 與 judgment_reasons"""
    specs = {m.module_id: m.judgment for m in recipe.modules}
    px = recipe.pixel_size_um
    for mr in result.modules:
        if mr.status == STATUS_ERROR:
            mr.judgment, mr.judgment_reasons = JUDGE_REVIEW, ["module_error"]
            continue
        if mr.status == STATUS_NO_RESULT:
            mr.judgment, mr.judgment_reasons = JUDGE_REVIEW, list(mr.reasons) or ["no_result"]
            continue
        cls = plugin.get(mr.module_id)
        spec = cls.resolve_judgment(specs.get(mr.module_id))
        level, reasons = cls().judge(mr, spec, (mr.summary or {}).get("pixel_size_um") or px)
        mr.judgment, mr.judgment_reasons = level, list(reasons)


def overall(result):
    """回傳 (影像判定, 原因清單)"""
    if result.quality["level"] == QUALITY_FAIL:
        return JUDGE_QUALITY, ["image_quality_insufficient"]
    level, reasons = JUDGE_NOT_JUDGED, []
    unvalidated = set(getattr(result, "unvalidated_modules", None) or ())
    for mr in result.modules:
        if mr.module_id in unvalidated and mr.judgment in (JUDGE_PASS, JUDGE_FAIL):
            mr.judgment_reasons = list(mr.judgment_reasons) + ["module_unvalidated"]
            mr.judgment = JUDGE_REVIEW
        if _RANK[mr.judgment] > _RANK[level]:
            level = mr.judgment
        if mr.judgment in (JUDGE_FAIL, JUDGE_REVIEW):
            reasons += [f"{mr.module_id}.{r}" for r in mr.judgment_reasons]
    if result.reference_only and level in (JUDGE_PASS, JUDGE_FAIL):
        reasons.append("non_raw_image")
        level = JUDGE_REVIEW
    return level, reasons
