/** 複合工具純函式：封裝選取（邊界埠、必填未接、具名輸出搬到實例、邊重接）、介面候選、對外參數規格、key 轉換。 */
import { describe, expect, it } from 'vitest'

import { encapsulateSelection, interfaceCandidates, isCompositeType, orderedParamSpecs, slugKey, splitCompositeKey, withParamOrder, withParamSpec } from './composite'
import type { FlowGraph, ToolParam, ToolPort, ToolTypeDef } from './types'

function port(key: string, type: ToolPort['type'] = 'image', extra: Partial<ToolPort> = {}): ToolPort {
  return { key, label: key, type, required: false, multiple: false, tone: 'neutral', ...extra }
}
function param(key: string, kind: ToolParam['kind'] = 'number'): ToolParam {
  return { key, label: key, kind, required: false, default: 0, help_text: '', options: [], unit: '', minimum: null, maximum: null, step: null, visible_when: null, shapes: [], accept: '', group: '' }
}
function def(key: string, inputs: ToolPort[], outputs: ToolPort[], params: ToolParam[] = []): ToolTypeDef {
  return { key, label: key, description: '', category: 'preprocess', category_label: 'P', icon: 'Box', heavy: false, params, inputs, outputs }
}

const defs = new Map<string, ToolTypeDef>([
  ['image_source', def('image_source', [], [port('image')])],
  ['grayscale', def('grayscale', [port('image', 'image', { required: true })], [port('image')])],
  ['threshold', def('threshold', [port('image', 'image', { required: true }), port('roi', 'region', { required: true })], [port('image')], [param('threshold'), param('code', 'code')])],
  ['blob', def('blob', [port('image', 'image', { required: true })], [port('count', 'number'), port('found', 'flow')], [param('min_area')])],
  ['output', def('output', [port('value', 'any', { required: true })], [])],
])

const graph: FlowGraph = {
  nodes: [
    { id: 'src', type: 'image_source', params: {}, position: { x: 0, y: 0 } },
    { id: 'gray', type: 'grayscale', params: {}, position: { x: 200, y: 0 } },
    { id: 'thr', type: 'threshold', params: { threshold: 90, roi: { shape: 'rect' } }, position: { x: 400, y: 0 } },
    { id: 'blob', type: 'blob', params: {}, position: { x: 600, y: 40 }, interface: { outputs: [{ key: 'count', alias: 'holes' }] } },
    { id: 'out', type: 'output', params: { name: 'n' }, position: { x: 800, y: 0 } },
    { id: 'note', type: 'note', params: { text: 'hi' }, position: { x: 0, y: 200 } },
  ],
  edges: [
    { id: 'e1', source: 'src', source_handle: 'image', target: 'gray', target_handle: 'image' },
    { id: 'e2', source: 'gray', source_handle: 'image', target: 'thr', target_handle: 'image' },
    { id: 'e3', source: 'thr', source_handle: 'image', target: 'blob', target_handle: 'image' },
    { id: 'e4', source: 'blob', source_handle: 'count', target: 'out', target_handle: 'value' },
    { id: 'e5', source: 'blob', source_handle: 'found', target: 'out', target_handle: '_flow' },
  ],
}

describe('encapsulateSelection', () => {
  it('turns the selection into a tool graph, an interface and one instance node', () => {
    const result = encapsulateSelection(graph, ['gray', 'thr', 'blob', 'note'], defs, 'count_holes', 'Count holes')
    expect(result).not.toBeNull()
    const { toolGraph, interface: iface, instance, graph: after } = result!
    expect(toolGraph.nodes.map((node) => node.id)).toEqual(['gray', 'thr', 'blob'])
    expect(toolGraph.nodes[0].position).toEqual({ x: 40, y: 40 })
    expect(toolGraph.edges.map((edge) => edge.id)).toEqual(['e2', 'e3'])
    // 工具內部不留具名輸出名稱；名稱搬到實例上
    expect(toolGraph.nodes[2].interface).toBeUndefined()
    expect(instance.interface).toEqual({ outputs: [{ key: 'blob:count', alias: 'holes' }] })
    // 跨邊界的輸入埠；thr.roi 是必填但參數已填，不對外
    expect(iface.inputs).toEqual([{ key: 'gray:image', exposed: true, order: 0 }])
    expect(iface.outputs).toEqual([{ key: 'blob:count', exposed: true, order: 0 }, { key: 'blob:found', exposed: true, order: 1 }])
    expect(instance.type).toBe('composite:count_holes')
    expect(instance.id).toBe('count_holes-1')
    expect(after.nodes.map((node) => node.id)).toEqual(['src', 'out', 'note', 'count_holes-1'])
    expect(after.edges).toEqual([
      { id: 'src-count_holes-1-gray:image', source: 'src', source_handle: 'image', target: 'count_holes-1', target_handle: 'gray:image' },
      { id: 'count_holes-1-count-out-value', source: 'count_holes-1', source_handle: 'blob:count', target: 'out', target_handle: 'value' },
      { id: 'count_holes-1-found-out-_flow', source: 'count_holes-1', source_handle: 'blob:found', target: 'out', target_handle: '_flow' },
    ])
  })

  it('exposes unconnected required inputs and returns null for a note-only selection', () => {
    const result = encapsulateSelection(graph, ['thr'], defs, 't', 'T')!
    expect(result.interface.inputs?.map((spec) => spec.key)).toEqual(['thr:image'])
    expect(encapsulateSelection(graph, ['note'], defs, 't', 'T')).toBeNull()
  })
})

describe('interfaceCandidates', () => {
  it('lists inner ports and parameters, marking inputs fed from inside', () => {
    const tool: FlowGraph = { nodes: graph.nodes.filter((node) => ['gray', 'thr', 'blob'].includes(node.id)), edges: graph.edges.filter((edge) => ['e2', 'e3'].includes(edge.id ?? '')) }
    const candidates = interfaceCandidates(tool, defs)
    expect(candidates.inputs.map((item) => `${item.key}${item.connectedInside ? '!' : ''}`)).toEqual(['gray:image', 'thr:image!', 'thr:roi', 'blob:image!'])
    expect(candidates.outputs.map((item) => item.key)).toEqual(['gray:image', 'thr:image', 'blob:count', 'blob:found'])
    // code 參數不能對外（腳本核准繞不過）
    expect(candidates.params.map((item) => item.key)).toEqual(['thr:threshold', 'blob:min_area'])
    expect(candidates.params[0].label).toBe('threshold: threshold')
  })
})

describe('param specs and keys', () => {
  it('adds, updates, orders and removes exposed parameters', () => {
    let iface = withParamSpec({}, 'thr:threshold', {})
    expect(iface).toEqual({ params: [{ key: 'thr:threshold', order: 0 }] })
    iface = withParamSpec(iface, 'blob:min_area', { alias: 'Min area', teach: true })
    iface = withParamSpec(iface, 'thr:threshold', { alias: 'Level' })
    expect(orderedParamSpecs(withParamOrder(iface, ['blob:min_area', 'thr:threshold'])).map((spec) => `${spec.key}=${spec.alias}`)).toEqual(['blob:min_area=Min area', 'thr:threshold=Level'])
    expect(withParamSpec(withParamSpec(iface, 'thr:threshold', null), 'blob:min_area', null)).toEqual({})
  })

  it('slugs labels into tool keys and splits composite keys', () => {
    expect(slugKey('Count Holes v2')).toBe('count_holes_v2')
    expect(slugKey('計數')).toBe('tool')
    expect(slugKey('123 go')).toBe('tool_123_go')
    expect(isCompositeType('composite:x')).toBe(true)
    expect(isCompositeType('blob')).toBe(false)
    expect(splitCompositeKey('inner:blob:count')).toEqual({ inner: 'inner', port: 'blob:count' })
  })
})
