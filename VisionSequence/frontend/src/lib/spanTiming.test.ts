import { describe, expect, it } from 'vitest'

import { calculateSpanTiming } from './spanTiming'

const nodes = {
  a: { id: 'a', duration_ms: 10 },
  b: { id: 'b', duration_ms: 20 },
  c: { id: 'c', duration_ms: 30 },
  d: { id: 'd', duration_ms: 40 },
  x: { id: 'x', duration_ms: 100 },
}

describe('calculateSpanTiming', () => {
  it('returns the single-node span when source and target are equal', () => {
    const result = calculateSpanTiming(nodes, [], 'b', 'b')
    expect(result.hasPath).toBe(true)
    expect(result.nodeIds).toEqual(['b'])
    expect(result.totalMs).toBe(20)
  })

  it('returns an empty span when no data-flow path exists', () => {
    const result = calculateSpanTiming(nodes, [{ source: 'a', target: 'b' }], 'b', 'd')
    expect(result.hasPath).toBe(false)
    expect(result.nodeCount).toBe(0)
    expect(result.percent).toBe(0)
  })

  it('uses the union of all nodes across multiple paths', () => {
    const result = calculateSpanTiming(nodes, [
      { source: 'a', target: 'b' },
      { source: 'b', target: 'd' },
      { source: 'a', target: 'c' },
      { source: 'c', target: 'd' },
    ], 'a', 'd')
    expect(result.nodeIds).toEqual(['a', 'b', 'c', 'd'])
    expect(result.totalMs).toBe(100)
    expect(result.nodeCount).toBe(4)
    expect(result.percent).toBeCloseTo(50)
  })
})
