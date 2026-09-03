/**
 * 平台風格的確認對話框（取代 window.confirm）：`const { confirm, dialog } = useConfirm()`，
 * `await confirm(message, { title, confirmLabel, danger })` 回 true／false；把 `{dialog}` 放進 JSX。
 * 一次只會有一個待確認；再呼叫時前一個視為取消。
 */
import { useCallback, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ConfirmDialog } from '@/components/ui'

export interface ConfirmOptions {
  title?: ReactNode
  confirmLabel?: string
  danger?: boolean
}

interface Pending extends ConfirmOptions {
  message: ReactNode
  resolve: (ok: boolean) => void
}

export function useConfirm() {
  const { t } = useTranslation()
  const [pending, setPending] = useState<Pending | null>(null)
  const pendingRef = useRef<Pending | null>(null)

  const confirm = useCallback((message: ReactNode, options: ConfirmOptions = {}) => new Promise<boolean>((resolve) => {
    pendingRef.current?.resolve(false)
    const next: Pending = { message, resolve, ...options }
    pendingRef.current = next
    setPending(next)
  }), [])

  const settle = useCallback((ok: boolean) => {
    const cur = pendingRef.current
    pendingRef.current = null
    setPending(null)
    cur?.resolve(ok)
  }, [])

  const dialog = (
    <ConfirmDialog
      open={pending !== null}
      onClose={() => settle(false)}
      onConfirm={() => settle(true)}
      title={pending?.title ?? t('common.confirmTitle')}
      message={pending?.message ?? ''}
      confirmLabel={pending?.confirmLabel ?? t('common.confirm')}
      danger={pending?.danger ?? true}
    />
  )
  return { confirm, dialog }
}
