/**
 * 跨頁共享的流程「草稿」與試跑工作階段（流程編輯器 ⇄ 工具頁）。
 *
 * - 沒有引入 zustand：用模組層 Map + useSyncExternalStore 的極簡 store。
 * - draft：未儲存的圖與名稱／描述；編輯器離開頁面時寫入、載入時若 baseVersion 相符就用它取代伺服器版本。
 *   工具頁直接讀寫 draft（改參數 = 改 draft），回到編輯器就看到相同的變更。
 * - scratch：頂列「上傳暫存影像」的結果；有它時所有試跑都帶 reuse_image_ref。
 * - previewRun：最近一次試跑的結果（工具頁跑的 until_node 試跑也放這裡，讓編輯器影像視窗跟著更新）。
 * - 持久化：髒草稿另存一份到 localStorage（`persistDraft`；使用者層，登出清掉），重新整理或分頁當掉後回來，
 *   編輯器依 `baseVersion` 對得上就提示「還原／放棄」（PM-REVIEW #3）；儲存成功或放棄就清掉。
 */
import { useSyncExternalStore } from 'react'

import type { Flow, FlowGraph, NodeInterface, RunReport, ScratchImage } from './types'

/** 隨流程一起儲存的運行設定（以前每改一下就送伺服器，與描述的生效時機不一致）。 */
export interface FlowSettings {
  continuous_interval_ms: number
  timeout_s: number
  concurrency: number
  stop_on_ng: boolean
}

export function settingsOf(flow: Pick<Flow, 'continuous_interval_ms' | 'timeout_s' | 'concurrency' | 'stop_on_ng'>): FlowSettings {
  return { continuous_interval_ms: flow.continuous_interval_ms ?? 0, timeout_s: flow.timeout_s ?? 0, concurrency: flow.concurrency ?? 1, stop_on_ng: flow.stop_on_ng === true }
}

export interface FlowDraft {
  /** 依據的伺服器版本；不符（別人存過）就丟掉草稿 */
  baseVersion: number
  graph: FlowGraph
  name: string
  description: string
  /** 運行設定；舊草稿沒有這個欄位時儲存不帶（維持伺服器的值） */
  settings?: FlowSettings
  /** 複合工具的內部圖（Flow.kind=tool）：對外介面也在草稿裡，儲存時一起送 */
  toolInterface?: NodeInterface
  dirty: boolean
}

export interface FlowSession {
  draft: FlowDraft | null
  scratch: ScratchImage | null
  previewRun: RunReport | null
  /** 「用上次影像重跑」開關 */
  reuseImage: boolean
}

const EMPTY: FlowSession = { draft: null, scratch: null, previewRun: null, reuseImage: false }

const sessions = new Map<number, FlowSession>()
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

export function getSession(flowId: number): FlowSession {
  return sessions.get(flowId) ?? EMPTY
}

export function updateSession(flowId: number, patch: Partial<FlowSession>) {
  sessions.set(flowId, { ...getSession(flowId), ...patch })
  emit()
}

export function setDraft(flowId: number, draft: FlowDraft | null) {
  updateSession(flowId, { draft })
}

/** 只改草稿裡的一個步驟（工具頁用）。沒有草稿時不動作。 */
export function patchDraftNode(flowId: number, nodeId: string, patch: Partial<FlowGraph['nodes'][number]>) {
  const session = getSession(flowId)
  if (!session.draft) return
  const nodes = session.draft.graph.nodes.map((n) => (n.id === nodeId ? { ...n, ...patch } : n))
  updateSession(flowId, { draft: { ...session.draft, graph: { ...session.draft.graph, nodes }, dirty: true } })
}

export function clearSession(flowId: number) {
  sessions.delete(flowId)
  emit()
}

// ---- 草稿持久化（重新整理保護） ----
export const PERSIST_KEY = 'vs.flowDrafts.v1'
/** 單一草稿的 JSON 上限；超過（幾十 MB 的固定影像描述子不會，但腳本與大圖仍可能）就不存，不讓 localStorage 配額炸掉整頁 */
export const PERSIST_MAX_CHARS = 2_000_000
/** 最多保留幾條流程的草稿（依 savedAt 淘汰最舊的） */
export const PERSIST_MAX_ENTRIES = 8

export interface PersistedDraft {
  baseVersion: number
  graph: FlowGraph
  name: string
  description: string
  settings?: FlowSettings
  toolInterface?: NodeInterface
  /** ISO 時間，畫面上顯示「來自 …」 */
  savedAt: string
  /** 草稿依據的伺服器 updated_at；圖沒變的儲存（改描述、設定）不會 +1 version，靠這個看出「別人存過」 */
  baseUpdatedAt?: string
}

function readPersisted(): Record<string, PersistedDraft> {
  try {
    const raw = localStorage.getItem(PERSIST_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, PersistedDraft> : {}
  } catch {
    return {}
  }
}

function writePersisted(all: Record<string, PersistedDraft>): boolean {
  try {
    if (Object.keys(all).length === 0) localStorage.removeItem(PERSIST_KEY)
    else localStorage.setItem(PERSIST_KEY, JSON.stringify(all))
    return true
  } catch {
    return false  // 私密模式或配額不足：沒有保護，但不影響編輯
  }
}

/** 髒草稿寫進瀏覽器；沒改過或太大就不寫（回 false）。 */
export function persistDraft(flowId: number, draft: FlowDraft, now: Date = new Date(), baseUpdatedAt?: string): boolean {
  if (!draft.dirty) return false
  const entry: PersistedDraft = {
    baseVersion: draft.baseVersion, graph: draft.graph, name: draft.name, description: draft.description,
    settings: draft.settings, toolInterface: draft.toolInterface, savedAt: now.toISOString(),
    ...(baseUpdatedAt ? { baseUpdatedAt } : {}),
  }
  let encoded: string
  try {
    encoded = JSON.stringify(entry)
  } catch {
    return false
  }
  if (encoded.length > PERSIST_MAX_CHARS) return false
  const all = readPersisted()
  all[String(flowId)] = entry
  const ids = Object.keys(all).sort((a, b) => (all[a].savedAt < all[b].savedAt ? -1 : 1))
  while (ids.length > PERSIST_MAX_ENTRIES) delete all[ids.shift() as string]
  return writePersisted(all)
}

/** 瀏覽器裡的草稿是否還對得上伺服器版本（version 相同、且沒有人在中間存過）。 */
export function persistedDraftMatches(entry: PersistedDraft, flow: { version: number; updated_at?: string }): boolean {
  if (entry.baseVersion !== flow.version) return false
  return !entry.baseUpdatedAt || !flow.updated_at || entry.baseUpdatedAt === flow.updated_at
}

export function readPersistedDraft(flowId: number): PersistedDraft | null {
  const entry = readPersisted()[String(flowId)]
  if (!entry || typeof entry !== 'object' || !entry.graph || typeof entry.baseVersion !== 'number') return null
  return entry
}

export function clearPersistedDraft(flowId: number): void {
  const all = readPersisted()
  if (!(String(flowId) in all)) return
  delete all[String(flowId)]
  writePersisted(all)
}

export function useFlowSession(flowId: number): FlowSession {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => getSession(flowId),
    () => getSession(flowId),
  )
}
