import { describe, expect, it } from 'vitest'
import { checkConnection, graphProblems, nodeProblems } from './graphValidation'
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
  ['measure', def('measure', [port('image', 'image')], [port('value', 'number'), port('image', 'image'), { ...port('_image', 'image'), implicit: true }, port('done', 'flow')])],
])
const nodes = new Map<string, GraphNode>([
  ['g', { id: 'g', type: 'multi_light_grab' }],
  ['f', { id: 'f', type: 'multi_light_fuse' }],
  ['b', { id: 'b', type: 'grayscale' }],
  ['m', { id: 'm', type: 'measure' }],
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

describe('published outputs validation', () => {
  function publishProblems(publish: Record<string, string>) {
    return nodeProblems({ id: 'm', type: 'measure', params: { _publish: publish } }, defs.get('measure'), [])
      .filter((problem) => problem.key.startsWith('publish:'))
  }

  it('accepts data output ports with valid names', () => {
    expect(publishProblems({ value: 'diameter_1', image: 'result_image' })).toEqual([])
    expect(graphProblems([{ id: 'm', type: 'measure', params: { _publish: { value: 'diameter_1' } } }], [], defs).has('m')).toBe(false)
  })

  it('rejects flow, implicit and missing ports', () => {
    expect(publishProblems({ done: 'route' })[0]).toMatchObject({ code: 'publishBadPort', values: { port: 'done' } })
    expect(publishProblems({ _image: 'passthrough' })[0]).toMatchObject({ code: 'publishBadPort', values: { port: '_image' } })
    expect(publishProblems({ missing: 'value' })[0]).toMatchObject({ code: 'publishBadPort', values: { port: 'missing' } })
  })

  it('rejects invalid names', () => {
    expect(publishProblems({ value: '1bad' })[0]).toMatchObject({ code: 'publishBadName', values: { port: 'value', name: '1bad' } })
    expect(publishProblems({ value: 'bad-name' })[0]).toMatchObject({ code: 'publishBadName' })
  })
})
