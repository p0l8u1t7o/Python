import { useTranslation } from 'react-i18next'
import { BatteryCharging, Factory, Home, Sun } from 'lucide-react'

import { formatMeasurement, formatPercent } from '@/lib/format'
import type { PowerFlow } from '@/lib/types'
import { MeterBar } from '@/components/ui'
import { useChartColors } from './chartTheme'

/**
 * Live site power balance.
 *
 * Sign convention (same as the backend): grid > 0 imports, battery > 0
 * discharges. Each edge animates in the direction energy is actually moving,
 * so the diagram reads at a glance without checking a legend.
 */

interface NodeSpec {
  id: 'pv' | 'grid' | 'battery' | 'load'
  labelKey: string
  icon: typeof Sun
  x: number
  y: number
}

const NODES: NodeSpec[] = [
  { id: 'pv', labelKey: 'storage.pv', icon: Sun, x: 160, y: 26 },
  { id: 'grid', labelKey: 'storage.grid', icon: Factory, x: 26, y: 130 },
  { id: 'battery', labelKey: 'storage.battery', icon: BatteryCharging, x: 294, y: 130 },
  { id: 'load', labelKey: 'storage.load', icon: Home, x: 160, y: 234 },
]

const CENTER = { x: 160, y: 130 }

function Edge({
  from,
  color,
  active,
  reverse,
}: {
  from: NodeSpec
  color: string
  active: boolean
  reverse: boolean
}) {
  // Draw from the node towards the centre; reverse flips the dash animation so
  // the movement points the other way without duplicating the path.
  const d = `M ${from.x} ${from.y} L ${CENTER.x} ${CENTER.y}`
  return (
    <g>
      <path d={d} stroke="var(--border)" strokeWidth={3} fill="none" strokeLinecap="round" />
      {active ? (
        <path
          d={d}
          stroke={color}
          strokeWidth={3}
          fill="none"
          strokeLinecap="round"
          strokeDasharray="7 9"
          style={{
            animation: `flow-dash 1.1s linear infinite${reverse ? ' reverse' : ''}`,
          }}
        />
      ) : null}
    </g>
  )
}

export function PowerFlowDiagram({ flow }: { flow: PowerFlow }) {
  const { t } = useTranslation()
  const colors = useChartColors()

  const gridKw = flow.grid_kw ?? 0
  const pvKw = flow.pv_kw ?? 0
  const batteryKw = flow.battery_kw ?? 0
  const loadKw = flow.load_kw ?? 0

  const edgeColor: Record<NodeSpec['id'], string> = {
    pv: colors.warning,
    grid: gridKw >= 0 ? colors.series[1] : colors.ok,
    battery: batteryKw >= 0 ? colors.brand : colors.info,
    load: colors.series[2],
  }

  const active: Record<NodeSpec['id'], boolean> = {
    pv: Math.abs(pvKw) > 0.05,
    grid: Math.abs(gridKw) > 0.05,
    battery: Math.abs(batteryKw) > 0.05,
    load: Math.abs(loadKw) > 0.05,
  }

  // Reverse means energy travels from the centre outwards.
  const reversed: Record<NodeSpec['id'], boolean> = {
    pv: false,
    grid: gridKw < 0,
    battery: batteryKw < 0,
    load: true,
  }

  const values: Record<NodeSpec['id'], number> = {
    pv: pvKw,
    grid: gridKw,
    battery: batteryKw,
    load: loadKw,
  }

  const captions: Record<NodeSpec['id'], string> = {
    pv: '',
    grid: gridKw > 0.05 ? t('storage.importing') : gridKw < -0.05 ? t('storage.exporting') : t('storage.idle'),
    battery:
      batteryKw > 0.05
        ? t('storage.discharging')
        : batteryKw < -0.05
          ? t('storage.charging')
          : t('storage.idle'),
    load: '',
  }

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
      <style>{`@keyframes flow-dash { to { stroke-dashoffset: -32; } }`}</style>

      <div className="relative mx-auto w-full max-w-[340px] shrink-0">
        <svg viewBox="0 0 320 264" className="w-full" role="img" aria-label={t('storage.powerFlow')}>
          {NODES.map((node) => (
            <Edge
              key={node.id}
              from={node}
              color={edgeColor[node.id]}
              active={active[node.id]}
              reverse={reversed[node.id]}
            />
          ))}
          <circle cx={CENTER.x} cy={CENTER.y} r={7} fill="var(--surface)" stroke="var(--border-strong)" strokeWidth={2} />
        </svg>

        {NODES.map((node) => {
          const Icon = node.icon
          return (
            <div
              key={node.id}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${(node.x / 320) * 100}%`, top: `${(node.y / 264) * 100}%` }}
            >
              <div className="flex flex-col items-center gap-1">
                <span
                  className="grid size-11 place-items-center rounded-xl border border-line bg-surface shadow-sm"
                  style={{ color: edgeColor[node.id] }}
                >
                  <Icon className="size-5" aria-hidden />
                </span>
                <span className="text-[11px] font-medium text-muted">{t(node.labelKey)}</span>
                <span className="text-xs font-semibold text-content tnum whitespace-nowrap">
                  {formatMeasurement(Math.abs(values[node.id]), 'kW', 1)}
                </span>
                {captions[node.id] ? (
                  <span className="text-[10px] text-subtle whitespace-nowrap">
                    {captions[node.id]}
                  </span>
                ) : null}
              </div>
            </div>
          )
        })}
      </div>

      <div className="flex-1 space-y-4">
        <div>
          <div className="mb-1.5 flex items-baseline justify-between gap-2">
            <span className="text-xs font-medium text-muted">{t('storage.soc')}</span>
            <span className="text-sm font-semibold text-content tnum">
              {formatPercent(flow.battery_soc_percent, { alreadyPercent: true, decimals: 1 })}
            </span>
          </div>
          <MeterBar
            value={flow.battery_soc_percent}
            accent={
              (flow.battery_soc_percent ?? 100) < 15
                ? 'critical'
                : (flow.battery_soc_percent ?? 100) < 30
                  ? 'warning'
                  : 'brand'
            }
          />
        </div>

        {flow.battery_soh_percent !== null ? (
          <div>
            <div className="mb-1.5 flex items-baseline justify-between gap-2">
              <span className="text-xs font-medium text-muted">{t('storage.soh')}</span>
              <span className="text-sm font-semibold text-content tnum">
                {formatPercent(flow.battery_soh_percent, { alreadyPercent: true, decimals: 1 })}
              </span>
            </div>
            <MeterBar value={flow.battery_soh_percent} accent="info" />
          </div>
        ) : null}
      </div>
    </div>
  )
}
