/**
 * 「更多」動作選單（Suggest5 第 5 點：常駐高頻動作，其餘收進選單）。
 * - 以 portal 固定定位掛在 body，所以放在 overflow-hidden 的卡片或可橫向捲動的工具列裡也不會被裁掉。
 * - 鍵盤：開啟時焦點移到第一項，↑↓ 在項目間移動，Escape 關閉並把焦點還給觸發鈕；點選項目或點外面關閉。
 * - 觸發鈕由呼叫端畫（拿到 open 與要展開的 aria 屬性），項目用 ActionMenuItem／ActionMenuSeparator。
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'

export interface ActionMenuTriggerProps {
  onClick: () => void
  'aria-haspopup': 'menu'
  'aria-expanded': boolean
}

const ITEM = '[role="menuitem"]:not([aria-disabled="true"])'

export function ActionMenu({ trigger, children, align = 'right', testId, label }: { trigger: (open: boolean, props: ActionMenuTriggerProps) => ReactNode; children: ReactNode; align?: 'left' | 'right'; testId?: string; label?: string }) {
  const [open, setOpen] = useState(false)
  const anchorRef = useRef<HTMLSpanElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; left?: number; right?: number }>({ top: 0 })

  const close = useCallback((restore = true) => {
    setOpen(false)
    if (restore) anchorRef.current?.querySelector<HTMLElement>('button, a, [tabindex]')?.focus()
  }, [])

  // 位置：先貼在觸發鈕下方，量到高度後放不下就翻到上方
  useLayoutEffect(() => {
    if (!open || !anchorRef.current) return
    const r = anchorRef.current.getBoundingClientRect()
    const h = menuRef.current?.offsetHeight ?? 0
    let top = r.bottom + 4
    if (h && top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 4)
    setPos(align === 'left' ? { top, left: Math.max(8, r.left) } : { top, right: Math.max(8, window.innerWidth - r.right) })
  }, [open, align])

  useEffect(() => {
    if (!open) return
    menuRef.current?.querySelector<HTMLElement>(ITEM)?.focus()
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (!anchorRef.current?.contains(target) && !menuRef.current?.contains(target)) close(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        close()
        return
      }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
      const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>(ITEM) ?? [])
      if (!items.length) return
      e.preventDefault()
      const at = items.indexOf(document.activeElement as HTMLElement)
      const next = e.key === 'ArrowDown' ? (at + 1) % items.length : (at - 1 + items.length) % items.length
      items[next].focus()
    }
    const onAway = () => close(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey, true)
    window.addEventListener('resize', onAway)
    window.addEventListener('scroll', onAway, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey, true)
      window.removeEventListener('resize', onAway)
      window.removeEventListener('scroll', onAway, true)
    }
  }, [open, close])

  return (
    <>
      <span ref={anchorRef} className="inline-flex" data-testid={testId}>
        {trigger(open, { onClick: () => setOpen((v) => !v), 'aria-haspopup': 'menu', 'aria-expanded': open })}
      </span>
      {open
        ? createPortal(
            <div
              ref={menuRef}
              role="menu"
              aria-label={label}
              style={{ position: 'fixed', top: pos.top, left: pos.left, right: pos.right }}
              className="z-50 min-w-44 max-w-72 rounded-xl border border-line bg-surface p-1 text-sm shadow-lg"
              data-testid={testId ? `${testId}-menu` : undefined}
              onClick={(e) => {
                // 項目自己會做事；這裡只負責關閉（帶 data-keep-open 的項目除外）
                const item = (e.target as HTMLElement).closest('[role="menuitem"]')
                if (item && !item.hasAttribute('data-keep-open') && item.getAttribute('aria-disabled') !== 'true') close(false)
              }}
            >
              {children}
            </div>,
            document.body,
          )
        : null}
    </>
  )
}

export function ActionMenuItem({ icon, children, onClick, to, disabled, danger, title, testId }: { icon?: ReactNode; children: ReactNode; onClick?: () => void; to?: string; disabled?: boolean; danger?: boolean; title?: string; testId?: string }) {
  const cls = `flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs outline-none focus-visible:bg-surface-muted ${disabled ? 'cursor-not-allowed opacity-40' : danger ? 'text-critical hover:bg-critical-soft' : 'hover:bg-surface-muted'}`
  if (to && !disabled) return <Link to={to} role="menuitem" className={cls} title={title} data-testid={testId}>{icon} {children}</Link>
  return (
    <button type="button" role="menuitem" className={cls} onClick={disabled ? undefined : onClick} aria-disabled={disabled || undefined} disabled={disabled} title={title} data-testid={testId}>
      {icon} {children}
    </button>
  )
}

export function ActionMenuSeparator() {
  return <div role="separator" className="my-1 h-px bg-line" />
}
