import { describe, expect, it } from 'vitest'

import { flowGraphSignature, shouldSaveDraftVersion } from './flowAutoVersion'
import type { FlowGraph } from './types'

describe('flow auto version helpers', () => {
  it('does not save when graph content has not changed', () => {
    const left: FlowGraph = {
      nodes: [{ id: 'a', type: 'threshold', params: { high: 20, low: 10 } }],
      edges: [{ source: 'a', target: 'b', target_handle: 'image', source_handle: 'image' }],
    }
    const right: FlowGraph = {
      nodes: [{ type: 'threshold', id: 'a', params: { low: 10, high: 20 } }],
      edges: [{ target_handle: 'image', source_handle: 'image', target: 'b', source: 'a' }],
    }
    const signature = flowGraphSignature(left)

    expect(flowGraphSignature(right)).toBe(signature)
    expect(shouldSaveDraftVersion({ enabled: true, dirty: true, currentSignature: signature, lastSavedSignature: signature })).toBe(false)
  })

  it('saves only when enabled, dirty and graph content changed', () => {
    const saved = flowGraphSignature({ nodes: [{ id: 'a', type: 'threshold', params: { limit: 10 } }], edges: [] })
    const current = flowGraphSignature({ nodes: [{ id: 'a', type: 'threshold', params: { limit: 11 } }], edges: [] })

    expect(shouldSaveDraftVersion({ enabled: true, dirty: true, currentSignature: current, lastSavedSignature: saved })).toBe(true)
    expect(shouldSaveDraftVersion({ enabled: false, dirty: true, currentSignature: current, lastSavedSignature: saved })).toBe(false)
    expect(shouldSaveDraftVersion({ enabled: true, dirty: false, currentSignature: current, lastSavedSignature: saved })).toBe(false)
  })
})
