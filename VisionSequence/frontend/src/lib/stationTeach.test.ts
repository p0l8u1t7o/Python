import { describe, expect, it } from 'vitest'

import {
  buildStationTeachPatches,
  filterStationTeachItems,
  invalidGroupItems,
  saveStationTeachPatches,
  stationTeachKey,
  stationTeachOptions,
  stationTeachRef,
} from './stationTeach'
import type { Flow, StationTeachGroup, StationTeachParamItem, ToolParam } from './types'

const param: ToolParam = { key: 'threshold', label: 'Threshold', kind: 'number', required: false, default: 128, help_text: '', options: [], unit: '', minimum: 0, maximum: 255, step: 1, visible_when: null, shapes: [], accept: '', group: '', teach: true }

const rows: StationTeachParamItem[] = [
  { id: '1:thr:threshold', flow_id: 1, flow_name: 'Front', flow_version: 1, node_id: 'thr', node_label: 'Threshold', tool_type: 'threshold', tool_label: 'Threshold', tool_category: 'preprocess', param, value: 60 },
  { id: '2:blob:min_area', flow_id: 2, flow_name: 'Side', flow_version: 1, node_id: 'blob', node_label: 'Blob', tool_type: 'blob', tool_label: 'Blob analysis', tool_category: 'detect', param: { ...param, key: 'min_area', label: 'Min area' }, value: 20 },
]

const flows: Flow[] = [
  { id: 1, name: 'Front', description: '', graph: { nodes: [{ id: 'thr', type: 'threshold', params: { method: 'fixed', threshold: 60 } }], edges: [] }, is_enabled: true, version: 1, continuous_interval_ms: 0, timeout_s: 0, concurrency: 1, stop_on_ng: false, node_count: 1, created_at: '', updated_at: '', stats: { runs: 0, ok: 0, ng: 0, failed: 0, avg_ms: 0, max_ms: 0, last_ms: 0, last_status: '', last_run_id: '', last_finished_at: 0 }, continuous: false, owner_id: 1, owner_name: 'admin' },
  { id: 2, name: 'Side', description: '', graph: { nodes: [{ id: 'blob', type: 'blob', params: { min_area: 20 } }], edges: [] }, is_enabled: true, version: 1, continuous_interval_ms: 0, timeout_s: 0, concurrency: 1, stop_on_ng: false, node_count: 1, created_at: '', updated_at: '', stats: { runs: 0, ok: 0, ng: 0, failed: 0, avg_ms: 0, max_ms: 0, last_ms: 0, last_status: '', last_run_id: '', last_finished_at: 0 }, continuous: false, owner_id: 1, owner_name: 'admin' },
]

describe('station teach helpers', () => {
  it('tool options follow the selected flow', () => {
    expect(stationTeachOptions(rows, '')).toEqual({ flows: [[1, 'Front'], [2, 'Side']], tools: [['threshold', 'Threshold'], ['blob', 'Blob analysis']] })
    expect(stationTeachOptions(rows, 2)).toEqual({ flows: [[1, 'Front'], [2, 'Side']], tools: [['blob', 'Blob analysis']] })
    expect(stationTeachOptions(rows, 99).tools).toEqual([])
  })

  it('filters by flow, tool and keyword', () => {
    expect(filterStationTeachItems(rows, { flowId: 1, toolType: '', q: '' }).map((row) => row.flow_name)).toEqual(['Front'])
    expect(filterStationTeachItems(rows, { flowId: '', toolType: 'blob', q: '' }).map((row) => row.node_label)).toEqual(['Blob'])
    expect(filterStationTeachItems(rows, { flowId: '', toolType: '', q: 'area' }).map((row) => row.param.key)).toEqual(['min_area'])
  })

  it('detects invalid group shortcuts', () => {
    const group: StationTeachGroup = { id: 'g', name: 'Daily', count: 2, items: [{ valid: true, flow_id: 1, node_id: 'thr', param: 'threshold' }, { valid: false, flow_id: 9, node_id: 'gone', param: 'threshold', reason: 'missing' }] }
    expect(invalidGroupItems(group)).toEqual([{ flow_id: 9, node_id: 'gone', param: 'threshold' }])
  })

  it('builds one graph patch per changed flow only', () => {
    const changes = {
      [stationTeachKey(stationTeachRef(rows[0]))]: 70,
      [stationTeachKey(stationTeachRef(rows[1]))]: 20,
    }
    const patches = buildStationTeachPatches(flows, rows, changes)
    expect(patches).toHaveLength(1)
    expect(patches[0].flow.id).toBe(1)
    expect(patches[0].graph.nodes[0].params?.threshold).toBe(70)
  })

  it('keeps partial save results separated by flow', async () => {
    const patches = buildStationTeachPatches(flows, rows, {
      [stationTeachKey(stationTeachRef(rows[0]))]: 70,
      [stationTeachKey(stationTeachRef(rows[1]))]: 30,
    })
    const results = await saveStationTeachPatches(patches, async (patch) => {
      if (patch.flow.id === 2) throw new Error('denied')
    })
    expect(results.map((result) => [result.flow_id, result.ok])).toEqual([[1, true], [2, false]])
  })
})
