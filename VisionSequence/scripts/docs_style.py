"""docs/*.html 的版面產生器：統一內嵌 CSS、左側章節目錄（由 h2／h3 靜態產生）、章節與內文字級階層。

用法：
    .venv/Scripts/python.exe scripts/docs_style.py          # 重新套用到 docs/ 全部頁面（可重複執行）
    .venv/Scripts/python.exe scripts/docs_style.py --check  # 只檢查是否已是最新版面（CI／驗證用）

每頁仍是獨立 HTML、無外部依賴（CLAUDE.md 規範）：本腳本把同一段 CSS 寫進每頁的 <style>，
並在 <article class="doc"> 外包 .doc-layout、前面插入 <aside class="toc">（本頁目錄）。
h2 沒有 id 的會補 sec-N；頁內原本的 <nav>（舊的內文目錄）會移除，改由側欄提供。
"""

from __future__ import annotations

import html
import os
import re
import sys

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

CSS = """
  :root {
    --bg:#f5f7fa; --paper:#ffffff; --ink:#26303f; --head:#0f1a2b; --muted:#5b6b80; --subtle:#8a97a8;
    --line:#e2e8f0; --brand:#2563eb; --brand-ink:#1d4ed8; --brand-soft:#eef4ff;
    --code-bg:#f1f5f9; --code-ink:#334155; --pre-bg:#0f172a; --pre-ink:#dce6f2;
    --toc-w:250px; --top-h:52px;
  }
  * { box-sizing:border-box; }
  html { scroll-behavior:smooth; }
  body { margin:0; background:var(--bg); color:var(--ink); font-family:"Segoe UI",system-ui,"Noto Sans TC","Microsoft JhengHei",sans-serif; line-height:1.8; font-size:16px; -webkit-font-smoothing:antialiased; }

  /* 頂列：站內導覽 */
  /* 單列、可橫向捲動：頂列高度固定，側欄 sticky 的位置才不會被第二列蓋住 */
  nav.site { position:sticky; top:0; z-index:20; display:flex; flex-wrap:nowrap; overflow-x:auto; scrollbar-width:none; align-items:center; gap:.15rem; min-height:var(--top-h); padding:.5rem 1.4rem; background:rgba(255,255,255,.94); backdrop-filter:blur(8px); border-bottom:1px solid var(--line); font-size:.84rem; }
  nav.site::-webkit-scrollbar { display:none; }
  nav.site::before { content:"VisionSequence"; margin-right:.9rem; padding:.15rem .6rem; border-radius:6px; background:var(--brand); color:#fff; font-weight:700; letter-spacing:.03em; font-size:.78rem; }
  nav.site a { color:var(--muted); text-decoration:none; padding:.26rem .62rem; border-radius:999px; white-space:nowrap; }
  nav.site a:hover { color:var(--brand-ink); background:var(--brand-soft); }
  nav.site a[aria-current="page"] { color:var(--brand-ink); background:var(--brand-soft); font-weight:600; }

  /* 兩欄：左側本頁目錄（sticky）＋內文 */
  .doc-layout { display:flex; align-items:flex-start; gap:3rem; max-width:1320px; margin:0 auto; padding:2.2rem 2rem 6rem; }
  aside.toc { flex:0 0 var(--toc-w); position:sticky; top:calc(var(--top-h) + 1rem); max-height:calc(100vh - var(--top-h) - 2rem); overflow-y:auto; padding:.2rem 1rem .6rem 0; border-right:1px solid var(--line); font-size:.86rem; line-height:1.5; scrollbar-width:thin; }
  aside.toc .toc-title { margin:0 0 .7rem; font-size:.72rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--subtle); }
  aside.toc ul { list-style:none; margin:0; padding:0; }
  aside.toc li { margin:0; }
  aside.toc a { display:block; padding:.34rem .6rem .34rem .7rem; margin:.05rem 0; border-left:2px solid transparent; border-radius:0 6px 6px 0; color:var(--muted); text-decoration:none; overflow-wrap:anywhere; }
  aside.toc a:hover { color:var(--brand-ink); background:var(--brand-soft); }
  aside.toc a.active { color:var(--brand-ink); border-left-color:var(--brand); background:var(--brand-soft); font-weight:600; }
  aside.toc ul ul a { padding-left:1.6rem; font-size:.82rem; color:var(--subtle); }
  aside.toc ul ul a.active { color:var(--brand-ink); }

  article.doc { flex:1 1 auto; min-width:0; max-width:880px; }
  article.doc.wide { max-width:1040px; }

  /* 字級階層：標題明顯大於內文，段落之間留白 */
  h1 { font-size:2.1rem; line-height:1.28; color:var(--head); letter-spacing:-.02em; margin:.2rem 0 1.4rem; font-weight:700; }
  h1::after { content:""; display:block; width:64px; height:4px; margin-top:.7rem; border-radius:2px; background:linear-gradient(90deg,var(--brand),#7c3aed); }
  h2 { font-size:1.5rem; line-height:1.35; color:var(--head); font-weight:700; margin:3.4rem 0 1.1rem; padding:.35rem .8rem .35rem .85rem; border-left:4px solid var(--brand); background:linear-gradient(90deg,var(--brand-soft),transparent 70%); border-radius:0 8px 8px 0; scroll-margin-top:calc(var(--top-h) + 1rem); }
  h2:first-of-type { margin-top:2.4rem; }
  h3 { font-size:1.15rem; line-height:1.4; color:var(--head); font-weight:650; margin:2.3rem 0 .75rem; scroll-margin-top:calc(var(--top-h) + 1rem); }
  h4 { font-size:1rem; color:var(--head); margin:1.6rem 0 .5rem; }
  p { margin:.85rem 0; }
  p.lead { font-size:1.05rem; color:var(--muted); }
  a { color:var(--brand-ink); text-decoration-color:#b6ccf5; text-underline-offset:2px; }
  a:hover { text-decoration-color:var(--brand-ink); }
  strong { color:var(--head); }
  code { font-family:ui-monospace,Consolas,"Cascadia Mono",monospace; font-size:.86em; background:var(--code-bg); color:var(--code-ink); border:1px solid var(--line); border-radius:5px; padding:.08em .38em; overflow-wrap:anywhere; }
  pre { background:var(--pre-bg); color:var(--pre-ink); border-radius:10px; padding:1.05rem 1.2rem; margin:1.1rem 0; overflow-x:auto; line-height:1.65; font-size:.84em; }
  pre code { background:none; border:none; color:inherit; padding:0; }
  td pre { margin:.35rem 0; padding:.5rem .7rem; font-size:.82em; }
  table { width:100%; border-collapse:separate; border-spacing:0; margin:1.3rem 0; font-size:.92em; background:var(--paper); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th { background:#f3f6fa; color:var(--head); text-align:left; font-weight:600; padding:.6rem .8rem; border-bottom:1px solid var(--line); }
  td { padding:.55rem .8rem; border-bottom:1px solid var(--line); vertical-align:top; }
  tr:last-child td { border-bottom:none; }
  tr:nth-child(even) td { background:#fafcff; }
  ul, ol { padding-left:1.5rem; margin:.7rem 0; }
  li { margin:.4rem 0; }
  li > ul, li > ol { margin:.3rem 0; }
  .note { background:#fff8e6; border:1px solid #f5d98f; border-left:4px solid #f59e0b; border-radius:8px; padding:.7rem 1rem; margin:1.3rem 0; }
  blockquote { margin:1.3rem 0; padding:.8rem 1.15rem; background:var(--paper); border:1px solid var(--line); border-left:4px solid #94a3b8; border-radius:8px; color:#475569; }
  hr { border:none; border-top:1px solid var(--line); margin:2.6rem 0; }
  img { max-width:100%; border-radius:8px; }
  .wrap { overflow-x:auto; }
  .good { color:#15803d; font-weight:600; }
  .bad { color:#b91c1c; }
  .noise { color:#94a3b8; }
  .num td:nth-child(n+2), .num th:nth-child(n+2) { text-align:right; font-variant-numeric:tabular-nums; }

  @media (max-width:960px) {
    .doc-layout { flex-direction:column; gap:1.4rem; padding:1.4rem 1rem 4rem; }
    aside.toc { position:static; max-height:none; flex:none; width:100%; border-right:none; border-bottom:1px solid var(--line); padding:0 0 .8rem; }
    aside.toc ul { columns:2; column-gap:1.5rem; }
    aside.toc li { break-inside:avoid; }
    aside.toc ul ul { columns:1; }
    h1 { font-size:1.6rem; }
    h2 { font-size:1.28rem; margin-top:2.4rem; }
  }
  @media print {
    nav.site, aside.toc { display:none; }
    .doc-layout { display:block; padding:0; }
    body { background:#fff; }
  }
"""

SCRIPT = """<script>
// 本頁目錄：捲動時標出目前章節（無 JS 也能用，只是沒有高亮）
(function () {
  var site = document.querySelector('nav.site');
  if (site) document.documentElement.style.setProperty('--top-h', site.offsetHeight + 'px');
  var links = Array.prototype.slice.call(document.querySelectorAll('aside.toc a[href^="#"]'));
  if (!links.length || !('IntersectionObserver' in window)) return;
  var byId = {};
  links.forEach(function (a) { byId[a.getAttribute('href').slice(1)] = a; });
  var current = null;
  function activate(id) {
    if (current === id) return;
    current = id;
    links.forEach(function (a) { a.classList.toggle('active', a.getAttribute('href') === '#' + id); });
    var a = byId[id];
    if (a && a.scrollIntoView) { try { a.scrollIntoView({ block: 'nearest' }); } catch (e) {} }
  }
  var heads = Array.prototype.slice.call(document.querySelectorAll('article.doc h2[id], article.doc h3[id]')).filter(function (h) { return byId[h.id]; });
  var observer = new IntersectionObserver(function () {
    var top = window.scrollY + 90, best = heads[0];
    for (var i = 0; i < heads.length; i++) { if (heads[i].offsetTop <= top) best = heads[i]; else break; }
    if (best) activate(best.id);
  }, { rootMargin: '-80px 0px -60% 0px', threshold: [0, 1] });
  heads.forEach(function (h) { observer.observe(h); });
  window.addEventListener('scroll', function () { var top = window.scrollY + 90, best = heads[0]; for (var i = 0; i < heads.length; i++) { if (heads[i].offsetTop <= top) best = heads[i]; else break; } if (best) activate(best.id); }, { passive: true });
})();
</script>"""

#: 個別頁面額外的規則（效能報告的數值表右對齊）；其餘頁面共用同一段 CSS。
PAGE_EXTRA = {
    "performance.html": "\n  td:nth-child(n+2), th:nth-child(n+2) { text-align:right; font-variant-numeric:tabular-nums; }\n  table { font-size:.85em; }\n",
}

H_RE = re.compile(r"<h([23])([^>]*)>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)


def _text(inner: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()


def _ensure_ids(body: str) -> str:
    """h2／h3 沒有 id 的補 sec-N（h3 用 sec-N-M）。"""
    n2 = 0
    n3 = 0

    def fix(m: re.Match) -> str:
        nonlocal n2, n3
        level, attrs, inner = m.group(1), m.group(2), m.group(3)
        if level == "2":
            n2 += 1
            n3 = 0
        else:
            n3 += 1
        if re.search(r'\bid="', attrs):
            return m.group(0)
        sid = f"sec-{n2}" if level == "2" else f"sec-{n2}-{n3}"
        return f'<h{level} id="{sid}"{attrs}>{inner}</h{level}>'

    return H_RE.sub(fix, body)


def _toc(body: str) -> str:
    items: list[tuple[str, str, str]] = []
    for m in H_RE.finditer(body):
        level, attrs, inner = m.group(1), m.group(2), m.group(3)
        mid = re.search(r'\bid="([^"]+)"', attrs)
        if not mid:
            continue
        items.append((level, mid.group(1), _text(inner)))
    if not items:
        return ""
    out = ['<aside class="toc" aria-label="本頁目錄"><p class="toc-title">本頁目錄</p><ul>']
    open_sub = False
    for level, sid, title in items:
        if level == "2":
            if open_sub:
                out.append("</ul></li>")
                open_sub = False
            elif out[-1] != '<aside class="toc" aria-label="本頁目錄"><p class="toc-title">本頁目錄</p><ul>':
                out.append("</li>")
            out.append(f'<li><a href="#{sid}">{html.escape(title)}</a>')
        else:
            if not open_sub:
                out.append("<ul>")
                open_sub = True
            out.append(f'<li><a href="#{sid}">{html.escape(title)}</a></li>')
    if open_sub:
        out.append("</ul></li>")
    else:
        out.append("</li>")
    out.append("</ul></aside>")
    return "".join(out)


def render(src: str, name: str = "") -> str:
    # 1. CSS（共用一段＋頁面額外規則）
    if "<style>" not in src:
        raise ValueError("沒有 <style>")
    css = CSS + PAGE_EXTRA.get(name, "")
    src = re.sub(r"<style>.*?</style>", lambda _m: "<style>" + css + "</style>", src, count=1, flags=re.DOTALL)
    # 2. 拆出 article
    m = re.search(r'<article class="doc[^"]*"[^>]*>', src)
    if not m:
        raise ValueError("沒有 <article class=\"doc\">")
    open_tag = m.group(0)
    start = m.end()
    end = src.index("</article>", start)
    body = src[start:end]
    # 舊版包裝／側欄／內文目錄一律拆掉再重建（可重複執行）
    body = re.sub(r'<aside class="toc".*?</aside>', "", body, count=1, flags=re.DOTALL)
    body = re.sub(r"<nav>\s*<p><strong>[^<]*目錄</strong></p>.*?</nav>\s*", "", body, count=1, flags=re.DOTALL)
    body = re.sub(r"<nav>\s*<ul>.*?</ul>\s*</nav>\s*", "", body, count=1, flags=re.DOTALL)
    body = _ensure_ids(body)
    toc = _toc(body)
    before = src[: m.start()]
    after = src[end + len("</article>"):]
    # 重跑：把上一次產生的 .doc-layout 包裝、側欄與結尾標記清掉再重建
    before = re.sub(r'<div class="doc-layout">\s*(<aside class="toc".*?</aside>)?\s*$', "", before, flags=re.DOTALL)
    after = re.sub(r"^\s*</div><!-- /doc-layout -->", "", after, count=1)
    src = before + '<div class="doc-layout">' + toc + open_tag + body + "</article></div><!-- /doc-layout -->" + after
    # 3. 高亮腳本
    src = re.sub(r"<script>\s*// 本頁目錄.*?</script>\s*", "", src, count=1, flags=re.DOTALL)
    src = src.replace("</body>", SCRIPT + "\n</body>", 1)
    return src


def main() -> int:
    check = "--check" in sys.argv
    changed = []
    for name in sorted(os.listdir(DOCS)):
        if not name.endswith(".html"):
            continue
        path = os.path.join(DOCS, name)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        out = render(src, name)
        if out != src:
            changed.append(name)
            if not check:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(out)
    if check:
        print("需要重新套用：" + ", ".join(changed) if changed else "docs 版面已是最新")
        return 1 if changed else 0
    print(f"已套用 {len(changed)} 頁：" + ", ".join(changed) if changed else "沒有變更")
    return 0


if __name__ == "__main__":
    sys.exit(main())
