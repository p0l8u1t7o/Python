/** Shapes of `GET /ems/reports/energy` — mirrors apps/ems/reports.py. */

export interface ReportTotals {
  load_kwh: number
  pv_kwh: number
  grid_import_kwh: number
  grid_export_kwh: number
  battery_charge_kwh: number
  battery_discharge_kwh: number
  peak_import_kw: number | null
  peak_load_kw: number | null
  peak_basis: string
  energy_cost: number
  export_revenue: number
  estimated_savings: number
  demand_savings: number
  penalty_avoided: number
  net_cost: number
  self_consumption_ratio: number | null
  self_sufficiency_ratio: number | null
  round_trip_efficiency: number | null
  currency: string
}

export interface ReportSiteRow {
  site_id: string
  site_name: string
  parent_id: string | null
  timezone_name: string
  device_count: number
  interval_count: number
  load_kwh: number
  pv_kwh: number
  grid_import_kwh: number
  grid_export_kwh: number
  battery_charge_kwh: number
  battery_discharge_kwh: number
  self_consumption_ratio: number | null
  self_sufficiency_ratio: number | null
  energy_cost: number
  export_revenue: number
  estimated_savings: number
  currency: string
  peak_demand_kw: number | null
  baseline_peak_kw: number | null
  contract_capacity_kw: number | null
  demand_savings: number
  penalty_avoided: number
  over_contract: boolean
}

export interface ReportDay {
  day: string
  load_kwh: number
  pv_kwh: number
  grid_import_kwh: number
  grid_export_kwh: number
  battery_discharge_kwh: number
  energy_cost: number
  estimated_savings: number
}

export interface ReportHour {
  hour: number
  avg_load_kw: number
  avg_import_kw: number
}

export interface ReportAlerts {
  total: number
  per_day: number
  by_severity: Record<string, number>
  by_status: Record<string, number>
  open: number
  resolved: number
  by_hour: number[]
  by_weekday: number[]
  peak_hour: number | null
  peak_hour_share: number | null
  peak_weekday: string | null
  mean_minutes_to_resolve: number | null
  median_minutes_to_resolve: number | null
  mean_minutes_to_acknowledge: number | null
  by_site: { site_id: string; site_name: string; total: number; critical: number; major: number; warning: number; info: number; open: number }[]
  top_titles: { code: string; title: string; count: number; occurrences: number; severity: string }[]
  top_devices: { device_id: string; device_name: string; site_name: string; count: number }[]
}

export interface ReportInsight {
  level: 'critical' | 'warning' | 'ok' | 'info'
  text: string
}

export interface EnergyReport {
  generated_at: string
  organization_name: string
  scope_name: string
  start: string
  end: string
  timezone_name: string
  currency: string
  mixed_currency: boolean
  site_count: number
  device_count: number
  totals: ReportTotals
  sites: ReportSiteRow[]
  daily: ReportDay[]
  hourly_load: ReportHour[]
  alerts: ReportAlerts
  insights: ReportInsight[]
}

export interface ReportParams {
  start: string
  end: string
  site_id?: string
  include_descendants?: boolean
}
