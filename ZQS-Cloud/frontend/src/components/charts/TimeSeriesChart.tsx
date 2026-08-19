import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatAxisTime, formatDateTime, formatNumber } from '@/lib/format'
import type { Series } from '@/lib/types'
import { useChartColors } from './chartTheme'

interface Row {
  ts: number
  [key: string]: number | null
}

export function seriesKey(series: Series): string {
  return `${series.device_external_id || series.device_id}·${series.metric_key}`
}

/**
 * Merges several series onto one time axis.
 *
 * Devices sample independently, so timestamps rarely line up. Rows are keyed by
 * exact timestamp and gaps stay `null` — with `connectNulls` off, that draws an
 * honest break in the line instead of inventing a straight segment across an
 * outage.
 */
function toRows(series: Series[]): Row[] {
  const byTimestamp = new Map<number, Row>()

  for (const item of series) {
    const key = seriesKey(item)
    for (const point of item.points) {
      const ts = new Date(point.ts).getTime()
      if (Number.isNaN(ts)) continue
      let row = byTimestamp.get(ts)
      if (!row) {
        row = { ts }
        byTimestamp.set(ts, row)
      }
      row[key] = point.value
    }
  }

  return [...byTimestamp.values()].sort((a, b) => a.ts - b.ts)
}

export function TimeSeriesChart({
  series,
  spanSeconds,
  height = 300,
  showLegend = true,
}: {
  series: Series[]
  spanSeconds: number
  height?: number
  showLegend?: boolean
}) {
  const colors = useChartColors()
  const { t } = useTranslation()
  const rows = useMemo(() => toRows(series), [series])

  // One axis per distinct unit; mixing kW and % on a shared scale is unreadable.
  const units = useMemo(() => {
    const seen: string[] = []
    for (const item of series) {
      const unit = item.unit || ''
      if (!seen.includes(unit)) seen.push(unit)
    }
    return seen.slice(0, 2)
  }, [series])

  if (rows.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-muted"
        style={{ height }}
      >
        {t('telemetry.noSeries')}
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="ts"
          type="number"
          scale="time"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(value: number) => formatAxisTime(value, spanSeconds)}
          stroke={colors.axis}
          tick={{ fontSize: 11, fill: colors.axis }}
          tickLine={false}
          axisLine={{ stroke: colors.grid }}
          minTickGap={40}
        />
        {units.map((unit, index) => (
          <YAxis
            key={unit || `unit-${index}`}
            yAxisId={unit}
            orientation={index === 0 ? 'left' : 'right'}
            stroke={colors.axis}
            tick={{ fontSize: 11, fill: colors.axis }}
            tickLine={false}
            axisLine={false}
            width={56}
            tickFormatter={(value: number) => formatNumber(value, { maximumFractionDigits: 1 })}
            label={
              unit
                ? {
                    value: unit,
                    angle: -90,
                    position: index === 0 ? 'insideLeft' : 'insideRight',
                    style: { fontSize: 11, fill: colors.axis },
                  }
                : undefined
            }
          />
        ))}
        <Tooltip
          contentStyle={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 10,
            fontSize: 12,
            color: colors.content,
          }}
          labelFormatter={(value) => formatDateTime(new Date(Number(value)))}
          formatter={(value, name) => {
            const item = series.find((entry) => seriesKey(entry) === String(name))
            const numeric = typeof value === 'number' ? value : null
            return [
              numeric === null ? '—' : `${formatNumber(numeric)} ${item?.unit ?? ''}`.trim(),
              item ? `${item.device_external_id} · ${item.label}` : String(name),
            ]
          }}
        />
        {showLegend ? (
          <Legend
            wrapperStyle={{ fontSize: 12, color: colors.axis, paddingTop: 8 }}
            formatter={(name: string) => {
              const item = series.find((entry) => seriesKey(entry) === name)
              return item ? `${item.device_external_id} · ${item.label}` : name
            }}
          />
        ) : null}
        {series.map((item, index) => (
          <Line
            key={seriesKey(item)}
            yAxisId={units.includes(item.unit || '') ? item.unit || '' : units[0]}
            type="monotone"
            dataKey={seriesKey(item)}
            stroke={colors.series[index % colors.series.length]}
            strokeWidth={1.75}
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
