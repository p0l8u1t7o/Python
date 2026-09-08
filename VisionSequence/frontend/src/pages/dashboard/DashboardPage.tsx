import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Edit3, Expand, Shrink } from 'lucide-react'

import { WidgetRenderer } from '@/components/dashboard/WidgetRenderer'
import { Button, ErrorState, LoadingState } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { dashboardFlowIds, cellById, nestedWidgetIds } from '@/lib/dashboard'
import { useFlowStream, type StreamEvent } from '@/lib/flowStream'
import { MOBILE_QUERY, useMediaQuery } from '@/lib/useMediaQuery'
import { useDashboard, useDashboardData, useDefaultDashboard } from '@/lib/queries'
import type { Dashboard, DashboardLayout, DashboardWidget, RunReport } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'

function DeviceStrip({ dashboard, data }: { dashboard: Dashboard; data?: ReturnType<typeof useDashboardData>['data'] }) {
  const { t } = useTranslation()
  const device = data?.device
  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      <span className="truncate text-content">{dashboard.name}</span>
      {device ? (
        <>
          <span>{t('dashboardRun.station')}: <span className="tnum text-content">{device.station_id}</span></span>
          <span>{t('dashboardRun.version')}: <span className="tnum text-content">{device.version}</span></span>
          <span>{t('dashboardRun.capacity')}: <span className="tnum text-content">{device.capacity.active}/{device.capacity.max_workers}</span></span>
          <span>{device.lock.locked ? `${t('dashboardRun.locked')} ${device.lock.holder}` : t('dashboardRun.unlocked')}</span>
        </>
      ) : null}
    </div>
  )
}

function FlowStreamSubscriber({ flowId, onRun, onRefresh }: { flowId: number; onRun: (flowId: number, run: RunReport) => void; onRefresh: () => void }) {
  useFlowStream(flowId, true, (event: StreamEvent) => {
    if (event.type === 'run_finished' && event.run) {
      onRun(flowId, event.run)
      onRefresh()
    }
  })
  return null
}

function topLevelWidgets(layout: DashboardLayout): DashboardWidget[] {
  const nested = nestedWidgetIds(layout)
  return layout.widgets.filter((widget) => !nested.has(widget.id))
}

export function DashboardPage() {
  const { t } = useTranslation()
  const params = useParams()
  const navigate = useNavigate()
  const auth = useAuth()
  const mobile = useMediaQuery(MOBILE_QUERY)
  const routeId = params.id ? Number(params.id) : null
  const single = useDashboard(routeId)
  const fallback = useDefaultDashboard(routeId === null)
  const dashboard = routeId === null ? fallback.data : single.data
  const dashboardQuery = routeId === null ? fallback : single
  const data = useDashboardData(dashboard?.id ?? null, { refetchInterval: 15000 })
  const [live, setLive] = useState<Record<number, RunReport | null>>({})
  const [fullscreen, setFullscreen] = useState(false)
  const flowIds = useMemo(() => dashboard ? dashboardFlowIds(dashboard.layout) : [], [dashboard])

  useEffect(() => {
    if (dashboard) document.title = dashboard.name
  }, [dashboard])

  useEffect(() => {
    const onChange = () => setFullscreen(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  if (dashboardQuery.isPending) return <div className="flex min-h-screen items-center justify-center bg-app"><LoadingState /></div>
  if (dashboardQuery.isError) {
    if (routeId === null && dashboardQuery.error instanceof ApiError && dashboardQuery.error.code === 'no_default') {
      return (
        <div className="flex min-h-screen items-center justify-center bg-app p-6">
          <div className="max-w-md rounded-md border border-line bg-surface p-6 text-center shadow-sm">
            <h1 className="text-xl font-semibold text-heading">{t('dashboardRun.noDefault')}</h1>
            <div className="mt-4">
              <Button onClick={() => navigate('/dashboards')}>{t('dashboardRun.openList')}</Button>
            </div>
          </div>
        </div>
      )
    }
    return <div className="flex min-h-screen items-center justify-center bg-app p-6"><ErrorState error={dashboardQuery.error} onRetry={() => void dashboardQuery.refetch()} /></div>
  }
  if (!dashboard) return null

  const layout = dashboard.layout
  const cells = layout.cells
  const widgets = topLevelWidgets(layout)
  const header = layout.bars.top !== false
  const bottom = layout.bars.bottom === true
  const gridStyle = mobile
    ? undefined
    : {
        gridTemplateRows: `repeat(${Math.max(1, layout.rows)}, minmax(0, 1fr))`,
        gridTemplateColumns: `repeat(${Math.max(1, layout.cols)}, minmax(0, 1fr))`,
      }

  const toggleFullscreen = async () => {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await document.documentElement.requestFullscreen()
  }

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-app text-content">
      {flowIds.map((flowId) => (
        <FlowStreamSubscriber key={flowId} flowId={flowId} onRun={(id, run) => setLive((current) => ({ ...current, [id]: run }))} onRefresh={() => void data.refetch()} />
      ))}
      {header ? (
        <header className="flex min-h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
          <DeviceStrip dashboard={dashboard} data={data.data} />
          <div className="flex shrink-0 items-center gap-2">
            <Button size="sm" variant="ghost" icon={fullscreen ? <Shrink className="size-4" /> : <Expand className="size-4" />} onClick={() => void toggleFullscreen()}>{fullscreen ? t('dashboardRun.exitFullscreen') : t('dashboardRun.fullscreen')}</Button>
            <Button size="sm" variant="ghost" icon={<ArrowLeft className="size-4" />} onClick={() => navigate('/dashboards')}>{t('dashboardRun.backToList')}</Button>
            {auth.can('flows.edit') ? <Link to={`/dashboards/${dashboard.id}/design`} className="btn h-8 px-2.5 text-xs"><Edit3 className="size-4" />{t('dashboardRun.editLayout')}</Link> : null}
          </div>
        </header>
      ) : null}
      <div className="grid min-h-0 flex-1 overflow-hidden" style={{ gridTemplateColumns: `${layout.bars.left ? '3rem ' : ''}minmax(0,1fr)${layout.bars.right ? ' 3rem' : ''}` }}>
        {layout.bars.left ? <aside className="border-r border-line bg-surface/80" /> : null}
        <main className={`${mobile ? 'overflow-y-auto' : 'overflow-hidden'} min-w-0 p-2`}>
          <div className={`${mobile ? 'flex flex-col' : 'grid'} h-full min-h-0 gap-2`} style={gridStyle}>
            {cells.map((cell) => {
              const assigned = widgets.filter((widget) => widget.cell === cell.id)
              if (!assigned.length) return null
              const style = mobile ? undefined : {
                gridRow: `${cell.row} / span ${cell.row_span}`,
                gridColumn: `${cell.col} / span ${cell.col_span}`,
              }
              return (
                <section key={cell.id} className="min-h-40 min-w-0 overflow-hidden" style={style}>
                  <div className="grid h-full min-h-0 gap-2">
                    {assigned.map((widget) => <WidgetRenderer key={widget.id} widget={widget} layout={layout} data={data.data} live={live} />)}
                  </div>
                </section>
              )
            })}
            {widgets.filter((widget) => !cellById(layout, widget.cell)).map((widget) => (
              <section key={widget.id} className="min-h-40 min-w-0 overflow-hidden">
                <WidgetRenderer widget={widget} layout={layout} data={data.data} live={live} />
              </section>
            ))}
          </div>
        </main>
        {layout.bars.right ? <aside className="border-l border-line bg-surface/80" /> : null}
      </div>
      {bottom ? (
        <footer className="flex min-h-9 shrink-0 items-center border-t border-line bg-surface px-4">
          <DeviceStrip dashboard={dashboard} data={data.data} />
        </footer>
      ) : null}
    </div>
  )
}
