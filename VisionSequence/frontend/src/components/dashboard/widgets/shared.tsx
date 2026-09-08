import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Lock, Maximize2, Play, Square } from 'lucide-react'

import { ImageViewer } from '@/components/viewer/ImageViewer'
import { Badge, Button, DetailRow, EmptyState, Switch, TextInput } from '@/components/ui'
import { api, fixedImageUrl, imageUrl } from '@/lib/api'
import { pickImage } from '@/lib/board'
import {
  booleanProp,
  evalRule,
  flowPack,
  imageOf,
  latestBoardRun,
  numberProp,
  resolveFlow,
  stringProp,
  templateText,
  valueOf,
  widgetById,
} from '@/lib/dashboard'
import { useContinuous, useFlow, useFlowMutations, useFlowSpc, useLockMutations, useRecipes, useRunFlow, useRunHistory } from '@/lib/queries'
import type { DashboardAction, DashboardRuleOp, DashboardWidget, RunReport } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import type { DashboardWidgetProps } from '../types'

const toneClass: Record<string, string> = {
  ok: 'text-ok border-ok/30 bg-ok-soft',
  ng: 'text-critical border-critical/30 bg-critical-soft',
  failed: 'text-warning border-warning/30 bg-warning-soft',
  neutral: 'text-muted border-line bg-surface-muted',
}

function liveFor(props: DashboardWidgetProps, flowId: number | null): RunReport | null {
  return flowId === null ? null : props.live[flowId] ?? null
}

function WidgetShell({ title, children, className = '' }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <div className={`flex h-full min-h-28 min-w-0 flex-col overflow-hidden rounded-md border border-line bg-surface/95 p-3 text-content shadow-sm ${className}`}>
      {title ? <div className="mb-2 truncate text-xs font-semibold uppercase tracking-normal text-muted">{title}</div> : null}
      <div className="min-h-0 min-w-0 flex-1">{children}</div>
    </div>
  )
}

function Placeholder({ message }: { message: string }) {
  return <div className="flex h-full min-h-24 items-center justify-center rounded border border-dashed border-line text-sm text-muted">{message}</div>
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)))
  if (typeof value === 'boolean') return value ? 'True' : 'False'
  return String(value)
}

function statusTone(status: string | undefined | null): keyof typeof toneClass {
  if (status === 'ok' || status === 'OK') return 'ok'
  if (status === 'ng' || status === 'NG') return 'ng'
  if (status === 'failed' || status === 'error') return 'failed'
  return 'neutral'
}

export function ImageWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const flowId = resolveFlow(props.widget, props.layout)
  const live = liveFor(props, flowId)
  const historyLimit = numberProp(props.widget, 'history', 1)
  const history = useRunHistory(flowId, { limit: historyLimit })
  const [selectedRef, setSelectedRef] = useState('')
  const currentImage = imageOf(props.data, flowId, props.widget, live)
  const historyImages = useMemo(() => historyImagesFor(props.widget, history.data?.items ?? [], live, historyLimit), [props.widget, history.data, live, historyLimit])
  const selectedImage = selectedRef ? historyImages.find((item) => item.ref === selectedRef) : null
  const image = selectedImage ?? currentImage
  if (!image) return <WidgetShell><Placeholder message={t('dashboardRun.noImage')} /></WidgetShell>
  return (
    <WidgetShell className="p-0">
      <div className="flex h-full min-h-48 flex-col">
        <div className="relative min-h-0 flex-1">
          <ImageViewer
            src={imageUrl(image.ref, 1600)}
            imageWidth={image.width}
            imageHeight={image.height}
            overlays={image.overlays}
            toolbar={false}
            badge={latestBoardRun(flowPack(props.data, flowId), live) ? { text: latestBoardRun(flowPack(props.data, flowId), live)?.verdict ?? '', tone: statusTone(latestBoardRun(flowPack(props.data, flowId), live)?.status) === 'ng' ? 'ng' : 'ok' } : null}
            className="h-full"
          />
          {booleanProp(props.widget, 'crosshair', false) ? (
            <div className="pointer-events-none absolute inset-0">
              <div className="absolute left-1/2 top-0 h-full border-l border-white/40" />
              <div className="absolute left-0 top-1/2 w-full border-t border-white/40" />
            </div>
          ) : null}
        </div>
        {historyLimit > 1 && historyImages.length > 1 ? (
          <div className="flex shrink-0 gap-1 overflow-x-auto border-t border-line bg-surface p-1.5">
            {historyImages.map((item) => (
              <button key={item.ref} type="button" title={item.runId} onClick={() => setSelectedRef(item.ref)} className={`h-14 w-20 shrink-0 overflow-hidden rounded border ${item.ref === image.ref ? 'border-brand' : 'border-line'}`}>
                <img src={imageUrl(item.ref, 160)} alt="" className="h-full w-full object-cover" />
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </WidgetShell>
  )
}

export function ImagesWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const columns = numberProp(props.widget, 'columns', 2)
  const items = Array.isArray(props.widget.props?.items) ? props.widget.props.items : [props.widget.props ?? {}]
  return (
    <WidgetShell>
      <div className="grid h-full min-h-0 gap-2" style={{ gridTemplateColumns: `repeat(${Math.max(1, columns)}, minmax(0, 1fr))` }}>
        {items.map((item, index) => {
          const itemWidget = { ...props.widget, props: { ...props.widget.props, ...(typeof item === 'object' && item !== null ? item : {}) } }
          const flowId = resolveFlow(itemWidget, props.layout)
          const img = imageOf(props.data, flowId, itemWidget, liveFor(props, flowId))
          return img ? <img key={index} src={imageUrl(img.ref, 800)} alt="" className="h-full min-h-24 w-full rounded object-contain" /> : <Placeholder key={index} message={t('dashboardRun.noImage')} />
        })}
      </div>
    </WidgetShell>
  )
}

export function RunControlWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const auth = useAuth()
  const flowId = resolveFlow(props.widget, props.layout)
  const run = useRunFlow()
  const continuous = useContinuous()
  const disabledReason = auth.can('flows.run') ? '' : t('dashboardRun.noPermission')
  return (
    <WidgetShell title={t('dashboardRun.widgetTypes.run_control')}>
      <div className="flex h-full flex-wrap items-center justify-center gap-2">
        <Button icon={<Play className="size-4" />} loading={run.isPending} disabled={!flowId || !!disabledReason} title={disabledReason} onClick={() => flowId && run.mutate({ flowId })}>{t('dashboardRun.runOnce')}</Button>
        <Button icon={<Maximize2 className="size-4" />} loading={continuous.isPending} disabled={!flowId || !!disabledReason} title={disabledReason} onClick={() => flowId && continuous.mutate({ flowId, running: true })}>{t('dashboardRun.startContinuous')}</Button>
        <Button icon={<Square className="size-4" />} loading={continuous.isPending} disabled={!flowId || !!disabledReason} title={disabledReason} onClick={() => flowId && continuous.mutate({ flowId, running: false })}>{t('dashboardRun.stopContinuous')}</Button>
      </div>
    </WidgetShell>
  )
}

export function RunStatusWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const flowId = resolveFlow(props.widget, props.layout)
  const run = latestBoardRun(flowPack(props.data, flowId), liveFor(props, flowId))
  return (
    <WidgetShell title={t('dashboardRun.widgetTypes.run_status')}>
      {run ? (
        <dl className="space-y-1">
          <DetailRow label={t('dashboardRun.status')}>{run.status}</DetailRow>
          <DetailRow label={t('dashboardRun.duration')}>{run.duration_ms.toFixed(1)} ms</DetailRow>
          <DetailRow label={t('dashboardRun.runId')} mono>{run.id}</DetailRow>
          <DetailRow label={t('dashboardRun.time')}>{run.started_at ? new Date(run.started_at * 1000).toLocaleTimeString() : ''}</DetailRow>
        </dl>
      ) : <Placeholder message={t('dashboardRun.noData')} />}
    </WidgetShell>
  )
}

export function VerdictWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const flowId = resolveFlow(props.widget, props.layout)
  const run = latestBoardRun(flowPack(props.data, flowId), liveFor(props, flowId))
  const tone = statusTone(run?.status)
  return (
    <WidgetShell>
      <div className={`flex h-full min-h-28 flex-col items-center justify-center rounded border px-3 text-center ${toneClass[tone]}`}>
        <div className="text-xs uppercase tracking-normal">{t('dashboardRun.verdict')}</div>
        <div className="mt-1 text-5xl font-bold leading-none">{run?.verdict ?? '-'}</div>
        {run?.label ? <div className="mt-2 text-sm">{run.label}</div> : null}
      </div>
    </WidgetShell>
  )
}

export function TextWidgetBase(props: DashboardWidgetProps) {
  const flowId = resolveFlow(props.widget, props.layout)
  const text = templateText(stringProp(props.widget, 'template'), props.data, flowId, liveFor(props, flowId))
  return <WidgetShell><div className="flex h-full items-center text-2xl font-semibold leading-tight">{text || '-'}</div></WidgetShell>
}

function requiredPermission(action: DashboardAction | string | undefined): 'flows.run' | 'flows.teach' | 'flows.edit' | null {
  if (action === 'run_once' || action === 'continuous_start' || action === 'continuous_stop') return 'flows.run'
  if (action === 'activate_recipe' || action === 'set_variable') return 'flows.teach'
  if (action === 'lock' || action === 'unlock') return 'flows.edit'
  return null
}

export function ButtonWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const flowId = resolveFlow(props.widget, props.layout)
  const action = stringProp(props.widget, 'action') as DashboardAction | undefined
  const run = useRunFlow()
  const continuous = useContinuous()
  const lock = useLockMutations()
  const recipes = useRecipes(flowId)
  const permission = requiredPermission(action)
  const disabledReason = permission && !auth.can(permission) ? t('dashboardRun.noPermission') : ''
  const label = stringProp(props.widget, 'label') ?? t(`dashboardRun.actions.${action ?? 'run_once'}`)
  const execute = async () => {
    if (!flowId && !['navigate', 'lock', 'unlock'].includes(action ?? '')) return
    if (action === 'run_once' && flowId) return run.mutate({ flowId })
    if (action === 'continuous_start' && flowId) return continuous.mutate({ flowId, running: true })
    if (action === 'continuous_stop' && flowId) return continuous.mutate({ flowId, running: false })
    if (action === 'activate_recipe' && flowId) {
      const recipeRaw = props.widget.props?.recipe
      const match = recipes.data?.items.find((recipe) => recipe.id === Number(recipeRaw) || recipe.name === recipeRaw)
      await api.post(`/vision/flows/${flowId}/recipes/${match?.id ?? Number(recipeRaw)}/activate`, {})
      toast.success(t('dashboardRun.actionDone'))
      return
    }
    if (action === 'set_variable') {
      const variable = stringProp(props.widget, 'variable')
      if (!variable) return
      const value = props.widget.props?.value
      const path = flowId ? `/vision/flows/${flowId}/variables` : '/vision/variables'
      await api.put(path, { values: { [variable]: value } })
      toast.success(t('dashboardRun.actionDone'))
      return
    }
    if (action === 'lock') return lock.acquire.mutate({ reason: 'dashboard' })
    if (action === 'unlock') return lock.release.mutate()
    if (action === 'navigate') {
      const url = stringProp(props.widget, 'url')
      if (url) window.location.href = url
    }
  }
  return (
    <WidgetShell>
      <div className="flex h-full items-center justify-center">
        <Button onClick={() => void execute()} disabled={!!disabledReason} title={disabledReason} icon={<Play className="size-4" />}>{label}</Button>
      </div>
    </WidgetShell>
  )
}

export function SwitchWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const flowId = resolveFlow(props.widget, props.layout)
  const variable = stringProp(props.widget, 'variable') ?? props.widget.source?.key ?? ''
  const current = Boolean(valueOf(props.data, flowId, variable))
  const disabled = !auth.can('flows.teach')
  const update = async (value: boolean) => {
    const path = props.widget.props?.scope === 'station' || !flowId ? '/vision/variables' : `/vision/flows/${flowId}/variables`
    await api.put(path, { values: { [variable]: value } })
    toast.success(t('dashboardRun.saved'))
  }
  return <WidgetShell title={variable || t('dashboardRun.widgetTypes.switch')}><div className="flex h-full items-center justify-center"><Switch checked={current} disabled={disabled || !variable} label={variable} onChange={(v) => void update(v)} /></div></WidgetShell>
}

export function ParamWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const auth = useAuth()
  const flowId = resolveFlow(props.widget, props.layout)
  const nodeId = stringProp(props.widget, 'node') ?? ''
  const param = stringProp(props.widget, 'param') ?? ''
  const flow = useFlow(flowId)
  const mutations = useFlowMutations()
  const [draft, setDraft] = useState('')
  const value = flow.data?.graph.nodes.find((node) => node.id === nodeId)?.params?.[param]
  const display = draft || formatValue(value)
  const save = () => {
    if (!flow.data || !nodeId || !param) return
    const graph = {
      ...flow.data.graph,
      nodes: flow.data.graph.nodes.map((node) => node.id === nodeId ? { ...node, params: { ...(node.params ?? {}), [param]: parseDraft(draft) } } : node),
    }
    mutations.patch.mutate({ id: flow.data.id, graph })
    setDraft('')
  }
  return (
    <WidgetShell title={param || t('dashboardRun.param')}>
      <div className="space-y-2">
        <TextInput value={display} readOnly={!auth.can('flows.teach')} onChange={(e) => setDraft(e.target.value)} />
        {auth.can('flows.teach') ? <Button size="sm" onClick={save} disabled={!draft}>{t('dashboardRun.save')}</Button> : <Badge tone="neutral">{t('dashboardRun.readonly')}</Badge>}
      </div>
    </WidgetShell>
  )
}

export function VariableWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const flowId = resolveFlow(props.widget, props.layout)
  const variable = stringProp(props.widget, 'variable') ?? props.widget.source?.key ?? ''
  const editable = props.widget.props?.editable !== false && auth.can('flows.teach')
  const [draft, setDraft] = useState('')
  const value = valueOf(props.data, flowId, variable)
  const save = async () => {
    const path = props.widget.props?.scope === 'station' || !flowId ? '/vision/variables' : `/vision/flows/${flowId}/variables`
    await api.put(path, { values: { [variable]: parseDraft(draft) } })
    setDraft('')
    toast.success(t('dashboardRun.saved'))
  }
  return (
    <WidgetShell title={variable || t('dashboardRun.variable')}>
      <div className="space-y-2">
        <div className="text-2xl font-semibold">{formatValue(value) || '-'}</div>
        {editable ? (
          <div className="flex gap-2">
            <TextInput value={draft} placeholder={formatValue(value)} onChange={(e) => setDraft(e.target.value)} />
            <Button size="sm" onClick={() => void save()} disabled={!draft}>{t('dashboardRun.save')}</Button>
          </div>
        ) : <Badge tone="neutral">{t('dashboardRun.readonly')}</Badge>}
      </div>
    </WidgetShell>
  )
}

export function TrafficLightWidgetBase(props: DashboardWidgetProps) {
  const flowId = resolveFlow(props.widget, props.layout)
  const run = latestBoardRun(flowPack(props.data, flowId), liveFor(props, flowId))
  const active = statusTone(run?.status)
  return (
    <WidgetShell>
      <div className="flex h-full items-center justify-center gap-4">
        {(['ok', 'ng', 'failed'] as const).map((tone) => <span key={tone} className={`size-14 rounded-full border ${active === tone ? toneClass[tone] : 'border-line bg-surface-muted opacity-35'}`} />)}
      </div>
    </WidgetShell>
  )
}

export function ConditionalLightWidgetBase(props: DashboardWidgetProps) {
  const key = stringProp(props.widget, 'key') ?? props.widget.source?.key
  const flowId = resolveFlow(props.widget, props.layout)
  const value = valueOf(props.data, flowId, key, liveFor(props, flowId))
  const ok = evalRule(stringProp(props.widget, 'op') as DashboardRuleOp | undefined, value, props.widget.props?.value, props.widget.props?.value2)
  return <WidgetShell title={key}><div className="flex h-full items-center justify-center"><span className={`size-16 rounded-full border ${ok ? 'border-ok/30 bg-ok text-white' : 'border-line bg-surface-muted'}`} /></div></WidgetShell>
}

export function TableWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const flowId = resolveFlow(props.widget, props.layout)
  const live = liveFor(props, flowId)
  const maxRows = numberProp(props.widget, 'rows', 10)
  const history = useRunHistory(flowId, { limit: maxRows })
  const columns = Array.isArray(props.widget.props?.columns) ? props.widget.props.columns.filter((key): key is string => typeof key === 'string' && key.trim() !== '') : []
  const rules = Array.isArray(props.widget.props?.rules) ? props.widget.props.rules : []
  const rows = useMemo(() => historyRows(history.data?.items ?? [], live, maxRows), [history.data, live, maxRows])
  return (
    <WidgetShell title={t('dashboardRun.widgetTypes.table')}>
      {rows.length ? (
        <div className="h-full overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr>
                <th className="py-1 pr-2 text-left font-medium">{t('dashboardRun.runId')}</th>
                <th className="py-1 pr-2 text-left font-medium">{t('dashboardRun.time')}</th>
                <th className="py-1 pr-2 text-left font-medium">{t('dashboardRun.verdict')}</th>
                {columns.map((column) => <th key={column} className="py-1 pr-2 text-left font-medium">{column}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((run) => {
                const color = ruleColor(rules, run)
                return (
                <tr key={run.id} className="border-t border-line" style={color ? { color } : undefined}>
                  <td className="max-w-28 truncate py-1 pr-2 font-mono text-xs">{run.id}</td>
                  <td className="tnum whitespace-nowrap py-1 pr-2 text-xs">{run.finished_at ? new Date(run.finished_at * 1000).toLocaleTimeString() : '-'}</td>
                  <td className="py-1 pr-2 font-semibold">{runVerdict(run)}</td>
                  {columns.map((column) => <td key={column} className="tnum py-1 pr-2">{formatValue(runValue(run, column)) || '-'}</td>)}
                </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : <Placeholder message={t('dashboardRun.noRows')} />}
    </WidgetShell>
  )
}

function historyRows(history: RunReport[], live: RunReport | null, limit: number): RunReport[] {
  const rows = live ? [live, ...history] : history
  const seen = new Set<string>()
  return rows.filter((run) => {
    if (seen.has(run.id)) return false
    seen.add(run.id)
    return true
  }).slice(0, limit)
}

function historyImagesFor(widget: DashboardWidget, history: RunReport[], live: RunReport | null, limit: number) {
  return historyRows(history, live, limit).map((run) => {
    const image = pickImage(run, stringProp(widget, 'node') ?? stringProp(widget, 'port'))
    if (!image) return null
    return {
      ...image,
      runId: run.id,
      overlays: widget.props?.overlays === false ? [] : Object.values(run.nodes ?? {}).flatMap((node) => node.overlays ?? []),
    }
  }).filter((item): item is { ref: string; width: number; height: number; overlays: RunReport['nodes'][string]['overlays']; runId: string } => item !== null)
}

function runVerdict(run: RunReport): string {
  const judge = run.outputs?.judge
  return typeof judge === 'string' && judge ? judge : run.status.toUpperCase()
}

function runValue(run: RunReport, key: string): unknown {
  if (key === 'run_id') return run.id
  if (key === 'time') return run.finished_at ?? run.started_at
  if (key === 'verdict' || key === 'judge') return runVerdict(run)
  if (key === 'status') return run.status
  if (key === 'duration_ms') return run.duration_ms
  return run.outputs?.[key]
}

function ruleColor(rules: unknown[], run: RunReport): string {
  for (const raw of rules) {
    if (!raw || typeof raw !== 'object') continue
    const rule = raw as { key?: unknown; op?: DashboardRuleOp; value?: unknown; color?: unknown }
    if (typeof rule.key === 'string' && evalRule(rule.op, runValue(run, rule.key), rule.value)) return typeof rule.color === 'string' ? rule.color : 'var(--critical)'
  }
  return ''
}

export function LineChartWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const flowId = resolveFlow(props.widget, props.layout)
  const output = stringProp(props.widget, 'key') ?? props.widget.source?.key ?? ''
  const points = numberProp(props.widget, 'points', 80)
  const q = useFlowSpc(flowId, { output, chart: 'imr', subgroup: 5, hours: 24 })
  const series = useMemo(() => (q.data?.series ?? []).slice(-points).map((item, index) => ({ i: index + 1, value: item.value })), [q.data, points])
  return (
    <WidgetShell title={output || t('dashboardRun.widgetTypes.line_chart')}>
      {series.length ? (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
            <XAxis dataKey="i" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            {props.widget.props?.lower != null ? <ReferenceLine y={Number(props.widget.props.lower)} stroke="var(--critical)" strokeDasharray="2 2" /> : null}
            {props.widget.props?.upper != null ? <ReferenceLine y={Number(props.widget.props.upper)} stroke="var(--critical)" strokeDasharray="2 2" /> : null}
            <Line type="monotone" dataKey="value" stroke="var(--brand)" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      ) : <Placeholder message={t('dashboardRun.noData')} />}
    </WidgetShell>
  )
}

export function StatsWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const flowId = resolveFlow(props.widget, props.layout)
  const counts = flowPack(props.data, flowId)?.counts
  return (
    <WidgetShell title={t('dashboardRun.widgetTypes.stats')}>
      {counts ? (
        <div className="grid h-full grid-cols-2 place-content-center gap-3 text-center">
          <Metric label={t('dashboardRun.total')} value={counts.total} />
          <Metric label={t('dashboardRun.yield')} value={counts.yield == null ? '-' : `${(counts.yield * 100).toFixed(1)}%`} />
          <Metric label={t('dashboardRun.ok')} value={counts.ok} tone="text-ok" />
          <Metric label={t('dashboardRun.ng')} value={counts.ng + counts.failed} tone="text-critical" />
        </div>
      ) : <Placeholder message={t('dashboardRun.noData')} />}
    </WidgetShell>
  )
}

function Metric({ label, value, tone = '' }: { label: string; value: ReactNode; tone?: string }) {
  return <div><div className="text-xs uppercase tracking-normal text-muted">{label}</div><div className={`tnum text-2xl font-bold ${tone}`}>{value}</div></div>
}

export function PieWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const flowId = resolveFlow(props.widget, props.layout)
  const counts = flowPack(props.data, flowId)?.counts
  const data = counts ? [
    { name: t('dashboardRun.ok'), value: counts.ok, color: 'var(--ok)' },
    { name: t('dashboardRun.ng'), value: counts.ng, color: 'var(--critical)' },
    { name: t('dashboardRun.failed'), value: counts.failed, color: 'var(--warning)' },
  ] : []
  return (
    <WidgetShell title={t('dashboardRun.widgetTypes.pie')}>
      {data.some((item) => item.value > 0) ? (
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="45%" outerRadius="75%" isAnimationActive={false}>
              {data.map((item) => <Cell key={item.name} fill={item.color} />)}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      ) : <Placeholder message={t('dashboardRun.noData')} />}
    </WidgetShell>
  )
}

export function ImageStaticWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const id = stringProp(props.widget, 'fixed_image_id')
  return <WidgetShell className="p-0">{id ? <img src={fixedImageUrl(id, 1200)} alt="" className="h-full w-full object-contain" /> : <Placeholder message={t('dashboardRun.noImage')} />}</WidgetShell>
}

export function ClockWidgetBase() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(id)
  }, [])
  return <WidgetShell><div className="flex h-full flex-col items-center justify-center"><div className="tnum text-5xl font-bold">{now.toLocaleTimeString()}</div><div className="mt-2 text-sm text-muted">{now.toLocaleDateString()}</div></div></WidgetShell>
}

export function LogWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const flowId = resolveFlow(props.widget, props.layout)
  const live = liveFor(props, flowId)
  const pack = flowPack(props.data, flowId)
  const run = live ?? null
  const logs = run ? Object.entries(run.nodes ?? {}).flatMap(([id, node]) => (node.logs ?? []).map((log) => `${id}: ${log.level} ${log.message}`)) : pack?.run?.error ? [pack.run.error] : []
  return (
    <WidgetShell title={t('dashboardRun.widgetTypes.log')}>
      {logs.length ? <div className="h-full overflow-auto font-mono text-xs">{logs.slice(-20).map((line, index) => <div key={`${index}-${line}`} className="py-0.5">{line}</div>)}</div> : <Placeholder message={t('dashboardRun.noLogs')} />}
    </WidgetShell>
  )
}

export function DeviceStatusWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const device = props.data?.device
  return (
    <WidgetShell title={t('dashboardRun.widgetTypes.device_status')}>
      {device ? (
        <dl className="space-y-1">
          <DetailRow label={t('dashboardRun.station')}>{device.station_id}</DetailRow>
          <DetailRow label={t('dashboardRun.version')}>{device.version}</DetailRow>
          <DetailRow label={t('dashboardRun.lock')}>{device.lock.locked ? `${t('dashboardRun.locked')} ${device.lock.holder}` : t('dashboardRun.unlocked')}</DetailRow>
          <DetailRow label={t('dashboardRun.running')}>{device.flows_running.length}</DetailRow>
          <DetailRow label={t('dashboardRun.capacity')}>{device.capacity.active}/{device.capacity.max_workers}</DetailRow>
        </dl>
      ) : <Placeholder message={t('dashboardRun.noData')} />}
    </WidgetShell>
  )
}

export function GroupWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  const title = stringProp(props.widget, 'title') ?? t('dashboardRun.widgetTypes.group')
  const children = Array.isArray(props.widget.props?.children) ? props.widget.props.children.filter((id): id is string => typeof id === 'string') : []
  return (
    <WidgetShell title={title}>
      <div className="grid h-full min-h-0 gap-2">
        {children.map((id) => {
          const child = widgetById(props.layout, id)
          return child ? <NestedWidget key={id} widget={child} props={props} /> : null
        })}
      </div>
    </WidgetShell>
  )
}

export function TabsWidgetBase(props: DashboardWidgetProps) {
  const tabs = Array.isArray(props.widget.props?.tabs) ? props.widget.props.tabs : []
  const normalized = tabs.filter((tab): tab is { title?: string; children?: string[] } => typeof tab === 'object' && tab !== null)
  const [active, setActive] = useState(0)
  const tab = normalized[active] ?? normalized[0]
  return (
    <WidgetShell>
      <div className="mb-2 flex flex-wrap gap-1">
        {normalized.map((item, index) => <Button key={index} size="xs" variant={index === active ? 'primary' : 'subtle'} onClick={() => setActive(index)}>{item.title ?? `Tab ${index + 1}`}</Button>)}
      </div>
      <div className="grid h-[calc(100%-2.25rem)] min-h-0 gap-2">
        {(tab?.children ?? []).map((id) => {
          const child = widgetById(props.layout, id)
          return child ? <NestedWidget key={id} widget={child} props={props} /> : null
        })}
      </div>
    </WidgetShell>
  )
}

function NestedWidget({ widget, props }: { widget: DashboardWidget; props: DashboardWidgetProps }) {
  if ((props.depth ?? 0) > 4) return null
  const next = { ...props, widget, depth: (props.depth ?? 0) + 1 }
  switch (widget.type) {
    case 'image': return <ImageWidgetBase {...next} />
    case 'images': return <ImagesWidgetBase {...next} />
    case 'run_status': return <RunStatusWidgetBase {...next} />
    case 'verdict': return <VerdictWidgetBase {...next} />
    case 'text': return <TextWidgetBase {...next} />
    case 'stats': return <StatsWidgetBase {...next} />
    case 'device_status': return <DeviceStatusWidgetBase {...next} />
    default: return <GenericWidgetBase {...next} />
  }
}

export function GenericWidgetBase(props: DashboardWidgetProps) {
  const { t } = useTranslation()
  return <WidgetShell title={t(`dashboardRun.widgetTypes.${props.widget.type}`)}><EmptyState title={t('dashboardRun.noData')} /></WidgetShell>
}

function parseDraft(value: string): unknown {
  const trimmed = value.trim()
  if (trimmed === 'true') return true
  if (trimmed === 'false') return false
  if (trimmed !== '' && Number.isFinite(Number(trimmed))) return Number(trimmed)
  try {
    return JSON.parse(trimmed)
  } catch {
    return value
  }
}

export function OpenLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link to={to} className="inline-flex items-center gap-1 text-brand hover:underline"><Lock className="size-3" />{children}</Link>
}
