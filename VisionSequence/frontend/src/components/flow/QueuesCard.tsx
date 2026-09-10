/** 站台佇列摘要；清空權限與 API 相同。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, ErrorState, LoadingState } from '@/components/ui'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useQueues } from '@/lib/queries'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

export function QueuesCard() {
  const auth = useAuth()
  const { t } = useTranslation()
  const toast = useToast()
  const queues = useQueues(auth.can('integration'))
  const [busy, setBusy] = useState<string | null>(null)
  if (!auth.can('integration')) return null
  const canClear = auth.can('connections') || auth.can('flows.edit')

  async function clear(name: string) {
    setBusy(name)
    try {
      await api.delete(`/vision/queues/${encodeURIComponent(name)}`)
      await queues.refetch()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="space-y-2 border-t border-line pt-3" data-testid="queues-card">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t('queues.title')}</h3>
        <Button size="sm" onClick={() => void queues.refetch()}>{t('common.refresh')}</Button>
      </div>
      <p className="text-xs text-subtle">{t('queues.hint')}</p>
      {queues.isLoading ? <LoadingState /> : queues.error ? <ErrorState error={queues.error} /> : (
        <div className="space-y-2">
          {!queues.data?.items.length ? <p className="text-xs text-subtle">{t('queues.empty')}</p> : null}
          {queues.data?.items.map((queue) => (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-line p-2 text-xs" key={queue.name}>
              <div className="min-w-0 flex-1">
                <div className="break-all font-mono">{queue.name}</div>
                <div className="text-muted">{t('queues.stats', { size: queue.size, age: Math.round(queue.oldest_age_ms), dropped: queue.dropped })}</div>
              </div>
              {canClear ? <Button size="sm" loading={busy === queue.name} disabled={busy !== null || queue.size === 0} onClick={() => void clear(queue.name)}>{t('queues.clear')}</Button> : null}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
