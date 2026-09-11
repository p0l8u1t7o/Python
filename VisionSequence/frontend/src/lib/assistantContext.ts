/**
 * 全域 AI 助手的頁面脈絡：每個頁面在掛載時登記「我是誰、能做什麼」（流程編輯器：目前畫布與套用；批次頁：目前執行與建議套用；
 * 工具頁：節點型別），助手視窗依此分流（問答／修改流程／資料諮詢／依資料調整）並顯示對應的快速提示。
 * `describe()` 回頁面自己的現況快照（選了哪個節點、上次執行怎麼了、未儲存…），讓助手回答時對得上畫面。
 * 與 flowDraft.ts 同樣是模組層 store＋useSyncExternalStore，頁面切換即自動清除。
 */
import { useEffect, useSyncExternalStore } from 'react'

import type { Suggestion } from '@/lib/batch'
import type { AssistantWorkState, FlowGraph, Region, RoiShape, RunReport } from '@/lib/types'

const progressListeners = new Set<(flowId: number, state: AssistantWorkState, decision?: string) => void>()
/** 只有目前綁定該流程的對話接收成功動作的摘要，不攜帶圖或影像。 */
export function publishAssistantProgress(flowId: number, state: AssistantWorkState, decision?: string) {
  progressListeners.forEach((fn) => fn(flowId, state, decision))
}
export function subscribeAssistantProgress(fn: (flowId: number, state: AssistantWorkState, decision?: string) => void) {
  progressListeners.add(fn)
  return () => { progressListeners.delete(fn) }
}

export type AssistantKind = 'inspect' | 'flow_editor' | 'tool' | 'batch' | 'golden' | 'agent' | 'dl' | 'sources' | 'assets' | 'dashboard' | 'page'

/** 頁面現況快照：純資料、可 JSON 化；欄位由各頁自訂，後端只當文字脈絡用。 */
export type PageSnapshot = Record<string, unknown>

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
  /** 頁面自己的現況（選取、上次執行、未儲存…）；每次提問時呼叫 */
  describe?: () => PageSnapshot | null
  /** 流程編輯器：選取並捲到某個節點（助手回覆的「前往」動作） */
  focusNode?: (nodeId: string) => void
  /** 提案只疊在影像上，不寫入任何節點。 */
  showProposals?: (regions: Region[]) => void
  proposalTasks?: (ids: string[]) => void
  /** 套用前先等待頁面內尚未完成的欄位變更。 */
  prepareGraph?: () => Promise<void>
  runInspection?: () => Promise<void>
  /** 影像視窗互動協定：請使用者在這一頁的影像上畫一個區域（取消回 null） */
  requestRegion?: (shapes?: RoiShape[]) => Promise<Region | null>
  /** 影像視窗互動協定：顯示某個節點（或整條流程）的預覽 */
  showPreview?: (request: { node?: string; port?: string; image?: number }) => Promise<void>
  /** 流程編輯器：開工具箱（可指定分類，離線退化到「檢測任務」） */
  openToolPicker?: (category?: string) => void
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

/** 一次執行的精簡摘要（狀態、錯誤、沒過的節點）；給快照與操作軌跡用，不含影像。 */
export function describeReport(report: RunReport | null | undefined, types?: Map<string, string>): PageSnapshot | null {
  if (!report) return null
  const nodes = Object.entries(report.nodes ?? {})
    .filter(([, n]) => n.status !== 'ok')
    .slice(0, 8)
    .map(([id, n]) => ({ id, ...(types?.get(id) ? { type: types.get(id) } : {}), status: n.status, ...(n.message ? { message: String(n.message).slice(0, 160) } : {}) }))
  return {
    status: report.status,
    ...(report.error ? { error: String(report.error).slice(0, 300) } : {}),
    duration_ms: Math.round(report.duration_ms ?? 0),
    ...(nodes.length ? { nodes } : {}),
  }
}
