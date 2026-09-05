/**
 * 畫面快照：不靠頁面登記也能從 DOM 讀到的「現在看到什麼」——頁面標題、開著的對話框、鎖定橫幅、整合頁的分頁。
 * `screenSummary()` 是使用者主動附上的文字版畫面（標題、警示、分頁、表格前幾列、表單欄位與值、按鈕），
 * 只取文字與結構、跳過密碼欄與助手視窗本身，總長有上限；給全域 AI 助手當脈絡用。
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
const SUMMARY_MAX = 3000
const SKIP_SELECTOR = '[data-testid="assistant-dock"], nav, aside, script, style'

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

function labelOf(el: HTMLElement): string {
  const id = el.id
  const byFor = id ? document.querySelector(`label[for="${id.replace(/"/g, '\\"')}"]`) : null
  const wrap = el.closest('label')
  return text(byFor ?? wrap, 40) || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('name') || ''
}

/** 目前畫面的文字摘要（≤ 3000 字）：使用者按下「附上畫面」才會送出。 */
export function screenSummary(max = SUMMARY_MAX): string {
  if (typeof document === 'undefined') return ''
  const root = (document.querySelector('main') ?? document.body) as HTMLElement
  const skip = (el: Element) => el.closest(SKIP_SELECTOR) !== null
  const lines: string[] = []
  const add = (s: string) => {
    const v = s.replace(/[ \t]+/g, ' ').trim()
    if (v) lines.push(v)
  }
  for (const h of root.querySelectorAll('h1, h2, h3')) if (!skip(h)) add(`# ${text(h)}`)
  for (const el of root.querySelectorAll('[role="alert"], [role="status"]')) if (!skip(el)) add(`! ${text(el, 200)}`)
  for (const el of root.querySelectorAll('[aria-selected="true"], [aria-current="page"]')) if (!skip(el)) add(`tab: ${text(el, 60)}`)
  let tables = 0
  for (const table of root.querySelectorAll('table')) {
    if (skip(table)) continue
    if (tables++ >= 3) break
    const head = [...table.querySelectorAll('thead th')].map((c) => text(c, 40)).filter(Boolean)
    if (head.length) add(`table: ${head.join(' | ')}`)
    const all = [...table.querySelectorAll('tbody tr')]
    for (const r of all.slice(0, 8)) add(`  ${[...r.querySelectorAll('td, th')].map((c) => text(c, 40)).filter(Boolean).join(' | ')}`)
    if (all.length > 8) add(`  ... ${all.length - 8} more rows`)
  }
  let fields = 0
  for (const el of root.querySelectorAll('input, select, textarea')) {
    if (skip(el) || fields >= 25) continue
    const input = el as HTMLInputElement
    if (input.type === 'password' || input.type === 'hidden' || input.type === 'file') continue
    const label = labelOf(input)
    if (!label) continue
    const value = input.type === 'checkbox' || input.type === 'radio' ? (input.checked ? 'on' : 'off') : String(input.value ?? '').slice(0, 60)
    add(`${label}: ${value}`)
    fields++
  }
  const buttons = new Set<string>()
  for (const b of root.querySelectorAll('button, [role="button"]')) {
    if (skip(b) || buttons.size >= 30) continue
    const name = text(b, 40) || b.getAttribute('aria-label') || ''
    if (name) buttons.add(name)
  }
  if (buttons.size) add(`buttons: ${[...buttons].join(', ')}`)
  const out = lines.join('\n')
  return out.length > max ? `${out.slice(0, max)}…` : out
}
