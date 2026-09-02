/** 總覽：左欄＝流程卡垂直清單（點卡＝選擇觀看，不再跳編輯器；編輯器／統計改小圖示鈕）＋
 *  即時檢測資訊；中央＝選中流程的即時影像。訂該流程 SSE（含輸出），外部 API／連續執行
 *  觸發的每筆檢測完成立即更新。全域 SSE 照樣把 stats 寫進 flows 快取（卡片數字即時）。 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Activity, BarChart3, MonitorPlay, Pencil, Radio, Workflow } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { Badge, Button, Card, EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '@/components/ui'
import { TrendStrip } from '@/pages/StatsPage'
import { api, imageUrl } from '@/lib/api'
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
  for (const skipThru of [true, false]) {
    for (let i = reports.length - 1; i >= 0; i -= 1) {
      for (const [key, v] of Object.entries(reports[i].outputs)) {
        if (skipThru && key === '_image') continue // 優先真正的輸出；只剩直通才用
        if (v && typeof v === 'object' && 'ref' in v && 'width' in v) {
          const r = v as { ref: string | null; width: number; height: number }
          if (r.ref) return { ref: r.ref, width: r.width, height: r.height }
        }
      }
    }
  }
  return null
}

/** 中央即時影像：訂該流程的 SSE（含輸出），每筆完成的 run 立刻換上最新影像；資訊交給左欄。 */
function FlowLiveMonitor({ flow, onRun }: { flow: Flow; onRun: (run: RunReport) => void }) {
  const { t } = useTranslation()
  const [run, setRun] = useState<RunReport | null>(null)
  const runRef = useRef(run)
  runRef.current = run
  const onRunRef = useRef(onRun)
  onRunRef.current = onRun
  useFlowStream(flow.id, true, (event) => {
    if (event.type === 'run_finished' && event.run) {
      setRun(event.run)
      onRun(event.run)
    }
  })
  // 沒有事件之前，先顯示最後一次執行結果（引擎記憶體的 recent；網頁試跑也算）
  useEffect(() => {
    let cancelled = false
    void api.get<{ items: RunReport[] }>(`/vision/flows/${flow.id}/recent`, { limit: 1 })
      .then((r) => {
        if (!cancelled && !runRef.current && r.items[0]) {
          setRun(r.items[0])
          onRunRef.current(r.items[0])
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [flow.id])
  const image = run ? lastImage(run) : null
  const overlays = useMemo(() => (run ? Object.values(run.nodes).flatMap((n) => n.overlays ?? []) : []), [run])
  if (!image || !run) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg bg-viewer text-sm text-white/60">
        <span className="flex items-center gap-2"><span className="size-1.5 animate-pulse rounded-full bg-brand" />{t('dashboard.waitingRun')}</span>
      </div>
    )
  }
  return (
    <ImageViewer className="h-full w-full" src={imageUrl(image.ref, 1600)} imageWidth={image.width} imageHeight={image.height}
      overlays={overlays} badge={{ text: run.status.toUpperCase(), tone: run.status === 'ok' ? 'ok' : 'ng' }} />
  )
}

/** 左欄：即時檢測資訊（最新一筆 run 的判定／耗時／來源／具名輸出）。 */
function LiveInfo({ run }: { run: RunReport | null }) {
  const { t } = useTranslation()
  return (
    <Card className="p-3">
      <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-heading"><MonitorPlay size={13} className="text-brand" />{t('dashboard.liveInfo')}</p>
      {run ? (
        <div className="space-y-1.5 text-xs text-muted">
          <div className="flex items-center gap-2">
            <StatusBadge status={run.status} />
            <span className="tnum">{Math.round(run.duration_ms)} ms</span>
            <span>{run.trigger}</span>
            <span className="tnum ml-auto text-subtle">#{run.id.slice(0, 8)}</span>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5">
            {run.station_id ? <span>{t('dashboard.station')} <code className="font-mono">{run.station_id}</code></span> : null}
            {run.recipe ? <span>{t('dashboard.recipe')} <code className="font-mono">{run.recipe}</code></span> : null}
          </div>
          {Object.keys(run.outputs).length ? (
            <div className="rounded-md border border-line px-2 py-1.5">
              {Object.entries(run.outputs).map(([k, v]) => (
                <p key={k} className="flex justify-between gap-2"><span className="truncate">{k}</span><span className="tnum shrink-0 font-medium text-content">{String(v)}</span></p>
              ))}
            </div>
          ) : null}
          {run.warnings?.length ? <p className="text-warning">{run.warnings.join('；')}</p> : null}
        </div>
      ) : (
        <p className="flex items-center gap-1.5 text-xs text-subtle"><span className="size-1.5 animate-pulse rounded-full bg-brand" />{t('dashboard.waitingRun')}</p>
      )}
    </Card>
  )
}

/** 左欄流程卡（窄版）：點卡＝選擇觀看；編輯器與統計改成小圖示鈕。 */
function FlowCard({ flow, selected, onSelect }: { flow: Flow; selected: boolean; onSelect: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const s = flow.stats
  const recent = useRecentRuns(flow.id)
  const trend = [...(recent.data?.items ?? [])].reverse().map((r) => r.status)
  const okRate = s.runs ? Math.round((s.ok / s.runs) * 100) : null
  const last = s.last_status
  const lastColor = last === 'ok' ? 'bg-ok' : last === 'ng' ? 'bg-warning' : last === 'failed' ? 'bg-critical' : 'bg-line-strong'
  return (
    <button type="button" onClick={onSelect} aria-pressed={selected} data-testid={`dash-flow-${flow.id}`}
      className={`card flex w-full gap-2.5 p-3 text-left transition ${selected ? '!border-brand ring-2 ring-brand/30' : 'hover:border-brand/60'}`}>
      <div className={`w-1.5 shrink-0 rounded-full ${lastColor}`} title={t('dashboard.lastRun')} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <p className="min-w-0 flex-1 truncate text-sm font-semibold">{flow.name}</p>
          {flow.continuous ? <Badge tone="brand"><Radio size={11} className="animate-pulse" aria-hidden />{t('dashboard.continuous')}</Badge> : null}
          {!flow.is_enabled ? <Badge>{t('common.disabled')}</Badge> : null}
          <span role="button" tabIndex={0} className="btn-icon !p-1" title={t('dashboard.openEditor')} aria-label={t('dashboard.openEditor')}
            onClick={(e) => { e.stopPropagation(); navigate(`/flows/${flow.id}`) }}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); navigate(`/flows/${flow.id}`) } }} data-testid="card-edit">
            <Pencil size={13} />
          </span>
          <span role="button" tabIndex={0} className="btn-icon !p-1" title={t('stats.open')} aria-label={t('stats.open')}
            onClick={(e) => { e.stopPropagation(); navigate(`/flows/${flow.id}/stats`) }}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); navigate(`/flows/${flow.id}/stats`) } }} data-testid="card-stats">
            <BarChart3 size={13} />
          </span>
        </div>
        <div className="mt-1.5 flex items-center gap-3 text-[11px] text-muted">
          <StatusBadge status={last || null} />
          <span className="tnum">{s.runs} {t('dashboard.runs')}</span>
          {okRate !== null ? <span className="tnum">{t('dashboard.okRate')} {okRate}%</span> : null}
          <span className="tnum ml-auto">{Math.round(s.avg_ms)} ms</span>
        </div>
        {trend.length ? <TrendStrip statuses={trend} className="mt-2" /> : null}
      </div>
    </button>
  )
}

export function DashboardPage() {
  const { t } = useTranslation()
  const flows = useFlows()
  const stream = useFlowStream(null, true)
  const [watchingId, setWatchingId] = useState<number | null>(null)
  const [lastRun, setLastRun] = useState<RunReport | null>(null)
  const items = flows.data?.items ?? []
  const watching = items.find((f) => f.id === watchingId) ?? null

  // 預設選第一個流程（優先連續執行中的——最可能是正在被外部呼叫的那個）
  useEffect(() => {
    if (watchingId === null && items.length) setWatchingId((items.find((f) => f.continuous) ?? items[0]).id)
  }, [watchingId, items])

  // 換流程時清掉上一個流程的 run 資訊
  useEffect(() => {
    setLastRun(null)
  }, [watchingId])

  return (
    <Page wide>
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
      ) : items.length === 0 ? (
        <EmptyState icon={<Workflow className="size-6" />} title={t('dashboard.empty')} description={t('dashboard.createFirst')} action={<Link to="/flows"><Button variant="primary">{t('flows.create')}</Button></Link>} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)_300px]">
          {/* 左欄：流程卡垂直清單 */}
          <div className="space-y-2 lg:max-h-[calc(100vh-280px)] lg:overflow-y-auto lg:pr-1" data-testid="dash-flow-list">
            {items.map((flow) => (
              <FlowCard key={flow.id} flow={flow} selected={flow.id === watchingId} onSelect={() => setWatchingId(flow.id)} />
            ))}
          </div>
          {/* 中央：即時影像 */}
          <div className="h-[52vh] min-h-80 lg:h-[calc(100vh-280px)] lg:min-h-[480px]">
            {watching ? (
              <FlowLiveMonitor key={watching.id} flow={watching} onRun={setLastRun} />
            ) : (
              <div className="flex h-full items-center justify-center rounded-lg bg-viewer text-sm text-white/60">{t('dashboard.selectFlow')}</div>
            )}
          </div>
          {/* 右欄：即時檢測資訊 */}
          <div className="min-w-0">
            <LiveInfo run={lastRun} />
          </div>
        </div>
      )}
    </Page>
  )
}
