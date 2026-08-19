import { useEffect, useState } from 'react'

import { useTheme } from '@/providers/ThemeProvider'

export interface ChartColors {
  series: string[]
  grid: string
  axis: string
  surface: string
  border: string
  content: string
  ok: string
  warning: string
  critical: string
  info: string
  brand: string
}

const FALLBACK: ChartColors = {
  series: ['#0f766e', '#b45309', '#1d4ed8', '#9333ea', '#be123c', '#0891b2'],
  grid: '#e5e9f0',
  axis: '#5b6779',
  surface: '#ffffff',
  border: '#dfe4ec',
  content: '#0f172a',
  ok: '#15803d',
  warning: '#b45309',
  critical: '#b91c1c',
  info: '#1d4ed8',
  brand: '#0f766e',
}

function read(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/**
 * Resolves the palette to concrete colour strings.
 *
 * SVG presentation attributes do not accept `var(--x)`, so Recharts cannot be
 * handed CSS variables directly. Reading the computed values and re-reading
 * them whenever the theme flips keeps the charts in step with the rest of the
 * console.
 */
export function useChartColors(): ChartColors {
  const { resolved } = useTheme()
  const [colors, setColors] = useState<ChartColors>(FALLBACK)

  useEffect(() => {
    setColors({
      series: [
        read('--series-1', FALLBACK.series[0]),
        read('--series-2', FALLBACK.series[1]),
        read('--series-3', FALLBACK.series[2]),
        read('--series-4', FALLBACK.series[3]),
        read('--series-5', FALLBACK.series[4]),
        read('--series-6', FALLBACK.series[5]),
      ],
      grid: read('--grid-line', FALLBACK.grid),
      axis: read('--content-muted', FALLBACK.axis),
      surface: read('--surface', FALLBACK.surface),
      border: read('--border', FALLBACK.border),
      content: read('--content', FALLBACK.content),
      ok: read('--ok', FALLBACK.ok),
      warning: read('--warning', FALLBACK.warning),
      critical: read('--critical', FALLBACK.critical),
      info: read('--info', FALLBACK.info),
      brand: read('--brand', FALLBACK.brand),
    })
  }, [resolved])

  return colors
}
