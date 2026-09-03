"""提示詞＋ROI 形狀＋影像特徵 → 檢測意圖（規則引擎；無外部依賴、完全離線）。

意圖是封閉集合：synth.py 對每種意圖都有一個合成器。解析順序＝特異性排序
（條碼／角度這種明確詞優先，泛用的「有無」殿後）。中英關鍵詞都收。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

INTENT_KINDS = (
    "barcode", "count", "diameter", "width", "angle", "golden",
    "defect", "color_match", "color_presence", "presence", "brightness", "generic",
    "text", "distance", "template_presence",
)

_GOOD_WORDS = ("好品", "良品", "ok 品", "ok品", "正常品", "正常", "合格", "golden", "good", "reference", "範本", "范本")
_BAD_WORDS = ("壞品", "坏品", "不良", "ng 品", "ng品", "瑕疵品", "缺陷品", "異常", "异常", "不合格", "bad", "defective")

#: 定位標記 ROI 的提示詞（這個 ROI 不參與檢測，只當定位範本）。
_LOCATOR_WORDS = ("定位", "標記", "标记", "marker", "fiducial", "anchor", "locator")

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
    #: 目標相對背景的極性（dark／bright）；None 交給特徵自動判斷。
    polarity: str | None = None
    #: 計數目標是圓形（孔／圓）：blob 加圓形度下限，排除線段與雜訊。
    round_target: bool = False
    #: 讀碼期望內容（barcode.expected）；亮度可接受範圍（brightness）。
    expected_text: str = ""
    range_low: float | None = None
    range_high: float | None = None
    #: 良品比對：哪個 ROI 是好品（當範本）、哪個是壞品（示範缺陷）；索引以 0 起算。
    good_roi: int | None = None
    bad_roi: int | None = None
    #: 工件位置會變：在流程前面包「範本比對 → 定位補正 → ROI 跟隨」；locator_roi 是當定位範本的 ROI（提示填「定位」）。
    locate: bool = False
    locator_roi: int | None = None
    #: 圖案有無（範本比對）：哪個 ROI 裁成範本。
    template_roi: int | None = None
    #: 解析過程的說明（rationale 的素材）。
    notes: list[str] = field(default_factory=list)


def _roi_refs(text: str, tag_words: tuple[str, ...]) -> list[int]:
    """找「ROI01 是好品」這種指涉：回傳被 tag_words 修飾的 ROI 索引（0 起算）。"""
    out: list[int] = []
    for m in re.finditer(r"roi\s*0*(\d+)", text, re.IGNORECASE):
        idx = int(m.group(1)) - 1
        window = text[m.end():m.end() + 14].lower()
        if any(w in window for w in tag_words):
            out.append(idx)
    return out


def _golden_roles(text: str, regions: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """好品／壞品 ROI 的角色：ROI 自己的 hint 優先，其次提示詞裡的「ROI01 是好品」。"""
    good = bad = None
    for i, r in enumerate(regions):
        hint = str(r.get("hint") or "").lower()
        if any(w in hint for w in _LOCATOR_WORDS):
            continue
        if good is None and any(w in hint for w in _GOOD_WORDS):
            good = i
        elif bad is None and any(w in hint for w in _BAD_WORDS):
            bad = i
    low = text.lower()
    if good is None:
        refs = _roi_refs(low, _GOOD_WORDS)
        good = refs[0] if refs else None
    if bad is None:
        refs = _roi_refs(low, _BAD_WORDS)
        bad = refs[0] if refs else None
    return good, bad


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
    nominal = _find_number(text, [r"(?:直徑|直径|孔徑|孔径|寬度|宽度|標稱|标称|應為|应为|夾角|夹角|角度|距離|距离|孔距|中心距|diameter|width|angle|distance)\D{0,6}(\d+(?:\.\d+)?)"])
    if nominal is not None:
        intent.nominal = nominal
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm|毫米|公厘)\s*[/＝=]\s*(\d+(?:\.\d+)?)\s*(?:px|像素)", text)
    if m:
        intent.mm_per_px = float(m.group(1)) / float(m.group(2))
        intent.unit = "mm"
    elif re.search(r"mm|毫米|公厘", text) and intent.nominal is not None:
        intent.unit = "mm"

    if _has(low, "比背景暗", "暗色", "黑色目標", "darker", "dark target"):
        intent.polarity = "dark"
    elif _has(low, "比背景亮", "亮色", "白色目標", "brighter", "bright target"):
        intent.polarity = "bright"

    # 定位：提示詞說位置會變，或有 ROI 標成「定位」
    for i, r in enumerate(regions):
        if any(w in str(r.get("hint") or "").lower() for w in _LOCATOR_WORDS):
            intent.locator_roi = i
            intent.locate = True
            break
    if _has(low, "定位", "位置會變", "位置会变", "會移動", "会移动", "位移", "跟隨", "跟随", "位置不固定", "位置不一", "locate", "fixture", "alignment"):
        intent.locate = True
    work_regions = [r for i, r in enumerate(regions) if i != intent.locator_roi]
    if intent.locator_roi is not None:
        first = work_regions[0].get("region") if work_regions else None
        shape = str(first.get("shape", "")) if first else ""
        region_infos = [row for i, row in enumerate(region_infos) if i != intent.locator_roi]

    # --- 特異性排序的意圖判斷 ---
    good, bad = _golden_roles(text, regions)
    wants_golden = _has(low, "良品比對", "良品比对", "用良品", "跟良品", "與良品", "与良品", "golden")
    if wants_golden or (good is not None and (bad is not None or _has(low, *_BAD_WORDS) or _has(low, "比對", "比对", "差異", "差异", "compare"))):
        intent.kind = "golden"
        intent.good_roi, intent.bad_roi = good, bad
        intent.notes.append(("良品比對：" + (f"ROI{good + 1:02d} 當好品範本" if good is not None else "尚未指定好品 ROI")) + (f"、ROI{bad + 1:02d} 是壞品示範" if bad is not None else ""))
        return intent
    if _has(low, "條碼", "条码", "二維碼", "二维码", "qr", "barcode", "讀碼", "读码", "掃碼", "扫码"):
        intent.kind = "barcode"
        intent.notes.append("提示詞含讀碼關鍵詞")
        m = re.search(r"(?:期望內容|期望内容|內容應為|内容应为|內容是|内容是|expected)\s*[:：]?\s*([^\s，,。；;]+)", text)
        if m:
            intent.expected_text = m.group(1)
        return intent
    if _has(low, "文字", "印字", "字有", "有字", "沒有字", "没有字", "序號", "序号", "字元", "字符", "刻字", "噴印", "喷印", "text", "print"):
        intent.kind = "text"
        intent.notes.append("印字有無（筆劃密度）")
        return intent
    circle_rois = [r for r in work_regions if str((r.get("region") or {}).get("shape", "")) in ("circle", "annulus")]
    if _has(low, "距離", "距离", "孔距", "中心距", "distance", "pitch") and (len(circle_rois) >= 2 or _has(low, "孔", "圓", "圆", "圓心", "圆心", "hole", "circle", "center")):
        intent.kind = "distance"
        intent.notes.append("兩孔中心距：兩個 ROI 各找一個圓再量距離")
        return intent
    if _has(low, "範本", "范本", "樣板", "样板", "圖案", "图案", "圖樣", "图样", "標誌", "标志", "印記", "印记", "符號", "符号", "pattern", "template", "logo") and work_regions:
        intent.kind = "template_presence"
        intent.template_roi = next((i for i, r in enumerate(regions) if i != intent.locator_roi), None)
        intent.notes.append("圖案有無：ROI 裁成範本做比對")
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
        m = re.search(r"(\d+(?:\.\d+)?)\s*[~～－到至]\s*(\d+(?:\.\d+)?)", text) or re.search(r"(?:範圍|范围|range)\D{0,4}(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", text)
        if m:
            intent.range_low, intent.range_high = float(m.group(1)), float(m.group(2))
        return intent
    count = _expected_count(text)
    if count is not None or _has(low, "幾個", "几个", "數量", "数量", "計數", "计数", "count", "數一", "数一"):
        intent.kind = "count"
        intent.expected_count = count
        intent.round_target = _has(low, "孔", "圓", "圆", "hole", "circle", "圓形", "圆形")
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
