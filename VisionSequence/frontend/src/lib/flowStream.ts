/**
 * SSE：事件串流的連線登記表（registry）——同一個頻道（全域或某條流程）不管幾個元件訂閱，整個分頁只開一條 EventSource，
 * 事件直接寫進 TanStack Query 快取，再分派給訂閱者。多台客戶端電腦、每台好幾個分頁時，這決定伺服端要撐幾條串流
 * （HTTP/1.1 每來源只有 6 條連線；伺服端有 VISION_SSE_MAX_STREAMS 上限）。
 *
 * - `run_finished`：run 塞到 ['recent', flowId]（最多 8 筆、新在前），同時更新 flow 的 stats。
 * - `stats` / `continuous`：更新 flow 快取的 stats 與 continuous 旗標。
 * - `lock`：引擎鎖定狀態，寫進 ['engine-lock']（AuthProvider 與橫幅讀這個）。任何頻道都會收到 lock（伺服端不過濾沒有 flow_id 的事件）。
 * - `cleared`：重置（DELETE recent）：清空 recent 與 stats；編輯器另外靠 onEvent 清畫面。
 * - `flow_updated`：別人存了流程：列表快取失效，編輯器自己決定要不要重載。
 * - `bye`：伺服器 55 秒主動關閉，帶 seq 重連補齊漏掉的事件。
 * - `ping`：伺服器每 15 秒的心跳；超過 WATCHDOG_MS 沒收到任何訊息就當斷線（經 proxy 時後端死掉
 *   客戶端連線不一定會被關），主動關閉並重連。
 *
 * 規則：
 * 1. 一個 key（'global' 或 'flow:<id>'）一條連線；outputs 取訂閱者的聯集，從 0 升到 1 時帶著 since 立刻重開。
 * 2. 「只要鎖定事件」的訂閱者（AppShell）不開自己的連線：有任何流程頻道開著就搭那條；都沒有才開 global?outputs=0。
 * 3. 訂閱數歸零延遲 LINGER_MS 再關（StrictMode 雙掛載、換頁時同一個頻道立刻又被訂閱）。
 * 4. 分頁隱藏超過 HIDDEN_GRACE_MS 關掉所有連線（保留 since）；回到前景立刻重開，離開超過 HIDDEN_RESYNC_MS 就不帶 since 並讓相關查詢失效。
 * 5. 連線被伺服端拒絕（readyState=CLOSED：401／503／代理 5xx）時，節流探一次 /auth/me——401 會走 api.ts 的 onSessionExpired 導回登入。
 */
import { useEffect, useRef, useState } from 'react'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'

import { api, apiKey, authToken, onSessionExpired, streamUrl } from './api'
import { emptyStats, keys, type RecentRuns } from './queries'
import type { EngineLock, Flow, FlowStats, Page, RunReport } from './types'

export const RECONNECT_DELAY_MS = 5000
/** 伺服器心跳 15 秒、串流最長 55 秒；超過這個時間完全沒訊息就是連線死了 */
export const WATCHDOG_MS = 40_000
/** 訂閱歸零後多久才真的關連線 */
export const LINGER_MS = 1000
/** 分頁隱藏多久後釋放連線 */
export const HIDDEN_GRACE_MS = 15_000
/** 離開超過這麼久回來就不重播事件，改讓查詢重抓 */
export const HIDDEN_RESYNC_MS = 60_000
const PROBE_THROTTLE_MS = 10_000
const KEEP_RECENT = 8
export const EVENT_TYPES = ['run_finished', 'run_started', 'run_queued', 'continuous', 'stats', 'lock', 'cleared', 'flow_updated'] as const

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
  /** type=flow_updated：誰存了第幾版 */
  version?: number
  by?: string
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
        // 瘦身版（沒有輸出）不能蓋掉快取裡同一個 run 的完整版：編輯器靠完整版顯示影像
        const existing = (old?.items ?? []).find((r) => r.id === run.id)
        const kept = run.nodes_trimmed && existing && !existing.nodes_trimmed ? existing : run
        const items = [kept, ...(old?.items ?? []).filter((r) => r.id !== run.id)].slice(0, KEEP_RECENT)
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
    case 'flow_updated':
      // 別人存了：列表重抓；流程詳情交給編輯器自己判斷（未儲存的畫布不能被重載沖掉）
      void client.invalidateQueries({ queryKey: keys.flows })
      break
    default:
      break
  }
}

// ---------------------------------------------------------------------------
// 連線登記表
// ---------------------------------------------------------------------------
interface Subscriber {
  outputs: boolean
  onEvent?: (event: StreamEvent) => void
  onState?: (connected: boolean) => void
}

interface Channel {
  key: string
  flowId: number | null
  subs: Set<Subscriber>
  source: EventSource | null
  outputs: boolean
  since: number
  connected: boolean
  /** 上一次是斷線（不是伺服器正常的 bye）：重新連上後補抓鎖定狀態 */
  errored: boolean
  timer?: number
  linger?: number
  stopWatchdog?: () => void
}

const channels = new Map<string, Channel>()
/** 只要求「至少一條連線」的訂閱者數（鎖定橫幅） */
let presence = 0
let client: QueryClient | null = null
let hiddenAt = 0
let hiddenClosed = false
let hiddenTimer: number | undefined
let lastProbe = 0

/** 給登記表用的 QueryClient（hooks 會自動帶入；main.tsx 也可先設） */
export function setStreamClient(next: QueryClient): void {
  client = next
}

function keyOf(flowId: number | null): string {
  return flowId === null ? 'global' : `flow:${flowId}`
}

function anyFlowChannelActive(): boolean {
  for (const ch of channels.values()) if (ch.flowId !== null && ch.subs.size > 0) return true
  return false
}

function ensureChannel(flowId: number | null): Channel {
  const key = keyOf(flowId)
  let ch = channels.get(key)
  if (!ch) {
    ch = { key, flowId, subs: new Set(), source: null, outputs: false, since: 0, connected: false, errored: false }
    channels.set(key, ch)
  }
  return ch
}

function setConnected(ch: Channel, value: boolean) {
  if (ch.connected === value) return
  ch.connected = value
  for (const s of ch.subs) s.onState?.(value)
  if (value && ch.errored) {
    ch.errored = false
    // 斷線期間漏掉的鎖定事件靠這一次補回來（正常的 55 秒重連不需要）
    void client?.invalidateQueries({ queryKey: keys.lock })
  }
}

function closeSource(ch: Channel) {
  ch.stopWatchdog?.()
  ch.stopWatchdog = undefined
  ch.source?.close()
  ch.source = null
  window.clearTimeout(ch.timer)
  ch.timer = undefined
  setConnected(ch, false)
}

function scheduleReopen(ch: Channel, ms: number) {
  window.clearTimeout(ch.timer)
  ch.timer = window.setTimeout(() => {
    ch.timer = undefined
    reconcile()
  }, ms)
}

function probeSession() {
  const now = Date.now()
  if (now - lastProbe < PROBE_THROTTLE_MS) return
  lastProbe = now
  // 401 會走 api.ts 的 onSessionExpired（清 token、導回登入、關掉所有串流）；其他錯誤不管，照常重連
  void api.get('/auth/me').catch(() => {})
}

function dispatch(ch: Channel, raw: MessageEvent) {
  let event: StreamEvent
  try {
    event = JSON.parse(raw.data) as StreamEvent
  } catch {
    return
  }
  event.type = raw.type
  if (event.seq) ch.since = event.seq
  if (client) applyStreamEvent(client, event)
  for (const s of ch.subs) s.onEvent?.(event)
}

function open(ch: Channel, outputs: boolean) {
  if (!authToken() && !apiKey()) return
  ch.outputs = outputs
  const source = new EventSource(streamUrl(ch.flowId, ch.since || undefined, outputs))
  ch.source = source
  ch.stopWatchdog?.()
  ch.stopWatchdog = watchdog(source, () => {
    // 沒心跳：當作斷線
    ch.errored = true
    closeSource(ch)
    scheduleReopen(ch, RECONNECT_DELAY_MS)
  })
  source.addEventListener('open', () => setConnected(ch, true))
  source.addEventListener('hello', (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data) as { seq?: number }
      // hello 的 seq 是伺服器認可的位置（重啟後會被夾回），一律採用
      if (typeof data.seq === 'number') ch.since = data.seq
    } catch {
      /* ignore */
    }
  })
  for (const type of EVENT_TYPES) source.addEventListener(type, (e) => dispatch(ch, e as MessageEvent))
  source.addEventListener('bye', (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data) as { seq?: number }
      if (data.seq) ch.since = data.seq
    } catch {
      /* ignore */
    }
    if (ch.source !== source) return
    ch.stopWatchdog?.()
    source.close()
    ch.source = null
    // 伺服器正常結束：立刻重連，不等 5 秒（connected 狀態不變，橫幅不會閃）
    scheduleReopen(ch, 50)
  })
  source.onerror = () => {
    if (ch.source !== source) return
    // CLOSED＝伺服端拒絕（401／503／代理 5xx），瀏覽器不會自己重試；CONNECTING＝網路斷，瀏覽器會重試但我們統一自己管
    const refused = source.readyState === EventSource.CLOSED
    ch.errored = true
    closeSource(ch)
    if (refused) probeSession()
    scheduleReopen(ch, RECONNECT_DELAY_MS)
  }
}

function wantedOutputs(ch: Channel): boolean {
  for (const s of ch.subs) if (s.outputs) return true
  return false
}

function needed(ch: Channel): boolean {
  if (ch.flowId === null) return ch.subs.size > 0 || (presence > 0 && !anyFlowChannelActive())
  return ch.subs.size > 0
}

/** 依目前的訂閱決定每個頻道開或關；所有變動都經過這裡。 */
function reconcile() {
  if (hiddenClosed) return
  if (presence > 0 && !anyFlowChannelActive()) ensureChannel(null)
  for (const [key, ch] of [...channels.entries()]) {
    if (needed(ch)) {
      if (ch.linger) {
        window.clearTimeout(ch.linger)
        ch.linger = undefined
      }
      const outputs = wantedOutputs(ch)
      if (!ch.source) {
        if (!ch.timer) open(ch, outputs)
      } else if (outputs && !ch.outputs) {
        // 有人要影像了：帶著 since 重開，不漏事件
        closeSource(ch)
        open(ch, outputs)
      }
    } else if (!ch.linger) {
      ch.linger = window.setTimeout(() => {
        ch.linger = undefined
        if (needed(ch)) return
        closeSource(ch)
        if (ch.subs.size === 0) channels.delete(key)
        reconcile()
      }, LINGER_MS)
    }
  }
}

function closeAll(keepSince = true) {
  for (const ch of channels.values()) {
    if (!keepSince) ch.since = 0
    closeSource(ch)
    window.clearTimeout(ch.linger)
    ch.linger = undefined
  }
}

/**
 * 訂閱一個頻道。flowId=null 是全域事件流；`lockOnly` 只保證「至少有一條連線」讓鎖定事件進得來，不開自己的連線。
 * 回傳取消訂閱。
 */
export function subscribeStream(
  flowId: number | null,
  opts: { outputs: boolean; lockOnly?: boolean },
  sub: { onEvent?: (event: StreamEvent) => void; onState?: (connected: boolean) => void } = {},
): () => void {
  if (opts.lockOnly) {
    presence += 1
    reconcile()
    return () => {
      presence = Math.max(0, presence - 1)
      reconcile()
    }
  }
  const ch = ensureChannel(flowId)
  const s: Subscriber = { outputs: opts.outputs, onEvent: sub.onEvent, onState: sub.onState }
  ch.subs.add(s)
  sub.onState?.(ch.connected)
  reconcile()
  return () => {
    ch.subs.delete(s)
    reconcile()
  }
}

function onVisibilityChange() {
  if (document.hidden) {
    hiddenAt = Date.now()
    window.clearTimeout(hiddenTimer)
    hiddenTimer = window.setTimeout(() => {
      if (!document.hidden) return
      hiddenClosed = true
      closeAll(true)
    }, HIDDEN_GRACE_MS)
    return
  }
  window.clearTimeout(hiddenTimer)
  const away = hiddenAt ? Date.now() - hiddenAt : 0
  hiddenAt = 0
  if (!hiddenClosed) return
  hiddenClosed = false
  if (away > HIDDEN_RESYNC_MS) {
    // 太久沒看：不重播一堆帶影像的事件，改讓查詢自己重抓
    for (const ch of channels.values()) ch.since = 0
    if (client) {
      void client.invalidateQueries({ queryKey: keys.flows })
      void client.invalidateQueries({ queryKey: keys.capacity })
      void client.invalidateQueries({ queryKey: keys.lock })
    }
  }
  reconcile()
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', onVisibilityChange)
  onSessionExpired(() => closeAll(true))
}

/** 測試用：清掉所有頻道與狀態。 */
export function _resetStreamsForTests(): void {
  for (const ch of channels.values()) {
    closeSource(ch)
    window.clearTimeout(ch.linger)
  }
  channels.clear()
  presence = 0
  hiddenAt = 0
  hiddenClosed = false
  window.clearTimeout(hiddenTimer)
  lastProbe = 0
}

/** 測試用：目前的頻道快照。 */
export function _channelsForTests(): { key: string; open: boolean; outputs: boolean; subs: number; since: number }[] {
  return [...channels.values()].map((ch) => ({ key: ch.key, open: ch.source !== null, outputs: ch.outputs, subs: ch.subs.size, since: ch.since }))
}

export function _presenceForTests(): number {
  return presence
}

// ---------------------------------------------------------------------------
// hooks
// ---------------------------------------------------------------------------
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
  const queryClient = useQueryClient()
  const [connected, setConnectedState] = useState(false)
  const [runningIds, setRunningIds] = useState<Set<string>>(() => new Set())
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  useEffect(() => {
    if (!enabled || flowId === undefined) return
    setStreamClient(queryClient)
    const unsubscribe = subscribeStream(flowId, { outputs: true }, {
      onState: setConnectedState,
      onEvent: (event) => {
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
      },
    })
    return () => {
      unsubscribe()
      setConnectedState(false)
    }
  }, [flowId, enabled, queryClient])

  return { connected, runningIds }
}

/** 只要鎖定事件（AppShell 的橫幅）：搭現有的連線，沒有才開一條不帶影像的全域串流。 */
export function useLockEvents(enabled: boolean) {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!enabled) return
    setStreamClient(queryClient)
    return subscribeStream(null, { outputs: false, lockOnly: true })
  }, [enabled, queryClient])
}
