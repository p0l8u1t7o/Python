/**
 * AI 助手視窗的版面：右下角浮動（float）或展開成右側面板（side）。
 * 模組層 store＋useSyncExternalStore：AppShell 依它把內容區讓出右側寬度，助手視窗依它換樣式；偏好存裝置層 localStorage。
 */
import { useSyncExternalStore } from 'react'

export type AssistantLayout = 'float' | 'side'
export interface AssistantLayoutState { layout: AssistantLayout; open: boolean }

const KEY = 'vs.assistant.layout'
/** 右側面板寬度（px）；AppShell 的 padding-right 與面板寬度要一致 */
export const SIDE_PANEL_WIDTH = 440

function readLayout(): AssistantLayout {
  try {
    return localStorage.getItem(KEY) === 'side' ? 'side' : 'float'
  } catch {
    return 'float'
  }
}

let state: AssistantLayoutState = { layout: readLayout(), open: false }
const listeners = new Set<() => void>()

function emit() {
  for (const fn of listeners) fn()
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

export function assistantLayoutState(): AssistantLayoutState {
  return state
}

export function setAssistantLayout(layout: AssistantLayout): void {
  if (state.layout === layout) return
  state = { ...state, layout }
  try {
    localStorage.setItem(KEY, layout)
  } catch {
    /* 隱私模式沒有 localStorage 也要能用 */
  }
  emit()
}

export function setAssistantOpen(open: boolean): void {
  if (state.open === open) return
  state = { ...state, open }
  emit()
}

/** 測試用：回到出廠狀態 */
export function resetAssistantLayout(): void {
  state = { layout: 'float', open: false }
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
  emit()
}

export function useAssistantLayout(): AssistantLayoutState {
  return useSyncExternalStore(subscribe, assistantLayoutState, assistantLayoutState)
}
