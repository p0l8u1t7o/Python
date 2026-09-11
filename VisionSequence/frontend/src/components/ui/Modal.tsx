import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'

import { Button, IconButton } from './Button'

/** 開著的對話框堆疊：巢狀時只有最上層處理 Escape 與 Tab 循環（Suggest5 第 3 點）。 */
const openStack: symbol[] = []
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function focusables(root: HTMLElement): HTMLElement[] {
  // 不看版面（jsdom 沒有 layout）：只排除明確隱藏的
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => !el.hasAttribute('hidden') && el.getAttribute('aria-hidden') !== 'true' && !el.closest('[hidden]'))
}

export type ModalFooter = ReactNode | ((close: () => void) => ReactNode)

/**
 * 共用對話框。
 * - 焦點：開啟時移進面板、Tab／Shift+Tab 只在面板內循環、關閉後回到開啟前的元素。
 * - 標題／描述以 aria-labelledby／aria-describedby 關聯。
 * - 關閉規則只有一套：X、背景、Escape 與 footer 拿到的 `close` 都會先看 `dirty` 問要不要放棄；
 *   footer 請用 `(close) => …` 的寫法，不要自己呼叫 onClose 繞過檢查。
 */
export function Modal({ open, onClose, title, description, children, footer, size = 'md', dirty = false }: { open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children: ReactNode; footer?: ModalFooter; size?: 'sm' | 'md' | 'lg' | 'xl' | 'full'; dirty?: boolean }) {
  const { t } = useTranslation()
  const panelRef = useRef<HTMLDivElement>(null)
  const [askDiscard, setAskDiscard] = useState(false)
  const titleId = useId()
  const descriptionId = useId()
  const token = useRef(Symbol('modal'))
  const restoreTo = useRef<HTMLElement | null>(null)
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
    const id = token.current
    openStack.push(id)
    restoreTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const onKeyDown = (event: KeyboardEvent) => {
      if (openStack[openStack.length - 1] !== id) return
      if (event.key === 'Escape') {
        event.stopPropagation()
        if (dirtyRef.current) setAskDiscard(true)
        else onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !panelRef.current) return
      const items = focusables(panelRef.current)
      if (!items.length) {
        event.preventDefault()
        panelRef.current.focus()
        return
      }
      const active = document.activeElement
      const inside = panelRef.current.contains(active)
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && (active === first || !inside || active === panelRef.current)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !inside)) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    if (!panelRef.current?.contains(document.activeElement)) panelRef.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      const at = openStack.lastIndexOf(id)
      if (at >= 0) openStack.splice(at, 1)
      const target = restoreTo.current
      restoreTo.current = null
      if (target && document.contains(target)) target.focus()
    }
  }, [open])

  if (!open) return null
  const guardedClose = () => (dirtyRef.current ? setAskDiscard(true) : onCloseRef.current())
  const width = { sm: 'max-w-md', md: 'max-w-xl', lg: 'max-w-3xl', xl: 'max-w-6xl', full: 'max-w-[min(96vw,1680px)]' }[size]

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-8">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-[1px]" onClick={guardedClose} aria-hidden />
      <div ref={panelRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={description ? descriptionId : undefined} tabIndex={-1} className={`card relative z-10 w-full ${width} shadow-2xl shadow-black/30 outline-none`}>
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold text-content">{title}</h2>
            {description ? <p id={descriptionId} className="mt-1 text-sm leading-relaxed text-muted">{description}</p> : null}
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
        {footer ? <footer className="flex items-center justify-end gap-2 border-t border-line px-5 py-3">{typeof footer === 'function' ? footer(guardedClose) : footer}</footer> : null}
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
      <div className="text-sm text-content">{message}</div>
    </Modal>
  )
}
