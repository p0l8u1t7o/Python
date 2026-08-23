/** 共用 UI 小工具：格式化、DOM 建構、載入狀態、Toast。 */

export const pct = (v, nd = 1) =>
  (v === null || v === undefined || Number.isNaN(v)) ? '—' : `${(v * 100).toFixed(nd)}%`;

export const num = (v, nd = 4) => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e6)) return v.toExponential(2);
  return v.toFixed(nd);
};

export const money = (v) => (v === null || v === undefined) ? '—'
  : new Intl.NumberFormat('zh-TW', { style: 'currency', currency: 'TWD',
      maximumFractionDigits: 0 }).format(v);

export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function card(title, subtitle, ...body) {
  return h('section', { class: 'card' },
    title ? h('header', { class: 'card-head' },
      h('h3', {}, title),
      subtitle ? h('p', { class: 'muted' }, subtitle) : null) : null,
    h('div', { class: 'card-body' }, ...body));
}

export function stat(label, value, hint, tone) {
  return h('div', { class: `stat ${tone ? 'tone-' + tone : ''}` },
    h('div', { class: 'stat-label' }, label),
    h('div', { class: 'stat-value' }, value),
    hint ? h('div', { class: 'stat-hint' }, hint) : null);
}

export function table(headers, rows, opts = {}) {
  const wrap = h('div', { class: 'table-wrap' });
  const t = h('table', { class: 'data-table' });
  t.append(h('thead', {}, h('tr', {}, ...headers.map((x) =>
    h('th', { class: typeof x === 'object' && x.align ? 'ta-' + x.align : null },
      typeof x === 'object' ? x.label : x)))));
  const tb = h('tbody');
  for (const r of rows) {
    const tr = h('tr', { class: r.__class || null });
    for (const cell of (r.cells || r)) {
      tr.append(h('td', {
        class: (typeof cell === 'object' && cell !== null && cell.align) ? 'ta-' + cell.align : null,
        title: (typeof cell === 'object' && cell !== null && cell.title) || null,
      }, (typeof cell === 'object' && cell !== null)
          ? (cell.node || cell.text || '') : cell));
    }
    if (r.__click) tr.addEventListener('click', r.__click);
    if (r.__click) tr.classList.add('clickable');
    tb.append(tr);
  }
  t.append(tb);
  wrap.append(t);
  if (opts.empty && rows.length === 0) wrap.append(h('p', { class: 'muted pad' }, opts.empty));
  return wrap;
}

export function badge(text, tone) {
  return h('span', { class: `badge tone-${tone || 'neutral'}` }, text);
}

export function notice(kind, title, ...body) {
  return h('div', { class: `notice notice-${kind}` },
    h('strong', {}, title),
    ...body.map((b) => (b instanceof Node ? b : h('p', {}, b))));
}

export function spinner(text) {
  return h('div', { class: 'loading' }, h('div', { class: 'spin' }), h('span', {}, text || '計算中…'));
}

export function chartBox(title, note) {
  const host = h('div', { class: 'chart-host' });
  const box = h('div', { class: 'chart-box' },
    title ? h('div', { class: 'chart-title' }, title) : null,
    host,
    note ? h('p', { class: 'chart-note' }, note) : null);
  box.host = host;
  return box;
}

let toastTimer = null;
export function toast(msg, kind = 'info') {
  let el = document.getElementById('toast');
  if (!el) {
    el = h('div', { id: 'toast' });
    document.body.append(el);
  }
  el.className = `toast toast-${kind} show`;
  el.textContent = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 4200);
}

/** 極簡 Markdown → HTML（助理回覆用）。只支援必要語法，並逸出 HTML。 */
export function mdToHtml(src) {
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const lines = esc(src || '').split('\n');
  const out = [];
  let inTable = false;
  const inline = (s) => s
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^_])_([^_]+)_/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');

  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    if (/^\s*\|.*\|\s*$/.test(ln)) {
      const cells = ln.trim().slice(1, -1).split('|').map((c) => c.trim());
      if (/^[\s|:-]+$/.test(ln)) continue;
      if (!inTable) { out.push('<table class="md-table"><tr>' + cells.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr>'); inTable = true; }
      else out.push('<tr>' + cells.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>');
      continue;
    }
    if (inTable) { out.push('</table>'); inTable = false; }
    if (/^\s*-\s+/.test(ln)) out.push(`<li>${inline(ln.replace(/^\s*-\s+/, ''))}</li>`);
    else if (ln.trim() === '') out.push('');
    else out.push(`<p>${inline(ln)}</p>`);
  }
  if (inTable) out.push('</table>');
  return out.join('\n').replace(/(<li>[\s\S]*?<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`);
}

export const toneForK = (k) => (k < 0.15 ? 'good' : k < 0.4 ? 'ok' : k < 0.75 ? 'warn' : 'bad');
export const toneForSeverity = (s) => ({ high: 'bad', medium: 'warn', low: 'neutral' }[s] || 'neutral');
