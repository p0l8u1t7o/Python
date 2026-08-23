/** 參數映射：GP 灰帶圖 + BPS 線性化檢查。這是取信於工程師的關鍵畫面。 */

import { api } from '../api.js';
import { h, card, table, badge, num, notice, chartBox, stat } from '../ui.js';
import { bandChart, PALETTE } from '../charts.js';

let current = null;
let mode = 'k';   // 'k' = k_eff vs v；'z' = 線性化檢查

export default async function mapping() {
  const data = await api.mapping();
  const els = data.elements || [];
  if (!els.length) {
    return h('div', {}, notice('warn', '尚未建立映射模型',
      '需要至少 2 個不同速率的批次才能擬合。請先匯入或產生資料。'));
  }
  if (!current || !els.includes(current)) current = els[0];

  const root = h('div');
  for (const w of data.warnings || []) root.append(notice('warn', '模型提示', w));

  const chips = h('div', { class: 'chips', style: 'margin-bottom:14px' },
    ...els.map((el) => h('button', {
      class: `chip ${el === current ? 'active' : ''}`,
      onclick: () => { current = el; rerender(); },
    }, el)),
    h('span', { style: 'flex:1' }),
    h('button', {
      class: `chip ${mode === 'k' ? 'active' : ''}`,
      onclick: () => { mode = 'k'; rerender(); },
    }, 'k_eff vs 速率'),
    h('button', {
      class: `chip ${mode === 'z' ? 'active' : ''}`,
      onclick: () => { mode = 'z'; rerender(); },
    }, 'BPS 線性化檢查'));

  const body = h('div');
  root.append(chips, body);

  function rerender() {
    root.querySelectorAll('.chip').forEach((c) => {
      const t = c.textContent;
      c.classList.toggle('active',
        t === current || (t === 'k_eff vs 速率' && mode === 'k')
        || (t === 'BPS 線性化檢查' && mode === 'z'));
    });
    renderModel(body, data.models[current], current);
  }
  rerender();
  return root;
}

function renderModel(host, m, el) {
  host.innerHTML = '';
  const bps = m.bps || {};
  const colors = PALETTE();

  host.append(h('div', { class: 'grid cols-4', style: 'margin-bottom:16px' },
    stat('k₀（平衡分配係數）', num(bps.k0),
      '速率趨近 0 時的理論最佳值'),
    stat('δ/D（斜率）', num(bps.delta_over_d, 4),
      `hr/mm，標準誤 ${num(bps.slope_se, 4)}。數字越大代表速率影響越劇烈`,
      bps.delta_over_d > 0.3 ? 'warn' : 'ok'),
    stat('R²', num(bps.r2, 3),
      `${bps.n_points} 個批次`,
      bps.r2 > 0.85 ? 'good' : bps.r2 > 0.5 ? 'warn' : 'bad'),
    stat('映射模型', m.gp_used ? '高斯過程' : 'BPS 線性',
      m.gp_used ? '以 BPS 直線為均值函數，GP 只學殘差' : '批次數不足，未啟用 GP',
      m.gp_used ? 'ok' : 'neutral')));

  if (bps.linearity_note) {
    host.append(notice('warn', '線性假設檢查', bps.linearity_note));
  }

  const box = chartBox(
    mode === 'k'
      ? `${el}：k_eff 隨熔區移動速率的變化（溫度固定在 ${num(m.temp_used, 1)} °C）`
      : `${el}：BPS 線性化 — ln(1/k_eff − 1) 對速率應為直線`,
    mode === 'k'
      ? '陰影是 95% 不確定區間。它會在有資料的地方收窄、在沒資料的地方張開——'
        + '這正是「模型知道自己哪裡不知道」。斜線底紋區域代表超出歷史批次涵蓋範圍，屬外插。'
      : '依 BPS 理論，ln(1/k_eff − 1) = ln(1/k₀ − 1) − (δ/D)·v 對速率是一次式。'
        + '散點若明顯不成直線，代表有 BPS 以外的機制在作用（氧化夾帶、對流不穩、'
        + '取樣位置不一致、或量測不確定度大於製程效應）——這個發現本身就有價值，'
        + '不該硬套模型。');
  host.append(card(mode === 'k' ? '製程參數 → 純化效率' : '物理模型的誠實度檢查', null, box));

  const pts = m.points.map((p) => ({
    x: p.speed_mm_hr,
    y: mode === 'k' ? p.k_eff : p.z,
    lo: mode === 'k' ? p.k_lo : null,
    hi: mode === 'k' ? p.k_hi : null,
    label: `${p.batch_id}（${num(p.temp_c, 1)} °C）`,
  }));

  bandChart(box.host, {
    height: 380,
    x: m.v_curve,
    y: mode === 'k' ? m.k_curve : m.z_curve,
    lo: mode === 'k' ? m.k_lo : m.z_curve.map((z, i) => z - 1.96 * m.z_std[i]),
    hi: mode === 'k' ? m.k_hi : m.z_curve.map((z, i) => z + 1.96 * m.z_std[i]),
    baseline: mode === 'z' ? bpsLine(m) : null,
    points: pts,
    observedRange: m.v_range_observed,
    color: colors[0],
    clampY: mode === 'k' ? [0, 1] : null,
    xLabel: '熔區移動速率 v (mm/hr)',
    yLabel: mode === 'k' ? 'k_eff' : 'ln(1/k_eff − 1)',
    seriesLabel: m.gp_used ? '高斯過程預測' : 'BPS 線性預測',
  });

  host.append(card('這對製程代表什麼',
    null,
    h('div', { class: 'grid cols-2' },
      h('div', {},
        h('h4', {}, '核心取捨：慢 = 純，快 = 產能'),
        h('p', {}, '凝固介面把雜質吐回液體，這些雜質要靠擴散散進整個液池。'
          + '凝固太快時雜質來不及散開，在介面前堆成一層高濃度邊界層，'
          + `使得實際感受到的 k_eff 變大、純化變差。${el} 的 δ/D = `
          + `${num(bps.delta_over_d, 3)} hr/mm 就是在量化這個效應的強度。`),
        h('p', {}, '這條曲線上的甜蜜點，就是客戶需求三（參數最佳化建議）的答案來源。')),
      h('div', {},
        h('h4', {}, '溫度為什麼是代理變數'),
        h('p', {}, '溫度不是獨立的物理變數。它透過兩條路徑影響結果：'
          + '(1) 溫度高 → 熔區變長 l → 曲線形狀改變；'
          + '(2) 溫度高 → 液池對流變強 → 邊界層變薄 → k_eff 變好。'),
        h('p', {}, '真正的物理變數是熔區長度 l。若客戶尚未實測 l，'
          + '這是整個專案投報率最高的補量測項目——量到 l 就不需要靠溫度推。')))));

  host.append(card('各批次擬合值',
    '按速率排序。k_eff 越低越好。',
    table(['批次', { label: '速率 mm/hr', align: 'right' },
           { label: '溫度 °C', align: 'right' },
           { label: 'k_eff', align: 'right' },
           { label: '95% 區間', align: 'right' },
           { label: 'ln(1/k−1)', align: 'right' }],
      [...m.points].sort((a, b) => a.speed_mm_hr - b.speed_mm_hr).map((p) => ({
        cells: [p.batch_id,
          { text: num(p.speed_mm_hr, 2), align: 'right' },
          { text: num(p.temp_c, 1), align: 'right' },
          { text: num(p.k_eff), align: 'right' },
          { text: p.k_lo != null ? `${num(p.k_lo)} ~ ${num(p.k_hi)}` : '—', align: 'right' },
          { text: num(p.z, 3), align: 'right' }],
      })))));
}

/** 純 BPS 直線（不含 GP 修正），作為線性化圖的基準線。 */
function bpsLine(m) {
  const b = m.bps || {};
  const intercept = Math.log(1 / Math.max(Math.min(b.k0, 0.9999), 1e-6) - 1);
  return m.v_curve.map((v) => intercept - (b.delta_over_d || 0) * v);
}
