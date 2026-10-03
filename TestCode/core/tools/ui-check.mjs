// 標準互動測試：以桌面、手機直向、手機橫向、觸控平板四種尺寸開啟專案頁面，逐項操作標準介面並量測版面。
//   node core/tools/ui-check.mjs [專案…] [--port 8771] [--devices desktop,phone,landscape,tablet] [--shots 資料夾]
// check.mjs 完整檢查的內建項目「ui」會逐專案呼叫；結果寫到 <專案>/review/ui-check.json（不含時間，內容不變就不會產生 git 差異）。
//
// 每種尺寸都檢查：
//   load        頁面載入、window.sim 就緒、主控台無錯誤
//   overflow    沒有水平／垂直捲軸（版面不超出視窗）
//   canvas      3D 畫布可見面積 ≥ 視窗的 30%
//   play        播放後時間前進、暫停後停住（以 #timeline 的值判斷）
//   steps       下一步／上一步／步驟選單會跳到事件時刻（精簡版面先開 ⚙）
//   views       每個 [data-view] 按鈕點下去不出錯（精簡版面先開 ☰，點完選單自動收起）
//   panels      側欄可打開且在視窗內（精簡版面用工具列 ◨／◧）
//   labels      可見的 3D 標籤中心都在畫布內；精簡版面上互不重疊
//   targets     精簡版面與觸控平板：可見的按鈕／選單高度 ≥ 30 px
// 桌面另外檢查 ?pause&movie 可載入。
// project.json 的 "ui" 可設定：{ "skip": ["labels"], "params": "&sku=A" }（skip 的項目記為略過，不算失敗）
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { pickProjects } from './projects.mjs';
import { startServer } from './serve.mjs';
import { openBrowser, sleep } from './cdp.mjs';

const argv = process.argv.slice(2);
const opt = (name, def) => { const i = argv.indexOf('--' + name); return i >= 0 ? argv.splice(i, 2)[1] : def; };
const port = +opt('port', 8771), shots = opt('shots', ''), deviceNames = opt('devices', 'desktop,phone,landscape,tablet').split(',');
const DEVICES = {
  desktop: { width: 1680, height: 1000, scale: 1, touch: false },
  phone: { width: 390, height: 844, scale: 2, touch: true },
  landscape: { width: 844, height: 390, scale: 2, touch: true },
  tablet: { width: 1024, height: 768, scale: 2, touch: true },
};
const projects = pickProjects(argv.filter(a => !a.startsWith('--')));

// 頁面內的量測與操作（字串，交給 Runtime.evaluate）
const PAGE = `(() => {
  const $ = s => document.querySelector(s);
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const inView = e => { const r = e.getBoundingClientRect(); return r.left >= -1 && r.top >= -1 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1; };
  const time = () => +($('#timeline')?.value ?? NaN);
  const click = s => { const e = typeof s === 'string' ? $(s) : s; if (!e) return false; e.click(); return true; };
  window.__ui = { $, vis, inView, time, click,
    compact: () => document.body.classList.contains('viewer-compact'),
    layout() {
      const de = document.documentElement, c = $('canvas').getBoundingClientRect();
      const w = Math.max(0, Math.min(c.right, innerWidth) - Math.max(c.left, 0)), h = Math.max(0, Math.min(c.bottom, innerHeight) - Math.max(c.top, 0));
      return { scrollW: de.scrollWidth, scrollH: de.scrollHeight, innerW: innerWidth, innerH: innerHeight, canvasShare: +(w * h / innerWidth / innerHeight).toFixed(3) };
    },
    labels() {
      const c = $('canvas').getBoundingClientRect(), list = [...document.querySelectorAll('.label3d')].filter(vis).map(e => e.getBoundingClientRect());
      const outside = list.filter(r => { const x = (r.left + r.right) / 2, y = (r.top + r.bottom) / 2; return x < c.left - 2 || x > c.right + 2 || y < c.top - 2 || y > c.bottom + 2; }).length;
      let overlaps = 0;
      for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) { const a = list[i], b = list[j]; if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps++; }
      return { visible: list.length, outside, overlaps };
    },
    smallTargets() {
      return [...document.querySelectorAll('button,select,input:not([type=range]):not([type=checkbox]):not([type=hidden])')]
        .filter(e => vis(e) && inView(e) && !e.closest('#pipFrame .camera-actions, .label3d, #movie') && e.getBoundingClientRect().height < 30)
        .map(e => (e.id ? '#' + e.id : e.tagName.toLowerCase()) + (e.textContent.trim() ? ' ' + e.textContent.trim().slice(0, 12) : '') + ' ' + Math.round(e.getBoundingClientRect().height) + 'px');
    },
  };
  return true;
})()`;

async function checkDevice(b, p, name, dev, cfg) {
  const out = {}, skip = new Set(cfg.skip || []);
  const put = (k, ok, info) => { out[k] = skip.has(k) ? { ok: true, skipped: true } : { ok: !!ok, ...(info === undefined ? {} : { info }) }; };
  const ev = expr => b.evaluate(expr);
  await b.send('Emulation.setDeviceMetricsOverride', { width: dev.width, height: dev.height, deviceScaleFactor: dev.scale, mobile: dev.touch });
  await b.send('Emulation.setTouchEmulationEnabled', { enabled: dev.touch, maxTouchPoints: dev.touch ? 5 : 0 });
  const url = `http://127.0.0.1:${port}/${encodeURIComponent(p.id)}/?pause${cfg.params || ''}`;
  const loaded = await b.goto(url); await sleep(700); await b.frames();
  if (!loaded) { put('load', false, b.errors.slice(0, 5)); return out; }
  await ev(PAGE);
  const compact = await ev('__ui.compact()');
  const L = await ev('__ui.layout()');
  put('overflow', L.scrollW <= L.innerW + 1 && L.scrollH <= L.innerH + 1, L.scrollW > L.innerW + 1 || L.scrollH > L.innerH + 1 ? L : undefined);
  put('canvas', L.canvasShare >= .3, L.canvasShare >= .3 ? undefined : L.canvasShare);
  if (shots) { mkdirSync(shots, { recursive: true }); writeFileSync(join(shots, `${p.id.replace(/\s/g, '_')}-${name}.jpg`), await b.screenshot('jpeg', 70)); }

  // 播放與暫停
  const t0 = await ev('__ui.time()');
  await ev(`__ui.click('#playBtn')`); await sleep(700);
  const t1 = await ev('__ui.time()');
  await ev(`__ui.click('#playBtn')`); await sleep(100);
  const t2 = await ev('__ui.time()'); await sleep(400);
  const t3 = await ev('__ui.time()');
  const played = t1 > t0 && Math.abs(t3 - t2) < 1e-6; put('play', played, played ? undefined : { t0, t1, t2, t3 });

  // 下一步／上一步／步驟選單
  if (compact) { await ev(`__ui.click('#mobilePlaybackToggle')`); await sleep(150); }
  const steps = await ev(`(async () => {
    const u = __ui, sel = u.$('#stepSelect'), next = u.$('#next'), prev = u.$('#previous');
    if (!sel || !next || !prev) return { ok: false, missing: [!sel && 'stepSelect', !next && 'next', !prev && 'previous'].filter(Boolean) };
    const reach = [sel, next, prev].every(e => u.vis(e) && u.inView(e));
    const times = [...sel.options].map(o => +o.value);
    sel.value = String(Math.min(2, sel.options.length - 1)); sel.dispatchEvent(new Event('change')); await new Promise(r => setTimeout(r, 60));
    const a = u.time(); next.click(); await new Promise(r => setTimeout(r, 60));
    const b = u.time(); prev.click(); await new Promise(r => setTimeout(r, 60));
    const c = u.time();
    return { ok: reach && b > a && c < b, reach, a, b, c, options: times.length };
  })()`);
  put('steps', steps.ok, steps.ok ? undefined : steps);
  if (compact) { await ev(`__ui.click('#mobilePlaybackToggle')`); await sleep(150); }

  // 視角按鈕
  const views = await ev(`(async () => {
    const u = __ui, n = document.querySelectorAll('[data-view]').length, bad = [];
    for (let i = 0; i < n; i++) {
      if (u.compact()) { if (!document.body.classList.contains('viewer-nav-open')) u.click('#mobileNavToggle'); await new Promise(r => setTimeout(r, 80)); }
      const btn = document.querySelectorAll('[data-view]')[i];
      if (btn.tagName === 'OPTION') continue;
      if (!u.vis(btn) || !u.inView(btn)) { bad.push((btn.dataset.view || i) + ' 看不到'); continue; }
      btn.click(); await new Promise(r => setTimeout(r, 80));
      if (u.compact() && document.body.classList.contains('viewer-nav-open')) bad.push((btn.dataset.view || i) + ' 點完選單未收起');
    }
    return { n, bad };
  })()`);
  put('views', !views.bad.length && !b.errors.length, views.bad.length ? views.bad.slice(0, 6) : views.n);

  // 側欄（精簡版面由工具列打開；桌面應已顯示）
  const panels = await ev(`(async () => {
    const u = __ui, ids = ['side', 'left'].filter(id => document.getElementById(id)), res = {};
    for (const id of ids) {
      const panel = document.getElementById(id), btn = document.querySelector('.viewer-tools [aria-controls="' + id + '"]');
      if (u.compact()) { if (!btn) { res[id] = '無切換鈕'; continue; } if (panel.hidden) btn.click(); await new Promise(r => setTimeout(r, 120)); }
      res[id] = !u.vis(panel) ? (u.compact() ? '打不開' : 'hidden') : u.inView(panel) || panel.scrollHeight > panel.clientHeight ? 'ok' : '超出視窗';
      if (u.compact() && btn && !panel.hidden) { btn.click(); await new Promise(r => setTimeout(r, 80)); }
    }
    return res;
  })()`);
  const panelBad = Object.entries(panels).filter(([, v]) => v !== 'ok' && v !== 'hidden');
  put('panels', !panelBad.length, panelBad.length ? panels : undefined);

  // 標籤（回到第一個視角，重繪後量）
  await ev(`(sim.setView?.(sim.views?.[0], true), 1)`); await b.frames(); await sleep(150);
  const lab = await ev('__ui.labels()');
  put('labels', lab.outside === 0 && (!compact || lab.overlaps === 0), lab);

  // 點按目標
  if (compact || dev.touch) { const small = await ev('__ui.smallTargets()'); put('targets', !small.length, small.length ? small.slice(0, 8) : undefined); }

  put('load', !b.errors.length, b.errors.length ? b.errors.slice(0, 5) : undefined);
  if (name === 'desktop') {
    const ok = await b.goto(url + '&movie'); await sleep(500);
    put('movie', ok && !b.errors.length, ok ? b.errors.slice(0, 3) : '未就緒');
  }
  return out;
}

const server = await startServer({ port, quiet: true }), b = await openBrowser();
let failed = 0;
try {
  for (const p of projects) {
    const cfg = p.ui || {}, report = { project: p.id, devices: {} };
    for (const name of deviceNames) {
      const res = await checkDevice(b, p, name, DEVICES[name], cfg);
      report.devices[name] = res;
      const bad = Object.entries(res).filter(([, v]) => !v.ok);
      failed += bad.length;
      console.log(`${bad.length ? '✗' : '✓'} ${p.id} · ${name}  ${Object.keys(res).length - bad.length}/${Object.keys(res).length}` + (bad.length ? '  ' + bad.map(([k, v]) => `${k} ${JSON.stringify(v.info ?? '')}`).join('；') : ''));
    }
    mkdirSync(join(p.dir, 'review'), { recursive: true });
    writeFileSync(join(p.dir, 'review', 'ui-check.json'), JSON.stringify(report, (k, v) => typeof v === 'number' && !Number.isInteger(v) ? +v.toFixed(3) : v, 2));
  }
} finally { await b.close(); server.close(); }
process.exit(failed ? 1 : 0);
