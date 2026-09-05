"""docs/*.html 的版面產生器（Cyberpunk 風）：最左側直式「總目錄」導覽欄、其右「本頁目錄」（由 h2／h3 靜態產生）、
內文在右；章節與內文字級階層分明、排版寬鬆。

用法：
    .venv/Scripts/python.exe scripts/docs_style.py          # 重新套用到 docs/ 全部頁面（可重複執行）
    .venv/Scripts/python.exe scripts/docs_style.py --check  # 只檢查是否已是最新版面（CI／驗證用）

每頁仍是獨立 HTML、無外部依賴（CLAUDE.md 規範）：本腳本把同一段 CSS 寫進每頁的 <style>，
<nav class="site">（各頁共同的站內連結）以 CSS 變成左側直式導覽欄，並在 <article class="doc"> 外包 .doc-layout、
前面插入 <aside class="toc">（本頁目錄）。h2 沒有 id 的會補 sec-N；頁內原本的 <nav>（舊的內文目錄）會移除。
help.py 只解析 <article 之後的內容並剔除 nav.site，導覽欄與側欄都不進索引。
"""

from __future__ import annotations

import html
import os
import re
import sys

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

CSS = """
  /* Cyberpunk：深空黑＋霓虹綠／青、等寬標題、電路格線、HUD 角括號（與前端 .theme-cyber 同一套色票） */
  :root {
    --bg:#0a0a0f; --paper:#12121a; --panel:#0e0e16; --ink:#d6dae3; --head:#f0f0f5; --muted:#8b93a7; --subtle:#6b7280;
    --line:#2a2a3a; --line-strong:#3a3a52;
    --brand:#00ff88; --brand-dim:#00cc6e; --brand-soft:rgba(0,255,136,.08); --brand-glow:rgba(0,255,136,.35);
    --cyan:#00d4ff; --cyan-soft:rgba(0,212,255,.10); --magenta:#ff3366; --amber:#ffb020;
    --code-bg:#161622; --code-ink:#9ef0c5; --pre-bg:#07070c; --pre-ink:#cfe9dc;
    --rail-w:212px; --toc-w:232px; --top-h:0px;
    --mono:'Cascadia Code',Consolas,'JetBrains Mono','Fira Code','Noto Sans TC',ui-monospace,monospace;
    --sans:'Noto Sans TC','Segoe UI',system-ui,'Microsoft JhengHei',sans-serif;
  }
  * { box-sizing:border-box; }
  html { scroll-behavior:smooth; color-scheme:dark; }
  body {
    margin:0; min-height:100vh; display:flex; align-items:flex-start;
    background:var(--bg) linear-gradient(rgba(0,255,136,.028) 1px, transparent 1px) 0 0 / 44px 44px, linear-gradient(90deg, rgba(0,255,136,.028) 1px, transparent 1px) 0 0 / 44px 44px;
    color:var(--ink); font-family:var(--sans); line-height:1.85; font-size:16px; -webkit-font-smoothing:antialiased;
  }
  ::selection { background:var(--brand); color:#0a0a0f; }
  ::-webkit-scrollbar { width:10px; height:10px; }
  ::-webkit-scrollbar-thumb { background:var(--line-strong); border-radius:2px; border:2px solid var(--bg); }
  ::-webkit-scrollbar-track { background:transparent; }
  :focus-visible { outline:2px solid var(--brand); outline-offset:2px; box-shadow:0 0 8px var(--brand-glow); }

  /* 最左：站內總目錄（直式導覽欄，sticky 滿高，掃描線只鋪在這裡） */
  nav.site {
    position:sticky; top:0; z-index:20; flex:0 0 var(--rail-w); height:100vh; overflow-y:auto; scrollbar-width:thin;
    display:flex; flex-direction:column; gap:.1rem; padding:1.1rem .7rem 1.4rem;
    background:var(--bg) repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(0,0,0,.22) 3px, rgba(0,0,0,.22) 4px);
    border-right:1px solid rgba(0,255,136,.14); font-family:var(--mono); font-size:.8rem;
  }
  nav.site::before {
    content:"VisionSequence\\A DOCS // 總目錄"; white-space:pre; display:block; margin:0 .4rem 1rem; padding:.55rem .7rem;
    border:1px solid rgba(0,255,136,.35); border-radius:3px; color:var(--brand); font-weight:700; letter-spacing:.06em; line-height:1.45;
    text-shadow:0 0 10px var(--brand-glow); background:var(--brand-soft);
  }
  nav.site a { display:block; padding:.42rem .7rem .42rem .8rem; border-left:2px solid transparent; border-radius:0 3px 3px 0; color:var(--muted); text-decoration:none; white-space:normal; line-height:1.4; overflow-wrap:anywhere; }
  nav.site a::before { content:"› "; color:var(--subtle); }
  nav.site a:hover { color:var(--brand); background:var(--brand-soft); }
  nav.site a[aria-current="page"] { color:var(--brand); border-left-color:var(--brand); background:var(--brand-soft); font-weight:700; text-shadow:0 0 8px var(--brand-glow); }
  nav.site a[aria-current="page"]::before { content:"▸ "; color:var(--brand); }

  /* 中：本頁目錄（sticky）＋ 右：內文 */
  .doc-layout { flex:1 1 auto; min-width:0; display:flex; align-items:flex-start; gap:2.6rem; max-width:1240px; padding:2.4rem 2.4rem 6rem 2.2rem; }
  aside.toc { flex:0 0 var(--toc-w); position:sticky; top:calc(var(--top-h) + 1.4rem); max-height:calc(100vh - var(--top-h) - 2.8rem); overflow-y:auto; scrollbar-width:thin; padding:.2rem 1rem .6rem 0; border-right:1px solid var(--line); font-family:var(--mono); font-size:.8rem; line-height:1.5; }
  aside.toc .toc-title { margin:0 0 .7rem; font-size:.68rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase; color:var(--cyan); }
  aside.toc .toc-title::before { content:"// "; color:var(--subtle); }
  aside.toc ul { list-style:none; margin:0; padding:0; }
  aside.toc li { margin:0; }
  aside.toc a { display:block; padding:.34rem .6rem .34rem .7rem; margin:.05rem 0; border-left:2px solid transparent; border-radius:0 3px 3px 0; color:var(--muted); text-decoration:none; overflow-wrap:anywhere; }
  aside.toc a:hover { color:var(--cyan); background:var(--cyan-soft); }
  aside.toc a.active { color:var(--brand); border-left-color:var(--brand); background:var(--brand-soft); font-weight:700; text-shadow:0 0 8px var(--brand-glow); }
  aside.toc ul ul a { padding-left:1.6rem; font-size:.76rem; color:var(--subtle); }
  aside.toc ul ul a.active { color:var(--brand); }

  article.doc { flex:1 1 auto; min-width:0; max-width:880px; }
  article.doc.wide { max-width:1060px; }

  /* 字級階層：標題等寬字＋霓虹，明顯大於內文；段落留白 */
  h1 { font-family:var(--mono); font-size:2rem; line-height:1.3; color:var(--head); letter-spacing:-.01em; margin:.2rem 0 1.5rem; font-weight:700; text-shadow:0 0 14px rgba(0,255,136,.22); }
  h1::after { content:""; display:block; width:72px; height:3px; margin-top:.8rem; background:linear-gradient(90deg,var(--brand),var(--cyan)); box-shadow:0 0 10px var(--brand-glow); }
  h2 { font-family:var(--mono); font-size:1.45rem; line-height:1.35; color:var(--brand); font-weight:700; margin:3.4rem 0 1.1rem; padding:.4rem .9rem .4rem .95rem; border-left:3px solid var(--brand); background:linear-gradient(90deg,var(--brand-soft),transparent 72%); border-radius:0 3px 3px 0; text-shadow:0 0 10px rgba(0,255,136,.25); scroll-margin-top:calc(var(--top-h) + 1.2rem); }
  h2::before { content:"// "; color:var(--subtle); font-weight:400; }
  h2:first-of-type { margin-top:2.2rem; }
  h3 { font-family:var(--mono); font-size:1.12rem; line-height:1.4; color:var(--cyan); font-weight:700; margin:2.3rem 0 .75rem; scroll-margin-top:calc(var(--top-h) + 1.2rem); }
  h3::before { content:"› "; color:var(--subtle); }
  h4 { font-family:var(--mono); font-size:1rem; color:var(--head); margin:1.6rem 0 .5rem; }
  p { margin:.9rem 0; }
  p.lead { font-size:1.05rem; color:var(--muted); }
  a { color:var(--cyan); text-decoration:underline; text-decoration-color:rgba(0,212,255,.35); text-underline-offset:3px; }
  a:hover { color:var(--brand); text-decoration-color:var(--brand); }
  strong { color:var(--head); }
  em { color:var(--amber); font-style:normal; }
  code { font-family:var(--mono); font-size:.86em; background:var(--code-bg); color:var(--code-ink); border:1px solid var(--line); border-radius:3px; padding:.08em .4em; overflow-wrap:anywhere; }
  pre { position:relative; background:var(--pre-bg); color:var(--pre-ink); border:1px solid var(--line); border-radius:3px; padding:1.1rem 1.25rem; margin:1.2rem 0; overflow-x:auto; line-height:1.65; font-size:.84em; box-shadow:0 0 0 1px rgba(0,255,136,.04), 0 0 16px rgba(0,255,136,.05); }
  pre::before, pre::after { content:""; position:absolute; width:12px; height:12px; border:2px solid var(--brand); pointer-events:none; }
  pre::before { top:3px; left:3px; border-right:0; border-bottom:0; }
  pre::after { bottom:3px; right:3px; border-left:0; border-top:0; }
  pre code { background:none; border:none; color:inherit; padding:0; }
  td pre { margin:.35rem 0; padding:.5rem .7rem; font-size:.82em; }
  table { width:100%; border-collapse:separate; border-spacing:0; margin:1.3rem 0; font-size:.92em; background:var(--paper); border:1px solid var(--line); border-top:2px solid var(--brand); border-radius:3px; overflow:hidden; }
  th { background:#161622; color:var(--brand); font-family:var(--mono); font-size:.78em; letter-spacing:.06em; text-align:left; font-weight:700; padding:.65rem .85rem; border-bottom:1px solid var(--line-strong); }
  td { padding:.6rem .85rem; border-bottom:1px solid var(--line); vertical-align:top; }
  tr:last-child td { border-bottom:none; }
  tr:nth-child(even) td { background:#141420; }
  ul, ol { padding-left:1.5rem; margin:.75rem 0; }
  li { margin:.45rem 0; }
  li::marker { color:var(--brand-dim); }
  li > ul, li > ol { margin:.3rem 0; }
  .note, blockquote { position:relative; margin:1.4rem 0; padding:.85rem 1.15rem; background:var(--panel); border:1px solid var(--line); border-left:3px solid var(--amber); border-radius:3px; color:var(--ink); }
  .note::after, blockquote::after { content:""; position:absolute; right:3px; bottom:3px; width:10px; height:10px; border-right:2px solid var(--amber); border-bottom:2px solid var(--amber); pointer-events:none; }
  blockquote { border-left-color:var(--cyan); color:var(--muted); }
  blockquote::after { border-color:var(--cyan); }
  hr { border:none; border-top:1px solid var(--line); margin:2.8rem 0; }
  img { max-width:100%; border:1px solid var(--line); border-radius:3px; }
  figure.shot { margin:1.4rem 0 1.8rem; padding:.6rem; background:var(--panel); border:1px solid var(--line); border-radius:3px; position:relative; }
  figure.shot::before { content:""; position:absolute; top:3px; left:3px; width:12px; height:12px; border-top:2px solid var(--cyan); border-left:2px solid var(--cyan); pointer-events:none; }
  figure.shot img { display:block; width:100%; height:auto; border:1px solid var(--line-strong); }
  figure.shot figcaption { margin:.7rem .2rem 0; font-size:.9em; color:var(--muted); line-height:1.6; }
  figure.shot figcaption b { color:var(--head); font-family:var(--mono); font-size:.9em; letter-spacing:.04em; }
  figure.shot ol.callouts { margin:.4rem 0 0; padding-left:0; list-style:none; columns:2; column-gap:1.6rem; }
  figure.shot ol.callouts li { break-inside:avoid; margin:.25rem 0; padding-left:1.9rem; position:relative; }
  figure.shot ol.callouts li::before { content:attr(data-n); position:absolute; left:0; top:.05em; width:1.35rem; height:1.35rem; border-radius:50%; background:var(--brand); color:#0a0a12; font-family:var(--mono); font-weight:700; font-size:.76em; display:inline-flex; align-items:center; justify-content:center; }
  @media (max-width:700px) { figure.shot ol.callouts { columns:1; } }
  .wrap { overflow-x:auto; }
  .good { color:var(--brand); font-weight:600; }
  .bad { color:var(--magenta); }
  .noise { color:var(--subtle); }
  .num td:nth-child(n+2), .num th:nth-child(n+2) { text-align:right; font-variant-numeric:tabular-nums; }

  @media (max-width:1180px) {
    .doc-layout { flex-direction:column; gap:1.4rem; padding:1.8rem 1.6rem 4rem; }
    aside.toc { position:static; max-height:none; flex:none; width:100%; border-right:none; border-bottom:1px solid var(--line); padding:0 0 .8rem; }
    aside.toc ul { columns:2; column-gap:1.5rem; }
    aside.toc li { break-inside:avoid; }
    aside.toc ul ul { columns:1; }
  }
  @media (max-width:900px) {
    body { display:block; }
    nav.site { position:sticky; height:auto; flex-direction:row; flex-wrap:nowrap; overflow-x:auto; overflow-y:hidden; gap:.15rem; padding:.5rem .8rem; border-right:none; border-bottom:1px solid rgba(0,255,136,.14); }
    nav.site::before { content:"VS"; white-space:nowrap; margin:0 .6rem 0 0; padding:.2rem .5rem; }
    nav.site a { white-space:nowrap; border-left:none; border-bottom:2px solid transparent; border-radius:3px 3px 0 0; padding:.3rem .55rem; }
    nav.site a::before { content:""; }
    nav.site a[aria-current="page"] { border-bottom-color:var(--brand); }
    .doc-layout { padding:1.4rem 1rem 4rem; }
    h1 { font-size:1.55rem; }
    h2 { font-size:1.25rem; margin-top:2.4rem; }
  }
  @media print {
    body { display:block; background:#fff; color:#111; }
    nav.site, aside.toc { display:none; }
    .doc-layout { display:block; padding:0; max-width:none; }
    h1, h2, h3 { color:#111; text-shadow:none; }
    a { color:#1d4ed8; }
    code, pre, table { background:#f5f5f5; color:#111; }
  }
"""

SCRIPT = """<script>
// 本頁目錄：捲動時標出目前章節（無 JS 也能用，只是沒有高亮）；窄螢幕時頂列導覽的高度給 sticky／scroll-margin 用
(function () {
  var site = document.querySelector('nav.site');
  function measure() {
    if (!site) return;
    var horizontal = getComputedStyle(site).flexDirection !== 'column';
    document.documentElement.style.setProperty('--top-h', (horizontal ? site.offsetHeight : 0) + 'px');
  }
  measure();
  window.addEventListener('resize', measure);
  var links = Array.prototype.slice.call(document.querySelectorAll('aside.toc a[href^="#"]'));
  if (!links.length) return;
  var byId = {};
  links.forEach(function (a) { byId[a.getAttribute('href').slice(1)] = a; });
  var heads = Array.prototype.slice.call(document.querySelectorAll('article.doc h2[id], article.doc h3[id]')).filter(function (h) { return byId[h.id]; });
  var current = null;
  function activate(id) {
    if (current === id) return;
    current = id;
    links.forEach(function (a) { a.classList.toggle('active', a.getAttribute('href') === '#' + id); });
    var a = byId[id];
    if (a && a.scrollIntoView) { try { a.scrollIntoView({ block: 'nearest' }); } catch (e) {} }
  }
  function update() {
    var top = window.scrollY + 100, best = heads[0];
    for (var i = 0; i < heads.length; i++) { if (heads[i].offsetTop <= top) best = heads[i]; else break; }
    if (best) activate(best.id);
  }
  update();
  window.addEventListener('scroll', update, { passive: true });
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
    head = '<aside class="toc" aria-label="本頁目錄"><p class="toc-title">本頁目錄</p><ul>'
    out = [head]
    open_sub = False
    for level, sid, title in items:
        if level == "2":
            if open_sub:
                out.append("</ul></li>")
                open_sub = False
            elif out[-1] != head:
                out.append("</li>")
            out.append(f'<li><a href="#{sid}">{html.escape(title)}</a>')
        else:
            if not open_sub:
                out.append("<ul>")
                open_sub = True
            out.append(f'<li><a href="#{sid}">{html.escape(title)}</a></li>')
    out.append("</ul></li>" if open_sub else "</li>")
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
        raise ValueError('沒有 <article class="doc">')
    open_tag = m.group(0)
    start = m.end()
    end = src.index("</article>", start)
    body = src[start:end]
    # 舊版側欄／內文目錄一律拆掉再重建（可重複執行）
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
