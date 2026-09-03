import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

export type Tone = 'neutral' | 'brand' | 'ok' | 'info' | 'warning' | 'critical'

const TONES: Record<Tone, string> = {
  neutral: 'bg-surface-muted text-muted',
  brand: 'bg-brand-soft text-brand',
  ok: 'bg-ok-soft text-ok',
  info: 'bg-info-soft text-info',
  warning: 'bg-warning-soft text-warning',
  critical: 'bg-critical-soft text-critical',
}

export function Badge({ tone = 'neutral', children, className = '', title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]} ${className}`}>{children}</span>
}

/** run / node 狀態 → 色調。ng 用橘（是判定，不是程式錯）；failed/error 才用紅。 */
export const STATUS_TONE: Record<string, Tone> = {
  ok: 'ok',
  ng: 'warning',
  failed: 'critical',
  error: 'critical',
  cancelled: 'neutral',
  skipped: 'neutral',
  running: 'brand',
}

export function StatusBadge({ status, className = '' }: { status: string | null | undefined; className?: string }) {
  const { t } = useTranslation()
  const key = status || 'none'
  return (
    <Badge tone={STATUS_TONE[key] ?? 'neutral'} className={className}>
      {t(`status.${key}`, { defaultValue: key })}
    </Badge>
  )
}
