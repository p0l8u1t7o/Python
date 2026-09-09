import { describe, expect, it } from 'vitest'

import { countPreviewSequenceResult, createPreviewSequenceState, findPreviewSequenceSource, graphForPreviewSequenceItem, isPreviewSequenceDone, nextPreviewSequenceIndex } from './previewSequence'
import type { FlowGraph, ImageSource } from './types'

describe('preview sequence helpers', () => {
  it('advances through images and counts OK and NG results', () => {
    let state = createPreviewSequenceState(2)
    expect(nextPreviewSequenceIndex(state)).toBe(1)
    expect(isPreviewSequenceDone(state)).toBe(false)

    state = countPreviewSequenceResult(state, 'ok')
    expect(state).toMatchObject({ index: 1, ok: 1, ng: 0 })
    expect(nextPreviewSequenceIndex(state)).toBe(2)

    state = countPreviewSequenceResult(state, 'ng')
    expect(state).toMatchObject({ index: 2, ok: 1, ng: 1 })
    expect(isPreviewSequenceDone(state)).toBe(true)
    expect(nextPreviewSequenceIndex(state)).toBeNull()
  })

  it('detects fixed images and builds a fixed-index preview graph', () => {
    const graph: FlowGraph = {
      nodes: [{ id: 'src', type: 'fixed_image', params: { mode: 'cycle', images: [{ id: 'a' }, { id: 'b' }] } }],
      edges: [],
    }
    const source = findPreviewSequenceSource(graph, [])
    expect(source).toMatchObject({ kind: 'fixed_image', nodeId: 'src', total: 2 })

    const patched = graphForPreviewSequenceItem(graph, source!, 2)
    expect(patched.nodes[0].params).toMatchObject({ mode: 'fixed', index: 2 })
    expect(graph.nodes[0].params).toMatchObject({ mode: 'cycle' })
  })

  it('detects folder sources with a known count', () => {
    const graph: FlowGraph = { nodes: [{ id: 'src', type: 'image_source', params: { source_id: 3 } }], edges: [] }
    const sources: ImageSource[] = [{
      id: 3,
      name: 'Folder',
      group: '',
      kind: 'folder',
      config: { path: 'D:/images' },
      status: { count: 4 },
      is_enabled: true,
      created_at: '',
      updated_at: '',
    }]
    expect(findPreviewSequenceSource(graph, sources)).toMatchObject({ kind: 'folder', nodeId: 'src', total: 4, folderPath: 'D:/images' })
  })
})
