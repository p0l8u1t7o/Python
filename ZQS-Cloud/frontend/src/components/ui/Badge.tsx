import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { AlertStatus, CommandStatus, ConnectionStatus, EventLevel, Severity } from '@/lib/types'

type Tone = 'neutral' | 'brand' | 'ok' | 'info' | 'warning' | 'major' | 'critical'

const TONES: Record<Tone, string> = {
  neutral: 'bg-surface-muted text-muted',
  brand: 'bg-brand-soft text-brand',
  ok: 'bg-ok-soft text-ok',
  info: 'bg-info-soft text-info',
  warning: 'bg-warning-soft text-warning',
  major: 'bg-major-soft text-major',
  critical: 'bg-critical-soft text-critical',
}

export function Badge({
  tone = 'neutral',
  children,
  className = '',
}: {
  tone?: Tone
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium
        whitespace-nowrap ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  )
}

const CONNECTION_TONE: Record<ConnectionStatus, Tone> = {
  online: 'ok',
  offline: 'critical',
  unknown: 'neutral',
}

export function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  const { t } = useTranslation()
  return (
    <Badge tone={CONNECTION_TONE[status]}>
      <span
        aria-hidden
        className="size-1.5 rounded-full bg-current"
        // A steady dot for offline, a pulsing one for a live connection.
        style={status === 'online' ? { animation: 'pulse 2s ease-in-out infinite' } : undefined}
      />
      {t(`status.${status}`)}
    </Badge>
  )
}

export const SEVERITY_TONE: Record<Severity, Tone> = {
  info: 'info',
  warning: 'warning',
  major: 'major',
  critical: 'critical',
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation()
  return <Badge tone={SEVERITY_TONE[severity]}>{t(`severity.${severity}`)}</Badge>
}

const ALERT_STATUS_TONE: Record<AlertStatus, Tone> = {
  firing: 'critical',
  acknowledged: 'warning',
  resolved: 'ok',
}

export function AlertStatusBadge({ status }: { status: AlertStatus }) {
  const { t } = useTranslation()
  return <Badge tone={ALERT_STATUS_TONE[status]}>{t(`alerts.${status}`)}</Badge>
}

const COMMAND_TONE: Record<CommandStatus, Tone> = {
  pending: 'neutral',
  sent: 'info',
  accepted: 'info',
  succeeded: 'ok',
  rejected: 'major',
  failed: 'critical',
  expired: 'warning',
  cancelled: 'neutral',
}

export function CommandStatusBadge({ status }: { status: CommandStatus }) {
  const { t } = useTranslation()
  return <Badge tone={COMMAND_TONE[status]}>{t(`commands.statuses.${status}`)}</Badge>
}

const LEVEL_TONE: Record<EventLevel, Tone> = {
  debug: 'neutral',
  info: 'info',
  notice: 'info',
  warning: 'warning',
  error: 'major',
  critical: 'critical',
}

export function EventLevelBadge({ level }: { level: EventLevel }) {
  const { t } = useTranslation()
  return <Badge tone={LEVEL_TONE[level]}>{t(`events.levels.${level}`)}</Badge>
}
