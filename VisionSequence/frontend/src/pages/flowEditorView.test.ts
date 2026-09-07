/** 影像視窗派生邏輯對「瘦身版 run」（節點沒有 outputs／overlays）不能炸：Temp/Issue「流程工具編輯出錯」。 */
import { describe, expect, it } from 'vitest'

import type { GraphEdge, GraphNode, NodeReport, RunReport, ToolTypeDef } from '@/lib/types'
import { inputImage, resolveView, sourceRefOf } from '@/pages/FlowEditorPage'

const edges: GraphEdge[] = [{ id: 'e1', source: 'src', target: 't', source_handle: 'image', target_handle: 'image' }]
const payloads = new Map<string, GraphNode>([
  ['src', { id: 'src', type: 'image_source', label: '', description: '', enabled: true, continue_on_error: false, params: {}, position: { x: 0, y: 0 } }],
  ['t', { id: 't', type: 'blur', label: '', description: '', enabled: true, continue_on_error: false, params: {}, position: { x: 0, y: 0 } }],
])
const defs = new Map<string, ToolTypeDef>()

function runWith(nodes: Record<string, Partial<NodeReport>>, extra: Partial<RunReport> = {}): RunReport {
  return { id: 'r1', flow_id: 1, flow_version: 1, trigger: 'tcp', status: 'ok', started_at: 1, finished_at: 2, duration_ms: 1, error: '', outputs: {}, nodes: nodes as Record<string, NodeReport>, ...extra }
}

describe('editor view with trimmed runs', () => {
  it('inputImage tolerates upstream reports without outputs', () => {
    const legacy = runWith({ src: { status: 'ok', duration_ms: 1, message: '', branch: null }, t: { status: 'ok', duration_ms: 1, message: '', branch: null, overlay_on: 'image' } })
    expect(inputImage(legacy, 't', legacy.nodes.t, edges, defs, payloads)).toBeNull()
    const trimmed = runWith({ src: { status: 'ok', duration_ms: 1, message: '', branch: null, outputs: {}, overlays: [], overlay_on: null, detail: {}, logs: [] }, t: { status: 'ok', duration_ms: 1, message: '', branch: null, outputs: {}, overlays: [], overlay_on: 'image', detail: {}, logs: [] } }, { nodes_trimmed: true })
    expect(inputImage(trimmed, 't', trimmed.nodes.t, edges, defs, payloads)).toBeNull()
  })

  it('resolveView and sourceRefOf return empty results instead of throwing', () => {
    const legacy = runWith({ src: { status: 'ok', duration_ms: 1, message: '', branch: null }, t: { status: 'ok', duration_ms: 1, message: '', branch: null, overlay_on: 'image' } })
    const view = resolveView(legacy, 't', 'output', true, edges, defs, payloads, ['src', 't'])
    expect(view.ref).toBeNull()
    expect(view.overlays).toEqual([])
    expect(sourceRefOf(legacy, payloads)).toBeNull()
  })

  it('still finds the image when the run is complete', () => {
    const full = runWith({
      src: { status: 'ok', duration_ms: 1, message: '', branch: null, outputs: { image: { ref: 'r1:src:image', width: 8, height: 6 } }, overlays: [], overlay_on: null, detail: {}, logs: [] },
      t: { status: 'ok', duration_ms: 1, message: '', branch: null, outputs: {}, overlays: [{ kind: 'point', x: 1, y: 1 } as never], overlay_on: 'image', detail: {}, logs: [] },
    })
    expect(inputImage(full, 't', full.nodes.t, edges, defs, payloads)).toEqual({ ref: 'r1:src:image', width: 8, height: 6 })
    expect(sourceRefOf(full, payloads)).toBe('r1:src:image')
    expect(resolveView(full, 't', 'output', false, edges, defs, payloads, ['src', 't']).overlays).toHaveLength(1)
  })
})
