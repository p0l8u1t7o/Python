/**
 * Golden Set（GoldenPage）`/flows/:id/golden`：有期望值的影像集與回歸測試。
 *
 * - 案例表：縮圖（GET /golden/{case}/image 帶 token）、名稱、期望（ok／ng／any，直接改）、備註、上次結果（最新基準）。
 * - 新增：上傳影像（multipart images[]＋expect_status／note）；批次測試結果的「存為 Golden Set」走 from_batch（在 BatchTestModal）。
 * - 回歸：POST /regress {graph?, save_baseline?, fail_under?}；「用目前畫布未儲存的圖」取 lib/flowDraft.ts 的草稿。
 *   結果：KPI＋混淆矩陣，**regressed 清單置頂**，improved，全部案例表（篩選 mismatch／與基準不同）。
 * - 點縮圖／列：用該案例的 image_ref（只有 mismatch 的前 20 張有）再試跑一次（reuse_image_ref），在影像視窗顯示標記。
 */
import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Eye, FlaskConical, Gem, ImageOff, Play, Trash2, TriangleAlert, Upload } from 'lucide-react'

import { formatValue } from '@/components/editor/ResultsPanel'
import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, CardBody, CardHeader, Checkbox, ConfirmDialog, EmptyRow, ErrorState, LoadingState, Modal, PageHeader, SegmentedControl, Select, StatusBadge, TBody, THead, Table, Td, TextInput, Th, Tr } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { goldenImageUrl, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useFlowSession } from '@/lib/flowDraft'
import { previewFlow, useFlow, useGolden, useGoldenBaseline, useGoldenMutations } from '@/lib/queries'
import type { ExpectStatus, GoldenCase, RegressCase, RegressChange, RegressResult, RunReport } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'
import { sourceRefOf } from './FlowEditorPage'

const EXPECTS: ExpectStatus[] = ['ok', 'ng', 'any']

function CaseThumb({ flowId, c }: { flowId: number; c: GoldenCase }) {
  const [gone, setGone] = useState(false)
  if (gone) return <span className="flex h-12 w-16 items-center justify-center rounded bg-surface-muted text-subtle"><ImageOff size={14} /></span>
  return <img src={goldenImageUrl(flowId, c.id, 96)} alt={c.name} className="h-12 w-16 rounded bg-surface-muted object-contain" onError={() => setGone(true)} />
}

function Kpi({ label, value, tone = '' }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded-lg bg-surface-muted px-2 py-1.5 text-center">
      <p className="text-[10px] uppercase text-subtle">{label}</p>
      <p className={`tnum text-sm font-semibold ${tone}`}>{value}</p>
    </div>
  )
}

function GoldenPageInner({ flowId }: { flowId: number }) {
  const { t } = useTranslation()
  const toast = useToast()
  const flow = useFlow(flowId)
  const golden = useGolden(flowId)
  const baseline = useGoldenBaseline(flowId)
  const { upload, patch, remove, regress } = useGoldenMutations(flowId)
  const session = useFlowSession(flowId)
  const fileInput = useRef<HTMLInputElement>(null)

  const [uploadExpect, setUploadExpect] = useState<ExpectStatus>('ok')
  const [uploadNote, setUploadNote] = useState('')
  const [useDraft, setUseDraft] = useState(false)
  const [saveBaseline, setSaveBaseline] = useState(false)
  const [failUnder, setFailUnder] = useState('')
  const [result, setResult] = useState<RegressResult | null>(null)
  const [filter, setFilter] = useState<'all' | 'mismatch' | 'changed'>('all')
  const [pendingDelete, setPendingDelete] = useState<GoldenCase | null>(null)
  const [viewing, setViewing] = useState<{ name: string; run: RunReport | null; loading: boolean } | null>(null)

  const draft = session.draft && flow.data && session.draft.baseVersion === flow.data.version && session.draft.dirty ? session.draft : null
  const canManage = golden.data?.can_manage ?? false
  const baselineResults = baseline.data?.baseline?.results ?? {}
  const cases = golden.data?.items ?? []

  async function onUpload(files: FileList | null) {
    const list = files ? [...files] : []
    if (!list.length) return
    try {
      const res = await upload.mutateAsync({ files: list, expect_status: uploadExpect, note: uploadNote })
      toast.success(t('golden.uploaded', { count: res.created }))
      setUploadNote('')
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function patchCase(id: number, body: { name?: string; expect_status?: ExpectStatus; note?: string }) {
    try {
      await patch.mutateAsync({ id, ...body })
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function onDelete() {
    if (!pendingDelete) return
    try {
      await remove.mutateAsync(pendingDelete.id)
      toast.success(t('golden.deleted'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setPendingDelete(null)
    }
  }

  async function runRegress() {
    const fu = failUnder.trim() === '' ? null : Number(failUnder)
    try {
      const res = await regress.mutateAsync({ graph: useDraft && draft ? draft.graph : null, save_baseline: saveBaseline, fail_under: fu })
      setResult(res)
      setFilter(res.mismatch ? 'mismatch' : 'all')
      if (res.baseline_saved) toast.success(t('golden.baselineSaved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  /** 用案例影像再試跑一次，取得標記。 */
  async function view(name: string, imageRef: string | null) {
    if (!imageRef) return toast.warning(t('golden.imageGone'))
    setViewing({ name, run: null, loading: true })
    try {
      const graph = useDraft && draft ? draft.graph : flow.data?.graph
      if (!graph) return
      const run = await previewFlow({ flowId, graph, reuse_image_ref: imageRef })
      setViewing({ name, run, loading: false })
    } catch (error) {
      toast.error(errorMessage(error))
      setViewing(null)
    }
  }

  const caseById = useMemo(() => new Map((result?.cases ?? []).map((c) => [c.case_id, c])), [result])
  const shownCases = useMemo(() => {
    const items = result?.cases ?? []
    if (filter === 'mismatch') return items.filter((c) => !c.match)
    if (filter === 'changed') return items.filter((c) => c.changed_since_baseline)
    return items
  }, [result, filter])

  const viewRun = viewing?.run ?? null
  const viewPayloads = useMemo(() => new Map((flow.data?.graph.nodes ?? []).map((n) => [n.id, n])), [flow.data])
  const viewRef = viewRun ? sourceRefOf(viewRun, viewPayloads) : null
  const viewSize = useMemo(() => {
    if (!viewRun) return { w: 0, h: 0 }
    for (const rep of Object.values(viewRun.nodes)) {
      const img = Object.values(rep.outputs).find((v) => v && typeof v === 'object' && 'width' in (v as object)) as { width: number; height: number } | undefined
      if (img) return { w: img.width, h: img.height }
    }
    return { w: 0, h: 0 }
  }, [viewRun])
  const viewOverlays = viewRun ? Object.values(viewRun.nodes).flatMap((n) => n.overlays ?? []) : []

  function ChangeRow({ item, tone }: { item: RegressChange; tone: 'critical' | 'ok' }) {
    const c = caseById.get(item.case_id)
    return (
      <li className={`flex items-center gap-3 rounded-lg border px-3 py-2 ${tone === 'critical' ? 'border-critical/40 bg-critical-soft' : 'border-ok/40 bg-ok-soft'}`} data-testid={tone === 'critical' ? 'regressed-row' : 'improved-row'}>
        <button type="button" className="shrink-0" title={t('golden.viewImageHint')} onClick={() => void view(item.name, c?.image_ref ?? null)}>
          {c?.image_ref ? <img src={imageUrl(c.image_ref, 96)} alt={item.name} className="h-12 w-16 rounded bg-surface-muted object-contain" /> : <span className="flex h-12 w-16 items-center justify-center rounded bg-surface-muted text-subtle" title={t('golden.imageGone')}><ImageOff size={14} /></span>}
        </button>
        <div className="min-w-0 flex-1 text-xs">
          <p className="truncate font-semibold">{item.name}</p>
          <p className="flex flex-wrap items-center gap-1.5">
            <StatusBadge status={item.was ?? null} /> → <StatusBadge status={item.now} />
            {item.node ? <span className="font-mono text-muted">@{item.node}</span> : null}
          </p>
          {item.reasons?.length ? <p className="text-muted">{item.reasons.join('；')}</p> : null}
          {item.error ? <p className="truncate text-critical" title={item.error}>{item.error}</p> : null}
        </div>
        <Button size="xs" icon={<Eye size={12} />} onClick={() => void view(item.name, c?.image_ref ?? null)}>{t('golden.viewImage')}</Button>
      </li>
    )
  }

  const confusion = result?.confusion
  const total = golden.data?.total ?? 0

  return (
    <Page wide>
      <PageHeader
        title={<span className="flex items-center gap-2"><Gem size={20} className="text-brand" />{t('golden.title')}{flow.data ? <span className="text-muted">· {flow.data.name}</span> : null}</span>}
        description={t('golden.subtitle')}
        actions={<Link to={`/flows/${flowId}`}><Button size="sm" icon={<ArrowLeft size={14} />}>{t('golden.back')}</Button></Link>}
      />

      {/* 回歸控制列 */}
      <Card className="mb-4">
        <CardBody className="flex flex-wrap items-end gap-3">
          <Checkbox label={t('golden.useDraft')} hint={draft ? t('editor.unsaved') : t('golden.useDraftHint')} checked={useDraft && Boolean(draft)} disabled={!draft} onChange={setUseDraft} />
          <Checkbox label={t('golden.saveBaseline')} hint={t('golden.saveBaselineHint')} checked={saveBaseline} disabled={!canManage} onChange={setSaveBaseline} />
          <TextInput label={t('golden.failUnder')} hint={t('golden.failUnderHint')} type="number" min={0} max={1} step={0.01} className="!w-28" value={failUnder} onChange={(e) => setFailUnder(e.target.value)} data-testid="golden-fail-under" />
          <span title={t('golden.regressHint')}>
            <Button variant="primary" icon={<Play size={14} />} loading={regress.isPending} disabled={total === 0} onClick={() => void runRegress()} data-testid="golden-regress">
              {regress.isPending ? t('golden.regressing', { count: total }) : t('golden.regress')}
            </Button>
          </span>
          <span className="ml-auto text-xs text-muted" data-testid="golden-baseline">
            {baseline.data?.baseline ? t('golden.baselineVersion', { version: baseline.data.baseline.flow_version, time: new Date(baseline.data.baseline.created_at).toLocaleString() }) : t('golden.baselineNone')}
          </span>
        </CardBody>
      </Card>

      {/* 回歸結果 */}
      {result ? (
        <div data-testid="golden-result">
        <Card className="mb-4">
          <CardHeader
            title={<span className="flex items-center gap-2"><FlaskConical size={16} className="text-brand" />{t('golden.result')} <Badge tone={result.passed ? 'ok' : 'critical'}>{result.passed ? t('golden.passed') : t('golden.notPassed')}</Badge>{result.baseline_saved ? <Badge tone="brand">{t('golden.baselineSaved')}</Badge> : null}{result.graph_override ? <Badge>{t('golden.useDraft')}</Badge> : null}</span>}
            description={`v${result.flow_version} · ${Math.round(result.duration_ms)} ms${result.baseline_version !== null ? ` · ${t('golden.baseline')} v${result.baseline_version}` : ''}`}
          />
          <CardBody className="space-y-4">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8" data-testid="golden-kpi">
              <Kpi label={t('golden.kpi.total')} value={result.total} />
              <Kpi label={t('golden.kpi.match')} value={result.match} tone="text-ok" />
              <Kpi label={t('golden.kpi.mismatch')} value={result.mismatch} tone={result.mismatch ? 'text-critical' : ''} />
              <Kpi label={t('golden.kpi.matchRate')} value={`${Math.round(result.match_rate * 1000) / 10}%`} />
              {confusion ? (
                <>
                  <Kpi label={t('golden.confusion.tp')} value={confusion.tp} tone="text-ok" />
                  <Kpi label={t('golden.confusion.fn')} value={confusion.fn} tone={confusion.fn ? 'text-critical' : ''} />
                  <Kpi label={t('golden.confusion.fp')} value={confusion.fp} tone={confusion.fp ? 'text-critical' : ''} />
                  <Kpi label={t('golden.confusion.tn')} value={confusion.tn} tone="text-ok" />
                </>
              ) : null}
            </div>

            <div>
              <p className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-critical"><TriangleAlert size={15} /> {t('golden.regressed')} <span className="tnum font-normal">({result.regressed.length})</span> <span className="text-xs font-normal text-muted">· {t('golden.regressedHint')}</span></p>
              {result.regressed.length === 0 ? <p className="text-xs text-muted" data-testid="no-regressed">{t('golden.noRegressed')}</p> : <ul className="space-y-1.5">{result.regressed.map((r) => <ChangeRow key={r.case_id} item={r} tone="critical" />)}</ul>}
            </div>
            {result.improved.length ? (
              <div>
                <p className="mb-1 text-sm font-semibold text-ok">{t('golden.improved')} <span className="tnum font-normal">({result.improved.length})</span></p>
                <ul className="space-y-1.5">{result.improved.map((r) => <ChangeRow key={r.case_id} item={r} tone="ok" />)}</ul>
              </div>
            ) : null}

            <div>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <p className="text-sm font-semibold">{t('golden.allCases')}</p>
                <SegmentedControl size="sm" value={filter} onChange={setFilter} options={[{ value: 'all', label: t('golden.filterAll') }, { value: 'mismatch', label: t('golden.filterMismatch') }, { value: 'changed', label: t('golden.filterChanged') }]} />
                <span className="tnum text-xs text-muted">{shownCases.length} / {result.cases.length}</span>
              </div>
              <div className="max-h-[50vh] overflow-auto rounded-lg border border-line">
                <table className="w-full text-xs" data-testid="golden-cases-result">
                  <thead className="sticky top-0 bg-surface-muted text-[10px] uppercase text-subtle">
                    <tr>
                      <th className="px-2 py-1 text-left font-medium">{t('golden.cols.thumb')}</th>
                      <th className="px-2 py-1 text-left font-medium">{t('golden.cols.name')}</th>
                      <th className="px-2 py-1 text-left font-medium">{t('golden.cols.expect')}</th>
                      <th className="px-2 py-1 text-left font-medium">{t('golden.cols.status')}</th>
                      <th className="px-2 py-1 text-left font-medium">{t('golden.cols.was')}</th>
                      <th className="px-2 py-1 text-center font-medium">{t('golden.cols.match')}</th>
                      <th className="px-2 py-1 text-right font-medium">{t('golden.cols.ms')}</th>
                      <th className="px-2 py-1 text-left font-medium">{t('golden.cols.outputs')}</th>
                      <th className="px-2 py-1 text-left font-medium">{t('golden.cols.reasons')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {shownCases.map((c: RegressCase) => (
                      <tr key={c.case_id} className={`hover:bg-surface-muted/70 ${c.match ? '' : 'bg-critical-soft/40'} ${c.image_ref ? 'cursor-pointer' : ''}`} onClick={() => c.image_ref && void view(c.name, c.image_ref)} data-testid="golden-result-row">
                        <td className="px-2 py-1">{c.image_ref ? <img src={imageUrl(c.image_ref, 96)} alt={c.name} className="h-10 w-14 rounded bg-surface-muted object-contain" /> : <span className="flex h-10 w-14 items-center justify-center rounded bg-surface-muted text-subtle" title={t('golden.imageGone')}><ImageOff size={12} /></span>}</td>
                        <td className="max-w-[160px] truncate px-2 py-1 font-medium" title={c.name}>{c.name}</td>
                        <td className="px-2 py-1"><Badge>{t(`golden.expect${c.expect === 'ok' ? 'Ok' : c.expect === 'ng' ? 'Ng' : 'Any'}`)}</Badge></td>
                        <td className="px-2 py-1"><StatusBadge status={c.status} /></td>
                        <td className="px-2 py-1"><StatusBadge status={c.was ?? null} /></td>
                        <td className="px-2 py-1 text-center">{c.match ? <span className="text-ok">✓</span> : <span className="font-semibold text-critical">✗</span>}</td>
                        <td className="tnum px-2 py-1 text-right">{Math.round(c.duration_ms)}</td>
                        <td className="max-w-[220px] truncate px-2 py-1 font-mono text-[10px] text-muted" title={JSON.stringify(c.outputs)}>{Object.entries(c.outputs ?? {}).slice(0, 4).map(([k, v]) => `${k}=${formatValue(v)}`).join('  ') || '—'}</td>
                        <td className="max-w-[220px] truncate px-2 py-1 text-critical" title={[...(c.reasons ?? []), c.error].filter(Boolean).join('\n')}>{[...(c.reasons ?? []), c.error].filter(Boolean).join('；')}</td>
                      </tr>
                    ))}
                    {shownCases.length === 0 ? <tr><td colSpan={9} className="px-2 py-4 text-center text-muted">—</td></tr> : null}
                  </tbody>
                </table>
              </div>
            </div>
          </CardBody>
        </Card>
        </div>
      ) : null}

      {/* 案例表 */}
      <Card className="overflow-hidden">
        <CardHeader
          title={<span>{t('golden.cases')} <span className="tnum font-normal text-muted">({total})</span></span>}
          actions={
            canManage ? (
              <span className="flex flex-wrap items-end gap-2" title={t('golden.uploadHint')}>
                <Select label={t('golden.uploadExpect')} className="!py-1 text-xs" value={uploadExpect} onChange={(e) => setUploadExpect(e.target.value as ExpectStatus)} options={EXPECTS.map((v) => ({ value: v, label: t(`golden.expect${v === 'ok' ? 'Ok' : v === 'ng' ? 'Ng' : 'Any'}`) }))} data-testid="golden-upload-expect" />
                <TextInput label={t('golden.uploadNote')} className="!w-40 !py-1 text-xs" value={uploadNote} onChange={(e) => setUploadNote(e.target.value)} />
                <Button size="sm" variant="primary" icon={<Upload size={14} />} loading={upload.isPending} onClick={() => fileInput.current?.click()} data-testid="golden-upload">{t('golden.upload')}</Button>
                <input ref={fileInput} type="file" accept="image/*" multiple className="hidden" data-testid="golden-upload-input" onChange={(e) => { void onUpload(e.target.files); e.target.value = '' }} />
              </span>
            ) : (
              <span className="text-xs text-muted">{t('golden.readOnly')}</span>
            )
          }
        />
        {golden.isPending ? (
          <LoadingState compact />
        ) : golden.isError ? (
          <ErrorState error={golden.error} onRetry={() => void golden.refetch()} />
        ) : (
          <Table>
            <THead>
              <Th>{t('golden.cols.thumb')}</Th>
              <Th>{t('golden.cols.name')}</Th>
              <Th>{t('golden.cols.expect')}</Th>
              <Th>{t('golden.cols.note')}</Th>
              <Th>{t('golden.lastResult')}</Th>
              <Th>{t('golden.cols.created')}</Th>
              <Th align="right">{t('common.actions')}</Th>
            </THead>
            <TBody>
              {cases.length === 0 ? (
                <EmptyRow colSpan={7} message={t('golden.empty')} />
              ) : (
                cases.map((c) => {
                  const last = baselineResults[String(c.id)]
                  return (
                    <Tr key={c.id}>
                      <Td><CaseThumb flowId={flowId} c={c} /></Td>
                      <Td>
                        <input className="input !py-1 text-xs" defaultValue={c.name} disabled={!canManage} onBlur={(e) => e.target.value.trim() && e.target.value.trim() !== c.name && void patchCase(c.id, { name: e.target.value.trim() })} data-testid="golden-case-name" />
                      </Td>
                      <Td>
                        <select className="input !w-24 !py-1 text-xs" value={c.expect_status} disabled={!canManage} onChange={(e) => void patchCase(c.id, { expect_status: e.target.value as ExpectStatus })} data-testid="golden-case-expect">
                          {EXPECTS.map((v) => <option key={v} value={v}>{t(`golden.expect${v === 'ok' ? 'Ok' : v === 'ng' ? 'Ng' : 'Any'}`)}</option>)}
                        </select>
                      </Td>
                      <Td><input className="input !py-1 text-xs" defaultValue={c.note} disabled={!canManage} onBlur={(e) => e.target.value !== c.note && void patchCase(c.id, { note: e.target.value })} /></Td>
                      <Td>{last ? <span className="flex items-center gap-1"><StatusBadge status={last.status} /><span className="tnum text-[11px] text-muted">{Math.round(last.duration_ms)} ms</span></span> : <span className="text-xs text-subtle">{t('golden.noBaseline')}</span>}</Td>
                      <Td className="tnum text-xs text-muted">{new Date(c.created_at).toLocaleString()}</Td>
                      <Td align="right">
                        <button type="button" className="btn-icon" title={canManage ? t('common.delete') : t('golden.readOnly')} disabled={!canManage} onClick={() => setPendingDelete(c)} data-testid="golden-case-delete"><Trash2 size={15} className="text-critical" /></button>
                      </Td>
                    </Tr>
                  )
                })
              )}
            </TBody>
          </Table>
        )}
      </Card>

      <Modal open={viewing !== null} onClose={() => setViewing(null)} title={viewing ? t('golden.viewing', { name: viewing.name }) : ''} size="xl">
        {viewing?.loading ? (
          <LoadingState compact />
        ) : viewRun ? (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <StatusBadge status={viewRun.status} />
              <span className="tnum text-muted">{Math.round(viewRun.duration_ms)} ms</span>
              {viewRun.error ? <span className="text-critical">{viewRun.error}</span> : null}
              <span className="font-mono text-muted">{Object.entries(viewRun.outputs).slice(0, 6).map(([k, v]) => `${k}=${formatValue(v)}`).join('  ')}</span>
            </div>
            <div className="h-[65vh] rounded-lg bg-viewer">
              <ImageViewer src={viewRef ? imageUrl(viewRef, 1600) : null} imageWidth={viewSize.w} imageHeight={viewSize.h} overlays={viewOverlays} toolbar className="h-full w-full" badge={{ text: t(`status.${viewRun.status}`), tone: viewRun.status === 'ok' ? 'ok' : viewRun.status === 'ng' || viewRun.status === 'failed' ? 'ng' : 'neutral' }} />
            </div>
          </div>
        ) : null}
      </Modal>
      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void onDelete()} title={t('golden.deleteTitle')} message={t('golden.deleteMessage', { name: pendingDelete?.name ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </Page>
  )
}

export function GoldenPage() {
  const { flowId } = useParams<{ flowId: string }>()
  const id = Number(flowId)
  if (!flowId || Number.isNaN(id)) return null
  return <GoldenPageInner key={id} flowId={id} />
}
