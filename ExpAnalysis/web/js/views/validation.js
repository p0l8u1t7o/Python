/** 模型驗證：留一批交叉驗證 = 驗收文件。 */

import { api } from '../api.js';
import { h, card, stat, badge, num, notice, table, chartBox } from '../ui.js';
import { barChart, lineChart } from '../charts.js';

export default async function validation() {
  const root = h('div');
  const res = await api.validation();

  root.append(notice('good', '將「不影響準確性」化為可驗收的條件',
    '「不影響準確性」的要求應轉化為可量化、可驗收的條件，'
    + '而非口頭承諾。下表即為驗收依據。'));

  if (!res.n_points) {
    root.append(card('留一批交叉驗證', null,
      notice('warn', '無法執行', res.verdict || '批次數不足。'),
      ...(res.notes || []).map((n) => h('p', { class: 'muted' }, n))));
    return root;
  }

  const better = res.ai_better && res.improvement_pct >= 3;
  root.append(h('div', { class: 'grid cols-4', style: 'margin-bottom:18px' },
    stat('交叉驗證折數', `${res.n_batches} 折`, `${res.n_points} 個未設限測點`),
    stat('純物理 MAE', `${num(res.physics_mae_ppm, 4)} ppm`, '平均絕對誤差'),
    // 後端的 SafeJSONResponse 會把 NaN 消毒成 null，所以這裡要檢查 null
    // 而不是 Number.isNaN（Number.isNaN(null) 恆為 false）
    stat('物理 + AI MAE',
      res.ai_mae_ppm == null ? '未訓練' : `${num(res.ai_mae_ppm, 4)} ppm`,
      Number.isFinite(res.improvement_pct) ? `改善 ${res.improvement_pct.toFixed(1)}%` : '',
      better ? 'good' : 'warn'),
    stat('上線門檻', res.gate_passed ? '通過' : '未通過',
      res.gate_passed ? 'AI 修正已啟用' : '本階段只交付純物理模型',
      res.gate_passed ? 'good' : 'neutral')));

  root.append(card('驗收判定', null,
    h('p', {}, res.verdict),
    h('p', { class: 'muted' },
      'AI 模組僅在經驗證優於純物理模型時才會啟用。此規則從根本上排除「AI 使結果變差」的風險，'
      + '是本系統對準確性最明確的保證。')));

  root.append(card('誤差比較',
    'MAE = 平均絕對誤差（ppm，越小越好）。同一份資料、同一組折，只差在有沒有套 AI 修正。',
    table(['指標', { label: '純物理', align: 'right' },
           { label: '物理 + AI', align: 'right' }, { label: '差異', align: 'right' }],
      [
        ['平均絕對誤差 (ppm)', res.physics_mae_ppm, res.ai_mae_ppm],
        ['最大誤差 (ppm)', res.physics_max_ppm, res.ai_max_ppm],
        ['對數空間平均誤差', res.physics_mae_log, res.ai_mae_log],
      ].map(([label, p, a]) => ({
        cells: [label,
          { text: num(p, 4), align: 'right' },
          { text: a == null ? '未訓練' : num(a, 4), align: 'right' },
          { node: (a != null && Number.isFinite(a))
              ? badge(`${(((a - p) / p) * 100).toFixed(1)}%`, a < p ? 'good' : 'bad')
              : h('span', { class: 'muted' }, '—'), align: 'right' }],
      })))));

  // ── 各元素 ──────────────────────────────────────────────
  const elBox = chartBox('各元素的預測誤差（純物理）',
    '誤差偏高的元素通常有兩種原因：k_eff 接近 1（訊號本身就弱），'
    + '或該元素的測點大量落在檢測極限以下。');
  root.append(card('分元素檢視', null,
    table(['元素', { label: '純物理 MAE (ppm)', align: 'right' },
           { label: '物理 + AI MAE', align: 'right' },
           { label: '測點數', align: 'right' }],
      Object.entries(res.per_element || {}).map(([el, v]) => ({
        cells: [el,
          { text: num(v.physics_mae_ppm, 4), align: 'right' },
          { text: v.ai_mae_ppm == null ? '—' : num(v.ai_mae_ppm, 4), align: 'right' },
          { text: String(v.n_points), align: 'right' }],
      }))),
    elBox));
  barChart(elBox.host, {
    labelWidth: 56, xLabel: '平均絕對誤差 (ppm)',
    items: Object.entries(res.per_element || {}).map(([el, v]) => ({
      label: el, value: v.physics_mae_ppm, text: `${num(v.physics_mae_ppm, 4)} ppm`,
    })),
  });

  // ── 逐批 ────────────────────────────────────────────────
  const bBox = chartBox('逐批誤差',
    '每一點是「把這一批完全留出、用其他批訓練後再預測」的誤差。'
    + '若某批誤差特別高，通常和資料稽核標記的批次是同一批。');
  root.append(card('逐批交叉驗證結果', null,
    table(['批次', { label: '速率', align: 'right' }, { label: '溫度', align: 'right' },
           { label: '次數', align: 'right' }, { label: '測點', align: 'right' },
           { label: '純物理 MAE', align: 'right' }, { label: '最大誤差', align: 'right' }],
      res.per_batch.map((b) => ({
        cells: [b.batch_id,
          { text: num(b.speed_mm_hr, 2), align: 'right' },
          { text: num(b.temp_c, 1), align: 'right' },
          { text: String(b.n_passes), align: 'right' },
          { text: String(b.n_points), align: 'right' },
          { text: num(b.physics_mae_ppm, 4), align: 'right' },
          { text: num(b.physics_max_ppm, 4), align: 'right' }],
      }))),
    bBox));
  lineChart(bBox.host, {
    height: 240,
    xLabel: '批次序號', yLabel: '平均絕對誤差 (ppm)',
    series: [{ label: '純物理', color: 'var(--c1)',
      points: res.per_batch.map((b, i) => [i + 1, b.physics_mae_ppm]) },
      ...(res.per_batch.some((b) => b.ai_mae_ppm != null && Number.isFinite(b.ai_mae_ppm))
        ? [{ label: '物理 + AI', color: 'var(--c4)', dash: '5 4',
            points: res.per_batch.map((b, i) => [i + 1, b.ai_mae_ppm || 0]) }] : [])],
  });

  root.append(card('建議寫進合約的驗收條件',
    '這四條把責任邊界與品質保證同時講清楚。',
    h('ol', { style: 'padding-left:20px;line-height:1.9' },
      h('li', {}, 'AI 模組之預測誤差不得高於純物理模型基準（以留一批交叉驗證衡量）。'),
      h('li', {}, '所有預測同時提供物理基準值與不確定區間。'),
      h('li', {}, '超出訓練資料範圍之查詢，系統自動退回純物理模式並標示警告。'),
      h('li', {}, 'AI 不參與任何設備控制決策；本系統為離線決策輔助工具。')),
    ...(res.notes || []).map((n) => h('p', { class: 'muted' }, n))));

  return root;
}
