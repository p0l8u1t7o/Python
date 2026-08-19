import type { ReactNode } from 'react'

type Accent = 'neutral' | 'brand' | 'ok' | 'info' | 'warning' | 'major' | 'critical'

const ACCENTS: Record<Accent, string> = {
  neutral: 'text-content',
  brand: 'text-brand',
  ok: 'text-ok',
  info: 'text-info',
  warning: 'text-warning',
  major: 'text-major',
  critical: 'text-critical',
}

export function StatTile({
  label,
  value,
  unit,
  hint,
  icon,
  accent = 'neutral',
  onClick,
}: {
  label: ReactNode
  value: ReactNode
  unit?: ReactNode
  hint?: ReactNode
  icon?: ReactNode
  accent?: Accent
  onClick?: () => void
}) {
  const interactive = Boolean(onClick)
  const Wrapper = interactive ? 'button' : 'div'

  return (
    <Wrapper
      {...(interactive ? { type: 'button' as const, onClick } : {})}
      className={`card w-full p-4 text-left ${
        interactive ? 'transition-colors hover:border-line-strong hover:bg-surface-muted/50' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-muted">{label}</p>
        {icon ? <span className={`shrink-0 ${ACCENTS[accent]}`}>{icon}</span> : null}
      </div>
      <p className={`mt-2 flex items-baseline gap-1 ${ACCENTS[accent]}`}>
        <span className="text-2xl font-semibold tracking-tight tnum">{value}</span>
        {unit ? <span className="text-sm font-medium text-muted">{unit}</span> : null}
      </p>
      {hint ? <p className="mt-1 text-xs text-subtle">{hint}</p> : null}
    </Wrapper>
  )
}

/** Horizontal gauge used for SOC and other 0–100 % readings. */
export function MeterBar({
  value,
  min = 0,
  max = 100,
  accent = 'brand',
  className = '',
  markers = [],
}: {
  value: number | null
  min?: number
  max?: number
  accent?: Accent
  className?: string
  markers?: { value: number; label?: string }[]
}) {
  const clamped =
    value === null ? 0 : Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100))

  const fill: Record<Accent, string> = {
    neutral: 'bg-muted',
    brand: 'bg-brand',
    ok: 'bg-ok',
    info: 'bg-info',
    warning: 'bg-warning',
    major: 'bg-major',
    critical: 'bg-critical',
  }

  return (
    <div
      className={`relative h-2 w-full overflow-hidden rounded-full bg-surface-muted ${className}`}
      role="meter"
      aria-valuenow={value ?? undefined}
      aria-valuemin={min}
      aria-valuemax={max}
    >
      <div
        className={`h-full rounded-full transition-[width] duration-500 ${fill[accent]}`}
        style={{ width: `${clamped}%` }}
      />
      {markers.map((marker) => (
        <span
          key={marker.value}
          title={marker.label}
          className="absolute top-0 h-full w-px bg-line-strong"
          style={{ left: `${Math.min(100, Math.max(0, ((marker.value - min) / (max - min)) * 100))}%` }}
        />
      ))}
    </div>
  )
}
