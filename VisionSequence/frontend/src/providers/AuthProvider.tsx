/**
 * 身分：啟動時查 /auth/status 與 /auth/me；提供 me、role、isAdmin、isEngineer、lock、login/logout/refresh。
 * - 401（api.ts 的 onSessionExpired）→ me 清空，RequireAuth 會導到 /login。
 * - lock 狀態放在 query 快取 ['engine-lock']：me.lock 預填、SSE lock 事件與 30 秒輪詢更新。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api, authToken, onSessionExpired, setAuthToken } from '@/lib/api'
import { keys, useEngineLock } from '@/lib/queries'
import { isThemePreference, useTheme } from '@/providers/ThemeProvider'
import type { AuthUser, EngineLock, Me, Role } from '@/lib/types'

interface AuthContextValue {
  /** 尚未完成初始查詢 */
  loading: boolean
  /** 系統沒有任何使用者（要先建立第一個管理員） */
  setupRequired: boolean
  me: Me | null
  /** 已登入（使用者）或整合方金鑰有效 */
  authenticated: boolean
  role: Role
  isAdmin: boolean
  /** 能改流程圖、訓練模型、調任何參數（admin 或 engineer）。 */
  isEngineer: boolean
  lock: EngineLock
  login: (username: string, password: string) => Promise<Me>
  setup: (username: string, password: string, displayName: string) => Promise<Me>
  logout: () => Promise<void>
  refresh: () => Promise<Me | null>
}

const NO_LOCK: EngineLock = { locked: false, holder: '', reason: '', locked_at: null, expires_at: null }
const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const [loading, setLoading] = useState(true)
  const [setupRequired, setSetupRequired] = useState(false)
  const [me, setMe] = useState<Me | null>(null)
  // 主題經 ref 讀最新值：applyMe 的身分不能跟著 theme 變（refresh 的 effect 會重觸發）
  const theme = useTheme()
  const themeRef = useRef(theme)
  themeRef.current = theme

  const applyMe = useCallback(
    (next: Me | null) => {
      setMe(next)
      if (next?.lock) client.setQueryData<EngineLock>(keys.lock, next.lock)
      // 登入者存過主題 → 套用伺服端偏好（不回寫；跨裝置/重整都一致）
      const remote = next?.prefs?.theme
      if (isThemePreference(remote) && remote !== themeRef.current.preference) themeRef.current.adoptRemote(remote)
    },
    [client],
  )

  const refresh = useCallback(async (): Promise<Me | null> => {
    try {
      const status = await api.get<{ setup_required: boolean }>('/auth/status')
      setSetupRequired(status.setup_required)
      if (status.setup_required) {
        applyMe(null)
        return null
      }
    } catch {
      /* 後端未啟動：交給下面的 /auth/me 判斷 */
    }
    try {
      const next = await api.get<Me>('/auth/me')
      // bootstrap（沒有使用者）不算登入
      const usable = next.kind === 'bootstrap' ? null : next
      applyMe(usable)
      return usable
    } catch {
      applyMe(null)
      return null
    } finally {
      setLoading(false)
    }
  }, [applyMe])

  useEffect(() => {
    void refresh().finally(() => setLoading(false))
  }, [refresh])

  useEffect(
    () =>
      onSessionExpired(() => {
        setMe(null)
        client.clear()
      }),
    [client],
  )

  const login = useCallback(
    async (username: string, password: string) => {
      const result = await api.post<{ token: string; user: AuthUser }>('/auth/login', { username, password })
      setAuthToken(result.token)
      client.clear()
      const next = await api.get<Me>('/auth/me')
      applyMe(next)
      setSetupRequired(false)
      return next
    },
    [applyMe, client],
  )

  const setup = useCallback(
    async (username: string, password: string, displayName: string) => {
      const result = await api.post<{ token: string; user: AuthUser }>('/auth/setup', { username, password, display_name: displayName })
      setAuthToken(result.token)
      client.clear()
      const next = await api.get<Me>('/auth/me')
      applyMe(next)
      setSetupRequired(false)
      return next
    },
    [applyMe, client],
  )

  const logout = useCallback(async () => {
    if (authToken()) {
      try {
        await api.post('/auth/logout')
      } catch {
        /* 權杖可能已失效 */
      }
    }
    setAuthToken('')
    setMe(null)
    client.clear()
  }, [client])

  const authenticated = me !== null && (me.kind === 'integrator' || me.user !== null)
  const lockQuery = useEngineLock(authenticated)
  const lock = lockQuery.data ?? me?.lock ?? NO_LOCK

  const value = useMemo<AuthContextValue>(
    () => {
      const role: Role = (me?.role as Role) ?? (me?.is_admin ? 'admin' : 'engineer')  // 舊版後端沒回 role 時比照後端預設
      return { loading, setupRequired, me, authenticated, role, isAdmin: role === 'admin', isEngineer: role === 'admin' || role === 'engineer', lock, login, setup, logout, refresh }
    },
    [loading, setupRequired, me, authenticated, lock, login, setup, logout, refresh],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

/** 目前身分是否為這把鎖的持有者（管理員另外判斷）。 */
export function isLockHolder(me: Me | null, lock: EngineLock): boolean {
  if (!lock.locked) return false
  if (me?.kind === 'integrator') return lock.holder === 'integrator'
  return Boolean(me?.user && lock.holder === me.user.username)
}
