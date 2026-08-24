/** 最佳化建議：網格熱圖 + 三種建議 + 貝氏最佳化下一批 + DOE 省批次試算。 */

import { api } from '../api.js';
import { h, card, stat, badge, pct, num, money, notice, chartBox, spinner, table } from '../ui.js';
import { heatmap, lineChart } from '../charts.js';
import { ensureOverview } from '../app.js';

let passIndex = 0;
let throughputWeight = 0;
let zoneFrac = null;

export default async function optimize() {
  const ov = await ensureOverview();
  if (ov.empty) return h('div', {}, notice('warn', '沒有資料', '請先匯入或產生批次資料。'));

  if (zoneFrac === null) {
    zoneFrac = Math.round((ov.zone_len_frac_median || 0.1) * 1000) / 1000;
  }

  const root = h('div');
  const gridHost = h('div');
  const boHost = h('div');
  const doeHost = h('div');

  root.append(
    card('掃描設定', null,
      h('div', { class: 'row' },
        h('label', { class: 'field' }, '產能權重',
          h('select', {
            onchange: (e) => { throughputWeight = Number(e.target.value); renderGrid(gridHost); },
          },
            h('option', { value: '0' }, '0 — 只看得料率'),
            h('option', { value: '0.02' }, '0.02 — 略微考慮時間成本'),
            h('option', { value: '0.05' }, '0.05 — 明顯偏向產能'))),
        h('label', { class: 'field' }, '熔區長度比 l/L',
          h('input', {
            type: 'number', min: 0.02, max: 0.5, step: 0.005, value: zoneFrac,
            onchange: (e) => {
              const v = Number(e.target.value);
              if (Number.isFinite(v) && v > 0 && v < 1) { zoneFrac = v; renderGrid(gridHost); }
            },
          })),
        h('p', { class: 'muted', style: 'max-width:520px' },
          '產能權重把「跑得慢、跑很多次」的時間成本納入目標函數：'
          + '目標 = 得料率 − w × (次數 / 速率)。w = 0 時是純追求純度。'
          + '熔區長度比 l/L 預設為歷史批次中位數，如有實測值請以實測為準。'))),
    gridHost, boHost, doeHost);

  await renderGrid(gridHost);
  renderBO(boHost);
  renderDOE(doeHost, ov);
  return root;
}

async function renderGrid(host) {
  host.innerHTML = '';
  host.append(spinner('掃描參數網格…'));
  let res;
  try {
    res = await api.optimizeGrid({ throughput_weight: throughputWeight,
                                   zone_len_frac: zoneFrac });
  } catch (e) {
    host.innerHTML = '';
    host.append(notice('error', '掃描失敗', e.message));
    return;
  }
  host.innerHTML = '';

  for (const n of res.notes || []) host.append(notice('warn', '掃描提示', n));

  host.append(card('三種建議 — 用途各異，建議一併參考',
    '同時提供三組建議而非單一「最佳解」，可完整呈現取捨關係，便於依實際需求選用。',
    h('div', { class: 'grid cols-3' },
      suggestionCard('可直接執行（穩健）', res.best_robust, 'good',
        '只在歷史資料涵蓋範圍內挑選，且以悲觀情境排序。此組合可直接應用於產線。'),
      suggestionCard('理論最高得料率', res.best, 'ok',
        res.best && !res.best.in_training_range
          ? '⚠ 位於外插區。建議視為值得安排實驗驗證的方向，不宜直接套用於產線。'
          : '在掃描範圍內得料率最高的組合。'),
      suggestionCard('產能導向', res.best_throughput, 'warn',
        res.best_throughput?.rationale || ''))));

  // ── 熱圖 ────────────────────────────────────────────────
  const passes = res.passes || [];
  // 預設顯示「穩健建議」所用的 pass 次數，而不是清單第一項——
  // 第一項通常是次數最少、得料率最差的那張圖，第一眼印象會很糟。
  if (!host.dataset.touched && res.best_robust) {
    const i = passes.indexOf(res.best_robust.n_passes);
    if (i >= 0) passIndex = i;
  }
  passIndex = Math.min(passIndex, Math.max(passes.length - 1, 0));
  const chips = h('div', { class: 'chips', style: 'margin-bottom:12px' },
    ...passes.map((p, i) => h('button', {
      class: `chip ${i === passIndex ? 'active' : ''}`,
      onclick: () => { passIndex = i; host.dataset.touched = '1'; drawHeat(); },
    }, `${p} passes`)));

  const box = chartBox('6N 得料率地圖',
    '橫軸為熔區移動速率、縱軸為熔區溫度，顏色為預測得料率。'
    + '半透明區域代表超出歷史批次涵蓋範圍（外插），白圈是穩健建議點。'
    + '將滑鼠移至格點上可檢視確切數值。');
  host.append(card('參數空間掃描',
    `共評估 ${res.n_evaluated} 組參數組合。`, chips, box));

  function drawHeat() {
    chips.querySelectorAll('.chip').forEach((c, i) =>
      c.classList.toggle('active', i === passIndex));
    const br = res.best_robust;
    heatmap(box.host, {
      height: 400,
      xs: res.speeds, ys: res.temps, z: res.yield_grid[passIndex],
      inRange: res.in_range_grid[passIndex],
      xLabel: '熔區移動速率 (mm/hr)', yLabel: '熔區溫度 (°C)',
      marker: br && br.n_passes === passes[passIndex]
        ? { x: br.speed_mm_hr, y: br.temp_c, label: '穩健建議' } : null,
    });
  }
  drawHeat();

  // ── pass 建議 ───────────────────────────────────────────
  const pa = res.pass_advice || {};
  if (pa.yield_by_pass) {
    const pbox = chartBox('純化次數的邊際效益（在穩健建議條件下）', pa.note);
    host.append(card('純化次數建議', null, pbox,
      h('div', { class: 'row', style: 'margin-top:10px' },
        badge(`建議 ${pa.recommended_passes} 次`, 'good'),
        badge(`第 ${pa.saturation_pass} 次後邊際增益趨近於零`, 'warn'),
        badge(`可省下 ${pa.passes_saved_vs_max} 趟`, 'neutral'))));
    lineChart(pbox.host, {
      height: 250, percentY: true,
      xLabel: '純化次數', yLabel: '6N 得料率',
      yTickFormat: (v) => `${(v * 100).toFixed(0)}%`,
      series: [{ label: '6N 得料率', points: pa.yield_by_pass.map((y, i) => [i, y]) }],
      vline: pa.recommended_passes, vlineLabel: `建議 ${pa.recommended_passes} 次`,
    });
  }
}

function suggestionCard(title, s, tone, note) {
  if (!s) return h('div', { class: 'stat' }, h('div', { class: 'stat-label' }, title),
    h('div', { class: 'stat-value' }, '—'));
  return h('div', { class: `stat tone-${tone}` },
    h('div', { class: 'stat-label' }, title),
    h('div', { class: 'stat-value' }, pct(s.yield_nominal)),
    h('div', { class: 'stat-hint' },
      `速率 ${num(s.speed_mm_hr, 2)} mm/hr · ${num(s.temp_c, 1)} °C · ${s.n_passes} passes`),
    h('div', { class: 'stat-hint', style: 'margin-top:4px' },
      `悲觀 ${pct(s.yield_pessimistic)}｜限制元素 ${s.limiting_element || '—'}`),
    h('div', { class: 'stat-hint', style: 'margin-top:6px;white-space:normal' }, note));
}

async function renderBO(host) {
  host.innerHTML = '';
  host.append(spinner('計算貝氏最佳化建議…'));
  let res;
  try {
    res = await api.suggest({ n_suggest: 3 });
  } catch (e) {
    host.innerHTML = '';
    host.append(notice('error', '無法產生實驗建議', e.message));
    return;
  }
  host.innerHTML = '';

  if (!res.suggestions?.length) {
    host.append(card('下一批實驗參數建議', null,
      ...(res.notes || []).map((n) => notice('warn', '目前無法建議', n))));
    return;
  }

  host.append(card('下一批實驗參數建議 — 貝氏最佳化序列實驗設計',
    '實驗批次的成本與時程往往是最主要的限制。'
    + '本功能回答的問題是：下一批應設定何種參數，才能取得最多的資訊。'
    + '系統僅提供實驗建議，最終準確度仍來自真實實驗資料。',
    table(['順序', { label: '速率 mm/hr', align: 'right' },
           { label: '溫度 °C', align: 'right' }, { label: '次數', align: 'right' },
           { label: '預測得料率', align: 'right' }, '這一批的目的'],
      res.suggestions.map((s) => ({
        cells: [`第 ${s.rank} 批`,
          { text: num(s.speed_mm_hr, 2), align: 'right' },
          { text: num(s.temp_c, 1), align: 'right' },
          { text: String(s.n_passes), align: 'right' },
          { text: `${pct(s.predicted_yield)} ± ${pct(s.predicted_std)}`, align: 'right' },
          { node: h('span', { style: 'white-space:normal;display:block;max-width:460px' },
              s.rationale) }],
      }))),
    h('p', { class: 'muted', style: 'margin-top:10px' },
      `依 ${res.n_observations} 批既有資料建模，目前最佳得料率 ${pct(res.best_observed_yield)}。`
      + (res.notes || []).join(' '))));
}

async function renderDOE(host, ov) {
  host.innerHTML = '';
  host.append(spinner('執行 DOE 對比模擬…'));
  let res;
  try {
    res = await api.doeComparison({ bo_budget: 12, seed_n: 5, cost_per_batch: 100000 });
  } catch (e) {
    host.innerHTML = '';
    host.append(notice('warn', 'DOE 對比未執行', e.message));
    return;
  }
  host.innerHTML = '';

  const box = chartBox('全因子 DOE vs 貝氏最佳化：跑到第 n 批時的最佳得料率',
    '兩條線都在同一個「虛擬產線」上跑（以既有資料擬合出的模型），比較的是實驗策略的效率，'
    + '不是對真實產線的績效承諾。全因子的順序已隨機打散，避免因為剛好先跑到最佳點而高估其效率。');

  host.append(card('實驗成本節省評估',
    '比較兩種實驗策略在相同目標下所需的批次數，並換算為成本差異。',
    h('div', { class: 'grid cols-4', style: 'margin-bottom:14px' },
      stat('全因子需要', `${res.factorial_n} 批`,
        `最終最佳得料率 ${pct(res.factorial_best)}`),
      stat('貝氏最佳化', res.bo_batches_to_match ? `${res.bo_batches_to_match} 批`
        : `${res.bo_n} 批未追平`,
        res.bo_batches_to_match ? '即達到全因子最終結果的 99%' : '需要更多預算',
        res.bo_batches_to_match ? 'good' : 'warn'),
      stat('可省批次', `${res.batches_saved} 批`, '在相同目標下'),
      stat('估算節省', money(res.cost_saved),
        `以每批 ${money(res.cost_per_batch)} 計`, 'good')),
    box,
    ...(res.notes || []).map((n) => h('p', { class: 'chart-note' }, n))));

  lineChart(box.host, {
    height: 300, percentY: true,
    xLabel: '已跑批次數', yLabel: '目前為止的最佳得料率',
    yTickFormat: (v) => `${(v * 100).toFixed(0)}%`,
    series: [
      { label: `全因子 DOE（${res.factorial_n} 批）`, color: 'var(--c2)', markers: false,
        points: res.factorial_trace.map((y, i) => [i + 1, y]) },
      { label: `貝氏最佳化（起始 ${res.seed_n} 批 + 序列建議）`, color: 'var(--c1)',
        points: res.bo_trace.map((y, i) => [i + 1, y]) },
    ],
    vline: res.bo_batches_to_match,
    vlineLabel: res.bo_batches_to_match ? `第 ${res.bo_batches_to_match} 批追平` : null,
  });
}
