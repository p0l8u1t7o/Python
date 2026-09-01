/**
 * 主題風格：light / dark / cyber（Cyberpunk，Temp/Style.md）／system（跟隨系統，二選 light|dark）。
 * - 套用方式：html 掛 .dark（深色系主題）＋ .theme-<id>（自訂風格的變數覆蓋；index.css）。
 * - 儲存：localStorage（index.html 首次繪製前套 class 用）；已登入時另 PATCH /auth/prefs 回寫
 *   使用者設定，登入／重整由 AuthProvider 依 /auth/me 的 prefs.theme 呼叫 adoptRemote() 套用。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { THEME_KEY, api, authToken } from '@/lib/api'

/** 可選主題（與後端 UI_THEMES、index.html 開機腳本同步）。base 決定要不要掛 .dark。 */
export const THEMES = [
  { id: 'light', base: 'light' },
  { id: 'dark', base: 'dark' },
  { id: 'cyber', base: 'dark' },
] as const

export type ThemeId = (typeof THEMES)[number]['id']
export type ThemePreference = ThemeId | 'system'

const IDS = THEMES.map((t) => t.id) as readonly string[]

interface ThemeContextValue {
  preference: ThemePreference
  /** 實際生效的主題（system 已解析） */
  active: ThemeId
  /** 深淺色（給只需要二元判斷的元件） */
  resolved: 'light' | 'dark'
  setPreference: (value: ThemePreference) => void
  /** 套用伺服端儲存的偏好（不回寫伺服器；AuthProvider 用） */
  adoptRemote: (value: ThemePreference) => void
  toggle: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)
const MEDIA = '(prefers-color-scheme: dark)'

function baseOf(id: ThemeId): 'light' | 'dark' {
  return THEMES.find((t) => t.id === id)?.base ?? 'light'
}

function resolve(preference: ThemePreference): ThemeId {
  if (preference === 'system') return window.matchMedia(MEDIA).matches ? 'dark' : 'light'
  return preference
}

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === 'system' || (typeof value === 'string' && IDS.includes(value))
}

function readStored(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    return isThemePreference(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

function apply(preference: ThemePreference) {
  const id = resolve(preference)
  const root = document.documentElement
  root.classList.toggle('dark', baseOf(id) === 'dark')
  for (const t of THEMES) root.classList.toggle(`theme-${t.id}`, t.id === id && !['light', 'dark'].includes(t.id))
  try {
    if (preference === 'system') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, preference)
  } catch {
    /* 私密模式 */
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStored)
  const [active, setActive] = useState<ThemeId>(() => resolve(readStored()))

  const adoptRemote = useCallback((value: ThemePreference) => {
    setPreferenceState(value)
    apply(value)
    setActive(resolve(value))
  }, [])

  const setPreference = useCallback((value: ThemePreference) => {
    adoptRemote(value)
    // 已登入 → 回寫使用者設定（fire-and-forget；離線失敗不影響本地切換）
    if (authToken()) void api.patch('/auth/prefs', { theme: value }).catch(() => {})
  }, [adoptRemote])

  useEffect(() => {
    if (preference !== 'system') return
    const media = window.matchMedia(MEDIA)
    const onChange = () => {
      apply('system')
      setActive(resolve('system'))
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [preference])

  const resolved = baseOf(active)
  const value = useMemo(
    () => ({
      preference,
      active,
      resolved,
      setPreference,
      adoptRemote,
      toggle: () => setPreference(resolved === 'dark' ? 'light' : 'dark'),
    }),
    [preference, active, resolved, setPreference, adoptRemote],
  )
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider')
  return ctx
}
