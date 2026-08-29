/** 主題：light / dark / system。index.html 已在首次繪製前套 class，這裡只負責之後的切換。 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { THEME_KEY } from '@/lib/api'

export type ThemePreference = 'light' | 'dark' | 'system'

interface ThemeContextValue {
  preference: ThemePreference
  resolved: 'light' | 'dark'
  setPreference: (value: ThemePreference) => void
  toggle: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)
const MEDIA = '(prefers-color-scheme: dark)'

function resolve(preference: ThemePreference): 'light' | 'dark' {
  if (preference === 'system') return window.matchMedia(MEDIA).matches ? 'dark' : 'light'
  return preference
}

function readStored(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
  } catch {
    return 'system'
  }
}

function apply(preference: ThemePreference) {
  document.documentElement.classList.toggle('dark', resolve(preference) === 'dark')
  try {
    if (preference === 'system') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, preference)
  } catch {
    /* 私密模式 */
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStored)
  const [resolved, setResolved] = useState<'light' | 'dark'>(() => resolve(readStored()))

  const setPreference = useCallback((value: ThemePreference) => {
    setPreferenceState(value)
    apply(value)
    setResolved(resolve(value))
  }, [])

  useEffect(() => {
    if (preference !== 'system') return
    const media = window.matchMedia(MEDIA)
    const onChange = () => {
      apply('system')
      setResolved(resolve('system'))
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [preference])

  const value = useMemo(
    () => ({
      preference,
      resolved,
      setPreference,
      toggle: () => setPreference(resolved === 'dark' ? 'light' : 'dark'),
    }),
    [preference, resolved, setPreference],
  )
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider')
  return ctx
}
