/** 步驟右鍵選單的關閉條件：點選單裡面不關，點外面（含會吃掉事件的畫布）與 Esc 都要關。 */
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NodeContextMenu } from './NodeContextMenu'
import type { GraphNode } from '@/lib/types'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

const node: GraphNode = { id: 'n1', type: 'blur', label: '去噪', description: '', enabled: true, continue_on_error: false, params: {}, position: { x: 0, y: 0 } }

function show(onClose: () => void) {
  return render(
    <NodeContextMenu
      menu={{ x: 10, y: 10, node }}
      onClose={onClose}
      onOpenTool={() => {}}
      onDuplicate={() => {}}
      onToggleEnabled={() => {}}
      onDelete={() => {}}
      onCopyParams={() => {}}
      paramsClipboardType={null}
      onPasteParams={() => {}}
    />,
  )
}

afterEach(() => {
  document.querySelectorAll('[data-fake-pane]').forEach((el) => el.remove())
})

describe('node context menu', () => {
  it('closes when the click lands on an element that stops propagation (the canvas pane)', () => {
    const onClose = vi.fn()
    show(onClose)
    expect(screen.getByTestId('node-menu')).toBeInTheDocument()
    // React Flow 的畫布會在 mousedown 就停止傳遞：選單只有用 capture 才收得到
    const pane = document.createElement('div')
    pane.setAttribute('data-fake-pane', '')
    pane.addEventListener('mousedown', (e) => e.stopPropagation())
    document.body.appendChild(pane)
    fireEvent.mouseDown(pane)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('stays open while clicking inside itself and closes on Escape', () => {
    const onClose = vi.fn()
    show(onClose)
    fireEvent.mouseDown(screen.getByTestId('node-menu'))
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
