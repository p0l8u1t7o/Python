import type { DashboardData, DashboardLayout, DashboardWidget, RunReport } from '@/lib/types'

export interface DashboardWidgetProps {
  widget: DashboardWidget
  layout: DashboardLayout
  data?: DashboardData
  live: Record<number, RunReport | null>
  depth?: number
  design?: boolean
}
