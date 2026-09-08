/**
 * 現場全螢幕看板 /board/:flowId：沒有側欄，只有大影像、大判定、這條線設定要看的那幾個數字、今日良率與變數。
 * 資料來源是 GET /flows/{id}/board（設定＋今日數字，15 秒一次），每次 run 由 SSE 即時進來，在前端依設定評估。
 * 操作站用 Edge 的 kiosk 模式開這一頁就是一個看板。
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, MonitorPlay } from 'lucide-react'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { LoadingState, ErrorState } from '@/components/ui'
import { imageUrl } from '@/lib/api'
import { evaluateValues, runToBoard, type BoardRun, type BoardValue } from '@/lib/board'
import { useFlowStream } from '@/lib/flowStream'
import { formatDateTime } from '@/lib/format'
import { useBoard } from '@/lib/queries'

function Tile({ label, value, tone, unit, big = false, testId }: { label: string; value: string; tone?: 'ok' | 'ng' | 'neutral'; unit?: string; big?: boolean; testId?: string }) {
  const ring = tone === 'ok' ? 'border-ok/70 shadow-[0_0_24px_-8px_var(--color-ok)]' : tone === 'ng' ? 'border-critical/80 shadow-[0_0_24px_-8px_var(--color-critical)]' : 'border-white/10'
  const text = tone === 'ok' ? 'text-ok' : tone === 'ng' ? 'text-critical' : 'text-white'
  return (
    <div className={`flex min-w-0 flex-col justify-between rounded-xl border-2 bg-white/5 px-4 py-3 ${ring}`} data-testid={testId}>
      <span className="truncate text-xs uppercase tracking-wide text-white/55">{label}</span>
      <span className={`mt-1 truncate font-semibold tabular-nums leading-none ${big ? 'text-5xl' : 'text-3xl'} ${text}`} title={value}>
        {value}
        {unit ? <span className="ml-1 text-base font-normal text-white/50">{unit}</span> : null}
      </span>
    </div>
  )
}

export function BoardPage() {
  const { t } = useTranslation()
  const { flowId: raw } = useParams()
  const flowId = Number(raw)
  const board = useBoard(Number.isFinite(flowId) ? flowId : null)
  const [live, setLive] = useState<{ run: BoardRun; values: BoardValue[] } | null>(null)
  const config = board.data?.config

  // 每一片由串流即時進來；設定（公差、要看哪幾個）跟著 GET 來的 config 走
  useFlowStream(Number.isFinite(flowId) ? flowId : null, true, (event) => {
    if (event.type === 'run_finished' && event.flow_id === flowId && event.run) {
      setLive({ run: runToBoard(event.run, config), values: evaluateValues(config, event.run.outputs as Record<string, unknown>) })
      void board.refetch()
    }
  })
  useEffect(() => {
    document.title = board.data?.flow.title ? `${board.data.flow.title} · VisionSequence` : 'VisionSequence'
    return () => { document.title = 'VisionSequence' }
  }, [board.data?.flow.title])

  const run = live?.run ?? board.data?.run ?? null
  const values = live?.values ?? board.data?.values ?? []
  const counts = board.data?.counts ?? null
  const variables = board.data?.variables ?? {}
  const verdictTone = run ? (run.status === 'ok' ? 'ok' : run.status === 'ng' ? 'ng' : 'neutral') : 'neutral'
  const overlays = useMemo(() => run?.overlays ?? [], [run])

  if (board.isPending) return <div className="flex h-screen items-center justify-center bg-black text-white"><LoadingState /></div>
  if (board.isError) return <div className="flex h-screen items-center justify-center bg-black text-white"><ErrorState error={board.error} onRetry={() => void board.refetch()} /></div>

  return (
    <div className="flex h-screen flex-col bg-black text-white" data-testid="board-page">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-white/10 px-5 py-3">
        <Link to="/" className="flex items-center gap-1 text-xs text-white/50 hover:text-white" data-testid="board-exit"><ArrowLeft size={13} /> {t('board.exit')}</Link>
        <h1 className="truncate text-2xl font-semibold tracking-tight" data-testid="board-title">{board.data?.flow.title}</h1>
        {counts ? (
          <div className="ml-auto flex items-center gap-4 text-sm tabular-nums" data-testid="board-counts">
            <span className="text-white/50">{t('board.today')}</span>
            <span>{t('board.total')} <b>{counts.total}</b></span>
            <span className="text-ok">{t('board.ok')} <b>{counts.ok}</b></span>
            <span className="text-critical">{t('board.ng')} <b>{counts.ng}</b></span>
            <span>{t('board.yield')} <b>{counts.yield === null ? '—' : `${counts.yield}%`}</b></span>
          </div>
        ) : null}
      </header>
      <main className="grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,30%)]">
        <section className="relative min-h-[40vh] overflow-hidden rounded-xl border border-white/10 bg-viewer">
          {run?.image ? (
            <ImageViewer className="h-full w-full" toolbar={false} src={imageUrl(run.image.ref, 1920)} imageWidth={run.image.width} imageHeight={run.image.height} overlays={overlays} stateKey={`board:${flowId}`} />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-white/60">
              <MonitorPlay size={40} className="text-brand" aria-hidden />
              <p className="flex items-center gap-2 text-sm"><span className="size-2 animate-pulse rounded-full bg-brand" />{t('board.waiting')}</p>
            </div>
          )}
          {run && config?.show_verdict !== false ? (
            <div className={`pointer-events-none absolute left-4 top-4 rounded-2xl border-4 px-8 py-4 text-6xl font-black tracking-widest backdrop-blur ${verdictTone === 'ok' ? 'border-ok bg-ok/20 text-ok' : verdictTone === 'ng' ? 'border-critical bg-critical/20 text-critical' : 'border-white/40 bg-white/10 text-white'}`} data-testid="board-verdict">
              {run.verdict}
              {run.label ? <span className="ml-3 align-middle text-xl font-medium tracking-normal opacity-80">{run.label}</span> : null}
            </div>
          ) : null}
        </section>
        <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          {values.length ? (
            <div className="grid grid-cols-2 gap-3" data-testid="board-values">
              {values.map((v) => (
                <Tile key={v.key} label={v.label} value={v.present ? v.text : '—'} unit={v.unit} tone={v.ok === null ? 'neutral' : v.ok ? 'ok' : 'ng'} big={values.length <= 2} testId={`board-value-${v.key}`} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-white/50">{t('board.noValues')}</p>
          )}
          {Object.keys(variables).length ? (
            <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm" data-testid="board-variables">
              <p className="mb-1 text-xs uppercase tracking-wide text-white/55">{t('board.variables')}</p>
              {Object.entries(variables).map(([k, v]) => (
                <p key={k} className="flex justify-between gap-3 tabular-nums"><span className="font-mono text-white/70">{k}</span><span className="truncate">{typeof v === 'object' && v ? JSON.stringify(v) : String(v ?? '')}</span></p>
              ))}
            </div>
          ) : null}
          {run ? (
            <p className="mt-auto text-xs text-white/45 tabular-nums" data-testid="board-last">
              {t('board.lastRun')} {formatDateTime(new Date(run.started_at * 1000).toISOString())} · {Math.round(run.duration_ms)} ms{run.recipe ? ` · ${run.recipe}` : ''}
              {run.error ? <span className="ml-2 text-critical">{run.error}</span> : null}
            </p>
          ) : null}
        </aside>
      </main>
    </div>
  )
}

export default BoardPage
