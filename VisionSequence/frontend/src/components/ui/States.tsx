import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Inbox, Loader2 } from 'lucide-react'

import { errorMessage } from '@/lib/errors'
import { Button } from './Button'

export function Spinner({ className = 'size-5' }: { className?: string }) {
  return <Loader2 className={`animate-spin text-muted ${className}`} aria-hidden />
}

export function LoadingState({ label, compact = false }: { label?: string; compact?: boolean }) {
  const { t } = useTranslation()
  return (
    <div className={`flex items-center justify-center gap-2 text-sm text-muted ${compact ? 'py-4' : 'py-12'}`}>
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
      {onRetry ? <Button size="sm" onClick={onRetry}>{t('common.retry')}</Button> : null}
    </div>
  )
}

export function EmptyState({ title, description, icon, action, compact = false }: { title: ReactNode; description?: ReactNode; icon?: ReactNode; action?: ReactNode; compact?: boolean }) {
  return (
    <div className={`flex flex-col items-center gap-2 px-4 text-center ${compact ? 'py-6' : 'py-12'}`}>
      <span className="text-subtle" aria-hidden>{icon ?? <Inbox className="size-6" />}</span>
      <p className="text-sm font-medium text-content">{title}</p>
      {description ? <p className="max-w-md text-sm leading-relaxed text-muted">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}
