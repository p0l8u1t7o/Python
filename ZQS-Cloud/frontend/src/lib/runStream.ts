/**
 * Live run updates over server-sent events.
 *
 * While a run is moving, the editor needs to track a token that spends two
 * seconds on a node. Polling once a second pays full HTTP overhead per tick;
 * one SSE connection receives only the deltas. The hook writes what arrives
 * straight into the TanStack Query cache, so every consumer of the run and
 * log queries updates without knowing the transport changed - and if the
 * stream cannot connect, those queries' own polling is still there as the
 * fallback (the caller lowers it while `connected` is true).
 *
 * EventSource cannot set headers, so auth rides as `?token=`; the server
 * closes each stream after ~55s and the reconnect re-reads the (short-lived)
 * access token.
 */

import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { session } from '@/lib/api'
import { keys } from '@/lib/queries'
import type { Page } from '@/lib/types'
import type { WorkflowRun, WorkflowRunLog } from '@/lib/workflowTypes'

const RECONNECT_DELAY_MS = 5000
/** Must mirror the params the editor passes to `useRunLogs`. */
const LOG_PARAMS = { limit: 200 }

export function useRunStream(runId: string | null, enabled: boolean): boolean {
  const queryClient = useQueryClient()
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!runId || !enabled) return

    let source: EventSource | null = null
    let retryTimer: number | undefined
    let finished = false
    let lastLogId = 0

    const open = () => {
      const token = session.access
      if (!token) return

      const params = new URLSearchParams({ token })
      const organization = session.organization
      if (organization) params.set('organization', organization)
      if (lastLogId) params.set('since', String(lastLogId))

      source = new EventSource(`/api/workflow-runs/${runId}/stream?${params}`)

      source.addEventListener('open', () => setConnected(true))

      source.addEventListener('run', (event) => {
        const run = JSON.parse((event as MessageEvent).data) as WorkflowRun
        queryClient.setQueryData(keys.workflowRun(runId), run)
      })

      source.addEventListener('logs', (event) => {
        const fresh = JSON.parse((event as MessageEvent).data) as WorkflowRunLog[]
        if (fresh.length === 0) return
        lastLogId = fresh[fresh.length - 1].id
        queryClient.setQueryData<Page<WorkflowRunLog>>(
          keys.workflowRunLogs(runId, LOG_PARAMS),
          (old) => {
            const items = [...(old?.items ?? [])]
            const seen = new Set(items.map((item) => item.id))
            for (const entry of fresh) {
              if (!seen.has(entry.id)) items.push(entry)
            }
            return {
              limit: old?.limit ?? LOG_PARAMS.limit,
              offset: old?.offset ?? 0,
              total: items.length,
              items,
            }
          },
        )
      })

      source.addEventListener('done', () => {
        finished = true
        source?.close()
        setConnected(false)
        // The run just finished - the runs list and capacity counters moved.
        void queryClient.invalidateQueries({ queryKey: ['workflow-runs'] })
        void queryClient.invalidateQueries({ queryKey: ['workflows'] })
      })

      source.onerror = () => {
        // Covers both the server's deliberate ~55s window closing and real
        // failures. Reconnect by hand rather than with EventSource's builtin
        // retry so each attempt reads the *current* access token.
        setConnected(false)
        source?.close()
        if (!finished) {
          retryTimer = window.setTimeout(open, RECONNECT_DELAY_MS)
        }
      }
    }

    open()
    return () => {
      finished = true
      source?.close()
      window.clearTimeout(retryTimer)
      setConnected(false)
    }
  }, [runId, enabled, queryClient])

  return connected
}
