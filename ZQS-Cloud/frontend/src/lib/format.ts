/** Locale-aware formatting helpers shared by every page. */

import { currentLanguage } from '@/i18n'

function locale(): string {
  return currentLanguage()
}

export function formatNumber(
  value: number | null | undefined,
  options: Intl.NumberFormatOptions = {},
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat(locale(), {
    maximumFractionDigits: 2,
    ...options,
  }).format(value)
}

/** Adds the unit, and gives large/small magnitudes a sensible SI prefix. */
export function formatMeasurement(
  value: number | null | undefined,
  unit: string,
  decimals = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'

  let scaled = value
  let suffix = unit

  if (unit === 'W' || unit === 'VA' || unit === 'var') {
    const magnitude = Math.abs(value)
    if (magnitude >= 1_000_000) {
      scaled = value / 1_000_000
      suffix = `M${unit}`
    } else if (magnitude >= 1_000) {
      scaled = value / 1_000
      suffix = `k${unit}`
    }
  } else if (unit === 'kWh' && Math.abs(value) >= 1_000) {
    scaled = value / 1_000
    suffix = 'MWh'
  }

  const text = formatNumber(scaled, {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  })
  return suffix ? `${text} ${suffix}` : text
}

export function formatPercent(
  ratio: number | null | undefined,
  { alreadyPercent = false, decimals = 1 } = {},
): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return '—'
  const value = alreadyPercent ? ratio / 100 : ratio
  return new Intl.NumberFormat(locale(), {
    style: 'percent',
    maximumFractionDigits: decimals,
  }).format(value)
}

export function formatCurrency(
  value: number | null | undefined,
  currency: string | undefined,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  if (!currency) return formatNumber(value, { maximumFractionDigits: 2 })
  try {
    return new Intl.NumberFormat(locale(), {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format(value)
  } catch {
    // Unknown ISO code from a tenant-defined tariff; degrade to a plain number.
    return `${formatNumber(value, { maximumFractionDigits: 0 })} ${currency}`
  }
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(locale(), {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(date)
}

export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(locale(), { dateStyle: 'medium' }).format(date)
}

export function formatTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(locale(), { timeStyle: 'short' }).format(date)
}

/** Axis labels: minutes for short windows, dates once a chart spans days. */
export function formatAxisTime(value: string | number, spanSeconds: number): string {
  const date = typeof value === 'number' ? new Date(value) : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  if (spanSeconds <= 2 * 24 * 3600) {
    return new Intl.DateTimeFormat(locale(), {
      hour: '2-digit',
      minute: '2-digit',
    }).format(date)
  }
  return new Intl.DateTimeFormat(locale(), { month: 'short', day: 'numeric' }).format(date)
}

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
]

export function formatRelative(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return '—'

  const seconds = (date.getTime() - Date.now()) / 1000
  const formatter = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' })
  for (const [unit, size] of RELATIVE_UNITS) {
    if (Math.abs(seconds) >= size || unit === 'second') {
      return formatter.format(Math.round(seconds / size), unit)
    }
  }
  return formatter.format(0, 'second')
}

/** Compact duration such as "2 h 15 m", used for staleness and uptime. */
export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds === null || totalSeconds === undefined || Number.isNaN(totalSeconds)) {
    return '—'
  }
  const seconds = Math.max(0, Math.round(totalSeconds))
  if (seconds < 60) return `${seconds}s`

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    const remainder = minutes % 60
    return remainder ? `${hours}h ${remainder}m` : `${hours}h`
  }
  const days = Math.floor(hours / 24)
  const remainderHours = hours % 24
  return remainderHours ? `${days}d ${remainderHours}h` : `${days}d`
}

export function secondsSince(value: string | null | undefined): number | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return (Date.now() - date.getTime()) / 1000
}

/** Human label for a bucket width returned by the series endpoint. */
export function formatInterval(seconds: number): string {
  if (seconds <= 0) return '—'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`
  return `${Math.round(seconds / 86400)}d`
}

export function truncate(value: string, max = 60): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}
