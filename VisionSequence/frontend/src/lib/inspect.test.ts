import { describe, expect, it } from 'vitest'
import { INSPECT_REASON_CODES, forgetInspectionRun, inspectGraphHash, inspectionAdvancedPath, inspectionDefaults, inspectionEditableKind, inspectionOverall, inspectionReasonKey, inspectionRemovalGraph, inspectionRunFor, inspectionStale, inspectionStatus, inspectionValue, missingInspectionFields, rememberInspectionRun } from './inspect'
import type { FlowGraph, InspectKind, InspectReading, InspectTask, RunReport } from './types'
import { INSPECT_GRAPH, INSPECT_KINDS, installApiMock } from '@/test/apiMock'
import { writeInspection } from './queries'

installApiMock()

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

describe('inspection editing safety', () => {
  const task: InspectTask = { task_id: 'd', kind: 'measure_diameter', version: 1, required: true, nodes: { find: 'd_find', tol: 'd_tol' }, fields: {}, custom: false, reasons: [] }
  it('keeps moved steps and unmanaged parameters editable after a read response', () => {
    const advanced = structuredClone(INSPECT_GRAPH)
    advanced.nodes[1].position = { x: 800, y: 50 }
    advanced.nodes[1].params = { ...advanced.nodes[1].params, smoothing: 7 }
    const before = structuredClone(advanced)
    expect(inspectionEditableKind(task, INSPECT_KINDS)).toBe(INSPECT_KINDS[0])
    expect(inspectionAdvancedPath(6, advanced, task)).toBe('/flows/6?focus=d_find')
    expect(advanced).toEqual(before)
  })
  it('hides fields and focuses the target of a missing managed edge', () => {
    const broken = structuredClone(INSPECT_GRAPH)
    broken.edges = broken.edges.filter((edge) => edge.target !== 'd_tol')
    const custom = { ...task, custom: true, reasons: [{ code: 'managed_edge_missing', role: 'tol', node_id: 'd_tol', detail: 'Missing d_find.diameter -> d_tol.value' }] }
    expect(inspectionEditableKind(custom, INSPECT_KINDS)).toBeUndefined()
    expect(inspectionAdvancedPath(6, broken, custom)).toBe('/flows/6?focus=d_tol')
    expect(inspectionReasonKey(custom.reasons[0].code)).toBe('inspect.reasons.managed_edge_missing')
  })
  it('focuses an inserted blur and does not expose a custom task form', () => {
    const advanced = structuredClone(INSPECT_GRAPH)
    advanced.nodes.push({ id: 'extra blur', type: 'blur', params: {} })
    const custom = { ...task, custom: true, reasons: [{ code: 'unexpected_node', role: 'extra', node_id: 'extra blur', detail: 'The task contains an extra step' }] }
    expect(inspectionEditableKind(custom, INSPECT_KINDS)).toBeUndefined()
    expect(inspectionAdvancedPath(6, advanced, custom)).toBe('/flows/6?focus=extra%20blur')
  })
  it('sends a tolerance edit through the translator without rebuilding advanced nodes and edges', async () => {
    const advanced = structuredClone(INSPECT_GRAPH)
    advanced.nodes[1].params = { ...advanced.nodes[1].params, smoothing: 7 }
    advanced.nodes.push({ id: 'external', type: 'formula', params: { expression: 'a' } })
    advanced.edges.push({ source: 'd_find', source_handle: 'diameter', target: 'external', target_handle: 'a' })
    const before = structuredClone(advanced)
    const result = await writeInspection('update', advanced, { task_id: 'd', fields: { upper_tol: 5 } })
    const expected = structuredClone(advanced)
    expected.nodes[2].params!.upper_tol = 5
    expect(result.graph).toEqual(expected)
    expect(advanced).toEqual(before)
  })
  it('keeps the graph when removal is blocked and accepts only a successful removal', () => {
    const removed = { nodes: [INSPECT_GRAPH.nodes[0]], edges: [] }
    const dependency = { target: 'external', title: 'External formula', target_handle: 'a' }
    expect(inspectionRemovalGraph(INSPECT_GRAPH, { graph: removed, removed: false, dependencies: [dependency] })).toBe(INSPECT_GRAPH)
    expect(inspectionRemovalGraph(INSPECT_GRAPH, { graph: removed, removed: true, dependencies: [dependency] })).toBe(INSPECT_GRAPH)
    expect(inspectionRemovalGraph(INSPECT_GRAPH, { graph: removed, removed: true, dependencies: [] })).toEqual({ nodes: [INSPECT_GRAPH.nodes[0]], edges: [] })
  })
  it('preserves stale evidence across page returns and updates it only after another run', () => {
    const report: RunReport = { id: 'run-1', flow_id: 7, flow_version: 1, trigger: 'preview', started_at: 1, finished_at: 2, duration_ms: 1, error: '', status: 'ok', outputs: { judge: 'PASS' }, nodes: {} }
    rememberInspectionRun(7, INSPECT_GRAPH, report, [reading])
    const advanced = structuredClone(INSPECT_GRAPH)
    advanced.nodes[2].params!.upper_tol = 5
    const previous = inspectionRunFor(7, report)!
    expect(inspectionStatus(previous.readings[0], inspectionStale(advanced, previous.hash))).toBe('stale')
    expect(inspectionOverall(report, true)).toBe('stale')
    const rerun = { ...report, id: 'run-2', status: 'ng', outputs: { judge: 'NG' } } as RunReport
    const next = rememberInspectionRun(7, advanced, rerun, [{ ...reading, verdict: 'fail' }])
    expect(inspectionStatus(next.readings[0], inspectionStale(advanced, next.hash))).toBe('fail')
    expect(inspectionOverall(rerun, false)).toBe('NG')
    expect(inspectionRunFor(7, report)).toBeUndefined()
    forgetInspectionRun(7)
    expect(inspectionRunFor(7, rerun)).toBeUndefined()
  })
  it('handles unknown versions and missing nodes without invalid focus targets', () => {
    expect(inspectionEditableKind({ ...task, version: 99 }, INSPECT_KINDS)).toBeUndefined()
    const missing = { ...task, custom: true, reasons: [{ code: 'role_missing', role: 'tol', node_id: 'missing', detail: 'Missing step' }] }
    expect(inspectionAdvancedPath(6, INSPECT_GRAPH, missing)).toBe('/flows/6?focus=d_find')
    for (const code of INSPECT_REASON_CODES) expect(inspectionReasonKey(code)).toBe(`inspect.reasons.${code}`)
    expect(inspectionReasonKey('future_reason')).toBe('inspect.customHint')
  })
})
