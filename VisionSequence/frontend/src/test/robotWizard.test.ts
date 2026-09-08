/** 手眼精靈從節點輸出取點：不同工具的命名不一樣，取點的順序要固定。 */
import { describe, expect, it } from 'vitest'
import { pointOf } from '@/components/calibration/RobotWizard'

describe('pointOf', () => {
  it('reads the usual position outputs', () => {
    expect(pointOf({ best_x: 10, best_y: 20 })).toEqual([10, 20])
    expect(pointOf({ cx: 1.5, cy: 2.5 })).toEqual([1.5, 2.5])
    expect(pointOf({ x: 3, y: 4 })).toEqual([3, 4])
    expect(pointOf({ center: [7, 8] })).toEqual([7, 8])
    expect(pointOf({ matches: [{ cx: 5, cy: 6 }] })).toEqual([5, 6])
  })

  it('prefers the best match over a plain x and y', () => {
    expect(pointOf({ x: 1, y: 1, best_x: 9, best_y: 9 })).toEqual([9, 9])
  })

  it('returns nothing when the step has no position', () => {
    expect(pointOf(undefined)).toBeNull()
    expect(pointOf({})).toBeNull()
    expect(pointOf({ count: 3, ok: true })).toBeNull()
    expect(pointOf({ best_x: Number.NaN, best_y: 2 })).toBeNull()
    expect(pointOf({ matches: [] })).toBeNull()
  })
})
