/** 節點耗時熱點：最慢的那幾步著紅、一半以上橙、其餘不強調；沒有 run 就沒有熱度。 */
import { describe, expect, it } from 'vitest'

import { heatLevel } from './ToolNode'

describe('heatLevel', () => {
  it('grades a node by its share of the slowest step', () => {
    expect(heatLevel(undefined)).toBe('cool')
    expect(heatLevel(0)).toBe('cool')
    expect(heatLevel(0.2)).toBe('cool')
    expect(heatLevel(0.5)).toBe('warm')
    expect(heatLevel(0.84)).toBe('warm')
    expect(heatLevel(0.85)).toBe('hot')
    expect(heatLevel(1)).toBe('hot')
  })
})
