/**
 * The console's live feed: one SSE connection, targeted cache invalidation.
 *
 * The server pushes *what changed* (telemetry for these devices, a status
 * change, an alert, an event, a command) every half second at most. This
 * hook turns each notice into `invalidateQueries` on exactly the queries that
 * show that data, so the active page refetches immediately instead of on its
 * next 5-15 s poll. Notices are coalesced for ~150 ms so a burst of readings
 * from four devices becomes one round of refetches, not four.
 *
 * Polling stays on underneath as the fallback; when the stream is connected
 * it is simply never the first to notice anything.
 */

import { useEffect, useRef, useState } from 'react'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'

import { session } from '@/lib/api'
import { LIVE_REANCHOR_EVENT } from '@/lib/useTimeRange'

const RECONNECT_DELAY_MS = 5000
const COALESCE_MS = 150

type Pending = {
  telemetry: Set<string>
  devices: Set<string>
  events: Set<string>
  commands: Set<string>
  alerts: boolean
}

function empty(): Pending {
  return {
    telemetry: new Set(),
    devices: new Set(),
    events: new Set(),
    commands: new Set(),
    alerts: false,
  }
}

/**
 * Charts re-query a whole window, and re-anchoring a rolling window changes
 * the query key of *every* windowed query on the page (energy intervals,
 * cost breakdown, sessions...). Keep that to the old polling pace; the
 * live values themselves still update within a second.
 */
const SERIES_THROTTLE_MS = 15_000
let lastSeriesRefresh = 0

function flush(queryClient: QueryClient, pending: Pending) {
  const invalidate = (queryKey: readonly unknown[]) =>
    void queryClient.invalidateQueries({ queryKey })

  if (pending.telemetry.size > 0) {
    invalidate(['latest'])
    invalidate(['fleet'])
    invalidate(['ems', 'overview'])
    invalidate(['deviceMetrics'])
    for (const id of pending.telemetry) invalidate(['devices', 'detail', id])

    // Charts: roll the window forward and refetch the series, throttled -
    // a series query covers hours of samples, so once every few seconds is
    // the right pace, not once per reading.
    const now = Date.now()
    if (now - lastSeriesRefresh > SERIES_THROTTLE_MS) {
      lastSeriesRefresh = now
      window.dispatchEvent(new Event(LIVE_REANCHOR_EVENT))
      invalidate(['series'])
      invalidate(['ems', 'intervals'])
    }
  }
  // Rolling time windows re-anchor to "now" so a freshly time-stamped row
  // is inside the query, not just fetched and discarded.
  if (pending.events.size > 0 || pending.alerts || pending.devices.size > 0) {
    window.dispatchEvent(new Event(LIVE_REANCHOR_EVENT))
  }
  if (pending.devices.size > 0) {
    invalidate(['devices'])
    invalidate(['fleet'])
    invalidate(['sites'])
    invalidate(['edge-nodes'])
  }
  if (pending.alerts) {
    invalidate(['alerts'])
    invalidate(['fleet'])
  }
  if (pending.events.size > 0) {
    invalidate(['events'])
    for (const id of pending.events) invalidate(['devices', id, 'events'])
  }
  if (pending.commands.size > 0) {
    invalidate(['commands'])
    for (const id of pending.commands) invalidate(['devices', id, 'commands'])
  }
}

export function useLiveStream(enabled: boolean): boolean {
  const queryClient = useQueryClient()
  const [connected, setConnected] = useState(false)
  const pending = useRef<Pending>(empty())
  const flushTimer = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (!enabled) return

    let source: EventSource | null = null
    let retryTimer: number | undefined
    let stopped = false

    const schedule = () => {
      if (flushTimer.current !== undefined) return
      flushTimer.current = window.setTimeout(() => {
        flushTimer.current = undefined
        const batch = pending.current
        pending.current = empty()
        flush(queryClient, batch)
      }, COALESCE_MS)
    }

    const ids = (event: Event): string[] => {
      try {
        const data = JSON.parse((event as MessageEvent).data) as { device_ids?: string[] }
        return data.device_ids ?? []
      } catch {
        return []
      }
    }

    const open = () => {
      const token = session.access
      if (!token) return
      const params = new URLSearchParams({ token })
      const organization = session.organization
      if (organization) params.set('organization', organization)

      source = new EventSource(`/api/live/stream?${params}`)
      source.addEventListener('open', () => setConnected(true))
      source.addEventListener('telemetry', (event) => {
        for (const id of ids(event)) pending.current.telemetry.add(id)
        schedule()
      })
      source.addEventListener('devices', (event) => {
        for (const id of ids(event)) pending.current.devices.add(id)
        schedule()
      })
      source.addEventListener('alerts', () => {
        pending.current.alerts = true
        schedule()
      })
      source.addEventListener('events', (event) => {
        for (const id of ids(event)) pending.current.events.add(id)
        schedule()
      })
      source.addEventListener('commands', (event) => {
        for (const id of ids(event)) pending.current.commands.add(id)
        schedule()
      })
      source.onerror = () => {
        // Covers the server's deliberate ~55 s window closing as well as real
        // failures; reconnect by hand so each attempt reads the current token.
        setConnected(false)
        source?.close()
        if (!stopped) retryTimer = window.setTimeout(open, RECONNECT_DELAY_MS)
      }
    }

    open()
    return () => {
      stopped = true
      source?.close()
      window.clearTimeout(retryTimer)
      window.clearTimeout(flushTimer.current)
      flushTimer.current = undefined
      setConnected(false)
    }
  }, [enabled, queryClient])

  return connected
}
