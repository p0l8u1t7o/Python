/**
 * Station view `/station`: the screen a shop-floor operator actually stands in front of.
 *
 * Deliberately not the engineer UI. No canvas, no toolbox, no sidebar — a verdict you can read from
 * two metres away, today's yield, the last few parts, start/stop, and change-over. Everything an
 * operator is allowed to do (see `Principal.role`), nothing they are not.
 *
 * The station remembers which flow it is responsible for (`vs.station.flow`), so the machine comes
 * back to the same line after a reboot; a dropdown switches it when one person watches several.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { CircleDot, Maximize2, Pause, Play, Settings2 } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useFlowStream } from '@/lib/flowStream'
import { firstImageOutput, lastImage } from '@/lib/runImages'
import { keys, useFlow, useFlowStats, useFlows, useRecipes } from '@/lib/queries'
import { Badge, Button, LoadingState, Select } from '@/components/ui'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import type { RunReport } from '@/lib/types'

const FLOW_KEY = 'vs.station.flow'
const RECENT = 12

function storedFlow(): number | null {
  try {
    const raw = localStorage.getItem(FLOW_KEY)
    return raw ? Number(raw) || null : null
  } catch {
    return null
  }
}

/** OK green / NG amber / failed red — the same three the rest of the product uses. */
function verdictTone(status: string | undefined) {
  if (status === 'ok') return { bg: 'bg-ok', text: 'text-ok' }
  if (status === 'ng') return { bg: 'bg-warning', text: 'text-warning' }
  return { bg: 'bg-critical', text: 'text-critical' }
}

export function StationPage() {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const flows = useFlows()
  const urlFlow = Number(params.get('flow')) || null
  const [flowId, setFlowId] = useState<number | null>(urlFlow ?? storedFlow())
  const [recent, setRecent] = useState<RunReport[]>([])
  const [current, setCurrent] = useState<RunReport | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  // 沒有選過流程時，用第一個啟用中的
  const items = flows.data?.items ?? []
  const effectiveId = flowId ?? items.find((f) => f.is_enabled)?.id ?? items[0]?.id ?? null
  useEffect(() => {
    if (effectiveId === null) return
    try {
      localStorage.setItem(FLOW_KEY, String(effectiveId))
    } catch { /* 無痕視窗：記不住就算了 */ }
  }, [effectiveId])

  const flow = useFlow(effectiveId)
  const stats = useFlowStats(effectiveId, 24)
  const recipes = useRecipes(effectiveId)

  useFlowStream(effectiveId, effectiveId !== null, (event) => {
    if (event.type === 'run_finished' && event.run) {
      setCurrent(event.run)
      setRecent((prev) => [event.run as RunReport, ...prev].slice(0, RECENT))
    }
  })

  // 開機或換線時，先把最近幾次補上，畫面不會是空的
  useEffect(() => {
    if (effectiveId === null) return
    let cancelled = false
    setCurrent(null)
    setRecent([])
    void api.get<{ items: RunReport[] }>(`/vision/flows/${effectiveId}/recent`, { limit: RECENT })
      .then((r) => {
        if (cancelled) return
        setRecent(r.items)
        setCurrent(r.items[0] ?? null)
      })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [effectiveId])

  const continuous = useMutation({
    mutationFn: (running: boolean) => api.post(`/vision/flows/${effectiveId}/continuous`, { running }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.flow(effectiveId ?? 0) }),
    onError: (error) => toast.error(errorMessage(error)),
  })
  const changeOver = useMutation({
    mutationFn: (recipeId: number) => api.post(`/vision/flows/${effectiveId}/recipes/${recipeId}/activate`, {}),
    onSuccess: (_d, recipeId) => {
      void qc.invalidateQueries({ queryKey: keys.recipes(effectiveId ?? 0) })
      toast.success(t('station.changedOver', { name: (recipes.data?.items ?? []).find((r) => r.id === recipeId)?.name ?? '' }))
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const total = stats.data?.total ?? 0
  const ok = stats.data?.by_status?.ok ?? 0
  const ng = (stats.data?.by_status?.ng ?? 0) + (stats.data?.by_status?.failed ?? 0)
  const yieldPct = total ? Math.round((ok / total) * 1000) / 10 : null
  const running = Boolean(flow.data?.continuous)
  const tone = verdictTone(current?.status)
  const image = current ? (lastImage(current) ?? firstImageOutput(current))?.ref ?? null : null
  const defaultRecipe = (recipes.data?.items ?? []).find((r) => r.is_default)

  if (flows.isPending) return <LoadingState />

  return (
    <div ref={rootRef} className="flex h-screen w-screen flex-col overflow-hidden bg-surface" data-testid="station">
      {/* 頂列：流程、料號、開始／停止 */}
      <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2.5">
        <Select aria-label={t('station.flow')} value={String(effectiveId ?? '')} className="!w-56"
          onChange={(e) => { const id = Number(e.target.value); setFlowId(id); setParams({ flow: String(id) }) }}
          options={items.map((f) => ({ value: String(f.id), label: f.name }))} data-testid="station-flow" />
        {(recipes.data?.items ?? []).length > 0 ? (
          <Select aria-label={t('station.recipe')} value={String(defaultRecipe?.id ?? '')} className="!w-48"
            onChange={(e) => changeOver.mutate(Number(e.target.value))} data-testid="station-recipe"
            options={(recipes.data?.items ?? []).map((r) => ({ value: String(r.id), label: r.name }))} />
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <Button size="lg" variant={running ? 'danger' : 'primary'} loading={continuous.isPending}
            icon={running ? <Pause size={18} /> : <Play size={18} />}
            onClick={() => continuous.mutate(!running)} data-testid="station-run">
            {running ? t('station.stop') : t('station.start')}
          </Button>
          <Button size="lg" icon={<Maximize2 size={18} />} title={t('station.fullscreen')} aria-label={t('station.fullscreen')}
            onClick={() => void (document.fullscreenElement ? document.exitFullscreen() : rootRef.current?.requestFullscreen())} />
          {auth.isEngineer ? (
            <Link to={`/flows/${effectiveId}`} className="btn" title={t('station.openEditor')}><Settings2 size={18} /></Link>
          ) : null}
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* 判定：兩公尺外要看得清楚 */}
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 p-4">
          <div className={`flex w-full max-w-2xl items-center justify-center rounded-xl py-6 ${tone.bg} text-white`} data-testid="station-verdict">
            <span className="text-[clamp(3rem,12vw,7rem)] font-bold leading-none tracking-tight">
              {current ? (current.outputs?.judge as string) || current.status.toUpperCase() : '—'}
            </span>
          </div>
          {image ? (
            <img src={imageUrl(image, 900)} alt="" className="min-h-0 max-h-[45vh] w-auto rounded border border-line object-contain" />
          ) : (
            <p className="text-sm text-muted">{t('station.waiting')}</p>
          )}
        </div>

        {/* 右欄：今日產量與最近幾片 */}
        <aside className="flex w-full shrink-0 flex-col gap-4 border-t border-line p-4 lg:w-80 lg:border-l lg:border-t-0">
          <div className="grid grid-cols-3 gap-2 text-center">
            <div><div className="text-2xl font-semibold tnum" data-testid="station-total">{total}</div><div className="text-xs text-muted">{t('station.today')}</div></div>
            <div><div className="text-2xl font-semibold tnum text-warning">{ng}</div><div className="text-xs text-muted">{t('station.ng')}</div></div>
            <div><div className="text-2xl font-semibold tnum text-ok">{yieldPct === null ? '—' : `${yieldPct}%`}</div><div className="text-xs text-muted">{t('station.yield')}</div></div>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <CircleDot size={12} className={running ? 'text-ok' : 'text-muted'} aria-hidden />
            {running ? t('station.running') : t('station.stopped')}
            {flow.data?.commissioned === false ? <Badge tone="warning">{t('station.notCommissioned')}</Badge> : null}
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <p className="mb-1.5 text-xs font-medium text-muted">{t('station.recent')}</p>
            <div className="grid grid-cols-3 gap-1.5" data-testid="station-recent">
              {recent.map((run) => {
                const ref = (lastImage(run) ?? firstImageOutput(run))?.ref
                return (
                  <button key={run.id} type="button" onClick={() => setCurrent(run)} title={new Date(run.started_at * 1000).toLocaleTimeString()}
                    className={`relative overflow-hidden rounded border-2 ${run.status === 'ok' ? 'border-ok' : run.status === 'ng' ? 'border-warning' : 'border-critical'}`}>
                    {ref ? <img src={imageUrl(ref, 120)} alt="" className="aspect-square w-full object-cover" loading="lazy" />
                      : <span className="flex aspect-square w-full items-center justify-center text-[10px] text-muted">{run.status}</span>}
                  </button>
                )
              })}
              {recent.length === 0 ? <p className="col-span-3 text-xs text-muted">{t('station.noRuns')}</p> : null}
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}
