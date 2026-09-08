import type { Overlay } from '@/lib/types'

export const DEFAULT_OVERLAY_LIMIT = 2000
export const OVERLAY_LIMIT_KEY = 'vs.overlayLimit'

export interface OverlayLimitResult {
  overlays: Overlay[]
  shown: number
  total: number
  truncated: boolean
  limit: number
}

export function normalizeOverlayLimit(value: unknown, fallback = DEFAULT_OVERLAY_LIMIT): number {
  const parsed = Number(value)
  const safeFallback = Number.isFinite(fallback) && fallback > 0 ? Math.floor(fallback) : DEFAULT_OVERLAY_LIMIT
  if (!Number.isFinite(parsed) || parsed <= 0) return safeFallback
  return Math.max(1, Math.floor(parsed))
}

export function limitOverlays(overlays: Overlay[] | undefined | null, limit: number): OverlayLimitResult {
  const list = overlays ?? []
  const safeLimit = normalizeOverlayLimit(limit)
  const shown = Math.min(list.length, safeLimit)
  return {
    overlays: list.slice(0, shown),
    shown,
    total: list.length,
    truncated: shown < list.length,
    limit: safeLimit,
  }
}

export function readOverlayLimit(): number {
  try {
    return normalizeOverlayLimit(localStorage.getItem(OVERLAY_LIMIT_KEY))
  } catch {
    return DEFAULT_OVERLAY_LIMIT
  }
}

export function writeOverlayLimit(limit: number): number {
  const safeLimit = normalizeOverlayLimit(limit)
  try {
    localStorage.setItem(OVERLAY_LIMIT_KEY, String(safeLimit))
  } catch {
    /* 裝置儲存失敗時僅保留畫面狀態。 */
  }
  return safeLimit
}
