import { describe, expect, it } from 'vitest'
import type { Edge, Node } from '@xyflow/react'

import { collapseView, expandOnDrop, groupHandleId, groupsOf, parseGroupHandleId } from './nodeGroups'
import type { FlowGraph } from './types'

const graph: FlowGraph = {
  nodes: [
    { id: 'src', type: 'image_source', label: 'Camera', position: { x: 0, y: 0 }, meta: { inspect: { task_id: 'acq', role: 'find', kind: 'locate_part', schema_version: 1, required: true } } },
    { id: 'find-a', type: 'blob', label: 'Find rim', position: { x: 300, y: 0 }, meta: { inspect: { task_id: 'diameter-a', role: 'find', kind: 'measure_diameter', schema_version: 1, required: true } } },
    { id: 'judge-a', type: 'in_range', label: 'Judge rim', position: { x: 580, y: 20 }, meta: { inspect: { task_id: 'diameter-a', role: 'judge', kind: 'measure_diameter', schema_version: 1, required: true } } },
    { id: 'find-b', type: 'blob', position: { x: 300, y: 220 }, meta: { inspect: { task_id: 'count-b', role: 'find', kind: 'count_objects', schema_version: 1, required: true } } },
    { id: 'judge-b', type: 'in_range', position: { x: 580, y: 240 }, meta: { inspect: { task_id: 'count-b', role: 'judge', kind: 'count_objects', schema_version: 1, required: true } } },
  ],
  edges: [
    { id: 'e1', source: 'src', source_handle: 'image', target: 'find-a', target_handle: 'image' },
    { id: 'e2', source: 'find-a', source_handle: 'count', target: 'judge-a', target_handle: 'value' },
    { id: 'e3', source: 'src', source_handle: 'image', target: 'find-b', target_handle: 'image' },
    { id: 'e4', source: 'find-b', source_handle: 'count', target: 'judge-b', target_handle: 'value' },
    { id: 'e5', source: 'find-a', source_handle: 'image', target: 'judge-b', target_handle: 'image' },
    { id: 'e6', source: 'find-a', source_handle: 'image', target: 'judge-b', target_handle: 'image' },
  ],
}

const flowNodes: Node[] = graph.nodes.map((node) => ({ id: node.id, type: 'tool', position: node.position ?? { x: 0, y: 0 }, data: {} }))
const flowEdges: Edge[] = graph.edges.map((edge) => ({ id: edge.id ?? '', source: edge.source, target: edge.target, sourceHandle: edge.source_handle, targetHandle: edge.target_handle }))

describe('nodeGroups', () => {
  it('groups inspection nodes by task id and keeps image sources out', () => {
    const groups = groupsOf(graph)
    expect(groups.map((group) => group.task_id)).toEqual(['diameter-a', 'count-b'])
    expect(groups[0]).toMatchObject({ kind: 'measure_diameter', node_ids: ['find-a', 'judge-a'], label: 'Find rim' })
    expect(groups[1].label).toBe('count_objects')
  })

  it('uses translated kind labels when no member has a title', () => {
    const group = groupsOf(graph, undefined, (key, fallback) => key === 'editor.groups.kinds.count_objects' ? 'Count objects' : fallback)
      .find((item) => item.task_id === 'count-b')
    expect(group?.label).toBe('Count objects')
  })

  it('falls back from an unnamed find role to the first titled member', () => {
    const source: FlowGraph = {
      nodes: [
        { id: 'find', type: 'blob', meta: { inspect: { task_id: 't1', role: 'find', kind: 'measure_diameter', schema_version: 1, required: true } } },
        { id: 'judge', type: 'in_range', label: 'Diameter spec', meta: { inspect: { task_id: 't1', role: 'judge', kind: 'measure_diameter', schema_version: 1, required: true } } },
      ],
      edges: [],
    }
    expect(groupsOf(source)[0].label).toBe('Diameter spec')
  })

  it('collapses members into display-only group nodes and hides internal edges', () => {
    const view = collapseView(flowNodes, flowEdges, new Set(['diameter-a', 'count-b']), graph)
    expect(view.nodes.map((node) => node.id).sort()).toEqual(['group:count-b', 'group:diameter-a', 'src'])
    expect(view.edges.some((edge) => edge.id.includes('find-a.count-judge-a.value'))).toBe(false)
    expect(view.edges).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: 'src', target: 'group:diameter-a' }),
      expect.objectContaining({ source: 'src', target: 'group:count-b' }),
    ]))
  })

  it('rewires boundary edges to encoded handles and merges duplicate pairs with a count', () => {
    const view = collapseView(flowNodes, flowEdges, new Set(['diameter-a', 'count-b']), graph)
    const cross = view.edges.find((edge) => edge.source === 'group:diameter-a' && edge.target === 'group:count-b')
    expect(cross).toMatchObject({ label: '2' })
    expect(parseGroupHandleId(cross?.sourceHandle)).toEqual({ nodeId: 'find-a', port: 'image' })
    expect(parseGroupHandleId(cross?.targetHandle)).toEqual({ nodeId: 'judge-b', port: 'image' })
    expect(cross?.sourceHandle).toBe(groupHandleId('find-a', 'image'))
  })

  it('expanding restores the original graph columns exactly', () => {
    const view = collapseView(flowNodes, flowEdges, new Set(['diameter-a']), graph)
    expect(view.nodes.some((node) => node.id === 'find-a')).toBe(false)
    const expanded = collapseView(flowNodes, flowEdges, new Set(), graph)
    expect(expanded.nodes).toEqual(flowNodes)
    expect(expanded.edges).toEqual(flowEdges)
  })

  it('moves only task members when a group is dropped', () => {
    const moved = expandOnDrop(graph, 'diameter-a', { x: 10, y: -5 })
    expect(moved.nodes.find((node) => node.id === 'find-a')?.position).toEqual({ x: 310, y: -5 })
    expect(moved.nodes.find((node) => node.id === 'judge-a')?.position).toEqual({ x: 590, y: 15 })
    expect(moved.nodes.find((node) => node.id === 'find-b')?.position).toEqual({ x: 300, y: 220 })
    expect(moved.edges).toEqual(graph.edges)
  })
})
