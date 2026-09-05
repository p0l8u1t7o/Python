/** 整合 ▸ 事件監看：訂閱 /vision/events（SSE），即時列出每一次執行。 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Pause, Play, Trash2 } from 'lucide-react'

import { Badge, Button, Card, CardHeader, StatusBadge } from '@/components/ui'
import { subscribeStream, type StreamEvent } from '@/lib/flowStream'
import { useFlows } from '@/lib/queries'

interface WatchedEvent {
  seq: number
  time: string
  type: string
  flow: string
  status: string
  ms: number | null
  detail: string
}

const MAX_EVENTS = 200

function EventsSection() {
  const { t } = useTranslation()
  const flows = useFlows()
  const [events, setEvents] = useState<WatchedEvent[]>([])
  const [paused, setPaused] = useState(false)
  const [connected, setConnected] = useState(false)
  const pausedRef = useRef(paused)
  pausedRef.current = paused
  const counter = useRef(0)
  const names = useMemo(() => new Map((flows.data?.items ?? []).map((f) => [f.id, f.name])), [flows.data])
  const namesRef = useRef(names)
  namesRef.current = names

  useEffect(() => {
    // 走共用的登記表：與總覽頁同一條全域連線，不另開
    return subscribeStream(null, { outputs: true }, {
      onState: setConnected,
      onEvent: (event: StreamEvent) => {
        if (pausedRef.current) return
        const data = event as unknown as Record<string, unknown>
        const type = event.type
        const run = event.run as { status?: string; duration_ms?: number; outputs?: Record<string, unknown>; error?: string } | undefined
        const flowId = typeof event.flow_id === 'number' ? event.flow_id : undefined
        const lock = event.lock as { locked?: boolean; holder?: string } | undefined
        const item: WatchedEvent = {
          seq: (counter.current += 1),
          time: new Date().toLocaleTimeString(),
          type,
          flow: flowId !== undefined ? namesRef.current.get(flowId) ?? `#${flowId}` : '',
          status: run?.status ?? (type === 'continuous' ? (event.running ? 'running' : 'idle') : ''),
          ms: run?.duration_ms ?? null,
          detail: run ? run.error || JSON.stringify(run.outputs ?? {}).slice(0, 120) : lock ? `${lock.locked ? 'locked' : 'unlocked'} ${lock.holder ?? ''}` : JSON.stringify({ ...data, run: undefined }).slice(0, 120),
        }
        setEvents((old) => [item, ...old].slice(0, MAX_EVENTS))
      },
    })
  }, [])

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title={t('integration.tabs.events')}
        description={t('integration.events.hint')}
        actions={
          <>
            <Badge tone={connected ? 'ok' : 'neutral'}>{connected ? t('integration.events.connected') : t('integration.events.disconnected')}</Badge>
            <Button size="sm" icon={paused ? <Play size={13} /> : <Pause size={13} />} onClick={() => setPaused((v) => !v)} data-testid="events-pause">{paused ? t('integration.events.resume') : t('integration.events.pause')}</Button>
            <Button size="sm" icon={<Trash2 size={13} />} onClick={() => setEvents([])}>{t('integration.events.clear')}</Button>
          </>
        }
      />
      <div className="max-h-[60vh] overflow-auto">
        <table className="w-full text-xs" data-testid="events-table">
          <thead className="sticky top-0 bg-surface-muted text-[10px] uppercase text-subtle">
            <tr>
              <th className="px-3 py-1.5 text-left font-medium">{t('integration.events.cols.time')}</th>
              <th className="px-3 py-1.5 text-left font-medium">{t('integration.events.cols.type')}</th>
              <th className="px-3 py-1.5 text-left font-medium">{t('integration.events.cols.flow')}</th>
              <th className="px-3 py-1.5 text-left font-medium">{t('integration.events.cols.status')}</th>
              <th className="px-3 py-1.5 text-right font-medium">{t('integration.events.cols.ms')}</th>
              <th className="px-3 py-1.5 text-left font-medium">{t('integration.events.cols.detail')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {events.length === 0 ? <tr><td colSpan={6} className="px-3 py-8 text-center text-muted">{t('integration.events.empty')}</td></tr> : null}
            {events.map((e) => (
              <tr key={e.seq} data-testid="event-row">
                <td className="tnum whitespace-nowrap px-3 py-1">{e.time}</td>
                <td className="px-3 py-1 font-mono">{e.type}</td>
                <td className="max-w-[160px] truncate px-3 py-1">{e.flow}</td>
                <td className="px-3 py-1">{e.status ? <StatusBadge status={e.status} /> : null}</td>
                <td className="tnum px-3 py-1 text-right">{e.ms === null ? '' : Math.round(e.ms)}</td>
                <td className="max-w-[360px] truncate px-3 py-1 font-mono text-[10px] text-muted" title={e.detail}>{e.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}


export function EventsPage() {
  return (
    <div className="space-y-4">
      <EventsSection />
      
    </div>
  )
}
