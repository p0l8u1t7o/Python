/** 影像來源清單的顯示摘要：設定與狀態原本直接印 JSON，改成人看得懂的短句（完整 JSON 留在 title）。 */

const KEY_ORDER = ['client', 'channel', 'mode', 'path', 'url', 'index', 'device', 'host', 'port', 'pattern', 'fps', 'loop', 'sort', 'seed', 'defect_rate']

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
  tone: 'ok' | 'neutral' | 'critical' | 'warning'
  /** i18n key：sources.statusOpen / statusClosed / statusError / statusOffline */
  key: 'statusOpen' | 'statusClosed' | 'statusError' | 'statusOffline' | 'statusOnline'
  frames: number | null
  error: string
  /** 擷取端相機：通道影格率、最近影格距今毫秒、是否走共享記憶體（同一台電腦） */
  fps: number | null
  ageMs: number | null
  shm: boolean
}

/** status JSON（{open, kind, frames, error, connected, fps, age_ms, shm…}）→ 徽章色、文案 key、張數、錯誤字串。 */
export function sourceStatus(status: Record<string, unknown> | null | undefined): SourceStatusView {
  const st = status ?? {}
  const error = typeof st.error === 'string' && st.error ? st.error : typeof st.last_error === 'string' && st.last_error ? st.last_error : ''
  const frames = typeof st.frames === 'number' ? st.frames : typeof st.count === 'number' ? st.count : null
  const fps = typeof st.fps === 'number' && st.fps > 0 ? Math.round(st.fps * 10) / 10 : null
  const ageMs = typeof st.age_ms === 'number' ? Math.round(st.age_ms) : null
  const shm = st.shm === true
  // 擷取端離線優先於上一次的錯誤：使用者要先知道「擷取端沒連上」
  if (st.connected === false) return { tone: 'warning', key: 'statusOffline', frames, error: '', fps: null, ageMs: null, shm: false }
  if (error) return { tone: 'critical', key: 'statusError', frames, error, fps, ageMs, shm }
  if (st.open === true) return { tone: 'ok', key: 'statusOpen', frames, error: '', fps, ageMs, shm }
  if (st.connected === true) return { tone: 'ok', key: 'statusOnline', frames, error: '', fps, ageMs, shm }
  return { tone: 'neutral', key: 'statusClosed', frames, error: '', fps, ageMs, shm }
}
