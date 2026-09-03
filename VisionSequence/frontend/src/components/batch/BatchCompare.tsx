/** 比較兩次執行：逐張狀態變化、命中變化、輸出差異、參數差異。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Badge, Checkbox, StatusBadge, Tile } from '@/components/ui'
import { formatValue } from '@/components/editor/ResultsPanel'
import { batchImageUrl, type BatchCompare as Compare } from '@/lib/batch'
import { runTitle } from './BatchRunList'

export function BatchComparePanel({ compare, onPreview }: { compare: Compare | null; onPreview: (index: number) => void }) {
  const { t } = useTranslation()
  const [onlyChanged, setOnlyChanged] = useState(true)
  const rows = useMemo(() => (compare ? compare.rows.filter((r) => !onlyChanged || r.changed || r.a_match !== r.b_match) : []), [compare, onlyChanged])
  if (!compare) return <p className="text-xs text-muted" data-testid="batch-compare-empty">{t('batchPage.compare.hint')}</p>
  const s = compare.summary
  return (
    <div className="space-y-3" data-testid="batch-compare">
      <p className="text-xs text-muted">{t('batchPage.compare.a')}：<b>{runTitle(compare.a)}</b>　{t('batchPage.compare.b')}：<b>{runTitle(compare.b)}</b></p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Tile label={t('batchPage.compare.changed')} value={s.changed} />
        <Tile label={t('batchPage.compare.improved')} value={s.improved} tone="text-ok" />
        <Tile label={t('batchPage.compare.regressed')} value={s.regressed} tone={s.regressed ? 'text-critical' : ''} />
        <Tile label={t('batchPage.compare.same')} value={s.same} />
        <Tile label={t('batchPage.kpi.match')} value={s.labeled ? `${s.a_match ?? 0} → ${s.b_match ?? 0}` : '—'} unit={s.labeled ? `/ ${s.labeled}` : undefined} />
      </div>
      {compare.param_diff.rows.length || compare.param_diff.added.length || compare.param_diff.removed.length ? (
        <p className="rounded-lg border border-line px-2 py-1.5 font-mono text-[11px] text-muted">
          {t('batchPage.insights.paramDiff')}：{compare.param_diff.rows.map((r) => `${r.label}.${r.key} ${String(r.from)} → ${String(r.to)}`).join('；') || '—'}
          {compare.param_diff.added.length ? `　+${compare.param_diff.added.join(', ')}` : ''}{compare.param_diff.removed.length ? `　−${compare.param_diff.removed.join(', ')}` : ''}
        </p>
      ) : <p className="text-[11px] text-subtle">{t('batchPage.compare.sameParams')}</p>}
      <Checkbox label={t('batchPage.compare.onlyChanged')} checked={onlyChanged} onChange={setOnlyChanged} />
      <div className="max-h-[50vh] overflow-auto rounded-lg border border-line">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-surface-muted text-[10px] uppercase text-subtle"><tr>
            <th className="px-2 py-1 text-left font-medium">{t('batchPage.cols.thumb')}</th><th className="px-2 py-1 text-left font-medium">{t('batchPage.cols.name')}</th>
            <th className="px-2 py-1 text-left font-medium">{t('batchPage.cols.expected')}</th><th className="px-2 py-1 text-left font-medium">{t('batchPage.compare.a')}</th>
            <th className="px-2 py-1 text-left font-medium">{t('batchPage.compare.b')}</th><th className="px-2 py-1 text-left font-medium">{t('batchPage.cols.outputs')}</th>
          </tr></thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr key={r.index} className={`cursor-pointer hover:bg-surface-muted/70 ${r.a_match === true && r.b_match === false ? 'bg-critical-soft/30' : r.a_match === false && r.b_match === true ? 'bg-ok-soft/30' : ''}`} onClick={() => onPreview(r.index)}>
                <td className="px-2 py-1"><img src={batchImageUrl(compare.a.set_id, r.index, 96)} alt={r.name} className="h-10 w-14 rounded bg-surface-muted object-contain" loading="lazy" /></td>
                <td className="max-w-[160px] truncate px-2 py-1"><span className="tnum text-subtle">#{r.index + 1}</span> {r.name}</td>
                <td className="px-2 py-1">{r.expected ? <Badge>{r.expected.toUpperCase()}</Badge> : '—'}</td>
                <td className="px-2 py-1"><StatusBadge status={r.a_status} />{r.a_match === false ? <span className="ml-1 text-critical">✗</span> : r.a_match ? <span className="ml-1 text-ok">✓</span> : null}</td>
                <td className="px-2 py-1"><StatusBadge status={r.b_status} />{r.b_match === false ? <span className="ml-1 text-critical">✗</span> : r.b_match ? <span className="ml-1 text-ok">✓</span> : null}</td>
                <td className="max-w-[320px] truncate px-2 py-1 font-mono text-[10px] text-muted">
                  {[...new Set([...Object.keys(r.a_outputs), ...Object.keys(r.b_outputs)])].slice(0, 4).map((k) => `${k}: ${formatValue(r.a_outputs[k])} → ${formatValue(r.b_outputs[k])}`).join('  ') || '—'}
                </td>
              </tr>
            ))}
            {rows.length === 0 ? <tr><td colSpan={6} className="px-2 py-4 text-center text-muted">—</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
