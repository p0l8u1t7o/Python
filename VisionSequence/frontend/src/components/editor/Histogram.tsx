/** 自畫 SVG 長條圖：灰階直方圖（256 bins）與數值分布（自動分箱）。不依賴 recharts，小而快。 */
import { useMemo } from 'react'

export function Histogram({ bins, height = 72, color = 'var(--brand)', title, labels }: { bins: number[]; height?: number; color?: string; title?: string; labels?: [string, string] }) {
  const width = 256
  const max = useMemo(() => bins.reduce((m, v) => (v > m ? v : m), 0), [bins])
  const n = bins.length || 1
  const step = width / n
  return (
    <figure className="m-0" data-testid="histogram">
      {title ? <figcaption className="mb-1 text-[11px] text-muted">{title}</figcaption> : null}
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="block h-auto w-full rounded border border-line bg-surface-muted/40" style={{ height }} role="img" aria-label={title}>
        {max > 0
          ? bins.map((v, i) => {
              if (!v) return null
              const h = Math.max(0.5, (v / max) * (height - 2))
              return <rect key={i} x={i * step} y={height - h} width={Math.max(step, 0.8)} height={h} fill={color} opacity={0.85} />
            })
          : null}
      </svg>
      {labels ? (
        <div className="flex justify-between font-mono text-[10px] text-subtle">
          <span>{labels[0]}</span>
          <span>{labels[1]}</span>
        </div>
      ) : null}
    </figure>
  )
}

/** 把數值序列分成 bins 箱。 */
export function binValues(values: number[], bins = 32): { counts: number[]; min: number; max: number } {
  if (!values.length) return { counts: [], min: 0, max: 0 }
  let min = Infinity
  let max = -Infinity
  for (const v of values) {
    if (v < min) min = v
    if (v > max) max = v
  }
  const counts = new Array<number>(bins).fill(0)
  const span = max - min || 1
  for (const v of values) {
    const i = Math.min(bins - 1, Math.floor(((v - min) / span) * bins))
    counts[i] += 1
  }
  return { counts, min, max }
}

export function fmtNum(v: number): string {
  if (!Number.isFinite(v)) return '—'
  return Number.isInteger(v) ? String(v) : Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(3)
}
