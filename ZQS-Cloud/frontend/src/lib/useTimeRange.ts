import { useCallback, useEffect, useMemo, useState } from 'react'

/** The rolling presets, shortest first. `custom` is not one of them. */
export const RANGE_KEYS = ['1h', '6h', '24h', '7d', '30d'] as const
export type PresetKey = (typeof RANGE_KEYS)[number]

/** A preset, or an explicit start/end the user typed in. */
export type RangeKey = PresetKey | 'custom'

/** Dispatched by the live feed when something time-stamped arrived. */
export const LIVE_REANCHOR_EVENT = 'zqs:live-reanchor'

const SECONDS: Record<PresetKey, number> = {
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
  setKey: (key: PresetKey) => void
  /**
   * Pin the window to an explicit interval. ISO strings, or the value of a
   * `datetime-local` input - both parse.
   */
  setCustom: (start: string, end: string) => void
  /** Drop back to the last preset used. */
  clearCustom: () => void
  isCustom: boolean
  /** Bump to re-anchor `end` to "now" without changing the window length. */
  refresh: () => void
}

function isPreset(key: RangeKey): key is PresetKey {
  return key !== 'custom'
}

/**
 * A time window: either a rolling preset anchored at "now", or a fixed
 * interval the user chose.
 *
 * `end` is recomputed only when the range changes or `refresh()` is called -
 * not on every render - because a start/end that drifted each render would
 * change the query key continuously and refetch forever.
 *
 * A custom window does not drift at all, which is the point of it: comparing
 * two readings, or lining a chart up against an incident report, needs the
 * axis to hold still.
 */
export function useTimeRange(initial: PresetKey = '24h'): TimeRange {
  const [key, setKey] = useState<RangeKey>(initial)
  const [preset, setPreset] = useState<PresetKey>(initial)
  const [anchor, setAnchor] = useState(() => Date.now())
  const [custom, setCustomRange] = useState<{ start: string; end: string } | null>(null)

  const refresh = useCallback(() => setAnchor(Date.now()), [])

  // A rolling window has to roll. Without this, `end` stayed at the moment
  // the page opened: after an hour on the events page nothing from the last
  // hour was visible, and a reading that arrived after the page load was
  // outside every query's window no matter how often it refetched. Two
  // triggers: the live feed announcing an event / alert / status change, and
  // a slow timer for the quiet stretches. Custom windows never move.
  useEffect(() => {
    if (custom) return
    const onLive = () => setAnchor(Date.now())
    window.addEventListener(LIVE_REANCHOR_EVENT, onLive)
    const timer = window.setInterval(onLive, 60_000)
    return () => {
      window.removeEventListener(LIVE_REANCHOR_EVENT, onLive)
      window.clearInterval(timer)
    }
  }, [custom])

  const changeKey = useCallback((next: PresetKey) => {
    setKey(next)
    setPreset(next)
    setCustomRange(null)
    setAnchor(Date.now())
  }, [])

  const applyCustom = useCallback((start: string, end: string) => {
    const from = new Date(start)
    const to = new Date(end)
    // Reject an unusable interval rather than issuing a request the API will
    // refuse: the caller has already validated in the UI, this is the backstop.
    if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return
    if (from >= to) return
    setCustomRange({ start: from.toISOString(), end: to.toISOString() })
    setKey('custom')
  }, [])

  const clearCustom = useCallback(() => {
    setCustomRange(null)
    setKey(preset)
    setAnchor(Date.now())
  }, [preset])

  return useMemo(() => {
    if (custom) {
      const seconds = Math.max(
        1,
        Math.round((new Date(custom.end).getTime() - new Date(custom.start).getTime()) / 1000),
      )
      return {
        key: 'custom' as const,
        seconds,
        start: custom.start,
        end: custom.end,
        setKey: changeKey,
        setCustom: applyCustom,
        clearCustom,
        isCustom: true,
        refresh,
      }
    }

    const active: PresetKey = isPreset(key) ? key : preset
    const seconds = SECONDS[active]
    const end = new Date(anchor)
    const start = new Date(anchor - seconds * 1000)
    return {
      key: active,
      seconds,
      start: start.toISOString(),
      end: end.toISOString(),
      setKey: changeKey,
      setCustom: applyCustom,
      clearCustom,
      isCustom: false,
      refresh,
    }
  }, [key, preset, anchor, custom, changeKey, applyCustom, clearCustom, refresh])
}

/**
 * Format an instant for a `datetime-local` input.
 *
 * The input has no timezone, so the value has to be the user's *local* clock
 * time. `toISOString()` would hand it UTC and the field would show the wrong
 * hour for everyone outside it.
 */
export function toLocalInputValue(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}
