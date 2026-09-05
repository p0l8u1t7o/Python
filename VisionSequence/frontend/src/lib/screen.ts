/**
 * 畫面快照：不靠頁面登記也能從 DOM 讀到的「現在看到什麼」——頁面標題、開著的對話框、鎖定橫幅、整合頁的分頁。
 * 只取文字與結構，不取表單值；給全域 AI 助手當脈絡用。
 */
import { sectionOf } from '@/pages/integration/sections'

export interface PageSnapshot {
  title?: string
  dialog?: string
  banner?: string
  tab?: string
  [key: string]: unknown
}

const TAB_KEY = 'vs.integrationTab'

function text(el: Element | null | undefined, max = 120): string {
  return (el?.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, max)
}

/** 整合頁目前的分頁（SectionTabs 記在 sessionStorage）。 */
export function integrationTab(pathname: string): string {
  if (!pathname.startsWith('/integration')) return ''
  try {
    return sessionStorage.getItem(`${TAB_KEY}.${sectionOf(pathname)}`) ?? ''
  } catch {
    return ''
  }
}

/** 設定整合頁要顯示的分頁（助手的「前往」動作在導頁前呼叫）。 */
export function setIntegrationTab(section: string, tab: string): void {
  try {
    sessionStorage.setItem(`${TAB_KEY}.${section}`, tab)
  } catch {
    /* 私密視窗沒有 sessionStorage 也要能用 */
  }
}

export function pageSnapshot(pathname: string): PageSnapshot {
  if (typeof document === 'undefined') return {}
  const out: PageSnapshot = {}
  const title = text(document.querySelector('main h1'))
  if (title) out.title = title
  const dialog = document.querySelector('[role="dialog"]')
  if (dialog) out.dialog = text(dialog.querySelector('h2, h3')) || text(dialog, 80)
  const banner = text(document.querySelector('[data-testid="lock-banner"]'), 200)
  if (banner) out.banner = banner
  const tab = integrationTab(pathname)
  if (tab) out.tab = tab
  return out
}
