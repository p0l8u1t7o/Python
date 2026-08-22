import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'

import { Button, IconButton } from './Button'

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
  dirty = false,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg'
  /**
   * The form inside has unsaved edits. Escape, the backdrop and the X then
   * ask before discarding - those are the accidental ways out. A Cancel
   * button in the footer is a deliberate one and closes directly.
   */
  dirty?: boolean
}) {
  const { t } = useTranslation()
  const panelRef = useRef<HTMLDivElement>(null)
  const [askDiscard, setAskDiscard] = useState(false)
  const dirtyRef = useRef(dirty)
  dirtyRef.current = dirty

  useEffect(() => {
    if (!open) setAskDiscard(false)
  }, [open])

  // Read through a ref so the effect below does not depend on `onClose`.
  //
  // Every caller writes `onClose={() => setOpen(false)}` - a new function on
  // every render - and this page re-renders every few seconds with the polls.
  // With `onClose` in the dependency list the effect re-ran on each poll, and
  // its `panelRef.current?.focus()` yanked focus out of whatever field the
  // operator was typing in. The symptom was maddening: text scrambled or
  // keystrokes vanishing mid-word, every five seconds, in every form.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const guardedClose = () => {
    if (dirtyRef.current) setAskDiscard(true)
    else onCloseRef.current()
  }
  const guardedCloseRef = useRef(guardedClose)
  guardedCloseRef.current = guardedClose

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') guardedCloseRef.current()
    }
    document.addEventListener('keydown', onKeyDown)
    // Stop the page behind the dialog from scrolling with it.
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    // Focus the panel only when the dialog *opens*, and only if nothing
    // inside it holds focus already - stealing focus is only ever right once.
    if (!panelRef.current?.contains(document.activeElement)) {
      panelRef.current?.focus()
    }
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [open])

  if (!open) return null

  const width = { sm: 'max-w-md', md: 'max-w-xl', lg: 'max-w-3xl' }[size]

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-8">
      <div
        className="fixed inset-0 bg-black/45 backdrop-blur-[1px]"
        onClick={guardedClose}
        aria-hidden
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={`card relative z-10 w-full ${width} shadow-2xl shadow-black/25 outline-none`}
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-content">{title}</h2>
            {description ? (
              <p className="mt-1 text-sm text-muted leading-relaxed">{description}</p>
            ) : null}
          </div>
          <IconButton label={t('common.close')} onClick={guardedClose}>
            <X className="size-4" />
          </IconButton>
        </header>

        {askDiscard ? (
          <div className="border-b border-line bg-warning-soft px-5 py-3 text-sm" role="alertdialog">
            <p className="text-warning">{t('common.discardChanges')}</p>
            <div className="mt-2 flex justify-end gap-2">
              <Button size="sm" onClick={() => setAskDiscard(false)}>
                {t('common.keepEditing')}
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  setAskDiscard(false)
                  onCloseRef.current()
                }}
              >
                {t('common.discard')}
              </Button>
            </div>
          </div>
        ) : null}

        <div className="px-5 py-4">{children}</div>

        {footer ? (
          <footer className="flex items-center justify-end gap-2 border-t border-line px-5 py-3">
            {footer}
          </footer>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel,
  danger = false,
  loading = false,
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: ReactNode
  message: ReactNode
  confirmLabel?: string
  danger?: boolean
  loading?: boolean
}) {
  const { t } = useTranslation()
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button onClick={onClose} disabled={loading}>
            {t('common.cancel')}
          </Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            onClick={onConfirm}
            loading={loading}
          >
            {confirmLabel ?? t('common.confirm')}
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted leading-relaxed">{message}</p>
    </Modal>
  )
}
