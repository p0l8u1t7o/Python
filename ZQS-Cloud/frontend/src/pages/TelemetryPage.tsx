import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download } from 'lucide-react'

import { useAllDevices, useMetrics, useSeries } from '@/lib/queries'
import { currentLanguage } from '@/i18n'
import { formatDateTime, formatInterval } from '@/lib/format'
import { RANGE_KEYS, useTimeRange, type RangeKey } from '@/lib/useTimeRange'
import type { SeriesResponse } from '@/lib/types'
import { TimeSeriesChart, seriesKey } from '@/components/charts/TimeSeriesChart'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SegmentedControl,
  TextInput,
} from '@/components/ui'

const MAX_SELECTION = 8

export function TelemetryPage() {
  const { t } = useTranslation()
  const range = useTimeRange('6h')
  const devices = useAllDevices()
  const metrics = useMetrics()

  const [deviceIds, setDeviceIds] = useState<string[]>([])
  const [metricKeys, setMetricKeys] = useState<string[]>([])
  const [deviceFilter, setDeviceFilter] = useState('')
  const [metricFilter, setMetricFilter] = useState('')

  const series = useSeries({
    device_ids: deviceIds,
    metrics: metricKeys,
    start: range.start,
    end: range.end,
    max_points: 1500,
  })

  const visibleDevices = useMemo(() => {
    const needle = deviceFilter.trim().toLowerCase()
    const list = devices.data?.items ?? []
    if (!needle) return list
    return list.filter(
      (device) =>
        device.name.toLowerCase().includes(needle) ||
        device.device_id.toLowerCase().includes(needle),
    )
  }, [devices.data, deviceFilter])

  const visibleMetrics = useMemo(() => {
    const needle = metricFilter.trim().toLowerCase()
    const list = metrics.data ?? []
    if (!needle) return list
    return list.filter(
      (metric) =>
        metric.key.toLowerCase().includes(needle) ||
        metric.label.toLowerCase().includes(needle),
    )
  }, [metrics.data, metricFilter])

  function toggle(list: string[], value: string, setter: (next: string[]) => void) {
    if (list.includes(value)) {
      setter(list.filter((item) => item !== value))
    } else if (list.length < MAX_SELECTION) {
      setter([...list, value])
    }
  }

  const ready = deviceIds.length > 0 && metricKeys.length > 0

  return (
    <>
      <PageHeader
        title={t('telemetry.title')}
        description={t('telemetry.subtitle')}
        actions={
          <>
            <SegmentedControl<RangeKey>
              size="sm"
              value={range.key}
              onChange={range.setKey}
              options={RANGE_KEYS.map((key) => ({ value: key, label: t(`range.${key}`) }))}
            />
            <Button
              icon={<Download className="size-4" />}
              disabled={!series.data || series.data.series.length === 0}
              onClick={() => series.data && downloadCsv(series.data)}
            >
              {t('telemetry.export')}
            </Button>
          </>
        }
      />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="lg:order-2">
          <CardHeader
            title={t('telemetry.selectDevices')}
            description={`${deviceIds.length}/${MAX_SELECTION}`}
          />
          <CardBody className="space-y-2">
            <TextInput
              value={deviceFilter}
              onChange={(event) => setDeviceFilter(event.target.value)}
              placeholder={t('common.search')}
            />
            <div className="max-h-52 space-y-1 overflow-y-auto pr-1">
              {visibleDevices.map((device) => {
                const active = deviceIds.includes(device.id)
                return (
                  <button
                    key={device.id}
                    type="button"
                    onClick={() => toggle(deviceIds, device.id, setDeviceIds)}
                    disabled={!active && deviceIds.length >= MAX_SELECTION}
                    className={`flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5
                      text-left text-sm transition-colors disabled:opacity-40 ${
                        active
                          ? 'bg-brand-soft text-brand'
                          : 'text-content hover:bg-surface-muted'
                      }`}
                  >
                    <span className="min-w-0 truncate">{device.name}</span>
                    <span className="shrink-0 font-mono text-[10px] text-subtle">
                      {device.device_id}
                    </span>
                  </button>
                )
              })}
              {visibleDevices.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted">{t('common.noResults')}</p>
              ) : null}
            </div>
          </CardBody>

          <CardHeader
            title={t('telemetry.selectMetrics')}
            description={`${metricKeys.length}/${MAX_SELECTION}`}
          />
          <CardBody className="space-y-2">
            <TextInput
              value={metricFilter}
              onChange={(event) => setMetricFilter(event.target.value)}
              placeholder={t('common.search')}
            />
            <div className="max-h-52 space-y-1 overflow-y-auto pr-1">
              {visibleMetrics.map((metric) => {
                const active = metricKeys.includes(metric.key)
                return (
                  <button
                    key={metric.key}
                    type="button"
                    onClick={() => toggle(metricKeys, metric.key, setMetricKeys)}
                    disabled={!active && metricKeys.length >= MAX_SELECTION}
                    className={`flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5
                      text-left text-sm transition-colors disabled:opacity-40 ${
                        active
                          ? 'bg-brand-soft text-brand'
                          : 'text-content hover:bg-surface-muted'
                      }`}
                  >
                    <span className="min-w-0 truncate">{metric.label}</span>
                    {metric.unit ? (
                      <span className="shrink-0 text-[10px] text-subtle">{metric.unit}</span>
                    ) : null}
                  </button>
                )
              })}
              {visibleMetrics.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted">{t('common.noResults')}</p>
              ) : null}
            </div>
          </CardBody>
        </Card>

        <Card className="lg:order-1">
          <CardHeader
            title={t('telemetry.chart')}
            description={
              series.data ? (
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone={series.data.downsampled ? 'info' : 'ok'}>
                    {series.data.downsampled
                      ? t('telemetry.downsampled', {
                          interval: formatInterval(series.data.interval_seconds),
                        })
                      : t('telemetry.raw')}
                  </Badge>
                  <span className="text-xs text-subtle">
                    {formatDateTime(series.data.start)} → {formatDateTime(series.data.end)}
                  </span>
                </span>
              ) : undefined
            }
          />
          <CardBody>
            {!ready ? (
              <EmptyState title={t('telemetry.noSelection')} />
            ) : series.isPending ? (
              <LoadingState />
            ) : series.error ? (
              <ErrorState error={series.error} onRetry={() => void series.refetch()} />
            ) : (
              <TimeSeriesChart
                series={series.data?.series ?? []}
                spanSeconds={range.seconds}
                height={420}
              />
            )}
          </CardBody>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader title={t('telemetry.metricCatalogue')} />
        <CardBody>
          {metrics.isPending ? (
            <LoadingState />
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {(metrics.data ?? []).map((metric) => (
                <div key={metric.key} className="rounded-lg border border-line p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-content">
                      {metric.translations[currentLanguage()] ?? metric.label}
                    </p>
                    <Badge tone={metric.is_builtin ? 'neutral' : 'brand'}>
                      {metric.is_builtin ? t('telemetry.builtin') : t('telemetry.custom')}
                    </Badge>
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-subtle">{metric.key}</p>
                  <p className="mt-1.5 flex flex-wrap gap-x-3 text-xs text-muted">
                    {metric.unit ? <span>{metric.unit}</span> : null}
                    <span>{metric.aggregation}</span>
                    {metric.min_value !== null || metric.max_value !== null ? (
                      <span className="tnum">
                        {metric.min_value ?? '−∞'} … {metric.max_value ?? '∞'}
                      </span>
                    ) : null}
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </>
  )
}

/**
 * Exports the exact rows the chart is showing.
 *
 * Series are merged onto one timestamp column so the file opens as a normal
 * wide table in a spreadsheet, which is what people actually do with it.
 */
function downloadCsv(response: SeriesResponse) {
  const columns = response.series.map(seriesKey)
  const rows = new Map<string, Record<string, number | null>>()

  for (const series of response.series) {
    const key = seriesKey(series)
    for (const point of series.points) {
      const existing = rows.get(point.ts) ?? {}
      existing[key] = point.value
      rows.set(point.ts, existing)
    }
  }

  const escape = (value: string) => (/[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value)

  const header = ['timestamp', ...columns].map(escape).join(',')
  const body = [...rows.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([ts, values]) =>
      [ts, ...columns.map((column) => (values[column] ?? '').toString())].map(escape).join(','),
    )

  const blob = new Blob([[header, ...body].join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `telemetry-${response.start.slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

export default TelemetryPage
