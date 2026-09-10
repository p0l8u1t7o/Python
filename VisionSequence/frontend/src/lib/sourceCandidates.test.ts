import { describe, expect, it } from 'vitest'

import { sourceCandidates } from '@/lib/sourceCandidates'
import type { FlowGraph, ToolPort, ToolTypeDef } from '@/lib/types'

function port(key: string, type: ToolPort['type'], extra: Partial<ToolPort> = {}): ToolPort {
  return { key, label: key, type, required: false, multiple: false, tone: 'neutral', ...extra }
}

function tool(key: string, inputs: ToolPort[], outputs: ToolPort[]): ToolTypeDef {
  return { key, label: key, description: '', category: 'test', category_label: 'Test', icon: 'Box', heavy: false, params: [], inputs, outputs }
}

describe('sourceCandidates', () => {
  it('filters by connection type and existing graph validation rules', () => {
    const defs = new Map([
      ['source', tool('source', [], [port('image', 'image'), port('value', 'number')])],
      ['target', tool('target', [port('image', 'image')], [])],
    ])
    const graph: FlowGraph = {
      nodes: [{ id: 's', type: 'source' }, { id: 't', type: 'target' }],
      edges: [],
    }

    expect(sourceCandidates(graph, 't', 'image', defs).map((item) => item.portKey)).toEqual(['image'])
  })

  it('filters by semantics only when both sides declare them', () => {
    const defs = new Map([
      ['shape', tool('shape', [], [
        port('circle', 'any', { semantic: 'circle' }),
        port('line', 'any', { semantic: 'line' }),
        port('plain', 'any'),
      ])],
      ['target', tool('target', [port('geometry', 'any', { accepts_semantics: ['circle'] })], [])],
      ['plain_target', tool('plain_target', [port('geometry', 'any')], [])],
    ])
    const graph: FlowGraph = {
      nodes: [{ id: 'shape', type: 'shape' }, { id: 'target', type: 'target' }, { id: 'plain', type: 'plain_target' }],
      edges: [],
    }

    expect(sourceCandidates(graph, 'target', 'geometry', defs).map((item) => item.portKey)).toEqual(['circle', 'plain'])
    expect(sourceCandidates(graph, 'plain', 'geometry', defs).map((item) => item.portKey)).toEqual(['circle', 'line', 'plain'])
  })

  it('excludes self, notes, implicit outputs, branch outputs and cycle-forming sources', () => {
    const defs = new Map([
      ['source', tool('source', [], [port('out', 'number'), port('_image', 'image', { implicit: true }), port('ok', 'flow')])],
      ['target', tool('target', [port('value', 'number')], [port('out', 'number')])],
      ['downstream', tool('downstream', [port('value', 'number')], [port('out', 'number')])],
    ])
    const graph: FlowGraph = {
      nodes: [
        { id: 'a', type: 'target' },
        { id: 'b', type: 'source' },
        { id: 'note', type: 'note' },
        { id: 'c', type: 'downstream' },
      ],
      edges: [{ source: 'a', target: 'c', source_handle: 'out', target_handle: 'value' }],
    }

    expect(sourceCandidates(graph, 'a', 'value', defs).map((item) => `${item.nodeId}.${item.portKey}`)).toEqual(['b.out'])
  })

  it('excludes downstream nodes that would create a loop', () => {
    const defs = new Map([
      ['step', tool('step', [port('value', 'number')], [port('out', 'number')])],
    ])
    const graph: FlowGraph = {
      nodes: [{ id: 'a', type: 'step' }, { id: 'b', type: 'step' }, { id: 'c', type: 'step' }],
      edges: [
        { source: 'a', target: 'b', source_handle: 'out', target_handle: 'value' },
        { source: 'b', target: 'c', source_handle: 'out', target_handle: 'value' },
      ],
    }

    expect(sourceCandidates(graph, 'a', 'value', defs)).toHaveLength(0)
  })

  it('sorts same inspect task first, locate tasks second, then graph order', () => {
    const defs = new Map([
      ['source', tool('source', [], [port('out', 'number')])],
      ['target', tool('target', [port('value', 'number')], [])],
    ])
    const graph: FlowGraph = {
      nodes: [
        { id: 'target', type: 'target', meta: { inspect: { task_id: 't1', role: 'judge', kind: 'measure_diameter', schema_version: 1, required: true } } },
        { id: 'plain', type: 'source' },
        { id: 'locate', type: 'source', meta: { inspect: { task_id: 'loc', role: 'find', kind: 'locate_part', schema_version: 1, required: true } } },
        { id: 'same', type: 'source', meta: { inspect: { task_id: 't1', role: 'find', kind: 'measure_diameter', schema_version: 1, required: true } } },
      ],
      edges: [],
    }

    expect(sourceCandidates(graph, 'target', 'value', defs).map((item) => item.nodeId)).toEqual(['same', 'locate', 'plain'])
  })
})
