/** 影像來源清單的顯示摘要：設定與狀態原本直接印 JSON，改成人看得懂的短句（完整 JSON 留在 title）。 */

const KEY_ORDER = ['path', 'url', 'index', 'device', 'host', 'port', 'pattern', 'fps', 'loop', 'sort', 'seed', 'defect_rate']

function fmt(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'boolean') return value ? 'on' : 'off'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (typeof value === 'string') return value.length > 40 ? `…${value.slice(-38)}` : value
  return ''
}

/** 依來源種類挑重點欄位：路徑／裝置／尺寸／模式…，最多 3 項，用「·」串起。 */
export function summarizeSourceConfig(kind: string, config: Record<string, unknown> | null | undefined): string {
  const cfg = config ?? {}
  const parts: string[] = []
  if (typeof cfg.width === 'number' && typeof cfg.height === 'number') parts.push(`${cfg.width}×${cfg.height}`)
  for (const key of KEY_ORDER) {
    if (parts.length >= 3) break
    const v = fmt(cfg[key])
    if (v) parts.push(key === 'path' || key === 'url' ? v : `${key}: ${v}`)
  }
  if (!parts.length) {
    for (const [k, v] of Object.entries(cfg)) {
      if (parts.length >= 3) break
      const s = fmt(v)
      if (s) parts.push(`${k}: ${s}`)
    }
  }
  return parts.length ? parts.join(' · ') : kind
}

export interface SourceStatusView {
  tone: 'ok' | 'neutral' | 'critical'
  /** i18n key：sources.statusOpen / statusClosed / statusError */
  key: 'statusOpen' | 'statusClosed' | 'statusError'
  frames: number | null
  error: string
}

/** status JSON（{open, kind, frames, error…}）→ 徽章色、文案 key、張數、錯誤字串。 */
export function sourceStatus(status: Record<string, unknown> | null | undefined): SourceStatusView {
  const st = status ?? {}
  const error = typeof st.error === 'string' && st.error ? st.error : typeof st.last_error === 'string' && st.last_error ? st.last_error : ''
  const frames = typeof st.frames === 'number' ? st.frames : typeof st.count === 'number' ? st.count : null
  if (error) return { tone: 'critical', key: 'statusError', frames, error }
  if (st.open === true) return { tone: 'ok', key: 'statusOpen', frames, error: '' }
  return { tone: 'neutral', key: 'statusClosed', frames, error: '' }
}
