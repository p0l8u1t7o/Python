"""平台使用說明問答：把 docs/*.html 拆成章節＋名詞規範表＋每個工具的技能建成檢索索引（BM25，中文用雙字詞），
依問題找最相關的幾段，LLM 可用時以文件片段為依據回答（引用章節），離線時直接回文件片段與連結。

索引在第一次查詢時建立並快取（docs 檔案有更新就重建）；docs 由 Django 在 /docs/<page>.html 提供，回答附的 url 可直接開。"""

from __future__ import annotations

import html
import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apps.vision.agent import actions, lookup, notes, providers, situation, skills
from apps.vision.tools import base as tools

log = logging.getLogger("vision.agent")

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"
#: 介面地圖（frontend/src/lib/uiMap.ts 經 `node scripts/ui_map.mjs` 產生；三語系的頁面名稱、用途、分頁與主要動作）
UI_MAP_PATH = Path(__file__).resolve().parent / "ui_map.json"
PAGE_TITLES = {
    "index.html": "Overview", "workflow-design.html": "Workflow design", "architecture.html": "Architecture", "automation.html": "Automation", "modbus.html": "Modbus",
    "dl.html": "Deep learning", "plugins.html": "Plugins", "contract.html": "Contract", "glossary.html": "Glossary", "golden.html": "Golden Set",
    "batch.html": "Batch testing", "performance.html": "Performance", "vision-capabilities.html": "Inspection capabilities", "samples.html": "Example templates",
    "agent.html": "AI assistant", "user-guide.html": "User guide", "capture-client.html": "Capture client", "deployment.html": "Deployment",
}
#: 使用者手冊與 AI 助手／批次頁最貼近操作，檢索時略加權；合約／設計手冊偏工程。
#: 頁面加權：手冊與功能頁優先；合約／架構／效能／部署與名詞表是參考資料，「怎麼做」的問題不該被它們搶走第一名；名詞表有中文欄，每一段都塞滿名詞，中文提問幾乎都命中，壓到 0.7 才不會把功能頁擠掉
PAGE_BOOST = {"user-guide.html": 1.4, "batch.html": 1.2, "agent.html": 1.1, "capture-client.html": 1.1, "golden.html": 1.1, "dl.html": 1.1, "automation.html": 1.1, "contract.html": 0.8, "architecture.html": 0.8, "performance.html": 0.7, "deployment.html": 0.9, "glossary.html": 0.7}
#: 使用者指南的 Markdown 正本：docs/guide/<lang>/<page>.md（en 是正本，zh-Hant／zh-Hans 是譯本）；有 md 的頁面不再索引同名 HTML。


def _guide_dir() -> Path:
    """呼叫時才算：測試會把 DOCS_DIR 換成暫存資料夾，指南也要跟著換。"""
    return DOCS_DIR / "guide"


GUIDE_LANGS = ("en", "zh-Hant", "zh-Hans")
GUIDE_PAGES = ("user-guide", "samples", "vision-capabilities", "calibration", "batch", "dl", "agent", "golden", "glossary")
PAGE_TITLES.update({f"guide/{p}": PAGE_TITLES.get(f"{p}.html", p) for p in GUIDE_PAGES})
PAGE_BOOST.update({f"guide/{p}": PAGE_BOOST.get(f"{p}.html", 1.0) for p in GUIDE_PAGES})
#: 提問語言與章節語言不同時的降權：譯本存在時同語系的章節優先，但英文正本仍然找得到
OTHER_LANG_WEIGHT = 0.8
MAX_SECTION_CHARS = 1400
TOP_K = 5
#: 問「在哪裡／哪個頁面」時介面地圖段加權，其餘降權：地圖段很短，BM25 的長度正規化會讓它們搶走「怎麼做」類問題的第一名。
_WHERE = re.compile(r"哪裡|哪里|哪個頁面|哪个页面|在哪|哪一頁|哪一页|哪頁|哪页|怎麼去|怎么去|\bwhere\b|which (page|tab|menu)|how do i (get|go) to|navigate", re.IGNORECASE)
UI_WEIGHT_WHERE = 1.3
UI_WEIGHT_OTHER = 0.35
#: 問題本身在問錯誤／失敗時，最近的錯誤文字才併進檢索（否則一個 423 會把「在哪裡」帶到鎖定章節）
_ABOUT_ERROR = re.compile(r"為什麼|为什么|失敗|失败|錯誤|错误|出錯|出错|不行|無法|无法|沒有反應|没有反应|\bwhy\b|\bfail|\berror|\bwrong|\bnot work|\bcannot\b|\bcan't\b|\bbroken", re.IGNORECASE)
#: 使用者看得到的規則／警告文字（依介面語言；LLM 的回答本來就跟提問語言）
MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "recent_error": "Most recent error ({ago}s ago): {text}",
        "no_hits": "The documentation has no section that directly matches this question. Try other keywords (a feature or page name), or open the Help page for the quick start and the glossary.",
        "by_docs": "From the platform documentation:",
        "footer": "(The full text is behind the reference links below; the offline rule mode only quotes the documentation, an LLM provider gives an organised answer.)",
        "lookup_failed": "Live lookups failed, answered from the documentation only: {reason}",
        "empty_reply": "The LLM ({provider}) returned nothing; fell back to documentation excerpts",
        "llm_failed": "The LLM ({provider}) failed; fell back to documentation excerpts: {reason}",
        "no_screenshot": "The offline rule mode cannot see screenshots; answered from text only",
    },
    "zh-Hant": {
        "recent_error": "最近一次錯誤（{ago} 秒前）：{text}",
        "no_hits": "文件裡找不到與問題直接相關的段落。可試著換個關鍵詞（例如功能名稱或頁面名稱），或到「說明」頁瀏覽快速上手與名詞定義。",
        "by_docs": "依平台文件：",
        "footer": "（完整內容請見下方參考連結；離線規則模式只能節錄文件，接上 LLM 供應商可得到整理過的回答。）",
        "lookup_failed": "即時查詢失敗，已改用純文件回答：{reason}",
        "empty_reply": "LLM（{provider}）回了空白，已改用文件節錄",
        "llm_failed": "LLM（{provider}）失敗，已改用文件節錄：{reason}",
        "no_screenshot": "離線規則模式看不到截圖，只依文字回答",
    },
    "zh-Hans": {
        "recent_error": "最近一次错误（{ago} 秒前）：{text}",
        "no_hits": "文档里找不到与问题直接相关的段落。可尝试换个关键词（例如功能名称或页面名称），或到「帮助」页浏览快速上手与名词定义。",
        "by_docs": "依平台文档：",
        "footer": "（完整内容请见下方参考链接；离线规则模式只能节录文档，接上 LLM 供应商可得到整理过的回答。）",
        "lookup_failed": "即时查询失败，已改用纯文档回答：{reason}",
        "empty_reply": "LLM（{provider}）回了空白，已改用文档节录",
        "llm_failed": "LLM（{provider}）失败，已改用文档节录：{reason}",
        "no_screenshot": "离线规则模式看不到截图，只依文字回答",
    },
}


def msg(lang: Any, key: str, **kw: Any) -> str:
    return MESSAGES[situation.norm_lang(lang)][key].format(**kw)


#: 問答路徑最多幾回合工具呼叫（每回合可查多個），之後要求直接回答
MAX_LOOKUP_TURNS = 4
NL = chr(10)
ACTION_KINDS = ("navigate", "focus_node", "open_tool")
_ACTIONS_LINE = re.compile(r"^\s*ACTIONS:\s*(\[.*\])\s*$", re.MULTILINE | re.DOTALL)

HELP_SYSTEM = """You are the documentation assistant for VisionSequence, a machine vision platform.
- Answer only from the documentation excerpts below. If they do not cover it, say so plainly, suggest the page that might, and never invent a feature.
- Reply in the interface language given in the situation ("UI language": en = English, zh-Hant = Traditional Chinese, zh-Hans = Simplified Chinese; never mix the two Chinese scripts); without it, use the language of the question. The documentation is English: translate what you quote.
- Conclusion first, then the steps; mostly bullets; under 300 words. Name pages, tabs and buttons exactly as the interface shows them in that language; the interface map lists each name as "English / interface-language" when they differ, use the second form for Chinese users.
- End with a separate line starting "References:" listing the sections you used, as Page > Section.
- If the question is about changing a flow or a parameter, mention that the assistant can make the change directly in the flow editor or on the batch page.
- You are also given the user's current situation: the page they are on, what it shows, their recent actions and errors, their role and the engine lock. Use it: if a recent error explains the question, explain that error first and how to fix it; point to the exact page, tab and button (the interface map lists them in the user's languages); never tell the user to do something their role cannot do, say which role can.
- When lookup tools are available, use them to read the live state (flows, sources, connections, a run report, the lock, plugins) before answering questions about "why", "which" or "is it"; they are read-only and permission-checked, so a "not permitted" result means the user's role cannot see that, and you say so. Do not call a tool for questions the documentation alone answers.
- Hardware questions — which camera, lens, sensor, interface or lighting, what field of view, working distance, resolution, frame rate, exposure or bandwidth — are yours to answer: call `camera_optics` with whatever the user gave and explain its numbers (never estimate the arithmetic yourself, and never tell the user to ask the assistant, you are the assistant). Pair the numbers with the lighting advice from the imaging sections.
- If a screenshot is attached, answer from what is visible in it (labels, values, statuses, highlighted rows); say when something is not legible instead of guessing.
- "Things the user asked you to remember" are facts this user stored on purpose: treat them as true for this user and use them when relevant.
- You may end with ONE extra line `ACTIONS: [...]` (a JSON array, at most 3 items) offering shortcuts: {"kind":"navigate","to":"<route from the interface map with real ids filled in>","tab":"<tab key, optional>","label":"<short label in the user's language>"} or, in the flow editor, {"kind":"focus_node","node":"<node id>","label":"..."} / {"kind":"open_tool","node":"<node id>","label":"..."}. Only routes from the map; omit the line when nothing applies."""

#: 在檢測任務頁回答時的附加規則：那一頁的使用者不看流程圖（階段 15：回覆列出 find_circle、叫人進畫布接 Fixed image）
INSPECT_GUIDANCE = """The user is on the Inspection tasks page, which builds an inspection from a task list without wiring.
- Answer in terms of inspection tasks and their fields as that page shows them (Add task, the task form, Try run, Save, Advanced flow); do not name internal tool keys, node ids or port names.
- Do not tell the user to add steps, wire connections or edit parameters in the advanced flow unless they ask about the advanced flow. Changes to the task list can be made by asking the assistant to add, change or remove a task, which proposes a card to confirm."""

#: 中英對照：docs 是英文，中文提問先把詞彙補成英文再檢索（來源＝docs/guide/en/glossary.md 的對照表）。
BILINGUAL = {
    "工程筆記": "engineering note", "工程笔记": "engineering note",
    "影像座標系": "image coordinate system pixel origin top left", "物理座標系": "physical coordinate system world millimetres",
    "世界座標": "world physical coordinate millimetres", "座標系": "coordinate system image physical",
    "左手座標系": "left handed coordinate system handedness", "右手座標系": "right handed coordinate system handedness",
    "手性一致性": "chiral consistency handedness mirrored", "手性": "handedness chirality mirrored",
    "物理點": "physical point world coordinate", "示教點": "teaching point reference pose locate offset",
    "運行點": "run point current pose locate offset", "位姿": "pose position angle transform",
    "單像素精度": "single pixel precision mm per pixel calibration", "像素當量": "single pixel precision mm per pixel calibration",
    "線角度": "line angle from x axis clockwise",
    "檢測區": "detection area roi region", "遮罩": "mask 255 ignore apply mask",
    "檢測框": "box rectangle centre width height angle matches", "矩形框": "box rectangle matches",
    "連通區域": "blob connected component area centroid", "形心": "centroid mean position",
    "機率圖": "probability map score map segmentation anomaly", "色彩空間": "colour space rgb hsv hsi lab yuv",
    "方案": "solution station flows settings", "工控機": "industrial computer ipc station",
    "機械手臂": "robot arm corrected position",
    "影像來源": "image source camera", "來源": "source", "資料夾": "folder", "相機": "camera", "取像": "acquire grab image",
    "鏡頭": "lens focal length", "焦距": "focal length lens", "視野": "field of view fov", "工作距離": "working distance wd",
    "景深": "depth of field dof", "光圈": "aperture f-number", "遠心": "telecentric lens", "感光元件": "sensor format",
    "解析度": "resolution pixels", "像素": "pixel resolution", "選型": "choosing camera lens", "頻寬": "bandwidth interface",
    "介面": "interface GigE USB3 CoaXPress", "打光": "lighting illumination", "光源": "light source lighting", "背光": "backlight",
    "同軸光": "coaxial light", "暗場": "dark field low angle", "環形光": "ring light", "圓頂光": "dome light diffuse",
    "偏光": "polariser polarizing filter", "頻閃": "strobe flash", "曝光": "exposure time", "運動模糊": "motion blur",
    "擷取端": "capture client", "通道": "channel", "共享記憶體": "shared memory", "連續串流": "continuous stream",
    "依需求取像": "on demand grab", "流程": "flow graph", "步驟": "node step", "工具": "tool", "連線": "edge connection",
    "埠": "port", "參數": "parameter param", "教導參數": "teaching parameter teach", "參數卡": "teach page",
    "區域": "region roi", "標記": "overlay label", "執行": "run execute", "試執行": "preview", "執行一次": "run once",
    "連續執行": "continuous", "暫存影像": "scratch image", "資產": "asset", "判定": "judge verdict",
    "具名輸出": "named output", "引擎鎖定": "engine lock locked 423", "鎖定": "lock locked", "整合方": "integrator api key",
    "金鑰": "api key", "角色": "role", "管理員": "administrator admin", "工程師": "engineer", "操作員": "operator",
    "重置": "reset", "範本": "template", "範本畫廊": "template gallery", "固定影像": "fixed image picture", "範例樣板": "example template sample",
    "文字辨識": "ocr text read", "字串驗證": "ocv text verify expected", "字型教導": "font teaching taught font ocr", "日期碼": "date code lot number ocr",
    "條碼分級": "barcode quality grade verifier iso 15415 15416", "條碼品質": "barcode quality grade verifier", "符號對比": "symbol contrast grade", "調變": "modulation grade", "未用錯誤更正": "unused error correction UEC", "固定圖形損傷": "fixed pattern damage", "靜區": "quiet zone barcode",
    "形位公差": "form and position tolerance gdt", "直線度": "straightness minimum zone band", "真圓度": "roundness minimum zone circle MZC", "平行度": "parallelism datum", "垂直度": "perpendicularity datum", "傾斜度": "angularity reference angle",
    "光度立體": "photometric stereo four lights surface normal curvature", "刻印字": "embossed engraved characters photometric stereo", "凹坑": "dent photometric stereo curvature", "反射率圖": "albedo photometric stereo",
    "圓形卡尺": "circular caliper radius run-out", "徑向跳動": "run-out radial deviation circular caliper", "序列缺陷": "profile defects sequence",
    "異常檢測": "anomaly detection good parts only memory bank", "只教良品": "anomaly detection good parts only", "記憶庫": "memory bank anomaly",
    "形狀比對": "shape match geometric matching edge direction", "形狀範本": "shape model asset", "幾何比對": "geometric matching shape match",
    "統計範本": "statistical template stat template mean std", "統計良品比對": "statistical defects stat template",
    "平場校正": "shading correction flat field", "陰影校正": "shading correction flat field", "白板": "white reference flat field", "漸暈": "vignetting uneven lighting",
    "排除區": "exclusion zone composite region combine", "組合區域": "composite region combine", "區域組合": "region combine composite",
    "輪廓": "contour outline", "凸缺陷": "convexity defect chip", "崩邊": "chipped edge convexity defect", "缺角": "chipped corner convexity defect",
    "極座標展開": "polar unwrap ring strip", "極座標": "polar", "齒數": "tooth count gear", "展開圖": "unwrapped strip",
    "註解": "note", "批次測試": "batch testing", "影像集": "image set", "批次執行": "batch run",
    "資料洞察": "insights", "建議門檻": "threshold suggestion", "資料諮詢": "consult", "全域 AI 助手": "assistant dock",
    "使用說明": "help documentation", "助手": "assistant", "工作階段": "agent session", "先驗": "prior",
    "代理模式": "agentic mode", "步驟時間軸": "step timeline", "候選方案": "candidate", "影像標記": "image label",
    "自動調參": "autotune auto-tune coordinate descent", "定位補正": "locate correction fixture", "定位": "locate template match",
    "統計": "statistics stats yield", "每小時彙總": "hourly rollup", "影像封存": "image archive", "流程版本": "flow version",
    "操作紀錄": "audit log", "站台": "station", "整合頁": "integration page", "傳圖": "send image tcp_image push", "上位機": "host program",
    "命令與結果": "trace commands results", "主站": "modbus client master", "從站": "modbus server slave",
    "寫入": "write", "讀取": "read", "暫存器": "register holding", "線圈": "coil", "觸發": "trigger",
    "配方": "recipe", "覆寫": "override", "回歸": "regression regress", "基準": "baseline", "案例": "golden case",
    "退步": "regressed", "進步": "improved", "合格門檻": "fail_under threshold",
    "教導專案": "teaching project", "自動標記": "auto label", "模型種類": "trainer", "標記編輯器": "labelling editor shapes",
    "智慧選取": "smart select sam", "智慧框選": "smart box sam", "資料集": "dataset", "分割": "split segmentation",
    "資料集版本": "dataset version", "資料增強": "augmentation augment", "重複偵測": "dedupe duplicate",
    "訓練": "train training", "推論": "inference predict", "深度學習": "deep learning",
    "外掛": "plugin", "主題": "theme", "位深": "bit depth", "手動寫入": "manual write", "匯出": "export", "匯入": "import",
    "效能": "performance benchmark", "執行緒池": "thread pool worker", "快取": "cache", "影像快取": "image cache",
    "事件": "event sse stream", "串流": "stream sse", "指令": "command", "錯誤碼": "error code",
    "安裝": "install setup", "部署": "deploy deployment", "備份": "backup", "還原": "restore", "升級": "upgrade",
    "監控": "monitor health", "卡尺": "caliper edge projection sub-pixel", "找圓": "find_circle circle", "找線": "find_line line",
    "量測": "measure measurement", "公差": "tolerance", "寬度": "width", "直徑": "diameter", "角度": "angle",
    "顏色": "colour color", "缺陷": "defect", "瑕疵": "defect scratch", "條碼": "barcode", "計數": "count blob",
    "門檻": "threshold", "二值化": "threshold binarise", "面積": "area", "圓形度": "circularity",
    "金字塔": "pyramid", "範本比對": "template_match template matching", "形狀": "shape", "多邊形": "polygon",
    "矩形": "rect rectangle", "環形": "annulus", "橢圓": "ellipse", "折線": "polyline",
    "使用者": "user account", "帳號": "account user", "登入": "sign in login", "密碼": "password",
    "文案": "wording tone copy", "用詞": "wording terminology", "規範": "convention rule glossary",
    "良率": "yield", "不良": "reject ng", "看板": "board dashboard",
    "設定": "settings configuration", "語言": "language", "說明": "help",
}


def expand_query(query: str) -> str:
    """中文提問補上英文同義詞（docs 是英文），英文提問原樣。

    長詞優先：命中「執行緒池」就不再加「執行」的同義詞，避免短詞把檢索帶偏。
    """
    matched: list[str] = []
    extra: list[str] = []
    for zh in sorted(BILINGUAL, key=len, reverse=True):
        if zh in query and not any(zh in seen for seen in matched):
            matched.append(zh)
            extra.append(BILINGUAL[zh])
    return (query + " " + " ".join(extra)) if extra else query


@dataclass
class Section:
    page: str
    page_title: str
    heading: str
    anchor: str
    text: str
    kind: str = "doc"  # doc | glossary | tool | ui
    tokens: dict[str, int] = field(default_factory=dict)
    length: int = 0
    lang: str = "en"  # doc 章節的語言：HTML 工程文件一律 en，指南 md 依資料夾

    @property
    def url(self) -> str:
        if self.kind == "ui":
            return self.anchor  # 介面地圖：anchor 就是前端路由
        if self.page.startswith("guide/"):
            page = self.page[len("guide/"):]
            return f"/help/{page}#{self.anchor}" if self.anchor else f"/help/{page}"
        return f"/docs/{self.page}#{self.anchor}" if self.anchor else f"/docs/{self.page}"

    @property
    def title(self) -> str:
        return f"{self.page_title} › {self.heading}" if self.heading else self.page_title


@dataclass
class Index:
    sections: list[Section]
    df: dict[str, int]
    avg_len: float
    stamp: float
    #: 依 kind 分開的 df 與（段數, 平均長度）：只搜某幾種段落（例如工具技能）時 idf 要在那個子集裡算，
    #: 不然三語系指南章節的詞頻會把工具技能的分數拉低（「相機」在指南裡到處都是）
    df_by_kind: dict[str, dict[str, int]] = field(default_factory=dict)
    stats_by_kind: dict[str, tuple[int, float]] = field(default_factory=dict)


_CJK = re.compile(r"[㐀-鿿]+")
_WORD = re.compile(r"[a-z0-9_][a-z0-9_.\-]*")


def tokenize(text: str) -> list[str]:
    """英數字整詞＋中文雙字詞（外加單字，讓短查詢也有命中）。"""
    low = text.lower()
    out: list[str] = _WORD.findall(low)
    for run in _CJK.findall(low):
        if len(run) == 1:
            out.append(run)
            continue
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
    return out


def _strip(fragment: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</(p|li|tr|h[1-6]|pre|div|table)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<td[^>]*>", " | ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _parse_page(page: str, raw: str) -> list[Section]:
    body = raw.split("<article", 1)[1] if "<article" in raw else raw
    body = re.sub(r"<nav class=\"site\">.*?</nav>", "", body, flags=re.DOTALL)
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, flags=re.DOTALL)
    page_title = _strip(m.group(1)) if m else PAGE_TITLES.get(page, page)
    parts = re.split(r"(<h[23][^>]*>.*?</h[23]>)", body, flags=re.DOTALL)
    sections: list[Section] = []
    heading, anchor = "", ""
    intro = _strip(parts[0])
    if intro and len(intro) > 40:
        sections.append(Section(page, page_title, "", "", intro[:MAX_SECTION_CHARS * 2]))
    for i in range(1, len(parts), 2):
        tag, content = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        heading = _strip(re.sub(r"<[^>]+>", "", tag))
        am = re.search(r'id="([^"]+)"', tag)
        anchor = am.group(1) if am else ""
        text = _strip(content)
        if not text:
            continue
        for chunk_no, start in enumerate(range(0, len(text), MAX_SECTION_CHARS * 2)):
            chunk = text[start:start + MAX_SECTION_CHARS * 2]
            sections.append(Section(page, page_title, heading if chunk_no == 0 else f"{heading}（續）", anchor, chunk))
    return sections


_MD_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
_MD_ANCHOR = re.compile(r"\s*\{#([\w\-]+)\}\s*$")


def _md_strip(fragment: str) -> str:
    """Markdown → 純文字：先拆掉內嵌 HTML（截圖說明區塊），再去掉強調、程式碼、連結與錨點語法。"""
    text = _strip(fragment)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"```[a-z]*", " ", text)
    text = re.sub(r"[*_`]{1,3}", "", text)
    text = re.sub(r"\{#[\w\-]+\}", "", text)
    text = re.sub(r"^\|?-{3,}\|.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _parse_markdown(page: str, raw: str, lang: str) -> list[Section]:
    """指南 md → 章節：`## Title {#id}` 與 `### Title {#id}` 各一段，標題前的內文是一段簡介；anchor 沒寫就用 slug。"""
    m = re.match(r"^#\s+(.+?)\s*$", raw, flags=re.MULTILINE)
    page_title = _md_strip(m.group(1)) if m else PAGE_TITLES.get(page, page)
    body = raw[m.end():] if m else raw
    sections: list[Section] = []
    pos = 0
    heading, anchor = "", ""
    for hm in list(_MD_HEADING.finditer(body)) + [None]:
        content = body[pos:hm.start()] if hm else body[pos:]
        text = _md_strip(content)
        if heading or len(text) > 40:
            # 長章節（名詞表那種大表格）切成「（續）」片段，與 HTML 解析同一套；只截斷會把表格後半段丟掉
            for chunk_no, start in enumerate(range(0, max(1, len(text)), MAX_SECTION_CHARS * 2)):
                chunk = text[start:start + MAX_SECTION_CHARS * 2]
                sections.append(Section(page, page_title, heading if chunk_no == 0 else f"{heading}（續）", anchor, chunk, lang=lang))
        if hm is None:
            break
        title = hm.group(2)
        am = _MD_ANCHOR.search(title)
        anchor = am.group(1) if am else re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        heading = _md_strip(_MD_ANCHOR.sub("", title))
        pos = hm.end()
    return sections


def _guide_sections() -> list[Section]:
    out: list[Section] = []
    for lang in GUIDE_LANGS:
        folder = _guide_dir() / lang
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            if path.name.startswith("_"):
                continue  # 底線開頭＝翻譯用的暫存片段，不是指南頁
            try:
                out.extend(_parse_markdown(f"guide/{path.stem}", path.read_text(encoding="utf-8"), lang))
            except Exception:  # noqa: BLE001
                log.warning("說明索引：%s/%s 解析失敗", lang, path.name, exc_info=True)
    return out


def _guide_html_names() -> set[str]:
    """已有 md 正本的指南頁：同名 HTML（過渡期可能還在）不再索引，免得同一段內容出現兩次。"""
    return {f"{p}.html" for p in GUIDE_PAGES if (_guide_dir() / "en" / f"{p}.md").exists()}


def _tool_sections() -> list[Section]:
    out = []
    for t in tools.all_types():
        try:
            text = skills.base_skill_text(t.key)
        except KeyError:
            continue
        out.append(Section("agent.html", "AI skills", f"Tool: {t.label} ({t.key})", "skills", _strip(text)[:MAX_SECTION_CHARS * 2], kind="tool"))
    return out


def load_ui_map() -> dict[str, Any]:
    try:
        return json.loads(UI_MAP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("介面地圖 %s 讀不到，助手不知道頁面與按鈕的名稱", UI_MAP_PATH)
        return {"languages": [], "pages": []}


def _names(row: dict[str, Any] | None) -> str:
    """{'en': 'Sources', 'zh-Hant': '來源庫', ...} → 'Sources / 來源庫 / 来源库'（去重）。"""
    seen: list[str] = []
    for v in (row or {}).values():
        if v and v not in seen:
            seen.append(str(v))
    return " / ".join(seen)


def _imaging_sections() -> list[Section]:
    """取像與打光的技能：一個 `##` 一節，讓「怎麼選鏡頭」「刮痕怎麼打光」問得到。"""
    out = []
    for heading, body in skills.imaging_sections():
        out.append(Section("agent.html", "Imaging and lighting", heading, "imaging", _strip(body)[:MAX_SECTION_CHARS * 2], kind="tool"))
    return out


def _ui_sections() -> list[Section]:
    """介面地圖每頁一段：三語系的名稱、用途、分頁、動作與需要的功能，中文提問也檢索得到。"""
    out: list[Section] = []
    for p in load_ui_map().get("pages", []):
        lines = [f"Page: {_names(p.get('names'))}", f"Route: {p.get('route')}", f"Purpose: {_names(p.get('summary'))}"]
        if p.get("admin"):
            lines.append("Access: administrators only")
        elif p.get("feature"):
            lines.append(f"Access: needs the '{p['feature']}' feature (administrators always can)")
        if p.get("tabs"):
            lines.append("Tabs: " + "; ".join(_names(t.get("names")) for t in p["tabs"]))
        if p.get("actions"):
            lines.append("Buttons: " + "; ".join(_names(a) for a in p["actions"]))
        out.append(Section("ui", "Interface", str((p.get("names") or {}).get("en") or p.get("id")), str(p.get("route") or ""), "\n".join(lines), kind="ui"))
    return out


def ui_page_for(route: str) -> dict[str, Any] | None:
    """前端路由（/flows/12/tools/blob）→ 介面地圖的頁面（/flows/:flowId/tools/:nodeId）；最長樣板優先。"""
    best = None
    for p in load_ui_map().get("pages", []):
        pattern = "^" + re.sub(r":[A-Za-z]+", r"[^/]+", str(p.get("route") or "")) + "$"
        if re.match(pattern, route or "") and (best is None or len(p["route"]) > len(best["route"])):
            best = p
    return best


def _bi(names: dict[str, Any] | None, lang: str) -> str:
    """'English / 介面語言名稱'（兩者相同或英文介面時只給英文）。"""
    names = names or {}
    en = str(names.get("en") or "")
    other = str(names.get(lang) or "") if lang != "en" else ""
    return f"{en} / {other}" if other and other != en else en


def ui_brief(lang: str = "en") -> str:
    """給 system 提示的一頁地圖（一行一頁），讓 LLM 用介面上真正的名稱指路；中文介面時名稱給「英文 / 中文」。"""
    lang = situation.norm_lang(lang)
    rows = []
    for p in load_ui_map().get("pages", []):
        names = p.get("names") or {}
        extras = []
        if p.get("tabs"):
            extras.append("tabs: " + ", ".join(f"{t.get('key')} ({_bi(t.get('names'), lang) or t.get('key')})" for t in p["tabs"]))
        if p.get("actions"):
            extras.append("buttons: " + ", ".join(_bi(a, lang) for a in p["actions"]))
        access = " [admin]" if p.get("admin") else (f" [{p['feature']}]" if p.get("feature") else "")
        rows.append(f"- {_bi(names, lang) or p.get('id')} ({p.get('route')}){access}: {(p.get('summary') or {}).get('en', '')}" + (f"; {'; '.join(extras)}" if extras else ""))
    head = "# Interface map (page (route) [required feature]: purpose; tabs; buttons)" + ("; names are English / interface language" if lang != "en" else "")
    return head + "\n" + "\n".join(rows)


def _finish(sections: list[Section]) -> Index:
    df: dict[str, int] = {}
    df_by_kind: dict[str, dict[str, int]] = {}
    totals: dict[str, list[float]] = {}
    total = 0
    for s in sections:
        counts: dict[str, int] = {}
        # 標題算兩次（標題命中比內文重要）；「（續）」續段只算一次——它只是同一節的後半，不該比正段更像那個標題
        head = s.heading if s.heading.endswith("（續）") else f"{s.heading} {s.heading}"
        for tok in tokenize(f"{s.page_title} {head} {s.text}"):
            counts[tok] = counts.get(tok, 0) + 1
        s.tokens = counts
        s.length = sum(counts.values())
        total += s.length
        kind_df = df_by_kind.setdefault(s.kind, {})
        agg = totals.setdefault(s.kind, [0, 0.0])
        agg[0] += 1
        agg[1] += s.length
        for tok in counts:
            df[tok] = df.get(tok, 0) + 1
            kind_df[tok] = kind_df.get(tok, 0) + 1
    stats = {kind: (int(n), (length / n) if n else 1.0) for kind, (n, length) in totals.items()}
    return Index(sections, df, (total / len(sections)) if sections else 1.0, _stamp(), df_by_kind, stats)


def _stamp() -> float:
    paths = list(DOCS_DIR.glob("*.html")) + list(_guide_dir().glob("*/*.md")) + ([UI_MAP_PATH] if UI_MAP_PATH.exists() else [])
    try:
        return max(p.stat().st_mtime for p in paths)
    except ValueError:
        return 0.0


_index: Index | None = None


def build_index(force: bool = False) -> Index:
    global _index
    stamp = _stamp()
    if _index is not None and not force and _index.stamp == stamp:
        return _index
    sections: list[Section] = []
    skip = _guide_html_names()
    for path in sorted(DOCS_DIR.glob("*.html")):
        if path.name in skip:
            continue
        try:
            sections.extend(_parse_page(path.name, path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            log.warning("說明索引：%s 解析失敗", path.name, exc_info=True)
    sections.extend(_guide_sections())
    sections.extend(_tool_sections())
    sections.extend(_imaging_sections())
    sections.extend(_ui_sections())
    _index = _finish(sections)
    return _index


def search(query: str, k: int = TOP_K, *, extra_terms: str = "", lang: str | None = None, kinds: tuple[str, ...] | None = None) -> list[tuple[Section, float]]:
    """BM25（k1=1.5、b=0.75），標題命中加權、頁面加權；給了 lang 時其他語言的文件章節略降權（譯本存在就先給譯本）；
    kinds 限定只對哪幾種段落計分（例如只找工具技能段，才不會被指南章節擠掉）。"""
    idx = build_index()
    q = tokenize(f"{expand_query(query)} {extra_terms}")
    if not q:
        return []
    n = len(idx.sections)
    df = idx.df
    avg_len = idx.avg_len
    if kinds:
        # 只搜這幾種段落：n／df／平均長度都在子集裡算，分數才反映「在工具技能裡有多特別」
        n = sum(idx.stats_by_kind.get(kind, (0, 1.0))[0] for kind in kinds) or 1
        df = {}
        for kind in kinds:
            for tok, count in idx.df_by_kind.get(kind, {}).items():
                df[tok] = df.get(tok, 0) + count
        lengths = [idx.stats_by_kind[kind] for kind in kinds if kind in idx.stats_by_kind]
        avg_len = (sum(c * a for c, a in lengths) / max(1, sum(c for c, _ in lengths))) if lengths else idx.avg_len
    ui_weight = UI_WEIGHT_WHERE if _WHERE.search(query) else UI_WEIGHT_OTHER
    scored: list[tuple[Section, float]] = []
    for s in idx.sections:
        if kinds and s.kind not in kinds:
            continue
        score = 0.0
        head_tokens = set(tokenize(f"{s.page_title} {s.heading}"))
        for tok in set(q):
            tf = s.tokens.get(tok, 0)
            if not tf:
                continue
            dfv = df.get(tok, 1)
            idf = math.log(1 + (n - dfv + 0.5) / (dfv + 0.5))
            score += idf * (tf * 2.5) / (tf + 1.5 * (0.25 + 0.75 * s.length / avg_len))
            if tok in head_tokens:
                score += idf * 0.8
        if score > 0:
            weight = 0.9 if s.kind == "tool" else ui_weight if s.kind == "ui" else 1.0
            if lang and s.kind == "doc" and s.lang != lang:
                weight *= OTHER_LANG_WEIGHT
            scored.append((s, score * PAGE_BOOST.get(s.page, 1.0) * weight))
    scored.sort(key=lambda r: -r[1])
    return scored[:k]


def snippet(section: Section, query: str, width: int = 240) -> str:
    text = section.text
    if len(text) <= width:
        return text
    q = [t for t in tokenize(query) if len(t) >= 2]
    best, best_pos = -1, 0
    for pos in range(0, max(1, len(text) - width), 40):
        window = text[pos:pos + width].lower()
        hits = sum(1 for t in q if t in window)
        if hits > best:
            best, best_pos = hits, pos
    piece = text[best_pos:best_pos + width].strip()
    return ("…" if best_pos else "") + piece + ("…" if best_pos + width < len(text) else "")


def _optics_section(question: str) -> list[Section]:
    """問題裡有取像數字（視野、工作距離、特徵、fps、線速…）就先把規格算好，模型直接引用算出來的數字。

    這樣不管模型有沒有呼叫 camera_optics，回答裡的焦距與頻寬都是算的而不是猜的；離線規則路徑也拿得到。
    """
    from apps.vision.agent import optics

    if not optics.relevant(question):
        return []
    args = optics.parse_question(question)
    if len(args) < 2:
        return []
    result = optics.solve(**args)
    lines = ["Computed from the numbers in the question (arithmetic done by the platform, quote these):",
             "Inputs: " + ", ".join(f"{k}={v}" for k, v in result["inputs"].items())]
    lines += [f"{k}: {v}" for k, v in result.items() if k not in ("inputs", "notes")]
    lines += result["notes"]
    return [Section("agent.html", "Imaging and lighting", "Camera and lens calculation", "imaging", NL.join(lines), kind="tool")]


def _context_sections(context: dict[str, Any] | None) -> list[Section]:
    """目前頁面的專屬資料：工具頁／編輯器選到的工具技能、目前所在頁面的介面地圖段。"""
    out: list[Section] = []
    node_type = str((context or {}).get("node_type") or "")
    if node_type and tools.has(node_type):
        t = tools.get(node_type)
        out.append(Section("agent.html", "AI skills", f"Tool: {t.label} ({t.key})", "skills", _strip(skills.skill_text(node_type))[:MAX_SECTION_CHARS * 2], kind="tool"))
    route = str((context or {}).get("route") or "")
    page = ui_page_for(route) if route else None
    if page:
        out.extend(s for s in build_index().sections if s.kind == "ui" and s.anchor == page.get("route"))
    return out


def _error_terms(context: dict[str, Any] | None, question: str = "") -> str:
    """問錯誤時，最近的錯誤文字也拿去檢索（失敗碼與訊息常直接對到文件的一段）；問別的事不併，免得被帶偏。"""
    if question and not _ABOUT_ERROR.search(question):
        return ""
    errs = situation.recent_errors(situation.clean_activity((context or {}).get("activity")))
    if not errs:
        return ""
    e = errs[0]
    return f"{e['text']} {e.get('detail', '')}"[:300]


CONTEXT_LABELS = {"flow_editor": "flow editor", "tool": "tool page", "batch": "batch testing", "golden": "Golden Set", "agent": "AI assistant", "dl": "deep learning", "sources": "image sources", "assets": "assets", "dashboard": "dashboard", "page": ""}


def offline_answer(question: str, hits: list[tuple[Section, float]], *, context: dict[str, Any] | None = None) -> str:
    """離線規則回答：最近一次錯誤（有的話）＋文件節錄；文字依介面語言（context.lang，預設英文）。"""
    lang = (context or {}).get("lang")
    lines: list[str] = []
    # 問錯誤才先講最近一次錯誤（問「在哪裡」時那行是噪音）
    errs = situation.recent_errors(situation.clean_activity((context or {}).get("activity"))) if _ABOUT_ERROR.search(question) else []
    if errs:
        e = errs[0]
        lines.append(msg(lang, "recent_error", ago=e["ago_s"], text=e["text"] + (f" — {e['detail']}" if e.get("detail") else "")))
    if not hits:
        lines.append(msg(lang, "no_hits"))
        return "\n".join(lines)
    lines.append(msg(lang, "by_docs"))
    for i, (s, _) in enumerate(hits[:3], start=1):
        lines.append(f"{i}. {s.title}: {snippet(s, question)}")
    lines.append(msg(lang, "footer"))
    return "\n".join(lines)


def lookups_enabled() -> bool:
    """VISION_AGENT_HELP_LOOKUPS=0 關掉問答路徑的即時查詢（只剩文件）。"""
    return str(providers._cfg("AGENT_HELP_LOOKUPS") or "1").strip().lower() not in ("0", "false", "off", "no")


def parse_actions(text: str) -> tuple[str, list[dict[str, Any]]]:
    """把回覆尾端的 `ACTIONS: [...]` 抽出來（找不到或壞掉就當沒有）；回 (去掉那行的文字, 原始動作清單)。"""
    m = _ACTIONS_LINE.search(text or "")
    if not m:
        return (text or "").strip(), []
    try:
        raw = json.loads(m.group(1))
    except ValueError:
        return (text or "").strip(), []
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    return cleaned, [a for a in raw if isinstance(a, dict)] if isinstance(raw, list) else []


def validate_actions(raw: list[dict[str, Any]], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """只留合法的動作：navigate 的路由要對得上介面地圖（分頁要存在）、focus_node／open_tool 要有流程與節點（圖有給時節點要存在）。"""
    ctx = context or {}
    graph = ctx.get("graph") if isinstance(ctx.get("graph"), dict) else None
    node_ids = {str(n.get("id")) for n in (graph or {}).get("nodes", []) if isinstance(n, dict)} if graph else None
    out: list[dict[str, Any]] = []
    for a in raw[:3]:
        kind = str(a.get("kind") or "")
        label = str(a.get("label") or "")[:80]
        if kind == "navigate":
            to = str(a.get("to") or "").split("?")[0].strip()
            page = ui_page_for(to) if to.startswith("/") else None
            if not page:
                continue
            tab = str(a.get("tab") or "")
            if tab and not any(t.get("key") == tab for t in page.get("tabs") or []):
                tab = ""
            item: dict[str, Any] = {"kind": "navigate", "to": to, "label": label or str((page.get("names") or {}).get("en") or to)}
            if tab:
                item["tab"] = tab
            out.append(item)
        elif kind in ("focus_node", "open_tool"):
            node = str(a.get("node") or "")
            if not node or (node_ids is not None and node not in node_ids) or not ctx.get("flow_id"):
                continue
            out.append({"kind": kind, "node": node, "flow_id": int(ctx["flow_id"]), "label": label or node})
    return out


def rule_actions(question: str, hits: list[tuple[Section, float]], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """離線規則：問「在哪裡」時，用問題本身檢索前 20 名，第一個介面地圖段給一個「前往」動作（路由不含參數才給得出來）。"""
    if not _WHERE.search(question):
        return []
    pool = [s for s, _ in hits[:TOP_K] if s.kind == "ui" and ":" not in s.anchor]
    if not pool:
        pool = [s for s, _ in search(question, k=20) if s.kind == "ui" and ":" not in s.anchor]
    if not pool:
        return []
    s = pool[0]
    page = ui_page_for(s.anchor) or {}
    lang = str((context or {}).get("lang") or "en")
    names = page.get("names") or {}
    return [{"kind": "navigate", "to": s.anchor, "label": str(names.get(lang) or names.get("en") or s.anchor)}]


def _answer_with_lookups(settings: providers.AgentSettings, system: str, text: str, principal: Any, images: list[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """帶唯讀查詢的多回合問答：模型可先查平台狀態再回答；回 (回覆文字, 查了什麼)。預算用完就要求直接回答。images＝截圖（jpeg base64）。"""
    parts: list[dict[str, Any]] = [{"type": "image", "data": b64} for b64 in (images or [])]
    parts.append({"type": "text", "text": text})
    history: list[dict[str, Any]] = [{"role": "user", "content": parts}]
    specs = lookup.specs()
    steps: list[dict[str, Any]] = []
    timeout = providers.generate_timeout()
    for turn in range(MAX_LOOKUP_TURNS + 1):
        reply = providers.complete_tools(settings, system, history, specs, timeout=timeout)
        history.append({"role": "assistant", "content": reply.text, "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in reply.calls],
                        **({"raw": reply.raw} if reply.raw else {})})
        if not reply.calls or turn == MAX_LOOKUP_TURNS:
            return reply.text, steps
        for call in reply.calls:
            result = lookup.dispatch(principal, call.name, call.args)
            steps.append({"name": call.name, "args": {k: v for k, v in (call.args or {}).items()}, **({"error": result["error"]} if "error" in result else {})})
            history.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": actions.serialize_result(result)})
        if turn == MAX_LOOKUP_TURNS - 1:
            history.append({"role": "user", "content": [{"type": "text", "text": "Lookup budget is used up: answer now with what you have."}]})
    return "", steps


def answer(question: str, settings: providers.AgentSettings, *, context: dict[str, Any] | None = None,
           history: list[dict[str, Any]] | None = None, user: Any = None, principal: Any = None, lock: dict[str, Any] | None = None,
           screenshot: str = "") -> dict[str, Any]:
    """{answer, provider, sources:[{title, page, heading, url, snippet}], warnings, actions, lookups}

    context 除了頁面種類還可帶 page（頁面快照）、activity（操作軌跡）、lang、screen；principal／lock 由端點補（呼叫者自己的身分與鎖定）；
    screenshot 是使用者主動附上的畫面（jpeg base64），只有 LLM 看得到。
    有 LLM 且供應商支援工具呼叫時，模型可先用 lookup 的唯讀查詢看平台狀態再回答；回覆尾端的 ACTIONS 行變成前端的動作晶片。
    長期記憶（notes）：使用者要它記住的事實整段進現況、評過好的相似舊問答當範例；離線時相似度夠高直接用舊回答。"""
    ctx = context or {}
    kind_label = CONTEXT_LABELS.get(str(ctx.get("kind") or ""), "")
    hits = search(question, extra_terms=f"{kind_label} {_error_terms(ctx, question)}", lang=situation.norm_lang((context or {}).get("lang")))
    facts = notes.facts_text(user)
    from apps.vision import notes as engineering_notes
    engineering = engineering_notes.prompt(ctx.get("flow_id")) if user is not None else ""
    remembered = notes.recall(user, question)
    sections = _optics_section(question) + _context_sections(ctx) + [s for s, _ in hits]
    seen: set[tuple[str, str, str]] = set()
    sections = [s for s in sections if not ((s.page, s.anchor, s.heading) in seen or seen.add((s.page, s.anchor, s.heading)))]  # type: ignore[func-returns-value]
    # 目前頁面的介面段只給模型當脈絡；除非檢索本來就命中，否則不列進參考（免得每次都出現「Interface › 目前頁」）
    hit_keys = {(s.page, s.anchor) for s, _ in hits}
    listed = [s for s in sections if not (s.kind == "ui" and (s.page, s.anchor) not in hit_keys)]
    sources = [{"title": s.title, "page": s.page, "heading": s.heading, "url": s.url, "snippet": snippet(s, question), "kind": s.kind} for s in listed[:TOP_K + 1]]
    warnings: list[str] = []
    if providers.available(settings):
        try:
            where = situation.describe(ctx, principal=principal, lock=lock)
            if engineering:
                where += "\n" + engineering
            if facts:
                where = (where + "\n" if where else "") + "Things the user asked you to remember:\n" + facts
            if screenshot:
                where = (where + "\n" if where else "") + "A screenshot of the user's current screen is attached; read it before answering."
            turns = [h for h in (history or []) if isinstance(h, dict) and str(h.get("text") or "").strip()][-6:]
            recent = "\n".join(f"{'使用者' if h.get('role') == 'user' else '助理'}：{str(h.get('text'))[:300]}" for h in turns)
            docs_text = "\n\n".join(f"《{s.title}》\n{s.text[:MAX_SECTION_CHARS]}" for s in sections[:TOP_K + 1])
            lang_name = {"en": "English", "zh-Hant": "Traditional Chinese (繁體中文)", "zh-Hans": "Simplified Chinese (简体中文)"}[situation.norm_lang(ctx.get("lang"))]
            text = "\n\n".join(x for x in [("Current situation:\n" + where) if where else "", ("最近對話：\n" + recent) if recent else "", notes.examples_text(remembered),
                                           "文件片段：\n" + docs_text, f"問題：{question[:4000]}", f"Answer language: {lang_name}."] if x)
            system = HELP_SYSTEM + "\n\n" + skills.with_custom(skills.platform_text(), "platform", user)[:2500] + "\n\n" + ui_brief(str(ctx.get("lang") or "en"))
            if ctx.get("kind") == "inspect":
                system += "\n\n" + INSPECT_GUIDANCE
            images = [screenshot] if screenshot else []
            steps: list[dict[str, Any]] = []
            reply = ""
            if lookups_enabled() and principal is not None and settings.provider in providers._TOOL_IMPL:
                try:
                    reply, steps = _answer_with_lookups(settings, system, text, principal, images)
                except Exception as exc:  # noqa: BLE001 - 工具呼叫失敗就退回一般問答
                    log.warning("說明問答工具呼叫失敗，退回單次問答：%s", exc)
                    warnings.append(msg(ctx.get("lang"), "lookup_failed", reason=providers._explain(exc, providers.generate_timeout())))
                    steps = []
            if not (reply and reply.strip()):
                reply = providers.complete(settings, system, images, text)
            if reply and reply.strip():
                cleaned, raw_actions = parse_actions(reply)
                # 模型沒給 ACTIONS 時，問「在哪裡」仍由規則補一個「前往」（實測 Gemini 常略過選填的那一行）
                return {"answer": cleaned, "provider": settings.provider, "sources": sources, "warnings": warnings,
                        "actions": validate_actions(raw_actions, ctx) or rule_actions(question, hits, ctx), "lookups": steps}
            warnings.append(msg(ctx.get("lang"), "empty_reply", provider=settings.provider))
        except Exception as exc:  # noqa: BLE001
            log.warning("說明問答 LLM 失敗：%s", exc)
            warnings.append(msg(ctx.get("lang"), "llm_failed", provider=settings.provider, reason=providers._explain(exc, providers.generate_timeout())))
    if screenshot:
        warnings.append(msg(ctx.get("lang"), "no_screenshot"))
    if remembered and remembered[0][1] >= notes.DIRECT_MIN:
        # 這位使用者評過好的、幾乎同一個問題：直接用舊回答（仍附這次檢索到的參考）
        return {"answer": remembered[0][0].answer, "provider": "memory", "sources": sources, "warnings": warnings, "actions": rule_actions(question, hits, ctx), "lookups": []}
    return {"answer": offline_answer(question, hits, context=ctx), "provider": "rules", "sources": sources, "warnings": warnings,
            "actions": rule_actions(question, hits, ctx), "lookups": []}


def index_stats() -> dict[str, Any]:
    idx = build_index()
    return {"sections": len(idx.sections), "pages": len({s.page for s in idx.sections if s.kind == "doc"}), "tools": sum(1 for s in idx.sections if s.kind == "tool"),
            "ui_pages": sum(1 for s in idx.sections if s.kind == "ui")}

