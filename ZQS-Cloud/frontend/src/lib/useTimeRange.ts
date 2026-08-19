import { useCallback, useMemo, useState } from 'react'

export const RANGE_KEYS = ['1h', '6h', '24h', '7d', '30d'] as const
export type RangeKey = (typeof RANGE_KEYS)[number]

const SECONDS: Record<RangeKey, number> = {
  '1h': 3600,
  '6h': 6 * 3600,
  '24h': 24 * 3600,
  '7d': 7 * 24 * 3600,
  '30d': 30 * 24 * 3600,
}

export interface TimeRange {
  key: RangeKey
  seconds: number
  start: string
  end: string
  setKey: (key: RangeKey) => void
  /** Bump to re-anchor `end` to "now" without changing the window length. */
  refresh: () => void
}

/**
 * A rolling window anchored at the current time.
 *
 * `end` is recomputed only when the range changes or `refresh()` is called -
 * not on every render - because a start/end that drifted each render would
 * change the query key continuously and refetch forever.
 */
export function useTimeRange(initial: RangeKey = '24h'): TimeRange {
  const [key, setKey] = useState<RangeKey>(initial)
  const [anchor, setAnchor] = useState(() => Date.now())

  const refresh = useCallback(() => setAnchor(Date.now()), [])

  const changeKey = useCallback((next: RangeKey) => {
    setKey(next)
    setAnchor(Date.now())
  }, [])

  return useMemo(() => {
    const seconds = SECONDS[key]
    const end = new Date(anchor)
    const start = new Date(anchor - seconds * 1000)
    return {
      key,
      seconds,
      start: start.toISOString(),
      end: end.toISOString(),
      setKey: changeKey,
      refresh,
    }
  }, [key, anchor, changeKey, refresh])
}

export function rangeSeconds(key: RangeKey): number {
  return SECONDS[key]
}
