import { describe, expect, it } from 'vitest'

import { clearSession, getSession, patchDraftNode, setDraft, updateSession } from '@/lib/flowDraft'

const graph = { nodes: [{ id: 'a', type: 'grayscale', params: { x: 1 } }, { id: 'b', type: 'judge', params: {} }], edges: [{ source: 'a', target: 'b' }] }

describe('flowDraft store', () => {
  it('starts empty and merges patches', () => {
    clearSession(1)
    expect(getSession(1).draft).toBeNull()
    updateSession(1, { reuseImage: true })
    expect(getSession(1).reuseImage).toBe(true)
    expect(getSession(1).scratch).toBeNull()
  })

  it('patchDraftNode only touches the target node and marks dirty', () => {
    setDraft(2, { baseVersion: 3, graph, name: 'f', description: '', dirty: false })
    patchDraftNode(2, 'a', { params: { x: 2 } })
    const d = getSession(2).draft!
    expect(d.dirty).toBe(true)
    expect(d.graph.nodes[0].params).toEqual({ x: 2 })
    expect(d.graph.nodes[1]).toEqual(graph.nodes[1])
    expect(d.baseVersion).toBe(3)
  })

  it('patchDraftNode is a no-op without a draft', () => {
    clearSession(3)
    patchDraftNode(3, 'a', { params: {} })
    expect(getSession(3).draft).toBeNull()
  })
})
