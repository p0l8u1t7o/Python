/**
 * 跨頁共享的流程「草稿」與試跑工作階段（流程編輯器 ⇄ 工具頁）。
 *
 * - 沒有引入 zustand：用模組層 Map + useSyncExternalStore 的極簡 store。
 * - draft：未儲存的圖與名稱／描述；編輯器離開頁面時寫入、載入時若 baseVersion 相符就用它取代伺服器版本。
 *   工具頁直接讀寫 draft（改參數 = 改 draft），回到編輯器就看到相同的變更。
 * - scratch：頂列「上傳暫存影像」的結果；有它時所有試跑都帶 reuse_image_ref。
 * - previewRun：最近一次試跑的結果（工具頁跑的 until_node 試跑也放這裡，讓編輯器影像視窗跟著更新）。
 */
import { useSyncExternalStore } from 'react'

import type { Flow, FlowGraph, RunReport, ScratchImage } from './types'

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
