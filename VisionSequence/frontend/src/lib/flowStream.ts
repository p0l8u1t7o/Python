/**
 * SSE：一條 EventSource 接收流程的執行事件，直接寫進 TanStack Query 快取。
 *
 * - `run_finished`：run 塞到 ['recent', flowId]（最多 8 筆、新在前），同時更新 flow 的 stats。
 * - `stats` / `continuous`：更新 flow 快取的 stats 與 continuous 旗標。
 * - `lock`：引擎鎖定狀態，寫進 ['engine-lock']（AuthProvider 與橫幅讀這個）。
 * - `cleared`：重置（DELETE recent）：清空 recent 與 stats；編輯器另外靠 onEvent 清畫面。
 * - `bye`：伺服器 55 秒主動關閉，帶 seq 重連補齊漏掉的事件。
 * - `ping`：伺服器每 15 秒的心跳；超過 WATCHDOG_MS 沒收到任何訊息就當斷線（經 proxy 時後端死掉
 *   客戶端連線不一定會被關），主動關閉並重連。
 * - 其他錯誤：5 秒後重連。
 * flowId=null 時連全域 /vision/events（總覽頁），事件的 flow_id 各自分派。
 */
import { useEffect, useRef, useState } from 'react'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'

import { streamUrl } from './api'
import { emptyStats, keys, type RecentRuns } from './queries'
import type { EngineLock, Flow, FlowStats, Page, RunReport } from './types'

const RECONNECT_DELAY_MS = 5000
/** 伺服器心跳 15 秒、串流最長 55 秒；超過這個時間完全沒訊息就是連線死了 */
export const WATCHDOG_MS = 40_000
const KEEP_RECENT = 8

/** 幫一條 EventSource 掛看門狗：任何訊息都餵一次；逾時呼叫 onDead。回傳 stop。 */
export function watchdog(source: EventSource, onDead: () => void, ms = WATCHDOG_MS): () => void {
  let timer = window.setTimeout(onDead, ms)
  const feed = () => {
    window.clearTimeout(timer)
    timer = window.setTimeout(onDead, ms)
  }
  source.addEventListener('open', feed)
  source.addEventListener('ping', feed)
  source.onmessage = feed
  const original = source.addEventListener.bind(source)
  // 之後掛的具名事件也要餵：包一層 addEventListener
  source.addEventListener = ((type: string, listener: EventListenerOrEventListenerObject, options?: boolean | AddEventListenerOptions) => {
    original(type, listener, options)
    if (type !== 'open' && type !== 'ping' && type !== 'error') original(type, feed, options)
  }) as typeof source.addEventListener
  return () => window.clearTimeout(timer)
}

export interface StreamEvent {
  type: string
  flow_id: number
  seq?: number
  run?: RunReport
  run_id?: string
  stats?: FlowStats
  running?: boolean
  continuous?: boolean
  /** type=lock：引擎鎖定狀態變更（全域與流程串流都會收到） */
  lock?: EngineLock
}

function patchFlowCaches(client: QueryClient, flowId: number, patch: Partial<Flow>) {
  client.setQueryData<Flow>(keys.flow(flowId), (old) => (old ? { ...old, ...patch } : old))
  // 列表頁的快取 key 帶搜尋字串，用 prefix 更新所有變體。
  client.setQueriesData<Page<Flow>>({ queryKey: keys.flows }, (old) =>
    old ? { ...old, items: old.items.map((f) => (f.id === flowId ? { ...f, ...patch } : f)) } : old,
  )
}

export function applyStreamEvent(client: QueryClient, event: StreamEvent) {
  if (event.type === 'lock') {
    if (event.lock) client.setQueryData<EngineLock>(keys.lock, event.lock)
    return
  }
  const flowId = event.flow_id
  if (typeof flowId !== 'number') return
  switch (event.type) {
    case 'run_finished': {
      const run = event.run
      if (!run) return
      client.setQueryData<RecentRuns>(keys.recent(flowId), (old) => {
        const items = [run, ...(old?.items ?? []).filter((r) => r.id !== run.id)].slice(0, KEEP_RECENT)
        return { items, stats: event.stats ?? old?.stats ?? emptyStats(), continuous: old?.continuous ?? false }
      })
      if (event.stats) patchFlowCaches(client, flowId, { stats: event.stats })
      break
    }
    case 'stats':
      if (event.stats) patchFlowCaches(client, flowId, { stats: event.stats, continuous: event.continuous })
      break
    case 'cleared':
      client.setQueryData<RecentRuns>(keys.recent(flowId), (old) => ({ items: [], stats: event.stats ?? emptyStats(), continuous: old?.continuous ?? false }))
      patchFlowCaches(client, flowId, { stats: event.stats ?? emptyStats() })
      break
    case 'continuous':
      patchFlowCaches(client, flowId, { continuous: Boolean(event.running) })
      client.setQueryData<RecentRuns>(keys.recent(flowId), (old) =>
        old ? { ...old, continuous: Boolean(event.running) } : old,
      )
      void client.invalidateQueries({ queryKey: keys.capacity })
      break
    default:
      break
  }
}

export interface FlowStreamState {
  connected: boolean
  /** 目前有 run 在跑（run_started 後、run_finished 前） */
  runningIds: Set<string>
}

/**
 * @param flowId null = 全域事件流
 * @param onEvent 額外回呼（編輯器用來更新畫布），用 ref 讀最新版本
 */
export function useFlowStream(
  flowId: number | null | undefined,
  enabled: boolean,
  onEvent?: (event: StreamEvent) => void,
): FlowStreamState {
  const client = useQueryClient()
  const [connected, setConnected] = useState(false)
  const [runningIds, setRunningIds] = useState<Set<string>>(() => new Set())
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  useEffect(() => {
    if (!enabled || flowId === undefined) return
    let source: EventSource | null = null
    let timer: number | undefined
    let closed = false
    let since = 0

    const dispatch = (raw: MessageEvent) => {
      let event: StreamEvent
      try {
        event = JSON.parse(raw.data) as StreamEvent
      } catch {
        return
      }
      event.type = raw.type
      if (event.seq) since = event.seq
      applyStreamEvent(client, event)
      if (event.type === 'run_started' && event.run_id) {
        setRunningIds((old) => new Set(old).add(event.run_id as string))
      } else if (event.type === 'run_finished' && event.run) {
        const id = event.run.id
        setRunningIds((old) => {
          if (!old.has(id)) return old
          const next = new Set(old)
          next.delete(id)
          return next
        })
      }
      handlerRef.current?.(event)
    }

    let stopWatchdog: (() => void) | undefined
    const open = () => {
      if (closed) return
      source = new EventSource(streamUrl(flowId, since || undefined))
      stopWatchdog?.()
      stopWatchdog = watchdog(source, () => {
        // 沒心跳：當作斷線，走 onerror 的重連路徑
        setConnected(false)
        source?.close()
        if (!closed) timer = window.setTimeout(open, RECONNECT_DELAY_MS)
      })
      source.addEventListener('open', () => setConnected(true))
      source.addEventListener('hello', (e) => {
        try {
          const data = JSON.parse((e as MessageEvent).data) as { seq?: number }
          // hello 的 seq 是伺服器認可的位置（重啟後會被夾回），一律採用
          if (typeof data.seq === 'number') since = data.seq
        } catch {
          /* ignore */
        }
      })
      for (const type of ['run_finished', 'run_started', 'run_queued', 'continuous', 'stats', 'lock', 'cleared']) {
        source.addEventListener(type, (e) => dispatch(e as MessageEvent))
      }
      source.addEventListener('bye', (e) => {
        try {
          const data = JSON.parse((e as MessageEvent).data) as { seq?: number }
          if (data.seq) since = data.seq
        } catch {
          /* ignore */
        }
        stopWatchdog?.()
        source?.close()
        // 伺服器正常結束：立刻重連，不等 5 秒。
        timer = window.setTimeout(open, 50)
      })
      source.onerror = () => {
        setConnected(false)
        stopWatchdog?.()
        source?.close()
        if (!closed) timer = window.setTimeout(open, RECONNECT_DELAY_MS)
      }
    }

    open()
    return () => {
      closed = true
      stopWatchdog?.()
      source?.close()
      window.clearTimeout(timer)
      setConnected(false)
    }
  }, [flowId, enabled, client])

  return { connected, runningIds }
}

/**
 * 只聽引擎鎖定事件的全域串流（AppShell 用）。流程串流會過濾掉沒有 flow_id 的 lock 事件，
 * 所以編輯器頁也要靠這條才能即時看到橫幅；outputs=0 避免拉到影像 payload。
 */
export function useLockEvents(enabled: boolean) {
  const client = useQueryClient()
  useEffect(() => {
    if (!enabled) return
    let source: EventSource | null = null
    let timer: number | undefined
    let closed = false
    let stopWatchdog: (() => void) | undefined
    const open = () => {
      if (closed) return
      source = new EventSource(streamUrl(null, undefined, false))
      stopWatchdog?.()
      stopWatchdog = watchdog(source, () => {
        source?.close()
        if (!closed) timer = window.setTimeout(open, RECONNECT_DELAY_MS)
      })
      source.addEventListener('lock', (e) => {
        try {
          const data = JSON.parse((e as MessageEvent).data) as { lock?: EngineLock }
          if (data.lock) client.setQueryData<EngineLock>(keys.lock, data.lock)
        } catch {
          /* ignore */
        }
      })
      source.addEventListener('bye', () => {
        stopWatchdog?.()
        source?.close()
        timer = window.setTimeout(open, 50)
      })
      source.onerror = () => {
        stopWatchdog?.()
        source?.close()
        if (!closed) timer = window.setTimeout(open, RECONNECT_DELAY_MS)
      }
    }
    open()
    return () => {
      closed = true
      stopWatchdog?.()
      source?.close()
      window.clearTimeout(timer)
    }
  }, [enabled, client])
}
