/** 埠的顯示規則與順序（PRODUCT-DIRECTION v2 §2-3）：已接線鎖顯示、primary／alias／必填未接預設顯示、其餘收合；order 排序；自動排序照對端位置；名稱清單照埠順序。 */
import { describe, expect, it } from 'vitest'

import { autoOrderKeys, connectedHandles, graphOutputNames, orderedPorts, portLayout } from './portLayout'
import type { GraphEdge, GraphNode, ToolPort, ToolTypeDef } from './types'

function port(key: string, type: ToolPort['type'] = 'number', extra: Partial<ToolPort> = {}): ToolPort {
  return { key, label: key.toUpperCase(), type, required: false, multiple: false, tone: 'neutral', ...extra }
}

const def: ToolTypeDef = {
  key: 'measure', label: 'Measure', description: '', category: 'measure', category_label: 'Measure', icon: 'Ruler', heavy: false, params: [],
  inputs: [port('image', 'image', { required: true, primary: true }), port('region', 'region', { required: true }), port('ref', 'number')],
  outputs: [port('image', 'image', { primary: true }), port('value'), port('width'), port('ok', 'flow'), port('_image', 'image', { implicit: true }), port('_overlays', 'list', { implicit: true })],
}

describe('portLayout', () => {
  it('shows connected, primary, published and required-unconnected ports and collapses the rest', () => {
    const node: GraphNode = { id: 'm', type: 'measure', params: {}, interface: { outputs: [{ key: 'width', alias: 'w' }] } }
    const layout = portLayout(def, node, 'out', new Set(['value']))
    expect(layout.all.map((view) => `${view.port.key}:${view.reason}`)).toEqual(['image:primary', 'value:connected', 'width:alias', 'ok:primary', '_image:collapsed', '_overlays:collapsed'])
    expect(layout.hidden.map((view) => view.key)).toEqual(['_image', '_overlays'])
    const inputs = portLayout(def, node, 'in', new Set())
    expect(inputs.visible.map((view) => view.key)).toEqual(['image', 'region'])
    expect(inputs.all.find((view) => view.port.key === 'region')?.reason).toBe('required')
    expect(inputs.hiddenProblems).toEqual([])
  })

  it('honours explicit exposed flags but never hides a connected port', () => {
    const node: GraphNode = { id: 'm', type: 'measure', params: {}, interface: { inputs: [{ key: 'region', exposed: false }, { key: 'ref', exposed: true }], outputs: [{ key: 'image', exposed: false }] } }
    const inputs = portLayout(def, node, 'in', new Set(['image']))
    expect(inputs.visible.map((view) => view.key)).toEqual(['image', 'ref'])
    // 藏起來的必填未接輸入＝隱藏的問題埠
    expect(inputs.hiddenProblems.map((view) => view.key)).toEqual(['region'])
    expect(inputs.all.find((view) => view.port.key === 'region')?.missing).toBe(true)
    // ROI 埠的同名參數已填就不算缺
    const filled = portLayout(def, { ...node, params: { region: { shape: 'rect', x: 0, y: 0, w: 1, h: 1 } } }, 'in', new Set(['image']))
    expect(filled.hiddenProblems).toEqual([])
    const outputs = portLayout(def, node, 'out', new Set(['image']))
    expect(outputs.all[0]).toMatchObject({ reason: 'connected', visible: true, customised: true })
  })

  it('orders ports by interface order, catalogue order and implicit ports last', () => {
    const node: GraphNode = { id: 'm', type: 'measure', params: {}, interface: { outputs: [{ key: '_overlays', order: 0 }, { key: 'width', order: 1 }] } }
    expect(orderedPorts(def.outputs, node, 'out').map((view) => view.key)).toEqual(['_overlays', 'width', 'image', 'value', 'ok', '_image'])
    expect(orderedPorts(def.outputs, { interface: undefined }, 'out').map((view) => view.key)).toEqual(['image', 'value', 'width', 'ok', '_image', '_overlays'])
  })

  it('auto-orders connected ports by the position of their peers and keeps the rest behind', () => {
    const node: GraphNode = { id: 'm', type: 'measure', params: {}, position: { x: 0, y: 0 } }
    const nodes: GraphNode[] = [node, { id: 'a', type: 'x', params: {}, position: { x: 200, y: 300 } }, { id: 'b', type: 'x', params: {}, position: { x: 200, y: 20 } }]
    const edges: GraphEdge[] = [{ source: 'm', source_handle: 'value', target: 'a', target_handle: 'v' }, { source: 'm', source_handle: 'ok', target: 'b', target_handle: '_flow' }]
    expect(autoOrderKeys(def, node, 'out', edges, nodes)).toEqual(['ok', 'value', 'image', 'width', '_image', '_overlays'])
    expect(connectedHandles('m', edges, 'out')).toEqual(new Set(['value', 'ok']))
    expect(connectedHandles('a', edges, 'in')).toEqual(new Set(['v']))
  })

  it('lists graph output names in port order after output steps', () => {
    const defs = new Map([[def.key, def]])
    const nodes: GraphNode[] = [
      { id: 'm', type: 'measure', params: {}, interface: { outputs: [{ key: 'value', alias: 'v', order: 1 }, { key: 'width', alias: 'w', order: 0 }] } },
      { id: 'o', type: 'output', params: { name: 'verdict' } },
      { id: 'f', type: 'format_text', params: { name: '' } },
    ]
    expect(graphOutputNames(nodes, defs)).toEqual(['w', 'v', 'verdict'])
  })
})
