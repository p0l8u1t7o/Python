/**
 * 批次測試（/batch）：影像集（上傳／來源，跨流程共用）→ 選「測試流程」→ 批量執行（背景、進度）→ 每次結果暫存 → 期望標記與命中率 →
 * 洞察（建議門檻）→ 調參重跑／比較 → 寫回流程／存為配方／帶回編輯器 → AI 諮詢與調整（結果成為新的一次執行）。
 * 查詢參數：?flow=&set=&run=&draft=1（編輯器頂列「批次測試」帶草稿過來）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { BarChart3, GitCompare, Images, ListChecks, SlidersHorizontal } from 'lucide-react'

import { BatchComparePanel } from '@/components/batch/BatchCompare'
import { runTitle } from '@/components/batch/BatchRunList'
import { BatchImagesGrid } from '@/components/batch/BatchImagesGrid'
import { BatchInsightsPanel } from '@/components/batch/BatchInsights'
import { BatchRowPreviewModal } from '@/components/batch/BatchRowPreviewModal'
import { BatchRunDetail } from '@/components/batch/BatchRunDetail'
import { BatchRunList } from '@/components/batch/BatchRunList'
import { BatchSetList } from '@/components/batch/BatchSetList'
import { BatchTunePanel } from '@/components/batch/BatchTunePanel'
import { NewSetModal } from '@/components/batch/NewSetModal'
import { Page } from '@/components/layout/AppShell'
import { compactOverrides } from '@/components/recipes/RecipeDrawer'
import { Card, Checkbox, ConfirmDialog, EmptyState, PageHeader, Select, Tabs } from '@/components/ui'
import { RUNNING, applySuggestions, fetchCompare, paramDiff, useBatchInsights, useBatchMutations, useBatchRun, useBatchRuns, useBatchSet, useBatchSets, type BatchCompare, type BatchRun, type BatchSet, type Expected, type Suggestion } from '@/lib/batch'
import { useRegisterAssistantContext } from '@/lib/assistantContext'
import { errorMessage } from '@/lib/errors'
import { setDraft, useFlowSession } from '@/lib/flowDraft'
import { useFlow, useFlowMutations, useFlows, useRecipeMutations, useToolTypes } from '@/lib/queries'
import type { FlowGraph, ToolTypeDef } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

type TabKey = 'result' | 'images' | 'insights' | 'compare' | 'tune'

function num(v: string | null): number | null {
  const n = v ? Number(v) : NaN
  return Number.isFinite(n) ? n : null
}

export function BatchPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()
  const auth = useAuth()
  const [params, setParams] = useSearchParams()
  const flows = useFlows()
  const flowParam = num(params.get('flow'))
  const flowId = flowParam ?? (flows.data?.items[0]?.id ?? null)
  const flow = useFlow(flowId)
  const catalogue = useToolTypes()
  const defs = useMemo(() => new Map<string, ToolTypeDef>((catalogue.data?.items ?? []).map((d) => [d.key, d])), [catalogue.data])
  const sets = useBatchSets()
  const [setId, setSetId] = useState<number | null>(num(params.get('set')))
  const [runId, setRunId] = useState<number | null>(num(params.get('run')))
  const [compareId, setCompareId] = useState<number | null>(null)
  const [compare, setCompare] = useState<BatchCompare | null>(null)
  const [tab, setTab] = useState<TabKey>('result')
  const [graph, setGraph] = useState<FlowGraph | null>(null)
  //: 工作圖的來源鍵：draft｜run:<id>（同流程才沿用）｜flow:<id>:<version>
  const [graphSource, setGraphSource] = useState<string>('')
  const [newOpen, setNewOpen] = useState(false)
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const [pendingDelete, setPendingDelete] = useState<{ kind: 'set' | 'run'; id: number; name: string; setId: number } | null>(null)
  const [useDraft, setUseDraft] = useState(params.get('draft') === '1')
  const set = useBatchSet(setId)
  const runs = useBatchRuns(setId)
  const run = useBatchRun(runId)
  const insights = useBatchInsights(runId, run.data?.status === 'done')
  const mut = useBatchMutations(flowId)
  const flowMut = useFlowMutations()
  const recipeMut = useRecipeMutations(flowId ?? 0)
  const session = useFlowSession(flowId ?? 0)
  const draft = session.draft && flow.data && session.draft.baseVersion === flow.data.version && session.draft.dirty ? session.draft : null
  const canEditFlow = auth.isEngineer
  const canManage = set.data?.can_manage ?? true
  const setItems = useMemo(() => sets.data?.items ?? [], [sets.data])
  const runItems = useMemo(() => runs.data?.items ?? [], [runs.data])
  const hasLabels = Boolean(set.data && (set.data.labeled.ok + set.data.labeled.ng) > 0)

  // ---- URL 同步 ----
  useEffect(() => {
    const next = new URLSearchParams(params)
    if (flowId) next.set('flow', String(flowId)); else next.delete('flow')
    if (setId) next.set('set', String(setId)); else next.delete('set')
    if (runId) next.set('run', String(runId)); else next.delete('run')
    if (next.toString() !== params.toString()) setParams(next, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowId, setId, runId])

  // ---- 選第一個影像集／最新執行 ----
  useEffect(() => {
    // isFetching 時不動：剛建立的影像集在清單重抓完成前不算「不存在」，否則選取會被舊清單蓋掉
    if (!sets.data || sets.isFetching) return
    if (setId === null || !setItems.some((s) => s.id === setId)) setSetId(setItems[0]?.id ?? null)
  }, [sets.data, sets.isFetching, setItems, setId])
  useEffect(() => {
    if (!runs.data) return
    if (runId === null || !runItems.some((r) => r.id === runId)) setRunId(runItems[0]?.id ?? null)
    if (compareId !== null && !runItems.some((r) => r.id === compareId)) setCompareId(null)
  }, [runs.data, runItems, runId, compareId])
  // ---- 工作圖：勾草稿用草稿；同流程的執行沿用該次 graph；換測試流程用該流程的現圖 ----
  const graphKey = useDraft && draft ? 'draft'
    : run.data?.graph && run.data.flow_id === flowId ? `run:${run.data.id}`
      : flow.data ? `flow:${flow.data.id}:${flow.data.version}` : ''
  useEffect(() => {
    if (!graphKey || graphKey === graphSource) return
    const next = graphKey === 'draft' ? draft?.graph : graphKey.startsWith('run:') ? run.data?.graph : flow.data?.graph
    if (!next) return
    setGraph(next)
    setGraphSource(graphKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphKey])
  // ---- 執行結束：影像集清單的「最近執行」與洞察要跟著更新 ----
  const runStatus = run.data?.status
  useEffect(() => {
    if (runStatus && !RUNNING.has(runStatus) && setId !== null) mut.invalidateSet(setId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runStatus, run.data?.id])
  // ---- 比較 ----
  useEffect(() => {
    if (runId === null || compareId === null) { setCompare(null); return }
    let alive = true
    fetchCompare(runId, compareId).then((c) => { if (alive) setCompare(c) }).catch((e) => { if (alive) toast.error(errorMessage(e)) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, compareId, run.data?.status])

  /** 換測試流程：影像集與執行紀錄留著（同一組影像可以比不同流程），工作圖交給 graphKey 重取。 */
  const selectFlow = useCallback((id: number) => {
    setCompareId(null)
    const next = new URLSearchParams(params)
    next.set('flow', String(id))
    setParams(next, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, setParams])

  /** 選影像集：預設把測試流程切回它所屬的流程（要測別的流程再改上方選單）。 */
  const selectSet = useCallback((id: number, setFlowId: number | null) => {
    setSetId(id); setRunId(null); setCompareId(null)
    if (setFlowId !== null && setFlowId !== flowId) selectFlow(setFlowId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowId, selectFlow])

  async function startRun(g: FlowGraph | null, opts: { origin?: 'manual' | 'draft'; label?: string; mode?: 'run' | 'autotune' } = {}, targetSetId: number | null = setId) {
    if (targetSetId === null) return
    try {
      // parent 只在同一個影像集內有意義（後端會擋）：剛建立的影像集不能接上一個影像集的執行
      const parent = targetSetId === setId ? runId : null
      const r = await mut.startRun.mutateAsync({ setId: targetSetId, flow_id: flowId, graph: g, origin: opts.origin ?? (useDraft && draft ? 'draft' : 'manual'), label: opts.label ?? '', parent_run_id: parent, mode: opts.mode ?? 'run', max_evals: 40, deadline_s: 60 })
      setRunId(r.id)
      setTab('result')
      toast.success(t('batchPage.started', { id: r.id }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function label(index: number, expected: Expected) {
    if (setId === null) return
    try { await mut.patchSet.mutateAsync({ id: setId, labels: [{ index, expected }] }) } catch (error) { toast.error(errorMessage(error)) }
  }
  async function group(index: number, value: 'tune' | 'accept') {
    if (setId === null) return
    try { await mut.patchSet.mutateAsync({ id: setId, labels: [{ index, group: value }] }) } catch (error) { toast.error(errorMessage(error)) }
  }
  async function bulkLabel(expected: Expected) {
    if (setId === null || !set.data?.images) return
    try { await mut.patchSet.mutateAsync({ id: setId, labels: set.data.images.map((im) => ({ index: im.index, expected })) }) } catch (error) { toast.error(errorMessage(error)) }
  }
  function apply(sugs: Suggestion[], andRun: boolean) {
    const base = graph ?? run.data?.graph ?? flow.data?.graph
    if (!base) return
    const next = applySuggestions(base, sugs)
    setGraph(next)
    if (andRun) void startRun(next, { label: t('batchPage.insights.appliedLabel') })
    else { setTab('tune'); toast.success(t('batchPage.insights.applied', { count: sugs.length })) }
  }
  async function saveFlow() {
    if (!flow.data || !graph) return
    try {
      const saved = await flowMut.patch.mutateAsync({ id: flow.data.id, graph })
      toast.success(t('batchPage.tune.savedFlow', { version: saved.version }))
    } catch (error) { toast.error(errorMessage(error)) }
  }
  async function saveRecipe(name: string) {
    if (!flow.data || !graph) return
    const overrides: Record<string, Record<string, unknown>> = {}
    for (const d of paramDiff(flow.data.graph, graph)) (overrides[d.node] ??= {})[d.key] = d.to
    try {
      await recipeMut.create.mutateAsync({ name, description: '', param_overrides: compactOverrides(overrides), is_default: false })
      toast.success(t('batchPage.tune.savedRecipe', { name }))
    } catch (error) { toast.error(errorMessage(error)) }
  }
  function toEditor() {
    if (!flow.data || !graph) return
    setDraft(flow.data.id, { baseVersion: flow.data.version, graph, name: flow.data.name, description: flow.data.description, dirty: true })
    navigate(`/flows/${flow.data.id}`)
  }
  async function toGolden(indexes: number[]) {
    if (setId === null) return
    try {
      const r = await mut.toGolden.mutateAsync({ setId, indexes, expect_from: 'label' })
      toast.success(t('batchPage.toGoldenDone', { count: r.created }))
    } catch (error) { toast.error(errorMessage(error)) }
  }
  async function confirmDelete() {
    if (!pendingDelete) return
    try {
      if (pendingDelete.kind === 'set') { await mut.deleteSet.mutateAsync(pendingDelete.id); if (setId === pendingDelete.id) { setSetId(null); setRunId(null) } }
      else { await mut.deleteRun.mutateAsync({ id: pendingDelete.id, setId: pendingDelete.setId }); if (runId === pendingDelete.id) setRunId(null) }
      toast.success(t('batchPage.deleted'))
    } catch (error) { toast.error(errorMessage(error)) } finally { setPendingDelete(null) }
  }
  function onNewRun(id: number) {
    if (setId !== null) mut.invalidateSet(setId)
    setRunId(id)
    setTab('result')
  }

  const tabs = [
    { value: 'result' as const, label: t('batchPage.tabs.result'), icon: ListChecks },
    { value: 'images' as const, label: t('batchPage.tabs.images'), icon: Images },
    { value: 'insights' as const, label: t('batchPage.tabs.insights'), icon: BarChart3 },
    { value: 'compare' as const, label: t('batchPage.tabs.compare'), icon: GitCompare },
    { value: 'tune' as const, label: t('batchPage.tabs.tune'), icon: SlidersHorizontal },
  ]
  const currentRun: BatchRun | null = run.data ?? null
  // 可以拿來比較的：同一個影像集、已完成、不是目前選的那一次
  const compareCandidates = useMemo(() => runItems.filter((r) => r.status === 'done' && r.id !== runId), [runItems, runId])
  const currentSet: BatchSet | null = set.data ?? null
  //: 全域 AI 助手：選定一次已完成的執行後可資料諮詢／依資料調整，建議可套進調參面板、新執行自動選中
  const snapshotRef = useRef<() => Record<string, unknown>>(() => ({}))
  snapshotRef.current = () => ({
    tab,
    set: currentSet ? { id: currentSet.id, name: currentSet.name, images: currentSet.images?.length ?? 0 } : null,
    run: currentRun ? { id: currentRun.id, status: currentRun.status, origin: currentRun.origin, summary: currentRun.summary } : null,
  })
  useRegisterAssistantContext({
    kind: 'batch', flowId, flowName: flow.data?.name, batchRunId: currentRun?.status === 'done' ? currentRun.id : null,
    getGraph: () => graph ?? run.data?.graph ?? flow.data?.graph ?? null, applySuggestions: (sugs) => apply(sugs, false), onNewRun,
    describe: () => snapshotRef.current(),
  }, [flowId, flow.data?.name, currentRun?.id, currentRun?.status, graph, setId])

  return (
    <Page wide>
      <PageHeader
        title={t('batchPage.title')}
        description={t('batchPage.subtitle')}
        actions={
          <>
            <Checkbox label={t('batchPage.useDraft')} hint={draft ? t('editor.unsaved') : t('batchPage.useDraftHint')} checked={useDraft && Boolean(draft)} disabled={!draft} onChange={setUseDraft} />
            <Select label={t('batchPage.testFlow')} hint={t('batchPage.testFlowHint')} className="!py-1 text-xs" value={flowId ? String(flowId) : ''} onChange={(e) => selectFlow(Number(e.target.value))} placeholder={t('batchPage.pickFlow')}
              options={(flows.data?.items ?? []).map((f) => ({ value: String(f.id), label: f.name }))} data-testid="batch-flow" />
          </>
        }
      />
      {flowId === null ? <EmptyState title={t('batchPage.noFlows')} /> : (
        <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <div className="space-y-4">
            <Card className="p-3">
              <BatchSetList sets={setItems} selectedId={setId} flowId={flowId} onSelect={(id) => selectSet(id, setItems.find((s) => s.id === id)?.flow_id ?? null)} onNew={() => setNewOpen(true)}
                onDelete={(s) => setPendingDelete({ kind: 'set', id: s.id, name: s.name, setId: s.id })} keep={{ sets: sets.data?.keep_sets ?? 10, runs: sets.data?.keep_runs ?? 20 }} />
            </Card>
            {setId !== null ? (
              <Card className="p-3">
                <BatchRunList runs={runItems} selectedId={runId} onSelect={(id) => setRunId(id)} compareId={compareId} onCompare={(id) => { setCompareId(id); if (id !== null) setTab('compare') }}
                  onCancel={(id) => void mut.cancelRun.mutateAsync(id).then(() => toast.success(t('batchPage.cancelled'))).catch((e) => toast.error(errorMessage(e)))}
                  onDelete={(r) => setPendingDelete({ kind: 'run', id: r.id, name: r.label || `#${r.id}`, setId: r.set_id })} />
                <div className="mt-2">
                  <button type="button" className="btn-secondary w-full text-xs" disabled={!currentSet?.image_count || mut.startRun.isPending} onClick={() => void startRun(useDraft && draft ? draft.graph : null, { label: '' })} data-testid="batch-run-start">
                    ▶ {t('batchPage.runWith', { flow: flow.data?.name ?? '' })}{useDraft && draft ? ` (${t('batchPage.origin.draft')})` : ''}
                  </button>
                  {currentSet && currentSet.flow_id !== flowId ? (
                    <p className="mt-1 text-[11px] text-info" data-testid="batch-cross-flow">{t('batchPage.crossFlow', { set: currentSet.flow_name, flow: flow.data?.name ?? '' })}</p>
                  ) : null}
                </div>
              </Card>
            ) : null}
          </div>
          <Card className="min-w-0 p-3">
            <Tabs tabs={tabs} value={tab} onChange={setTab} size="sm" />
            <div className="mt-3">
              {tab === 'result' ? (currentRun && currentSet ? <BatchRunDetail run={currentRun} set={currentSet} onLabel={(i, e) => void label(i, e)} onPreview={setPreviewIndex} onToGolden={(idx) => void toGolden(idx)} canManage={canManage} />
                : <EmptyState title={currentSet ? t('batchPage.noRuns') : t('batchPage.noSets')} compact />) : null}
              {tab === 'images' ? (currentSet ? <BatchImagesGrid set={currentSet} run={currentRun} onGroup={(i, g) => void group(i, g)} onLabel={(i, e) => void label(i, e)} onBulk={(e) => void bulkLabel(e)} onPreview={setPreviewIndex} canManage={canManage} /> : <EmptyState title={t('batchPage.noSets')} compact />) : null}
              {tab === 'insights' ? (currentRun && currentSet ? <BatchInsightsPanel insights={insights.data} runs={runItems} set={currentSet} run={currentRun} onApply={apply} onPreview={setPreviewIndex} /> : <EmptyState title={t('batchPage.noRuns')} compact />) : null}
              {tab === 'compare' ? (
                <div className="space-y-3">
                  {currentRun ? (
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <label className="label mb-0" htmlFor="batch-compare-with">{t('batchPage.compare.pick', { run: runTitle(currentRun) })}</label>
                      <select id="batch-compare-with" className="input h-8 w-auto min-w-48 py-0 text-sm" value={compareId ?? ''} disabled={!compareCandidates.length}
                        onChange={(e) => setCompareId(e.target.value ? Number(e.target.value) : null)} data-testid="batch-compare-select">
                        <option value="">{compareCandidates.length ? t('batchPage.compare.none') : t('batchPage.compare.needTwo')}</option>
                        {compareCandidates.map((r) => <option key={r.id} value={r.id}>{runTitle(r)}</option>)}
                      </select>
                    </div>
                  ) : <EmptyState title={t('batchPage.noRuns')} compact />}
                  {currentRun ? <BatchComparePanel compare={compare} onPreview={setPreviewIndex} /> : null}
                </div>
              ) : null}
              {tab === 'tune' ? <BatchTunePanel graph={graph} baseGraph={flow.data?.graph ?? null} defs={defs} canEditFlow={canEditFlow} sourceRunId={graphSource.startsWith('run:') ? Number(graphSource.slice(4)) : null}
                onChange={setGraph} onRun={() => void startRun(graph, { label: t('batchPage.tune.runLabel') })} onSaveFlow={() => void saveFlow()} onSaveRecipe={(n) => void saveRecipe(n)}
                onReset={() => setGraphSource('')} onToEditor={toEditor} busy={mut.startRun.isPending}
                hasLabels={hasLabels} onAutotune={() => void startRun(graph, { mode: 'autotune', label: t('batchPage.origin.autotune') })} /> : null}
            </div>
          </Card>
        </div>
      )}
      {flowId !== null ? <NewSetModal open={newOpen} onClose={() => setNewOpen(false)} flowId={flowId} maxImages={sets.data?.max_images ?? 200} onCreated={(s) => { setSetId(s.id); setRunId(null); setTab('result'); toast.success(t('batchPage.createdAndRun')); void startRun(null, { label: t('batchPage.origin.manual') }, s.id) }} /> : null}
      <BatchRowPreviewModal run={previewIndex !== null ? currentRun : null} set={currentSet} index={previewIndex} graph={graph} onClose={() => setPreviewIndex(null)} />
      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void confirmDelete()}
        title={pendingDelete?.kind === 'set' ? t('batchPage.deleteSet') : t('batchPage.deleteRun')}
        message={pendingDelete?.kind === 'set' ? t('batchPage.deleteSetMessage', { name: pendingDelete?.name ?? '' }) : t('batchPage.deleteRunMessage', { name: pendingDelete?.name ?? '' })}
        confirmLabel={t('common.delete')} danger loading={mut.deleteSet.isPending || mut.deleteRun.isPending} />
    </Page>
  )
}
