/**
 * 主動提示：操作軌跡出現失敗（鎖定、權限、接收端沒開、沒選來源、埠被佔、執行失敗、逾時、伺服器錯誤）時，
 * 依規則配一句提示與一個可直接送給助手的問題。純規則、不打後端；同一種提示 5 分鐘內只出現一次，關掉的這個 session 不再出現。
 */
import type { ActivityEvent } from '@/lib/activity'

export type HintKey = 'locked' | 'permission' | 'receiver' | 'noSource' | 'portInUse' | 'runFailed' | 'timeout' | 'serverError'

export interface Hint {
  key: HintKey
  /** 助手「詢問」時送出的問題（含原始錯誤，讓後端的現況與檢索有東西可用） */
  question: string
  /** 原始錯誤的一句話（顯示在提示卡） */
  detail: string
}

const COOLDOWN_MS = 5 * 60 * 1000
const DISMISS_KEY = 'vs.assistant.hints.dismissed'

const RULES: { key: HintKey; test: (text: string) => boolean }[] = [
  { key: 'locked', test: (s) => /-> 423\b|engine_locked|\block(ed)? by\b/i.test(s) },
  { key: 'permission', test: (s) => /-> 403\b|teach_only|forbidden|not permitted|permission/i.test(s) },
  { key: 'receiver', test: (s) => /nothing is listening|start the receiver|connection refused|unreachable/i.test(s) },
  { key: 'noSource', test: (s) => /no_source|image source is not set|pick an image source|source_missing/i.test(s) },
  { key: 'portInUse', test: (s) => /address already in use|port .* in use|only one usage of each socket|errno 10048|errno 98/i.test(s) },
  { key: 'timeout', test: (s) => /-> 504\b|run_timeout|timed out|timeout/i.test(s) },
  { key: 'serverError', test: (s) => /-> 5\d\d\b/.test(s) },
  { key: 'runFailed', test: (s) => /^(run|preview) flow \d+: failed/i.test(s) },
]

/** 事件配到的提示；配不到回 null。 */
export function hintFor(event: ActivityEvent): Hint | null {
  if (!(event.kind === 'error' || event.kind === 'warning' || event.kind === 'run')) return null
  const text = `${event.text} ${event.detail ?? ''}`.trim()
  const rule = RULES.find((r) => r.test(text))
  if (!rule) return null
  const detail = (event.detail || event.text).slice(0, 200)
  return { key: rule.key, question: `Why did this fail and what should I do: ${text.slice(0, 240)}`, detail }
}

const lastShown = new Map<HintKey, number>()

function dismissed(): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(DISMISS_KEY) ?? '[]') as string[])
  } catch {
    return new Set()
  }
}

/** 這個提示現在該不該出現（冷卻與關閉紀錄）；會記下出現時間。 */
export function shouldShow(hint: Hint, now = Date.now()): boolean {
  if (dismissed().has(hint.key)) return false
  const last = lastShown.get(hint.key) ?? 0
  if (now - last < COOLDOWN_MS) return false
  lastShown.set(hint.key, now)
  return true
}

export function dismissHint(key: HintKey): void {
  try {
    sessionStorage.setItem(DISMISS_KEY, JSON.stringify([...dismissed(), key]))
  } catch {
    /* 沒有 sessionStorage 就只靠冷卻 */
  }
}

/** 測試用：清掉冷卻與關閉紀錄。 */
export function resetHints(): void {
  lastShown.clear()
  try {
    sessionStorage.removeItem(DISMISS_KEY)
  } catch {
    /* 忽略 */
  }
}
