/**
 * 平台風格的確認對話框（取代 window.confirm）：`const { confirm, choose, dialog } = useConfirm()`，
 * `await confirm(message, { title, confirmLabel, danger })` 回 true／false；把 `{dialog}` 放進 JSX。
 * `await choose(message, { …, saveLabel })` 多一顆「儲存並離開」，回 'confirm'｜'save'｜'cancel'（PM-REVIEW-R2 P5）。
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

export type Choice = 'confirm' | 'save' | 'cancel'

interface Pending extends ConfirmOptions {
  message: ReactNode
  saveLabel?: string
  resolve: (choice: Choice) => void
}

export function useConfirm() {
  const { t } = useTranslation()
  const [pending, setPending] = useState<Pending | null>(null)
  const pendingRef = useRef<Pending | null>(null)

  const choose = useCallback((message: ReactNode, options: ConfirmOptions & { saveLabel?: string } = {}) => new Promise<Choice>((resolve) => {
    pendingRef.current?.resolve('cancel')
    const next: Pending = { message, resolve, ...options }
    pendingRef.current = next
    setPending(next)
  }), [])
  const confirm = useCallback((message: ReactNode, options: ConfirmOptions = {}) => choose(message, options).then((choice) => choice === 'confirm'), [choose])

  const settle = useCallback((choice: Choice) => {
    const cur = pendingRef.current
    pendingRef.current = null
    setPending(null)
    cur?.resolve(choice)
  }, [])

  const dialog = (
    <ConfirmDialog
      open={pending !== null}
      onClose={() => settle('cancel')}
      onConfirm={() => settle('confirm')}
      extraLabel={pending?.saveLabel}
      onExtra={() => settle('save')}
      title={pending?.title ?? t('common.confirmTitle')}
      message={pending?.message ?? ''}
      confirmLabel={pending?.confirmLabel ?? t('common.confirm')}
      danger={pending?.danger ?? true}
    />
  )
  return { confirm, choose, dialog }
}
