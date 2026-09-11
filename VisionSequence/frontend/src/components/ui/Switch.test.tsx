import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Switch } from '@/components/ui'

describe('Switch', () => {
  it('keeps the on state visible and explains why it is disabled', () => {
    // PM-REVIEW-R2 D2：停用的「已開啟」開關以前與「已關閉」長得一樣，也沒有任何原因
    render(<Switch checked disabled disabledReason="Your own account cannot be changed here" label="Enabled" onChange={() => {}} />)
    const control = screen.getByRole('switch')
    expect(control).toBeDisabled()
    expect(control).toHaveAttribute('aria-checked', 'true')
    expect(control.className).toContain('bg-brand')
    expect(control).toHaveAttribute('title', 'Your own account cannot be changed here')
    expect(control).toHaveAttribute('data-disabled-reason', 'Your own account cannot be changed here')
  })

  it('uses the label as the tooltip when it is enabled', () => {
    render(<Switch checked={false} disabledReason="never shown" label="Enabled" onChange={() => {}} />)
    const control = screen.getByRole('switch')
    expect(control).toHaveAttribute('title', 'Enabled')
    expect(control).not.toHaveAttribute('data-disabled-reason')
  })
})
