/**
 * 操作軌跡：最近的頁面切換、錯誤、執行結果與動作，存在記憶體的環形緩衝（不落地、不上傳，只隨 AI 助手的提問一起送出，
 * 讓助手知道「剛剛發生了什麼」）。金鑰／密碼類的字樣送出前遮掉；使用者可在助手視窗關閉分享。
 */
export type ActivityKind = 'nav' | 'error' | 'warning' | 'success' | 'run' | 'action'

export interface ActivityEvent {
  at: number
  kind: ActivityKind
  text: string
  detail?: string
  route: string
  /** 連續重複的事件只留一筆並計數 */
  count: number
}

const MAX_EVENTS = 40
const MAX_TEXT = 200
const MAX_DETAIL = 400
const SHARE_KEY = 'vs.assistant.share'

let events: ActivityEvent[] = []
let route = ''
const listeners = new Set<() => void>()

/** 遮掉像金鑰／權杖／密碼的片段（訊息裡偶爾會夾帶）。 */
export function redact(text: string): string {
  return text
    .replace(/Bearer\s+[A-Za-z0-9._-]+/g, 'Bearer ***')
    .replace(/\b(api[_-]?key|token|password|secret)(["']?\s*[:=]\s*["']?)[^\s"',;]+/gi, '$1$2***')
    .replace(/\b[a-f0-9]{32,}\b/gi, '***')
}

function notify() {
  for (const fn of listeners) fn()
}

export function setActivityRoute(pathname: string): void {
  route = pathname
}

export function logActivity(kind: ActivityKind, text: string, detail = ''): void {
  const clean = redact(String(text ?? '')).slice(0, MAX_TEXT).trim()
  if (!clean) return
  const cleanDetail = redact(String(detail ?? '')).slice(0, MAX_DETAIL).trim()
  const last = events[events.length - 1]
  if (last && last.kind === kind && last.text === clean && last.detail === cleanDetail) {
    last.count += 1
    last.at = Date.now()
  } else {
    events.push({ at: Date.now(), kind, text: clean, detail: cleanDetail, route, count: 1 })
    if (events.length > MAX_EVENTS) events = events.slice(-MAX_EVENTS)
  }
  notify()
}

export function recentActivity(limit = 20): ActivityEvent[] {
  return events.slice(-limit)
}

export function clearActivity(): void {
  events = []
  notify()
}

export function subscribeActivity(fn: () => void): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

/** 是否把頁面現況與操作軌跡隨提問送給助手（預設開；關掉後只送頁面種類）。 */
export function shareEnabled(): boolean {
  try {
    return localStorage.getItem(SHARE_KEY) !== '0'
  } catch {
    return true
  }
}

export function setShareEnabled(value: boolean): void {
  try {
    localStorage.setItem(SHARE_KEY, value ? '1' : '0')
  } catch {
    /* 私密視窗沒有 localStorage 也不影響使用 */
  }
  notify()
}

/** 送給後端的精簡形狀：相對秒數、種類、文字、細節、頁面。 */
export function activityPayload(limit = 20): { ago_s: number; kind: ActivityKind; text: string; detail?: string; route: string; count?: number }[] {
  const now = Date.now()
  return recentActivity(limit).map((e) => ({
    ago_s: Math.max(0, Math.round((now - e.at) / 1000)),
    kind: e.kind,
    text: e.text,
    ...(e.detail ? { detail: e.detail } : {}),
    route: e.route,
    ...(e.count > 1 ? { count: e.count } : {}),
  }))
}
