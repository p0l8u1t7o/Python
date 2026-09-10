/** 一次執行的結果：KPI、逐張表（縮圖、期望可改、狀態、命中、輸出、錯誤、檢視）、CSV、存入 Golden Set。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Eye, Gem } from 'lucide-react'

import { Button, SegmentedControl, StatusBadge, Tile } from '@/components/ui'
import { formatValue } from '@/components/editor/ResultsPanel'
import { RUNNING, batchImageUrl, fmtPct, type BatchRun, type BatchRunItem, type BatchSet, type Expected } from '@/lib/batch'
import { batchToCsv, downloadCsv } from '@/lib/batchCsv'

type Filter = 'all' | 'ng' | 'failed' | 'mismatch'

export function BatchRunDetail({ run, set, onLabel, onPreview, onToGolden, canManage }: {
  run: BatchRun
  set: BatchSet
  onLabel: (index: number, expected: Expected) => void
  onPreview: (index: number) => void
  onToGolden: (indexes: number[]) => void
  canManage: boolean
}) {
  const { t } = useTranslation()
  const grouping = (set.images ?? []).map((image) => ({ image, row: run.items?.find((item) => item.index === image.index) }))
  const groupScore = (group: 'tune' | 'accept') => {
    const labeled = grouping.filter(({ image, row }) => (image.group ?? 'tune') === group && image.expected && row)
    return { labeled: labeled.length, matches: labeled.filter(({ row }) => row?.match === true).length }
  }
  const tuning = (run.meta.autotune as { after?: { match: number; total: number } } | undefined)?.after
  const tune = tuning ? { matches: tuning.match, labeled: tuning.total } : groupScore('tune')
  const accept = (run.meta.acceptance as { matches: number; labeled: number } | undefined) ?? groupScore('accept')
  const [filter, setFilter] = useState<Filter>('all')
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const items = run.items ?? []
  const shown = useMemo(() => {
    if (filter === 'ng') return items.filter((it) => it.status === 'ng')
    if (filter === 'failed') return items.filter((it) => it.status !== 'ok' && it.status !== 'ng')
    if (filter === 'mismatch') return items.filter((it) => it.match === false)
    return items
  }, [items, filter])
  const s = run.summary
  const running = RUNNING.has(run.status)
  const yieldPct = s.total ? Math.round(((s.ok ?? 0) / s.total) * 1000) / 10 : null

  return (
    <div className="space-y-3" data-testid="batch-detail">
      <p className="text-xs text-muted" data-testid="batch-group-scores">
        {t('evidence.tune')}: {tune.matches}/{tune.labeled}{' · '}
        {accept.labeled ? `${t('evidence.accept')}: ${accept.matches}/${accept.labeled}` : t('evidence.noAcceptance')}
      </p>
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-8">
        <Tile label={t('batchPage.kpi.total')} value={running ? `${run.progress.done}/${run.progress.total}` : s.total ?? 0} />
        <Tile label={t('batchPage.kpi.ok')} value={s.ok ?? 0} tone="text-ok" />
        <Tile label={t('batchPage.kpi.ng')} value={s.ng ?? 0} tone="text-warning" />
        <Tile label={t('batchPage.kpi.failed')} value={s.failed ?? 0} tone={s.failed ? 'text-critical' : ''} />
        <Tile label={t('batchPage.kpi.yield')} value={yieldPct === null ? '—' : `${yieldPct}%`} />
        <Tile label={t('batchPage.kpi.match')} value={s.labeled ? `${s.match}/${s.labeled}` : '—'} unit={s.labeled ? fmtPct(s.match_rate) : undefined} tone={s.labeled && s.match === s.labeled ? 'text-ok' : ''} />
        <Tile label={t('batchPage.kpi.avg')} value={`${Math.round(s.avg_ms ?? 0)} ms`} />
        <Tile label={t('batchPage.kpi.wall')} value={`${Math.round(s.wall_ms ?? 0)} ms`} />
      </div>
      {run.error ? <p className="rounded bg-critical-soft px-2 py-1 text-xs text-critical">{run.error}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl size="sm" value={filter} onChange={setFilter} options={[
          { value: 'all', label: t('batchPage.filter.all') }, { value: 'ng', label: t('batchPage.filter.ng') },
          { value: 'failed', label: t('batchPage.filter.failed') }, { value: 'mismatch', label: t('batchPage.filter.mismatch') },
        ]} />
        <span className="tnum text-xs text-muted">{shown.length} / {items.length}</span>
        <span className="ml-auto flex items-center gap-1.5">
          <button type="button" className="text-[11px] text-muted hover:underline" onClick={() => setPicked(new Set(shown.map((it) => it.index)))}>{t('batchPage.selectAll')}</button>
          <button type="button" className="text-[11px] text-muted hover:underline" onClick={() => setPicked(new Set())}>{t('batchPage.selectNone')}</button>
          <Button size="xs" icon={<Gem size={12} />} disabled={!canManage || picked.size === 0} title={t('batchPage.toGoldenHint')} onClick={() => onToGolden([...picked])} data-testid="batch-to-golden">{t('batchPage.toGolden')}</Button>
          <Button size="xs" icon={<Download size={12} />} disabled={!items.length} onClick={() => downloadCsv(batchToCsv(items), `batch-${set.name}-${run.id}.csv`)} data-testid="batch-csv">{t('batchPage.exportCsv')}</Button>
        </span>
      </div>
      <div className="max-h-[52vh] overflow-auto rounded-lg border border-line">
        <table className="w-full text-xs" data-testid="batch-table">
          <thead className="sticky top-0 bg-surface-muted text-[10px] uppercase text-subtle">
            <tr>
              <th className="px-2 py-1 text-left font-medium" />
              <th className="px-2 py-1 text-left font-medium">{t('batchPage.cols.thumb')}</th>
              <th className="px-2 py-1 text-left font-medium">{t('batchPage.cols.name')}</th>
              <th className="px-2 py-1 text-left font-medium">{t('batchPage.cols.status')}</th>
              <th className="px-2 py-1 text-left font-medium">{t('batchPage.cols.expected')}</th>
              <th className="px-2 py-1 text-center font-medium">{t('batchPage.cols.match')}</th>
              <th className="px-2 py-1 text-right font-medium">{t('batchPage.cols.ms')}</th>
              <th className="px-2 py-1 text-left font-medium">{t('batchPage.cols.outputs')}</th>
              <th className="px-2 py-1 text-left font-medium">{t('batchPage.cols.error')}</th>
              <th className="px-2 py-1" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {shown.map((it: BatchRunItem) => (
              <tr key={it.index} className={`hover:bg-surface-muted/70 ${it.match === false ? 'bg-critical-soft/30' : ''}`} data-testid="batch-row">
                <td className="px-2 py-1"><input type="checkbox" className="accent-[var(--brand)]" checked={picked.has(it.index)} onChange={(e) => setPicked((old) => { const next = new Set(old); if (e.target.checked) next.add(it.index); else next.delete(it.index); return next })} /></td>
                <td className="px-2 py-1"><img src={batchImageUrl(set.id, it.index, 96)} alt={it.name} className="h-10 w-14 rounded bg-surface-muted object-contain" loading="lazy" /></td>
                <td className="max-w-[160px] truncate px-2 py-1" title={it.name}><span className="tnum text-subtle">#{it.index + 1}</span> {it.name}</td>
                <td className="px-2 py-1"><StatusBadge status={it.status} /></td>
                <td className="px-2 py-1">
                  <select className="input !w-16 !py-0.5 text-[11px]" value={it.expected} disabled={!canManage} onChange={(e) => onLabel(it.index, e.target.value as Expected)} data-testid="batch-expected">
                    <option value="">{t('batchPage.expectNone')}</option>
                    <option value="ok">OK</option>
                    <option value="ng">NG</option>
                  </select>
                </td>
                <td className="px-2 py-1 text-center">{it.match === null ? <span className="text-subtle">—</span> : it.match ? <span className="text-ok">✓</span> : <span className="font-semibold text-critical">✗</span>}</td>
                <td className="tnum px-2 py-1 text-right">{Math.round(it.duration_ms)}</td>
                <td className="max-w-[260px] truncate px-2 py-1 font-mono text-[10px] text-muted" title={JSON.stringify(it.outputs)}>
                  {Object.entries(it.outputs ?? {}).slice(0, 4).map(([k, v]) => `${k}=${formatValue(v)}`).join('  ') || '—'}
                </td>
                <td className="max-w-[200px] truncate px-2 py-1 text-critical" title={it.error}>{it.error ? `${it.error_node ? `[${it.error_node}] ` : ''}${it.error}` : ''}</td>
                <td className="px-2 py-1 text-right"><button type="button" className="btn-icon" title={t('batchPage.previewHint')} onClick={() => onPreview(it.index)} data-testid="batch-row-view"><Eye size={13} /></button></td>
              </tr>
            ))}
            {shown.length === 0 ? <tr><td colSpan={10} className="px-2 py-4 text-center text-muted">{running ? t('batchPage.running', { done: run.progress.done, total: run.progress.total }) : '—'}</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
