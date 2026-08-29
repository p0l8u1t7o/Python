import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'

import { Button, IconButton } from './Button'

export function Modal({ open, onClose, title, description, children, footer, size = 'md', dirty = false }: { open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children: ReactNode; footer?: ReactNode; size?: 'sm' | 'md' | 'lg' | 'xl'; dirty?: boolean }) {
  const { t } = useTranslation()
  const panelRef = useRef<HTMLDivElement>(null)
  const [askDiscard, setAskDiscard] = useState(false)
  // onClose 每次 render 都是新函式；用 ref 讀，避免 effect 重跑搶走輸入框焦點。
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const dirtyRef = useRef(dirty)
  dirtyRef.current = dirty

  useEffect(() => {
    if (!open) setAskDiscard(false)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      if (dirtyRef.current) setAskDiscard(true)
      else onCloseRef.current()
    }
    document.addEventListener('keydown', onKeyDown)
    if (!panelRef.current?.contains(document.activeElement)) panelRef.current?.focus()
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  if (!open) return null
  const guardedClose = () => (dirtyRef.current ? setAskDiscard(true) : onCloseRef.current())
  const width = { sm: 'max-w-md', md: 'max-w-xl', lg: 'max-w-3xl', xl: 'max-w-6xl' }[size]

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-8">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-[1px]" onClick={guardedClose} aria-hidden />
      <div ref={panelRef} role="dialog" aria-modal="true" tabIndex={-1} className={`card relative z-10 w-full ${width} shadow-2xl shadow-black/30 outline-none`}>
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-content">{title}</h2>
            {description ? <p className="mt-1 text-sm leading-relaxed text-muted">{description}</p> : null}
          </div>
          <IconButton label={t('common.close')} onClick={guardedClose}>
            <X className="size-4" />
          </IconButton>
        </header>
        {askDiscard ? (
          <div className="border-b border-line bg-warning-soft px-5 py-3 text-sm" role="alertdialog">
            <p className="text-warning">{t('common.discardChanges')}</p>
            <div className="mt-2 flex justify-end gap-2">
              <Button size="sm" onClick={() => setAskDiscard(false)}>{t('common.keepEditing')}</Button>
              <Button size="sm" variant="danger" onClick={() => { setAskDiscard(false); onCloseRef.current() }}>{t('common.discard')}</Button>
            </div>
          </div>
        ) : null}
        <div className="px-5 py-4">{children}</div>
        {footer ? <footer className="flex items-center justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer> : null}
      </div>
    </div>,
    document.body,
  )
}

export function ConfirmDialog({ open, onClose, onConfirm, title, message, confirmLabel, danger = false, loading = false }: { open: boolean; onClose: () => void; onConfirm: () => void; title: ReactNode; message: ReactNode; confirmLabel?: string; danger?: boolean; loading?: boolean }) {
  const { t } = useTranslation()
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button onClick={onClose} disabled={loading}>{t('common.cancel')}</Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} loading={loading}>{confirmLabel ?? t('common.confirm')}</Button>
        </>
      }
    >
      <div className="text-sm leading-relaxed text-muted">{message}</div>
    </Modal>
  )
}
