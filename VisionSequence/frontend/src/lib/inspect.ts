/** 檢測任務頁的純函式；規格與接線仍由核心定義表決定。 */
import type { FlowGraph, InspectField, InspectKind, InspectReading, ToolParam } from './types'

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
export function inspectionValue(reading?: InspectReading): string {
  if (!reading?.valid || !['pass', 'fail'].includes(reading.verdict) || reading.value === null || reading.value === undefined) return '—'
  if (typeof reading.value === 'number') return Number.isFinite(reading.value) ? String(reading.value) : '—'
  return typeof reading.value === 'string' ? reading.value : '—'
}
export function missingInspectionFields(kind: InspectKind, values: Record<string, unknown>): string[] {
  return kind.fields.filter((f) => {
    const value = values[f.key]
    if (f.required && (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length))) return true
    if (value !== null && value !== undefined && value !== '' && ['number', 'range'].includes(f.kind)) {
      return typeof value !== 'number' || !Number.isFinite(value) || (f.minimum != null && value < f.minimum) || (f.maximum != null && value > f.maximum)
    }
    return false
  }).map((f) => f.key)
}
