import { describe, expect, it } from 'vitest'

import { computeLayout, graphFrom, isFlowHandle, nextNodeId, toFlowEdges, toFlowNodes } from '@/components/editor/graphMapping'
import type { FlowGraph, ToolTypeDef } from '@/lib/types'

const defs = new Map<string, ToolTypeDef>([
  ['grayscale', { key: 'grayscale', label: '灰階', description: '', category: 'preprocess', category_label: '影像前處理', icon: 'Box', params: [], inputs: [{ key: 'image', label: '影像', type: 'image' }], outputs: [{ key: 'image', label: '影像', type: 'image' }], heavy: false } as unknown as ToolTypeDef],
  ['judge', { key: 'judge', label: '判定', description: '', category: 'logic', category_label: '邏輯', icon: 'Box', params: [], inputs: [{ key: '_flow', label: '分支', type: 'flow' }], outputs: [], heavy: false } as unknown as ToolTypeDef],
])
const graph: FlowGraph = {
  nodes: [
    { id: 'src', type: 'image_source', params: {}, position: { x: 0, y: 0 } },
    { id: 'g', type: 'grayscale', params: {}, position: { x: 300, y: 0 } },
    { id: 'n', type: 'note', label: '註解', description: 'hi', position: { x: 0, y: 200 }, width: 200, height: 80 },
  ],
  edges: [{ id: 'e1', source: 'src', target: 'g', source_handle: '', target_handle: '' }],
}

describe('graphMapping', () => {
  it('maps nodes and notes to React Flow node types and back losslessly', () => {
    const nodes = toFlowNodes(graph, defs)
    expect(nodes.map((n) => n.type)).toEqual(['tool', 'tool', 'note'])
    expect(nodes[2].width).toBe(200)
    const edges = toFlowEdges(graph, defs)
    expect(edges).toHaveLength(1)
    const payloads = new Map(graph.nodes.map((n) => [n.id, n]))
    const back = graphFrom(nodes, edges, payloads)
    expect(back.nodes.map((n) => n.id)).toEqual(['src', 'g', 'n'])
    expect(back.edges[0]).toMatchObject({ source: 'src', target: 'g' })
  })

  it('nextNodeId skips taken ids', () => {
    expect(nextNodeId(new Set(['blob-1', 'blob-2']), 'blob')).toBe('blob-3')
    expect(nextNodeId(new Set(), 'note')).toBe('note-1')
  })

  it('isFlowHandle only for _flow', () => {
    expect(isFlowHandle('_flow')).toBe(true)
    expect(isFlowHandle('image')).toBe(false)
    expect(isFlowHandle(null)).toBe(false)
  })

  it('computeLayout places downstream nodes to the right', () => {
    const layout = computeLayout(graph)
    expect(layout.get('g')!.x).toBeGreaterThan(layout.get('src')!.x)
  })
})
