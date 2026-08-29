/** 總覽：每個流程一張卡，訂閱全域 SSE 即時更新（stats 由 flowStream 寫進 flows 快取）。 */
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Activity, BarChart3, Radio, Workflow } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '@/components/ui'
import { TrendStrip } from '@/pages/StatsPage'
import { useFlowStream } from '@/lib/flowStream'
import { useCapacity, useFlows, useRecentRuns } from '@/lib/queries'
import type { Flow } from '@/lib/types'

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

function FlowCard({ flow }: { flow: Flow }) {
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
            <FlowCard key={flow.id} flow={flow} />
          ))}
        </div>
      )}
    </Page>
  )
}
