/** 檢測任務頁的純函式；規格與接線仍由核心定義表決定。 */
import type { FlowGraph, InspectDependency, InspectField, InspectKind, InspectReading, InspectTask, RunReport, ToolParam } from './types'

export const INSPECT_REASON_CODES = ['role_missing', 'unexpected_node', 'tool_changed', 'managed_edge_changed', 'managed_edge_missing', 'public_input_changed', 'schema_version_unknown'] as const
export function inspectionReasonKey(code: string): string {
  return INSPECT_REASON_CODES.some((known) => known === code) ? `inspect.reasons.${code}` : 'inspect.customHint'
}
export function inspectionEditableKind(task: InspectTask | undefined, kinds: InspectKind[]): InspectKind | undefined {
  if (!task || task.custom) return undefined
  return kinds.find((kind) => kind.kind === task.kind && kind.version === task.version)
}
export function inspectionAdvancedPath(flowId: number, graph: FlowGraph, task?: InspectTask): string {
  const problem = task?.reasons.map((reason) => reason.node_id || task.nodes[reason.role]).find((id) => graph.nodes.some((node) => node.id === id))
  const nodeId = problem ?? Object.values(task?.nodes ?? {}).find((id) => graph.nodes.some((node) => node.id === id))
  return `/flows/${flowId}${nodeId ? `?focus=${encodeURIComponent(nodeId)}` : ''}`
}
export function inspectionRemovalGraph(current: FlowGraph, result: { graph: FlowGraph; removed: boolean; dependencies: InspectDependency[] }): FlowGraph {
  return result.removed && !result.dependencies.length ? result.graph : current
}
export function inspectionOverall(run: RunReport | null, stale: boolean): string {
  return stale ? 'stale' : run ? String(run.outputs.judge ?? run.status.toUpperCase()) : '—'
}

interface InspectionRun { report: RunReport; readings: InspectReading[]; hash: string }
const runs = new Map<number, InspectionRun>()
/** 保留任務頁的試跑圖簽章；其他入口的新報告不可沿用舊的任務讀值。 */
export function rememberInspectionRun(flowId: number, graph: FlowGraph, report: RunReport, readings: InspectReading[]) {
  const snapshot = { report, readings, hash: inspectGraphHash(graph) }
  runs.set(flowId, snapshot)
  return snapshot
}
export function inspectionRunFor(flowId: number, report: RunReport | null): InspectionRun | undefined {
  const saved = runs.get(flowId)
  return saved?.report === report ? saved : undefined
}
export function forgetInspectionRun(flowId: number) { runs.delete(flowId) }

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.entries(value).filter(([, v]) => v !== undefined).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(',')}}`
  return JSON.stringify(value) ?? 'null'
}

/** 保留完整正規化內容，避免短雜湊碰撞把舊結果當成有效。 */
export function inspectGraphHash(graph: FlowGraph): string { return canonical(graph) }
export function inspectionStale(graph: FlowGraph, lastHash: string | null): boolean {
  return lastHash !== null && inspectGraphHash(graph) !== lastHash
}
export type InspectStatus = InspectReading['verdict'] | 'stale' | 'custom' | 'unrun'
export function inspectionStatus(reading: InspectReading | undefined, stale = false, custom = false): InspectStatus {
  if (custom) return 'custom'
  if (stale) return 'stale'
  if (!reading) return 'unrun'
  if (!reading.valid && reading.verdict === 'pass') return 'error'
  return reading.verdict
}
export const INSPECT_DOTS: Record<InspectStatus, string> = {
  pass: 'bg-ok', fail: 'bg-critical', not_found: 'bg-warning', locate_failed: 'bg-warning',
  error: 'bg-critical', skipped: 'bg-line-strong', stale: 'bg-line-strong', custom: 'bg-warning', unrun: 'bg-line',
}
export function inspectionDefaults(kind: InspectKind): Record<string, unknown> {
  return Object.fromEntries(kind.fields.map((f) => [f.key, structuredClone(f.default ?? null)]))
}
export function inspectionParam(field: InspectField): ToolParam {
  return { ...field, visible_when: null, group: '', shapes: field.shapes ?? [], options: field.options ?? [] }
}
export function inspectionFieldVisible(field: InspectField, values: Record<string, unknown>): boolean {
  return !field.visible_when || Object.entries(field.visible_when).every(([key, allowed]) => (Array.isArray(allowed) ? allowed : [allowed]).includes(values[key]))
}
export function inspectionValue(reading?: InspectReading): string {
  if (!reading?.valid || !['pass', 'fail'].includes(reading.verdict) || reading.value === null || reading.value === undefined) return '—'
  if (typeof reading.value === 'number') return Number.isFinite(reading.value) ? String(reading.value) : '—'
  return typeof reading.value === 'string' ? reading.value : '—'
}
export function missingInspectionFields(kind: InspectKind, values: Record<string, unknown>): string[] {
  return kind.fields.filter((f) => {
    if (!inspectionFieldVisible(f, values)) return false
    const value = values[f.key]
    if (f.required && (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length))) return true
    if (value !== null && value !== undefined && value !== '' && ['number', 'range'].includes(f.kind)) {
      return typeof value !== 'number' || !Number.isFinite(value) || (f.minimum != null && value < f.minimum) || (f.maximum != null && value > f.maximum)
    }
    return false
  }).map((f) => f.key)
}
