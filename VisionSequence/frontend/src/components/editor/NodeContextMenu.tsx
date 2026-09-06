/**
 * 步驟右鍵選單（NodeContextMenu）：開啟工具頁、複製、停用／啟用、刪除、複製參數／貼上參數（同型別）。
 * 位置用 fixed 座標；點外面或 Esc 關閉。
 */
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { ClipboardCopy, ClipboardPaste, Copy, Eye, EyeOff, SlidersHorizontal, Trash2, Play } from 'lucide-react'

import type { GraphNode } from '@/lib/types'

export interface NodeMenuState {
  x: number
  y: number
  node: GraphNode
}

export interface NodeContextMenuProps {
  menu: NodeMenuState | null
  onClose: () => void
  onOpenTool: (node: GraphNode) => void
  /** 只跑到這一步（含上游）；試執行被鎖定時不給 */
  onRunTo?: (node: GraphNode) => void
  onDuplicate: (node: GraphNode) => void
  onToggleEnabled: (node: GraphNode) => void
  onDelete: (node: GraphNode) => void
  onCopyParams: (node: GraphNode) => void
  /** null = 剪貼簿沒有參數；否則是剪貼簿裡的工具型別 */
  paramsClipboardType: string | null
  onPasteParams: (node: GraphNode) => void
}

export function NodeContextMenu(p: NodeContextMenuProps) {
  const { t } = useTranslation()
  const ref = useRef<HTMLDivElement>(null)
  const { menu, onClose } = p

  useEffect(() => {
    if (!menu) return
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', onDown)
    // capture：焦點在畫布節點上時，React Flow 會在節點層處理 Escape 並停止冒泡，冒泡階段收不到
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [menu, onClose])

  if (!menu) return null
  const node = menu.node
  const isNote = node.type === 'note'
  const canPaste = !isNote && p.paramsClipboardType === node.type
  const x = Math.min(menu.x, window.innerWidth - 200)
  const y = Math.min(menu.y, window.innerHeight - 260)
  const item = (label: string, icon: React.ReactNode, onClick: () => void, opts: { danger?: boolean; disabled?: boolean; title?: string } = {}) => (
    <button
      type="button"
      role="menuitem"
      disabled={opts.disabled}
      title={opts.title}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs disabled:opacity-40 ${opts.danger ? 'text-critical hover:bg-critical-soft' : 'hover:bg-surface-muted'}`}
      onClick={() => {
        onClick()
        onClose()
      }}
    >
      {icon} {label}
    </button>
  )
  return (
    <div ref={ref} role="menu" className="fixed z-50 w-48 rounded-xl border border-line bg-surface p-1 shadow-xl" style={{ left: x, top: y }} data-testid="node-menu">
      <p className="truncate px-2 py-1 text-[11px] font-medium text-muted">{node.label || node.type}</p>
      {!isNote ? item(t('nodeMenu.openTool'), <SlidersHorizontal size={13} />, () => p.onOpenTool(node)) : null}
      {!isNote && p.onRunTo ? item(t('nodeMenu.runTo'), <Play size={13} />, () => p.onRunTo?.(node), { disabled: node.enabled === false, title: t('nodeMenu.runToHint') }) : null}
      {item(t('nodeMenu.duplicate'), <Copy size={13} />, () => p.onDuplicate(node))}
      {!isNote ? item(node.enabled === false ? t('nodeMenu.enable') : t('nodeMenu.disable'), node.enabled === false ? <Eye size={13} /> : <EyeOff size={13} />, () => p.onToggleEnabled(node)) : null}
      {!isNote ? (
        <>
          <div className="my-1 h-px bg-line" />
          {item(t('nodeMenu.copyParams'), <ClipboardCopy size={13} />, () => p.onCopyParams(node))}
          {item(t('nodeMenu.pasteParams'), <ClipboardPaste size={13} />, () => p.onPasteParams(node), { disabled: !canPaste, title: t('nodeMenu.pasteParamsHint') })}
        </>
      ) : null}
      <div className="my-1 h-px bg-line" />
      {item(t('nodeMenu.delete'), <Trash2 size={13} />, () => p.onDelete(node), { danger: true })}
    </div>
  )
}
