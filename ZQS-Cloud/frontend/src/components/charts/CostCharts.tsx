import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatCurrency, formatNumber, truncate } from '@/lib/format'
import type { CostBreakdownRow, SiteCost } from '@/lib/types'
import { useChartColors } from './chartTheme'

/**
 * Cost and savings side by side, one pair of bars per site.
 *
 * Grouped rather than stacked. Stacking would put savings on top of cost and
 * invite the reading "this is what we spent in total", which is the opposite
 * of what savings means - and it makes a *negative* savings figure impossible
 * to draw at all.
 *
 * Negative savings are drawn, in the alert colour. A dispatch that cost more
 * than doing nothing is a real result and one an operator needs to see; a
 * chart that clamps it at zero is vouching for a bad decision.
 */
export function SiteCostChart({
  sites,
  currency,
  height = 260,
}: {
  sites: SiteCost[]
  currency?: string
  height?: number
}) {
  const { t } = useTranslation()
  const colors = useChartColors()

  const rows = useMemo(
    () =>
      sites
        // Sites that neither spent nor saved anything add a bare axis label and
        // nothing else, so they are left out rather than padding the chart.
        .filter((site) => site.energy_cost !== 0 || site.estimated_savings !== 0)
        .map((site) => ({
          name: truncate(site.site_name, 18),
          fullName: site.site_name,
          cost: Number(site.energy_cost.toFixed(2)),
          savings: Number(site.estimated_savings.toFixed(2)),
        }))
        .sort((a, b) => b.cost - a.cost),
    [sites],
  )

  if (rows.length === 0) {
    return <p className="py-8 text-center text-sm text-muted">{t('common.noData')}</p>
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
        <CartesianGrid stroke={colors.grid} vertical={false} />
        <XAxis
          dataKey="name"
          stroke={colors.axis}
          tick={{ fontSize: 11, fill: colors.axis }}
          tickLine={false}
          axisLine={{ stroke: colors.grid }}
          interval={0}
          angle={rows.length > 5 ? -20 : 0}
          textAnchor={rows.length > 5 ? 'end' : 'middle'}
          height={rows.length > 5 ? 52 : 30}
        />
        <YAxis
          stroke={colors.axis}
          tick={{ fontSize: 11, fill: colors.axis }}
          tickLine={false}
          axisLine={false}
          width={64}
          tickFormatter={(value: number) => formatNumber(value, { notation: 'compact' })}
        />
        <Tooltip
          cursor={{ fill: colors.grid, opacity: 0.35 }}
          contentStyle={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 10,
            fontSize: 12,
            color: colors.content,
          }}
          formatter={(value: number, name: string) => [
            formatCurrency(value, currency),
            name,
          ]}
          labelFormatter={(_label, payload) =>
            payload?.[0]?.payload?.fullName ?? _label
          }
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar
          dataKey="cost"
          name={t('storage.cost')}
          fill={colors.series[0]}
          radius={[3, 3, 0, 0]}
          maxBarSize={38}
        />
        <Bar
          dataKey="savings"
          name={t('storage.savings')}
          radius={[3, 3, 0, 0]}
          maxBarSize={38}
        >
          {rows.map((row) => (
            <Cell
              key={row.fullName}
              fill={row.savings < 0 ? colors.critical : colors.ok}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/**
 * What each source contributed to a site's bill.
 *
 * Horizontal, because a source name is a word and words read better along the
 * axis than rotated under it. Export revenue arrives as a negative amount and
 * is drawn to the left of zero, which is the honest place for money coming in.
 */
export function CostSourceChart({
  rows,
  currency,
  height = 200,
}: {
  rows: CostBreakdownRow[]
  currency?: string
  height?: number
}) {
  const { t } = useTranslation()
  const colors = useChartColors()

  const data = useMemo(
    () =>
      rows.map((row) => ({
        name: t(`ems.costSources.${row.source}`, { defaultValue: row.source }),
        amount: Number(row.amount.toFixed(2)),
        estimated: row.basis !== 'measured',
      })),
    [rows, t],
  )

  if (data.length === 0) {
    return <p className="py-8 text-center text-sm text-muted">{t('common.noData')}</p>
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 12, left: 4, bottom: 4 }}
      >
        <CartesianGrid stroke={colors.grid} horizontal={false} />
        <XAxis
          type="number"
          stroke={colors.axis}
          tick={{ fontSize: 11, fill: colors.axis }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(value: number) => formatNumber(value, { notation: 'compact' })}
        />
        <YAxis
          type="category"
          dataKey="name"
          stroke={colors.axis}
          tick={{ fontSize: 11, fill: colors.axis }}
          tickLine={false}
          axisLine={false}
          width={92}
        />
        <Tooltip
          cursor={{ fill: colors.grid, opacity: 0.35 }}
          contentStyle={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 10,
            fontSize: 12,
            color: colors.content,
          }}
          formatter={(value: number) => formatCurrency(value, currency)}
        />
        <Bar dataKey="amount" radius={[0, 3, 3, 0]} maxBarSize={26}>
          {data.map((row, index) => (
            <Cell
              key={row.name}
              fill={row.amount < 0 ? colors.ok : colors.series[index % colors.series.length]}
              // A modelled figure is drawn slightly faded, so a bill built on
              // an assumed fuel price does not look as solid as a metered one.
              fillOpacity={row.estimated ? 0.65 : 1}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
