import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api, onSessionExpired, session } from '@/lib/api'
import type { Me, ThemePreference, TokenPair } from '@/lib/types'
import { applyLanguage, normalizeLanguage, toApiLanguage, type SupportedLanguage } from '@/i18n'
import { applyThemeClass } from './ThemeProvider'

interface AuthContextValue {
  me: Me | null
  loading: boolean
  /** True once the initial session check has finished, success or not. */
  ready: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  reload: () => Promise<void>
  switchOrganization: (slug: string) => Promise<void>
  savePreferences: (input: {
    theme?: ThemePreference
    language?: SupportedLanguage
    timezone_name?: string
  }) => Promise<void>
  can: (permission: string) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(false)
  const [ready, setReady] = useState(!session.isAuthenticated)

  /** Adopt the account's stored theme and language so they follow the user. */
  const adoptPreferences = useCallback((profile: Me) => {
    applyThemeClass(profile.user.theme)
    applyLanguage(normalizeLanguage(profile.user.language))
  }, [])

  const loadMe = useCallback(async () => {
    const profile = await api.get<Me>('/auth/me')
    session.setOrganization(profile.organization.slug)
    setMe(profile)
    adoptPreferences(profile)
    return profile
  }, [adoptPreferences])

  // Restore the session on a page reload.
  useEffect(() => {
    if (!session.isAuthenticated) {
      setReady(true)
      return
    }
    let cancelled = false
    setLoading(true)
    loadMe()
      .catch(() => {
        if (!cancelled) session.clear()
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
        setReady(true)
      })
    return () => {
      cancelled = true
    }
  }, [loadMe])

  // The API client tells us when a refresh failed and the session is gone.
  useEffect(
    () =>
      onSessionExpired(() => {
        setMe(null)
        queryClient.clear()
      }),
    [queryClient],
  )

  const signIn = useCallback(
    async (email: string, password: string) => {
      setLoading(true)
      try {
        const pair = await api.anonymous.post<TokenPair>('/auth/login', { email, password })
        session.setTokens(pair)
        // A stale organisation header from a previous account would scope the
        // very first request to the wrong tenant.
        session.setOrganization(null)
        await loadMe()
      } finally {
        setLoading(false)
      }
    },
    [loadMe],
  )

  const signOut = useCallback(async () => {
    const refresh = session.refresh
    if (refresh) {
      // Best effort: a failed revoke must not trap the user in the app.
      await api.anonymous.post('/auth/logout', { refresh_token: refresh }).catch(() => undefined)
    }
    session.clear()
    setMe(null)
    queryClient.clear()
  }, [queryClient])

  const reload = useCallback(async () => {
    await loadMe()
  }, [loadMe])

  const switchOrganization = useCallback(
    async (slug: string) => {
      session.setOrganization(slug)
      // Everything cached belongs to the previous tenant.
      queryClient.clear()
      await loadMe()
    },
    [loadMe, queryClient],
  )

  const savePreferences = useCallback<AuthContextValue['savePreferences']>(
    async (input) => {
      const body: Record<string, string> = {}
      if (input.theme) body.theme = input.theme
      if (input.language) body.language = toApiLanguage(input.language)
      if (input.timezone_name) body.timezone_name = input.timezone_name

      const user = await api.patch<Me['user']>('/auth/me/preferences', body)
      setMe((current) => (current ? { ...current, user } : current))
    },
    [],
  )

  const can = useCallback(
    (permission: string) => Boolean(me?.permissions.includes(permission)),
    [me],
  )

  const value = useMemo<AuthContextValue>(
    () => ({
      me,
      loading,
      ready,
      signIn,
      signOut,
      reload,
      switchOrganization,
      savePreferences,
      can,
    }),
    [me, loading, ready, signIn, signOut, reload, switchOrganization, savePreferences, can],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
