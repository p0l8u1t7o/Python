import { useMemo, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { WidgetRenderer } from '../WidgetRenderer'
import type { DashboardWidgetProps } from '../types'
import { nestedWidgetIds, numberProp, stringProp } from '@/lib/dashboard'
import { useDashboard } from '@/lib/queries'

export function ChildWidget(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const dashboardId = numberProp(props.widget, 'dashboard_id', 0)
  const title = stringProp(props.widget, 'title')
  const query = useDashboard(dashboardId || null)
  const nested = useMemo(() => query.data ? nestedWidgetIds(query.data.layout) : new Set<string>(), [query.data])

  if ((props.depth ?? 0) > 0) return <ChildShell title={title}><Message text={t('dashboardRun.nestedChildHidden')} /></ChildShell>
  if (query.isPending) return <ChildShell title={title}><Message text={t('dashboardRun.loading')} /></ChildShell>
  if (query.isError || !query.data) return <ChildShell title={title}><Message text={t('dashboardRun.childDashboardNotFound')} /></ChildShell>

  const layout = query.data.layout
  const shownTitle = title || query.data.name
  const widgets = layout.widgets.filter((widget) => !nested.has(widget.id))
  return (
    <ChildShell title={shownTitle}>
      <div className="grid h-full min-h-0 gap-1.5" style={{ gridTemplateRows: `repeat(${Math.max(1, layout.rows)}, minmax(0, 1fr))`, gridTemplateColumns: `repeat(${Math.max(1, layout.cols)}, minmax(0, 1fr))` }}>
        {layout.cells.map((cell) => {
          const assigned = widgets.filter((widget) => widget.cell === cell.id)
          if (!assigned.length) return null
          return (
            <section key={cell.id} className="min-h-20 min-w-0 overflow-hidden" style={{ gridRow: `${cell.row} / span ${cell.row_span}`, gridColumn: `${cell.col} / span ${cell.col_span}` }}>
              <div className="grid h-full min-h-0 gap-1.5">
                {assigned.map((widget) => <WidgetRenderer key={widget.id} widget={widget} layout={layout} data={props.data} live={props.live} depth={(props.depth ?? 0) + 1} design={props.design} />)}
              </div>
            </section>
          )
        })}
      </div>
    </ChildShell>
  )
}

function ChildShell({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="flex h-full min-h-28 min-w-0 flex-col overflow-hidden rounded-md border border-line bg-surface/95 p-2 text-content shadow-sm">
      {title ? <div className="mb-1.5 truncate text-xs font-semibold uppercase tracking-normal text-muted">{title}</div> : null}
      <div className="min-h-0 min-w-0 flex-1">{children}</div>
    </div>
  )
}

function Message({ text }: { text: string }) {
  return <div className="flex h-full min-h-20 items-center justify-center rounded border border-dashed border-line px-2 text-center text-sm text-muted">{text}</div>
}
