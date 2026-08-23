/* 說明文件共用行為：側欄產生、主題切換、目前頁高亮。 */
const PAGES = [
  { grp: '開始' },
  { href: 'index.html', title: '文件總覽' },
  { href: '01-overview.html', title: '01 · 系統架構與設計理念' },
  { grp: '方法' },
  { href: '02-physics.html', title: '02 · 物理模型詳解' },
  { href: '04-methods.html', title: '04 · 擬合、AI 與最佳化方法' },
  { href: '08-validation.html', title: '08 · 驗證、驗收與風險控管' },
  { grp: '使用' },
  { href: '03-data-spec.html', title: '03 · 資料規格書' },
  { href: '05-user-guide.html', title: '05 · 使用者操作手冊' },
  { grp: '開發' },
  { href: '06-api.html', title: '06 · REST API 參考' },
  { href: '07-dev-guide.html', title: '07 · 開發者指南' },
];

function currentFile() {
  const p = location.pathname.split('/').pop();
  return p && p !== '' ? p : 'index.html';
}

function buildSidebar() {
  const cur = currentFile();
  const nav = document.createElement('nav');
  for (const it of PAGES) {
    if (it.grp) {
      const d = document.createElement('div');
      d.className = 'grp'; d.textContent = it.grp; nav.append(d); continue;
    }
    const a = document.createElement('a');
    a.href = it.href; a.textContent = it.title;
    if (it.href === cur) a.className = 'active';
    nav.append(a);
  }
  const side = document.createElement('aside');
  side.className = 'sidebar';
  side.innerHTML = '<div class="brand"><b>ExpAnalysis 說明文件</b>'
    + '<div>高純銦偏析純化製程分析平台</div></div>';
  side.append(nav);
  const back = document.createElement('div');
  back.style.cssText = 'padding:16px 20px 0;border-top:1px solid var(--line);margin-top:14px';
  back.innerHTML = '<a href="/" style="font-size:12.5px">← 回到分析平台</a>';
  side.append(back);

  const layout = document.createElement('div');
  layout.className = 'layout';
  const main = document.querySelector('main');
  main.parentNode.insertBefore(layout, main);
  layout.append(side, main);

  // 上一頁 / 下一頁
  const idx = PAGES.filter((p) => p.href).findIndex((p) => p.href === cur);
  const links = PAGES.filter((p) => p.href);
  if (idx >= 0) {
    const nx = document.createElement('div');
    nx.className = 'next';
    if (idx > 0) nx.innerHTML += `<a href="${links[idx - 1].href}"><span>上一頁</span>${links[idx - 1].title}</a>`;
    if (idx < links.length - 1) nx.innerHTML += `<a href="${links[idx + 1].href}"><span>下一頁</span>${links[idx + 1].title}</a>`;
    main.append(nx);
  }
  const f = document.createElement('footer');
  f.innerHTML = 'ExpAnalysis v0.1.0 · 本文件與程式碼同版本維護。'
    + '本系統為離線決策輔助工具，不參與任何設備控制。';
  main.append(f);
}

function initTheme() {
  const saved = (() => { try { return localStorage.getItem('expa-theme'); } catch { return null; } })();
  const t = saved || (window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  document.documentElement.dataset.theme = t;
  const bar = document.querySelector('.toolbar');
  if (!bar) return;
  const b = document.createElement('button');
  b.textContent = '◐ 主題';
  b.onclick = () => {
    const nt = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = nt;
    try { localStorage.setItem('expa-theme', nt); } catch { /* 私密瀏覽 */ }
  };
  bar.append(b);
}

buildSidebar();
initTheme();
