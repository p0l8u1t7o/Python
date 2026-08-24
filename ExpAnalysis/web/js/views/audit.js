/** 資料稽核：異常偵測結果 + 設限處理對照實驗。 */

import { api } from '../api.js';
import { h, card, badge, num, pct, notice, table, spinner, toneForSeverity, stat } from '../ui.js';
import { barChart } from '../charts.js';

export default async function audit() {
  const root = h('div');
  const findings = await api.anomalies();

  const counts = findings.reduce((a, f) => (a[f.severity] = (a[f.severity] || 0) + 1, a), {});
  root.append(h('div', { class: 'grid cols-3', style: 'margin-bottom:18px' },
    stat('高嚴重度', String(counts.high || 0), '建議確認原始紀錄後排除',
      counts.high ? 'bad' : 'good'),
    stat('中嚴重度', String(counts.medium || 0), '值得留意，暫不排除',
      counts.medium ? 'warn' : 'good'),
    stat('低嚴重度', String(counts.low || 0), '僅供參考')));

  root.append(notice('good', '本功能不影響預測準確度',
    '異常偵測不參與任何預測計算，僅將可疑批次標示出來供人工確認。'
    + '其作用是將品質不佳的資料排除於模型之外，僅會保護準確度，不會造成損害。'
    + '被標為高嚴重度的資料會自動從參數映射的訓練集中排除，但原始資料完整保留在資料庫中。'));

  if (!findings.length) {
    root.append(card('稽核結果', null, notice('good', '沒有發現異常',
      '所有批次的殘差、擬合品質與 (v,T) 映射一致性都在門檻內。')));
  } else {
    const items = findings.map((f) => h('div', { class: 'card' },
      h('div', { class: 'card-body' },
        h('div', { class: 'row', style: 'margin-bottom:8px' },
          badge(f.severity.toUpperCase(), toneForSeverity(f.severity)),
          h('strong', {}, `${f.batch_id} · ${f.element}`),
          f.exclude_recommended ? badge('已自動排除於模型訓練', 'warn') : null),
        ...f.reasons.map((r) => h('p', {}, r)),
        f.suggested_action ? h('p', { class: 'muted' }, `建議動作：${f.suggested_action}`) : null,
        h('details', {},
          h('summary', { class: 'muted' }, '偵測指標'),
          h('pre', { class: 'mono muted', style: 'white-space:pre-wrap;font-size:11.5px' },
            JSON.stringify(f.metrics, null, 2))))));
    root.append(card('稽核發現', `共 ${findings.length} 項`, ...items));
  }

  // ── 設限處理對照 ────────────────────────────────────────
  const box = h('div');
  root.append(card('設限資料處理方式的對照實驗',
    '6N 純度下很多測值會是「< 0.05 ppm」。這不是一個數字，是一個不等式。'
    + '把它當成 0 會低估 k_eff（頭端看起來完美），當成 LOD 會高估（頭端看起來偏髒）。'
    + '正確做法是告訴擬合程式「這點的真值在 [0, LOD] 之間」。'
    + '下表為同一份資料、同一模型，僅更換設限處理方式所得的結果。',
    box));
  box.append(spinner('執行對照實驗…'));

  try {
    const cs = await api.censoringStudy();
    box.innerHTML = '';
    const methods = ['tobit', 'as_zero', 'as_lod'];
    const labels = { tobit: 'Tobit（正確）', as_zero: '當成 0', as_lod: '當成 LOD' };
    const els = Object.keys(cs.tobit?.elements || {});
    box.append(table(['元素', ...methods.map((m) => ({ label: labels[m], align: 'right' })),
                      { label: '「當成 0」的偏差', align: 'right' },
                      { label: '「當成 LOD」的偏差', align: 'right' }],
      els.map((el) => {
        const t = cs.tobit.elements[el]?.k_median;
        const z = cs.as_zero.elements[el]?.k_median;
        const l = cs.as_lod.elements[el]?.k_median;
        return { cells: [el,
          { text: num(t), align: 'right' },
          { text: num(z), align: 'right' },
          { text: num(l), align: 'right' },
          { text: t ? `${(((z - t) / t) * 100).toFixed(1)}%` : '—', align: 'right' },
          { text: t ? `${(((l - t) / t) * 100).toFixed(1)}%` : '—', align: 'right' }] };
      })));
    box.append(h('p', { class: 'chart-note', style: 'margin-top:10px' }, cs._note));
  } catch (e) {
    box.innerHTML = '';
    box.append(notice('warn', '對照實驗未執行', e.message));
  }

  return root;
}
