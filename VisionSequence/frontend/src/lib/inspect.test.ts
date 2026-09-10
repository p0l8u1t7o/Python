import { describe, expect, it } from 'vitest'
import { inspectGraphHash, inspectionDefaults, inspectionStale, inspectionStatus, inspectionValue, missingInspectionFields } from './inspect'
import type { FlowGraph, InspectKind, InspectReading } from './types'

const graph: FlowGraph = { nodes: [{ id: 'find', type: 'find_circle', params: { nominal: 3, roi: null } }], edges: [] }
const reading: InspectReading = { task_id: 'd', verdict: 'pass', valid: true, detected: true, value: 3, unit: 'px', reason: '', overlays: [], node_id: 'find' }
const kind = { fields: [{ key: 'pictures', kind: 'images', required: true, default: [] }, { key: 'name', kind: 'text', required: false, default: '' }, { key: 'enabled', kind: 'boolean', default: false }, { key: 'n', kind: 'number', required: true, default: 0, minimum: 0, maximum: 10 }] } as InspectKind

describe('inspection state', () => {
  it('ignores object key order but detects parameters and wiring changes', () => {
    expect(inspectGraphHash(graph)).toBe(inspectGraphHash({ edges: [], nodes: [{ params: { roi: null, nominal: 3 }, type: 'find_circle', id: 'find' }] }))
    const changed = structuredClone(graph)
    changed.nodes[0].params = { nominal: 4 }
    expect(inspectionStale(changed, inspectGraphHash(graph))).toBe(true)
    expect(inspectionStale(graph, null)).toBe(false)
    expect(inspectionStale(graph, inspectGraphHash(graph))).toBe(false)
    changed.edges.push({ source: 'find', target: 'judge', source_handle: 'diameter', target_handle: 'value' })
    expect(inspectGraphHash(changed)).not.toBe(inspectGraphHash(graph))
  })
  it('maps every verdict and gives custom and stale states precedence', () => {
    for (const verdict of ['pass', 'fail', 'not_found', 'locate_failed', 'error', 'skipped'] as const) expect(inspectionStatus({ ...reading, verdict })).toBe(verdict)
    expect(inspectionStatus(reading, true)).toBe('stale')
    expect(inspectionStatus(reading, true, true)).toBe('custom')
    expect(inspectionStatus(undefined)).toBe('unrun')
    expect(inspectionStatus({ ...reading, valid: false })).toBe('error')
  })
  it('never renders missing, invalid or undetected readings as zero', () => {
    expect(inspectionValue({ ...reading, value: 0 })).toBe('0')
    for (const value of [NaN, Infinity, null, undefined]) expect(inspectionValue({ ...reading, value })).toBe('—')
    for (const verdict of ['not_found', 'locate_failed', 'error', 'skipped'] as const) expect(inspectionValue({ ...reading, verdict, value: 0 })).toBe('—')
  })
  it('clones defaults and preserves optional blank values, false and zero', () => {
    const first = inspectionDefaults(kind)
    expect(first).toEqual({ pictures: [], name: '', enabled: false, n: 0 })
    ;(first.pictures as string[]).push('picture')
    expect(inspectionDefaults(kind).pictures).toEqual([])
    expect(missingInspectionFields(kind, first)).toEqual([])
    expect(missingInspectionFields(kind, { ...first, pictures: [], n: 11 })).toEqual(['pictures', 'n'])
  })
})
