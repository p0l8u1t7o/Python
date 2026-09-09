import { describe, expect, it } from 'vitest'
import { checkConnection } from './graphValidation'
import type { GraphEdge, GraphNode, ToolPort, ToolTypeDef } from './types'

// 與後端 graph.validate_graph 同一條規則：多重埠本來就收多張同型別，所以一條 list 線可以接進去；單一埠不放行。
function port(key: string, type: ToolPort['type'], multiple = false): ToolPort {
  return { key, label: key, type, required: false, multiple, tone: 'neutral' }
}

function def(key: string, inputs: ToolPort[], outputs: ToolPort[]): ToolTypeDef {
  return { key, label: key, description: '', category: 'source', category_label: 'Source', icon: '', heavy: false, params: [], inputs, outputs }
}

const defs = new Map<string, ToolTypeDef>([
  ['multi_light_grab', def('multi_light_grab', [], [port('images', 'list'), port('image', 'image'), port('azimuths', 'list')])],
  ['multi_light_fuse', def('multi_light_fuse', [port('images', 'image', true), port('image', 'image')], [port('image', 'image')])],
  ['grayscale', def('grayscale', [port('image', 'image')], [port('image', 'image')])],
])
const nodes = new Map<string, GraphNode>([
  ['g', { id: 'g', type: 'multi_light_grab' }],
  ['f', { id: 'f', type: 'multi_light_fuse' }],
  ['b', { id: 'b', type: 'grayscale' }],
])
const edges: GraphEdge[] = []

describe('checkConnection', () => {
  it('lets a list output feed a multiple image port', () => {
    expect(checkConnection({ source: 'g', sourceHandle: 'images', target: 'f', targetHandle: 'images' }, nodes, edges, defs)).toBeNull()
  })

  it('still rejects a list output on a single image port', () => {
    const rejection = checkConnection({ source: 'g', sourceHandle: 'images', target: 'b', targetHandle: 'image' }, nodes, edges, defs)
    expect(rejection?.code).toBe('incompatible')
    const single = checkConnection({ source: 'g', sourceHandle: 'images', target: 'f', targetHandle: 'image' }, nodes, edges, defs)
    expect(single?.code).toBe('incompatible')
  })

  it('keeps ordinary image to image connections working', () => {
    expect(checkConnection({ source: 'g', sourceHandle: 'image', target: 'b', targetHandle: 'image' }, nodes, edges, defs)).toBeNull()
  })
})
