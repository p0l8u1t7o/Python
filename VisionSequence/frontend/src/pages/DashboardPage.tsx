/** 總覽：每個流程一張卡，訂閱全域 SSE 即時更新（stats 由 flowStream 寫進 flows 快取）；
 *  「觀看」開即時監看 Modal——訂該流程的 SSE，外部 API／連續執行觸發的每筆檢測都會即時顯示。 */
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Activity, BarChart3, MonitorPlay, Radio, Workflow } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader, StatusBadge } from '@/components/ui'
import { TrendStrip } from '@/pages/StatsPage'
import { imageUrl } from '@/lib/api'
import { useFlowStream } from '@/lib/flowStream'
import { useCapacity, useFlows, useRecentRuns } from '@/lib/queries'
import type { Flow, RunReport } from '@/lib/types'

function CapacityBar() {
  const { t } = useTranslation()
  const capacity = useCapacity(3000)
  const data = capacity.data
  if (!data) return null
  const pct = data.max_workers ? Math.min(100, (data.active / data.max_workers) * 100) : 0
  const mb = Math.round(data.images.bytes / 1048576)
  return (
    <Card className="mb-4 px-4 py-3">
      <div className="flex items-center justify-between text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <Activity size={14} aria-hidden />
          {t('capacity.label', { active: data.active, max: data.max_workers })}
        </span>
        <span>{t('capacity.images', { images: data.images.images, mb })}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-muted">
        <div className={`h-full rounded-full transition-all ${pct >= 100 ? 'bg-critical' : pct >= 70 ? 'bg-warning' : 'bg-brand'}`} style={{ width: `${pct}%` }} />
      </div>
    </Card>
  )
}

/** run 裡最後一個影像輸出（節點依執行順序寫入 report，倒著找即可）。 */
function lastImage(run: RunReport): { ref: string; width: number; height: number } | null {
  const reports = Object.values(run.nodes)
  for (let i = reports.length - 1; i >= 0; i -= 1) {
    for (const v of Object.values(reports[i].outputs)) {
      if (v && typeof v === 'object' && 'ref' in v && 'width' in v) {
        const r = v as { ref: string | null; width: number; height: number }
        if (r.ref) return { ref: r.ref, width: r.width, height: r.height }
      }
    }
  }
  return null
}

/** 即時監看：訂該流程的 SSE（含輸出），每筆完成的 run 立刻換上最新影像與判定。 */
function FlowLiveMonitor({ flow }: { flow: Flow }) {
  const { t } = useTranslation()
  const [run, setRun] = useState<RunReport | null>(null)
  useFlowStream(flow.id, true, (event) => {
    if (event.type === 'run_finished' && event.run) setRun(event.run)
  })
  const image = run ? lastImage(run) : null
  const overlays = useMemo(() => (run ? Object.values(run.nodes).flatMap((n) => n.overlays ?? []) : []), [run])
  return (
    <div className="space-y-2">
      <div className="flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
        {run ? (
          <>
            <StatusBadge status={run.status} />
            <span className="tnum">{Math.round(run.duration_ms)} ms</span>
            <span>{run.trigger}</span>
            {run.station_id ? <span>{t('dashboard.station')} <code className="font-mono">{run.station_id}</code></span> : null}
            {run.recipe ? <span>{t('dashboard.recipe')} <code className="font-mono">{run.recipe}</code></span> : null}
            <span className="tnum text-subtle">#{run.id.slice(0, 8)}</span>
          </>
        ) : (
          <span className="flex items-center gap-1.5"><span className="size-1.5 animate-pulse rounded-full bg-brand" />{t('dashboard.waitingRun')}</span>
        )}
      </div>
      <div className="h-[62vh] min-h-80">
        {image && run ? (
          <ImageViewer className="h-full w-full" src={imageUrl(image.ref, 1600)} imageWidth={image.width} imageHeight={image.height}
            overlays={overlays} badge={{ text: run.status.toUpperCase(), tone: run.status === 'ok' ? 'ok' : 'ng' }} />
        ) : (
          <div className="flex h-full items-center justify-center rounded-lg bg-viewer text-sm text-white/60">{t('dashboard.waitingRun')}</div>
        )}
      </div>
    </div>
  )
}

function FlowCard({ flow, onWatch }: { flow: Flow; onWatch: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const s = flow.stats
  const recent = useRecentRuns(flow.id)
  const trend = [...(recent.data?.items ?? [])].reverse().map((r) => r.status)
  const latest = recent.data?.items[0]
  const okRate = s.runs ? Math.round((s.ok / s.runs) * 100) : null
  const last = s.last_status
  const lastColor = last === 'ok' ? 'bg-ok' : last === 'ng' ? 'bg-warning' : last === 'failed' ? 'bg-critical' : 'bg-line-strong'
  return (
    <Link to={`/flows/${flow.id}`} className="card flex gap-3 p-4 transition hover:border-brand hover:shadow-md">
      <div className={`w-2 shrink-0 rounded-full ${lastColor}`} title={t('dashboard.lastRun')} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{flow.name}</p>
            <p className="truncate text-xs text-muted">{flow.description || t('dashboard.nodes', { count: flow.node_count })}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {flow.continuous ? (
              <Badge tone="brand">
                <Radio size={11} className="animate-pulse" aria-hidden />
                {t('dashboard.continuous')}
              </Badge>
            ) : null}
            {!flow.is_enabled ? <Badge>{t('common.disabled')}</Badge> : null}
            {flow.commissioned === false ? <Badge tone="warning">{t('dashboard.notCommissioned')}</Badge> : null}
            {/* 卡片本身是 <a>，裡面不能再放 <a>（React 19 會警告 hydration），改用 button 導頁。 */}
            <button type="button" className="btn-icon !p-1" title={t('dashboard.watch')} aria-label={t('dashboard.watch')} onClick={(e) => { e.preventDefault(); e.stopPropagation(); onWatch() }} data-testid="card-watch">
              <MonitorPlay size={14} />
            </button>
            <button type="button" className="btn-icon !p-1" title={t('stats.open')} aria-label={t('stats.open')} onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(`/flows/${flow.id}/stats`) }} data-testid="card-stats">
              <BarChart3 size={14} />
            </button>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-4 gap-2 text-center">
          <div>
            <p className="text-[10px] uppercase text-subtle">{t('dashboard.lastRun')}</p>
            <StatusBadge status={last || null} />
          </div>
          <div>
            <p className="text-[10px] uppercase text-subtle">{t('dashboard.runs')}</p>
            <p className="tnum text-sm font-medium">{s.runs}</p>
            {okRate !== null ? <p className="tnum text-[10px] text-muted">{t('dashboard.okRate')} {okRate}%</p> : null}
          </div>
          <div>
            <p className="text-[10px] uppercase text-subtle">{t('dashboard.avg')}</p>
            <p className="tnum text-sm font-medium">{Math.round(s.avg_ms)} <span className="text-[10px] text-muted">ms</span></p>
          </div>
          <div>
            <p className="text-[10px] uppercase text-subtle">{t('dashboard.max')}</p>
            <p className="tnum text-sm font-medium">{Math.round(s.max_ms)} <span className="text-[10px] text-muted">ms</span></p>
          </div>
        </div>
        {latest?.station_id || latest?.recipe ? (
          <p className="mt-2 flex flex-wrap gap-x-3 text-[10px] text-muted" data-testid="card-meta">
            {latest.station_id ? <span>{t('dashboard.station')} <code className="font-mono">{latest.station_id}</code></span> : null}
            {latest.recipe ? <span>{t('dashboard.recipe')} <code className="font-mono">{latest.recipe}</code></span> : null}
          </p>
        ) : null}
        {trend.length ? <TrendStrip statuses={trend} className="mt-3" /> : null}
      </div>
    </Link>
  )
}

export function DashboardPage() {
  const { t } = useTranslation()
  const flows = useFlows()
  const stream = useFlowStream(null, true)
  const [watching, setWatching] = useState<Flow | null>(null)

  return (
    <Page>
      <PageHeader
        title={t('dashboard.title')}
        description={t('dashboard.subtitle')}
        actions={
          <Badge tone={stream.connected ? 'ok' : 'neutral'}>
            <span className={`size-1.5 rounded-full bg-current ${stream.connected ? 'animate-pulse' : ''}`} />
            {stream.connected ? t('dashboard.live') : t('dashboard.offline')}
          </Badge>
        }
      />
      <CapacityBar />
      {flows.isPending ? (
        <LoadingState />
      ) : flows.isError ? (
        <ErrorState error={flows.error} onRetry={() => void flows.refetch()} />
      ) : flows.data.items.length === 0 ? (
        <EmptyState icon={<Workflow className="size-6" />} title={t('dashboard.empty')} description={t('dashboard.createFirst')} action={<Link to="/flows"><Button variant="primary">{t('flows.create')}</Button></Link>} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {flows.data.items.map((flow) => (
            <FlowCard key={flow.id} flow={flow} onWatch={() => setWatching(flow)} />
          ))}
        </div>
      )}

      <Modal open={watching !== null} onClose={() => setWatching(null)} size="lg" title={t('dashboard.watchTitle', { name: watching?.name ?? '' })}>
        {watching ? <FlowLiveMonitor key={watching.id} flow={watching} /> : null}
      </Modal>
    </Page>
  )
}
