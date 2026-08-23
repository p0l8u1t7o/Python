/** 批次資料：清單 + 單批詳情（實測 vs 模型疊圖、殘差、6N 視窗）。 */

import { api } from '../api.js';
import { h, card, table, badge, pct, num, notice, chartBox, spinner, toneForK,
         toneForSeverity, stat } from '../ui.js';
import { profileChart, residualChart, PALETTE } from '../charts.js';
import { thresholdPpm } from '../app.js';

let selectedId = null;

export default async function batches() {
  const list = await api.listBatches();
  const root = h('div', { class: 'split' });

  if (!list.length) {
    return h('div', {}, notice('warn', '沒有批次資料',
      '請先到「資料管理」匯入或產生資料。'));
  }
  if (!selectedId || !list.some((b) => b.batch_id === selectedId)) {
    selectedId = list[0].batch_id;
  }

  const detailHost = h('div');
  const listCard = card('批次清單', `共 ${list.length} 批`,
    h('div', { class: 'scroll-list' },
      table(['批次', { label: 'v', align: 'right' }, { label: 'T', align: 'right' },
             { label: 'n', align: 'right' }, { label: '得料率', align: 'right' }],
        list.map((b) => ({
          cells: [b.batch_id,
                  { text: num(b.speed_mm_hr, 2), align: 'right' },
                  { text: num(b.temp_c, 1), align: 'right' },
                  { text: String(b.n_passes), align: 'right' },
                  { text: pct(b.yield_frac), align: 'right' }],
          __class: b.batch_id === selectedId ? 'active-row' : null,
          __click: () => { selectedId = b.batch_id; renderDetail(detailHost); },
        })))),
    h('p', { class: 'muted', style: 'margin-top:8px' },
      'v = 熔區移動速率 (mm/hr)、T = 熔區溫度 (°C)、n = 純化次數'));

  root.append(listCard, detailHost);
  await renderDetail(detailHost);
  return root;
}

async function renderDetail(host) {
  host.innerHTML = '';
  host.append(spinner('載入批次…'));
  let d;
  try {
    d = await api.getBatch(selectedId);
  } catch (e) {
    host.innerHTML = '';
    host.append(notice('error', '載入失敗', e.message));
    return;
  }
  host.innerHTML = '';

  const b = d.batch;
  const w = d.window || {};
  const colors = PALETTE();
  const els = Object.keys(d.curves);

  host.append(h('div', { class: 'grid cols-4', style: 'margin-bottom:16px' },
    stat('6N 得料率', pct(w.yield_frac),
      `高純區 x/L ${num(w.head_cut_frac, 3)} ~ ${num(w.tail_cut_frac, 3)}`,
      w.yield_frac > 0.4 ? 'good' : w.yield_frac > 0.15 ? 'warn' : 'bad'),
    stat('限制元素', w.limiting_element || '—', '決定切點的元素'),
    stat('製程條件', `${num(b.speed_mm_hr, 2)} mm/hr`,
      `${num(b.temp_c, 1)} °C · ${b.n_passes} passes · ${b.atmosphere}`),
    stat('熔區長度比 l/L', num(b.zone_len_frac, 3),
      `${b.zone_len_mm} mm / ${b.ingot_len_mm} mm`)));

  for (const a of d.anomalies || []) {
    host.append(notice(a.severity === 'high' ? 'error' : 'warn',
      `資料稽核 · ${a.element} · ${a.severity.toUpperCase()}`,
      ...a.reasons, a.suggested_action));
  }

  // ── 疊圖 ────────────────────────────────────────────────
  const box = chartBox(`${b.batch_id} — 實測 vs 物理模型`,
    '實線為 Pfann 多次 pass 模擬曲線（以擬合出的 k_eff 計算），圓點為實測值，'
    + '向下三角形代表該點低於檢測極限（左設限，以 Tobit likelihood 處理，'
    + '既不當成 0 也不當成 LOD）。綠色區塊為 6N 高純區，紅色為雜質濃縮區。');
  host.append(card('濃度分布', null, box));

  profileChart(box.host, {
    height: 380,
    threshold: thresholdPpm(),
    window: w,
    series: els.map((el, i) => ({
      label: el, color: colors[i % colors.length],
      points: d.curves[el].x_model.map((x, j) => [x, d.curves[el].y_model[j]]),
    })),
    scatter: els.map((el, i) => ({
      label: el, color: colors[i % colors.length],
      points: d.curves[el].x_obs.map((x, j) => [x, d.curves[el].y_obs[j]]),
      censored: d.curves[el].censored,
    })),
  });

  // ── 擬合表 ──────────────────────────────────────────────
  host.append(card('k_eff 擬合結果',
    'k_eff 越低代表偏析純化效果越好。信賴區間由參數式 bootstrap 產生：'
    + '從擬合好的模型重新生成資料、重新判定設限、再重擬合，重複數百次看 k 飄多少。',
    table(['元素', { label: 'k_eff', align: 'right' },
           { label: '95% 區間', align: 'right' },
           { label: 'C₀ (ppm)', align: 'right' },
           { label: '設限點', align: 'center' },
           { label: 'σ_log', align: 'right' }, '判讀'],
      els.map((el) => {
        const f = d.curves[el].fit;
        return { cells: [
          el,
          { text: num(f.k_eff), align: 'right' },
          { text: f.k_lo != null ? `${num(f.k_lo)} ~ ${num(f.k_hi)}` : '—', align: 'right' },
          { text: num(f.c0_ppm, 3), align: 'right' },
          { text: `${f.n_censored}/${f.n_points}`, align: 'center' },
          { text: num(f.sigma_log, 3), align: 'right',
            title: `相當於 ±${((Math.exp(f.sigma_log) - 1) * 100).toFixed(0)}% 相對誤差` },
          { node: h('span', {}, badge(f.interpretation.slice(0, 22), toneForK(f.k_eff)),
              f.note ? h('div', { class: 'muted', style: 'white-space:normal;max-width:340px' },
                f.note) : null) },
        ] };
      }))));

  // ── 殘差 ────────────────────────────────────────────────
  const rbox = chartBox('標準化殘差',
    '殘差落在綠色帶（±1σ）內屬正常。若殘差呈現「前段一致偏高、後段一致偏低」的結構，'
    + '通常代表取樣位置、熔區長度或 pass 次數的記錄有誤，而不是量測雜訊。'
    + '菱形為設限點，顯示的是 Tobit 的期望殘差。');
  host.append(card('擬合品質', null, rbox));
  residualChart(rbox.host, {
    height: 220,
    points: els.flatMap((el, i) => d.curves[el].x_obs.map((x, j) => ({
      x, y: d.curves[el].residuals[j], label: el,
      color: colors[i % colors.length], censored: d.curves[el].censored[j],
    }))),
  });
}
