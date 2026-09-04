"""平台使用說明問答：把 docs/*.html 拆成章節＋名詞規範表＋每個工具的技能建成檢索索引（BM25，中文用雙字詞），
依問題找最相關的幾段，LLM 可用時以文件片段為依據回答（引用章節），離線時直接回文件片段與連結。

索引在第一次查詢時建立並快取（docs 檔案有更新就重建）；docs 由 Django 在 /docs/<page>.html 提供，回答附的 url 可直接開。"""

from __future__ import annotations

import html
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apps.vision.agent import providers, skills
from apps.vision.tools import base as tools

log = logging.getLogger("vision.agent")

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"
PAGE_TITLES = {
    "index.html": "Overview", "workflow-design.html": "Workflow design", "architecture.html": "Architecture", "automation.html": "Automation", "modbus.html": "Modbus",
    "dl.html": "Deep learning", "plugins.html": "Plugins", "contract.html": "Contract", "glossary.html": "Glossary", "golden.html": "Golden Set",
    "batch.html": "Batch testing", "performance.html": "Performance", "vision-capabilities.html": "Inspection capabilities", "samples.html": "Example templates",
    "agent.html": "AI assistant", "user-guide.html": "User guide", "capture-client.html": "Capture client", "deployment.html": "Deployment",
}
#: 使用者手冊與 AI 助手／批次頁最貼近操作，檢索時略加權；合約／設計手冊偏工程。
PAGE_BOOST = {"user-guide.html": 1.4, "batch.html": 1.2, "agent.html": 1.1, "capture-client.html": 1.1, "golden.html": 1.1, "dl.html": 1.1, "automation.html": 1.1, "contract.html": 0.8, "architecture.html": 0.8, "performance.html": 0.7, "deployment.html": 0.9}
MAX_SECTION_CHARS = 1400
TOP_K = 5

HELP_SYSTEM = """You are the documentation assistant for VisionSequence, a machine vision platform.
- Answer only from the documentation excerpts below. If they do not cover it, say so plainly, suggest the page that might, and never invent a feature.
- Reply in the same language the question was asked in (the documentation is English; translate what you quote when the question is not).
- Conclusion first, then the steps; mostly bullets; under 300 words. Name the buttons and pages as the interface shows them ("New image set" on the Batch testing page).
- End with a separate line starting "References:" listing the sections you used, as Page > Section.
- If the question is about changing a flow or a parameter, mention that the assistant can make the change directly in the flow editor or on the batch page."""

#: 中英對照：docs 是英文，中文提問先把詞彙補成英文再檢索（來源＝docs/glossary.html 的對照表）。
BILINGUAL = {
    "影像來源": "image source camera", "來源": "source", "資料夾": "folder", "相機": "camera", "取像": "acquire grab image",
    "擷取端": "capture client", "通道": "channel", "共享記憶體": "shared memory", "連續串流": "continuous stream",
    "依需求取像": "on demand grab", "流程": "flow graph", "步驟": "node step", "工具": "tool", "連線": "edge connection",
    "埠": "port", "參數": "parameter param", "教導參數": "teaching parameter teach", "參數卡": "teach page",
    "區域": "region roi", "標記": "overlay label", "執行": "run execute", "試執行": "preview", "執行一次": "run once",
    "連續執行": "continuous", "暫存影像": "scratch image", "資產": "asset", "判定": "judge verdict",
    "具名輸出": "named output", "引擎鎖定": "engine lock locked 423", "鎖定": "lock locked", "整合方": "integrator api key",
    "金鑰": "api key", "角色": "role", "管理員": "administrator admin", "工程師": "engineer", "操作員": "operator",
    "重置": "reset", "範本": "template", "範本畫廊": "template gallery", "範例樣板": "example template sample",
    "註解": "note", "批次測試": "batch testing", "影像集": "image set", "批次執行": "batch run",
    "資料洞察": "insights", "建議門檻": "threshold suggestion", "資料諮詢": "consult", "全域 AI 助手": "assistant dock",
    "使用說明": "help documentation", "助手": "assistant", "工作階段": "agent session", "先驗": "prior",
    "代理模式": "agentic mode", "步驟時間軸": "step timeline", "候選方案": "candidate", "影像標記": "image label",
    "自動調參": "autotune auto-tune coordinate descent", "定位補正": "locate correction fixture", "定位": "locate template match",
    "統計": "statistics stats yield", "每小時彙總": "hourly rollup", "影像封存": "image archive", "流程版本": "flow version",
    "操作紀錄": "audit log", "站台": "station", "站台看板": "fleet board", "整合頁": "integration page",
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
    "監控": "monitor health", "卡尺": "caliper", "找圓": "find_circle circle", "找線": "find_line line",
    "量測": "measure measurement", "公差": "tolerance", "寬度": "width", "直徑": "diameter", "角度": "angle",
    "顏色": "colour color", "缺陷": "defect", "瑕疵": "defect scratch", "條碼": "barcode", "計數": "count blob",
    "門檻": "threshold", "二值化": "threshold binarise", "面積": "area", "圓形度": "circularity",
    "金字塔": "pyramid", "範本比對": "template_match template matching", "形狀": "shape", "多邊形": "polygon",
    "矩形": "rect rectangle", "環形": "annulus", "橢圓": "ellipse", "折線": "polyline",
    "使用者": "user account", "帳號": "account user", "登入": "sign in login", "密碼": "password",
    "文案": "wording tone copy", "用詞": "wording terminology", "規範": "convention rule glossary",
    "產線畫面": "station screen operator", "良率": "yield", "不良": "reject ng", "看板": "board dashboard",
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
    kind: str = "doc"  # doc | glossary | tool
    tokens: dict[str, int] = field(default_factory=dict)
    length: int = 0

    @property
    def url(self) -> str:
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


def _tool_sections() -> list[Section]:
    out = []
    for t in tools.all_types():
        try:
            text = skills.base_skill_text(t.key)
        except KeyError:
            continue
        out.append(Section("agent.html", "AI skills", f"Tool: {t.label} ({t.key})", "skills", _strip(text)[:MAX_SECTION_CHARS * 2], kind="tool"))
    return out


def _finish(sections: list[Section]) -> Index:
    df: dict[str, int] = {}
    total = 0
    for s in sections:
        counts: dict[str, int] = {}
        for tok in tokenize(f"{s.page_title} {s.heading} {s.heading} {s.text}"):
            counts[tok] = counts.get(tok, 0) + 1
        s.tokens = counts
        s.length = sum(counts.values())
        total += s.length
        for tok in counts:
            df[tok] = df.get(tok, 0) + 1
    return Index(sections, df, (total / len(sections)) if sections else 1.0, _stamp())


def _stamp() -> float:
    try:
        return max(p.stat().st_mtime for p in DOCS_DIR.glob("*.html"))
    except ValueError:
        return 0.0


_index: Index | None = None


def build_index(force: bool = False) -> Index:
    global _index
    stamp = _stamp()
    if _index is not None and not force and _index.stamp == stamp:
        return _index
    sections: list[Section] = []
    for path in sorted(DOCS_DIR.glob("*.html")):
        try:
            sections.extend(_parse_page(path.name, path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            log.warning("說明索引：%s 解析失敗", path.name, exc_info=True)
    sections.extend(_tool_sections())
    _index = _finish(sections)
    return _index


def search(query: str, k: int = TOP_K, *, extra_terms: str = "") -> list[tuple[Section, float]]:
    """BM25（k1=1.5、b=0.75），標題命中加權、頁面加權。"""
    idx = build_index()
    q = tokenize(f"{expand_query(query)} {extra_terms}")
    if not q:
        return []
    n = len(idx.sections)
    scored: list[tuple[Section, float]] = []
    for s in idx.sections:
        score = 0.0
        head_tokens = set(tokenize(f"{s.page_title} {s.heading}"))
        for tok in set(q):
            tf = s.tokens.get(tok, 0)
            if not tf:
                continue
            dfv = idx.df.get(tok, 1)
            idf = math.log(1 + (n - dfv + 0.5) / (dfv + 0.5))
            score += idf * (tf * 2.5) / (tf + 1.5 * (0.25 + 0.75 * s.length / idx.avg_len))
            if tok in head_tokens:
                score += idf * 0.8
        if score > 0:
            scored.append((s, score * PAGE_BOOST.get(s.page, 1.0) * (0.9 if s.kind == "tool" else 1.0)))
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


def _context_sections(context: dict[str, Any] | None) -> list[Section]:
    """目前頁面的專屬資料：工具頁／編輯器選到的工具技能。"""
    out: list[Section] = []
    node_type = str((context or {}).get("node_type") or "")
    if node_type and tools.has(node_type):
        t = tools.get(node_type)
        out.append(Section("agent.html", "AI skills", f"Tool: {t.label} ({t.key})", "skills", _strip(skills.skill_text(node_type))[:MAX_SECTION_CHARS * 2], kind="tool"))
    return out


CONTEXT_LABELS = {"flow_editor": "flow editor", "tool": "tool page", "batch": "batch testing", "golden": "Golden Set", "agent": "AI assistant", "dl": "deep learning", "sources": "image sources", "assets": "assets", "dashboard": "dashboard", "page": ""}


def offline_answer(question: str, hits: list[tuple[Section, float]]) -> str:
    if not hits:
        return "文件裡找不到與問題直接相關的段落。可試著換個關鍵詞（例如功能名稱或頁面名稱），或到「說明」頁瀏覽快速上手與名詞定義。"
    lines = ["依平台文件："]
    for i, (s, _) in enumerate(hits[:3], start=1):
        lines.append(f"{i}. 《{s.title}》：{snippet(s, question)}")
    lines.append("（完整內容請見下方參考連結；離線規則模式只能節錄文件，接上 LLM 供應商可得到整理過的回答。）")
    return "\n".join(lines)


def answer(question: str, settings: providers.AgentSettings, *, context: dict[str, Any] | None = None,
           history: list[dict[str, Any]] | None = None, user: Any = None) -> dict[str, Any]:
    """{answer, provider, sources:[{title, page, heading, url, snippet}], warnings}"""
    ctx = context or {}
    kind_label = CONTEXT_LABELS.get(str(ctx.get("kind") or ""), "")
    hits = search(question, extra_terms=kind_label)
    sections = _context_sections(ctx) + [s for s, _ in hits]
    sources = [{"title": s.title, "page": s.page, "heading": s.heading, "url": s.url, "snippet": snippet(s, question), "kind": s.kind} for s in sections[:TOP_K + 1]]
    warnings: list[str] = []
    if providers.available(settings):
        try:
            where = f"使用者目前在「{kind_label}」" + (f"（流程「{ctx.get('flow_name')}」）" if ctx.get("flow_name") else "") if kind_label else ""
            turns = [h for h in (history or []) if isinstance(h, dict) and str(h.get("text") or "").strip()][-6:]
            recent = "\n".join(f"{'使用者' if h.get('role') == 'user' else '助理'}：{str(h.get('text'))[:300]}" for h in turns)
            docs_text = "\n\n".join(f"《{s.title}》\n{s.text[:MAX_SECTION_CHARS]}" for s in sections[:TOP_K + 1])
            text = "\n\n".join(x for x in [where, ("最近對話：\n" + recent) if recent else "", "文件片段：\n" + docs_text, f"問題：{question[:4000]}"] if x)
            reply = providers.complete(settings, HELP_SYSTEM + "\n\n" + skills.platform_text()[:1500], [], text)
            if reply and reply.strip():
                return {"answer": reply.strip(), "provider": settings.provider, "sources": sources, "warnings": warnings}
            warnings.append(f"LLM（{settings.provider}）回了空白，已改用文件節錄")
        except Exception as exc:  # noqa: BLE001
            log.warning("說明問答 LLM 失敗：%s", exc)
            warnings.append(f"LLM（{settings.provider}）失敗，已改用文件節錄：{providers._explain(exc, providers.generate_timeout())}")
    return {"answer": offline_answer(question, hits), "provider": "rules", "sources": sources, "warnings": warnings}


def index_stats() -> dict[str, Any]:
    idx = build_index()
    return {"sections": len(idx.sections), "pages": len({s.page for s in idx.sections if s.kind == "doc"}), "tools": sum(1 for s in idx.sections if s.kind == "tool")}

