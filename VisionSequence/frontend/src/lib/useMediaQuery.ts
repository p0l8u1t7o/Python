/** 響應式判斷：訂閱 matchMedia，供 AppShell（手機抽屜式側欄、精簡麵包屑）等使用；SSR／jsdom 沒有 matchMedia 時回 false。 */
import { useSyncExternalStore } from 'react'

function subscribe(query: string, callback: () => void) {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {}
  const mql = window.matchMedia(query)
  mql.addEventListener('change', callback)
  return () => mql.removeEventListener('change', callback)
}

function snapshot(query: string): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia(query).matches
}

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore((cb) => subscribe(query, cb), () => snapshot(query), () => false)
}

/** 手機寬度（< 768px）：側欄改抽屜、編輯器只留畫布。 */
export const MOBILE_QUERY = '(max-width: 767px)'
/** 窄螢幕（< 640px）：麵包屑只留最後兩層。 */
export const NARROW_QUERY = '(max-width: 639px)'
