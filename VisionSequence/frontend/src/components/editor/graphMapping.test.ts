import { describe, expect, it } from 'vitest'

import { addInputSource, autoConnectOnInsert, computeLayout, graphFrom, isFlowHandle, nextNodeId, removeInputSource, replaceInputSource, toFlowEdges, toFlowNodes } from '@/components/editor/graphMapping'
import { createHistory, pushHistory, undoHistory } from '@/lib/flowHistory'
import type { FlowGraph, ToolPort, ToolTypeDef } from '@/lib/types'

function port(key: string, type: ToolPort['type'], required = false, implicit = false): ToolPort {
  return { key, label: key, type, required, multiple: false, tone: 'neutral', implicit }
}

function tool(key: string, inputs: ToolPort[], outputs: ToolPort[]): ToolTypeDef {
  return { key, label: key, description: '', category: 'test', category_label: 'Test', icon: 'Box', params: [], inputs, outputs, heavy: false }
}

const defs = new Map<string, ToolTypeDef>([
  ['image_source', tool('image_source', [], [port('image', 'image')])],
  ['fixed_image', tool('fixed_image', [], [port('image', 'image')])],
  ['grayscale', tool('grayscale', [port('image', 'image')], [port('image', 'image')])],
  ['judge', tool('judge', [port('_flow', 'flow')], [])],
  ['filter', tool('filter', [port('image', 'image', true)], [port('image', 'image'), port('_image', 'image', false, true)])],
  ['no_image_input', tool('no_image_input', [port('value', 'number')], [port('value', 'number')])],
  ['measure', tool('measure', [port('image', 'image', true)], [port('value', 'number'), port('_image', 'image', false, true)])],
])

const graph: FlowGraph = {
  nodes: [
    { id: 'src', type: 'image_source', params: {}, position: { x: 0, y: 0 } },
    { id: 'g', type: 'grayscale', params: {}, position: { x: 300, y: 0 } },
    { id: 'n', type: 'note', label: 'Note', description: 'hi', position: { x: 0, y: 200 }, width: 200, height: 80 },
  ],
  edges: [{ id: 'e1', source: 'src', target: 'g', source_handle: 'image', target_handle: 'image' }],
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

  it('preserves meta and _publish through React Flow mapping', () => {
    const source: FlowGraph = {
      nodes: [{ id: 'm', type: 'measure', params: { _publish: { value: 'diameter' } }, meta: { inspect: { task_id: 't1', role: 'find', kind: 'measure_diameter', schema_version: 1, required: true } } }],
      edges: [],
    }
    const nodes = toFlowNodes(source, defs)
    const back = graphFrom(nodes, [], new Map(source.nodes.map((node) => [node.id, node])))
    expect(back.nodes[0].meta).toEqual(source.nodes[0].meta)
    expect(back.nodes[0].params?._publish).toEqual({ value: 'diameter' })
  })

  it('auto-connects inserted image tools from the selected node', () => {
    const source: FlowGraph = { nodes: [{ id: 'src', type: 'image_source' }, { id: 'f', type: 'filter' }, { id: 'm', type: 'measure' }], edges: [] }
    expect(autoConnectOnInsert(source, 'm', 'f', defs)).toMatchObject({ source: 'f', source_handle: 'image', target: 'm', target_handle: 'image' })
  })

  it('auto-connects from the first image source when nothing is selected', () => {
    const source: FlowGraph = { nodes: [{ id: 'src', type: 'fixed_image' }, { id: 'm', type: 'measure' }], edges: [] }
    expect(autoConnectOnInsert(source, 'm', null, defs)).toMatchObject({ source: 'src', source_handle: 'image', target: 'm', target_handle: 'image' })
  })

  it('does not auto-connect from notes or self-selection', () => {
    const source: FlowGraph = { nodes: [{ id: 'n', type: 'note' }, { id: 'm', type: 'measure' }], edges: [] }
    expect(autoConnectOnInsert(source, 'm', 'n', defs)).toBeNull()
    expect(autoConnectOnInsert(source, 'm', 'm', defs)).toBeNull()
  })

  it('does not auto-connect when the new tool has no image input or the flow has no source', () => {
    expect(autoConnectOnInsert({ nodes: [{ id: 'src', type: 'image_source' }, { id: 'x', type: 'no_image_input' }], edges: [] }, 'x', null, defs)).toBeNull()
    expect(autoConnectOnInsert({ nodes: [{ id: 'm', type: 'measure' }], edges: [] }, 'm', null, defs)).toBeNull()
  })

  it('falls back to the selected node _image passthrough when it has no declared image output', () => {
    const source: FlowGraph = { nodes: [{ id: 'm1', type: 'measure' }, { id: 'm2', type: 'measure' }], edges: [] }
    expect(autoConnectOnInsert(source, 'm2', 'm1', defs)).toMatchObject({ source: 'm1', source_handle: '_image', target: 'm2' })
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

  it('replaces only the selected single input edge', () => {
    const source: FlowGraph = {
      nodes: [{ id: 'a', type: 'measure' }, { id: 'b', type: 'measure' }, { id: 'c', type: 'measure' }, { id: 't', type: 'measure' }],
      edges: [
        { id: 'old', source: 'a', target: 't', source_handle: 'value', target_handle: 'image' },
        { id: 'keep', source: 'c', target: 't', source_handle: 'value', target_handle: 'other' },
      ],
    }
    const next = replaceInputSource(source, 't', 'image', { nodeId: 'b', portKey: 'value' })
    expect(next.edges).toHaveLength(2)
    expect(next.edges).toContainEqual(source.edges[1])
    expect(next.edges.find((edge) => edge.target_handle === 'image')).toMatchObject({ source: 'b', source_handle: 'value', target: 't' })
  })

  it('adds and removes sources for multiple inputs', () => {
    const source: FlowGraph = { nodes: [{ id: 'a', type: 'measure' }, { id: 't', type: 'measure' }], edges: [] }
    const added = addInputSource(source, 't', 'images', { nodeId: 'a', portKey: 'image' })
    expect(added.edges).toMatchObject([{ source: 'a', target: 't', source_handle: 'image', target_handle: 'images' }])
    expect(addInputSource(added, 't', 'images', { nodeId: 'a', portKey: 'image' }).edges).toHaveLength(1)
    expect(removeInputSource(added, 't', 'images', { nodeId: 'a', portKey: 'image' }).edges).toEqual([])
  })

  it('treats one source picker change as one undo step', () => {
    const source: FlowGraph = {
      nodes: [{ id: 'a', type: 'measure' }, { id: 'b', type: 'measure' }, { id: 't', type: 'measure' }],
      edges: [{ id: 'old', source: 'a', target: 't', source_handle: 'image', target_handle: 'image' }],
    }
    const history = pushHistory(createHistory<FlowGraph>(), source)
    const changed = replaceInputSource(source, 't', 'image', { nodeId: 'b', portKey: 'image' })
    const previous = undoHistory(history, changed)
    expect(previous.value).toEqual(source)
  })
})
