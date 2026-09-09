"""把 docs/*.html 的使用者指南頁面轉成 docs/guide/en/<page>.md（Markdown 是之後的正本，HTML 轉完就退場）。

用法：
    .venv/Scripts/python.exe scripts/docs_to_guide.py            # 轉九頁
    .venv/Scripts/python.exe scripts/docs_to_guide.py samples    # 只轉一頁

只轉 `<article class="doc">` 內文（版面、側欄目錄、腳本都是 docs_style.py 產生的，不進 Markdown）。
- h1～h4 → `#`～`####`（保留 id 當錨點：`## Title {#id}`，前端與 help.py 都用這個錨點）
- p／ul／ol／li／strong／em／code／a／br／table → Markdown（表格用 GFM 語法，儲存格內的換行改成空白）
- `<figure class="shot">…</figure>`（截圖＋編號說明）**原樣保留成 HTML 區塊**：Markdown 表達不了「圖＋對應編號的說明」，
  marked 允許內嵌 HTML，前端用同一段樣式畫；圖片路徑改成絕對的 `/docs/img/…`
- 其餘沒列到的標籤（div／span／pre）：div／span 拆掉只留內容，pre 變成程式碼區塊
"""
from __future__ import annotations

import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "guide" / "en"
GUIDE_PAGES = ("user-guide", "samples", "vision-capabilities", "calibration", "batch", "dl", "agent", "golden", "glossary")
#: 內文連到其他 docs 頁的連結：使用者指南頁改成 guide 內部連結，工程頁維持 /docs/
INTERNAL = {f"{p}.html": p for p in GUIDE_PAGES}


class Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.list_stack: list[tuple[str, int]] = []  # (ul|ol, counter)
        self.figure_depth = 0
        self.figure_buf: list[str] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.header_rows = 0
        self.in_pre = False
        self.href = ""
        self.link_text: list[str] = []

    # ---- 輸出 ----
    def emit(self, text: str) -> None:
        if self.figure_depth:
            self.figure_buf.append(text)
        elif self.href:
            self.link_text.append(text)  # 連結要先於儲存格：表格裡的連結文字才不會被儲存格吃掉
        elif self.cell is not None:
            self.cell.append(text)
        else:
            self.out.append(text)

    def block(self) -> None:
        """段落分隔：確保前面有一個空行。"""
        if self.figure_depth or self.cell is not None:
            return
        while self.out and self.out[-1] == "\n":
            self.out.pop()
        if self.out:
            self.out.append("\n\n")

    # ---- 標籤 ----
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if self.figure_depth:
            if tag == "img" and a.get("src", "").startswith("img/"):
                a["src"] = "/docs/" + a["src"]
            self.figure_buf.append(_open(tag, a))
            if tag == "figure":
                self.figure_depth += 1
            return
        if tag == "figure":
            self.block()
            self.figure_depth = 1
            self.figure_buf = [_open(tag, a)]
            return
        self.stack.append(tag)
        if tag in ("h1", "h2", "h3", "h4"):
            self.block()
            self.emit("#" * int(tag[1]) + " ")
            self._heading_id = a.get("id", "")
        elif tag == "p":
            self.block()
        elif tag in ("ul", "ol"):
            self.block()
            self.list_stack.append((tag, 0))
        elif tag == "li":
            kind, n = self.list_stack[-1] if self.list_stack else ("ul", 0)
            if self.list_stack:
                self.list_stack[-1] = (kind, n + 1)
            indent = "  " * (len(self.list_stack) - 1)
            if self.out and not self.out[-1].endswith("\n"):
                self.out.append("\n")
            self.emit(f"{indent}{n + 1}. " if kind == "ol" else f"{indent}- ")
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag in ("em", "i"):
            self.emit("*")
        elif tag == "code" and not self.in_pre:
            self.emit("`")
        elif tag == "pre":
            self.block()
            self.in_pre = True
            self.emit("```\n")
        elif tag == "a":
            self.href = a.get("href", "")
            self.link_text = []
        elif tag == "br":
            self.emit(" " if self.cell is not None else "  \n")
        elif tag == "table":
            self.block()
            self.table, self.header_rows = [], 0
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
            if tag == "th":
                self._th = True
        elif tag == "hr":
            self.block()
            self.emit("---")

    def handle_endtag(self, tag: str) -> None:
        if self.figure_depth:
            self.figure_buf.append(f"</{tag}>")
            if tag == "figure":
                self.figure_depth -= 1
                if self.figure_depth == 0:
                    self.block()
                    self.out.append("".join(self.figure_buf))
                    self.out.append("\n\n")
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        if tag in ("h1", "h2", "h3", "h4"):
            hid = getattr(self, "_heading_id", "")
            if hid:
                self.emit(f" {{#{hid}}}")
            self.emit("\n\n")
        elif tag == "p":
            self.emit("\n\n")
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            self.emit("\n")
        elif tag == "li":
            self.emit("\n")
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag in ("em", "i"):
            self.emit("*")
        elif tag == "code" and not self.in_pre:
            self.emit("`")
        elif tag == "pre":
            self.in_pre = False
            self.emit("\n```\n\n")
        elif tag == "a":
            text = "".join(self.link_text).strip() or self.href
            href = self.href
            self.href, self.link_text = "", []
            self.emit(_link(text, href))
        elif tag in ("td", "th"):
            text = re.sub(r"\s+", " ", "".join(self.cell or [])).strip().replace("|", "\\|")
            if self.row is not None:
                self.row.append(text)
            self.cell = None
        elif tag == "tr":
            if self.table is not None and self.row is not None:
                self.table.append(self.row)
                if getattr(self, "_th", False):
                    self.header_rows += 1
            self.row = None
            self._th = False
        elif tag == "table":
            if self.table:
                width = max(len(r) for r in self.table)
                rows = [r + [""] * (width - len(r)) for r in self.table]
                head = rows[0] if self.header_rows else [""] * width
                body = rows[1:] if self.header_rows else rows
                lines = ["| " + " | ".join(head) + " |", "|" + "---|" * width] + ["| " + " | ".join(r) + " |" for r in body]
                self.out.append("\n".join(lines) + "\n\n")
            self.table = None

    def handle_data(self, data: str) -> None:
        if self.figure_depth:
            self.figure_buf.append(html.escape(data, quote=False))
            return
        if self.in_pre:
            self.emit(data)
            return
        text = re.sub(r"\s+", " ", data)
        if not text.strip():
            if text and self.out and not self.out[-1].endswith(("\n", " ")):
                self.emit(" ")
            return
        # 段落開頭不要留前導空白
        if self.out and self.out[-1].endswith("\n") and self.cell is None and not self.href:
            text = text.lstrip()
        self.emit(text)

    def result(self) -> str:
        text = "".join(self.out)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def _open(tag: str, attrs: dict[str, str]) -> str:
    inner = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in attrs.items())
    return f"<{tag}{inner}>"


def _link(text: str, href: str) -> str:
    page, _, anchor = href.partition("#")
    if page in INTERNAL:
        target = f"{INTERNAL[page]}.md" + (f"#{anchor}" if anchor else "")
    elif page.endswith(".html") and "/" not in page:
        target = f"/docs/{page}" + (f"#{anchor}" if anchor else "")
    else:
        target = href
    return f"[{text}]({target})"


def convert(page: str) -> Path:
    raw = (DOCS / f"{page}.html").read_text(encoding="utf-8")
    m = re.search(r"<article[^>]*>(.*)</article>", raw, re.S)
    if not m:
        raise SystemExit(f"{page}.html has no <article>")
    body = m.group(1)
    title = re.search(r"<title>(.*?)</title>", raw, re.S)
    conv = Converter()
    conv.feed(body)
    md = conv.result()
    # 第一個 h1 就是頁標題；沒有的話用 <title>
    if not md.startswith("# "):
        md = f"# {html.unescape(title.group(1).strip()) if title else page}\n\n" + md
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{page}.md"
    dest.write_text(md, encoding="utf-8")
    return dest


def main(argv: list[str]) -> int:
    pages = argv or list(GUIDE_PAGES)
    for page in pages:
        dest = convert(page)
        text = dest.read_text(encoding="utf-8")
        print(f"{page:22s} -> {dest.relative_to(ROOT)}  {len(text):7d} chars, {text.count(chr(10))} lines, {text.count('<figure')} figures, {text.count('|---')} tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
