/** 影像集清單（左欄）：名稱、所屬流程、張數、標記數、最近一次執行的命中率；可刪除。
 *  影像集是測試資料，可用任一流程測——所以清單跨流程，目前測試流程的排前面。 */
import { useTranslation } from 'react-i18next'
import { Images, Plus, Trash2, Workflow } from 'lucide-react'

import { Badge, Button, StatusBadge } from '@/components/ui'
import { fmtPct, type BatchSet } from '@/lib/batch'

export function BatchSetList({ sets, selectedId, flowId, onSelect, onNew, onDelete, keep }: {
  sets: BatchSet[]
  selectedId: number | null
  /** 目前的測試流程：屬於它的影像集排前面，其他流程的標出流程名稱 */
  flowId: number | null
  onSelect: (id: number) => void
  onNew: () => void
  onDelete: (set: BatchSet) => void
  keep: { sets: number; runs: number }
}) {
  const { t } = useTranslation()
  const ordered = [...sets].sort((a, b) => Number(b.flow_id === flowId) - Number(a.flow_id === flowId))
  return (
    <div className="space-y-2" data-testid="batch-sets">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-xs font-semibold"><Images size={13} className="text-brand" /> {t('batchPage.sets')} <span className="tnum font-normal text-muted">({sets.length})</span></p>
        <Button size="xs" variant="primary" icon={<Plus size={12} />} onClick={onNew} data-testid="batch-new-set">{t('batchPage.newSet')}</Button>
      </div>
      {sets.length === 0 ? <p className="sr-only" data-testid="batch-no-sets">{t('batchPage.noSets')}</p> : null}
      <ul className="space-y-1.5">
        {ordered.map((s) => {
          const latest = s.latest_run
          return (
            <li key={s.id}>
              <div role="button" tabIndex={0} onClick={() => onSelect(s.id)} onKeyDown={(e) => { if (e.key === 'Enter') onSelect(s.id) }}
                className={`group cursor-pointer rounded-lg border px-2.5 py-2 text-xs ${s.id === selectedId ? 'border-brand bg-brand-soft/40' : 'border-line hover:bg-surface-muted/70'}`} data-testid="batch-set-row">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-medium" title={s.name}>{s.name}</span>
                  <button type="button" className="btn-icon text-critical opacity-0 group-hover:opacity-100" aria-label={t('common.delete')} onClick={(e) => { e.stopPropagation(); onDelete(s) }}><Trash2 size={13} /></button>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                  {s.flow_id !== flowId ? <Badge tone="info" title={t('batchPage.setFlowHint')}><Workflow size={10} aria-hidden />{s.flow_name}</Badge> : null}
                  <span className="tnum">{t('batchPage.images', { count: s.image_count })}</span>
                  <span className="tnum">{t('batchPage.labeled', { ok: s.labeled.ok, ng: s.labeled.ng })}</span>
                  {latest ? <StatusBadge status={latest.status === 'done' ? (latest.summary.failed ? 'failed' : 'ok') : latest.status} /> : null}
                  {latest?.summary.labeled ? <Badge tone="brand">{t('batchPage.kpi.match')} {fmtPct(latest.summary.match_rate)}</Badge> : null}
                </div>
              </div>
            </li>
          )
        })}
      </ul>
      <p className="text-[10px] text-subtle">{t('batchPage.anyFlowHint')}</p>
      <p className="text-[10px] text-subtle">{t('batchPage.keepHint', { sets: keep.sets, runs: keep.runs })}</p>
    </div>
  )
}
