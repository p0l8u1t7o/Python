/** 引擎鎖定橫幅：lock.locked 時顯示在內容區最上方；管理員或持有者可直接解鎖。 */
import { useTranslation } from 'react-i18next'
import { Lock, Unlock } from 'lucide-react'

import { Button } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { useLockMutations } from '@/lib/queries'
import { isLockHolder, useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

export function LockBanner() {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const { release } = useLockMutations()
  const lock = auth.lock
  if (!lock.locked) return null
  const canUnlock = auth.isAdmin || isLockHolder(auth.me, lock)
  const holder = lock.holder === 'integrator' ? t('lock.integrator') : lock.holder || t('lock.integrator')

  async function unlock() {
    try {
      await release.mutateAsync()
      toast.success(t('lock.released'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <div className="flex items-center gap-3 border-b border-amber-400 bg-amber-100 px-4 py-2 text-sm text-amber-900 dark:border-amber-500/60 dark:bg-amber-500/20 dark:text-amber-100" role="status" data-testid="lock-banner">
      <Lock size={16} className="shrink-0" aria-hidden />
      <p className="min-w-0 flex-1">
        <span className="font-semibold">{t('lock.bannerTitle', { holder, reason: lock.reason || t('lock.noReason') })}</span>
        <span className="ml-2">{t('lock.bannerHint')}</span>
        {lock.expires_at ? <span className="ml-2 text-xs opacity-80">{t('lock.expiresAt', { time: new Date(lock.expires_at).toLocaleString() })}</span> : null}
      </p>
      {canUnlock ? (
        <Button size="sm" variant="primary" icon={<Unlock size={14} />} loading={release.isPending} onClick={() => void unlock()}>
          {t('lock.unlock')}
        </Button>
      ) : null}
    </div>
  )
}
