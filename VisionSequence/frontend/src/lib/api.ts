/**
 * API 客戶端。身分兩種：使用者權杖（Authorization: Bearer，存 localStorage `vs.token`）
 * 或整合方 API 金鑰（X-API-Key）。<img>／EventSource 帶不了 header，兩者都走 query string。
 * 401 → 清 token 並通知 AuthProvider（onSessionExpired）導到登入頁。
 */

/** API 基底：獨立部署前端時以 VITE_API_BASE_URL 指向後端（含 /api）；同源時走 /api（dev 由 Vite 代理、正式由 whitenoise 同站服務）。 */
export const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api'
export const API_KEY_STORAGE = 'vs.apiKey'
export const TOKEN_STORAGE = 'vs.token'
export const THEME_KEY = 'vs.theme'
export const LANGUAGE_KEY = 'vs.language'

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown }
}

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
}

export function apiKey(): string {
  try {
    return localStorage.getItem(API_KEY_STORAGE) ?? ''
  } catch {
    return ''
  }
}

export function setApiKey(key: string) {
  if (key) localStorage.setItem(API_KEY_STORAGE, key)
  else localStorage.removeItem(API_KEY_STORAGE)
}

export function authToken(): string {
  try {
    return localStorage.getItem(TOKEN_STORAGE) ?? ''
  } catch {
    return ''
  }
}

export function setAuthToken(token: string) {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE, token)
    else localStorage.removeItem(TOKEN_STORAGE)
  } catch {
    /* 私密模式 */
  }
}

// ---- 401 通知：AuthProvider 註冊，request() 收到 401 時呼叫 ----
type SessionListener = () => void
const sessionListeners = new Set<SessionListener>()

export function onSessionExpired(listener: SessionListener): () => void {
  sessionListeners.add(listener)
  return () => sessionListeners.delete(listener)
}

function notifySessionExpired() {
  for (const listener of sessionListeners) listener()
}

/** <img src> / EventSource 帶不了 header，金鑰與權杖走 query string。 */
export function withKey(url: string): string {
  const params: string[] = []
  const key = apiKey()
  if (key) params.push(`api_key=${encodeURIComponent(key)}`)
  const token = authToken()
  if (token) params.push(`token=${encodeURIComponent(token)}`)
  if (!params.length) return url
  return `${url}${url.includes('?') ? '&' : '?'}${params.join('&')}`
}

/** 快取影像的網址。max = 最長邊（0 = 原圖）。 */
export function imageUrl(ref: string | null | undefined, max = 0, fmt: 'jpeg' | 'png' = 'jpeg'): string {
  if (!ref) return ''
  const params = new URLSearchParams()
  if (max) params.set('max', String(max))
  if (fmt !== 'jpeg') params.set('fmt', fmt)
  const qs = params.toString()
  return withKey(`${BASE_URL}/vision/images/${encodeURIComponent(ref)}${qs ? `?${qs}` : ''}`)
}

/** Golden Set 案例影像（<img> 用；帶 token） */
export function goldenImageUrl(flowId: number, caseId: number, max = 0): string {
  return withKey(`${BASE_URL}/vision/flows/${flowId}/golden/${caseId}/image${max ? `?max=${max}` : ''}`)
}

/** 下載檔案（fetch blob，帶 Authorization／X-API-Key）；檔名取 Content-Disposition，沒有就用 fallback。 */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const headers: Record<string, string> = {}
  const key = apiKey()
  if (key) headers['X-API-Key'] = key
  const token = authToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(buildUrl(path), { headers })
  if (!response.ok) throw await toApiError(response)
  const blob = await response.blob()
  let name = fallbackName
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const plain = /filename="([^"]+)"/i.exec(disposition)
  if (utf8) name = decodeURIComponent(utf8[1])
  else if (plain) name = plain[1]
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function assetUrl(id: string, max = 0): string {
  return withKey(`${BASE_URL}/vision/assets/${id}/file${max ? `?max=${max}` : ''}`)
}

export function sourcePreviewUrl(id: number, max = 1280): string {
  return withKey(`${BASE_URL}/vision/sources/${id}/preview?max=${max}&t=${Date.now()}`)
}

export function streamUrl(flowId: number | null, since?: number, outputs = true): string {
  const params = new URLSearchParams()
  if (since) params.set('since', String(since))
  if (!outputs) params.set('outputs', '0')
  const qs = params.toString()
  const path = flowId === null ? `${BASE_URL}/vision/events` : `${BASE_URL}/vision/flows/${flowId}/stream`
  return withKey(`${path}${qs ? `?${qs}` : ''}`)
}

interface RequestOptions {
  method?: string
  body?: unknown
  /** multipart：直接傳 FormData */
  form?: FormData
  query?: Record<string, unknown>
  signal?: AbortSignal
}

function buildUrl(path: string, query?: Record<string, unknown>): string {
  const url = `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.append(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = 'http_error'
  let message = `${response.status} ${response.statusText}`
  let details: unknown
  try {
    const body = (await response.json()) as Partial<ApiErrorBody> & { detail?: string }
    if (body?.error) {
      code = body.error.code || code
      message = body.error.message || message
      details = body.error.details
    } else if (typeof body?.detail === 'string') {
      // ninja 預設的 401 格式 {"detail": "Unauthorized"}
      message = body.detail
      if (response.status === 401) code = 'unauthenticated'
    }
  } catch {
    /* 非 JSON */
  }
  if (response.status === 401 && code === 'http_error') code = 'unauthenticated'
  return new ApiError(response.status, code, message, details)
}

/** 登入／初始化本身的 401 是「帳密錯誤」，不算工作階段過期。 */
const NO_EXPIRE_PATHS = ['/auth/login', '/auth/setup', '/auth/status']

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const key = apiKey()
  if (key) headers['X-API-Key'] = key
  const token = authToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (options.form) {
    body = options.form
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? (body ? 'POST' : 'GET'),
    headers,
    body,
    signal: options.signal,
  })
  if (!response.ok) {
    const error = await toApiError(response)
    if (response.status === 401 && !NO_EXPIRE_PATHS.some((p) => path.startsWith(p))) {
      setAuthToken('')
      notifySessionExpired()
    }
    // 423 engine_locked：details 就是 lock 物件，留給 UI 顯示。
    throw error
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string, query?: Record<string, unknown>) => request<T>(path, { query }),
  post: <T>(path: string, body?: unknown, query?: Record<string, unknown>) =>
    request<T>(path, { method: 'POST', body: body ?? {}, query }),
  postForm: <T>(path: string, form: FormData, query?: Record<string, unknown>) =>
    request<T>(path, { method: 'POST', form, query }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T = void>(path: string) => request<T>(path, { method: 'DELETE' }),
}

/** 深度學習樣本影像（<img> 用；帶 token）。 */
export function dlSampleUrl(id: string, max = 0): string {
  return withKey(`${BASE_URL}/vision/dl/samples/${id}/file${max ? `?max=${max}` : ''}`)
}
