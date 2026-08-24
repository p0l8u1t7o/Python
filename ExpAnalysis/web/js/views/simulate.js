/** 模擬與預測：拉滑桿即時看到分布與得料率，含雙軌顯示。 */

import { api } from '../api.js';
import { h, card, stat, badge, pct, num, notice, chartBox, spinner, table } from '../ui.js';
import { profileChart, PALETTE } from '../charts.js';
import { ensureOverview, thresholdPpm } from '../app.js';

const params = { speed: null, temp: null, passes: null, useAi: false, headCrop: 0.03,
                 zoneFrac: null, c0: null };
let debounce = null;

export default async function simulate() {
  const ov = await ensureOverview();
  if (ov.empty) {
    return h('div', {}, notice('warn', '沒有資料', '請先匯入或產生批次資料。'));
  }
  if (params.speed === null) {
    params.speed = round2((ov.speed_range[0] + ov.speed_range[1]) / 2);
    params.temp = Math.round((ov.temp_range[0] + ov.temp_range[1]) / 2);
    params.passes = Math.round((ov.pass_range[0] + ov.pass_range[1]) / 2);
  }
  if (params.zoneFrac === null) {
    params.zoneFrac = Math.round((ov.zone_len_frac_median || 0.1) * 1000) / 1000;
  }
  if (params.c0 === null) {
    params.c0 = {};
    for (const el of ov.elements || []) params.c0[el] = ov.c0_median?.[el] ?? 1.0;
  }

  const root = h('div');
  const out = h('div');

  const sSpeed = slider('熔區移動速率', 'mm/hr',
    Math.max(0.2, ov.speed_range[0] * 0.5), round2(ov.speed_range[1] * 1.5), 0.05,
    params.speed, (v) => { params.speed = v; run(out); });
  const sTemp = slider('熔區溫度', '°C',
    Math.round(ov.temp_range[0] - 15), Math.round(ov.temp_range[1] + 15), 1,
    params.temp, (v) => { params.temp = v; run(out); });
  const sPass = slider('純化次數', 'pass', 1, Math.max(20, ov.pass_range[1] + 6), 1,
    params.passes, (v) => { params.passes = v; run(out); });
  const sCrop = slider('頭端切除比例', '', 0, 0.2, 0.005,
    params.headCrop, (v) => { params.headCrop = v; run(out); });
  // 指南第 04 節：真正的物理變數是熔區長度 l，溫度只是它的代理指標，
  // 故 l/L 必須可獨立於溫度調整。預設為歷史批次中位數。
  const sZone = slider('熔區長度比 l/L', '', 0.02, 0.3, 0.005,
    params.zoneFrac, (v) => { params.zoneFrac = v; run(out); });

  const aiToggle = h('label', { class: 'switch' },
    h('input', { type: 'checkbox', onchange: (e) => { params.useAi = e.target.checked; run(out); } }),
    '同時顯示「物理 + AI 修正」（雙軌）');

  root.append(card('製程條件', '調整滑桿即可即時檢視雜質分布與 6N 得料率的變化。',
    sSpeed, sTemp, sPass, sZone, sCrop,
    h('div', { class: 'row', style: 'margin-top:6px' }, aiToggle,
      h('span', { class: 'muted' },
        `歷史涵蓋範圍：速率 ${num(ov.speed_range[0], 2)}~${num(ov.speed_range[1], 2)} mm/hr、`
        + `溫度 ${num(ov.temp_range[0], 0)}~${num(ov.temp_range[1], 0)} °C、`
        + `l/L 中位數 ${num(ov.zone_len_frac_median, 3)}`)),
    h('details', { style: 'margin-top:10px' },
      h('summary', { class: 'muted', style: 'cursor:pointer' },
        '進階設定：各元素進料濃度 C₀（預設為歷史批次中位數）'),
      h('div', { class: 'row', style: 'margin-top:8px' },
        ...Object.keys(params.c0).map((el) =>
          h('label', { class: 'field' }, `${el} C₀ (ppm)`,
            h('input', {
              type: 'number', min: 0.001, step: 0.1, value: params.c0[el],
              onchange: (e) => {
                const v = Number(e.target.value);
                if (Number.isFinite(v) && v > 0) { params.c0[el] = v; run(out); }
              },
            })))),
      h('p', { class: 'muted', style: 'margin-top:6px' },
        'C₀ 為進料的初始雜質濃度，是所有預測曲線的比較基準。'
        + '調整此值可評估更換進料純度等級的影響。'))));
  root.append(out);
  run(out);
  return root;
}

function round2(v) { return Math.round(v * 100) / 100; }

function slider(label, unit, min, max, step, value, onInput) {
  const val = h('span', { class: 'val' }, `${value}${unit ? ' ' + unit : ''}`);
  const input = h('input', {
    type: 'range', min, max, step, value,
    oninput: (e) => {
      const v = Number(e.target.value);
      val.textContent = `${v}${unit ? ' ' + unit : ''}`;
      onInput(v);
    },
  });
  return h('div', { class: 'slider-row' }, h('span', {}, label), input, val);
}

function run(host) {
  clearTimeout(debounce);
  debounce = setTimeout(() => doRun(host), 160);
}

async function doRun(host) {
  if (!host.dataset.init) { host.innerHTML = ''; host.append(spinner('模擬中…')); host.dataset.init = '1'; }
  let res;
  try {
    res = await api.simulate({
      speed_mm_hr: params.speed, temp_c: params.temp, n_passes: params.passes,
      head_crop_frac: params.headCrop, use_ai: params.useAi,
      zone_len_frac: params.zoneFrac, c0_ppm: params.c0,
    });
  } catch (e) {
    host.innerHTML = '';
    host.append(notice('error', '模擬失敗', e.message));
    return;
  }
  const p = res.physics;
  const ai = res.ai;
  const dt = res.dual_track;
  host.innerHTML = '';

  host.append(h('div', { class: 'grid cols-4', style: 'margin-bottom:16px' },
    stat('6N 得料率（名目）', pct(p.yield_nominal),
      `樂觀 ${pct(p.yield_optimistic)} / 悲觀 ${pct(p.yield_pessimistic)}`,
      p.yield_nominal > 0.4 ? 'good' : p.yield_nominal > 0.15 ? 'warn' : 'bad'),
    stat('高純區', `x/L ${num(p.window.head_cut_frac, 3)}–${num(p.window.tail_cut_frac, 3)}`,
      `限制元素 ${p.window.limiting_element || '—'}`),
    stat('雜質濃縮區起點', `x/L ${num(p.window.concentrate_start_frac, 3)}`,
      '總雜質超過門檻 5 倍之處'),
    stat('外插狀態', p.in_training_range ? '範圍內' : '外插區',
      p.in_training_range ? '模型可信度正常' : '不確定度大幅上升',
      p.in_training_range ? 'good' : 'warn')));

  for (const w of p.warnings || []) host.append(notice('warn', '外插警示', w));

  if (dt) {
    host.append(card('雙軌顯示 — AI 修正量透明呈現',
      '介面同時顯示「純物理」與「物理 + AI」兩組數值，修正量隨時可見；'
      + '若兩者差異過大，即代表 AI 修正需要進一步檢視。',
      h('div', { class: 'dual-track' },
        h('div', { class: 'track' },
          h('div', { class: 'stat-label' }, '純物理模型'),
          h('div', { class: 'stat-value' }, pct(dt.physics_only)),
          h('div', { class: 'stat-hint' }, 'Pfann + BPS/GP，不含任何 ML 修正')),
        h('div', { class: 'track ai' },
          h('div', { class: 'stat-label' }, '物理 + AI 修正'),
          h('div', { class: 'stat-value' },
            dt.ai_applied ? pct(dt.physics_plus_ai) : '未套用'),
          h('div', { class: 'stat-hint' },
            dt.ai_applied
              ? `相對修正 ${(dt.delta_pct * 100).toFixed(2)}%`
              + `（絕對 ${(dt.delta * 100).toFixed(2)} 個百分點）`
              : dt.reason))),
      h('p', { class: 'muted', style: 'margin-top:10px' }, dt.reason)));
  }

  const colors = PALETTE();
  const els = Object.keys(p.profiles);
  const box = chartBox('預測雜質分布',
    '各元素曲線由 GP/BPS 映射給出的 k_eff、經 Pfann 多次 pass 離散模擬得到。'
    + '粗線為總雜質，決定 6N 切點的就是它。');
  host.append(card('分布與純度視窗', null, box));

  profileChart(box.host, {
    height: 400, threshold: thresholdPpm(), window: p.window,
    series: [
      ...els.map((el, i) => ({
        label: el, color: colors[i % colors.length],
        points: p.x_norm.map((x, j) => [x, p.profiles[el][j]]),
      })),
      { label: '總雜質', color: 'var(--fg)', width: 3,
        points: p.x_norm.map((x, j) => [x, p.total_ppm[j]]) },
      ...(ai ? [{ label: '總雜質（含 AI 修正）', color: 'var(--accent)', dash: '6 4', width: 2,
        points: ai.x_norm.map((x, j) => [x, ai.total_ppm[j]]) }] : []),
    ],
  });

  host.append(card('各元素的預測 k_eff',
    '區間來自高斯過程的不確定度。區間過寬代表模型於此條件下的不確定度較高，'
    + '不建議直接作為製程參數設定之依據。',
    table(['元素', { label: 'k_eff', align: 'right' },
           { label: '95% 區間', align: 'right' },
           { label: '切點濃度 (ppm)', align: 'right' }],
      els.map((el) => ({
        cells: [el,
          { text: num(p.k_eff[el]), align: 'right' },
          { text: `${num(p.k_ci[el][0])} ~ ${num(p.k_ci[el][1])}`, align: 'right' },
          { text: num(p.window.per_element_at_cut?.[el], 4), align: 'right' }],
      })))));
}
