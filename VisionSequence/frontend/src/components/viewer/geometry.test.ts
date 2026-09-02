import { describe, expect, it } from 'vitest'

import { clampRegion, convertRegion, pointInPolygon, regionBounds, regionCenter, regionFromDrag, regionsEqual, roundRegion, translateRegion } from '@/components/viewer/geometry'

describe('viewer geometry', () => {
  it('drag → rect, bounds and center', () => {
    const r = regionFromDrag('rect', 10, 20, 110, 70)
    expect(r).toMatchObject({ shape: 'rect', x: 10, y: 20, w: 100, h: 50 })
    expect(regionBounds(r)).toMatchObject({ x: 10, y: 20, w: 100, h: 50 })
    expect(regionCenter(r)).toEqual([60, 45])
  })

  it('translate and clamp keep shape inside the image', () => {
    const r = regionFromDrag('circle', 50, 50, 90, 50)
    const moved = translateRegion(r, -100, 0)
    const clamped = clampRegion(moved, 200, 200)
    const b = regionBounds(clamped)
    expect(b.x).toBeGreaterThanOrEqual(0)
    expect(b.x + b.w).toBeLessThanOrEqual(200)
  })

  it('convertRegion between shapes preserves the bounding box roughly', () => {
    const rect = regionFromDrag('rect', 0, 0, 100, 60)
    const ell = convertRegion(rect, 'ellipse')
    expect(ell.shape).toBe('ellipse')
    const back = regionBounds(ell)
    expect(Math.round(back.w)).toBe(100)
    expect(Math.round(back.h)).toBe(60)
    expect(convertRegion(rect, 'annulus').shape).toBe('annulus')
    expect(convertRegion(rect, 'polygon').shape).toBe('polygon')
  })

  it('roundRegion / regionsEqual / pointInPolygon', () => {
    const r = roundRegion({ shape: 'rect', x: 1.4, y: 2.6, w: 10.2, h: 5.5 })
    expect(r).toMatchObject({ x: 1, y: 3, w: 10, h: 6 })
    expect(regionsEqual(r, { ...r })).toBe(true)
    expect(regionsEqual(r, null)).toBe(false)
    expect(pointInPolygon(5, 5, [[0, 0], [10, 0], [10, 10], [0, 10]])).toBe(true)
    expect(pointInPolygon(15, 5, [[0, 0], [10, 0], [10, 10], [0, 10]])).toBe(false)
  })
})
