/**
 * 範本庫（TemplateGallery）：範本畫廊 Modal（卡片＋節點示意縮圖）、存為範本 Modal。
 * - mode="create"（流程頁）：選範本 → 選來源 → 輸入流程名稱 → onCreate(graph, name, description, missingSource)
 * - mode="load"（編輯器）：選範本 → 選來源（可不選）→ onLoad(graph, name, missingSource)
 * 管理員或擁有者可刪自訂範本（後端判斷；內建 422）。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2 } from 'lucide-react'

import { Badge, Button, ConfirmDialog, ErrorState, LoadingState, Modal, Select, TextArea, TextInput } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { useSources, useTemplateMutations, useTemplates } from '@/lib/queries'
import type { FlowGraph, FlowTemplate } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

/** 節點示意 SVG：依 position 佈局，畫方塊與連線。 */
export function TemplateThumb({ graph, className = '' }: { graph: FlowGraph; className?: string }) {
  const nodes = graph.nodes.filter((n) => n.type !== 'note')
  const W = 160
  const H = 72
  if (!nodes.length) return <svg viewBox={`0 0 ${W} ${H}`} className={className} />
  const xs = nodes.map((n) => n.position?.x ?? 0)
  const ys = nodes.map((n) => n.position?.y ?? 0)
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const spanX = Math.max(1, Math.max(...xs) - minX)
  const spanY = Math.max(1, Math.max(...ys) - minY)
  const bw = 22
  const bh = 12
  const pos = new Map(nodes.map((n) => [n.id, { x: 6 + ((n.position?.x ?? 0) - minX) / spanX * (W - 12 - bw), y: 6 + ((n.position?.y ?? 0) - minY) / spanY * (H - 12 - bh) }]))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={className} aria-hidden>
      {graph.edges.map((e, i) => {
        const a = pos.get(e.source)
        const b = pos.get(e.target)
        if (!a || !b) return null
        return <line key={i} x1={a.x + bw} y1={a.y + bh / 2} x2={b.x} y2={b.y + bh / 2} stroke="var(--content-subtle)" strokeWidth={1} />
      })}
      {nodes.map((n) => {
        const p = pos.get(n.id)!
        const fill = n.type === 'image_source' || n.type === 'fixed_image' ? 'var(--brand)' : n.type === 'judge' ? 'var(--ok)' : 'var(--content-muted)'
        return <rect key={n.id} x={p.x} y={p.y} width={bw} height={bh} rx={2} fill={fill} opacity={0.85} />
      })}
    </svg>
  )
}

function categoryLabel(t: (k: string, o?: Record<string, unknown>) => string, category: string): string {
  return t(`templates.categories.${category}`, { defaultValue: category })
}

export function TemplateCard({ template, selected, onSelect, canDelete, onDelete }: { template: FlowTemplate; selected: boolean; onSelect: () => void; canDelete: boolean; onDelete: () => void }) {
  const { t } = useTranslation()
  return (
    <button type="button" onClick={onSelect} className={`card relative flex flex-col gap-2 p-3 text-left transition hover:border-brand ${selected ? '!border-brand ring-2 ring-brand/30' : ''}`} data-testid="template-card" data-template-id={template.id}>
      <TemplateThumb graph={template.graph} className="h-16 w-full rounded bg-surface-muted" />
      <p className="truncate text-sm font-semibold">{template.name}</p>
      <p className="line-clamp-2 min-h-8 text-xs text-muted">{template.description || '—'}</p>
      <div className="flex flex-wrap items-center gap-1 text-[11px]">
        <Badge tone={template.source === 'builtin' ? 'brand' : 'neutral'}>{template.source === 'builtin' ? t('templates.builtin') : t('templates.custom')}</Badge>
        <Badge>{categoryLabel(t, template.category)}</Badge>
        <span className="tnum text-muted">{t('templates.steps', { count: template.node_count })}</span>
        {template.owner_name ? <span className="ml-auto truncate text-subtle">{template.owner_name}</span> : null}
      </div>
      {canDelete ? (
        <span className="absolute right-2 top-2 rounded bg-surface/80 p-1 text-critical hover:bg-critical-soft" role="button" aria-label={t('common.delete')} title={t('common.delete')} onClick={(e) => { e.stopPropagation(); onDelete() }} data-testid="template-delete">
          <Trash2 size={13} />
        </span>
      ) : null}
    </button>
  )
}

export interface TemplateGalleryProps {
  open: boolean
  onClose: () => void
  mode: 'create' | 'load'
  /** create：建立流程；load：載入畫布 */
  /** 回傳 false 表示使用者取消（例如載入範本前的確認），畫廊保留目前選取 */
  onPick: (result: { graph: FlowGraph; name: string; description: string; missingSource: boolean; template: FlowTemplate }) => Promise<void | boolean> | void | boolean
  /** load 模式用的節點 id 前綴 */
  prefix?: string
}

export function TemplateGallery({ open, onClose, mode, onPick, prefix }: TemplateGalleryProps) {
  const { t } = useTranslation()
  const toast = useToast()
  const auth = useAuth()
  const templates = useTemplates(open)
  const sources = useSources()
  const { remove, instantiate } = useTemplateMutations()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [sourceId, setSourceId] = useState('')
  const [name, setName] = useState('')
  const [nameTouched, setNameTouched] = useState(false)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [pendingDelete, setPendingDelete] = useState<FlowTemplate | null>(null)
  const [busy, setBusy] = useState(false)

  const items = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (templates.data?.items ?? []).filter((it) => (!category || it.category === category) && (!q || `${it.name} ${it.description} ${it.category}`.toLowerCase().includes(q)))
  }, [templates.data, query, category])
  const allItems = templates.data?.items ?? []
  const categoriesPresent = useMemo(() => GALLERY_ORDER.filter((c) => allItems.some((it) => it.category === c)).concat(Array.from(new Set(allItems.map((it) => it.category))).filter((c) => !GALLERY_ORDER.includes(c))), [allItems])
  const groups = useMemo(() => categoriesPresent.map((c) => ({ category: c, items: items.filter((it) => it.category === c) })).filter((g) => g.items.length), [categoriesPresent, items])
  const selected = items.find((it) => it.id === selectedId) ?? null
  const effectiveName = nameTouched ? name : selected?.name ?? ''
  const canManage = templates.data?.can_manage ?? false
  const myName = auth.me?.user?.username ?? ''

  async function confirm() {
    if (!selected) return
    if (mode === 'create' && !effectiveName.trim()) return toast.error(t('flows.nameRequired'))
    setBusy(true)
    try {
      const useSamples = sourceId === '' || sourceId === 'samples'
      const inst = await instantiate.mutateAsync({ id: selected.id, source_id: sourceId && sourceId !== 'samples' ? Number(sourceId) : null, prefix: mode === 'load' ? prefix : '', use_samples: useSamples })
      const done = await onPick({ graph: inst.graph, name: effectiveName.trim() || inst.name, description: inst.description, missingSource: inst.missing_source, template: selected })
      if (done === false) return
      setSelectedId(null)
      setName('')
      setNameTouched(false)
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function doDelete() {
    if (!pendingDelete) return
    try {
      await remove.mutateAsync(pendingDelete.id)
      toast.success(t('templates.deleted'))
      if (selectedId === pendingDelete.id) setSelectedId(null)
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setPendingDelete(null)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title={t('templates.gallery')}
      description={mode === 'create' ? t('templates.galleryHint') : t('templates.loadHint')}
      footer={
        <>
          <input className="input mr-auto !w-48 !py-1 text-xs" placeholder={`${t('common.search')}…`} value={query} onChange={(e) => setQuery(e.target.value)} />
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" disabled={!selected} loading={busy} onClick={() => void confirm()} data-testid="template-confirm">
            {mode === 'create' ? t('templates.createFlow') : t('templates.load')}
          </Button>
        </>
      }
    >
      {templates.isPending ? (
        <LoadingState compact />
      ) : templates.isError ? (
        <ErrorState error={templates.error} onRetry={() => void templates.refetch()} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
          <div className="max-h-[55vh] space-y-4 overflow-y-auto pr-1" data-testid="template-grid">
            <div className="flex flex-wrap gap-1" data-testid="template-categories">
              <Button size="xs" active={category === ''} onClick={() => setCategory('')}>{t('templates.allCategories')}</Button>
              {categoriesPresent.map((c) => (
                <Button key={c} size="xs" active={category === c} onClick={() => setCategory(category === c ? '' : c)}>{categoryLabel(t, c)} <span className="tnum text-muted">{allItems.filter((it) => it.category === c).length}</span></Button>
              ))}
            </div>
            {items.length === 0 ? <p className="py-8 text-center text-sm text-muted">{t('templates.empty')}</p> : null}
            {groups.map((g) => (
              <section key={g.category} data-testid={`template-group-${g.category}`}>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{categoryLabel(t, g.category)} <span className="tnum">({g.items.length})</span></h3>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {g.items.map((it) => (
              <TemplateCard key={it.id} template={it} selected={it.id === selectedId} onSelect={() => setSelectedId(it.id)} canDelete={it.source === 'custom' && (canManage || it.owner_name === myName)} onDelete={() => setPendingDelete(it)} />
            ))}
                </div>
              </section>
            ))}
          </div>
          <div className="space-y-3 border-t border-line pt-3 lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0">
            {selected ? (
              <>
                <p className="text-sm font-semibold">{selected.name}</p>
                <p className="text-xs text-muted">{selected.description}</p>
              </>
            ) : (
              <p className="text-xs text-muted">{t('templates.galleryHint')}</p>
            )}
            <Select
              label={t('templates.source')}
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              placeholder={selected?.has_samples ? t('templates.samplesOption') : t('templates.sourceNone')}
              options={[...(selected?.has_samples ? [{ value: 'samples', label: t('templates.samplesOption') }] : []), ...(sources.data?.items ?? []).map((s) => ({ value: String(s.id), label: `${s.name} (${s.kind})` }))]}
              data-testid="template-source"
            />
            {mode === 'create' ? (
              <TextInput label={t('templates.flowName')} required value={effectiveName} onChange={(e) => { setName(e.target.value); setNameTouched(true) }} onKeyDown={(e) => e.key === 'Enter' && void confirm()} data-testid="template-flow-name" />
            ) : null}
          </div>
        </div>
      )}
      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void doDelete()} title={t('templates.deleteTitle')} message={t('templates.deleteMessage', { name: pendingDelete?.name ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </Modal>
  )
}

const CATEGORIES = ['custom', 'count', 'quality', 'measure', 'detect', 'identify']
/** 畫廊分組順序：先教學，再依檢測目的，自訂最後 */
const GALLERY_ORDER = ['tutorial', 'count', 'measure', 'quality', 'detect', 'identify', 'custom']

/** 存為範本：名稱／說明／類別。 */
export function SaveTemplateModal({ open, onClose, graph, defaultName }: { open: boolean; onClose: () => void; graph: () => FlowGraph; defaultName: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { create } = useTemplateMutations()
  const [form, setForm] = useState({ name: '', description: '', category: 'custom' })
  const name = form.name || defaultName

  async function submit() {
    if (!name.trim()) return toast.error(t('flows.nameRequired'))
    try {
      const saved = await create.mutateAsync({ name: name.trim(), description: form.description, category: form.category, graph: graph() })
      toast.success(t('templates.saved', { name: saved.name }))
      setForm({ name: '', description: '', category: 'custom' })
      onClose()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('templates.saveAsTitle')}
      size="sm"
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={create.isPending} onClick={() => void submit()} data-testid="save-template-confirm">{t('common.save')}</Button>
        </>
      }
    >
      <div className="space-y-3">
        <TextInput label={t('common.name')} required autoFocus value={name} onChange={(e) => setForm({ ...form, name: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && void submit()} data-testid="save-template-name" />
        <TextArea label={t('common.description')} rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        <Select label={t('templates.category')} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} options={CATEGORIES.map((c) => ({ value: c, label: categoryLabel(t, c) }))} />
      </div>
    </Modal>
  )
}
