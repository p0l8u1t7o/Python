import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Inbox, Loader2 } from 'lucide-react'

import { errorMessage } from '@/lib/errors'
import { Button } from './Button'

export function Spinner({ className = 'size-5' }: { className?: string }) {
  return <Loader2 className={`animate-spin text-muted ${className}`} aria-hidden />
}

export function LoadingState({ label }: { label?: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted">
      <Spinner className="size-4" />
      {label ?? `${t('common.loading')}…`}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-12 text-center">
      <AlertCircle className="size-6 text-critical" aria-hidden />
      <p className="max-w-md text-sm text-content">{errorMessage(error)}</p>
      {onRetry ? (
        <Button size="sm" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      ) : null}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: ReactNode
  description?: ReactNode
  icon?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <span className="text-subtle" aria-hidden>
        {icon ?? <Inbox className="size-6" />}
      </span>
      <p className="text-sm font-medium text-content">{title}</p>
      {description ? (
        <p className="max-w-md text-sm text-muted leading-relaxed">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}

/** Placeholder that reserves the final layout while data loads. */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-surface-muted ${className}`} />
}
