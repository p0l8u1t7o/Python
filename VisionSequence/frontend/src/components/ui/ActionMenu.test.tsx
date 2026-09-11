/** 「更多」選單：portal 掛在 body、開啟時焦點進第一項、↑↓ 移動、Escape 關閉並還焦點、點外面關閉、點項目關閉。 */
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ActionMenu, ActionMenuItem, ActionMenuSeparator } from './ActionMenu'

function Host({ onPick = () => {} }: { onPick?: () => void }) {
  return (
    <MemoryRouter>
      <div className="overflow-hidden" data-testid="clipper">
        <ActionMenu testId="more" label="More" trigger={(open, props) => <button type="button" {...props}>more {open ? 'open' : 'closed'}</button>}>
          <ActionMenuItem onClick={onPick} testId="item-a">Alpha</ActionMenuItem>
          <ActionMenuItem disabled testId="item-b">Beta</ActionMenuItem>
          <ActionMenuSeparator />
          <ActionMenuItem to="/x" testId="item-c">Gamma</ActionMenuItem>
        </ActionMenu>
      </div>
      <button type="button">outside</button>
    </MemoryRouter>
  )
}

describe('ActionMenu', () => {
  it('opens into a portal, focuses the first item and moves with arrow keys', () => {
    render(<Host />)
    const trigger = screen.getByText(/^more/)
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu')
    fireEvent.click(trigger)
    const menu = screen.getByRole('menu')
    expect(menu.parentElement).toBe(document.body)  // 不在 overflow-hidden 的容器裡
    expect(screen.queryByTestId('clipper')?.contains(menu)).toBe(false)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(document.activeElement).toBe(screen.getByTestId('item-a'))
    fireEvent.keyDown(document, { key: 'ArrowDown' })
    expect(document.activeElement).toBe(screen.getByTestId('item-c'))  // 停用的 Beta 跳過
    fireEvent.keyDown(document, { key: 'ArrowDown' })
    expect(document.activeElement).toBe(screen.getByTestId('item-a'))
    fireEvent.keyDown(document, { key: 'ArrowUp' })
    expect(document.activeElement).toBe(screen.getByTestId('item-c'))
  })

  it('closes on Escape (restoring focus), on outside click and after picking an item', () => {
    const onPick = vi.fn()
    render(<Host onPick={onPick} />)
    const trigger = screen.getByText(/^more/)
    fireEvent.click(trigger)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    fireEvent.click(trigger)
    fireEvent.mouseDown(screen.getByText('outside'))
    expect(screen.queryByRole('menu')).toBeNull()
    fireEvent.click(trigger)
    fireEvent.click(screen.getByTestId('item-b'))
    expect(screen.getByRole('menu')).toBeInTheDocument()  // 停用項目不關閉
    fireEvent.click(screen.getByTestId('item-a'))
    expect(onPick).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('menu')).toBeNull()
  })
})
