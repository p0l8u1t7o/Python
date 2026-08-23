/** 總覽：一眼看完「這批資料能不能做事、瓶頸在哪」。 */

import { api } from '../api.js';
import { h, card, stat, table, badge, pct, num, notice, chartBox, toneForK } from '../ui.js';
import { barChart, lineChart } from '../charts.js';
import { ensureOverview } from '../app.js';

export default async function dashboard() {
  const ov = await ensureOverview(true);
  const root = h('div');

  if (ov.empty) {
    root.append(notice('warn', '資料庫目前沒有任何批次',
      '請到「資料管理」匯入客戶的歷史批次 CSV，或先產生一組合成資料把整套流程跑起來。',
      h('p', {}, h('a', { href: '#/data' }, '前往資料管理 →'))));
    return root;
  }

  const ys = ov.yield_stats || {};
  const ac = ov.anomaly_counts || {};
  const worst = Object.entries(ov.keff_summary)
    .sort((a, b) => b[1].median - a[1].median)[0];

  root.append(h('div', { class: 'grid cols-4', style: 'margin-bottom:18px' },
    stat('批次數', String(ov.n_batches),
      `${ov.n_measurements} 個測點，其中 ${ov.n_censored} 點低於檢測極限`),
    stat('平均 6N 得料率', pct(ys.mean),
      `最佳 ${pct(ys.max)}／最差 ${pct(ys.min)}`,
      ys.mean > 0.4 ? 'good' : ys.mean > 0.15 ? 'warn' : 'bad'),
    stat('限制元素', worst ? worst[0] : '—',
      worst ? `k_eff 中位數 ${num(worst[1].median)}，${worst[1].removable}` : '',
      worst ? toneForK(worst[1].median) : null),
    stat('資料稽核', `${ac.high || 0} 高 / ${ac.medium || 0} 中`,
      ac.high ? '有批次需要確認原始紀錄' : '沒有高嚴重度發現',
      ac.high ? 'bad' : ac.medium ? 'warn' : 'good')));

  for (const w of ov.warnings || []) {
    root.append(notice('warn', '模型提示', w));
  }

  // ── 元素可去除性 ─────────────────────────────────────────
  const rows = Object.entries(ov.keff_summary).map(([el, v]) => ({
    cells: [
      el,
      { text: num(v.median), align: 'right' },
      { text: `${num(v.min)} ~ ${num(v.max)}`, align: 'right' },
      { node: badge(v.removable, toneForK(v.median)), align: 'center' },
      { text: num(v.bps?.k0), align: 'right' },
      { text: num(v.bps?.delta_over_d, 3), align: 'right' },
      { text: num(v.bps?.r2, 3), align: 'right' },
      { node: badge(v.gp_used ? '高斯過程' : 'BPS 線性', v.gp_used ? 'ok' : 'neutral'),
        align: 'center' },
    ],
  }));

  const bars = chartBox('各元素的偏析可去除性（k_eff 中位數，越低越好）',
    'k_eff 是有效分配係數：凝固時被固體帶走的雜質比例。k < 0.15 易去除；k > 0.75 代表偏析法對此元素幾乎無效，應由前段製程處理。');
  root.append(card('元素分析摘要',
    '每一條實測曲線都被壓縮成一個有物理意義的數字 k_eff，這是本方法能在數十批資料下工作的關鍵。',
    table(['元素', { label: 'k_eff 中位數', align: 'right' },
           { label: '批次間範圍', align: 'right' },
           { label: '判定', align: 'center' },
           { label: 'k₀（平衡值）', align: 'right' },
           { label: 'δ/D (hr/mm)', align: 'right' },
           { label: 'R²', align: 'right' },
           { label: '映射模型', align: 'center' }], rows),
    bars));

  barChart(bars.host, {
    height: Math.max(140, Object.keys(ov.keff_summary).length * 40 + 40),
    labelWidth: 56,
    xLabel: 'k_eff 中位數',
    items: Object.entries(ov.keff_summary).map(([el, v]) => ({
      label: el, value: v.median, text: `${num(v.median)}（${v.removable}）`,
      color: `var(--${toneForK(v.median) === 'good' ? 'good'
        : toneForK(v.median) === 'ok' ? 'ok'
        : toneForK(v.median) === 'warn' ? 'warn' : 'bad'})`,
    })),
  });

  // ── 純化次數飽和 ─────────────────────────────────────────
  const passBox = chartBox('純化次數的邊際效益',
    '一直 pass 下去，分布會收斂到「極限分布」——往尾端掃出去的雜質與熔區從右邊吃回來的達成平衡，之後再做完全沒有增益。這條曲線直接告訴你該停在第幾次。');
  const passCard = card('做幾次就夠了？',
    '這是本階段就能交付、能立刻省成本的結論。', passBox);
  root.append(passCard);

  try {
    const pa = await api.passAdvice(25);
    const pts = pa.yield_by_pass.map((y, i) => [i, y]);
    lineChart(passBox.host, {
      height: 260, percentY: true,
      xLabel: '純化次數 (pass)', yLabel: '6N 得料率',
      yTickFormat: (v) => `${(v * 100).toFixed(0)}%`,
      series: [{ label: '6N 得料率', points: pts }],
      vline: pa.recommended_passes,
      vlineLabel: `建議 ${pa.recommended_passes} 次`,
    });
    passBox.append(h('div', { class: 'row', style: 'margin-top:10px' },
      badge(`建議 ${pa.recommended_passes} 次`, 'good'),
      badge(`第 ${pa.saturation_pass} 次後邊際增益 < 0.5 個百分點`, 'warn'),
      badge(`第 ${pa.ultimate_pass} 次收斂到極限分布`, 'neutral')));
    passBox.append(h('p', { class: 'chart-note' }, pa.note));
    passBox.append(h('p', { class: 'chart-note' },
      `評估條件：速率 ${num(pa.conditions.speed_mm_hr, 2)} mm/hr、`
      + `溫度 ${num(pa.conditions.temp_c, 1)} °C（取歷史批次中位數）、`
      + `l/L = ${num(pa.conditions.zone_len_frac, 3)}。`));
  } catch (e) {
    passBox.host.replaceChildren(h('p', { class: 'muted' }, `無法計算：${e.message}`));
  }

  // ── 製程涵蓋範圍 ─────────────────────────────────────────
  root.append(card('歷史批次的參數涵蓋範圍',
    '模型只在這個範圍內可靠。超出範圍的查詢一律會標示為外插，並自動停用 AI 修正。',
    h('div', { class: 'grid cols-3' },
      stat('熔區移動速率', `${num(ov.speed_range[0], 2)} ~ ${num(ov.speed_range[1], 2)}`, 'mm/hr'),
      stat('熔區溫度', `${num(ov.temp_range[0], 1)} ~ ${num(ov.temp_range[1], 1)}`, '°C'),
      stat('純化次數', `${ov.pass_range[0]} ~ ${ov.pass_range[1]}`, 'pass'))));

  return root;
}
