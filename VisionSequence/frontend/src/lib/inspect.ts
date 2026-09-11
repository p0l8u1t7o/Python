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
  // 裝置層只保留讀值摘要；影像參照、節點輸出及疊圖均不落地。
  try {
    localStorage.setItem(`vs.inspectionRun.v1:${flowId}`, JSON.stringify({
      hash: snapshot.hash, status: report.status, judge: report.outputs.judge,
      readings: readings.map(({ overlays: _overlays, ...row }) => ({ ...row, overlays: [] })),
    }))
  } catch { /* 儲存空間不足時仍保留本次記憶體讀值。 */ }
  return snapshot
}
export function inspectionRunFor(flowId: number, report: RunReport | null): InspectionRun | undefined {
  const saved = runs.get(flowId)
  if (report) return saved?.report === report ? saved : undefined
  try {
    const raw = JSON.parse(localStorage.getItem(`vs.inspectionRun.v1:${flowId}`) ?? 'null')
    if (!raw || typeof raw.hash !== 'string' || !['ok', 'ng', 'failed'].includes(raw.status) || !Array.isArray(raw.readings)) return undefined
    if (!raw.readings.every((r: InspectReading) => r && typeof r.task_id === 'string' && typeof r.valid === 'boolean' && ['pass', 'fail', 'not_found', 'locate_failed', 'error', 'skipped'].includes(r.verdict))) return undefined
    return { hash: raw.hash, readings: raw.readings.map((r: InspectReading) => ({ ...r, overlays: [] })), report: {
      id: '', flow_id: flowId, flow_version: 0, trigger: 'preview', status: raw.status, started_at: 0,
      finished_at: null, duration_ms: 0, error: '', outputs: { judge: raw.judge }, nodes: {},
    } }
  } catch { return undefined }
}
export function forgetInspectionRun(flowId: number) {
  runs.delete(flowId)
  try { localStorage.removeItem(`vs.inspectionRun.v1:${flowId}`) } catch { /* 私密模式。 */ }
}

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
  if (typeof reading.value === 'number') {
    const digits = reading.unit === 'mm' ? 3 : ['px', 'deg', '°'].includes(reading.unit) ? 2 : 0
    return Number.isFinite(reading.value) ? String(Number(reading.value.toFixed(digits))) : '—'
  }
  return typeof reading.value === 'string' ? reading.value : '—'
}
export function inspectionHasImage(graph: FlowGraph, reuseRef?: string | null): boolean {
  const sources = graph.nodes.filter((node) => node.enabled !== false && node.params?.role !== 'reference')
  return sources.some((node) => {
    if (node.type === 'fixed_image') return Array.isArray(node.params?.images) && node.params.images.length > 0
    if (node.type === 'image_source') return Boolean(reuseRef || node.params?.source_id)
    return ['stereo_grab', 'multi_light_grab'].includes(node.type)
  })
}
/** 舊任務頁曾寫入 source；讀入草稿時改用固定影像正式的 acquire 選項。 */
export function normalizeInspectionSources(graph: FlowGraph): FlowGraph {
  if (!graph.nodes.some((node) => node.type === 'fixed_image' && node.params?.role === 'source')) return graph
  return { ...graph, nodes: graph.nodes.map((node) => node.type === 'fixed_image' && node.params?.role === 'source'
    ? { ...node, params: { ...node.params, role: 'acquire' } } : node) }
}
/** 固定影像由節點選圖；明確上傳的暫存影像仍可覆寫本次輸入。 */
export function inspectionReuseRef(graph: FlowGraph, scratchRef: string | null | undefined, reuse: boolean, lastRef?: string | null): string | null {
  if (scratchRef) return scratchRef
  const fixed = graph.nodes.some((node) => node.enabled !== false && node.type === 'fixed_image' && node.params?.role !== 'reference')
  return reuse && !fixed ? lastRef ?? null : null
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
