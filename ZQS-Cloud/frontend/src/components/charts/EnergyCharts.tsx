import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatAxisTime, formatDateTime, formatNumber } from '@/lib/format'
import type { EnergyInterval } from '@/lib/types'
import { useChartColors } from './chartTheme'

interface Row {
  ts: number
  gridImport: number
  gridExport: number
  pv: number
  charge: number
  discharge: number
  load: number
  soc: number | null
  savings: number
  cost: number
}

function toRows(intervals: EnergyInterval[]): Row[] {
  return intervals
    .map((interval) => ({
      ts: new Date(interval.interval_start).getTime(),
      gridImport: interval.grid_import_kwh,
      // Export and charge point downwards so the stack reads as a balance:
      // what the site drew above the axis, what it gave back below it.
      gridExport: -interval.grid_export_kwh,
      pv: interval.pv_kwh,
      charge: -interval.battery_charge_kwh,
      discharge: interval.battery_discharge_kwh,
      load: interval.load_kwh,
      soc: interval.soc_end_percent,
      savings: interval.estimated_savings,
      cost: interval.energy_cost,
    }))
    .sort((a, b) => a.ts - b.ts)
}

function useAxisProps(spanSeconds: number) {
  const colors = useChartColors()
  return {
    colors,
    xAxis: {
      dataKey: 'ts',
      type: 'number' as const,
      scale: 'time' as const,
      domain: ['dataMin', 'dataMax'] as [string, string],
      tickFormatter: (value: number) => formatAxisTime(value, spanSeconds),
      stroke: colors.axis,
      tick: { fontSize: 11, fill: colors.axis },
      tickLine: false,
      axisLine: { stroke: colors.grid },
      minTickGap: 40,
    },
    tooltip: {
      contentStyle: {
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        fontSize: 12,
        color: colors.content,
      },
      labelFormatter: (value: string | number) => formatDateTime(new Date(Number(value))),
    },
  }
}

export function EnergyBalanceChart({
  intervals,
  spanSeconds,
  height = 280,
}: {
  intervals: EnergyInterval[]
  spanSeconds: number
  height?: number
}) {
  const { t } = useTranslation()
  const rows = useMemo(() => toRows(intervals), [intervals])
  const { colors, xAxis, tooltip } = useAxisProps(spanSeconds)

  const bars: { key: keyof Row; labelKey: string; color: string }[] = [
    { key: 'gridImport', labelKey: 'storage.gridImport', color: colors.series[1] },
    { key: 'discharge', labelKey: 'storage.batteryDischarge', color: colors.series[0] },
    { key: 'pv', labelKey: 'storage.generation', color: colors.warning },
    { key: 'charge', labelKey: 'storage.batteryCharge', color: colors.series[3] },
    { key: 'gridExport', labelKey: 'storage.gridExport', color: colors.series[2] },
  ]

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 4 }} stackOffset="sign">
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis {...xAxis} />
        <YAxis
          stroke={colors.axis}
          tick={{ fontSize: 11, fill: colors.axis }}
          tickLine={false}
          axisLine={false}
          width={56}
          tickFormatter={(value: number) => formatNumber(value, { maximumFractionDigits: 1 })}
          label={{
            value: 'kWh',
            angle: -90,
            position: 'insideLeft',
            style: { fontSize: 11, fill: colors.axis },
          }}
        />
        <ReferenceLine y={0} stroke={colors.axis} strokeWidth={1} />
        <Tooltip
          {...tooltip}
          formatter={(value: number, name: string) => [
            `${formatNumber(Math.abs(value))} kWh`,
            t(bars.find((bar) => bar.key === name)?.labelKey ?? name),
          ]}
        />
        <Legend
          wrapperStyle={{ fontSize: 12, color: colors.axis, paddingTop: 8 }}
          formatter={(name: string) => t(bars.find((bar) => bar.key === name)?.labelKey ?? name)}
        />
        {bars.map((bar) => (
          <Bar
            key={bar.key}
            dataKey={bar.key}
            stackId="energy"
            fill={bar.color}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

export function SocChart({
  intervals,
  spanSeconds,
  height = 200,
  minSoc,
  reserve,
}: {
  intervals: EnergyInterval[]
  spanSeconds: number
  height?: number
  minSoc?: number | null
  reserve?: number | null
}) {
  const rows = useMemo(() => toRows(intervals).filter((row) => row.soc !== null), [intervals])
  const { colors, xAxis, tooltip } = useAxisProps(spanSeconds)
  const { t } = useTranslation()

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center text-sm text-muted" style={{ height }}>
        {t('common.noData')}
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
        <defs>
          <linearGradient id="socFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={colors.brand} stopOpacity={0.35} />
            <stop offset="100%" stopColor={colors.brand} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis {...xAxis} />
        <YAxis
          domain={[0, 100]}
          stroke={colors.axis}
          tick={{ fontSize: 11, fill: colors.axis }}
          tickLine={false}
          axisLine={false}
          width={44}
          tickFormatter={(value: number) => `${value}%`}
        />
        {typeof reserve === 'number' ? (
          <ReferenceLine
            y={reserve}
            stroke={colors.warning}
            strokeDasharray="4 4"
            label={{ value: 'reserve', fontSize: 10, fill: colors.warning, position: 'insideTopRight' }}
          />
        ) : null}
        {typeof minSoc === 'number' ? (
          <ReferenceLine y={minSoc} stroke={colors.critical} strokeDasharray="4 4" />
        ) : null}
        <Tooltip {...tooltip} formatter={(value: number) => [`${formatNumber(value)} %`, t('storage.soc')]} />
        <Area
          type="monotone"
          dataKey="soc"
          stroke={colors.brand}
          strokeWidth={1.75}
          fill="url(#socFill)"
          isAnimationActive={false}
          connectNulls
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

export function CostChart({
  intervals,
  spanSeconds,
  currency,
  height = 200,
}: {
  intervals: EnergyInterval[]
  spanSeconds: number
  currency?: string
  height?: number
}) {
  const { t } = useTranslation()
  const rows = useMemo(() => toRows(intervals), [intervals])
  const { colors, xAxis, tooltip } = useAxisProps(spanSeconds)

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
        <XAxis {...xAxis} />
        <YAxis
          stroke={colors.axis}
          tick={{ fontSize: 11, fill: colors.axis }}
          tickLine={false}
          axisLine={false}
          width={56}
          tickFormatter={(value: number) => formatNumber(value, { maximumFractionDigits: 0 })}
          label={
            currency
              ? {
                  value: currency,
                  angle: -90,
                  position: 'insideLeft',
                  style: { fontSize: 11, fill: colors.axis },
                }
              : undefined
          }
        />
        <Tooltip
          {...tooltip}
          formatter={(value: number, name: string) => [
            formatNumber(value, { maximumFractionDigits: 1 }),
            name === 'cost' ? t('storage.cost') : t('storage.savings'),
          ]}
        />
        <Legend
          wrapperStyle={{ fontSize: 12, color: colors.axis, paddingTop: 8 }}
          formatter={(name: string) => (name === 'cost' ? t('storage.cost') : t('storage.savings'))}
        />
        <Bar dataKey="cost" fill={colors.series[1]} isAnimationActive={false} />
        <Bar dataKey="savings" fill={colors.ok} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  )
}
