/**
 * 應用外殼：路由、佈景、全域狀態。
 *
 * 刻意不用任何前端框架：這個工具只有九個畫面、部署環境離線，
 * 引入建置流程（node_modules / bundler）只會增加交付與維護成本。
 * 用原生 ES module + hash 路由，任何瀏覽器打開就能跑。
 */

import { api, ApiError } from './api.js';
import { h, toast, spinner, badge } from './ui.js';

import dashboard from './views/dashboard.js';
import batches from './views/batches.js';
import mapping from './views/mapping.js';
import simulate from './views/simulate.js';
import optimize from './views/optimize.js';
import audit from './views/audit.js';
import validation from './views/validation.js';
import assistant from './views/assistant.js';
import dataview from './views/data.js';

const ROUTES = [
  { group: '分析' },
  { id: 'dashboard', title: '總覽', icon: '▤', view: dashboard },
  { id: 'batches', title: '批次資料', icon: '▦', view: batches },
  { id: 'mapping', title: '參數映射', icon: '∿', view: mapping },
  { group: '預測與建議' },
  { id: 'simulate', title: '模擬與預測', icon: '◈', view: simulate },
  { id: 'optimize', title: '最佳化建議', icon: '◎', view: optimize },
  { group: '品質保證' },
  { id: 'audit', title: '資料稽核', icon: '⚑', view: audit },
  { id: 'validation', title: '模型驗證', icon: '✓', view: validation },
  { group: '工具' },
  { id: 'assistant', title: 'AI 助理', icon: '✦', view: assistant },
  { id: 'data', title: '資料管理', icon: '⇪', view: dataview },
];

export const state = {
  config: null,
  overview: null,
  elements: [],
  theme: 'dark',
};

/** 6N 判定門檻。由後端 /api/config 提供，前端不再自己寫死 1.0——
 *  客戶用 EXPA_PURITY_THRESHOLD_PPM 改門檻時，圖上的虛線才不會跟
 *  後端算出來的綠色高純區對不上。 */
export const thresholdPpm = () => state.config?.purity_threshold_ppm ?? 1.0;

/** 共用的資料存取：同一份 overview 給所有畫面用，切頁不重打 API。 */
export async function ensureOverview(force = false) {
  if (!state.overview || force) {
    state.overview = await api.overview();
    state.elements = state.overview.elements || [];
    renderDataBadge();
  }
  return state.overview;
}

export function invalidate() {
  state.overview = null;
}

function renderNav() {
  const nav = document.getElementById('nav');
  nav.innerHTML = '';
  for (const r of ROUTES) {
    if (r.group) { nav.append(h('div', { class: 'nav-group' }, r.group)); continue; }
    nav.append(h('a', { href: `#/${r.id}`, 'data-id': r.id },
      h('span', { class: 'ico' }, r.icon), r.title));
  }
}

function renderDataBadge() {
  const el = document.getElementById('data-badge');
  el.innerHTML = '';
  const ov = state.overview;
  if (!ov || ov.empty) {
    el.append(badge('尚無資料', 'warn'));
    return;
  }
  el.append(h('span', { class: 'muted' },
    `${ov.n_batches} 批次 · ${ov.n_measurements} 測點 · ${ov.n_censored} 設限`));
}

async function renderHealth() {
  const line = document.getElementById('health-line');
  try {
    const hz = await api.health();
    const st = await api.assistantStatus();
    line.innerHTML = '';
    line.append(
      h('div', {}, `v${hz.version} · ${hz.ok ? '服務正常' : '服務異常'}`),
      h('div', {}, `AI：${st.active_provider}${st.degraded ? '（本地模板）' : ''}`));
  } catch (e) {
    line.textContent = '無法連線到服務';
  }
}

async function route() {
  const id = (location.hash.replace(/^#\/?/, '') || 'dashboard').split('?')[0];
  const entry = ROUTES.find((r) => r.id === id) || ROUTES.find((r) => r.id === 'dashboard');
  document.querySelectorAll('.nav a').forEach((a) =>
    a.classList.toggle('active', a.dataset.id === entry.id));
  document.getElementById('page-title').textContent = entry.title;

  const host = document.getElementById('view');
  host.innerHTML = '';
  host.append(spinner('載入中…'));
  try {
    const node = await entry.view(host);
    host.innerHTML = '';
    if (node) host.append(node);
  } catch (e) {
    host.innerHTML = '';
    const msg = e instanceof ApiError ? e.message : String(e);
    host.append(h('div', { class: 'notice notice-error' },
      h('strong', {}, '載入失敗'),
      h('p', {}, msg),
      e instanceof ApiError && e.detail ? h('p', { class: 'muted mono' }, e.detail) : null,
      h('button', { class: 'ghost small', onclick: () => route() }, '重試')));
    toast(msg, 'error');
  }
  window.scrollTo(0, 0);
}

function initTheme() {
  const saved = (() => {
    try { return localStorage.getItem('expa-theme'); } catch { return null; }
  })();
  state.theme = saved || (window.matchMedia?.('(prefers-color-scheme: light)').matches
    ? 'light' : 'dark');
  document.documentElement.dataset.theme = state.theme;
  document.getElementById('theme-toggle').addEventListener('click', () => {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = state.theme;
    try { localStorage.setItem('expa-theme', state.theme); } catch { /* 私密瀏覽模式 */ }
    route();   // 圖表顏色來自 CSS 變數，需重繪
  });
}

async function boot() {
  initTheme();
  renderNav();
  window.addEventListener('hashchange', route);
  try { state.config = await api.config(); } catch { /* 用預設值 */ }
  renderHealth();
  await route();
}

boot();
