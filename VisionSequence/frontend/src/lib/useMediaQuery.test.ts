/** useMediaQuery：跟著 matchMedia 變化、沒有 matchMedia 時回 false。 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useMediaQuery } from '@/lib/useMediaQuery'

function installMatchMedia(initial: boolean) {
  const listeners = new Set<() => void>()
  const mql = { matches: initial, addEventListener: (_: string, cb: () => void) => listeners.add(cb), removeEventListener: (_: string, cb: () => void) => listeners.delete(cb) }
  vi.stubGlobal('matchMedia', vi.fn(() => mql))
  return { set(v: boolean) { mql.matches = v; listeners.forEach((cb) => cb()) }, listeners }
}

describe('useMediaQuery', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('tracks matchMedia changes and unsubscribes on unmount', () => {
    const mm = installMatchMedia(false)
    const { result, unmount } = renderHook(() => useMediaQuery('(max-width: 767px)'))
    expect(result.current).toBe(false)
    act(() => mm.set(true))
    expect(result.current).toBe(true)
    expect(mm.listeners.size).toBe(1)
    unmount()
    expect(mm.listeners.size).toBe(0)
  })

  it('returns false when matchMedia is unavailable', () => {
    vi.stubGlobal('matchMedia', undefined)
    const { result } = renderHook(() => useMediaQuery('(max-width: 767px)'))
    expect(result.current).toBe(false)
  })
})
