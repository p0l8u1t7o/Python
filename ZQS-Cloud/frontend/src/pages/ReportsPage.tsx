import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Bell, CheckCircle2, Clock, Coins, CornerDownRight, Download, FileText, Info, PiggyBank, Plug, Sun, Zap } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { downloadEnergyReport, useEnergyReport, useSites } from '@/lib/queries'
import { formatCurrency, formatDateTime, formatNumber } from '@/lib/format'
import { errorMessage } from '@/lib/errors'
import { useToast } from '@/providers/ToastProvider'
import { useChartColors } from '@/components/charts/chartTheme'
import { treeRows } from '@/lib/siteTree'
import type { EnergyReport, ReportInsight, ReportParams } from '@/components/reports/reportTypes'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  EmptyState,
  ErrorState,
  PageHeader,
  SegmentedControl,
  Select,
  Skeleton,
  StatTile,
  Table,
  TBody,
  Td,
  TextInput,
  Th,
  THead,
  Tr,
} from '@/components/ui'

type Preset = 'today' | 'week' | 'month' | 'lastMonth' | '7d' | '30d' | 'custom'
const PRESETS: Preset[] = ['today', 'week', 'month', 'lastMonth', '7d', '30d', 'custom']

/** Calendar windows in the browser's local time; the API takes ISO instants. */
function presetWindow(preset: Preset, now = new Date()): { start: Date; end: Date } {
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const end = new Date(now)
  switch (preset) {
    case 'today':
      return { start: startOfDay(now), end }
    case 'week': {
      const day = (now.getDay() + 6) % 7 // Monday = 0
      const start = startOfDay(now)
      start.setDate(start.getDate() - day)
      return { start, end }
    }
    case 'month':
      return { start: new Date(now.getFullYear(), now.getMonth(), 1), end }
    case 'lastMonth':
      return {
        start: new Date(now.getFullYear(), now.getMonth() - 1, 1),
        end: new Date(now.getFullYear(), now.getMonth(), 1),
      }
    case '7d':
      return { start: new Date(now.getTime() - 7 * 86400_000), end }
    case '30d':
      return { start: new Date(now.getTime() - 30 * 86400_000), end }
    default:
      return { start: startOfDay(now), end }
  }
}

function toDateInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

const LEVEL_TONE: Record<ReportInsight['level'], 'critical' | 'warning' | 'ok' | 'info'> = {
  critical: 'critical',
  warning: 'warning',
  ok: 'ok',
  info: 'info',
}
const LEVEL_ICON = {
  critical: AlertTriangle,
  warning: AlertTriangle,
  ok: CheckCircle2,
  info: Info,
}

/**
 * Energy management report: pick a scope and a window, read the numbers and
 * the conclusions on screen, take the same thing away as PDF or Word. The
 * page renders exactly what the export contains - both come from one API
 * payload - so what is signed off is what was seen.
 */
export function ReportsPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const sites = useSites()
  const [preset, setPreset] = useState<Preset>('month')
  const [custom, setCustom] = useState(() => {
    const { start, end } = presetWindow('7d')
    return { from: toDateInput(start), to: toDateInput(end) }
  })
  const [siteId, setSiteId] = useState('')
  const [descendants, setDescendants] = useState(true)
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null)

  const params = useMemo<ReportParams | null>(() => {
    let start: Date
    let end: Date
    if (preset === 'custom') {
      start = new Date(`${custom.from}T00:00:00`)
      end = new Date(`${custom.to}T00:00:00`)
      end.setDate(end.getDate() + 1) // inclusive "to" day
      if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start >= end) return null
    } else {
      ;({ start, end } = presetWindow(preset))
    }
    return {
      start: start.toISOString(),
      end: end.toISOString(),
      site_id: siteId || undefined,
      include_descendants: descendants,
    }
  }, [preset, custom, siteId, descendants])

  const report = useEnergyReport(params)

  async function exportAs(format: 'pdf' | 'docx') {
    if (!params) return
    setExporting(format)
    try {
      await downloadEnergyReport(params, format)
      toast.success(t('reports.exported', { format: format.toUpperCase() }))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setExporting(null)
    }
  }

  return (
    <>
      <PageHeader
        title={t('reports.title')}
        description={t('reports.subtitle')}
        actions={
          <div className="flex gap-2">
            <Button
              icon={<FileText className="size-4" />}
              loading={exporting === 'pdf'}
              disabled={!report.data || exporting !== null}
              onClick={() => void exportAs('pdf')}
              data-testid="report-export-pdf"
            >
              {t('reports.exportPdf')}
            </Button>
            <Button
              icon={<Download className="size-4" />}
              loading={exporting === 'docx'}
              disabled={!report.data || exporting !== null}
              onClick={() => void exportAs('docx')}
              data-testid="report-export-docx"
            >
              {t('reports.exportDocx')}
            </Button>
          </div>
        }
      />

      <Card className="mb-5">
        <CardBody className="flex flex-wrap items-end gap-3">
          <Select
            label={t('reports.scope')}
            value={siteId}
            placeholder={t('reports.allSites')}
            options={(sites.data?.items ?? []).map((site) => ({
              value: site.id,
              label: `${'　'.repeat(site.depth)}${site.name}`,
            }))}
            onChange={(event) => setSiteId(event.target.value)}
            className="w-60"
          />
          {siteId ? (
            <Checkbox label={t('reports.includeDescendants')} checked={descendants} onChange={setDescendants} />
          ) : null}
          <div>
            <span className="label">{t('reports.period')}</span>
            <SegmentedControl<Preset>
              value={preset}
              onChange={setPreset}
              size="sm"
              options={PRESETS.map((key) => ({ value: key, label: t(`reports.presets.${key}`) }))}
            />
          </div>
          {preset === 'custom' ? (
            <>
              <TextInput
                label={t('range.from')}
                type="date"
                value={custom.from}
                onChange={(event) => setCustom({ ...custom, from: event.target.value })}
              />
              <TextInput
                label={t('range.to')}
                type="date"
                value={custom.to}
                onChange={(event) => setCustom({ ...custom, to: event.target.value })}
              />
            </>
          ) : null}
        </CardBody>
      </Card>

      {params === null ? (
        <EmptyState title={t('reports.badRange')} />
      ) : report.isPending ? (
        <div className="space-y-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-64" />
        </div>
      ) : report.error ? (
        <ErrorState error={report.error} onRetry={() => void report.refetch()} />
      ) : report.data ? (
        <ReportBody report={report.data} />
      ) : null}
    </>
  )
}

/** A site name in a tree table: indented, with the connector and its parent named. */
function SiteCell({ name, parent, depth }: { name: string; parent?: string; depth: number }) {
  const { t } = useTranslation()
  return (
    <span className="flex items-center gap-1" style={{ paddingLeft: `${depth * 18}px` }}>
      {depth > 0 ? <CornerDownRight className="size-3.5 shrink-0 text-subtle" aria-hidden /> : null}
      <span className="min-w-0">
        <span className={`block truncate ${depth === 0 ? 'font-semibold' : 'font-medium'}`}>{name}</span>
        {parent ? <span className="block truncate text-[11px] text-subtle">{t('dashboard.childOf', { parent })}</span> : null}
      </span>
    </span>
  )
}

function ReportBody({ report }: { report: EnergyReport }) {
  const { t } = useTranslation()
  const colors = useChartColors()
  const currency = report.mixed_currency ? undefined : report.currency || undefined
  const totals = report.totals
  const alerts = report.alerts
  const money = (value: number) => formatCurrency(value, currency)
  const pct = (value: number | null) => (value === null ? '—' : `${value.toFixed(0)}%`)
  const minutes = (value: number | null) =>
    value === null ? '—' : value >= 120 ? t('reports.hours', { value: (value / 60).toFixed(1) }) : t('reports.minutes', { value: value.toFixed(0) })

  const tooltipStyle = {
    background: colors.surface,
    border: `1px solid ${colors.border}`,
    borderRadius: 8,
    fontSize: 12,
    color: colors.content,
  }
  const daily = report.daily.map((d) => ({ ...d, label: d.day.slice(5) }))
  const hourly = report.hourly_load.map((h) => ({ ...h, label: `${String(h.hour).padStart(2, '0')}` }))
  const alertHours = alerts.by_hour.map((count, hour) => ({ label: String(hour).padStart(2, '0'), count }))
  // Sites are always shown as a tree: a workshop under its plant, never a flat list.
  const siteRows = treeRows(report.sites, (row) => row.site_id, (row) => row.parent_id)
  const alertSiteRows = treeRows(alerts.by_site, (row) => row.site_id, (row) => row.parent_id ?? null)
  const alertWeekdays = alerts.by_weekday.map((count, i) => ({ label: t(`reports.weekdays.${i}`), count }))

  return (
    <div className="space-y-5" data-testid="energy-report">
      <div>
        <h2 className="text-lg font-semibold">
          {t('reports.reportTitle', { scope: report.scope_name || t('reports.allSites') })}
        </h2>
        <p className="text-sm text-muted">
          {formatDateTime(report.start)} – {formatDateTime(report.end)} · {t('reports.coverage', { sites: report.site_count, devices: report.device_count })}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label={t('reports.kpi.load')} value={formatNumber(totals.load_kwh, { maximumFractionDigits: 0 })} unit="kWh" icon={<Plug className="size-4" />} />
        <StatTile label={t('reports.kpi.pv')} value={formatNumber(totals.pv_kwh, { maximumFractionDigits: 0 })} unit="kWh" accent="warning" icon={<Sun className="size-4" />} />
        <StatTile label={t('reports.kpi.import')} value={formatNumber(totals.grid_import_kwh, { maximumFractionDigits: 0 })} unit="kWh" icon={<Zap className="size-4" />} hint={t('reports.kpi.exportHint', { value: formatNumber(totals.grid_export_kwh, { maximumFractionDigits: 0 }) })} />
        <StatTile label={t('reports.kpi.peak')} value={totals.peak_load_kw === null ? '—' : formatNumber(totals.peak_load_kw, { maximumFractionDigits: 0 })} unit="kW" icon={<Zap className="size-4" />} />
        <StatTile label={t('reports.kpi.cost')} value={money(totals.energy_cost)} icon={<Coins className="size-4" />} hint={t('reports.kpi.revenueHint', { value: money(totals.export_revenue) })} />
        <StatTile label={t('reports.kpi.savings')} value={money(totals.estimated_savings + totals.demand_savings)} accent={totals.estimated_savings + totals.demand_savings < 0 ? 'critical' : 'ok'} icon={<PiggyBank className="size-4" />} hint={t('reports.kpi.savingsHint', { energy: money(totals.estimated_savings), demand: money(totals.demand_savings) })} />
        <StatTile label={t('reports.kpi.selfSufficiency')} value={pct(totals.self_sufficiency_ratio)} hint={t('reports.kpi.selfConsumption', { value: pct(totals.self_consumption_ratio) })} icon={<Sun className="size-4" />} />
        <StatTile label={t('reports.kpi.alerts')} value={alerts.total} accent={alerts.by_severity.critical > 0 ? 'critical' : alerts.total > 0 ? 'warning' : 'ok'} icon={<Bell className="size-4" />} hint={t('reports.kpi.alertsHint', { open: alerts.open, mttr: minutes(alerts.median_minutes_to_resolve) })} />
      </div>
      {report.mixed_currency ? <p className="text-xs text-warning">{t('dashboard.mixedCurrency')}</p> : null}

      <Card>
        <CardHeader title={t('reports.insights')} description={t('reports.insightsHint')} />
        <CardBody>
          <ul className="space-y-2" data-testid="report-insights">
            {report.insights.map((item, index) => {
              const Icon = LEVEL_ICON[item.level]
              return (
                <li key={index} className="flex items-start gap-2 text-sm">
                  <Badge tone={LEVEL_TONE[item.level]}>
                    <Icon className="mr-1 size-3" />
                    {t(`reports.levels.${item.level}`)}
                  </Badge>
                  <span>{item.text}</span>
                </li>
              )
            })}
          </ul>
        </CardBody>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title={t('reports.dailyTitle')} description={t('reports.dailyHint')} />
          <CardBody>
            {daily.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted">{t('common.noData')}</p>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={daily} margin={{ top: 8, right: 8, left: 4, bottom: 4 }} barGap={2}>
                  <CartesianGrid stroke={colors.grid} vertical={false} />
                  <XAxis dataKey="label" stroke={colors.axis} tick={{ fontSize: 11, fill: colors.axis }} tickLine={false} axisLine={{ stroke: colors.grid }} interval={daily.length > 14 ? Math.ceil(daily.length / 10) : 0} />
                  <YAxis stroke={colors.axis} tick={{ fontSize: 11, fill: colors.axis }} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => formatNumber(v, { notation: 'compact' })} />
                  <Tooltip cursor={{ fill: colors.grid, opacity: 0.35 }} contentStyle={tooltipStyle} formatter={(value: number) => `${formatNumber(value, { maximumFractionDigits: 0 })} kWh`} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="load_kwh" name={t('reports.series.load')} fill={colors.series[0]} radius={[3, 3, 0, 0]} maxBarSize={28} />
                  <Bar dataKey="grid_import_kwh" name={t('reports.series.import')} fill={colors.series[2]} radius={[3, 3, 0, 0]} maxBarSize={28} />
                  <Bar dataKey="pv_kwh" name={t('reports.series.pv')} fill={colors.series[1]} radius={[3, 3, 0, 0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t('reports.hourlyTitle')} description={t('reports.hourlyHint')} />
          <CardBody>
            {hourly.every((h) => h.avg_load_kw === 0) ? (
              <p className="py-8 text-center text-sm text-muted">{t('common.noData')}</p>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={hourly} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
                  <CartesianGrid stroke={colors.grid} vertical={false} />
                  <XAxis dataKey="label" stroke={colors.axis} tick={{ fontSize: 11, fill: colors.axis }} tickLine={false} axisLine={{ stroke: colors.grid }} interval={1} />
                  <YAxis stroke={colors.axis} tick={{ fontSize: 11, fill: colors.axis }} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => formatNumber(v, { notation: 'compact' })} />
                  <Tooltip cursor={{ fill: colors.grid, opacity: 0.35 }} contentStyle={tooltipStyle} formatter={(value: number) => `${formatNumber(value, { maximumFractionDigits: 0 })} kW`} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="avg_load_kw" name={t('reports.series.avgLoad')} fill={colors.series[3]} radius={[3, 3, 0, 0]} maxBarSize={18} />
                  <Bar dataKey="avg_import_kw" name={t('reports.series.avgImport')} fill={colors.series[2]} radius={[3, 3, 0, 0]} maxBarSize={18} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title={t('reports.sitesTitle')} description={t('reports.sitesHint')} />
        <Table>
          <THead>
            <Th>{t('sites.site')}</Th>
            <Th align="right">{t('reports.cols.load')}</Th>
            <Th align="right">{t('reports.cols.pv')}</Th>
            <Th align="right">{t('reports.cols.import')}</Th>
            <Th align="right">{t('reports.cols.selfSufficiency')}</Th>
            <Th align="right">{t('reports.cols.peak')}</Th>
            <Th align="right">{t('reports.cols.contract')}</Th>
            <Th align="right">{t('reports.cols.cost')}</Th>
            <Th align="right">{t('reports.cols.savings')}</Th>
          </THead>
          <TBody>
            {siteRows.map(({ item: row, parent, depth }) => (
              <Tr key={row.site_id} className={depth > 0 ? 'bg-surface-muted/30' : ''}>
                <Td>
                  <SiteCell name={row.site_name} parent={parent?.site_name} depth={depth} />
                </Td>
                <Td align="right" className="tnum">{formatNumber(row.load_kwh, { maximumFractionDigits: 0 })}</Td>
                <Td align="right" className="tnum text-muted">{formatNumber(row.pv_kwh, { maximumFractionDigits: 0 })}</Td>
                <Td align="right" className="tnum text-muted">{formatNumber(row.grid_import_kwh, { maximumFractionDigits: 0 })}</Td>
                <Td align="right" className="tnum">{pct(row.self_sufficiency_ratio)}</Td>
                <Td align="right" className="tnum">
                  {row.peak_demand_kw === null ? '—' : formatNumber(row.peak_demand_kw, { maximumFractionDigits: 0 })}
                  {row.over_contract ? <Badge tone="critical" className="ml-1">{t('reports.overContract')}</Badge> : null}
                </Td>
                <Td align="right" className="tnum text-muted">{row.contract_capacity_kw === null ? '—' : formatNumber(row.contract_capacity_kw, { maximumFractionDigits: 0 })}</Td>
                <Td align="right" className="tnum">{formatCurrency(row.energy_cost, row.currency || undefined)}</Td>
                <Td align="right" className={`tnum ${row.estimated_savings + row.demand_savings < 0 ? 'text-critical' : 'text-ok'}`}>
                  {formatCurrency(row.estimated_savings + row.demand_savings, row.currency || undefined)}
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      </Card>

      <Card>
        <CardHeader title={t('reports.alertsTitle')} description={t('reports.alertsHint')} />
        <CardBody className="space-y-5">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
            <StatTile label={t('reports.alerts.total')} value={alerts.total} hint={t('reports.alerts.perDay', { value: alerts.per_day.toFixed(1) })} icon={<Bell className="size-4" />} />
            <StatTile label={t('severity.critical')} value={alerts.by_severity.critical ?? 0} accent={alerts.by_severity.critical ? 'critical' : 'neutral'} />
            <StatTile label={t('severity.major')} value={alerts.by_severity.major ?? 0} accent={alerts.by_severity.major ? 'major' : 'neutral'} />
            <StatTile label={t('severity.warning')} value={alerts.by_severity.warning ?? 0} accent={alerts.by_severity.warning ? 'warning' : 'neutral'} />
            <StatTile label={t('reports.alerts.open')} value={alerts.open} accent={alerts.open ? 'warning' : 'ok'} hint={t('reports.alerts.resolved', { value: alerts.resolved })} />
            <StatTile label={t('reports.alerts.mttr')} value={minutes(alerts.median_minutes_to_resolve)} icon={<Clock className="size-4" />} hint={t('reports.alerts.mtta', { value: minutes(alerts.mean_minutes_to_acknowledge) })} />
          </div>

          {alerts.total > 0 ? (
            <>
              <div className="grid gap-5 xl:grid-cols-[2fr_1fr]">
                <div>
                  <p className="mb-1 text-sm font-medium">{t('reports.alerts.byHour')}</p>
                  <p className="mb-2 text-xs text-muted">
                    {alerts.peak_hour !== null
                      ? t('reports.alerts.peakHour', { hour: String(alerts.peak_hour).padStart(2, '0'), share: alerts.peak_hour_share?.toFixed(0) ?? '0' })
                      : ''}
                  </p>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={alertHours} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
                      <CartesianGrid stroke={colors.grid} vertical={false} />
                      <XAxis dataKey="label" stroke={colors.axis} tick={{ fontSize: 11, fill: colors.axis }} tickLine={false} axisLine={{ stroke: colors.grid }} interval={1} />
                      <YAxis stroke={colors.axis} tick={{ fontSize: 11, fill: colors.axis }} tickLine={false} axisLine={false} width={32} allowDecimals={false} />
                      <Tooltip cursor={{ fill: colors.grid, opacity: 0.35 }} contentStyle={tooltipStyle} />
                      <Bar dataKey="count" name={t('reports.alerts.count')} fill={colors.warning} radius={[3, 3, 0, 0]} maxBarSize={18} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div>
                  <p className="mb-1 text-sm font-medium">{t('reports.alerts.byWeekday')}</p>
                  <p className="mb-2 text-xs text-muted">
                    {alerts.peak_weekday ? t('reports.alerts.peakWeekday', { day: t(`reports.weekdayNames.${alerts.peak_weekday}`) }) : ''}
                  </p>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={alertWeekdays} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
                      <CartesianGrid stroke={colors.grid} vertical={false} />
                      <XAxis dataKey="label" stroke={colors.axis} tick={{ fontSize: 11, fill: colors.axis }} tickLine={false} axisLine={{ stroke: colors.grid }} />
                      <YAxis stroke={colors.axis} tick={{ fontSize: 11, fill: colors.axis }} tickLine={false} axisLine={false} width={32} allowDecimals={false} />
                      <Tooltip cursor={{ fill: colors.grid, opacity: 0.35 }} contentStyle={tooltipStyle} />
                      <Bar dataKey="count" name={t('reports.alerts.count')} fill={colors.warning} radius={[3, 3, 0, 0]} maxBarSize={24} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="grid gap-5 xl:grid-cols-2">
                <div>
                  <p className="mb-2 text-sm font-medium">{t('reports.alerts.bySite')}</p>
                  <Table>
                    <THead>
                      <Th>{t('sites.site')}</Th>
                      <Th align="right">{t('reports.alerts.total')}</Th>
                      <Th align="right">{t('severity.critical')}</Th>
                      <Th align="right">{t('severity.major')}</Th>
                      <Th align="right">{t('severity.warning')}</Th>
                      <Th align="right">{t('reports.alerts.open')}</Th>
                    </THead>
                    <TBody>
                      {alertSiteRows.map(({ item: row, parent, depth }) => (
                        <Tr key={row.site_id} className={depth > 0 ? 'bg-surface-muted/30' : ''}>
                          <Td>
                            <SiteCell name={row.site_name} parent={parent?.site_name} depth={depth} />
                          </Td>
                          <Td align="right" className="tnum">{row.total}</Td>
                          <Td align="right" className="tnum">{row.critical}</Td>
                          <Td align="right" className="tnum">{row.major}</Td>
                          <Td align="right" className="tnum">{row.warning}</Td>
                          <Td align="right" className="tnum">{row.open}</Td>
                        </Tr>
                      ))}
                    </TBody>
                  </Table>
                </div>
                <div>
                  <p className="mb-2 text-sm font-medium">{t('reports.alerts.topTitles')}</p>
                  <Table>
                    <THead>
                      <Th>{t('alerts.title')}</Th>
                      <Th>{t('reports.alerts.severity')}</Th>
                      <Th align="right">{t('reports.alerts.count')}</Th>
                      <Th align="right">{t('reports.alerts.occurrences')}</Th>
                    </THead>
                    <TBody>
                      {alerts.top_titles.map((row) => (
                        <Tr key={`${row.code}-${row.title}`}>
                          <Td className="font-medium">
                            {row.title}
                            {row.code ? <span className="ml-1 font-mono text-xs text-muted">{row.code}</span> : null}
                          </Td>
                          <Td><Badge tone={row.severity === 'critical' ? 'critical' : row.severity === 'major' ? 'major' : row.severity === 'warning' ? 'warning' : 'info'}>{t(`severity.${row.severity}`)}</Badge></Td>
                          <Td align="right" className="tnum">{row.count}</Td>
                          <Td align="right" className="tnum text-muted">{row.occurrences}</Td>
                        </Tr>
                      ))}
                    </TBody>
                  </Table>
                </div>
              </div>
            </>
          ) : (
            <p className="text-sm text-muted">{t('reports.alerts.none')}</p>
          )}
        </CardBody>
      </Card>

      <p className="text-xs text-subtle">
        {t('reports.generatedAt', { time: formatDateTime(report.generated_at), tz: report.timezone_name })}
      </p>
    </div>
  )
}

export default ReportsPage
