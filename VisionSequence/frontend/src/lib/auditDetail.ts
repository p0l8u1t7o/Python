/**
 * 操作紀錄的 detail 是後端寫的結構化資料；這裡把「變更」抽成一列一列（欄位／變更前／變更後），
 * 頁面畫成表格而不是 JSON（PM-REVIEW-R2 L-4：以前整包 JSON 連 Python repr 都外漏）。
 *
 * 認得三種形狀：
 * - `params: [{node, param, before, after}]`（流程圖差異，`graphdiff.diff`）
 * - `{field: {before, after}}`（`audit.fields_diff`：流程設定、使用者、連線、運行介面）
 * - `changes: [{field, before, after}]`（`values.field_changes`）
 * 其餘鍵（新增／刪除的步驟數、連線數）留在 `rest` 給頁面用 JSON 顯示。
 */
export interface AuditChangeRow {
  label: string
  before: unknown
  after: unknown
}

export interface AuditDetailView {
  rows: AuditChangeRow[]
  rest: Record<string, unknown> | null
}

function isChange(value: unknown): value is { before: unknown; after: unknown } {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value) && 'before' in (value as object) && 'after' in (value as object)
}

export function auditChanges(detail: Record<string, unknown> | null | undefined): AuditDetailView {
  const rows: AuditChangeRow[] = []
  const rest: Record<string, unknown> = {}
  if (!detail || typeof detail !== 'object') return { rows, rest: null }
  for (const [key, value] of Object.entries(detail)) {
    if (key === 'params' && Array.isArray(value)) {
      for (const entry of value) {
        if (!isChange(entry)) continue
        const e = entry as { node?: unknown; param?: unknown; before: unknown; after: unknown }
        rows.push({ label: [e.node, e.param].filter((x) => typeof x === 'string' && x).join(' · ') || key, before: e.before, after: e.after })
      }
      continue
    }
    if (key === 'changes' && Array.isArray(value)) {
      for (const entry of value) {
        if (!isChange(entry)) continue
        const e = entry as { field?: unknown; before: unknown; after: unknown }
        rows.push({ label: typeof e.field === 'string' ? e.field : key, before: e.before, after: e.after })
      }
      continue
    }
    if (isChange(value)) {
      rows.push({ label: key, before: value.before, after: value.after })
      continue
    }
    if (key === 'count' && rows.length) continue
    rest[key] = value
  }
  return { rows, rest: Object.keys(rest).length ? rest : null }
}

/** 表格裡一格的值：字串原樣、空值用破折號、其餘 JSON（太長截斷）。 */
export function formatAuditValue(value: unknown, limit = 160): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return value.length > limit ? `${value.slice(0, limit - 1)}…` : value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  let text: string
  try {
    text = JSON.stringify(value)
  } catch {
    text = String(value)
  }
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text
}
