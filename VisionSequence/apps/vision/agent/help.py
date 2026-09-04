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
    "index.html": "總覽", "workflow-design.html": "工作流程設計手冊", "architecture.html": "設計手冊", "automation.html": "自動化整合", "modbus.html": "Modbus 輸出",
    "dl.html": "深度學習教導", "plugins.html": "擴充外掛", "contract.html": "前後端合約", "glossary.html": "名詞規範", "golden.html": "Golden Set 與匯出",
    "batch.html": "批次測試", "performance.html": "效能報告", "vision-capabilities.html": "檢測功能設計", "samples.html": "範例樣板", "agent.html": "AI 助手", "user-guide.html": "使用者手冊", "capture-client.html": "擷取端", "deployment.html": "部署與維運",
}
#: 使用者手冊與 AI 助手／批次頁最貼近操作，檢索時略加權；合約／設計手冊偏工程。
PAGE_BOOST = {"user-guide.html": 1.4, "batch.html": 1.2, "agent.html": 1.1, "capture-client.html": 1.1, "golden.html": 1.1, "dl.html": 1.1, "automation.html": 1.1, "contract.html": 0.8, "architecture.html": 0.8, "performance.html": 0.7, "deployment.html": 0.9}
MAX_SECTION_CHARS = 1400
TOP_K = 5

HELP_SYSTEM = """你是 VisionSequence 機器視覺平台的使用說明助理。
- 只依下面提供的文件片段回答；文件沒有涵蓋就直說「文件沒有提到」並建議可能相關的頁面，不要臆測功能。
- 繁體中文、先給結論再給步驟、條列為主、不超過 300 字；提到操作時用介面上的按鈕與頁面名稱（例如「批次測試」頁的「新增影像集」）。
- 回答最後另起一行「參考：」列出你用到的章節名稱（用《頁面 › 章節》格式）。
- 使用者若問的是要改流程或參數，提醒可在流程編輯器或批次測試頁直接請助手修改。"""


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
        out.append(Section("agent.html", "AI 技能", f"工具：{t.label}（{t.key}）", "skills", _strip(text)[:MAX_SECTION_CHARS * 2], kind="tool"))
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
    q = tokenize(f"{query} {extra_terms}")
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
        out.append(Section("agent.html", "AI 技能", f"工具：{t.label}（{t.key}）", "skills", _strip(skills.skill_text(node_type))[:MAX_SECTION_CHARS * 2], kind="tool"))
    return out


CONTEXT_LABELS = {"flow_editor": "流程編輯器", "tool": "工具頁", "batch": "批次測試頁", "golden": "Golden Set 頁", "agent": "AI 助手頁", "dl": "深度學習頁", "sources": "影像來源庫", "assets": "資產庫", "dashboard": "總覽", "page": ""}


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

