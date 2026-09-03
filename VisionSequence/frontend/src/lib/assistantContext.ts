/**
 * 全域 AI 助手的頁面脈絡：每個頁面在掛載時登記「我是誰、能做什麼」（流程編輯器：目前畫布與套用；批次頁：目前執行與建議套用；
 * 工具頁：節點型別），助手視窗依此分流（問答／修改流程／資料諮詢／依資料調整）並顯示對應的快速提示。
 * 與 flowDraft.ts 同樣是模組層 store＋useSyncExternalStore，頁面切換即自動清除。
 */
import { useEffect, useSyncExternalStore } from 'react'

import type { Suggestion } from '@/lib/batch'
import type { FlowGraph } from '@/lib/types'

export type AssistantKind = 'flow_editor' | 'tool' | 'batch' | 'golden' | 'agent' | 'dl' | 'sources' | 'assets' | 'dashboard' | 'page'

export interface AssistantContext {
  kind: AssistantKind
  route?: string
  flowId?: number | null
  flowName?: string
  nodeId?: string
  nodeType?: string
  batchRunId?: number | null
  imageRef?: string | null
  execLocked?: boolean
  /** 流程編輯器／工具頁：目前畫布（未儲存） */
  getGraph?: () => FlowGraph | null
  /** 流程編輯器：把助手修改後的圖寫回畫布（可復原） */
  applyGraph?: (graph: FlowGraph, why: string) => void
  /** 批次頁：把參數建議套到調參面板 */
  applySuggestions?: (suggestions: Suggestion[]) => void
  /** 批次頁：AI 調整產生了新的一次執行 */
  onNewRun?: (runId: number) => void
}

let current: AssistantContext | null = null
const listeners = new Set<() => void>()

export function setAssistantContext(ctx: AssistantContext | null): void {
  current = ctx
  for (const fn of listeners) fn()
}

export function getAssistantContext(): AssistantContext | null {
  return current
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

export function useAssistantContext(): AssistantContext | null {
  return useSyncExternalStore(subscribe, getAssistantContext, getAssistantContext)
}

/** 頁面登記脈絡；卸載或 deps 變動時更新／清除。 */
export function useRegisterAssistantContext(ctx: AssistantContext | null, deps: unknown[]): void {
  useEffect(() => {
    setAssistantContext(ctx)
    return () => setAssistantContext(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}

/** 沒有頁面登記時，依路徑推一個粗略的脈絡（只影響提示與問答的措辭）。 */
export function contextFromPath(pathname: string): AssistantContext {
  const kind: AssistantKind = pathname === '/' ? 'dashboard'
    : pathname.startsWith('/batch') ? 'batch'
    : pathname.startsWith('/agent') ? 'agent'
    : pathname.startsWith('/dl') ? 'dl'
    : pathname.startsWith('/sources') ? 'sources'
    : pathname.startsWith('/assets') ? 'assets'
    : /^\/flows\/\d+\/golden/.test(pathname) ? 'golden'
    : 'page'
  return { kind, route: pathname }
}
