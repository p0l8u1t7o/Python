/** SSE 登記表：一個頻道一條連線、outputs 升級重開、鎖定訂閱者搭車、歸零延遲關閉、伺服端拒絕時探 /auth/me、分頁隱藏關閉／回來重開、flow_updated 讓列表失效。 */
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { ...actual.api, get: vi.fn(async () => ({})) }, authToken: () => 'test-token', apiKey: () => '' }
})

import { api } from '@/lib/api'
import { _channelsForTests, _presenceForTests, _resetStreamsForTests, HIDDEN_GRACE_MS, HIDDEN_RESYNC_MS, LINGER_MS, RECONNECT_DELAY_MS, setStreamClient, subscribeStream } from '@/lib/flowStream'
import { keys } from '@/lib/queries'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2
  readyState = 0
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  listeners = new Map<string, ((e: MessageEvent) => void)[]>()
  closed = false
  constructor(public url: string) {
    FakeEventSource.instances.push(this)
  }
  addEventListener(type: string, listener: (e: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }
  close() {
    this.closed = true
    this.readyState = 2
  }
  emit(type: string, data: unknown) {
    const event = { type, data: JSON.stringify(data) } as MessageEvent
    for (const l of this.listeners.get(type) ?? []) l(event)
  }
  open() {
    this.readyState = 1
    for (const l of this.listeners.get('open') ?? []) l({ type: 'open' } as MessageEvent)
  }
  fail(refused: boolean) {
    this.readyState = refused ? 2 : 0
    this.onerror?.()
  }
}

const live = () => FakeEventSource.instances.filter((s) => !s.closed)

describe('stream registry', () => {
  let client: QueryClient
  beforeEach(() => {
    vi.useFakeTimers()
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
    _resetStreamsForTests()
    client = new QueryClient()
    setStreamClient(client)
    vi.mocked(api.get).mockClear()
  })
  afterEach(() => {
    _resetStreamsForTests()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('shares one connection per channel and upgrades outputs with since', () => {
    const a = subscribeStream(null, { outputs: false })
    expect(live().length).toBe(1)
    expect(live()[0].url).toContain('outputs=0')
    live()[0].open()
    live()[0].emit('hello', { seq: 42 })
    const b = subscribeStream(null, { outputs: true })
    expect(live().length).toBe(1)
    expect(live()[0].url).not.toContain('outputs=0')
    expect(live()[0].url).toContain('since=42')
    expect(_channelsForTests()).toEqual([{ key: 'global', open: true, outputs: true, subs: 2, since: 42 }])
    b()
    a()
    expect(live().length).toBe(1)  // linger
    vi.advanceTimersByTime(LINGER_MS + 10)
    expect(live().length).toBe(0)
    expect(_channelsForTests()).toEqual([])
  })

  it('lock-only subscribers ride an existing flow channel and only open global when nothing else is open', () => {
    const lock = subscribeStream(null, { outputs: false, lockOnly: true })
    expect(_presenceForTests()).toBe(1)
    expect(live().map((s) => s.url)).toEqual([expect.stringContaining('/vision/events')])
    const flow = subscribeStream(7, { outputs: true })
    expect(live().filter((s) => s.url.includes('/flows/7/stream')).length).toBe(1)
    vi.advanceTimersByTime(LINGER_MS + 10)
    expect(live().length).toBe(1)  // global 讓位給流程頻道
    expect(live()[0].url).toContain('/flows/7/stream')
    // lock 事件從流程頻道進來也會寫快取
    live()[0].emit('lock', { lock: { locked: true, holder: 'integrator', reason: '', locked_at: null, expires_at: null } })
    expect(client.getQueryData(keys.lock)).toMatchObject({ locked: true })
    flow()
    vi.advanceTimersByTime(LINGER_MS + 10)
    expect(live().length).toBe(1)
    expect(live()[0].url).toContain('/vision/events')  // 又回到全域
    lock()
    vi.advanceTimersByTime(LINGER_MS + 10)
    expect(live().length).toBe(0)
  })

  it('reconnects after bye at once, after errors later, and probes the session when refused', () => {
    const state: boolean[] = []
    const off = subscribeStream(3, { outputs: true }, { onState: (c) => state.push(c) })
    const first = live()[0]
    first.open()
    first.emit('bye', { seq: 9 })
    vi.advanceTimersByTime(60)
    expect(live().length).toBe(1)
    expect(live()[0]).not.toBe(first)
    expect(live()[0].url).toContain('since=9')
    expect(state).toEqual([false, true])  // bye 不算斷線
    live()[0].fail(false)  // 網路斷：5 秒後重連、不探 session
    expect(state.at(-1)).toBe(false)
    expect(api.get).not.toHaveBeenCalled()
    vi.advanceTimersByTime(RECONNECT_DELAY_MS + 10)
    expect(live().length).toBe(1)
    live()[0].fail(true)  // 伺服端拒絕：探 /auth/me
    expect(api.get).toHaveBeenCalledWith('/auth/me')
    off()
  })

  it('closes while the tab is hidden and resyncs after a long absence', () => {
    const off = subscribeStream(null, { outputs: true })
    live()[0].open()
    live()[0].emit('hello', { seq: 5 })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
    document.dispatchEvent(new Event('visibilitychange'))
    vi.advanceTimersByTime(HIDDEN_GRACE_MS + 10)
    expect(live().length).toBe(0)
    vi.advanceTimersByTime(HIDDEN_RESYNC_MS + 10)
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(live().length).toBe(1)
    expect(live()[0].url).not.toContain('since=')  // 太久：不重播
    expect(invalidate).toHaveBeenCalledWith({ queryKey: keys.flows })
    off()
  })

  it('dispatches events to subscribers and applies flow_updated to the list cache', () => {
    const seen: string[] = []
    const off = subscribeStream(null, { outputs: true }, { onEvent: (e) => seen.push(e.type) })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    live()[0].emit('flow_updated', { flow_id: 1, version: 4, by: 'wang' })
    expect(seen).toEqual(['flow_updated'])
    expect(invalidate).toHaveBeenCalledWith({ queryKey: keys.flows })
    off()
  })

  it('does not let a trimmed run_finished overwrite the full run already cached', () => {
    const off = subscribeStream(1, { outputs: true }, { onEvent: () => undefined })
    const node = { status: 'ok', duration_ms: 1, message: '', branch: null, outputs: {}, overlays: [], overlay_on: null, detail: {}, logs: [] }
    const base = { flow_id: 1, flow_version: 1, trigger: 'tcp', status: 'ok', started_at: 1, finished_at: 2, duration_ms: 1, error: '', outputs: {} }
    const full = { ...base, id: 'r1', nodes: { src: { ...node, outputs: { image: { ref: 'r1:src:image', width: 4, height: 3 } } } } }
    const lean = { ...base, id: 'r1', nodes: { src: node }, nodes_trimmed: true }
    live()[0].emit('run_finished', { flow_id: 1, run: full })
    live()[0].emit('run_finished', { flow_id: 1, run: lean })
    const cached = client.getQueryData<{ items: { id: string; nodes_trimmed?: boolean; nodes: Record<string, { outputs: Record<string, unknown> }> }[] }>(keys.recent(1))
    expect(cached?.items).toHaveLength(1)
    expect(cached?.items[0].nodes_trimmed).toBeUndefined()
    expect(cached?.items[0].nodes.src.outputs.image).toBeDefined()
    // 反過來：只有瘦身版時照樣進快取，之後完整版來了要換成完整版
    live()[0].emit('run_finished', { flow_id: 1, run: { ...lean, id: 'r2' } })
    live()[0].emit('run_finished', { flow_id: 1, run: { ...full, id: 'r2' } })
    const again = client.getQueryData<{ items: { id: string; nodes_trimmed?: boolean }[] }>(keys.recent(1))
    expect(again?.items.map((r) => r.id)).toEqual(['r2', 'r1'])
    expect(again?.items[0].nodes_trimmed).toBeUndefined()
    off()
  })
})
