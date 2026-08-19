import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { THEME_KEY } from '@/lib/api'
import type { ThemePreference } from '@/lib/types'

interface ThemeContextValue {
  /** What the user chose, which may be "system". */
  preference: ThemePreference
  /** What is actually rendered right now. */
  resolved: 'light' | 'dark'
  setPreference: (value: ThemePreference) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

const MEDIA = '(prefers-color-scheme: dark)'

function systemPrefersDark(): boolean {
  return window.matchMedia(MEDIA).matches
}

function resolve(preference: ThemePreference): 'light' | 'dark' {
  if (preference === 'system') return systemPrefersDark() ? 'dark' : 'light'
  return preference
}

/** Exported so non-React code (the auth bootstrap) can adopt a server value. */
export function applyThemeClass(preference: ThemePreference): void {
  document.documentElement.classList.toggle('dark', resolve(preference) === 'dark')
  localStorage.setItem(THEME_KEY, preference)
}

function readStored(): ThemePreference {
  const stored = localStorage.getItem(THEME_KEY)
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStored)
  const [resolved, setResolved] = useState<'light' | 'dark'>(() => resolve(readStored()))

  const setPreference = useCallback((value: ThemePreference) => {
    setPreferenceState(value)
    applyThemeClass(value)
    setResolved(resolve(value))
  }, [])

  useEffect(() => {
    applyThemeClass(preference)
    setResolved(resolve(preference))
  }, [preference])

  // Following the OS setting means reacting to it changing while the tab is
  // open, not only at load.
  useEffect(() => {
    if (preference !== 'system') return
    const media = window.matchMedia(MEDIA)
    const onChange = () => {
      applyThemeClass('system')
      setResolved(resolve('system'))
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [preference])

  // A second tab changing the theme should be reflected here too.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== THEME_KEY) return
      const next = readStored()
      setPreferenceState(next)
      setResolved(resolve(next))
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const value = useMemo(
    () => ({ preference, resolved, setPreference }),
    [preference, resolved, setPreference],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used inside ThemeProvider')
  return context
}
