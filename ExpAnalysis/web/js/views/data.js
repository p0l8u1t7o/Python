/** 資料管理：CSV 匯入（先稽核再寫入）、合成資料、清除。 */

import { api } from '../api.js';
import { h, card, badge, notice, table, toast, spinner, num, pct } from '../ui.js';
import { invalidate } from '../app.js';

export default async function dataview() {
  const root = h('div');
  const list = await api.listBatches();

  // ── 匯入 ────────────────────────────────────────────────
  const reportHost = h('div');
  let picked = null;
  const fileInput = h('input', {
    type: 'file', accept: '.csv,.xlsx,.xls',
    onchange: (e) => { picked = e.target.files[0] || null; reportHost.innerHTML = ''; },
  });

  root.append(card('匯入客戶批次資料',
    '長格式表格：一列 = 一個取樣點的一個元素。欄名支援中英文與常見別名，'
    + '但單位與物理一致性一律嚴格檢查——不合格會擋下並說清楚哪一列、為什麼。',
    h('div', { class: 'row' },
      fileInput,
      h('button', { class: 'ghost', onclick: () => doImport(true) }, '只稽核（不寫入）'),
      h('button', { onclick: () => doImport(false) }, '稽核並匯入'),
      h('a', { class: 'btn ghost', href: '/api/batches/template.csv',
        style: 'text-decoration:none' }, '下載 CSV 範本')),
    h('p', { class: 'muted', style: 'margin-top:10px' },
      '低於檢測極限的寫法三種都支援：value_ppm 寫成 "<0.05"、'
      + '或填數值並把 censored 設為 1、或 value_ppm ≤ lod_ppm。'
      + '詳細欄位定義見 '),
    h('p', {}, h('a', { href: '/docs/03-data-spec.html', target: '_blank' },
      '資料規格書 →')),
    reportHost));

  async function doImport(dryRun) {
    if (!picked) { toast('請先選擇檔案', 'error'); return; }
    reportHost.innerHTML = '';
    reportHost.append(spinner(dryRun ? '稽核中…' : '匯入中…'));
    try {
      const rep = await api.importFile(picked, dryRun);
      reportHost.innerHTML = '';
      reportHost.append(renderReport(rep, dryRun));
      if (rep.ok && !dryRun) {
        invalidate();
        toast(`已匯入 ${rep.batches} 批次、${rep.measurements} 個測點`, 'success');
        setTimeout(() => location.reload(), 900);
      }
    } catch (e) {
      reportHost.innerHTML = '';
      reportHost.append(notice('error', '匯入失敗', e.message, e.detail || ''));
    }
  }

  // ── 合成資料 ────────────────────────────────────────────
  const nInput = h('input', { type: 'number', value: 20, min: 4, max: 200 });
  const noiseInput = h('input', { type: 'number', value: 0.12, min: 0, max: 1, step: 0.01 });
  const ptsInput = h('input', { type: 'number', value: 8, min: 3, max: 40 });
  const anomInput = h('input', { type: 'checkbox', checked: true });

  root.append(card('產生合成資料（demo 與方法驗證用）',
    '兩個用途：一是在拿到客戶歷史資料之前先把整套工具跑起來、會議上能實際操作；'
    + '二是以已知的真實 k₀ 與 δ/D 生成資料，讓整套流程反解、檢查能不能還原——'
    + '還原不了就代表方法有問題，這比在真實資料上「看起來合理」可靠得多。',
    h('div', { class: 'row' },
      h('label', { class: 'field' }, '批次數', nInput),
      h('label', { class: 'field' }, '量測相對誤差（對數 σ）', noiseInput),
      h('label', { class: 'field' }, '每批取樣點數', ptsInput),
      h('label', { class: 'switch', style: 'margin-top:18px' }, anomInput,
        '植入異常批次（熱電偶飄移、取樣位置顛倒）'),
      h('button', { style: 'margin-top:14px', onclick: doSeed }, '產生並取代現有資料')),
    h('p', { class: 'muted', style: 'margin-top:10px' },
      '⚠ 此操作會清空資料庫中既有的批次。所有由合成資料產生的畫面，'
      + '批次備註都會標示為「合成資料（demo 用，非實測）」。')));

  async function doSeed() {
    if (!confirm('這會清空現有資料並以合成資料取代，確定嗎？')) return;
    reportHost.innerHTML = '';
    try {
      const res = await api.seedDemo({
        n_batches: Number(nInput.value), rel_noise: Number(noiseInput.value),
        n_sample_points: Number(ptsInput.value), inject_anomalies: anomInput.checked,
        clear_existing: true,
      });
      invalidate();
      toast(`已產生 ${res.n_batches} 批合成資料`, 'success');
      setTimeout(() => location.reload(), 700);
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  // ── 現有資料 ────────────────────────────────────────────
  root.append(card(`目前資料庫（${list.length} 批）`, null,
    table(['批次', '日期', { label: '速率', align: 'right' }, { label: '溫度', align: 'right' },
           { label: '次數', align: 'right' }, '氣氛', '分析方法',
           { label: '得料率', align: 'right' }, { label: '', align: 'center' }],
      list.map((b) => ({
        cells: [b.batch_id, b.run_date || '—',
          { text: num(b.speed_mm_hr, 2), align: 'right' },
          { text: num(b.temp_c, 1), align: 'right' },
          { text: String(b.n_passes), align: 'right' },
          b.atmosphere, b.analysis_method,
          { text: pct(b.yield_frac), align: 'right' },
          { node: h('button', {
              class: 'ghost small',
              onclick: async () => {
                if (!confirm(`刪除批次 ${b.batch_id}？`)) return;
                try {
                  await api.deleteBatch(b.batch_id);
                  invalidate(); toast('已刪除', 'success');
                  setTimeout(() => location.reload(), 500);
                } catch (e) { toast(e.message, 'error'); }
              },
            }, '刪除'), align: 'center' }],
      })), { empty: '尚無資料' }),
    h('div', { class: 'row', style: 'margin-top:12px' },
      h('button', {
        class: 'danger small',
        onclick: async () => {
          if (!confirm('清空所有批次資料？此操作無法復原。')) return;
          await api.clearAll(); invalidate(); location.reload();
        },
      }, '清空所有資料'))));

  return root;
}

function renderReport(rep, dryRun) {
  const box = h('div', { style: 'margin-top:14px' });
  box.append(notice(rep.ok ? 'good' : 'error',
    rep.ok ? (dryRun ? '稽核通過（未寫入）' : '匯入成功')
           : `稽核未通過，${rep.errors.length} 項錯誤（未寫入任何資料）`,
    `${rep.batches} 個批次、${rep.measurements} 個測點，其中 ${rep.censored} 點為設限值。`
    + `元素：${(rep.elements || []).join('、') || '—'}`));

  if (rep.errors?.length) {
    box.append(h('div', { class: 'card' }, h('div', { class: 'card-body' },
      h('h4', {}, `錯誤（${rep.errors.length}）— 修正後才能匯入`),
      h('ul', { style: 'padding-left:20px' },
        ...rep.errors.slice(0, 60).map((e) => h('li', {}, e))),
      rep.errors.length > 60 ? h('p', { class: 'muted' },
        `另有 ${rep.errors.length - 60} 項未列出。`) : null)));
  }
  if (rep.warnings?.length) {
    box.append(h('div', { class: 'card' }, h('div', { class: 'card-body' },
      h('h4', {}, `警告（${rep.warnings.length}）— 不影響匯入，但會影響分析品質`),
      h('ul', { style: 'padding-left:20px' },
        ...rep.warnings.slice(0, 60).map((w) => h('li', {}, w))),
      rep.warnings.length > 60 ? h('p', { class: 'muted' },
        `另有 ${rep.warnings.length - 60} 項未列出。`) : null)));
  }
  return box;
}
