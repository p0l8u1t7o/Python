"""提示詞＋ROI 形狀＋影像特徵 → 檢測意圖（規則引擎；無外部依賴、完全離線）。

意圖是封閉集合：synth.py 對每種意圖都有一個合成器。解析順序＝特異性排序
（條碼／角度這種明確詞優先，泛用的「有無」殿後）。中英關鍵詞都收。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

INTENT_KINDS = (
    "barcode", "count", "diameter", "width", "angle",
    "defect", "color_match", "color_presence", "presence", "brightness", "generic",
)

_CN_NUM = {"一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


@dataclass
class Intent:
    kind: str = "generic"
    #: 期望數量（計數意圖；None = 只回報數字不判定）。
    expected_count: int | None = None
    #: 標稱值與公差（量測意圖；單位依 unit）。
    nominal: float | None = None
    tol: float | None = None
    unit: str = "px"
    #: mm/px（提示詞給了實距換算才有）。
    mm_per_px: float | None = None
    #: 顏色比對的目標色（十六進位；預設取 ROI 主色）。
    color_hex: str = ""
    #: 解析過程的說明（rationale 的素材）。
    notes: list[str] = field(default_factory=list)


def _find_number(text: str, patterns: list[str]) -> float | None:
    for p in patterns:
        m = re.search(p, text)
        if m:
            return float(m.group(1))
    return None


def _expected_count(text: str) -> int | None:
    m = re.search(r"(\d+)\s*[個个顆颗孔洞支根件]", text)
    if m:
        return int(m.group(1))
    m = re.search(r"([一二兩两三四五六七八九十])\s*[個个顆颗孔洞支根件]", text)
    if m:
        return _CN_NUM.get(m.group(1))
    m = re.search(r"(?:count|expect)\D{0,8}(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def parse(prompt: str, regions: list[dict[str, Any]], analysis: dict[str, Any]) -> Intent:
    """依提示詞（優先）＋ROI 形狀＋特徵決定意圖與參數。"""
    text = (prompt or "").strip()
    low = text.lower()
    intent = Intent()
    region_infos = analysis.get("regions") or []
    first = regions[0].get("region") if regions else None
    shape = str(first.get("shape", "")) if first else ""

    # 公差與換算（各意圖共用）
    m = re.search(r"[±\+\-]\s*(\d+(?:\.\d+)?)\s*(mm|毫米|公厘|px|像素)?", text)
    if m:
        intent.tol = float(m.group(1))
        if m.group(2) in ("mm", "毫米", "公厘"):
            intent.unit = "mm"
    nominal = _find_number(text, [r"(?:直徑|直径|孔徑|孔径|寬度|宽度|標稱|标称|應為|应为|diameter|width)\D{0,6}(\d+(?:\.\d+)?)"])
    if nominal is not None:
        intent.nominal = nominal
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm|毫米|公厘)\s*[/＝=]\s*(\d+(?:\.\d+)?)\s*(?:px|像素)", text)
    if m:
        intent.mm_per_px = float(m.group(1)) / float(m.group(2))
        intent.unit = "mm"
    elif re.search(r"mm|毫米|公厘", text) and intent.nominal is not None:
        intent.unit = "mm"

    # --- 特異性排序的意圖判斷 ---
    if _has(low, "條碼", "条码", "二維碼", "二维码", "qr", "barcode", "讀碼", "读码", "掃碼", "扫码"):
        intent.kind = "barcode"
        intent.notes.append("提示詞含讀碼關鍵詞")
        return intent
    if _has(low, "角度", "夾角", "夹角", "angle"):
        intent.kind = "angle"
        intent.notes.append("提示詞含角度關鍵詞；需要兩個 ROI 各框一條邊")
        return intent
    if _has(low, "直徑", "直径", "孔徑", "孔径", "半徑", "半径", "diameter", "圓孔", "圆孔") or (
        _has(low, "量", "尺寸", "measure") and shape in ("circle", "annulus")
    ):
        intent.kind = "diameter"
        intent.notes.append("量測圓孔直徑")
        return intent
    if _has(low, "寬度", "宽度", "寬", "宽", "厚度", "間距", "间距", "width", "gap", "thickness") and not _has(low, "邊緣密度"):
        intent.kind = "width"
        intent.notes.append("以卡尺量邊對間距")
        return intent
    if _has(low, "亮度", "曝光", "太暗", "太亮", "brightness", "exposure"):
        intent.kind = "brightness"
        intent.notes.append("亮度守門")
        return intent
    count = _expected_count(text)
    if count is not None or _has(low, "幾個", "几个", "數量", "数量", "計數", "计数", "count", "數一", "数一"):
        intent.kind = "count"
        intent.expected_count = count
        intent.notes.append(f"計數意圖（期望 {count} 個）" if count is not None else "計數意圖（只回報數量）")
        return intent
    if _has(low, "刮痕", "瑕疵", "缺陷", "髒污", "脏污", "污漬", "污渍", "破損", "破损", "異物", "异物", "defect", "scratch", "凹痕"):
        intent.kind = "defect"
        intent.notes.append("外觀缺陷檢測")
        return intent
    if _has(low, "顏色", "颜色", "色差", "偏色", "color") and _has(low, "對", "对", "正確", "正确", "一致", "符合", "match", "check", "比"):
        intent.kind = "color_match"
        intent.notes.append("顏色比對（目標色取 ROI 主色）")
        if region_infos and not region_infos[0].get("empty"):
            intent.color_hex = region_infos[0]["dominant"]["hex"]
        return intent
    if _has(low, "顏色", "颜色", "color") or (_has(low, "有沒有", "有没有", "有無", "有无", "是否", "缺料", "presence", "missing") and region_infos and not region_infos[0].get("empty") and region_infos[0]["dominant"]["s"] > 60):
        intent.kind = "color_presence"
        intent.notes.append("以顏色範圍判斷有無")
        if region_infos and not region_infos[0].get("empty"):
            intent.color_hex = region_infos[0]["dominant"]["hex"]
        return intent
    if _has(low, "有沒有", "有没有", "有無", "有无", "是否", "缺料", "在不在", "presence", "missing", "present"):
        intent.kind = "presence"
        intent.notes.append("以粒子有無判斷")
        return intent

    # 沒有明確關鍵詞：用 ROI 特徵猜
    if region_infos and not region_infos[0].get("empty"):
        r0 = region_infos[0]
        if shape in ("circle", "annulus") or r0["circle"]["found"]:
            intent.kind = "diameter"
            intent.notes.append("提示詞不明確；ROI 內有明顯圓形 → 量直徑")
            return intent
        dark = r0["blobs"]["dark"]["count"]
        if dark >= 2:
            intent.kind = "count"
            intent.notes.append(f"提示詞不明確；ROI 內有 {dark} 顆暗粒子 → 計數")
            return intent
    intent.kind = "generic"
    intent.notes.append("提示詞不明確；先給量測資訊流程（統計／直方圖／邊緣密度），請補充描述後重新生成")
    return intent
