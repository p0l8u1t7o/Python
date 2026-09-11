/** 共用對話框的鍵盤與關閉規則（Suggest5 第 3 點）：焦點循環、焦點恢復、標題關聯、巢狀只由最上層處理 Escape、footer 的 close 走草稿檢查。 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ConfirmDialog, Modal } from './Modal'

function Host({ dirty = false, onClose = () => {} }: { dirty?: boolean; onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>open</button>
      <Modal open={open} onClose={() => { onClose(); setOpen(false) }} title="Host dialog" description="Some help" dirty={dirty}
        footer={(close) => <><button type="button" onClick={close}>cancel</button><button type="button">ok</button></>}>
        <input aria-label="first" />
        <input aria-label="second" />
      </Modal>
    </div>
  )
}

describe('Modal', () => {
  it('ConfirmDialog shows a third button only when extraLabel is given', () => {
    const onExtra = vi.fn()
    const { rerender } = render(<ConfirmDialog open onClose={() => {}} onConfirm={() => {}} title="Leave?" message="unsaved" confirmLabel="Discard" />)
    expect(screen.queryByTestId('confirm-extra')).toBeNull()
    rerender(<ConfirmDialog open onClose={() => {}} onConfirm={() => {}} title="Leave?" message="unsaved" confirmLabel="Discard" extraLabel="Save and leave" onExtra={onExtra} />)
    fireEvent.click(screen.getByTestId('confirm-extra'))
    expect(onExtra).toHaveBeenCalledTimes(1)
  })

  it('labels the dialog, traps Tab inside and restores focus on close', async () => {
    render(<Host />)
    const trigger = screen.getByText('open')
    trigger.focus()
    fireEvent.click(trigger)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAccessibleName('Host dialog')
    expect(dialog).toHaveAccessibleDescription('Some help')
    const first = screen.getByLabelText('first')
    const ok = screen.getByText('ok')
    // 從最後一個往後 Tab 回到第一個；從第一個 Shift+Tab 回到最後一個
    ok.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(document.activeElement).toBe(screen.getAllByRole('button')[1])  // 面板內第一個可聚焦：關閉鈕
    screen.getAllByRole('button')[1].focus()  // 面板內第一個可聚焦元素（關閉鈕）往前循環到最後一個
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(ok)
    expect(first).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(document.activeElement).toBe(trigger)
  })

  it('routes every close entry through the dirty check', () => {
    const onClose = vi.fn()
    render(<Host dirty onClose={onClose} />)
    fireEvent.click(screen.getByText('open'))
    fireEvent.click(screen.getByText('cancel'))
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Discard'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('lets only the top-most dialog handle Escape', () => {
    const outer = vi.fn()
    const inner = vi.fn()
    function Nested() {
      // 實際使用一定是先開外層、再從裡面開內層（例如對話框裡的確認框）
      const [innerOpen, setInnerOpen] = useState(false)
      return (
        <Modal open onClose={outer} title="Outer">
          <button type="button" onClick={() => setInnerOpen(true)}>nest</button>
          <Modal open={innerOpen} onClose={() => { inner(); setInnerOpen(false) }} title="Inner"><p>inner body</p></Modal>
        </Modal>
      )
    }
    render(<Nested />)
    fireEvent.click(screen.getByText('nest'))
    expect(screen.getByText('inner body')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(inner).toHaveBeenCalledTimes(1)
    expect(outer).not.toHaveBeenCalled()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(outer).toHaveBeenCalledTimes(1)
  })
})
