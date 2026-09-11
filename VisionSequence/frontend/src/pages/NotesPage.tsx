import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Page } from '@/components/layout/AppShell'
import { ImagesField } from '@/components/editor/ParamField'
import { Badge, Button, ErrorState, LoadingState, PageHeader } from '@/components/ui'
import { api, fixedImageUrl, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useEngineeringNotes, useFlows, useRecipes } from '@/lib/queries'
import type { EngineeringNote } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

const KINDS = ['decision', 'lesson', 'constraint', 'lighting', 'calibration', 'tolerance_rationale', 'known_issue'] as const
const STATUSES = ['draft', 'confirmed', 'superseded', 'retracted'] as const

export function NotesPage() {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState('')
  const [part, setPart] = useState('')
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [editing, setEditing] = useState<Partial<EngineeringNote> | null>(null)
  const [busy, setBusy] = useState(false)
  const flow = params.get('flow') ?? ''
  const id = Number(params.get('note')) || null
  const list = useEngineeringNotes({ flow, q, part_number: part, kind, status, offset })
  const flows = useFlows()
  const detail = useQuery({ queryKey: ['engineering-note', id], queryFn: () => api.get<EngineeringNote>(`/vision/notes/${id}`), enabled: !!id })
  const row = detail.data
  const [retract, setRetract] = useState(false)
  const canEdit = auth.can('flows.edit')
  function select(note: number) { setParams((old) => { const next = new URLSearchParams(old); next.set('note', String(note)); return next }); setEditing(null); setRetract(false) }
  async function refresh(note: EngineeringNote) {
    await client.invalidateQueries({ queryKey: ['engineering-notes'] })
    client.setQueryData(['engineering-note', note.id], note)
    select(note.id)
  }
  async function transition(action: 'confirm' | 'retract') {
    if (!row) return
    setBusy(true)
    try { await refresh(await api.post<EngineeringNote>(`/vision/notes/${row.id}/${action}`, {})) }
    catch (error) { toast.error(errorMessage(error)) } finally { setBusy(false) }
  }
  return <Page><PageHeader title={t('notes.title')} description={t('notes.description')} actions={canEdit ? <Button onClick={() => setEditing({ kind: 'decision', flow: Number(flow) || null })}>{t('notes.create')}</Button> : undefined} />
    <div className="mb-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
      <label className="label">{t('notes.search')}<input className="input" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0) }} /></label>
      <label className="label">{t('notes.flow')}<select className="input" value={flow} onChange={(e) => { setParams(e.target.value ? { flow: e.target.value } : {}); setOffset(0) }}><option value="">{t('notes.all')}</option>{flows.data?.items.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label>
      <label className="label">{t('notes.part_number')}<input className="input" value={part} onChange={(e) => { setPart(e.target.value); setOffset(0) }} /></label>
      <label className="label">{t('notes.kind')}<select className="input" value={kind} onChange={(e) => { setKind(e.target.value); setOffset(0) }}><option value="">{t('notes.all')}</option>{KINDS.map((k) => <option key={k} value={k}>{t(`notes.kinds.${k}`)}</option>)}</select></label>
      <label className="label">{t('notes.status')}<select className="input" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }}><option value="">{t('notes.all')}</option>{STATUSES.map((s) => <option key={s} value={s}>{t(`notes.statuses.${s}`)}</option>)}</select></label>
    </div>
    {list.isLoading && <LoadingState />}{list.error && <ErrorState error={list.error} />}
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(240px,1fr)_minmax(0,2fr)]">
      <section className="space-y-2" aria-label={t('notes.title')}>
        {list.data?.items.map((note) => <button key={note.id} className={`w-full rounded border p-3 text-left ${id === note.id ? 'border-brand bg-brand/5' : 'border-line bg-surface'}`} onClick={() => select(note.id)}><span className="block break-words font-medium">{note.title}</span><span className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted"><Badge>{t(`notes.statuses.${note.status}`)}</Badge>{note.part_number}{note.flow_name}</span></button>)}
        {list.data?.total === 0 && <p className="p-4 text-muted">{t('notes.empty')}</p>}
        {!!list.data?.total && <div className="flex items-center gap-2"><Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))}>{t('notes.previous')}</Button><span>{t('notes.total', { count: list.data.total })}</span><Button disabled={offset + 100 >= list.data.total} onClick={() => setOffset(offset + 100)}>{t('notes.next')}</Button></div>}
      </section>
      <section className="min-w-0 rounded border border-line bg-surface p-4">
        {editing ? <NoteForm key={`${editing.id ?? 'new'}:${editing.supersedes ?? ''}`} initial={editing} onCancel={() => setEditing(null)} onSaved={refresh} /> : <>
          {detail.isLoading && id && <LoadingState />}{detail.error && <ErrorState error={detail.error} />}
          {row ? <div className="space-y-4 break-words"><div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">{row.title}</h2><Badge>{t(`notes.statuses.${row.status}`)}</Badge></div><p className="whitespace-pre-wrap">{row.body}</p>
            <dl className="grid gap-2 sm:grid-cols-2">{(['project', 'part_number', 'kind', 'owner_name', 'confirmed_by_name', 'confirmed_at', 'applies_from_version', 'applies_to_version', 'recipe', 'source'] as const).map((key) => <div key={key}><dt className="text-xs text-muted">{t(`notes.${key}`)}</dt><dd>{key === 'kind' ? t(`notes.kinds.${row.kind}`) : row[key] ?? '—'}</dd></div>)}</dl>
            {row.flow && <Link className="text-brand underline" to={`/flows/${row.flow}/inspect`}>{t('notes.flow')}: {row.flow_name || row.flow}</Link>}
            <div><h3 className="font-medium">{t('notes.conditions')}</h3><dl>{Object.entries(row.conditions).map(([key, value]) => <div key={key} className="flex flex-wrap gap-2"><dt>{key}</dt><dd>{typeof value === 'string' ? value : JSON.stringify(value)}</dd></div>)}</dl></div>
            <div className="flex flex-wrap gap-3">{row.images.map((item, i) => <NoteImage key={i} item={item} />)}</div>
            {!!row.runs.length && <p>{t('notes.runs')}: {row.runs.join(', ')}</p>}
            <div className="flex flex-wrap gap-3">{row.supersedes && <button className="text-brand underline" onClick={() => select(row.supersedes!)}>{t('notes.supersedes')} #{row.supersedes}</button>}{row.replacement && <button className="text-brand underline" onClick={() => select(row.replacement!)}>{t('notes.replacement')} #{row.replacement}</button>}</div>
            {canEdit && <div className="flex flex-wrap gap-2">{row.status === 'draft' && <><Button disabled={busy} onClick={() => setEditing(row)}>{t('notes.edit')}</Button><Button disabled={busy || !row.can_confirm} onClick={() => void transition('confirm')}>{t('notes.confirm')}</Button>{!row.can_confirm && <p className="w-full text-xs text-muted">{t('notes.otherEngineer')}</p>}</>}
              {['draft', 'confirmed'].includes(row.status) && <><Button disabled={busy} onClick={() => setEditing({ ...row, id: undefined, supersedes: row.id })}>{t('notes.replace')}</Button><Button variant="danger" disabled={busy} onClick={() => setRetract(true)}>{t('notes.retract')}</Button></>}
            </div>}
            {retract && <div role="alert" className="space-y-2"><p>{t('notes.retractPrompt')}</p><Button variant="danger" disabled={busy} onClick={() => void transition('retract')}>{t('notes.retract')}</Button><Button onClick={() => setRetract(false)}>{t('common.cancel')}</Button></div>}
          </div> : !id && <p className="text-muted">{t('notes.select')}</p>}
        </>}
      </section>
    </div>
  </Page>
}

function NoteImage({ item }: { item: EngineeringNote['images'][number] }) {
  const { t } = useTranslation()
  const [failed, setFailed] = useState(false)
  return failed ? <span className="text-xs text-muted">{t('notes.imageGone')}</span> : <img className="h-32 max-w-full rounded object-contain" src={typeof item === 'string' ? imageUrl(item, 320) : fixedImageUrl(item.id, 320)} alt={typeof item === 'string' ? t('notes.images') : item.name} onError={() => setFailed(true)} />
}

function NoteForm({ initial, onSaved, onCancel }: { initial: Partial<EngineeringNote>; onSaved: (row: EngineeringNote) => Promise<void>; onCancel: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const [form, setForm] = useState(initial)
  const [conditions, setConditions] = useState(() => Object.entries(initial.conditions ?? {}).map(([key, value]) => ({ key, text: typeof value === 'string' ? value : JSON.stringify(value), original: value })))
  const [images, setImages] = useState(initial.images ?? [])
  const [runs, setRuns] = useState((initial.runs ?? []).join('\n'))
  const [busy, setBusy] = useState(false)
  const auth = useAuth()
  const flows = useFlows()
  const recipes = useRecipes(form.flow ?? null)
  const sources = useQuery({ queryKey: ['note-sources'], queryFn: () => api.get<{ items: { id: number; name: string }[] }>('/vision/sources'), enabled: auth.can('sources') })
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true)
    try {
      if (conditions.some((item) => !item.key.trim()) || new Set(conditions.map((item) => item.key.trim())).size !== conditions.length) throw new Error(t('notes.invalidConditions'))
      const parsedConditions = Object.fromEntries(conditions.map((item) => [item.key.trim(), item.text === (typeof item.original === 'string' ? item.original : JSON.stringify(item.original)) ? item.original : item.text]))
      const payload = { title: form.title ?? '', body: form.body ?? '', kind: form.kind ?? 'decision', project: form.project ?? '', part_number: form.part_number ?? '',
        flow: form.flow ?? null, recipe: form.recipe ?? null, source: form.source ?? null, applies_from_version: form.applies_from_version ?? null, applies_to_version: form.applies_to_version ?? null,
        conditions: parsedConditions, images, runs: runs.split('\n').map((r) => r.trim()).filter(Boolean), ...(!form.id && form.supersedes ? { supersedes: form.supersedes } : {}) }
      const row = form.id ? await api.patch<EngineeringNote>(`/vision/notes/${form.id}`, payload) : await api.post<EngineeringNote>('/vision/notes', payload)
      await onSaved(row); toast.success(t('notes.saved'))
    } catch (error) { toast.error(errorMessage(error)) } finally { setBusy(false) }
  }
  return <form className="space-y-3" onSubmit={(e) => void save(e)}><h2 className="font-semibold">{t(form.id ? 'notes.edit' : 'notes.create')}</h2><fieldset className="space-y-3" disabled={busy}>
    {(['title', 'project', 'part_number'] as const).map((key) => <label className="label block" key={key}>{t(`notes.${key === 'title' ? 'noteTitle' : key}`)}<input className="input" required={key === 'title'} maxLength={key === 'part_number' ? 120 : 200} value={form[key] ?? ''} onChange={(e) => setForm({ ...form, [key]: e.target.value })} /></label>)}
    <label className="label block">{t('notes.kind')}<select className="input" value={form.kind ?? 'decision'} onChange={(e) => setForm({ ...form, kind: e.target.value as EngineeringNote['kind'] })}>{KINDS.map((kind) => <option key={kind} value={kind}>{t(`notes.kinds.${kind}`)}</option>)}</select></label>
    <label className="label block">{t('notes.body')}<textarea className="input min-h-28" required maxLength={12000} value={form.body ?? ''} onChange={(e) => setForm({ ...form, body: e.target.value })} /></label>
    <div className="grid gap-3 sm:grid-cols-2">{(['flow', 'recipe', 'source'] as const).map((key) => <label className="label" key={key}>{t(`notes.${key}`)}<select className="input" value={form[key] ?? ''} onChange={(e) => setForm({ ...form, [key]: e.target.value ? Number(e.target.value) : null, ...(key === 'flow' ? { recipe: null } : {}) })}><option value="">{t('common.none')}</option>{(key === 'flow' ? flows.data?.items : key === 'recipe' ? recipes.data?.items : sources.data?.items)?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>)}{(['applies_from_version', 'applies_to_version'] as const).map((key) => <label className="label" key={key}>{t(`notes.${key}`)}<input className="input" type="number" min="1" step="1" value={form[key] ?? ''} onChange={(e) => setForm({ ...form, [key]: e.target.value ? Number(e.target.value) : null })} /></label>)}</div>
    <p className="text-xs text-muted">{t('notes.versionHint')}</p>
    <div className="space-y-2"><h3 className="label">{t('notes.conditions')}</h3>{conditions.map((item, i) => <div key={i} className="flex flex-wrap items-end gap-2"><label className="label min-w-0 flex-1">{t('notes.conditionName')}<input className="input" required value={item.key} onChange={(e) => setConditions(conditions.map((v, j) => j === i ? { ...v, key: e.target.value } : v))} /></label><label className="label min-w-0 flex-1">{t('notes.conditionValue')}<input className="input" value={item.text} onChange={(e) => setConditions(conditions.map((v, j) => j === i ? { ...v, text: e.target.value } : v))} /></label><Button type="button" onClick={() => setConditions(conditions.filter((_, j) => j !== i))}>{t('notes.remove')}</Button></div>)}<Button type="button" onClick={() => setConditions([...conditions, { key: '', text: '', original: '' }])}>{t('notes.addCondition')}</Button></div>
    <ImagesField label={t('notes.images')} hint={t('notes.imagesHint')} value={images.filter((item) => typeof item !== 'string')} readOnly={busy} onChange={(value) => setImages([...(value as EngineeringNote['images']), ...images.filter((item) => typeof item === 'string')])} />
    {images.filter((item) => typeof item === 'string').map((item, i) => <div className="flex gap-2" key={i}><NoteImage item={item} /><Button type="button" onClick={() => setImages(images.filter((im) => im !== item))}>{t('notes.remove')}</Button></div>)}
    <label className="label block">{t('notes.runs')}<textarea className="input" value={runs} onChange={(e) => setRuns(e.target.value)} /><span className="text-xs text-muted">{t('notes.runsHint')}</span></label>
    {form.supersedes && <p className="text-warning">{t('notes.replaceHint', { id: form.supersedes })}</p>}
    <div className="flex gap-2"><Button type="submit">{t('notes.save')}</Button><Button type="button" onClick={onCancel}>{t('common.cancel')}</Button></div>
  </fieldset></form>
}
