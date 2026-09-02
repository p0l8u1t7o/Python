/**
 * 批次測試（BatchTestModal）：多張影像（檔案／拖放／從來源抓 N 張）用目前的圖跑一輪，
 * 顯示摘要（OK/NG/失敗、良率、平均／最大 ms）與結果表；可篩選、匯出 CSV、點某列在影像視窗檢視該次 run。
 * 影像 ref 受 KEEP_RUN_IMAGES=8 限制，被淘汰的顯示「影像已釋放」。
 */
import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Download, Eye, FolderOpen, Gem, ImageOff, Play, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Badge, Button, Checkbox, Modal, SegmentedControl, Select, StatusBadge, TextInput } from '@/components/ui'
import { api, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useBatchFromSource, useBatchTest, useGoldenMutations, useSources } from '@/lib/queries'
import type { BatchItem, BatchResult, FlowGraph } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'
import { formatValue } from './ResultsPanel'

const MAX_BATCH = 50

function csvCell(value: unknown): string {
  const text = typeof value === 'string' ? value : value === null || value === undefined ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function batchToCsv(result: BatchResult): string {
  const keys = [...new Set(result.items.flatMap((it) => Object.keys(it.outputs ?? {})))]
  const head = ['name', 'status', 'duration_ms', 'run_id', ...keys, 'error', 'error_node']
  const rows = result.items.map((it) => [it.name, it.status, it.duration_ms, it.run_id, ...keys.map((k) => csvCell(it.outputs?.[k])), it.error, it.error_node ?? ''].map(csvCell).join(','))
  return [head.join(','), ...rows].join('\r\n')
}

function Thumb({ item }: { item: BatchItem }) {
  const { t } = useTranslation()
  const [gone, setGone] = useState(!item.image_ref)
  if (gone) {
    return (
      <span className="flex h-12 w-16 items-center justify-center rounded bg-surface-muted text-[10px] text-subtle" title={t('batch.imageReleased')}>
        <ImageOff size={14} />
      </span>
    )
  }
  return <img src={imageUrl(item.image_ref, 96)} alt={item.name} className="h-12 w-16 rounded bg-surface-muted object-contain" onError={() => setGone(true)} />
}

export interface BatchTestModalProps {
  open: boolean
  onClose: () => void
  flowId: number
  /** 目前畫布的圖（未儲存） */
  graph: () => FlowGraph
  dirty: boolean
  execLocked: boolean
  /** 點某列 → 在影像視窗檢視那次 run（呼叫端抓 GET /runs/{id}） */
  onView: (item: BatchItem) => void
  /** 「請 AI 調整」後把新 graph 套回畫布 */
  onApplyGraph?: (graph: FlowGraph) => void
}

interface TuneResult {
  graph: FlowGraph
  rationale: string
  provider: string
  changes: string[]
  before: { ok: number; ng: number; failed: number }
  after: { ok: number; ng: number; failed: number } | null
  items: { name: string; before: string; after: string }[]
  applied: boolean
}

export function BatchTestModal(p: BatchTestModalProps) {
  const { t } = useTranslation()
  const toast = useToast()
  const sources = useSources()
  const batch = useBatchTest()
  const batchSource = useBatchFromSource()
  const fileInput = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([])
  const [useDraft, setUseDraft] = useState(true)
  const [sourceId, setSourceId] = useState('')
  const [count, setCount] = useState('10')
  const [result, setResult] = useState<BatchResult | null>(null)
  const [filter, setFilter] = useState<'all' | 'ng' | 'failed'>('all')
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const running = batch.isPending || batchSource.isPending
  const golden = useGoldenMutations(p.flowId)
  /** 勾選要存進 Golden Set 的列（run_id） */
  const [picked, setPicked] = useState<Set<string>>(new Set())
  /** 請 AI 依批次結果調整流程 */
  const [tuneText, setTuneText] = useState('')
  const [tuning, setTuning] = useState(false)
  const [tuneResult, setTuneResult] = useState<TuneResult | null>(null)

  async function tune() {
    if (!result || !tuneText.trim()) return
    setTuning(true)
    try {
      const runs = result.items.map((it) => ({ name: it.name, image_ref: it.image_ref ?? '', status: it.status, outputs: it.outputs }))
      const r = await api.post<TuneResult>('/vision/agent/tune', { graph: p.graph(), instruction: tuneText.trim(), runs })
      setTuneResult(r)
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setTuning(false)
    }
  }

  async function saveGolden() {
    if (!result) return
    const items = result.items.filter((it) => picked.has(it.run_id) && it.image_ref)
    if (!items.length) return
    try {
      const res = await golden.fromBatch.mutateAsync(items.map((it) => ({ image_ref: it.image_ref as string, name: it.name, expect_status: it.status === 'ok' ? 'ok' : it.status === 'ng' ? 'ng' : 'any' })))
      toast.success(t('golden.savedFromBatch', { count: res.created }))
      setPicked(new Set())
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  function addFiles(list: FileList | File[] | null) {
    if (!list) return
    const incoming = [...list].filter((f) => f.type.startsWith('image/') || /\.(png|jpe?g|bmp|tiff?|webp)$/i.test(f.name))
    // toast 要在 updater 外面呼叫，否則 React 會警告在 render 期間更新另一個元件（ToastProvider）
    const merged = [...files, ...incoming]
    if (merged.length > MAX_BATCH) toast.warning(t('batch.tooMany'))
    setFiles(merged.slice(0, MAX_BATCH))
  }

  async function runFiles() {
    if (!files.length) return
    try {
      const res = await batch.mutateAsync({ flowId: p.flowId, files, graph: useDraft ? p.graph() : null })
      setResult(res)
      setSelectedRun(null)
      setPicked(new Set())
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function runSource() {
    if (!sourceId) return
    try {
      const res = await batchSource.mutateAsync({ flowId: p.flowId, source_id: Number(sourceId), count: Math.max(1, Math.min(MAX_BATCH, Number(count) || 1)), graph: useDraft ? p.graph() : null })
      setResult(res)
      setSelectedRun(null)
      setPicked(new Set())
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  function exportCsv() {
    if (!result) return
    const blob = new Blob(['﻿', batchToCsv(result)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `batch-flow${p.flowId}-${new Date().toISOString().replace(/[:.]/g, '-')}.csv`
    a.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const shown = useMemo(() => {
    const items = result?.items ?? []
    if (filter === 'ng') return items.filter((it) => it.status === 'ng')
    if (filter === 'failed') return items.filter((it) => it.status !== 'ok' && it.status !== 'ng')
    return items
  }, [result, filter])
  const s = result?.summary
  const yieldPct = s && s.total ? Math.round((s.ok / s.total) * 1000) / 10 : null

  return (
    <Modal open={p.open} onClose={p.onClose} size="xl" title={t('batch.title')} description={t('batch.hint')}>
      <div className="space-y-4">
        {/* 輸入區 */}
        <div className="grid gap-3 lg:grid-cols-2">
          <div
            className={`flex flex-col gap-2 rounded-lg border border-dashed p-3 ${dragging ? 'border-brand bg-brand-soft/40' : 'border-line'}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files) }}
            data-testid="batch-drop"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" icon={<FolderOpen size={14} />} onClick={() => fileInput.current?.click()} data-testid="batch-pick">{t('batch.pickFiles')}</Button>
              <input ref={fileInput} type="file" accept="image/*" multiple className="hidden" data-testid="batch-input" onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
              <span className="text-xs text-muted">{files.length ? t('batch.files', { count: files.length }) : t('batch.dropHint')}</span>
              {files.length ? <button type="button" className="text-xs text-muted hover:underline" onClick={() => setFiles([])}>{t('batch.clear')}</button> : null}
            </div>
            <Button size="sm" variant="primary" icon={<Play size={14} />} disabled={!files.length || p.execLocked} loading={batch.isPending} onClick={() => void runFiles()} data-testid="batch-run">
              {batch.isPending ? t('batch.running', { count: files.length }) : t('batch.run')}
            </Button>
          </div>
          <div className="flex flex-col gap-2 rounded-lg border border-line p-3">
            <div className="flex flex-wrap items-end gap-2">
              <Select label={t('batch.fromSource')} className="!py-1 text-xs" value={sourceId} onChange={(e) => setSourceId(e.target.value)} placeholder="—" options={(sources.data?.items ?? []).map((src) => ({ value: String(src.id), label: src.name }))} data-testid="batch-source" />
              <TextInput label={t('batch.count')} type="number" min={1} max={MAX_BATCH} className="!w-20 !py-1 text-xs" value={count} onChange={(e) => setCount(e.target.value)} />
            </div>
            <Button size="sm" variant="primary" icon={<Play size={14} />} disabled={!sourceId || p.execLocked} loading={batchSource.isPending} onClick={() => void runSource()} data-testid="batch-run-source">
              {t('batch.grab', { count: Math.max(1, Math.min(MAX_BATCH, Number(count) || 1)) })}
            </Button>
          </div>
        </div>
        <Checkbox label={t('batch.useDraft')} checked={useDraft} onChange={setUseDraft} hint={p.dirty ? t('editor.unsaved') : undefined} />

        {/* 摘要 */}
        {s ? (
          <div className="grid grid-cols-4 gap-2 sm:grid-cols-8" data-testid="batch-summary">
            {[
              ['total', s.total, ''],
              ['ok', s.ok, 'text-ok'],
              ['ng', s.ng, 'text-warning'],
              ['failed', s.failed, 'text-critical'],
              ['yield', yieldPct === null ? '—' : `${yieldPct}%`, ''],
              ['avg', `${Math.round(s.avg_ms)} ms`, ''],
              ['max', `${Math.round(s.max_ms)} ms`, ''],
              ['wall', `${Math.round(s.wall_ms)} ms`, ''],
            ].map(([key, value, cls]) => (
              <div key={key as string} className="rounded-lg bg-surface-muted px-2 py-1.5 text-center">
                <p className="text-[10px] uppercase text-subtle">{t(`batch.summary.${key as string}`)}</p>
                <p className={`tnum text-sm font-semibold ${cls}`}>{value as string}</p>
              </div>
            ))}
          </div>
        ) : null}

        {/* 結果表 */}
        {result ? (
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <SegmentedControl size="sm" value={filter} onChange={setFilter} options={[{ value: 'all', label: t('batch.filterAll') }, { value: 'ng', label: t('batch.filterNg') }, { value: 'failed', label: t('batch.filterFailed') }]} />
              <span className="tnum text-xs text-muted">{shown.length} / {result.items.length}</span>
              <span className="ml-auto flex items-center gap-1">
                <button type="button" className="text-[11px] text-muted hover:underline" onClick={() => setPicked(new Set(shown.filter((it) => it.image_ref).map((it) => it.run_id)))} data-testid="batch-pick-all">{t('golden.selectAll')}</button>
                <button type="button" className="text-[11px] text-muted hover:underline" onClick={() => setPicked(new Set())}>{t('golden.selectNone')}</button>
                <span className="tnum text-[11px] text-muted">{t('golden.selected', { count: picked.size })}</span>
                <Button size="xs" icon={<Gem size={12} />} disabled={picked.size === 0} loading={golden.fromBatch.isPending} title={t('golden.saveFromBatchHint')} onClick={() => void saveGolden()} data-testid="batch-save-golden">{t('golden.saveFromBatch')}</Button>
                <Link to={`/flows/${p.flowId}/golden`} className="text-[11px] text-brand hover:underline" data-testid="batch-open-golden">{t('golden.openGolden')}</Link>
                <Button size="xs" icon={<Download size={12} />} onClick={exportCsv} data-testid="batch-csv">{t('batch.exportCsv')}</Button>
              </span>
            </div>
            <div className="max-h-[40vh] overflow-auto rounded-lg border border-line">
              <table className="w-full text-xs" data-testid="batch-table">
                <thead className="sticky top-0 bg-surface-muted text-[10px] uppercase text-subtle">
                  <tr>
                    <th className="px-2 py-1 text-left font-medium">{t('batch.cols2.pick')}</th>
                    <th className="px-2 py-1 text-left font-medium">{t('batch.cols.thumb')}</th>
                    <th className="px-2 py-1 text-left font-medium">{t('batch.cols.name')}</th>
                    <th className="px-2 py-1 text-left font-medium">{t('batch.cols.status')}</th>
                    <th className="px-2 py-1 text-right font-medium">{t('batch.cols.ms')}</th>
                    <th className="px-2 py-1 text-left font-medium">{t('batch.cols.outputs')}</th>
                    <th className="px-2 py-1 text-left font-medium">{t('batch.cols.error')}</th>
                    <th className="px-2 py-1" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {shown.map((it) => (
                    <tr key={it.run_id} className={`cursor-pointer hover:bg-surface-muted/70 ${selectedRun === it.run_id ? 'bg-brand-soft/40' : ''}`} onClick={() => { setSelectedRun(it.run_id); p.onView(it) }} data-testid="batch-row">
                      <td className="px-2 py-1" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" className="accent-[var(--brand)]" disabled={!it.image_ref} checked={picked.has(it.run_id)} onChange={(e) => setPicked((old) => { const next = new Set(old); if (e.target.checked) next.add(it.run_id); else next.delete(it.run_id); return next })} data-testid="batch-pick" />
                      </td>
                      <td className="px-2 py-1"><Thumb item={it} /></td>
                      <td className="max-w-[160px] truncate px-2 py-1" title={it.name}>{it.name}<span className="ml-1 tnum text-subtle">{it.width}×{it.height}</span></td>
                      <td className="px-2 py-1"><StatusBadge status={it.status} /></td>
                      <td className="tnum px-2 py-1 text-right">{Math.round(it.duration_ms)}</td>
                      <td className="max-w-[260px] truncate px-2 py-1 font-mono text-[10px] text-muted" title={JSON.stringify(it.outputs)}>
                        {Object.entries(it.outputs ?? {}).slice(0, 4).map(([k, v]) => `${k}=${formatValue(v)}`).join('  ') || '—'}
                      </td>
                      <td className="max-w-[200px] truncate px-2 py-1 text-critical" title={it.error}>{it.error ? `${it.error_node ? `[${it.error_node}] ` : ''}${it.error}` : ''}</td>
                      <td className="px-2 py-1 text-right"><Eye size={13} className="text-muted" aria-label={t('batch.viewRun')} /></td>
                    </tr>
                  ))}
                  {shown.length === 0 ? <tr><td colSpan={8} className="px-2 py-4 text-center text-muted">—</td></tr> : null}
                </tbody>
              </table>
            </div>
            {selectedRun ? <p className="mt-1 text-[11px] text-muted"><Badge tone="brand">{t('batch.viewing', { name: result.items.find((it) => it.run_id === selectedRun)?.name ?? '' })}</Badge></p> : null}

            {/* 請 AI 依這批結果調整流程／參數 */}
            <div className="mt-3 space-y-2 rounded-lg border border-line p-3" data-testid="batch-tune">
              <p className="flex items-center gap-1.5 text-xs font-semibold"><Sparkles size={13} className="text-brand" /> {t('agent.tuneTitle')}</p>
              <div className="flex gap-2">
                <input className="input flex-1 !py-1.5 text-xs" placeholder={t('agent.tunePlaceholder')} value={tuneText}
                  onChange={(e) => setTuneText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void tune() }} data-testid="batch-tune-input" />
                <Button size="sm" variant="primary" loading={tuning} disabled={!tuneText.trim() || p.execLocked} onClick={() => void tune()} data-testid="batch-tune-run">{t('agent.tune')}</Button>
              </div>
              {tuneResult ? (
                <div className="space-y-1.5 text-xs">
                  <p className="text-muted">{tuneResult.rationale}</p>
                  {tuneResult.changes.length ? <ul className="list-disc pl-4 text-[11px] text-muted">{tuneResult.changes.map((c, i) => <li key={i}>{c}</li>)}</ul> : null}
                  {tuneResult.applied && tuneResult.after ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="tnum">{t('agent.beforeAfter')}：OK {tuneResult.before.ok} → <b className="text-ok">{tuneResult.after.ok}</b>、NG {tuneResult.before.ng} → <b className="text-warning">{tuneResult.after.ng}</b>、{t('batch.summary.failed')} {tuneResult.before.failed} → <b className="text-critical">{tuneResult.after.failed}</b></span>
                      {p.onApplyGraph ? <Button size="xs" variant="primary" icon={<Check size={12} />} onClick={() => p.onApplyGraph?.(tuneResult.graph)} data-testid="batch-tune-apply">{t('agent.apply')}</Button> : null}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted">{running ? t('batch.running', { count: files.length || Number(count) }) : t('batch.noResults')}</p>
        )}
      </div>
    </Modal>
  )
}
