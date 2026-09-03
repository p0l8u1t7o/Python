/** 執行紀錄（左欄下半）：每次執行的來源、狀態／進度、OK／NG／失敗、命中率；可中斷、刪除、勾選比較。 */
import { useTranslation } from 'react-i18next'
import { GitCompare, History, Square, Trash2 } from 'lucide-react'

import { Badge, type Tone } from '@/components/ui'
import { RUNNING, fmtPct, type BatchRun } from '@/lib/batch'

const ORIGIN_TONE: Record<string, Tone> = { manual: 'neutral', draft: 'info', autotune: 'brand', ai_tune: 'brand' }
const STATUS_TONE: Record<string, Tone> = { queued: 'neutral', running: 'brand', done: 'ok', cancelled: 'warning', failed: 'critical' }

export function runTitle(run: BatchRun): string {
  return run.label || `#${run.id}`
}

export function BatchRunList({ runs, selectedId, onSelect, compareId, onCompare, onCancel, onDelete }: {
  runs: BatchRun[]
  selectedId: number | null
  onSelect: (id: number) => void
  compareId: number | null
  onCompare: (id: number | null) => void
  onCancel: (id: number) => void
  onDelete: (run: BatchRun) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="space-y-2" data-testid="batch-runs">
      <p className="flex items-center gap-1.5 text-xs font-semibold"><History size={13} className="text-brand" /> {t('batchPage.runs')} <span className="tnum font-normal text-muted">({runs.length})</span></p>
      {runs.length === 0 ? <p className="rounded-lg border border-dashed border-line p-3 text-xs text-muted">{t('batchPage.noRuns')}</p> : null}
      <ul className="space-y-1.5">
        {runs.map((r) => {
          const running = RUNNING.has(r.status)
          const s = r.summary
          const pct = r.progress.total ? Math.round((r.progress.done / r.progress.total) * 100) : 0
          return (
            <li key={r.id}>
              <div role="button" tabIndex={0} onClick={() => onSelect(r.id)} onKeyDown={(e) => { if (e.key === 'Enter') onSelect(r.id) }}
                className={`group cursor-pointer rounded-lg border px-2.5 py-2 text-xs ${r.id === selectedId ? 'border-brand bg-brand-soft/40' : compareId === r.id ? 'border-warning/60 bg-warning-soft/40' : 'border-line hover:bg-surface-muted/70'}`} data-testid="batch-run-row">
                <div className="flex items-center gap-1.5">
                  <span className="min-w-0 flex-1 truncate font-medium" title={runTitle(r)}>{runTitle(r)}</span>
                  <Badge tone={ORIGIN_TONE[r.origin] ?? 'neutral'}>{t(`batchPage.origin.${r.origin}`)}</Badge>
                  <Badge tone={STATUS_TONE[r.status] ?? 'neutral'}>{t(`batchPage.status.${r.status}`)}</Badge>
                </div>
                {running ? (
                  <div className="mt-1.5 flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded bg-surface-muted"><div className="h-full bg-brand transition-all" style={{ width: `${pct}%` }} /></div>
                    <span className="tnum text-[11px] text-muted">{t('batchPage.running', { done: r.progress.done, total: r.progress.total })}</span>
                    <button type="button" className="btn-icon text-critical" title={t('batchPage.cancel')} onClick={(e) => { e.stopPropagation(); onCancel(r.id) }} data-testid="batch-run-cancel"><Square size={12} /></button>
                  </div>
                ) : (
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                    <span className="tnum"><b className="text-ok">{s.ok ?? 0}</b> / <b className="text-warning">{s.ng ?? 0}</b> / <b className="text-critical">{s.failed ?? 0}</b></span>
                    {s.labeled ? <span className="tnum">{t('batchPage.kpi.match')} {fmtPct(s.match_rate)}</span> : null}
                    <span className="tnum">{r.created_at ? new Date(r.created_at).toLocaleString() : ''}</span>
                    <span className="ml-auto flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
                      {r.status === 'done' && r.id !== selectedId ? (
                        <button type="button" className={`btn-icon ${compareId === r.id ? 'text-warning' : ''}`} title={compareId === r.id ? t('batchPage.clearCompare') : t('batchPage.compareWith')} onClick={(e) => { e.stopPropagation(); onCompare(compareId === r.id ? null : r.id) }} data-testid="batch-run-compare"><GitCompare size={12} /></button>
                      ) : null}
                      <button type="button" className="btn-icon text-critical" aria-label={t('common.delete')} onClick={(e) => { e.stopPropagation(); onDelete(r) }}><Trash2 size={12} /></button>
                    </span>
                  </div>
                )}
                {r.progress.stage ? <p className="mt-1 text-[11px] text-brand">{r.progress.stage}</p> : null}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
