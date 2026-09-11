/** 清單卡只編輯提案；送出時使用頁面當下的圖並防止非同步覆蓋新變更。 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { Button } from '@/components/ui'
import { ParamField } from '@/components/editor/ParamField'
import { api } from '@/lib/api'
import { getAssistantContext, publishAssistantProgress, type AssistantContext } from '@/lib/assistantContext'
import { errorMessage } from '@/lib/errors'
import { useInspectKinds } from '@/lib/queries'
import { inspectionParam } from '@/lib/inspect'
import type { FlowGraph, InspectKind, InspectTask, Region, TaskDraft } from '@/lib/types'

const TASKLIST_MESSAGES: Record<string, string> = {
  'Choose one image source before adding tasks.': 'errors.source',
  'Select a calibration before using millimetres.': 'errors.calibration',
  'Choose the locate task to use.': 'errors.locator',
  'Other tasks or steps depend on this task.': 'errors.dependency',
  'Select an existing task of this kind.': 'errors.task',
  'Several tasks match. Say which item to change, for example "item 2".': 'errors.ambiguous',
  'Some proposed fields need valid values or additional information.': 'warnings.missing',
  'An explicit value from your request was preserved.': 'warnings.preserved',
}

/** 後端的清單訊息是英文正本；認得的換成介面語言，其餘原樣顯示（階段 15：繁中介面出現英文且重複六次）。 */
export function tasklistMessage(t: TFunction, text: string): string {
  const required = /^Confirm required fields: (.+)$/.exec(text)
  if (required) return t('assistant.tasklist.errors.required', { fields: required[1] })
  const invalid = /^Provide a valid value for '(.+)'\.$/.exec(text)
  if (invalid) return t('assistant.tasklist.errors.value', { field: invalid[1] })
  if (TASKLIST_MESSAGES[text]) return t(`assistant.tasklist.${TASKLIST_MESSAGES[text]}`)
  if (text.includes('offline parser')) return t(text.includes('request limit') ? 'assistant.tasklist.warnings.rateLimit' : 'assistant.tasklist.warnings.offline')
  return text
}

export function mergeDraft(draft: TaskDraft, key: string, value: unknown): TaskDraft {
  return { ...draft, fields: { ...draft.fields, [key]: { value, status: 'confirmed', source: 'user', note: '' } },
    regions: draft.regions.map((r) => r.field === key ? { ...r, region: value as Region, status: 'confirmed', source: 'user' } : r) }
}

export function confirmDraft(draft: TaskDraft): TaskDraft {
  return { ...draft, fields: Object.fromEntries(Object.entries(draft.fields).map(([key, value]) => [key, value.status === 'assumed' ? { ...value, status: 'confirmed' } : value])),
    regions: draft.regions.map((r) => r.status === 'assumed' ? { ...r, status: 'confirmed' } : r) }
}

function RegionValue({ value, shapes, onChange }: { value: unknown; shapes: string[]; onChange: (value: unknown) => void }) {
  const { t } = useTranslation()
  const region = value && typeof value === 'object' ? value as Record<string, unknown> : null
  const layouts: Record<string, Record<string, unknown>> = {
    rect: {shape:'rect',x:0,y:0,w:100,h:100}, rotated_rect: {shape:'rotated_rect',cx:100,cy:100,w:100,h:100,angle:0},
    circle: {shape:'circle',cx:100,cy:100,r:50}, annulus: {shape:'annulus',cx:100,cy:100,r_inner:40,r_outer:60},
  }
  return <div>
    <select className="input w-full" aria-label={t('assistant.tasklist.shape')} value={String(region?.shape ?? '')} onChange={(e) => onChange(layouts[e.target.value] ?? null)}>
      <option value="">{t('assistant.tasklist.chooseRegion')}</option>{shapes.filter((s) => layouts[s]).map((shape) => <option key={shape} value={shape}>{t(`viewer.shapes.${shape}`)}</option>)}
    </select>
    {region && <div className="grid grid-cols-2 gap-1">{Object.keys(layouts[String(region.shape)] ?? {}).filter((key) => key !== 'shape').map((key) => <label key={key} className="text-[11px]">{t(`assistant.tasklist.coordinates.${key}`)}<input className="input w-full min-w-0" type="number" step="any" value={typeof region[key] === 'number' ? region[key] : ''} onChange={(e) => onChange({...region,[key]: e.target.value === '' ? null : Number(e.target.value)})} /></label>)}</div>}
  </div>
}

function FieldValue({ value, kind, onChange, label, options }: { value: unknown; kind?: string; onChange: (v: unknown) => void; label: string; options?: { value: unknown; label: string }[] }) {
  const [raw, setRaw] = useState(() => typeof value === 'object' ? JSON.stringify(value ?? '') : String(value ?? ''))
  const [invalid, setInvalid] = useState(false)
  useEffect(() => { setRaw(typeof value === 'object' ? JSON.stringify(value ?? '') : String(value ?? '')) }, [value])
  if (kind === 'boolean') return <input type="checkbox" aria-label={label} checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
  if (kind === 'select') return <select className="input w-full" aria-label={label} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}><option value="" />{options?.map((o) => <option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}</select>
  const numeric = kind === 'number' || kind === 'range'
  return <input className="input w-full min-w-0" aria-label={label} aria-invalid={invalid} value={raw} type={numeric ? 'number' : 'text'} step="any" onChange={(e) => {
    const text = e.target.value
    setRaw(text)
    if (['roi', 'images', 'json', 'multiselect'].includes(kind ?? '')) {
      try { onChange(JSON.parse(text)); setInvalid(false) } catch { setInvalid(true); onChange(null) }
    } else onChange(numeric ? text === '' ? null : Number(text) : text)
  }} />
}

export function TaskListCard({ drafts, flowId, context, onChange, kinds: supplied, chatId }: {
  drafts: TaskDraft[]; flowId: number | null; context: AssistantContext; onChange: (drafts: TaskDraft[]) => void; kinds?: InspectKind[]; chatId?: number | null
}) {
  const { t } = useTranslation()
  const catalogue = useInspectKinds()
  const kinds = catalogue.data?.items ?? supplied ?? []
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const sameFlow = context.flowId === flowId
  function show(draft: TaskDraft) {
    context.showProposals?.(draft.regions.flatMap((r) => {
      const region = draft.fields[r.field]?.value as Region | null
      return region && draft.fields[r.field]?.status !== 'missing' ? [region] : []
    }))
  }
  async function apply(draft: TaskDraft) {
    if (!sameFlow) return
    setBusy(true); setError('')
    const control = new AbortController()
    controller.current = control
    try {
      if (draft.op === 'run') {
        await context.runInspection?.()
        onChange(drafts.filter((d) => d.draft_id !== draft.draft_id))
        return
      }
      await context.prepareGraph?.()
      const graph = context.getGraph?.()
      if (!graph || !context.applyGraph) throw new Error(t('assistant.tasklist.openFlow'))
      const signature = JSON.stringify(graph)
      const confirmed = confirmDraft(draft)
      const out = await api.post<{ graph: FlowGraph; tasks: InspectTask[]; applied: string[]; skipped: { draft_id: string; reason: string }[] }>('/vision/agent/tasklist/apply', {
        chat_id: chatId,
        flow_id: flowId,
        graph, drafts: [confirmed], confirmations: { [draft.draft_id]: { confirmed: true, image_node: confirmed.image_node || undefined, fields: Object.fromEntries(Object.entries(confirmed.fields).filter(([, v]) => v.status === 'confirmed').map(([k]) => [k, true])) } },
      }, undefined, control.signal)
      const current = getAssistantContext()
      if (current?.flowId !== flowId || JSON.stringify(current.getGraph?.()) !== signature) throw new Error(t('assistant.tasklist.changed'))
      if (out.skipped.length) { setError(out.skipped.map((s) => tasklistMessage(t, s.reason)).join(' ')); return }
      current.applyGraph?.(out.graph, '')
      current.showProposals?.([])
      if (flowId) publishAssistantProgress(flowId, {}, `Confirmed ${draft.op} proposal: ${draft.kind}.`)
      onChange(drafts.filter((d) => d.draft_id !== draft.draft_id))
    } catch (e) { if (!control.signal.aborted) setError(tasklistMessage(t, errorMessage(e))) } finally { setBusy(false) }
  }
  /** 定位標記等固定影像欄位：請使用者在影像上框選，平台擺正裁切存成固定影像後放進欄位 */
  async function cropInto(draft: TaskDraft, key: string, current: unknown) {
    const ctx = getAssistantContext()
    if (!ctx?.requestRegion || !ctx.imageRef) return
    setError('')
    const region = await ctx.requestRegion(['rect', 'rotated_rect'])
    if (!region) return
    try {
      const saved = await api.post<Record<string, unknown>>('/vision/fixed-images/from-ref', { ref: ctx.imageRef, region, name: `${draft.kind}-${key}` })
      const list = Array.isArray(current) ? current : []
      onChange(drafts.map((d) => d.draft_id === draft.draft_id ? mergeDraft(d, key, [...list, saved]) : d))
    } catch (e) { setError(tasklistMessage(t, errorMessage(e))) }
  }
  return <div className="space-y-2" data-testid="assistant-tasklist">
    <p className="text-xs text-muted">{t('assistant.tasklist.review')}</p>
    {drafts.map((draft) => {
      const kind = kinds.find((k) => k.kind === draft.kind)
      return <section className="rounded border border-border p-2" key={draft.draft_id}>
        <h4 className="text-sm font-medium">{t(`assistant.tasklist.ops.${draft.op}`)} {kind?.label ?? draft.kind}</h4>
        {draft.op === 'add' && (draft.source_choices?.length ?? 0) > 1 ? <label className="my-2 block text-xs" data-testid="tasklist-image-source">{t('assistant.tasklist.imageSource')}
          <select className="input mt-1 w-full" aria-label={t('assistant.tasklist.imageSource')} value={draft.image_node ?? ''} onChange={(e) => onChange(drafts.map((d) => d.draft_id === draft.draft_id ? { ...d, image_node: e.target.value } : d))}>
            <option value="">{t('assistant.tasklist.chooseSource')}</option>{draft.source_choices?.map((c) => <option key={c.node} value={c.node}>{c.label}</option>)}
          </select></label> : null}
        {Object.entries(draft.fields).map(([key, value]) => {
          const spec = kind?.fields.find((f) => f.key === key)
          if (spec?.visible_when && Object.entries(spec.visible_when).some(([k, v]) => !(Array.isArray(v) ? v : [v]).includes(draft.fields[k]?.value ?? kind?.fields.find((f) => f.key === k)?.default))) return null
          return <div key={key} className={`my-2 rounded p-1 ${value.status === 'assumed' ? 'bg-warning/10 text-warning' : ''}`}>
            <div className="flex flex-wrap justify-between gap-1 text-xs"><span>{spec?.label ?? key}</span><span>{t(`assistant.tasklist.status.${value.status}`)}</span></div>
            {spec?.kind === 'roi' ? <RegionValue value={value.value} shapes={spec.shapes ?? []} onChange={(v) => onChange(drafts.map((d) => d.draft_id === draft.draft_id ? mergeDraft(d, key, v) : d))} />
              : spec && ['asset', 'images'].includes(spec.kind) ? <ParamField param={inspectionParam(spec)} value={value.value} onChange={(v) => onChange(drafts.map((d) => d.draft_id === draft.draft_id ? mergeDraft(d, key, v) : d))} actions={{roiEditingKey:null,setRoiEditing:()=>{},templateFromImage:()=>{},templateKey:null,hasImage:false}} />
              : <FieldValue label={spec?.label ?? key} kind={spec?.kind} value={value.value} options={spec?.options} onChange={(v) => onChange(drafts.map((d) => d.draft_id === draft.draft_id ? mergeDraft(d, key, v) : d))} />}
            {spec?.kind === 'images' && context.requestRegion && context.imageRef ? <Button size="xs" className="mt-1" disabled={busy || !sameFlow} onClick={() => void cropInto(draft, key, value.value)} data-testid={`tasklist-crop-${key}`}>{t('assistant.tasklist.cropFromImage')}</Button> : null}
            {value.note && <p className="text-[11px] text-muted">{t(`assistant.tasklist.notes.${key === 'unit' ? value.status === 'missing' ? 'calibration' : 'unit' : spec?.kind === 'roi' ? 'region' : value.status === 'missing' ? 'missing' : 'assumed'}`)}</p>}
          </div>
        })}
        {draft.note && <p className="text-xs">{tasklistMessage(t, draft.note)}</p>}
        <div className="flex flex-wrap gap-2">
          {draft.regions.length > 0 && <Button size="xs" disabled={!sameFlow || !context.showProposals} onClick={() => show(draft)}>{t('assistant.tasklist.show')}</Button>}
          <Button size="xs" variant="primary" disabled={busy || !sameFlow || draft.op === 'answer' || (draft.op === 'run' ? !context.runInspection || context.execLocked : !context.applyGraph)} onClick={() => void apply(draft)}>{t(draft.op === 'run' ? 'assistant.tasklist.ops.run' : 'assistant.tasklist.confirm')}</Button>
          <Button size="xs" disabled={busy} onClick={() => { context.showProposals?.([]); onChange(drafts.filter((d) => d.draft_id !== draft.draft_id)) }}>{t('assistant.tasklist.discard')}</Button>
        </div>
      </section>
    })}
    {error && <p role="alert" className="text-xs text-danger">{error}</p>}
  </div>
}
