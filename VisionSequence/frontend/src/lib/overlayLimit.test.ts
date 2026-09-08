import { describe, expect, it } from 'vitest'

import { DEFAULT_OVERLAY_LIMIT, OVERLAY_LIMIT_KEY, limitOverlays, normalizeOverlayLimit, readOverlayLimit, writeOverlayLimit } from './overlayLimit'
import type { Overlay } from './types'

function marks(count: number): Overlay[] {
  return Array.from({ length: count }, (_v, i) => ({ kind: 'point', x: i, y: i }))
}

describe('overlay limit helpers', () => {
  it('normalizes invalid limits to the configured fallback', () => {
    expect(normalizeOverlayLimit('nope', 50)).toBe(50)
    expect(normalizeOverlayLimit(0, 50)).toBe(50)
    expect(normalizeOverlayLimit(12.8, 50)).toBe(12)
  })

  it('truncates overlays and reports shown and total counts', () => {
    const result = limitOverlays(marks(5), 3)
    expect(result.overlays).toHaveLength(3)
    expect(result.shown).toBe(3)
    expect(result.total).toBe(5)
    expect(result.truncated).toBe(true)
  })

  it('stores the limit as device-scoped local state', () => {
    localStorage.removeItem(OVERLAY_LIMIT_KEY)
    expect(readOverlayLimit()).toBe(DEFAULT_OVERLAY_LIMIT)
    expect(writeOverlayLimit(7.9)).toBe(7)
    expect(readOverlayLimit()).toBe(7)
  })
})
