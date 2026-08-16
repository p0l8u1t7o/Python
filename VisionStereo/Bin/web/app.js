/* ══════════════════════════════════════════════════════════════
   YoloSeg Studio — 前端
   座標一律以正規化 (0~1) 儲存，與 YOLO segmentation txt 一致。
   ══════════════════════════════════════════════════════════════ */
'use strict';

const $ = (id) => document.getElementById(id);

const S = {
  root: '', dataset: '', splits: [], split: 'train', classes: [],
  items: [], total: 0, page: 0, pageSize: 60,
  cur: null, img: null,
  shapes: [], sel: -1, dirty: false,
  hist: [],
  mode: 'select', draft: null, draftHover: null,
  page_: 'annotate',
  zoom: 1, ox: 0, oy: 0,
  drag: null, curClass: 0, space: false,
  gen: 0,                    // 資料集世代（影像 URL 的快取版本）
};

let openSeq = 0;             // openImage 的請求序號，用來丟棄過期的回應

const PAGE_TITLE = {
  annotate: '標註編輯', grid: '多圖瀏覽', video: '影片轉資料集',
  train: '模型訓練', dataset: '資料集設定', stats: '統計', guide: '使用流程',
};

/* ══════════ 主題（深色 / 淺色）══════════ */
const cssVar = (name, fallback) => {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
};

function currentTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

function applyThemeIcons() {
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', currentTheme() === 'dark' ? '#1a1e27' : '#ffffff');
}

function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('ys-theme', t); } catch (e) { /* 私密模式 */ }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', t === 'dark' ? '#1a1e27' : '#ffffff');
  // 畫布與圖表是自己畫的，換主題要重畫才會跟著變
  draw();
  if (S.page_ === 'grid') renderGrid();
  if (S.page_ === 'train') drawTrainChart(LAST_HISTORY);
}

/* ══════════ 行動版選單 ══════════ */
function setNav(open) {
  document.body.classList.toggle('nav-open', open);
  $('navScrim').classList.toggle('d-none', !open);
}
function setTopTools(open) {
  $('topTools').classList.toggle('open', open);
}
const isMobile = () => window.matchMedia('(max-width:820px)').matches;

const CANVAS = $('canvas');
const CTX = CANVAS.getContext('2d');

/* ───────── 小工具 ───────── */
function classColor(i) {
  const hues = [230, 12, 152, 38, 280, 190, 330, 96, 20, 258];
  const h = hues[i % hues.length] + Math.floor(i / hues.length) * 17;
  return `hsl(${h % 360} 72% 55%)`;
}
function className(i) { return S.classes[i] !== undefined ? S.classes[i] : `class${i}`; }
const clamp01 = (v) => Math.min(1, Math.max(0, v));

let toastTimer = null;
function toast(msg, kind = '') {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast ' + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('d-none'), 3400);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('json')) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}
const post = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});
const enc = encodeURIComponent;
// g = 資料集世代；換資料夾或搬移檔案後遞增，避免瀏覽器沿用同名舊圖
const imgURL = (split, name) => `/api/image?split=${enc(split)}&name=${enc(name)}&g=${S.gen}`;
const thumbURL = (split, name, w) => `/api/thumb?split=${enc(split)}&name=${enc(name)}&w=${w}&g=${S.gen}`;

/* ══════════ 頁面切換 ══════════ */
function switchPage(p) {
  if (!PAGE_TITLE[p]) p = 'annotate';
  S.page_ = p;
  if (location.hash.slice(1) !== p) location.hash = p;
  document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === p));
  document.querySelectorAll('.page').forEach((s) => s.classList.toggle('active', s.dataset.page === p));
  $('pageTitle').textContent = PAGE_TITLE[p] || p;
  if (isMobile()) { setNav(false); setTopTools(false); }
  previewSync();                       // 離開影片頁就把串流斷掉
  if (p === 'annotate') resizeCanvas();
  if (p === 'grid') renderGrid();
  if (p === 'stats') loadStats();
  if (p === 'train') pollTrain(true);
  if (p === 'guide') loadLanUrls();
}

/* ══════════ 設定 / 資料夾 ══════════ */
async function loadConfig() {
  const c = await api('/api/config');
  S.root = c.root; S.dataset = c.dataset;
  S.splits = c.splits.length ? c.splits : ['train'];
  S.classes = c.classes;
  if (!S.splits.includes(S.split)) S.split = S.splits[0];
  $('rootPath').value = c.root;
  $('sideDataset').textContent = c.dataset;
  renderSplitTabs();
  renderClasses();
  renderQuickClasses();
  renderClassFilter();
  document.title = `YoloSeg Studio — ${c.dataset}`;
}

async function changeRoot(path) {
  if (!path) return;
  if (!(await confirmDirty())) return;
  try {
    await post('/api/root', { path });
    S.gen++;                       // 換資料集 → 影像 URL 換版本
    resetImage();
    S.page = 0;
    await loadConfig();
    await loadList();
    loadStats();
    if (S.items.length) await openImage(S.items[0].name);   // 切換後直接開第一張
    // 訓練頁的資料集相關欄位跟著換，其他調過的參數保留
    try {
      const d = await api('/api/train/defaults');
      TRAIN_DEFAULTS = d;
      ['trData', 'trName', 'trOutputDir'].forEach((id) => {
        const key = TR_FIELDS[id];
        if ($(id) && d[key] !== undefined) $(id).value = d[key];
      });
    } catch (e) { /* 訓練模組不可用 */ }
    toast('已切換資料夾', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

function resetImage() {
  S.cur = null; S.shapes = []; S.img = null; S.sel = -1;
  S.hist = []; S.draft = null; S.dirty = false; GRAD = null;
  $('canvasHint').classList.remove('d-none');
  renderShapes();
  draw();
}

function renderSplitTabs() {
  const box = $('splitTabs');
  box.innerHTML = '';
  S.splits.forEach((sp) => {
    const b = document.createElement('button');
    b.className = 'seg-btn' + (sp === S.split ? ' active' : '');
    b.textContent = sp;
    b.onclick = async () => {
      if (sp === S.split) return;
      if (!(await confirmDirty())) return;
      S.split = sp; S.page = 0;
      resetImage();
      renderSplitTabs();
      await loadList();
    };
    box.appendChild(b);
  });
}

/* ══════════ 影像清單 ══════════ */
async function loadList() {
  const q = new URLSearchParams({
    split: S.split, page: S.page, pageSize: S.pageSize,
    q: $('search').value.trim(),
    cls: $('filterClass').value,
    state: $('filterState').value,
  });
  const d = await api('/api/list?' + q);
  S.items = d.items; S.total = d.total; S.pageSize = d.pageSize;
  renderList();
  if (S.page_ === 'grid') renderGrid();
}

function renderList() {
  const box = $('fileList');
  box.innerHTML = '';
  S.items.forEach((it) => {
    const row = document.createElement('div');
    row.className = 'file-item' + (it.name === S.cur ? ' active' : '');
    row.dataset.name = it.name;

    const im = document.createElement('img');
    im.loading = 'lazy';
    im.src = thumbURL(S.split, it.name, 96);
    const nm = document.createElement('div');
    nm.className = 'nm'; nm.textContent = it.name; nm.title = it.name;
    const bd = document.createElement('span');
    bd.className = 'badge ' + (it.objects ? 'ok' : 'zero');
    bd.textContent = it.objects;

    row.append(im, nm, bd);
    row.onclick = () => openImage(it.name);
    box.appendChild(row);
  });

  const pages = Math.max(1, Math.ceil(S.total / S.pageSize));
  $('pageInfo').textContent = `${S.page + 1} / ${pages}（共 ${S.total} 張）`;
  $('listCount').textContent = `${S.split} — ${S.total} 張影像`;
  $('gridTitle').textContent = `多圖瀏覽 — ${S.split}（${S.total} 張）`;
  $('pagePrev').disabled = S.page <= 0;
  $('pageNext').disabled = S.page >= pages - 1;
}

function renderClassFilter() {
  const sel = $('filterClass');
  const keep = sel.value;
  sel.innerHTML = '<option value="-1">所有類別</option>';
  S.classes.forEach((n, i) => {
    const o = document.createElement('option');
    o.value = i; o.textContent = `${i} ${n}`;
    sel.appendChild(o);
  });
  sel.value = keep && Number(keep) < S.classes.length ? keep : '-1';
}

/* ══════════ 開圖 / 標記檔 ══════════ */
async function openImage(name) {
  if (name === S.cur) return;
  if (!(await confirmDirty())) return;
  S.cur = name; S.sel = -1; S.hist = []; S.draft = null; S.dirty = false; GRAD = null;
  S.userView = false;
  renderList();
  if (S.page_ === 'grid') highlightGrid();

  const my = ++openSeq;
  const split = S.split;
  try {
    const [lbl, img] = await Promise.all([
      api(`/api/label?split=${enc(split)}&name=${enc(name)}`),
      loadImg(imgURL(split, name)),
    ]);
    // 連點好幾張時，先發出的請求可能後回來；過期的結果一律丟棄，
    // 否則畫面會停在舊圖，但 S.cur 已經是別張，存檔就會寫錯檔案。
    if (my !== openSeq) return;
    S.shapes = lbl.shapes;
    S.img = img;
    $('canvasHint').classList.add('d-none');
    fitView();
    renderShapes();
  } catch (e) { toast(e.message, 'err'); }
}

function loadImg(src) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => rej(new Error('影像載入失敗'));
    im.src = src;
  });
}

async function saveLabel(silent) {
  if (!S.cur) return true;
  try {
    const r = await post('/api/label', { split: S.split, name: S.cur, shapes: S.shapes });
    S.dirty = false;
    updateStatus();
    const it = S.items.find((x) => x.name === S.cur);
    if (it) {
      it.objects = r.lines;
      it.classes = [...new Set(S.shapes.map((s) => s.cls))].sort((a, b) => a - b);
      renderList();
      if (S.page_ === 'grid') renderGrid();
    }
    if (!silent) toast(`已儲存 ${r.lines} 個物件 → ${r.labelPath}`, 'ok');
    return true;
  } catch (e) { toast('儲存失敗：' + e.message, 'err'); return false; }
}

function askUnsaved() {
  return new Promise((resolve) => {
    const dlg = $('dlgUnsaved');
    $('unsavedName').textContent = S.cur || '';
    dlg.classList.remove('d-none');
    const done = (ans) => {
      dlg.classList.add('d-none');
      document.removeEventListener('keydown', onKey, true);
      resolve(ans);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); done('cancel'); }
      if (e.key === 'Enter') { e.stopPropagation(); done('save'); }
    };
    $('unsavedSave').onclick = () => done('save');
    $('unsavedDiscard').onclick = () => done('discard');
    $('unsavedCancel').onclick = () => done('cancel');
    document.addEventListener('keydown', onKey, true);
    $('unsavedSave').focus();
  });
}

async function confirmDirty() {
  if (!S.dirty) return true;
  const ans = await askUnsaved();
  if (ans === 'cancel') return false;
  if (ans === 'save') return await saveLabel(true);
  S.dirty = false;
  return true;
}

function pushHist() {
  S.hist.push(JSON.stringify(S.shapes));
  if (S.hist.length > 60) S.hist.shift();
}
function undo() {
  if (!S.hist.length) { toast('沒有可復原的步驟', 'warn'); return; }
  S.shapes = JSON.parse(S.hist.pop());
  S.sel = Math.min(S.sel, S.shapes.length - 1);
  markDirty(); renderShapes(); draw();
}
function markDirty() { S.dirty = true; updateStatus(); }

/* ══════════ 視圖轉換 ══════════ */
function cssSize() {
  const r = CANVAS.getBoundingClientRect();
  return { w: r.width, h: r.height };
}
function resizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const { w, h } = cssSize();
  if (w < 2 || h < 2) return;                 // 版面尚未成形，等 ResizeObserver 再來
  CANVAS.width = Math.max(1, Math.round(w * dpr));
  CANVAS.height = Math.max(1, Math.round(h * dpr));
  // 使用者還沒自己縮放／平移過，就跟著版面重新置中
  if (S.img && (!S.userView || !isFinite(S.zoom) || S.zoom <= 0)) { fitView(); return; }
  draw();
}
function fitView() {
  if (!S.img) return;
  const { w, h } = cssSize();
  const z = Math.min(w / S.img.naturalWidth, h / S.img.naturalHeight) * 0.96;
  S.zoom = z;
  S.ox = (w - S.img.naturalWidth * z) / 2;
  S.oy = (h - S.img.naturalHeight * z) / 2;
  draw();
}
function fitCenter() {
  if (!S.img) return;
  const { w, h } = cssSize();
  S.ox = (w - S.img.naturalWidth * S.zoom) / 2;
  S.oy = (h - S.img.naturalHeight * S.zoom) / 2;
  draw();
}
function zoomAt(px, py, factor) {
  S.userView = true;
  const nz = Math.min(40, Math.max(0.02, S.zoom * factor));
  S.ox = px - (px - S.ox) * (nz / S.zoom);
  S.oy = py - (py - S.oy) * (nz / S.zoom);
  S.zoom = nz;
  draw();
}
function toNorm(px, py) {
  return [(px - S.ox) / (S.zoom * S.img.naturalWidth),
          (py - S.oy) / (S.zoom * S.img.naturalHeight)];
}
function toScr(nx, ny) {
  return [nx * S.img.naturalWidth * S.zoom + S.ox,
          ny * S.img.naturalHeight * S.zoom + S.oy];
}
function evPos(e) {
  const r = CANVAS.getBoundingClientRect();
  return [e.clientX - r.left, e.clientY - r.top];
}

/* ══════════ 繪製 ══════════ */
function draw() {
  const dpr = window.devicePixelRatio || 1;
  const { w, h } = cssSize();
  CTX.setTransform(dpr, 0, 0, dpr, 0, 0);
  CTX.clearRect(0, 0, w, h);
  CTX.fillStyle = cssVar('--canvas-bg', '#eceff5');
  CTX.fillRect(0, 0, w, h);
  if (!S.img) { updateStatus(); return; }

  CTX.imageSmoothingEnabled = S.zoom < 4;
  CTX.drawImage(S.img, S.ox, S.oy, S.img.naturalWidth * S.zoom, S.img.naturalHeight * S.zoom);

  const fill = $('showFill').checked;
  const showIdx = $('showIdx').checked;

  S.shapes.forEach((sh, i) => {
    const col = classColor(sh.cls);
    const on = i === S.sel;
    const pts = sh.points.map((p) => toScr(p[0], p[1]));

    CTX.beginPath();
    pts.forEach(([x, y], k) => (k ? CTX.lineTo(x, y) : CTX.moveTo(x, y)));
    CTX.closePath();
    if (fill) {
      CTX.fillStyle = col.replace('hsl', 'hsla').replace(')', on ? ' / .3)' : ' / .15)');
      CTX.fill();
    }
    CTX.lineWidth = on ? 2.5 : 1.6;
    CTX.strokeStyle = col;
    CTX.stroke();

    const [lx, ly] = pts.reduce((a, p) => (p[1] < a[1] ? p : a), pts[0]);
    const txt = `${sh.cls} ${className(sh.cls)}${sh.kind === 'bbox' ? ' [box]' : ''}`;
    CTX.font = '600 12px Inter,system-ui,sans-serif';
    CTX.fillStyle = col;
    CTX.fillRect(lx, ly - 18, CTX.measureText(txt).width + 10, 16);
    CTX.fillStyle = '#fff';
    CTX.fillText(txt, lx + 5, ly - 6);

    if (on) {
      const dot = cssVar('--card', '#fff');
      const idxCol = cssVar('--text', '#111');
      const touch = HIT > 10;                    // 觸控時頂點畫大一點才好抓
      pts.forEach(([x, y], k) => {
        const base = touch ? 6.5 : 4.5;
        const r = (S.drag && S.drag.type === 'vertex' && S.drag.pt === k) ? base + 1.5 : base;
        CTX.beginPath(); CTX.arc(x, y, r, 0, 7);
        CTX.fillStyle = dot; CTX.fill();
        CTX.lineWidth = 2; CTX.strokeStyle = col; CTX.stroke();
        if (showIdx) { CTX.fillStyle = idxCol; CTX.fillText(String(k), x + 8, y - 8); }
      });
    }
  });

  if (S.draft && S.draft.length) {
    const pts = S.draft.map((p) => toScr(p[0], p[1]));
    CTX.beginPath();
    pts.forEach(([x, y], k) => (k ? CTX.lineTo(x, y) : CTX.moveTo(x, y)));
    if (S.draftHover) CTX.lineTo(S.draftHover[0], S.draftHover[1]);
    CTX.strokeStyle = classColor(S.curClass);
    CTX.setLineDash([5, 4]); CTX.lineWidth = 2; CTX.stroke(); CTX.setLineDash([]);
    pts.forEach(([x, y], k) => {
      CTX.beginPath(); CTX.arc(x, y, k === 0 ? 6 : 4, 0, 7);
      CTX.fillStyle = k === 0 ? cssVar('--card', '#fff') : classColor(S.curClass);
      CTX.fill();
      CTX.lineWidth = 2; CTX.strokeStyle = classColor(S.curClass); CTX.stroke();
    });
  }
  updateStatus();
}

function updateStatus() {
  $('stFile').textContent = S.cur ? `${S.split} / ${S.cur}` : '—';
  $('stSize').textContent = S.img ? `${S.img.naturalWidth}×${S.img.naturalHeight}` : '';
  $('stZoom').textContent = S.img ? `${Math.round(S.zoom * 100)}%` : '';
  $('stMode').textContent = S.mode === 'draw'
    ? '新增多邊形中（Enter 完成 / Esc 取消）' : `物件 ${S.shapes.length}`;
  const d = $('stDirty');
  d.textContent = S.dirty ? '● 未儲存' : '';
  d.className = S.dirty ? 'on' : '';
}

/* ══════════ 命中測試 ══════════ */
let HIT = 8;                 // 觸控時會放大（見 onPointerDown）
function hitVertex(px, py) {
  for (let i = S.shapes.length - 1; i >= 0; i--) {
    const sh = S.shapes[i];
    for (let k = 0; k < sh.points.length; k++) {
      const [x, y] = toScr(sh.points[k][0], sh.points[k][1]);
      if (Math.abs(x - px) <= HIT && Math.abs(y - py) <= HIT) return { shape: i, pt: k };
    }
  }
  return null;
}
function hitShape(px, py) {
  const [nx, ny] = toNorm(px, py);
  for (let i = S.shapes.length - 1; i >= 0; i--) {
    if (pointInPoly(nx, ny, S.shapes[i].points)) return i;
  }
  return -1;
}
function pointInPoly(x, y, pts) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function hitEdge(px, py) {
  for (let i = S.shapes.length - 1; i >= 0; i--) {
    const pts = S.shapes[i].points.map((p) => toScr(p[0], p[1]));
    for (let k = 0; k < pts.length; k++) {
      if (distToSeg(px, py, pts[k], pts[(k + 1) % pts.length]) <= HIT) return { shape: i, edge: k };
    }
  }
  return null;
}
function distToSeg(px, py, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len = dx * dx + dy * dy;
  let t = len ? ((px - a[0]) * dx + (py - a[1]) * dy) / len : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy));
}

/* ══════════════════════════════════════════════════════════════
   指標輸入（滑鼠 + 觸控共用 Pointer Events）
   單指：拖曳頂點／移動多邊形／平移；雙指：縮放與平移
   ══════════════════════════════════════════════════════════════ */
const POINTERS = new Map();
let PINCH = null;

CANVAS.addEventListener('contextmenu', (e) => e.preventDefault());

CANVAS.addEventListener('pointerdown', (e) => {
  POINTERS.set(e.pointerId, evPos(e));
  try { CANVAS.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }

  if (POINTERS.size === 2) {            // 進入雙指手勢，取消單指的拖曳
    const [a, b] = [...POINTERS.values()];
    PINCH = {
      dist: Math.hypot(a[0] - b[0], a[1] - b[1]),
      mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2],
      ox: S.ox, oy: S.oy, zoom: S.zoom,
    };
    S.drag = null;
    S.userView = true;
    return;
  }
  if (POINTERS.size > 2) return;
  onPointerDown(e);
});

CANVAS.addEventListener('pointermove', (e) => {
  if (POINTERS.has(e.pointerId)) POINTERS.set(e.pointerId, evPos(e));

  if (PINCH && POINTERS.size >= 2) {
    const [a, b] = [...POINTERS.values()];
    const dist = Math.hypot(a[0] - b[0], a[1] - b[1]);
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    if (PINCH.dist > 8) {
      const k = dist / PINCH.dist;
      const nz = Math.min(40, Math.max(0.02, PINCH.zoom * k));
      // 以起始中點為錨縮放，再跟著中點位移平移
      S.ox = PINCH.mid[0] - (PINCH.mid[0] - PINCH.ox) * (nz / PINCH.zoom) + (mid[0] - PINCH.mid[0]);
      S.oy = PINCH.mid[1] - (PINCH.mid[1] - PINCH.oy) * (nz / PINCH.zoom) + (mid[1] - PINCH.mid[1]);
      S.zoom = nz;
      draw();
    }
    return;
  }
  onPointerMove(e);
});

function endPointer(e) {
  POINTERS.delete(e.pointerId);
  try { CANVAS.releasePointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
  if (POINTERS.size < 2) PINCH = null;
  if (S.drag && S.drag.type !== 'pan') renderShapes();
  S.drag = null;
}
CANVAS.addEventListener('pointerup', endPointer);
CANVAS.addEventListener('pointercancel', endPointer);

function onPointerDown(e) {
  if (!S.img) return;
  const [px, py] = evPos(e);
  HIT = e.pointerType === 'touch' ? 16 : 8;    // 觸控的命中範圍要大一點

  if (e.button === 1 || S.space) {
    S.drag = { type: 'pan', x: px, y: py, ox: S.ox, oy: S.oy };
    e.preventDefault();
    return;
  }
  if (e.button === 2) {
    const hv = hitVertex(px, py);
    if (hv) deleteVertex(hv.shape, hv.pt);
    return;
  }
  if (e.button !== 0) return;

  if (S.mode === 'draw') {
    const [nx, ny] = toNorm(px, py);
    if (!S.draft) S.draft = [];
    if (S.draft.length >= 3) {
      const [fx, fy] = toScr(S.draft[0][0], S.draft[0][1]);
      if (Math.hypot(fx - px, fy - py) <= HIT + 2) { finishDraft(); return; }
    }
    S.draft.push([clamp01(nx), clamp01(ny)]);
    draw();
    return;
  }

  const hv = hitVertex(px, py);
  if (hv) {
    if (e.altKey) { deleteVertex(hv.shape, hv.pt); return; }
    S.sel = hv.shape;
    pushHist();
    S.drag = { type: 'vertex', shape: hv.shape, pt: hv.pt };
    renderShapes(); draw();
    return;
  }

  const hs = hitShape(px, py);
  if (hs >= 0) {
    S.sel = hs;
    pushHist();
    S.drag = { type: 'move', shape: hs, x: px, y: py, orig: S.shapes[hs].points.map((p) => [...p]) };
    renderShapes(); draw();
    return;
  }

  S.sel = -1;
  S.drag = { type: 'pan', x: px, y: py, ox: S.ox, oy: S.oy };
  renderShapes(); draw();
}

function onPointerMove(e) {
  if (!S.img || S.page_ !== 'annotate') return;
  const [px, py] = evPos(e);

  if (S.mode === 'draw' && S.draft && S.draft.length) {
    S.draftHover = [px, py];
    draw();
  }
  if (!S.drag) return;

  if (S.drag.type === 'pan') {
    S.userView = true;
    S.ox = S.drag.ox + (px - S.drag.x);
    S.oy = S.drag.oy + (py - S.drag.y);
    draw();
  } else if (S.drag.type === 'vertex') {
    const [nx, ny] = toNorm(px, py);
    const sh = S.shapes[S.drag.shape];
    sh.points[S.drag.pt] = [clamp01(nx), clamp01(ny)];
    if (sh.kind === 'bbox') sh.kind = 'polygon';
    markDirty(); draw();
  } else if (S.drag.type === 'move') {
    const [nx0, ny0] = toNorm(S.drag.x, S.drag.y);
    const [nx1, ny1] = toNorm(px, py);
    const dx = nx1 - nx0, dy = ny1 - ny0;
    S.shapes[S.drag.shape].points = S.drag.orig.map((p) => [clamp01(p[0] + dx), clamp01(p[1] + dy)]);
    markDirty(); draw();
  }
}

CANVAS.addEventListener('dblclick', (e) => {
  if (!S.img) return;
  const [px, py] = evPos(e);
  if (S.mode === 'draw') {
    if (S.draft && S.draft.length > 3) S.draft.pop();
    finishDraft();
    return;
  }
  const he = hitEdge(px, py);
  if (!he) return;
  pushHist();
  const [nx, ny] = toNorm(px, py);
  S.shapes[he.shape].points.splice(he.edge + 1, 0, [clamp01(nx), clamp01(ny)]);
  if (S.shapes[he.shape].kind === 'bbox') S.shapes[he.shape].kind = 'polygon';
  S.sel = he.shape;
  markDirty(); renderShapes(); draw();
});

CANVAS.addEventListener('wheel', (e) => {
  if (!S.img) return;
  e.preventDefault();
  const [px, py] = evPos(e);
  zoomAt(px, py, e.deltaY < 0 ? 1.15 : 1 / 1.15);
}, { passive: false });

function deleteVertex(si, pi) {
  const sh = S.shapes[si];
  if (sh.points.length <= 3) { toast('多邊形至少需 3 個頂點', 'err'); return; }
  pushHist();
  sh.points.splice(pi, 1);
  if (sh.kind === 'bbox') sh.kind = 'polygon';
  S.sel = si;
  markDirty(); renderShapes(); draw();
}

function finishDraft() {
  if (S.draft && S.draft.length >= 3) {
    pushHist();
    S.shapes.push({ cls: S.curClass, kind: 'polygon', points: S.draft });
    S.sel = S.shapes.length - 1;
    markDirty();
  }
  S.draft = null; S.draftHover = null;
  setMode('select');
  renderShapes(); draw();
}

function setMode(m) {
  S.mode = m;
  $('toolSelect').classList.toggle('active', m === 'select');
  $('toolDraw').classList.toggle('active', m === 'draw');
  CANVAS.style.cursor = m === 'draw' ? 'crosshair' : 'default';
  if (m !== 'draw') { S.draft = null; S.draftHover = null; }
  updateStatus();
}

/* ══════════════════════════════════════════════════════════════
   一鍵自動優化 polygon ROI
   灰階 → 3×3 降噪 → Sobel 邊緣圖；多邊形等距重取樣後沿法線找最強邊緣
   貼合，再 Laplacian 平滑 + Douglas–Peucker 精簡。只改記憶體，不寫檔。
   ══════════════════════════════════════════════════════════════ */
let GRAD = null;

function buildGradient() {
  if (!S.img) return null;
  const maxSide = 1280;
  const scale = Math.min(1, maxSide / Math.max(S.img.naturalWidth, S.img.naturalHeight));
  const w = Math.max(4, Math.round(S.img.naturalWidth * scale));
  const h = Math.max(4, Math.round(S.img.naturalHeight * scale));

  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  cx.drawImage(S.img, 0, 0, w, h);
  let px;
  try { px = cx.getImageData(0, 0, w, h).data; } catch (err) { return null; }

  const lum = new Float32Array(w * h);
  for (let i = 0, p = 0; i < lum.length; i++, p += 4) {
    lum[i] = 0.299 * px[p] + 0.587 * px[p + 1] + 0.114 * px[p + 2];
  }
  const sm = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let s = 0, n = 0;
      for (let dy = -1; dy <= 1; dy++) {
        const yy = y + dy;
        if (yy < 0 || yy >= h) continue;
        for (let dx = -1; dx <= 1; dx++) {
          const xx = x + dx;
          if (xx < 0 || xx >= w) continue;
          s += lum[yy * w + xx]; n++;
        }
      }
      sm[y * w + x] = s / n;
    }
  }
  const mag = new Float32Array(w * h);
  let mx = 1e-6;
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const gx = -sm[i - w - 1] - 2 * sm[i - 1] - sm[i + w - 1]
                 + sm[i - w + 1] + 2 * sm[i + 1] + sm[i + w + 1];
      const gy = -sm[i - w - 1] - 2 * sm[i - w] - sm[i - w + 1]
                 + sm[i + w - 1] + 2 * sm[i + w] + sm[i + w + 1];
      const m = Math.hypot(gx, gy);
      mag[i] = m;
      if (m > mx) mx = m;
    }
  }
  for (let i = 0; i < mag.length; i++) mag[i] /= mx;
  return { w, h, mag };
}

function sampleMag(g, x, y) {
  if (!(x >= 0 && y >= 0 && x <= g.w - 1 && y <= g.h - 1)) return 0;
  const x0 = Math.floor(x), y0 = Math.floor(y);
  const x1 = Math.min(g.w - 1, x0 + 1), y1 = Math.min(g.h - 1, y0 + 1);
  const fx = x - x0, fy = y - y0;
  const a = g.mag[y0 * g.w + x0], b = g.mag[y0 * g.w + x1];
  const c = g.mag[y1 * g.w + x0], d = g.mag[y1 * g.w + x1];
  return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy;
}

function perimeter(pts) {
  let s = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length];
    s += Math.hypot(b[0] - a[0], b[1] - a[1]);
  }
  return s;
}

function resamplePoly(pts, step) {
  const per = perimeter(pts);
  if (!(per > 0) || !(step > 0)) return pts.map((p) => [...p]);
  if (per / step > 2000) step = per / 2000;
  const out = [];
  let carry = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length];
    const seg = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (seg === 0) continue;
    let t = carry;
    while (t < seg) {
      const r = t / seg;
      out.push([a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r]);
      t += step;
    }
    carry = t - seg;
  }
  return out.length >= 3 ? out : pts.map((p) => [...p]);
}

function normalAt(pts, i) {
  const n = pts.length;
  const a = pts[(i - 1 + n) % n], b = pts[(i + 1) % n];
  const tx = b[0] - a[0], ty = b[1] - a[1];
  const len = Math.hypot(tx, ty) || 1;
  return [-ty / len, tx / len];
}

function smoothPoly(pts, alpha) {
  const n = pts.length;
  return pts.map((p, i) => {
    const a = pts[(i - 1 + n) % n], b = pts[(i + 1) % n];
    return [p[0] + alpha * ((a[0] + b[0]) / 2 - p[0]),
            p[1] + alpha * ((a[1] + b[1]) / 2 - p[1])];
  });
}

function simplifyPoly(pts, eps) {
  if (pts.length < 4) return pts.map((p) => [...p]);
  const keep = new Array(pts.length).fill(false);
  keep[0] = keep[pts.length - 1] = true;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [s, e] = stack.pop();
    let far = -1, fd = eps;
    for (let i = s + 1; i < e; i++) {
      const d = distToSeg(pts[i][0], pts[i][1], pts[s], pts[e]);
      if (d > fd) { fd = d; far = i; }
    }
    if (far > 0) { keep[far] = true; stack.push([s, far], [far, e]); }
  }
  const out = pts.filter((_, i) => keep[i]);
  return out.length >= 3 ? out : pts.map((p) => [...p]);
}

function optimizeShape(sh, g, R) {
  if (!sh || !sh.points || sh.points.length < 3) return false;
  const W = g.w, H = g.h;
  let pts = sh.points.map((p) => [p[0] * W, p[1] * H]);
  pts = resamplePoly(pts, Math.max(2, R * 0.6));
  if (pts.length < 3) return false;

  const PEN = 0.035;
  for (let it = 0; it < 3; it++) {
    const moved = pts.map((p, i) => {
      const nrm = normalAt(pts, i);
      let bx = p[0], by = p[1], bv = sampleMag(g, p[0], p[1]);
      for (let t = -R; t <= R; t += 0.5) {
        if (t === 0) continue;
        const x = p[0] + nrm[0] * t, y = p[1] + nrm[1] * t;
        const v = sampleMag(g, x, y) - PEN * Math.abs(t);
        if (v > bv) { bv = v; bx = x; by = y; }
      }
      return [bx, by];
    });
    pts = smoothPoly(moved, 0.3);
  }

  let eps = Math.max(0.9, R * 0.22);
  let out = simplifyPoly(pts, eps);
  while (out.length > 120) { eps *= 1.5; out = simplifyPoly(pts, eps); }
  if (out.length < 3) return false;

  sh.points = out.map((p) => [clamp01(p[0] / W), clamp01(p[1] / H)]);
  sh.kind = 'polygon';
  return true;
}

function optimizeShapes(idxList) {
  if (!S.img) { toast('請先開啟影像', 'err'); return; }
  if (!idxList.length) { toast('沒有可優化的物件', 'warn'); return; }
  if (!GRAD) GRAD = buildGradient();
  if (!GRAD) { toast('無法讀取影像像素，優化中止', 'err'); return; }

  pushHist();
  const R = Number($('optStrength').value) || 7;
  let ok = 0;
  idxList.forEach((i) => { if (optimizeShape(S.shapes[i], GRAD, R)) ok++; });
  if (!ok) { S.hist.pop(); toast('沒有可優化的物件', 'warn'); return; }

  markDirty(); renderShapes(); draw();
  toast(`已優化 ${ok} 個物件 — 尚未儲存，確認後請按 Ctrl+S（Ctrl+Z 可還原）`, 'warn');
}

const optimizeSelected = () => optimizeShapes(
  S.sel >= 0 ? [S.sel] : S.shapes.map((_, i) => i));
const optimizeAll = () => optimizeShapes(S.shapes.map((_, i) => i));

/* ══════════ 物件清單 ══════════ */
function renderShapes() {
  const box = $('shapeList');
  box.innerHTML = '';
  S.shapes.forEach((sh, i) => {
    const row = document.createElement('div');
    row.className = 'shape-row' + (i === S.sel ? ' active' : '');

    const sw = document.createElement('span');
    sw.className = 'swatch'; sw.style.background = classColor(sh.cls);

    const sel = document.createElement('select');
    sel.className = 'input input-sm';
    S.classes.forEach((n, k) => {
      const o = document.createElement('option');
      o.value = k; o.textContent = `${k} ${n}`;
      sel.appendChild(o);
    });
    if (sh.cls >= S.classes.length) {
      const o = document.createElement('option');
      o.value = sh.cls; o.textContent = `${sh.cls} (未定義)`;
      sel.appendChild(o);
    }
    sel.value = sh.cls;
    sel.onchange = () => { pushHist(); sh.cls = Number(sel.value); markDirty(); renderShapes(); draw(); };
    sel.onclick = (e) => e.stopPropagation();

    const pt = document.createElement('span');
    pt.className = 'pt'; pt.textContent = `${sh.points.length}pt`;

    const x = document.createElement('button');
    x.className = 'btn-x'; x.textContent = '✕'; x.title = '刪除';
    x.onclick = (e) => { e.stopPropagation(); delShape(i); };

    row.append(sw, sel, pt, x);
    row.onclick = () => { S.sel = i; renderShapes(); draw(); };
    box.appendChild(row);
  });
  updateStatus();
}

function delShape(i) {
  if (i < 0 || i >= S.shapes.length) return;
  pushHist();
  S.shapes.splice(i, 1);
  S.sel = Math.min(S.sel, S.shapes.length - 1);
  markDirty(); renderShapes(); draw();
}

/* ══════════ 類別 ══════════ */
function renderClasses() {
  const box = $('classList');
  box.innerHTML = '';
  S.classes.forEach((n, i) => {
    const row = document.createElement('div');
    row.className = 'class-row';

    const sw = document.createElement('span');
    sw.className = 'swatch'; sw.style.background = classColor(i);
    const id = document.createElement('span');
    id.className = 'id'; id.textContent = i;
    const inp = document.createElement('input');
    inp.type = 'text'; inp.className = 'input'; inp.value = n;
    inp.oninput = () => { S.classes[i] = inp.value; renderQuickClasses(); };

    const x = document.createElement('button');
    x.className = 'btn-x'; x.textContent = '✕'; x.title = '移除此類別';
    x.onclick = () => {
      if (!confirm(`移除類別 ${i}「${S.classes[i]}」？\n（僅改 data.yaml，既有標記的 id 不會改變）`)) return;
      S.classes.splice(i, 1);
      S.curClass = Math.max(0, Math.min(S.curClass, S.classes.length - 1));
      renderClasses(); renderQuickClasses(); renderClassFilter(); renderShapes(); draw();
    };

    row.append(sw, id, inp, x);
    box.appendChild(row);
  });
}

function renderQuickClasses() {
  const box = $('quickClasses');
  box.innerHTML = '';
  S.classes.forEach((n, i) => {
    const c = document.createElement('button');
    c.className = 'chip' + (i === S.curClass ? ' active' : '');
    const sw = document.createElement('span');
    sw.className = 'swatch'; sw.style.background = classColor(i);
    const t = document.createElement('span');
    t.textContent = `${i} ${n}`;
    c.append(sw, t);
    c.onclick = () => { S.curClass = i; renderQuickClasses(); };
    box.appendChild(c);
  });
}

/* ══════════ 多圖瀏覽 ══════════ */
function renderGrid() {
  const box = $('gridWrap');
  box.innerHTML = '';
  S.items.forEach((it) => {
    const cell = document.createElement('div');
    cell.className = 'cell' + (it.name === S.cur ? ' active' : '');
    cell.dataset.name = it.name;

    const cv = document.createElement('canvas');
    cv.width = 380; cv.height = 285;
    const cap = document.createElement('div');
    cap.className = 'cap';
    const nm = document.createElement('span');
    nm.className = 'nm'; nm.textContent = it.name; nm.title = it.name;
    const bd = document.createElement('span');
    bd.className = 'badge ' + (it.objects ? 'ok' : 'zero');
    bd.textContent = it.objects;
    cap.append(nm, bd);

    cell.append(cv, cap);
    cell.onclick = async () => { await openImage(it.name); if (S.cur === it.name) switchPage('annotate'); };
    box.appendChild(cell);
    drawCell(cv, it);
  });
}

async function drawCell(cv, it) {
  const ctx = cv.getContext('2d');
  ctx.fillStyle = cssVar('--canvas-bg', '#eceff5');
  ctx.fillRect(0, 0, cv.width, cv.height);
  try {
    const [im, lbl] = await Promise.all([
      loadImg(thumbURL(S.split, it.name, 380)),
      it.objects ? api(`/api/label?split=${enc(S.split)}&name=${enc(it.name)}`) : Promise.resolve({ shapes: [] }),
    ]);
    const z = Math.min(cv.width / im.naturalWidth, cv.height / im.naturalHeight);
    const w = im.naturalWidth * z, h = im.naturalHeight * z;
    const ox = (cv.width - w) / 2, oy = (cv.height - h) / 2;
    ctx.drawImage(im, ox, oy, w, h);

    lbl.shapes.forEach((sh) => {
      const col = classColor(sh.cls);
      ctx.beginPath();
      sh.points.forEach((p, k) => {
        const x = ox + p[0] * w, y = oy + p[1] * h;
        if (k) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      });
      ctx.closePath();
      ctx.fillStyle = col.replace('hsl', 'hsla').replace(')', ' / .26)');
      ctx.fill();
      ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke();
    });
  } catch (err) { /* 縮圖失敗留底色 */ }
}

function highlightGrid() {
  document.querySelectorAll('#gridWrap .cell').forEach((c) => {
    c.classList.toggle('active', c.dataset.name === S.cur);
  });
}

/* ══════════════════════════════════════════════════════════════
   影片 → 資料集
   ══════════════════════════════════════════════════════════════ */
let VIDEO_TIMER = null;
let VIDEO_LOG_NEXT = 0;     // 只向後端要新的記錄行
let PV_ACTIVE = false;      // 預覽串流是否已連上

/* 預覽用 MJPEG 串流：一條連線由伺服器推畫面，關掉就完全不產生預覽 */
function previewStart() {
  if (PV_ACTIVE) return;
  const img = $('vidPreview');
  img.src = `/api/video/stream?fps=${$('pvFps').value}&t=${Date.now()}`;
  PV_ACTIVE = true;
  $('pvHint').classList.add('d-none');
}
function previewStop() {
  if (!PV_ACTIVE) return;
  const img = $('vidPreview');
  img.removeAttribute('src');       // 斷線 → 後端 viewer 計數歸零
  img.removeAttribute('srcset');
  PV_ACTIVE = false;
  $('pvHint').classList.remove('d-none');
}
let VIDEO_RUNNING = false;
function previewSync() {
  const running = VIDEO_RUNNING;
  const want = running && $('pvOn').checked && S.page_ === 'video';
  if (want) previewStart(); else previewStop();
  $('pvHint').textContent = running
    ? ($('pvOn').checked ? '等待畫面…' : '預覽已關閉（轉檔端不會產生預覽）')
    : '尚未開始轉換';
}

async function loadVideoDefaults() {
  try {
    const d = await api('/api/video/defaults');
    $('vidDir').value = d.videoDir;
    $('vidOut').value = d.outDir;
    $('vidModel').value = d.modelPath;
    $('vidConf').value = d.conf;
    $('vidImgsz').value = d.imgsz;
    $('vidMinArea').value = d.minArea;
    $('vidEdge').value = d.edgeMargin;
    $('vidMaxPts').value = d.maxPolyPoints;
    $('vidConsec').value = d.consecutive;
    $('consecText').textContent = d.consecutive;
    $('vidSplit').value = d.split;
  } catch (e) { /* 影片模組不可用時靜默 */ }
}

async function scanVideos() {
  try {
    const d = await api('/api/video/list?dir=' + enc($('vidDir').value.trim()));
    const tb = $('vidTable');
    tb.innerHTML = '';
    if (!d.videos.length) {
      tb.innerHTML = '<tr><td colspan="4" class="muted center">找不到影片</td></tr>';
    } else {
      d.videos.forEach((v) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${v.name}</td><td class="muted">${v.sizeMB} MB</td><td>—</td><td>—</td>`;
        tb.appendChild(tr);
      });
    }
    $('vsVideos').textContent = d.videos.length;
    toast(`找到 ${d.videos.length} 部影片`, 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

async function startVideoJob() {
  const body = {
    videoDir: $('vidDir').value.trim(),
    outDir: $('vidOut').value.trim(),
    modelPath: $('vidModel').value.trim(),
    conf: Number($('vidConf').value),
    imgsz: Number($('vidImgsz').value),
    minArea: Number($('vidMinArea').value),
    edgeMargin: Number($('vidEdge').value),
    maxPolyPoints: Number($('vidMaxPts').value),
    split: $('vidSplit').value,
  };
  if (!confirm(`開始轉換？\n影片：${body.videoDir}\n輸出：${body.outDir}\n\n`
    + '影像會依現有數字續編寫入，不會覆蓋既有檔案。')) return;
  try {
    const r = await post('/api/video/start', body);
    if (!r.ok) { toast(r.error || '無法啟動', 'err'); return; }
    toast('已開始轉換', 'ok');
    VIDEO_LOG_NEXT = 0;
    $('vidLog').textContent = '';
    VIDEO_RUNNING = true;
    previewSync();
    pollVideo(true);
  } catch (e) { toast(e.message, 'err'); }
}

async function stopVideoJob() {
  try {
    const r = await post('/api/video/stop', {});
    toast(r.message || '已送出中止', 'warn');
  } catch (e) { toast(e.message, 'err'); }
}

let VIDEO_INFLIGHT = false;
function pollVideo(force) {
  if (VIDEO_TIMER) clearTimeout(VIDEO_TIMER);
  if (VIDEO_INFLIGHT) {                 // 避免兩個輪詢用同一個 logFrom 重複拿記錄
    VIDEO_TIMER = setTimeout(() => pollVideo(force), 400);
    return;
  }
  VIDEO_INFLIGHT = true;
  // 只要新的 log 行；狀態本體很小，1 Hz 輪詢的成本可忽略
  api('/api/video/status?logFrom=' + VIDEO_LOG_NEXT).then((st) => {
    renderVideoStatus(st);
    // 沒在跑就把輪詢放慢到 5 秒，閒置時幾乎不佔資源
    const gap = st.running ? 1000 : 5000;
    if (st.running || force) VIDEO_TIMER = setTimeout(() => pollVideo(false), gap);
  }).catch(() => { /* 模組不可用 */ })
    .finally(() => { VIDEO_INFLIGHT = false; });
}

function renderVideoStatus(st) {
  const running = !!st.running;
  VIDEO_RUNNING = running;
  $('btnVideoStart').disabled = running;
  $('btnVideoStop').disabled = !running;
  $('navVideoDot').classList.toggle('d-none', !running);

  const ph = $('vidPhase');
  ph.textContent = st.phase;
  ph.className = 'badge ' + (st.phase === 'error' ? 'err'
    : st.phase === 'finished' ? 'fin' : running ? 'run' : '');

  const pct = st.framesTotal ? Math.min(100, st.framesDone / st.framesTotal * 100) : 0;
  $('vidBar').style.width = pct.toFixed(1) + '%';
  $('vidPct').textContent = pct.toFixed(1) + '%';
  $('vidCurrent').textContent = st.currentVideo
    ? `${st.currentVideo}（${st.videoIndex + 1}/${st.videoCount}）` : '—';

  $('vsVideos').textContent = st.videoCount || (st.videos ? st.videos.length : 0);
  $('vsFrames').textContent = st.framesDone.toLocaleString();
  $('vsCaptured').textContent = st.captured;
  $('vsElapsed').textContent = st.elapsed ? `${st.elapsed}s` : '0s';

  if (st.videos && st.videos.length) {
    const tb = $('vidTable');
    tb.innerHTML = '';
    st.videos.forEach((v, i) => {
      const tr = document.createElement('tr');
      const cur = running && i === st.videoIndex ? ' ▶' : '';
      tr.innerHTML = `<td>${v.name}${cur}</td><td class="muted">${v.frames || '—'}</td>`
        + `<td>${v.processed || 0}</td><td><b>${v.captured || 0}</b></td>`;
      tb.appendChild(tr);
    });
  }

  // 增量附加：後端只回傳 logFrom 之後的新行
  const log = $('vidLog');
  if (st.logFrom === 0 && VIDEO_LOG_NEXT === 0) log.textContent = '';
  if (st.log && st.log.length) {
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
    log.textContent += (log.textContent ? '\n' : '') + st.log.join('\n');
    if (atBottom) log.scrollTop = log.scrollHeight;
  }
  if (typeof st.logNext === 'number') VIDEO_LOG_NEXT = st.logNext;

  const info = st.currentVideo
    ? `${st.currentVideo} · frame ${st.framesDone} · 已收錄 ${st.captured}`
    : '關閉「顯示」可讓轉檔端完全不產生預覽';
  $('pvInfo').textContent = info;
  previewSync();

  const canOpen = !!st.datasetDir && !running;
  $('btnOpenAsDataset').disabled = !canOpen;
  $('btnOpenAsDataset').dataset.dir = st.datasetDir || '';

  if (st.error) $('vidPhase').title = st.error;
}

/* ══════════════════════════════════════════════════════════════
   模型訓練
   ══════════════════════════════════════════════════════════════ */
let TRAIN_TIMER = null;
let TRAIN_LOG_NEXT = 0;
let TRAIN_DEFAULTS = null;

// 欄位 id ↔ 後端參數名
const TR_FIELDS = {
  trData: 'data', trModel: 'model', trEpochs: 'epochs', trImgsz: 'imgsz',
  trBatch: 'batch', trDevice: 'device', trWorkers: 'workers', trPatience: 'patience',
  trLr0: 'lr0', trLrf: 'lrf', trMaskRatio: 'maskRatio', trSavePeriod: 'savePeriod',
  trProject: 'project', trName: 'name',
  trAmp: 'amp', trCache: 'cache', trResume: 'resume',
  trOverlap: 'overlapMask', trRetina: 'retinaMasks',
  trDoExport: 'doExport', trExportHalf: 'exportHalf', trExportDynamic: 'exportDynamic',
  trExportFormat: 'exportFormat', trOutputDir: 'outputDir',
  trCopyBest: 'copyBest', trCopyLast: 'copyLast', trCopyExport: 'copyExport',
  aug_hsv_h: 'hsv_h', aug_hsv_s: 'hsv_s', aug_hsv_v: 'hsv_v', aug_bgr: 'bgr',
  aug_degrees: 'degrees', aug_translate: 'translate', aug_scale: 'scale',
  aug_shear: 'shear', aug_perspective: 'perspective',
  aug_flipud: 'flipud', aug_fliplr: 'fliplr', aug_mosaic: 'mosaic',
  aug_close_mosaic: 'close_mosaic', aug_mixup: 'mixup',
  aug_copy_paste: 'copy_paste', aug_copy_paste_mode: 'copy_paste_mode',
};

function fillTrainForm(d) {
  Object.entries(TR_FIELDS).forEach(([id, key]) => {
    const el = $(id);
    if (!el || d[key] === undefined) return;
    if (el.type === 'checkbox') el.checked = !!d[key];
    else el.value = d[key];
  });
}

function readTrainForm() {
  const out = {};
  Object.entries(TR_FIELDS).forEach(([id, key]) => {
    const el = $(id);
    if (!el) return;
    if (el.type === 'checkbox') out[key] = el.checked;
    else if (el.type === 'number') out[key] = Number(el.value);
    else out[key] = el.value.trim();
  });
  return out;
}

async function loadTrainDefaults(force) {
  try {
    const d = await api('/api/train/defaults');
    TRAIN_DEFAULTS = d;
    if (force || !$('trData').value) fillTrainForm(d);
  } catch (e) { /* 訓練模組不可用時靜默 */ }
}

async function startTrain() {
  const cfg = readTrainForm();
  if (!confirm(`開始訓練？\n資料：${cfg.data}\n權重：${cfg.model}\n`
    + `${cfg.epochs} epochs, imgsz ${cfg.imgsz}, batch ${cfg.batch}, device ${cfg.device}\n`
    + `輸出：${cfg.project}\\${cfg.name}`)) return;
  try {
    const r = await post('/api/train/start', cfg);
    if (!r.ok) { toast(r.error || '無法啟動訓練', 'err'); return; }
    TRAIN_LOG_NEXT = 0;
    $('trLog').textContent = '';
    toast('訓練已開始', 'ok');
    pollTrain(true);
  } catch (e) { toast(e.message, 'err'); }
}

async function stopTrain() {
  if (!confirm('中止訓練？\n會在目前 batch 結束後停止，已訓練的權重仍會保留。')) return;
  try {
    const r = await post('/api/train/stop', {});
    toast(r.message || '已送出中止', 'warn');
  } catch (e) { toast(e.message, 'err'); }
}

let TRAIN_INFLIGHT = false;
function pollTrain(force) {
  if (TRAIN_TIMER) clearTimeout(TRAIN_TIMER);
  // 兩個輪詢同時在路上時，兩邊都會用同一個 logFrom 去要記錄，回來就會重複又亂序
  if (TRAIN_INFLIGHT) {
    TRAIN_TIMER = setTimeout(() => pollTrain(force), 400);
    return;
  }
  TRAIN_INFLIGHT = true;
  api('/api/train/status?logFrom=' + TRAIN_LOG_NEXT).then((st) => {
    renderTrainStatus(st);
    const gap = st.running ? 1000 : 5000;
    if (st.running || force) TRAIN_TIMER = setTimeout(() => pollTrain(false), gap);
  }).catch(() => { /* 模組不可用 */ })
    .finally(() => { TRAIN_INFLIGHT = false; });
}

function fmtSec(s) {
  s = Math.max(0, Math.round(s || 0));
  if (s < 60) return s + 's';
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}
const pick = (o, ...keys) => {
  for (const k of keys) if (o && o[k] !== undefined) return o[k];
  return undefined;
};

function renderTrainStatus(st) {
  const running = !!st.running;
  $('btnTrainStart').disabled = running;
  $('btnTrainStop').disabled = !running;
  $('navTrainDot').classList.toggle('d-none', !running);

  const ph = $('trPhase');
  ph.textContent = st.stopping ? 'stopping' : st.phase;
  ph.className = 'badge ' + (st.phase === 'error' ? 'err'
    : st.phase === 'finished' ? 'fin' : running ? 'run' : '');
  ph.title = st.error || '';

  const m5095 = pick(st.metrics, 'mAP50-95(M)', 'mAP50-95(B)');
  const m50 = pick(st.metrics, 'mAP50(M)', 'mAP50(B)');
  $('tsEpoch').textContent = `${st.epoch} / ${st.epochs}`;
  $('tsMap').textContent = m5095 !== undefined ? Number(m5095).toFixed(4) : '—';
  $('tsBest').textContent = st.bestFitness
    ? `${Number(st.bestFitness).toFixed(4)}` : '—';
  $('tsEta').textContent = running && st.eta ? fmtSec(st.eta) : (st.elapsed ? fmtSec(st.elapsed) : '—');

  const ep = st.epochs ? Math.min(100, st.epoch / st.epochs * 100) : 0;
  $('trBarEpoch').style.width = ep.toFixed(1) + '%';
  $('trEpochPct').textContent = ep.toFixed(1) + '%';
  $('trEpochText').textContent = st.epochs
    ? `epoch ${st.epoch}/${st.epochs}` + (st.epochSec ? ` · ${st.epochSec}s/epoch` : '') : '—';

  const bp = st.batches ? Math.min(100, st.batch / st.batches * 100) : 0;
  $('trBarBatch').style.width = bp.toFixed(1) + '%';
  $('trBatchPct').textContent = bp.toFixed(1) + '%';
  const loss = Object.entries(st.losses || {})
    .map(([k, v]) => `${k} ${Number(v).toFixed(3)}`).join(' · ');
  $('trBatchText').textContent = st.batches
    ? `batch ${st.batch}/${st.batches}` + (loss ? ` · ${loss}` : '') : '—';

  drawTrainChart(st.history || []);

  const rows = (st.history || []).slice(-12).reverse();
  $('trTable').innerHTML = rows.length ? rows.map((h) => {
    const l = Object.entries(h).filter(([k]) => k.endsWith('loss') || ['box', 'seg', 'cls', 'dfl'].includes(k))
      .map(([k, v]) => `${k} ${Number(v).toFixed(3)}`).join(' ');
    const f = (v) => (v === undefined ? '—' : Number(v).toFixed(4));
    return `<tr><td>${h.epoch}</td><td>${f(pick(h, 'mAP50(M)', 'mAP50(B)'))}</td>`
      + `<td><b>${f(pick(h, 'mAP50-95(M)', 'mAP50-95(B)'))}</b></td>`
      + `<td>${f(h.fitness)}</td><td class="muted">${l || '—'}</td></tr>`;
  }).join('') : '<tr><td colspan="5" class="muted center">尚未開始</td></tr>';

  const paths = [];
  const c = st.cfg || {};
  if (c.epochs) {
    paths.push(`本次設定：${c.epochs} epochs · imgsz ${c.imgsz} · batch ${c.batch}`
      + ` · device ${c.device} · workers ${c.workers} · lr0 ${c.lr0}`);
    paths.push(`資料：<code>${c.data}</code>`);
    paths.push(`起始權重：<code>${c.model}</code>`);
  }
  if (st.saveDir) paths.push(`結果目錄：<code>${st.saveDir}</code>`);
  if (st.best) paths.push(`best：<code>${st.best}</code>`);
  if (st.exported) paths.push(`匯出：<code>${st.exported}</code>`);
  (st.copied || []).forEach((c) => paths.push(`已複製：<code>${c}</code>`));
  if (st.bestEpoch) paths.push(`最佳出現在 epoch ${st.bestEpoch}`);
  $('trPaths').innerHTML = paths.join('<br>') || '—';

  const log = $('trLog');
  if (st.log && st.log.length) {
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
    log.textContent += (log.textContent ? '\n' : '') + st.log.join('\n');
    if (atBottom) log.scrollTop = log.scrollHeight;
  }
  if (typeof st.logNext === 'number') TRAIN_LOG_NEXT = st.logNext;
}

let LAST_HISTORY = [];
function drawTrainChart(hist) {
  LAST_HISTORY = hist || [];
  const cv = $('trChart');
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 400, h = cv.clientHeight || 150;
  cv.width = Math.round(w * dpr);
  cv.height = Math.round(h * dpr);
  const c = cv.getContext('2d');
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.clearRect(0, 0, w, h);

  const pad = { l: 34, r: 8, t: 10, b: 18 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;

  // fitness 是加權和，分割任務常常大於 1，座標軸要跟著資料放大
  let ymax = 1;
  hist.forEach((r) => {
    [pick(r, 'mAP50-95(M)', 'mAP50-95(B)'), pick(r, 'mAP50(M)', 'mAP50(B)'), r.fitness]
      .forEach((v) => { if (typeof v === 'number' && isFinite(v)) ymax = Math.max(ymax, v); });
  });
  ymax = Math.ceil(ymax * 4) / 4;

  c.strokeStyle = cssVar('--line', '#e8eaf0');
  c.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + ih * i / 4;
    c.beginPath(); c.moveTo(pad.l, y); c.lineTo(pad.l + iw, y); c.stroke();
    c.fillStyle = cssVar('--muted', '#8b93a7');
    c.font = '10px Inter,system-ui,sans-serif';
    c.fillText((ymax * (1 - i / 4)).toFixed(2), 4, y + 3);
  }
  if (!hist.length) {
    c.fillStyle = cssVar('--muted', '#8b93a7');
    c.font = '12px Inter,system-ui,sans-serif';
    c.fillText('等待第一個 epoch 的驗證結果…', pad.l + 10, pad.t + ih / 2);
    return;
  }

  const n = Math.max(2, hist.length);
  const series = [
    ['#6366f1', (r) => pick(r, 'mAP50-95(M)', 'mAP50-95(B)')],
    ['#10b981', (r) => pick(r, 'mAP50(M)', 'mAP50(B)')],
    ['#f59e0b', (r) => r.fitness],
  ];
  series.forEach(([col, get]) => {
    c.beginPath();
    let started = false;
    hist.forEach((r, i) => {
      const v = get(r);
      if (v === undefined || v === null || isNaN(v)) return;
      const x = pad.l + iw * (hist.length === 1 ? 0.5 : i / (n - 1));
      const y = pad.t + ih * (1 - Math.min(1, Math.max(0, Number(v) / ymax)));
      if (started) c.lineTo(x, y); else { c.moveTo(x, y); started = true; }
    });
    c.strokeStyle = col; c.lineWidth = 2; c.stroke();
  });

  c.font = '10px Inter,system-ui,sans-serif';
  [['mAP50-95', '#6366f1'], ['mAP50', '#10b981'], ['fitness', '#f59e0b']]
    .forEach(([label, col], i) => {
      const x = pad.l + 6 + i * 74;
      c.fillStyle = col;
      c.fillRect(x, pad.t + 2, 10, 3);
      c.fillStyle = cssVar('--text-2', '#4b5563');
      c.fillText(label, x + 14, pad.t + 6);
    });
  c.fillStyle = cssVar('--muted', '#8b93a7');
  c.fillText(`epoch ${hist[hist.length - 1].epoch}`, pad.l + iw - 56, h - 5);
}

/* ══════════ train / val 比例 ══════════ */
function updateRatioLabel() {
  const r = Number($('ratio').value);
  $('ratioLabel').textContent = `train ${r}% / val ${100 - r}%`;
}

async function doSplit(dryRun) {
  const body = {
    trainRatio: Number($('ratio').value) / 100,
    seed: Number($('splitSeed').value) || 0,
    shuffle: $('splitShuffle').checked,
    includeTest: $('splitTest').checked,
    dryRun,
  };
  if (!dryRun) {
    const pct = Math.round(body.trainRatio * 100);
    if (!confirm(`即將依 train ${pct}% / val ${100 - pct}% 重新分配本地端檔案`
      + '（影像與對應 txt 會被搬移）。\n確定執行？')) return;
    if (!(await confirmDirty())) return;
  }
  try {
    const r = await post('/api/split', body);
    const lines = [
      `${dryRun ? '【預覽】' : '【已套用】'} 共 ${r.total} 張 → train ${r.train}、val ${r.val}`,
      `需搬移 ${r.moved} 個檔案`,
    ];
    if (r.conflictCount) lines.push(`衝突 ${r.conflictCount} 筆：<br>` + r.conflicts.join('<br>'));
    $('splitResult').innerHTML = lines.join('<br>');
    if (!dryRun) {
      toast(`已重新分配，搬移 ${r.moved} 個檔案`, 'ok');
      S.gen++;                     // 檔案在 split 間搬移過 → 影像 URL 換版本
      resetImage();
      S.page = 0;
      await loadList();
      loadStats();
    }
  } catch (e) { toast(e.message, 'err'); }
}

/* ══════════ 統計 ══════════ */
async function loadStats() {
  try {
    const st = await api('/api/stats');
    const splits = Object.entries(st);
    const totalImg = splits.reduce((a, [, v]) => a + v.images, 0);
    const totalObj = splits.reduce((a, [, v]) => a + v.objects, 0);
    const labeled = splits.reduce((a, [, v]) => a + v.labeled, 0);
    const tr = st.train ? st.train.images : 0;

    const tiles = [
      ['i-blue', '影像總數', totalImg,
        '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/>'],
      ['i-violet', '物件總數', totalObj,
        '<path d="M12 2 2 7l10 5 10-5-10-5Z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>'],
      ['i-green', '已標記影像', labeled,
        '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/>'],
      ['i-amber', 'train 佔比', totalImg ? Math.round(tr / totalImg * 100) + '%' : '—',
        '<path d="M21.2 15A6.7 6.7 0 0 1 9 12.5"/><path d="M12 3v9l6 3"/><circle cx="12" cy="12" r="10"/>'],
    ];
    $('statTiles').innerHTML = tiles.map(([cls, label, val, svg]) => `
      <div class="stat">
        <div class="stat-icon ${cls}"><svg viewBox="0 0 24 24">${svg}</svg></div>
        <div><div class="stat-label">${label}</div><div class="stat-value">${val}</div></div>
      </div>`).join('');

    $('statsTable').innerHTML = splits.map(([sp, v]) => {
      const per = Object.entries(v.perClass)
        .sort((a, b) => a[0] - b[0])
        .map(([c, n]) => `<span class="badge">${className(Number(c))} ${n}</span>`)
        .join(' ') || '<span class="muted">—</span>';
      return `<tr><td><b>${sp}</b></td><td>${v.images}</td><td>${v.labeled}</td>`
        + `<td>${v.objects}</td><td>${per}</td></tr>`;
    }).join('') || '<tr><td colspan="5" class="muted center">沒有資料</td></tr>';
  } catch (e) {
    $('statsTable').innerHTML = `<tr><td colspan="5" class="muted center">${e.message}</td></tr>`;
  }
}

/* ══════════ 說明頁：可用的連線網址 ══════════ */
async function loadLanUrls() {
  const box = $('lanUrls');
  if (!box || box.dataset.loaded) return;
  try {
    const d = await api('/api/net');
    const port = d.port || location.port || 80;
    const urls = (d.addresses || []).map((ip) => `http://${ip}:${port}/`);
    box.innerHTML = urls.length
      ? urls.map((u) => `<a href="${u}">${u}</a>`).join('<br>')
        + (d.lan ? '' : '<br><span class="muted">（伺服器目前只監聽本機，'
          + '手機要連請改用 <code>--lan</code> 啟動）</span>')
      : '<span class="muted">找不到區域網路位址</span>';
    box.dataset.loaded = '1';
  } catch (e) {
    box.textContent = '無法取得（' + e.message + '）';
  }
}

/* ══════════ 目錄瀏覽器 ══════════ */
let browseTarget = 'root';

function openBrowse(target, startPath, title, hint) {
  browseTarget = target;
  $('browseTitle').textContent = title;
  $('browseHint').innerHTML = hint;
  $('browseDlg').classList.remove('d-none');
  browse(startPath);
}

async function browse(path) {
  try {
    const d = await api('/api/browse?path=' + enc(path || ''));
    $('browsePath').value = d.path;
    const box = $('browseList');
    box.innerHTML = '';
    const add = (label, target) => {
      const row = document.createElement('div');
      row.textContent = label;
      row.onclick = () => browse(target);
      box.appendChild(row);
    };
    if (d.parent !== null) add('📁 ..', d.parent);
    d.dirs.forEach((it) => add('📁 ' + it.name, it.path));
  } catch (e) { toast(e.message, 'err'); }
}

/* ══════════ 鍵盤 ══════════ */
function isTyping(e) {
  const t = e.target;
  return t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA');
}

window.addEventListener('keydown', (e) => {
  if (e.code === 'Space' && !isTyping(e)) { S.space = true; e.preventDefault(); }

  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveLabel(false); return; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); return; }
  if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
  if (S.page_ !== 'annotate') return;

  const k = e.key;
  if (k === 'Escape') { if (S.draft) { S.draft = null; setMode('select'); draw(); } return; }
  if (k === 'Enter') { if (S.mode === 'draw') finishDraft(); return; }
  if (k === 'Delete' || k === 'Backspace') { delShape(S.sel); return; }
  if (k === 'n' || k === 'N') { setMode('draw'); return; }
  if (k === 'v' || k === 'V') { setMode('select'); return; }
  if (k === 'o' || k === 'O') { optimizeSelected(); return; }
  if (k === 'f' || k === 'F') { fitView(); return; }
  if (k === 'g' || k === 'G') { S.zoom = 1; fitCenter(); return; }
  if (k === 'ArrowRight' || k === 'd' || k === 'D') { e.preventDefault(); step(1); return; }
  if (k === 'ArrowLeft' || k === 'a' || k === 'A') { e.preventDefault(); step(-1); return; }
  if (k >= '0' && k <= '9') {
    const c = Number(k);
    if (S.sel >= 0) { pushHist(); S.shapes[S.sel].cls = c; markDirty(); renderShapes(); draw(); }
    if (c < S.classes.length) { S.curClass = c; renderQuickClasses(); }
  }
});
window.addEventListener('keyup', (e) => { if (e.code === 'Space') S.space = false; });

async function step(dir) {
  if (!S.items.length) return;
  const i = S.items.findIndex((x) => x.name === S.cur);
  const n = i + dir;
  if (n >= 0 && n < S.items.length) { await openImage(S.items[n].name); return; }
  const pages = Math.ceil(S.total / S.pageSize);
  if (dir > 0 && S.page < pages - 1) {
    if (!(await confirmDirty())) return;
    S.page++; await loadList();
    if (S.items[0]) await openImage(S.items[0].name);
  } else if (dir < 0 && S.page > 0) {
    if (!(await confirmDirty())) return;
    S.page--; await loadList();
    const last = S.items[S.items.length - 1];
    if (last) await openImage(last.name);
  }
}

/* ══════════ 綁定 ══════════ */
function bind() {
  document.querySelectorAll('.nav-item').forEach((b) => {
    b.onclick = () => switchPage(b.dataset.page);
  });

  // 主題
  $('btnTheme').onclick = () => applyTheme(currentTheme() === 'dark' ? 'light' : 'dark');
  // 使用者沒手動選過時，跟著系統設定走
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  const onScheme = (e) => {
    let saved = null;
    try { saved = localStorage.getItem('ys-theme'); } catch (err) { /* 忽略 */ }
    if (saved !== 'light' && saved !== 'dark') {
      document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
      draw();
    }
  };
  if (mq.addEventListener) mq.addEventListener('change', onScheme);

  // 行動版選單
  $('btnNav').onclick = () => setNav(!document.body.classList.contains('nav-open'));
  $('btnCloseNav').onclick = () => setNav(false);
  $('navScrim').onclick = () => setNav(false);
  $('btnTopTools').onclick = () => setTopTools(!$('topTools').classList.contains('open'));

  // 說明頁的流程圖與按鈕可直接跳頁
  document.querySelectorAll('[data-goto]').forEach((el) => {
    const target = el.dataset.goto;
    if (!target) return;
    el.addEventListener('click', () => switchPage(target));
  });

  $('btnApplyRoot').onclick = () => changeRoot($('rootPath').value.trim());
  $('rootPath').onkeydown = (e) => { if (e.key === 'Enter') changeRoot($('rootPath').value.trim()); };
  $('btnBrowse').onclick = () => openBrowse('root', $('rootPath').value.trim(),
    '選擇訓練資料夾', '需含 <code>images/</code> 或 <code>dataset/images/</code>');

  $('browseGo').onclick = () => browse($('browsePath').value.trim());
  $('browsePath').onkeydown = (e) => { if (e.key === 'Enter') browse($('browsePath').value.trim()); };
  $('browseCancel').onclick = () => $('browseDlg').classList.add('d-none');
  $('browsePick').onclick = () => {
    const p = $('browsePath').value;
    $('browseDlg').classList.add('d-none');
    if (browseTarget === 'root') { $('rootPath').value = p; changeRoot(p); }
    else if (browseTarget === 'videoOut') $('vidOut').value = p;
    else if (browseTarget === 'videoDir') { $('vidDir').value = p; scanVideos(); }
  };

  $('btnHelp').onclick = () => $('helpDlg').classList.remove('d-none');
  $('helpClose').onclick = () => $('helpDlg').classList.add('d-none');
  $('btnSave').onclick = () => saveLabel(false);

  let searchTimer = null;
  $('search').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { S.page = 0; loadList(); }, 250); };
  $('filterState').onchange = () => { S.page = 0; loadList(); };
  $('filterClass').onchange = () => { S.page = 0; loadList(); };
  $('pageSize').onchange = () => { S.pageSize = Number($('pageSize').value); S.page = 0; loadList(); };
  $('pagePrev').onclick = () => { if (S.page > 0) { S.page--; loadList(); } };
  $('pageNext').onclick = () => { if ((S.page + 1) * S.pageSize < S.total) { S.page++; loadList(); } };

  $('toolSelect').onclick = () => setMode('select');
  $('toolDraw').onclick = () => setMode('draw');
  $('btnOptimize').onclick = optimizeSelected;
  $('btnOptimizeSel').onclick = optimizeSelected;
  $('btnOptimizeAll').onclick = optimizeAll;
  $('btnFit').onclick = () => { S.userView = false; fitView(); };
  $('btn100').onclick = () => { S.userView = true; S.zoom = 1; fitCenter(); };
  $('btnUndo').onclick = undo;
  $('showFill').onchange = draw;
  $('showIdx').onchange = draw;

  $('btnDelShape').onclick = () => delShape(S.sel);
  $('btnClearShapes').onclick = () => {
    if (!S.shapes.length || !confirm('清空此影像的所有標記？')) return;
    pushHist(); S.shapes = []; S.sel = -1; markDirty(); renderShapes(); draw();
  };

  $('btnAddClass').onclick = () => {
    S.classes.push(`class${S.classes.length}`);
    renderClasses(); renderQuickClasses(); renderClassFilter();
  };
  $('btnSaveClasses').onclick = async () => {
    try {
      const r = await post('/api/classes', { names: S.classes });
      S.classes = r.classes;
      renderClasses(); renderQuickClasses(); renderClassFilter(); renderShapes(); draw();
      toast('已寫入 ' + r.yaml, 'ok');
    } catch (e) { toast(e.message, 'err'); }
  };

  $('ratio').oninput = updateRatioLabel;
  $('btnPreviewSplit').onclick = () => doSplit(true);
  $('btnApplySplit').onclick = () => doSplit(false);
  $('btnStats').onclick = loadStats;

  // 影片頁
  $('btnTrainStart').onclick = startTrain;
  $('btnTrainStop').onclick = stopTrain;
  $('btnTrainReset').onclick = () => {
    if (TRAIN_DEFAULTS) { fillTrainForm(TRAIN_DEFAULTS); toast('已回復預設參數', 'ok'); }
  };

  $('pvOn').onchange = previewSync;
  $('pvFps').onchange = () => { previewStop(); previewSync(); };
  $('btnScanVideos').onclick = scanVideos;
  $('btnVideoStart').onclick = startVideoJob;
  $('btnVideoStop').onclick = stopVideoJob;
  $('btnPickOut').onclick = () => openBrowse('videoOut', $('vidOut').value.trim(),
    '選擇輸出資料夾', '會在此資料夾下建立 <code>dataset/images|labels</code>');
  $('btnOpenAsDataset').onclick = () => {
    const dir = $('btnOpenAsDataset').dataset.dir;
    if (!dir) return;
    $('rootPath').value = dir;
    changeRoot(dir);
    switchPage('annotate');
  };

  // 版面尺寸會在字型／清單載入後才穩定，用 ResizeObserver 才不會量到過渡中的值
  if (window.ResizeObserver) {
    new ResizeObserver(() => { if (S.page_ === 'annotate') resizeCanvas(); }).observe($('editorWrap'));
  }
  window.addEventListener('resize', () => { if (S.page_ === 'annotate') resizeCanvas(); });
  window.addEventListener('beforeunload', (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ''; } });
}

/* ══════════ 啟動 ══════════ */
(async function init() {
  bind();
  updateRatioLabel();
  setMode('select');
  applyThemeIcons();
  switchPage(location.hash.slice(1) || 'annotate');
  window.addEventListener('hashchange', () => switchPage(location.hash.slice(1)));
  resizeCanvas();
  loadVideoDefaults();
  pollVideo(false);
  loadTrainDefaults(false);
  pollTrain(false);
  try {
    await loadConfig();
    await loadList();
    loadStats();
    if (S.items.length) openImage(S.items[0].name);
  } catch (e) {
    toast('讀取失敗：' + e.message, 'err');
  }
})();
