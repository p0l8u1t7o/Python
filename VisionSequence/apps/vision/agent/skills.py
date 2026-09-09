"""AI 代理技能（skills）：讓 LLM 快速理解平台規則、設計原則與每個工具怎麼用。

skills/ 目錄：
- platform.md：平台規則（graph 格式、埠、控制分支、ROI、收尾、禁止事項）——system 的固定段。
- design.md：流程設計原則與工具選用表——system 的固定段。
- tools.md：每個工具的人工要領（`## <type>` 分段）；沒寫到的工具用自動骨架。
每個工具的完整技能＝自動骨架（label／說明／參數表／埠表，從 Tool 定義生成）＋人工要領。

組裝策略：system 段只放穩定內容（規則＋原則＋全工具精簡目錄，可快取）；本次相關工具的完整技能
放進 user 訊息（依提示詞關鍵詞、ROI 形狀、既有 graph 的工具挑選），避免 61 個工具全文塞爆。
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from apps.vision.tools import base as tools

log = logging.getLogger(__name__)
SKILL_DIR = Path(__file__).parent / "skills"
GUIDE_KEYS = ("platform", "design", "agentic", "imaging")
GUIDE_LABELS = {"platform": "平台規則", "design": "流程設計原則", "agentic": "代理工作方式", "imaging": "取像與打光"}

#: 自訂技能（AgentSkill）改變時 +1；build_system(epoch) 以它當快取鍵，system 段才會重組。
_epoch = 0


def epoch() -> int:
    return _epoch


def invalidate() -> None:
    global _epoch
    _epoch += 1


def custom_texts(key: str, user: Any = None) -> tuple[str, str]:
    """(站點補充, 個人補充) 的 markdown；沒有就空字串。DB 讀不到（尚未遷移）時回空。"""
    try:
        from apps.vision.models import AgentSkill

        site = AgentSkill.objects.filter(key=key, scope="site").values_list("markdown", flat=True).first() or ""
        mine = ""
        if user is not None and getattr(user, "pk", None):
            mine = AgentSkill.objects.filter(key=key, scope="user", owner=user).values_list("markdown", flat=True).first() or ""
        return str(site), str(mine)
    except Exception:  # noqa: BLE001 - 記憶功能不可用時退回內建技能
        return "", ""


def with_custom(base: str, key: str, user: Any = None, *, include_user: bool = True) -> str:
    site, mine = custom_texts(key, user)
    parts = [base.rstrip()]
    if site:
        parts.append("## 站點補充\n\n" + site.strip())
    if include_user and mine:
        parts.append("## 個人補充\n\n" + mine.strip())
    return "\n\n".join(parts) + "\n"

#: 永遠帶完整技能的核心工具。
CORE_TOOLS = ("image_source", "grayscale", "threshold", "blob", "if_number", "in_range", "judge", "output", "draw_result", "note")

#: 提示詞關鍵詞 → 相關工具（中英）。
KEYWORD_TOOLS: dict[str, tuple[str, ...]] = {
    "直徑|直径|孔徑|孔径|半徑|半径|圓|圆|circle|diameter|round": ("find_circle", "hough_circles", "fit_ellipse", "fit_arc", "formula", "calibration", "tolerance_judge", "distance", "concentricity"),
    "寬|宽|厚|間距|间距|距離|距离|width|gap|thickness|distance": ("caliper", "wall_thickness", "find_line", "distance", "calibration", "tolerance_judge"),
    "角度|夾角|夹角|斜|倒角|angle|chamfer": ("find_line", "angle", "chamfer_angle", "geometry"),
    "幾個|几个|數量|数量|計數|计数|count|個|个|顆|颗": ("blob", "hough_circles", "count_list", "morphology", "blur"),
    "刮痕|瑕疵|缺陷|髒|脏|污|破損|破损|異物|异物|defect|scratch|良品|好品|壞品|坏品": ("defect_diff", "defect_stat", "fft_filter", "blur", "morphology", "blob", "apply_mask", "edge_density", "template_match"),
    "統計範本|统计范本|統計比對|统计比对|多張良品|多张良品|標準差|标准差|sigma|statistical|stat template": ("defect_stat", "if_number"),
    "異常|异常|只有良品|沒有壞品|没有坏品|沒看過|没看过|無監督|无监督|anomaly|unsupervised|patchcore|novelty": ("dl_anomaly", "if_number"),
    "顏色|颜色|色差|偏色|color|紅|红|綠|绿|藍|蓝|黃|黄": ("color_check", "color_stats", "color_range", "pixel_count", "color_convert"),
    "有沒有|有没有|有無|有无|是否|缺料|presence|missing": ("blob", "pixel_count", "color_range", "template_match", "intensity"),
    "條碼|条码|二維碼|二维码|qr|barcode|讀碼|读码|標籤|标签": ("barcode", "warp_perspective", "text_presence"),
    "文字|序號|序号|印字|text": ("ocr_read", "ocv_verify", "text_presence", "warp_perspective"),
    "讀字|读字|辨識|识别|日期碼|日期码|批號|批号|料號|料号|字元|字符|噴印|喷印|打標|打标|ocr|ocv|lot|date code|serial": ("ocr_read", "ocv_verify", "warp_perspective"),
    "亮度|曝光|太暗|太亮|brightness|exposure": ("intensity", "histogram", "lut", "resize"),
    "定位|位移|偏移|範本|范本|template|align|跟隨|跟随": ("shape_match", "template_match", "shape_align", "fixture_roi"),
    "形狀比對|形状比对|幾何比對|几何比对|任意角度|旋轉件|旋转件|遮擋|遮挡|多件|上下料|shape match|geometric": ("shape_match", "shape_align", "fixture_roi"),
    "紋|纹|網點|网点|週期|周期|texture|pattern": ("fft_filter", "threshold", "blob"),
    "斜貼|斜贴|透視|透视|拉正|perspective|warp": ("warp_perspective",),
    "剖面|profile|溝|沟": ("line_profile",),
    "對焦|对焦|清晰|模糊|失焦|焦距|focus|blur|sharp|defocus": ("sharpness", "in_range", "intensity"),
    "mm|毫米|公厘|公差|標稱|标称|tolerance": ("calibration", "tolerance_judge", "bool_logic"),
    "打光不均|光不均|漸暈|渐晕|暗角|角落暗|陰影校正|阴影校正|平場|平场|白板|shading|flat field|flat-field|vignett|uneven light": ("shading_correct", "threshold", "blob"),
    "排除|挖掉|挖除|扣掉|扣除|避開|避开|遮掉|不算|組合區|组合区|多重|exclude|exclusion|subtract|combine|mask out|ignore area": ("region_from_shape", "region_combine"),
    "圓周缺口|圆周缺口|崩邊|崩边|毛刺|徑向跳動|径向跳动|跳動|跳动|真圓|真圆|圓度|圆度|圓形卡尺|圆形卡尺|runout|run-out|circular caliper|rim": ("circular_caliper", "profile_defect", "if_number", "tolerance_judge"),
    "輪廓|轮廓|外形|凸|缺角|崩邊|崩边|崩角|毛邊|毛边|contour|outline|silhouette|convex|chip|notch|hu": ("contour_find", "contour_filter", "contour_geometry", "contour_match", "threshold", "if_number"),
    "條碼品質|条码品质|條碼等級|条码等级|分級|分级|grading|grade|驗證器|验证器|verifier|iso 15415|iso 15416|15415|15416|dpm|印刷品質|印刷品质|列印品質|打印品质": ("barcode_grade", "barcode", "judge"),
    "形位|直線度|直线度|平面度|真圓度|真圆度|圓度|圆度|平行度|垂直度|傾斜度|倾斜度|公差帶|公差带|最小區域|最小区域|gd&t|gdt|straightness|flatness|roundness|parallelism|perpendicularity|angularity|iso 1101": ("gdt_measure", "find_line", "circular_caliper", "contour_find", "contour_filter"),
    "光度立體|光度立体|多光源|四燈|四灯|四方向|打光合成|刻印|浮凸|壓印|压印|凹凸|凹坑|法向|photometric|stereo|emboss|engrav|dent|bump|relief": ("photometric_stereo", "crop", "threshold", "blob", "ocr_read"),
    "圓周|圆周|齒|齿|螺紋|螺纹|環形|环形|極座標|极坐标|展開|展开|polar|unwrap|gear|thread|o-ring|滾珠|滚珠": ("polar_unwrap", "polar_restore", "threshold", "blob", "if_number"),
}

#: 意圖 → 工具（規則引擎解析出意圖時用）。
INTENT_TOOLS: dict[str, tuple[str, ...]] = {
    "count": ("blur", "morphology", "blob"),
    "diameter": ("find_circle", "formula", "calibration", "tolerance_judge", "fit_arc", "fit_ellipse"),
    "width": ("caliper", "tolerance_judge"),
    "angle": ("find_line", "angle", "geometry", "chamfer_angle"),
    "golden": ("defect_diff", "defect_stat"),
    "defect": ("blur", "morphology", "apply_mask", "fft_filter", "defect_diff", "dl_anomaly"),
    "color_match": ("color_check", "color_stats"),
    "color_presence": ("color_range", "pixel_count"),
    "presence": ("blob", "intensity"),
    "brightness": ("intensity", "histogram"),
    "barcode": ("barcode", "warp_perspective", "text_presence"),
    "generic": ("intensity", "histogram", "edge_density"),
    "text": ("ocr_read", "ocv_verify", "text_presence"),
    "distance": ("find_circle", "distance", "calibration", "tolerance_judge"),
    "template_presence": ("template_match", "shape_match"),
    "focus": ("sharpness", "in_range"),
    "roundness": ("find_circle", "gdt_measure", "circular_caliper", "tolerance_judge"),
}

_ROI_TOOLS = {
    "circle": ("find_circle", "fit_ellipse"), "annulus": ("find_circle", "fit_arc"),
    "line": ("line_profile", "wall_thickness"), "polygon": ("warp_perspective",),
    "rotated_rect": ("caliper", "find_line"), "polyline": ("line_profile",),
}


@lru_cache(maxsize=1)
def platform_text() -> str:
    return (SKILL_DIR / "platform.md").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def design_text() -> str:
    return (SKILL_DIR / "design.md").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def agentic_text() -> str:
    return (SKILL_DIR / "agentic.md").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def imaging_text() -> str:
    """取像與打光（相機、鏡頭、介面、光源）：選型問答用，不進 system 段（太長且不是每次都要）。"""
    return (SKILL_DIR / "imaging.md").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def imaging_sections() -> list[tuple[str, str]]:
    """imaging.md 的 `## 標題` 分段 → [(標題, 內文)]，給說明檢索當一節一節的來源。"""
    text = imaging_text()
    return [(m.group(1).strip(), m.group(2).strip()) for m in re.finditer(r"^## (.+?)\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)]


@lru_cache(maxsize=1)
def curated_notes() -> dict[str, str]:
    """tools.md 的 `## <type>` 分段 → {type: 要領文字}。"""
    text = (SKILL_DIR / "tools.md").read_text(encoding="utf-8")
    notes: dict[str, str] = {}
    # 標題可以是 `## a / b`（幾顆工具共用一段要領）：每個 key 都登記同一段。以前只認單一 key，
    # `write_modbus / read_modbus`、`variable_get / variable_set` 四顆工具其實一直沒有要領進技能。
    for m in re.finditer(r"^## ([^\n]+?)\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL):
        body = m.group(2).strip()
        for key in re.split(r"\s*/\s*", m.group(1).strip()):
            if key:
                notes[key] = body
    return notes


def _param_line(p: Any) -> str:
    bits = [f"`{p.key}`（{p.label}，{p.kind}"]
    if p.default not in (None, ""):
        bits.append(f"，預設 {p.default!r}")
    rng = []
    if getattr(p, "minimum", None) is not None:
        rng.append(f"≥{p.minimum}")
    if getattr(p, "maximum", None) is not None:
        rng.append(f"≤{p.maximum}")
    if rng:
        bits.append("，範圍 " + " ".join(rng))
    if getattr(p, "unit", ""):
        bits.append(f"，單位 {p.unit}")
    if getattr(p, "options", None):
        bits.append("，選項 " + "/".join(str(o["value"]) for o in p.options))
    if getattr(p, "shapes", None):
        bits.append("，形狀 " + "/".join(p.shapes))
    if getattr(p, "required", False):
        bits.append("，必填")
    if getattr(p, "teach", False):
        bits.append("，現場調機參數")
    line = "".join(bits) + "）"
    if getattr(p, "help_text", ""):
        line += f"：{p.help_text}"
    return "- " + line


def tool_skill(key: str, user: Any = None, *, custom: bool = True) -> str:
    """單一工具的完整技能（markdown）：自動骨架＋人工要領（＋站點／個人補充）。note 不是工具，只有要領。"""
    notes = curated_notes()
    if key == "note":
        base = "# note（畫布便利貼）\n\n" + notes.get("note", "")
        return with_custom(base, key, user) if custom else base
    if not tools.has(key):
        raise KeyError(key)
    t = tools.get(key)
    lines = [f"# {t.key}（{t.label}）", "", f"分類：{tools.CATEGORY_LABELS.get(t.category, t.category)}", ""]
    if t.description:
        lines += [t.description, ""]
    if key in notes:
        lines += ["## 使用要領", "", notes[key], ""]
    lines += ["## 參數", ""]
    lines += [_param_line(p) for p in t.params] or ["（無）"]
    lines += ["", "## 輸入埠", ""]
    lines += [f"- `{p.key}`（{p.label}，{p.type}{'' if getattr(p, 'required', True) else '，選填'}）" for p in t.inputs] or ["（無）"]
    lines += ["", "## 輸出埠", ""]
    lines += [f"- `{p.key}`（{p.label}，{p.type}）" for p in t.outputs] or ["（無）"]
    extras = []
    if getattr(t, "accepts", ("u8",)) != ("u8",):
        extras.append("可吃位深：" + "/".join(t.accepts))
    if getattr(t, "heavy", False):
        extras.append("可能耗時較久")
    if extras:
        lines += ["", "；".join(extras)]
    base = "\n".join(lines).rstrip() + "\n"
    return with_custom(base, key, user) if custom else base


def list_skills() -> list[dict[str, Any]]:
    notes = curated_notes()
    items: list[dict[str, Any]] = [
        {"key": "platform", "label": "平台規則", "category": "guide", "curated": True},
        {"key": "design", "label": "流程設計原則", "category": "guide", "curated": True},
        {"key": "agentic", "label": "代理工作方式", "category": "guide", "curated": True},
    ]
    for t in sorted(tools.all_types(), key=lambda x: (x.category, x.key)):
        items.append({"key": t.key, "label": t.label, "category": t.category, "curated": t.key in notes})
    items.append({"key": "note", "label": "註解（便利貼）", "category": "guide", "curated": "note" in notes})
    return items


def base_skill_text(key: str) -> str:
    """內建技能（不含自訂補充）。"""
    if key == "platform":
        return platform_text()
    if key == "design":
        return design_text()
    if key == "agentic":
        return agentic_text()
    if key == "imaging":
        return imaging_text()
    return tool_skill(key, custom=False)


def skill_text(key: str, user: Any = None) -> str:
    """技能全文（內建＋站點補充＋個人補充）。"""
    if key in GUIDE_KEYS:
        return with_custom(base_skill_text(key), key, user)
    return tool_skill(key, user)


def _generatable(t: Any) -> bool:
    return not (t.key.startswith("dl_") or t.key in ("write_modbus", "save_image"))


@lru_cache(maxsize=1)
def brief_catalogue() -> str:
    """全工具一行式目錄（type｜名稱｜一句話），放在 system 段讓 LLM 知道有什麼可用。"""
    rows = []
    for t in sorted(tools.all_types(), key=lambda x: (x.category, x.key)):
        if not _generatable(t):
            continue
        desc = (t.description or "").replace("\n", " ")
        rows.append(f"- {t.key}（{t.label}，{tools.CATEGORY_LABELS.get(t.category, t.category)}）：{desc[:80]}")
    return "\n".join(rows)


def select_tools(text: str, regions: list[dict[str, Any]] | None = None, *, intent_kind: str = "",
                 graph: dict[str, Any] | None = None, limit: int = 24) -> list[str]:
    """本次要附完整技能的工具，兩層：必帶（核心 ∪ 關鍵詞命中 ∪ 意圖對應，永不截斷）＋可選（ROI 形狀 ∪ 既有 graph 用到的，補到 limit）。
    這樣既有 graph 節點很多時，不會把使用者指令點名的工具擠掉。"""
    must: list[str] = list(CORE_TOOLS)
    optional: list[str] = []

    def add(target: list[str], keys: tuple[str, ...] | list[str]) -> None:
        for k in keys:
            if k not in must and k not in optional and (k == "note" or tools.has(k)):
                target.append(k)

    low = (text or "").lower()
    for pattern, keys in KEYWORD_TOOLS.items():
        if re.search(pattern, low):
            add(must, keys)
    if intent_kind in INTENT_TOOLS:
        add(must, INTENT_TOOLS[intent_kind])
    for r in regions or []:
        shape = str((r.get("region") or {}).get("shape", ""))
        add(optional, _ROI_TOOLS.get(shape, ()))
    # 關鍵詞表只列得出常見的幾十顆；其餘 146 顆靠說明索引的工具技能段做檢索（BM25，中文提問會先補英文同義詞），
    # 提示詞裡沒有表上的字也能把對的工具帶進來（例如「兩台相機拼成一張」→ stitch_images）
    add(optional, retrieved_tools(text, k=RETRIEVED_TOOLS))
    if graph:
        add(optional, [n.get("type", "") for n in graph.get("nodes", []) if n.get("type") != "note"])
    return must + optional[: max(0, limit - len(must))]


#: 檢索帶進來的工具數上限（放在 optional，會被既有 graph 的節點與 limit 擠）
RETRIEVED_TOOLS = 6
_TOOL_HEADING = re.compile(r"\(([a-z0-9_]+)\)\s*$")


def retrieved_tools(text: str, k: int = RETRIEVED_TOOLS) -> list[str]:
    """用說明索引（help.py 的工具技能段）依提示詞找相關工具 key，依分數排序。索引第一次用時建立並快取。"""
    if not (text or "").strip():
        return []
    from apps.vision.agent import help as help_mod  # 延後 import：help 也 import skills

    out: list[str] = []
    try:
        hits = help_mod.search(text, k=max(k * 3, 12), kinds=("tool",))  # 只對工具技能段計分：指南章節（尤其中文譯本）會把工具擠出前幾名
    except Exception:  # noqa: BLE001 - 索引建不起來不該讓生成失敗
        log.warning("工具檢索失敗", exc_info=True)
        return out
    for section, _score in hits:
        if section.kind != "tool":
            continue
        m = _TOOL_HEADING.search(section.heading)
        key = m.group(1) if m else ""
        if key and tools.has(key) and key not in out:
            out.append(key)
        if len(out) >= k:
            break
    return out


@lru_cache(maxsize=4)
def build_system(epoch_key: int = 0) -> str:
    """穩定的 system 段（可快取；站點補充改變時 epoch 變、重組）：平台規則＋設計原則＋精簡目錄＋輸出格式。個人補充放 user 訊息（focus_text）。"""
    return "\n\n".join([
        with_custom(platform_text(), "platform", include_user=False).strip(),
        with_custom(design_text(), "design", include_user=False).strip(),
        "# 工具目錄（精簡；本次相關工具的完整參數與要領會附在使用者訊息裡）\n\n" + brief_catalogue(),
        "# 輸出\n\n只輸出一個 JSON 物件，不要任何其他文字或 markdown 圍欄：\n"
        '{"graph": {...}, "rationale": "繁體中文說明（生成理由／改了什麼）"}',
    ])


@lru_cache(maxsize=4)
def build_system_agentic(epoch_key: int = 0) -> str:
    """代理模式的 system 段：平台規則＋設計原則＋代理工作方式＋精簡目錄（不含單次 JSON 輸出格式）。"""
    return "\n\n".join([
        with_custom(platform_text(), "platform", include_user=False).strip(),
        with_custom(design_text(), "design", include_user=False).strip(),
        with_custom(agentic_text(), "agentic", include_user=False).strip(),
        "# 工具目錄（精簡；用 get_tool_skill 讀完整參數與要領）\n\n" + brief_catalogue(),
    ])


def focus_text(keys: list[str], user: Any = None) -> str:
    """相關工具的完整技能（放進 user 訊息）＋使用者對指南的個人補充。"""
    parts = []
    for k in keys:
        try:
            parts.append(skill_text(k, user))
        except KeyError:
            continue
    text = "# 本次相關工具的完整技能\n\n" + "\n---\n".join(parts)
    if user is not None and getattr(user, "pk", None):
        for g in GUIDE_KEYS:
            _, mine = custom_texts(g, user)
            if mine:
                text += f"\n\n# 個人補充：{GUIDE_LABELS[g]}\n\n{mine.strip()}"
    return text
