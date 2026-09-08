import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { DashboardWidgetType } from '@/lib/types'
import type { DashboardWidgetProps } from './types'
import { ImageWidget } from './widgets/ImageWidget'
import { ImagesWidget } from './widgets/ImagesWidget'
import { RunControlWidget } from './widgets/RunControlWidget'
import { RunStatusWidget } from './widgets/RunStatusWidget'
import { VerdictWidget } from './widgets/VerdictWidget'
import { TextWidget } from './widgets/TextWidget'
import { ButtonWidget } from './widgets/ButtonWidget'
import { SwitchWidget } from './widgets/SwitchWidget'
import { ParamWidget } from './widgets/ParamWidget'
import { VariableWidget } from './widgets/VariableWidget'
import { TrafficLightWidget } from './widgets/TrafficLightWidget'
import { ConditionalLightWidget } from './widgets/ConditionalLightWidget'
import { GroupWidget } from './widgets/GroupWidget'
import { TabsWidget } from './widgets/TabsWidget'
import { TableWidget } from './widgets/TableWidget'
import { LineChartWidget } from './widgets/LineChartWidget'
import { StatsWidget } from './widgets/StatsWidget'
import { PieWidget } from './widgets/PieWidget'
import { ImageStaticWidget } from './widgets/ImageStaticWidget'
import { ClockWidget } from './widgets/ClockWidget'
import { LogWidget } from './widgets/LogWidget'
import { DeviceStatusWidget } from './widgets/DeviceStatusWidget'

const RENDERERS: Record<DashboardWidgetType, (props: DashboardWidgetProps) => ReactNode> = {
  image: ImageWidget,
  images: ImagesWidget,
  run_control: RunControlWidget,
  run_status: RunStatusWidget,
  verdict: VerdictWidget,
  text: TextWidget,
  button: ButtonWidget,
  switch: SwitchWidget,
  param: ParamWidget,
  variable: VariableWidget,
  traffic_light: TrafficLightWidget,
  conditional_light: ConditionalLightWidget,
  group: GroupWidget,
  tabs: TabsWidget,
  table: TableWidget,
  line_chart: LineChartWidget,
  stats: StatsWidget,
  pie: PieWidget,
  image_static: ImageStaticWidget,
  clock: ClockWidget,
  log: LogWidget,
  device_status: DeviceStatusWidget,
}

export function WidgetRenderer(props: DashboardWidgetProps) {
  if (props.design && DESIGN_PLACEHOLDERS.has(props.widget.type)) return <DesignWidgetPreview {...props} />
  const render = RENDERERS[props.widget.type]
  return (
    <div className="h-full min-h-0 min-w-0" data-testid={`dash-widget-${props.widget.type}`}>
      {render ? render(props) : null}
    </div>
  )
}

const DESIGN_PLACEHOLDERS = new Set<DashboardWidgetType>(['run_control', 'button', 'switch', 'param', 'variable', 'line_chart'])

function DesignWidgetPreview(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const label = String(props.widget.source?.key ?? props.widget.props?.key ?? props.widget.props?.variable ?? t('dashboardDesign.designPreview'))
  return (
    <div className="h-full min-h-0 min-w-0" data-testid={`dash-widget-${props.widget.type}`}>
      <div className="flex h-full min-h-28 min-w-0 flex-col overflow-hidden rounded-md border border-line bg-surface/95 p-3 text-content shadow-sm">
        <div className="mb-2 truncate text-xs font-semibold uppercase tracking-normal text-muted">{t(`dashboardRun.widgetTypes.${props.widget.type}`)}</div>
        <div className="flex min-h-0 flex-1 items-center justify-center rounded border border-dashed border-line bg-surface-muted/40 text-sm text-muted">
          {label}
        </div>
      </div>
    </div>
  )
}
