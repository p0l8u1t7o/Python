import { afterEach, describe, expect, it, vi } from 'vitest'

import { createDebouncedCall } from './debounce'

describe('createDebouncedCall', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('runs only the final scheduled call', () => {
    vi.useFakeTimers()
    const fn = vi.fn()
    const debounced = createDebouncedCall<[string]>(fn, 500)

    debounced.schedule('first')
    vi.advanceTimersByTime(300)
    debounced.schedule('second')
    vi.advanceTimersByTime(499)
    expect(fn).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(fn).toHaveBeenCalledTimes(1)
    expect(fn).toHaveBeenCalledWith('second')
  })

  it('cancels a pending call', () => {
    vi.useFakeTimers()
    const fn = vi.fn()
    const debounced = createDebouncedCall(fn, 500)

    debounced.schedule()
    debounced.cancel()
    vi.advanceTimersByTime(500)

    expect(fn).not.toHaveBeenCalled()
  })
})
