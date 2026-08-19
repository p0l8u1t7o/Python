/**
 * API client.
 *
 * Two things here are worth knowing about:
 *
 * - **Single-flight refresh.** When several requests race a 401 at once, only
 *   one refresh call is made; the others await the same promise. Without this,
 *   a dashboard firing six parallel queries would burn six refresh tokens and
 *   trip the server's reuse detection, logging the user out.
 * - **Session storage.** Tokens live in localStorage so a reload keeps the
 *   session. The organisation header is sent on every request so the backend
 *   scopes the query without the caller having to remember.
 */

import type { ApiErrorBody, TokenPair } from './types'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api'

const ACCESS_KEY = 'zqs.access'
const REFRESH_KEY = 'zqs.refresh'
const ORG_KEY = 'zqs.org'
export const LANGUAGE_KEY = 'zqs.language'
export const THEME_KEY = 'zqs.theme'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** True when the caller should send the user back to the login screen. */
  get isAuthFailure(): boolean {
    return this.status === 401
  }
}

// ---------------------------------------------------------------------------
// Session state
// ---------------------------------------------------------------------------
export const session = {
  get access(): string | null {
    return localStorage.getItem(ACCESS_KEY)
  },
  get refresh(): string | null {
    return localStorage.getItem(REFRESH_KEY)
  },
  get organization(): string | null {
    return localStorage.getItem(ORG_KEY)
  },
  setTokens(pair: TokenPair) {
    localStorage.setItem(ACCESS_KEY, pair.access_token)
    localStorage.setItem(REFRESH_KEY, pair.refresh_token)
  },
  setOrganization(slug: string | null) {
    if (slug) localStorage.setItem(ORG_KEY, slug)
    else localStorage.removeItem(ORG_KEY)
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(ORG_KEY)
  },
  get isAuthenticated(): boolean {
    return Boolean(localStorage.getItem(ACCESS_KEY))
  },
}

type Listener = () => void
const logoutListeners = new Set<Listener>()

/** Notified when the session becomes unrecoverable, so the app can redirect. */
export function onSessionExpired(listener: Listener): () => void {
  logoutListeners.add(listener)
  return () => logoutListeners.delete(listener)
}

function announceSessionExpired() {
  session.clear()
  logoutListeners.forEach((listener) => listener())
}

// ---------------------------------------------------------------------------
// Refresh
// ---------------------------------------------------------------------------
let refreshInFlight: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight

  refreshInFlight = (async () => {
    const token = session.refresh
    if (!token) return null
    try {
      const response = await fetch(`${BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: token }),
      })
      if (!response.ok) return null
      const pair = (await response.json()) as TokenPair
      session.setTokens(pair)
      return pair.access_token
    } catch {
      return null
    } finally {
      // Cleared in a microtask so concurrent callers all observe this attempt.
      queueMicrotask(() => {
        refreshInFlight = null
      })
    }
  })()

  return refreshInFlight
}

// ---------------------------------------------------------------------------
// Request
// ---------------------------------------------------------------------------
interface RequestOptions {
  method?: string
  body?: unknown
  query?: Record<string, unknown>
  /** Skip the Authorization header (login, refresh, public endpoints). */
  anonymous?: boolean
  signal?: AbortSignal
}

function buildUrl(path: string, query?: Record<string, unknown>): string {
  const url = `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
  if (!query) return url

  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      // Ninja reads repeated keys as a list.
      value.forEach((item) => params.append(key, String(item)))
    } else {
      params.append(key, String(value))
    }
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = 'http_error'
  let message = `${response.status} ${response.statusText}`
  let details: unknown

  try {
    const body = (await response.json()) as Partial<ApiErrorBody>
    if (body?.error) {
      code = body.error.code || code
      message = body.error.message || message
      details = body.error.details
    }
  } catch {
    // Non-JSON error body (proxy failure, HTML error page); keep the default.
  }
  return new ApiError(response.status, code, message, details)
}

async function performRequest(
  path: string,
  options: RequestOptions,
  accessToken: string | null,
): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Accept-Language': localStorage.getItem(LANGUAGE_KEY) ?? 'en',
  }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (!options.anonymous && accessToken) {
    headers.Authorization = `Bearer ${accessToken}`
  }
  const organization = session.organization
  if (!options.anonymous && organization) headers['X-Organization'] = organization

  return fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  })
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await performRequest(path, options, session.access)

  if (response.status === 401 && !options.anonymous) {
    const renewed = await refreshAccessToken()
    if (renewed) {
      response = await performRequest(path, options, renewed)
    } else {
      announceSessionExpired()
      throw await toApiError(response)
    }
  }

  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T

  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const api = {
  get: <T>(path: string, query?: Record<string, unknown>, signal?: AbortSignal) =>
    request<T>(path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Record<string, unknown>) =>
    request<T>(path, { method: 'POST', body: body ?? {}, query }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body: body ?? {} }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ?? {} }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  anonymous: {
    post: <T>(path: string, body?: unknown) =>
      request<T>(path, { method: 'POST', body: body ?? {}, anonymous: true }),
    get: <T>(path: string) => request<T>(path, { anonymous: true }),
  },
}
