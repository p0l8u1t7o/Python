/**
 * 整合追蹤（命令與結果）：每個整合頁下方都放一個，開著就會即時列出這個介面收到的命令與回覆，
 * 便於除錯。資料來自 `GET /vision/integration/trace?channel=`（後端只在有人看時記錄，錯誤永遠記）。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, Pause, Play, Trash2 } from 'lucide-react'

import { Badge, Button, Card, CardBody, CardHeader } from '@/components/ui'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import type { TraceEntry } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

const MAX_ROWS = 300

function time(ts: number): string {
  const d = new Date(ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

function Row({ entry }: { entry: TraceEntry }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const detail = entry.detail === null || entry.detail === undefined ? '' : JSON.stringify(entry.detail, null, 2)
  return (
    <div className="border-b border-line last:border-0">
      <button type="button" onClick={() => setOpen((v) => !v)} disabled={!detail}
        className={`flex w-full items-start gap-2 px-3 py-1.5 text-left font-mono text-[11px] leading-relaxed ${detail ? 'hover:bg-surface-muted' : 'cursor-default'}`}>
        <span className="w-4 shrink-0 pt-0.5 text-subtle">{detail ? (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : null}</span>
        <span className="tnum shrink-0 text-subtle">{time(entry.ts)}</span>
        <span className={`shrink-0 ${entry.direction === 'out' ? 'text-brand' : 'text-info'}`}>{entry.direction === 'out' ? '←' : '→'}</span>
        {entry.name ? <span className="shrink-0 max-w-[9rem] truncate text-muted">{entry.name}</span> : null}
        <span className={`min-w-0 flex-1 break-all ${entry.ok ? '' : 'text-critical'}`}>{entry.summary}</span>
        {entry.ms !== null && entry.ms !== undefined ? <span className="tnum shrink-0 text-subtle">{entry.ms} ms</span> : null}
        {!entry.ok ? <Badge tone="critical">{t('integration.trace.failed')}</Badge> : null}
      </button>
      {open && detail ? <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all bg-surface-muted px-3 py-2 font-mono text-[11px]">{detail}</pre> : null}
    </div>
  )
}

export function TraceLog({ channel, title, description }: { channel: string; title?: string; description?: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const [entries, setEntries] = useState<TraceEntry[]>([])
  const [live, setLive] = useState(true)
  const [failedOnly, setFailedOnly] = useState(false)
  const since = useRef(0)
  const box = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    since.current = 0
    setEntries([])
  }, [channel])

  useEffect(() => {
    if (!live) return
    let stop = false
    const tick = async () => {
      try {
        const r = await api.get<{ items: TraceEntry[]; seq: number }>(`/vision/integration/trace?channel=${encodeURIComponent(channel)}&since=${since.current}&limit=200`)
        if (stop) return
        if (r.items.length) {
          since.current = r.seq
          setEntries((prev) => [...prev, ...r.items].slice(-MAX_ROWS))
        }
      } catch {
        /* 輪詢失敗就下次再試（不打擾使用者） */
      }
    }
    void tick()
    const timer = window.setInterval(() => void tick(), 1500)
    return () => {
      stop = true
      window.clearInterval(timer)
    }
  }, [channel, live])

  useEffect(() => {
    const el = box.current
    if (el && live) el.scrollTop = el.scrollHeight // jsdom 沒有 scrollTo
  }, [entries, live])

  const rows = useMemo(() => (failedOnly ? entries.filter((e) => !e.ok) : entries), [entries, failedOnly])

  async function clear() {
    try {
      await api.delete(`/vision/integration/trace?channel=${encodeURIComponent(channel)}`)
      since.current = 0
      setEntries([])
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Card className="overflow-hidden" testId={`trace-${channel}`}>
      <CardHeader
        title={title || t('integration.trace.title')}
        description={description || t('integration.trace.hint')}
        actions={
          <>
            <Button size="xs" active={failedOnly} onClick={() => setFailedOnly((v) => !v)}>{t('integration.trace.failedOnly')}</Button>
            <Button size="xs" icon={live ? <Pause size={12} /> : <Play size={12} />} onClick={() => setLive((v) => !v)}>
              {live ? t('integration.trace.pause') : t('integration.trace.resume')}
            </Button>
            <Button size="xs" icon={<Trash2 size={12} />} onClick={() => void clear()}>{t('common.clear')}</Button>
          </>
        }
      />
      <CardBody className="!p-0">
        <div ref={box} className="max-h-72 overflow-auto" data-testid={`trace-rows-${channel}`}>
          {rows.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-subtle">{live ? t('integration.trace.empty') : t('integration.trace.paused')}</p>
          ) : (
            rows.map((entry) => <Row key={entry.seq} entry={entry} />)
          )}
        </div>
      </CardBody>
    </Card>
  )
}
