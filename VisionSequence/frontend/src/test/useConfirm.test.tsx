/**
 * useConfirm：平台風格確認對話框取代 window.confirm。
 * 確定 → resolve true、取消／關閉 → resolve false、連續呼叫時前一個視為取消。
 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { useConfirm } from '@/lib/useConfirm'

import { renderPage } from './render'

function Demo() {
  const { confirm, dialog } = useConfirm()
  const [log, setLog] = useState<string[]>([])
  return (
    <div>
      <button type="button" onClick={() => void confirm('要離開嗎？', { confirmLabel: '放棄並離開' }).then((ok) => setLog((l) => [...l, ok ? 'yes' : 'no']))}>ask</button>
      <span data-testid="log">{log.join(',')}</span>
      {dialog}
    </div>
  )
}

describe('useConfirm', () => {
  it('resolves true on confirm and false on cancel', async () => {
    renderPage(<Demo />, { route: '/' })
    fireEvent.click(screen.getByText('ask'))
    expect(await screen.findByText('要離開嗎？')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '放棄並離開' }))
    await waitFor(() => expect(screen.getByTestId('log').textContent).toBe('yes'))
    expect(screen.queryByText('要離開嗎？')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('ask'))
    expect(await screen.findByText('要離開嗎？')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    await waitFor(() => expect(screen.getByTestId('log').textContent).toBe('yes,no'))
  })

  it('cancels the previous pending confirm when asked again', async () => {
    renderPage(<Demo />, { route: '/' })
    fireEvent.click(screen.getByText('ask'))
    fireEvent.click(screen.getByText('ask'))
    await waitFor(() => expect(screen.getByTestId('log').textContent).toBe('no'))
    fireEvent.click(screen.getByRole('button', { name: '放棄並離開' }))
    await waitFor(() => expect(screen.getByTestId('log').textContent).toBe('no,yes'))
  })
})
