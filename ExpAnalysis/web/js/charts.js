/**
 * 極簡 SVG 圖表模組 — 零外部相依。
 *
 * 為什麼自己寫而不用 Chart.js / ECharts：
 *   本工具的部署情境是「離線的產線辦公室機器」，CDN 拉不到、也不見得
 *   允許安裝 node 生態的一堆套件。把圖表縮到必要的六種型別、用純 SVG
 *   實作，總共不到 600 行，反而比引入一個 200KB 的函式庫更好維護，
 *   而且 SVG 可以直接右鍵存成向量圖貼進報告。
 *
 * 共同約定：
 *   每個繪圖函式接受 (host: HTMLElement, spec: Object)，會清空 host 後重繪。
 *   所有顏色都走 CSS 變數，明暗主題自動切換，不在 JS 裡寫死色碼。
 */

const NS = 'http://www.w3.org/2000/svg';

/** 讀取 CSS 變數，讓圖表跟著主題走。 */
function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export const PALETTE = () => [
  cssVar('--c1', '#4c8dff'), cssVar('--c2', '#f2994a'),
  cssVar('--c3', '#27ae60'), cssVar('--c4', '#bb6bd9'),
  cssVar('--c5', '#eb5757'), cssVar('--c6', '#56ccf2'),
];

function el(tag, attrs = {}, text) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    node.setAttribute(k, String(v));
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

function fmt(v, digits = 3) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(1);
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1);
  return v.toFixed(digits);
}

/** 產生「好看的」刻度值。 */
function niceTicks(min, max, count = 5) {
  if (!isFinite(min) || !isFinite(max) || min === max) return [min];
  const span = max - min;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const out = [];
  for (let t = Math.ceil(min / step) * step; t <= max + step * 1e-9; t += step) out.push(t);
  return out;
}

function logTicks(min, max) {
  const lo = Math.floor(Math.log10(min));
  const hi = Math.ceil(Math.log10(max));
  const out = [];
  for (let e = lo; e <= hi; e++) {
    const v = Math.pow(10, e);
    if (v >= min * 0.99 && v <= max * 1.01) out.push(v);
  }
  return out.length >= 2 ? out : [min, max];
}

/** 建立座標系統。回傳 { svg, g, sx, sy, W, H, pad } */
function frame(host, spec) {
  host.innerHTML = '';
  // 繪圖時 host 常常還沒進 DOM（各 view 是先組好整棵樹再一次掛上），
  // 此時 clientWidth = 0。所以用固定的設計寬度當 viewBox，再讓 SVG 以
  // width:100% / height:auto 等比縮放填滿容器——這樣不需要等版面計算完成，
  // 也不會因為量到 0 而縮在中間留下大片空白。
  const W = spec.width || (host.clientWidth > 120 ? host.clientWidth : 900);
  const H = spec.height || 320;
  const pad = Object.assign({ t: 18, r: 18, b: 44, l: 62 }, spec.pad || {});
  const svg = el('svg', {
    viewBox: `0 0 ${W} ${H}`, width: '100%',
    class: 'chart', preserveAspectRatio: 'xMidYMid meet', role: 'img',
    'aria-label': spec.title || '圖表',
  });
  host.appendChild(svg);

  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;
  const logY = !!spec.logY;

  let [x0, x1] = spec.xDomain;
  let [y0, y1] = spec.yDomain;
  if (logY) { y0 = Math.max(y0, 1e-12); y1 = Math.max(y1, y0 * 10); }
  if (x1 === x0) x1 = x0 + 1;
  if (y1 === y0) y1 = y0 + 1;

  const sx = (v) => pad.l + ((v - x0) / (x1 - x0)) * iw;
  const sy = logY
    ? (v) => pad.t + ih - ((Math.log10(Math.max(v, y0 * 1e-3)) - Math.log10(y0)) /
             (Math.log10(y1) - Math.log10(y0))) * ih
    : (v) => pad.t + ih - ((v - y0) / (y1 - y0)) * ih;

  const grid = cssVar('--grid', '#2a3140');
  const axis = cssVar('--axis', '#8892a4');

  // 格線與刻度
  const xt = spec.xTicks || niceTicks(x0, x1, 6);
  for (const t of xt) {
    const x = sx(t);
    svg.appendChild(el('line', { x1: x, x2: x, y1: pad.t, y2: pad.t + ih, stroke: grid, 'stroke-width': 1 }));
    svg.appendChild(el('text', { x, y: pad.t + ih + 18, 'text-anchor': 'middle',
      class: 'tick' }, spec.xTickFormat ? spec.xTickFormat(t) : fmt(t)));
  }
  const yt = spec.yTicks || (logY ? logTicks(y0, y1) : niceTicks(y0, y1, 5));
  for (const t of yt) {
    const y = sy(t);
    svg.appendChild(el('line', { x1: pad.l, x2: pad.l + iw, y1: y, y2: y, stroke: grid, 'stroke-width': 1 }));
    svg.appendChild(el('text', { x: pad.l - 8, y: y + 4, 'text-anchor': 'end',
      class: 'tick' }, spec.yTickFormat ? spec.yTickFormat(t) : fmt(t)));
  }

  // 軸標題
  if (spec.xLabel) svg.appendChild(el('text', {
    x: pad.l + iw / 2, y: pad.t + ih + 34, 'text-anchor': 'middle',
    class: 'axis-label' }, spec.xLabel));
  if (spec.yLabel) svg.appendChild(el('text', {
    x: 14, y: pad.t + ih / 2, 'text-anchor': 'middle', class: 'axis-label',
    transform: `rotate(-90 14 ${pad.t + ih / 2})` }, spec.yLabel));

  svg.appendChild(el('rect', { x: pad.l, y: pad.t, width: iw, height: ih,
    fill: 'none', stroke: axis, 'stroke-width': 1 }));

  return { svg, sx, sy, W, H, pad, iw, ih, x0, x1, y0, y1 };
}

function path(points, sx, sy) {
  return points.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(2)},${sy(p[1]).toFixed(2)}`).join(' ');
}

/** 估算文字寬度。CJK 字元約為 ASCII 的兩倍寬，用同一個係數會讓中文圖例互相重疊。 */
function textWidth(s, size = 11.5) {
  let w = 0;
  for (const ch of String(s)) w += /[\u2E80-\u9FFF\uFF00-\uFFEF]/.test(ch) ? size : size * 0.55;
  return w;
}

function legend(svg, items, x, y) {
  const g = el('g', { class: 'legend' });
  let cx = x;
  for (const it of items) {
    if (it.type === 'band') {
      g.appendChild(el('rect', { x: cx, y: y - 7, width: 16, height: 10,
        fill: it.color, opacity: 0.28, rx: 2 }));
    } else if (it.type === 'dot') {
      g.appendChild(el('circle', { cx: cx + 8, cy: y - 2, r: 4, fill: it.color }));
    } else {
      g.appendChild(el('line', { x1: cx, x2: cx + 16, y1: y - 2, y2: y - 2,
        stroke: it.color, 'stroke-width': 2.4,
        'stroke-dasharray': it.dash || null }));
    }
    g.appendChild(el('text', { x: cx + 22, y: y + 2, class: 'legend-text' }, it.label));
    cx += 34 + textWidth(it.label);
  }
  svg.appendChild(g);
}

function tooltipLayer(host, svg) {
  const tip = document.createElement('div');
  tip.className = 'chart-tip';
  tip.style.display = 'none';
  host.style.position = 'relative';
  host.appendChild(tip);
  return {
    show(clientX, clientY, html) {
      const r = host.getBoundingClientRect();
      tip.innerHTML = html;
      tip.style.display = 'block';
      const left = clientX - r.left;
      tip.style.left = `${Math.min(Math.max(left + 12, 4), r.width - tip.offsetWidth - 4)}px`;
      tip.style.top = `${clientY - r.top - tip.offsetHeight - 12}px`;
    },
    hide() { tip.style.display = 'none'; },
  };
}

/* ─────────────────────────────────────────────────────────────
 *  1. 濃度分布圖：模型曲線 + 實測點 + 設限標記 + 6N 視窗
 * ───────────────────────────────────────────────────────────── */
export function profileChart(host, spec) {
  const series = spec.series || [];
  const scatters = spec.scatter || [];
  let ymin = Infinity, ymax = -Infinity;
  for (const s of series) for (const p of s.points) {
    if (p[1] > 0) { ymin = Math.min(ymin, p[1]); ymax = Math.max(ymax, p[1]); }
  }
  for (const s of scatters) for (const p of s.points) {
    if (p[1] > 0) { ymin = Math.min(ymin, p[1]); ymax = Math.max(ymax, p[1]); }
  }
  if (spec.threshold) { ymin = Math.min(ymin, spec.threshold); ymax = Math.max(ymax, spec.threshold); }
  if (!isFinite(ymin)) { ymin = 1e-4; ymax = 1; }
  ymin = Math.pow(10, Math.floor(Math.log10(ymin)));
  ymax = Math.pow(10, Math.ceil(Math.log10(ymax)));

  const f = frame(host, Object.assign({}, spec, {
    pad: Object.assign({ b: 68 }, spec.pad || {}),
    xDomain: [0, 1], yDomain: [ymin, ymax], logY: true,
    xLabel: spec.xLabel || '歸一化位置 x/L（0 = 頭端）',
    yLabel: spec.yLabel || '雜質濃度 (ppm)',
    xTicks: [0, 0.2, 0.4, 0.6, 0.8, 1.0],
    yTickFormat: (v) => (v >= 1 ? String(v) : v.toExponential(0).replace('e-', 'e-')),
  }));
  const { svg, sx, sy, pad, iw, ih } = f;

  // 高純區 / 濃縮區底色
  if (spec.window) {
    const w = spec.window;
    if (w.tail_cut_frac > w.head_cut_frac) {
      svg.appendChild(el('rect', {
        x: sx(w.head_cut_frac), y: pad.t,
        width: Math.max(sx(w.tail_cut_frac) - sx(w.head_cut_frac), 0), height: ih,
        fill: cssVar('--good', '#27ae60'), opacity: 0.10 }));
      svg.appendChild(el('text', {
        x: (sx(w.head_cut_frac) + sx(w.tail_cut_frac)) / 2, y: pad.t + 14,
        'text-anchor': 'middle', class: 'zone-label' },
        `6N 高純區 ${(w.yield_frac * 100).toFixed(1)}%`));
    }
    if (w.concentrate_start_frac < 1) {
      svg.appendChild(el('rect', {
        x: sx(w.concentrate_start_frac), y: pad.t,
        width: Math.max(pad.l + iw - sx(w.concentrate_start_frac), 0), height: ih,
        fill: cssVar('--bad', '#eb5757'), opacity: 0.10 }));
      svg.appendChild(el('text', {
        x: (sx(w.concentrate_start_frac) + pad.l + iw) / 2, y: pad.t + 14,
        'text-anchor': 'middle', class: 'zone-label' }, '雜質濃縮區'));
    }
  }

  if (spec.threshold) {
    svg.appendChild(el('line', { x1: pad.l, x2: pad.l + iw,
      y1: sy(spec.threshold), y2: sy(spec.threshold),
      stroke: cssVar('--warn', '#f2c94c'), 'stroke-width': 1.6, 'stroke-dasharray': '6 4' }));
    svg.appendChild(el('text', { x: pad.l + iw - 4, y: sy(spec.threshold) - 6,
      'text-anchor': 'end', class: 'tick' }, `6N 門檻 ${spec.threshold} ppm`));
  }

  const colors = PALETTE();
  series.forEach((s, i) => {
    const c = s.color || colors[i % colors.length];
    svg.appendChild(el('path', { d: path(s.points, sx, sy), fill: 'none', stroke: c,
      'stroke-width': s.width || 2.2, 'stroke-dasharray': s.dash || null,
      opacity: s.opacity || 1 }));
  });

  const tip = tooltipLayer(host, svg);
  scatters.forEach((s, i) => {
    const c = s.color || colors[i % colors.length];
    s.points.forEach((p, j) => {
      const cx = sx(p[0]); const cy = sy(Math.max(p[1], ymin));
      const censored = s.censored && s.censored[j];
      const node = censored
        ? el('path', { d: `M${cx - 5},${cy - 5} L${cx + 5},${cy - 5} L${cx},${cy + 4} Z`,
            fill: 'none', stroke: c, 'stroke-width': 1.8 })
        : el('circle', { cx, cy, r: 4, fill: c, stroke: cssVar('--bg', '#0f1319'),
            'stroke-width': 1 });
      node.setAttribute('class', 'pt');
      node.addEventListener('mousemove', (e) => tip.show(e.clientX, e.clientY,
        `<b>${s.label}</b><br>x/L = ${p[0].toFixed(3)}<br>` +
        (censored ? `&lt; ${fmt(p[1], 4)} ppm（低於檢測極限）` : `${fmt(p[1], 4)} ppm`)));
      node.addEventListener('mouseleave', () => tip.hide());
      svg.appendChild(node);
    });
  });

  const items = series.filter((s) => s.label).map((s, i) => ({
    label: s.label, color: s.color || colors[i % colors.length], dash: s.dash }));
  scatters.filter((s) => s.label).forEach((s, i) => items.push({
    type: 'dot', label: `${s.label}（實測）`, color: s.color || colors[i % colors.length] }));
  if (items.length) legend(svg, items, pad.l + 6, f.H - 10);
  return svg;
}

/* ─────────────────────────────────────────────────────────────
 *  2. 帶不確定區間的曲線（GP 灰帶圖）
 * ───────────────────────────────────────────────────────────── */
export function bandChart(host, spec) {
  const { x, y, lo, hi } = spec;
  const pts = spec.points || [];
  let ymin = Math.min(...lo, ...(pts.map((p) => p.lo ?? p.y)));
  let ymax = Math.max(...hi, ...(pts.map((p) => p.hi ?? p.y)));
  const padY = (ymax - ymin) * 0.12 || 0.05;
  ymin -= padY; ymax += padY;
  if (spec.clampY) { ymin = Math.max(ymin, spec.clampY[0]); ymax = Math.min(ymax, spec.clampY[1]); }

  const f = frame(host, Object.assign({}, spec, {
    pad: Object.assign({ b: 68 }, spec.pad || {}),
    xDomain: [Math.min(...x), Math.max(...x)], yDomain: [ymin, ymax] }));
  const { svg, sx, sy, pad, ih } = f;
  const c = spec.color || PALETTE()[0];

  // 觀測範圍以外的區域加上斜線底紋，讓「這裡是外插」一眼看得出來
  if (spec.observedRange) {
    const [a, b] = spec.observedRange;
    const defs = el('defs');
    const pat = el('pattern', { id: 'hatch', width: 6, height: 6,
      patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' });
    pat.appendChild(el('line', { x1: 0, y1: 0, x2: 0, y2: 6,
      stroke: cssVar('--axis', '#8892a4'), 'stroke-width': 1, opacity: 0.35 }));
    defs.appendChild(pat); svg.appendChild(defs);
    if (sx(a) > pad.l) svg.appendChild(el('rect', { x: pad.l, y: pad.t,
      width: sx(a) - pad.l, height: ih, fill: 'url(#hatch)' }));
    if (sx(b) < pad.l + f.iw) svg.appendChild(el('rect', { x: sx(b), y: pad.t,
      width: pad.l + f.iw - sx(b), height: ih, fill: 'url(#hatch)' }));
  }

  const band = x.map((v, i) => [v, hi[i]]).concat(
    x.map((v, i) => [v, lo[i]]).reverse());
  svg.appendChild(el('path', { d: path(band, sx, sy) + ' Z', fill: c, opacity: 0.20, stroke: 'none' }));
  svg.appendChild(el('path', { d: path(x.map((v, i) => [v, y[i]]), sx, sy),
    fill: 'none', stroke: c, 'stroke-width': 2.4 }));

  if (spec.baseline) {
    svg.appendChild(el('path', { d: path(x.map((v, i) => [v, spec.baseline[i]]), sx, sy),
      fill: 'none', stroke: cssVar('--axis', '#8892a4'), 'stroke-width': 1.6,
      'stroke-dasharray': '5 4' }));
  }

  const tip = tooltipLayer(host, svg);
  for (const p of pts) {
    if (p.lo != null && p.hi != null && p.hi > p.lo) {
      svg.appendChild(el('line', { x1: sx(p.x), x2: sx(p.x), y1: sy(p.lo), y2: sy(p.hi),
        stroke: cssVar('--fg2', '#c7d0dd'), 'stroke-width': 1.4 }));
    }
    const dot = el('circle', { cx: sx(p.x), cy: sy(p.y), r: 4.5,
      fill: p.flagged ? cssVar('--bad', '#eb5757') : cssVar('--fg', '#e7edf5'),
      stroke: c, 'stroke-width': 1.6, class: 'pt' });
    dot.addEventListener('mousemove', (e) => tip.show(e.clientX, e.clientY,
      `<b>${p.label || ''}</b><br>${spec.xLabel || 'x'} = ${fmt(p.x)}<br>` +
      `${spec.yLabel || 'y'} = ${fmt(p.y, 4)}` +
      (p.lo != null ? `<br>95% CI ${fmt(p.lo, 4)} ~ ${fmt(p.hi, 4)}` : '')));
    dot.addEventListener('mouseleave', () => tip.hide());
    svg.appendChild(dot);
  }

  const items = [{ label: spec.seriesLabel || '模型預測', color: c },
                 { type: 'band', label: '95% 不確定區間', color: c }];
  if (spec.baseline) items.push({ label: 'BPS 線性基準', color: cssVar('--axis', '#8892a4'), dash: '5 4' });
  if (pts.length) items.push({ type: 'dot', label: '各批次擬合值', color: cssVar('--fg', '#e7edf5') });
  legend(svg, items, pad.l + 6, f.H - 10);
  return svg;
}

/* ─────────────────────────────────────────────────────────────
 *  3. 殘差圖
 * ───────────────────────────────────────────────────────────── */
export function residualChart(host, spec) {
  const pts = spec.points || [];
  const m = Math.max(3.2, ...pts.map((p) => Math.abs(p.y) + 0.4));
  const f = frame(host, Object.assign({ height: 200 }, spec, {
    xDomain: [0, 1], yDomain: [-m, m],
    xLabel: '歸一化位置 x/L', yLabel: '標準化殘差' }));
  const { svg, sx, sy, pad, iw } = f;

  for (const [lvl, col, op] of [[2, cssVar('--warn', '#f2c94c'), 0.10],
                                [1, cssVar('--good', '#27ae60'), 0.10]]) {
    svg.appendChild(el('rect', { x: pad.l, y: sy(lvl), width: iw,
      height: Math.abs(sy(-lvl) - sy(lvl)), fill: col, opacity: op }));
  }
  svg.appendChild(el('line', { x1: pad.l, x2: pad.l + iw, y1: sy(0), y2: sy(0),
    stroke: cssVar('--axis', '#8892a4'), 'stroke-width': 1.4 }));

  const tip = tooltipLayer(host, svg);
  const colors = PALETTE();
  pts.forEach((p) => {
    const c = p.color || colors[0];
    const node = p.censored
      ? el('rect', { x: sx(p.x) - 4, y: sy(p.y) - 4, width: 8, height: 8,
          fill: 'none', stroke: c, 'stroke-width': 1.8, transform: `rotate(45 ${sx(p.x)} ${sy(p.y)})` })
      : el('circle', { cx: sx(p.x), cy: sy(p.y), r: 4, fill: c });
    node.setAttribute('class', 'pt');
    node.addEventListener('mousemove', (e) => tip.show(e.clientX, e.clientY,
      `<b>${p.label || ''}</b><br>x/L = ${fmt(p.x)}<br>殘差 = ${fmt(p.y, 2)}` +
      (p.censored ? '<br>（設限點，顯示為期望殘差）' : '')));
    node.addEventListener('mouseleave', () => tip.hide());
    svg.appendChild(node);
  });
  return svg;
}

/* ─────────────────────────────────────────────────────────────
 *  4. 熱圖（得料率 vs 速率 × 溫度）
 * ───────────────────────────────────────────────────────────── */
export function heatmap(host, spec) {
  const { xs, ys, z } = spec;   // z[i][j] 對應 xs[i], ys[j]
  const flat = z.flat().filter((v) => isFinite(v));
  const vmin = spec.vmin ?? Math.min(...flat);
  const vmax = spec.vmax ?? Math.max(...flat);
  const f = frame(host, Object.assign({}, spec, {
    xDomain: [xs[0], xs[xs.length - 1]], yDomain: [ys[0], ys[ys.length - 1]],
    pad: { t: 18, r: 74, b: 44, l: 62 } }));
  const { svg, sx, sy, pad, iw, ih } = f;

  const cw = iw / xs.length;
  const chh = ih / ys.length;
  const tip = tooltipLayer(host, svg);
  for (let i = 0; i < xs.length; i++) {
    for (let j = 0; j < ys.length; j++) {
      const v = z[i][j];
      const t = vmax > vmin ? (v - vmin) / (vmax - vmin) : 0.5;
      const rect = el('rect', {
        x: pad.l + i * cw, y: pad.t + ih - (j + 1) * chh,
        width: cw + 0.6, height: chh + 0.6, fill: viridis(t),
        opacity: spec.inRange && spec.inRange[i] && spec.inRange[i][j] === false ? 0.38 : 1,
        class: 'cell' });
      rect.addEventListener('mousemove', (e) => tip.show(e.clientX, e.clientY,
        `速率 ${fmt(xs[i], 2)} mm/hr<br>溫度 ${fmt(ys[j], 1)} °C<br>` +
        `<b>得料率 ${(v * 100).toFixed(1)}%</b>` +
        (spec.inRange && spec.inRange[i] && spec.inRange[i][j] === false
          ? '<br><span style="color:var(--warn)">⚠ 外插區</span>' : '')));
      rect.addEventListener('mouseleave', () => tip.hide());
      svg.appendChild(rect);
    }
  }

  if (spec.marker) {
    const { x, y, label } = spec.marker;
    svg.appendChild(el('circle', { cx: sx(x), cy: sy(y), r: 7, fill: 'none',
      stroke: '#fff', 'stroke-width': 2.4 }));
    svg.appendChild(el('circle', { cx: sx(x), cy: sy(y), r: 7, fill: 'none',
      stroke: '#000', 'stroke-width': 1 }));
    if (label) svg.appendChild(el('text', { x: sx(x), y: sy(y) - 12,
      'text-anchor': 'middle', class: 'zone-label' }, label));
  }

  // 色階條
  const bx = pad.l + iw + 16;
  const defs = el('defs');
  const grad = el('linearGradient', { id: 'cbar', x1: 0, y1: 1, x2: 0, y2: 0 });
  for (let s = 0; s <= 10; s++) {
    grad.appendChild(el('stop', { offset: `${s * 10}%`, 'stop-color': viridis(s / 10) }));
  }
  defs.appendChild(grad); svg.appendChild(defs);
  svg.appendChild(el('rect', { x: bx, y: pad.t, width: 14, height: ih, fill: 'url(#cbar)' }));
  svg.appendChild(el('text', { x: bx + 18, y: pad.t + 10, class: 'tick' },
    `${(vmax * 100).toFixed(0)}%`));
  svg.appendChild(el('text', { x: bx + 18, y: pad.t + ih, class: 'tick' },
    `${(vmin * 100).toFixed(0)}%`));
  return svg;
}

/** 近似 viridis：感知均勻、色盲友善，且在灰階列印下仍可讀。 */
function viridis(t) {
  const stops = [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]];
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1);
  const i = Math.min(Math.floor(x), stops.length - 2);
  const w = x - i;
  const c = stops[i].map((v, k) => Math.round(v + (stops[i + 1][k] - v) * w));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

/* ─────────────────────────────────────────────────────────────
 *  5. 折線／階梯圖（得料率 vs pass、DOE 對比曲線）
 * ───────────────────────────────────────────────────────────── */
export function lineChart(host, spec) {
  const all = spec.series.flatMap((s) => s.points);
  const xs = all.map((p) => p[0]); const ys = all.map((p) => p[1]);
  const f = frame(host, Object.assign({}, spec, {
    pad: Object.assign({ b: 68 }, spec.pad || {}),
    xDomain: spec.xDomain || [Math.min(...xs), Math.max(...xs)],
    yDomain: spec.yDomain || [Math.min(0, ...ys), Math.max(...ys) * 1.08] }));
  const { svg, sx, sy, pad } = f;
  const colors = PALETTE();
  const tip = tooltipLayer(host, svg);

  spec.series.forEach((s, i) => {
    const c = s.color || colors[i % colors.length];
    svg.appendChild(el('path', {
      d: path(s.points, sx, sy), fill: 'none', stroke: c,
      'stroke-width': s.width || 2.4, 'stroke-dasharray': s.dash || null,
      'stroke-linejoin': 'round' }));
    if (s.markers !== false) {
      s.points.forEach((p) => {
        const dot = el('circle', { cx: sx(p[0]), cy: sy(p[1]), r: 3.6, fill: c, class: 'pt' });
        dot.addEventListener('mousemove', (e) => tip.show(e.clientX, e.clientY,
          `<b>${s.label || ''}</b><br>${spec.xLabel || 'x'} = ${fmt(p[0], 2)}<br>` +
          `${spec.yLabel || 'y'} = ${spec.percentY ? (p[1] * 100).toFixed(1) + '%' : fmt(p[1], 4)}`));
        dot.addEventListener('mouseleave', () => tip.hide());
        svg.appendChild(dot);
      });
    }
  });
  if (spec.vline != null) {
    svg.appendChild(el('line', { x1: sx(spec.vline), x2: sx(spec.vline),
      y1: pad.t, y2: pad.t + f.ih, stroke: cssVar('--warn', '#f2c94c'),
      'stroke-width': 1.8, 'stroke-dasharray': '6 4' }));
    if (spec.vlineLabel) svg.appendChild(el('text', { x: sx(spec.vline) + 6,
      y: pad.t + 14, class: 'zone-label' }, spec.vlineLabel));
  }
  legend(svg, spec.series.filter((s) => s.label).map((s, i) => ({
    label: s.label, color: s.color || colors[i % colors.length], dash: s.dash })),
    pad.l + 6, f.H - 10);
  return svg;
}

/* ─────────────────────────────────────────────────────────────
 *  6. 橫條圖（元素比較、誤差比較）
 * ───────────────────────────────────────────────────────────── */
export function barChart(host, spec) {
  const items = spec.items || [];
  const vmax = Math.max(...items.map((d) => d.value), spec.vmax || 0) * 1.15 || 1;
  const H = spec.height || Math.max(120, items.length * 34 + 50);
  const f = frame(host, Object.assign({}, spec, {
    height: H, xDomain: [0, vmax], yDomain: [0, items.length],
    yTicks: [], pad: { t: 14, r: 20, b: 40, l: spec.labelWidth || 96 } }));
  const { svg, sx, pad, ih } = f;
  const bh = ih / Math.max(items.length, 1);
  const colors = PALETTE();
  items.forEach((d, i) => {
    const y = pad.t + i * bh + bh * 0.18;
    const h = bh * 0.64;
    svg.appendChild(el('rect', { x: pad.l, y, width: Math.max(sx(d.value) - pad.l, 1),
      height: h, fill: d.color || colors[i % colors.length], rx: 3 }));
    svg.appendChild(el('text', { x: pad.l - 8, y: y + h / 2 + 4,
      'text-anchor': 'end', class: 'tick' }, d.label));
    svg.appendChild(el('text', { x: sx(d.value) + 6, y: y + h / 2 + 4,
      class: 'tick' }, d.text ?? fmt(d.value, 3)));
  });
  return svg;
}

export const chartUtils = { fmt, cssVar, viridis };
