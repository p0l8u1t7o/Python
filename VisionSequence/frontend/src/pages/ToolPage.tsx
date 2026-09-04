/**
 * 工具頁（ToolPage）：單一步驟的專屬調參頁 `/flows/:id/tools/:nodeId`。
 *
 * 版面：左＝參數表單；中＝「執行前」／「執行後」並排（沒有影像輸出的工具，執行後把標記疊在
 * 輸入影像上；輸出值只列在下方參考資訊，不疊浮層擋圖）＋下方參考資訊（直方圖／統計／series 橫向排列）；
 * 右＝按鍵（儲存／執行到此步驟／自動套用／重用影像／暫存影像）。
 *
 * 執行模式：預設「按執行鈕才跑」（改參數只暫存生效；可開自動套用改回 250 ms 防抖即跑）。
 * 參數編輯只寫入共享草稿（lib/flowDraft.ts），按「儲存」才寫回後台；按「返回」且未儲存時，
 * 本頁對此步驟的參數編輯會被放棄（confirm 後還原進頁時的狀態）。有 ROI 參數且已有值時進頁直接顯示。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useBlocker, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Check, FlaskConical, ImageUp, Loader2, Save } from 'lucide-react'

import { ScratchBadge } from '@/components/editor/EditorToolbar'
import { isTypingTarget } from '@/components/editor/graphMapping'
import { Histogram, binValues, fmtNum } from '@/components/editor/Histogram'
import type { InspectorActions } from '@/components/editor/ParamField'
import { ParamForm } from '@/components/editor/ParamForm'
import { formatValue } from '@/components/editor/ResultsPanel'
import { iconFor } from '@/components/editor/ToolNode'
import { Button, DetailRow, ErrorState, LoadingState, Modal, StatusBadge, Switch, TextInput } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { imageUrl } from '@/lib/api'
import { useConfirm } from '@/lib/useConfirm'
import { useRegisterAssistantContext } from '@/lib/assistantContext'
import { errorMessage } from '@/lib/errors'
import { getSession, patchDraftNode, setDraft, updateSession, useFlowSession } from '@/lib/flowDraft'
import { previewFlow, useAssetMutations, useFlow, useFlowMutations, useScratchImage, useToolTypes } from '@/lib/queries'
import { isImageRef, type GraphNode, type NodeAnalysis, type Region, type ToolTypeDef } from '@/lib/types'
import { isLockHolder, useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { firstImageOutput, inputImage, sourceRefOf } from './FlowEditorPage'

const DEBOUNCE_MS = 250

function StatsRows({ stats }: { stats: NonNullable<NodeAnalysis['input']>['stats'] }) {
  const { t } = useTranslation()
  if (!stats) return null
  return (
    <dl className="grid grid-cols-1 gap-x-6 font-mono text-[11px] sm:grid-cols-2">
      <DetailRow label={t('tool.stats.size')}><span className="whitespace-nowrap">{stats.width}×{stats.height}</span></DetailRow>
      <DetailRow label={t('tool.stats.range')}><span className="whitespace-nowrap">{stats.min}–{stats.max}</span></DetailRow>
      <DetailRow label={t('tool.stats.mean')}><span className="whitespace-nowrap">{stats.mean.toFixed(1)}</span></DetailRow>
      <DetailRow label={t('tool.stats.std')}><span className="whitespace-nowrap">{stats.std.toFixed(1)}</span></DetailRow>
    </dl>
  )
}

function ToolPageInner({ flowId, nodeId }: { flowId: number; nodeId: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const auth = useAuth()
  const catalogue = useToolTypes()
  const flow = useFlow(flowId)
  const { patch } = useFlowMutations()
  const scratchUpload = useScratchImage()
  const { fromImage } = useAssetMutations()
  const session = useFlowSession(flowId)

  const [autoApply, setAutoApply] = useState(false) // 預設按「執行」鈕才跑；要即時的自己開自動套用
  const [reuse, setReuse] = useState(true)
  const [updating, setUpdating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<NodeAnalysis | null>(null)
  const [roiEditingKey, setRoiEditingKey] = useState<string | null>(null)
  const navigate = useNavigate()
  //: 進頁時此步驟的快照：返回未儲存時還原（放棄本頁的參數編輯）
  const entryRef = useRef<{ key: string; json: string; dirty: boolean } | null>(null)
  const [templateKey, setTemplateKey] = useState<string | null>(null)
  const [templateRegion, setTemplateRegion] = useState<Region | null>(null)
  const [templateName, setTemplateName] = useState('')
  const [askTemplateName, setAskTemplateName] = useState(false)
  const scratchInput = useRef<HTMLInputElement>(null)

  const defs = useMemo(() => {
    const map = new Map<string, ToolTypeDef>()
    for (const def of catalogue.data?.items ?? []) map.set(def.key, def)
    return map
  }, [catalogue.data])

  // ---- 草稿：沒有（或伺服器版本變了）就用伺服器的圖建一份 ----
  const editorPath = `/flows/${flowId}`
  useEffect(() => {
    const data = flow.data
    if (!data) return
    // 讀 store 的即時值，不用 render 時的快照：從編輯器導過來時，編輯器是在這個元件 render 之後
    // 才（於 unmount cleanup）寫入草稿，用快照會誤判成「沒有草稿」而拿伺服器的圖蓋掉未儲存的變更。
    const draft = getSession(flowId).draft
    if (draft && draft.baseVersion === data.version) return
    setDraft(flowId, { baseVersion: data.version, graph: data.graph, name: data.name, description: data.description, dirty: false })
  }, [flow.data, session.draft, flowId])

  const draft = session.draft && flow.data && session.draft.baseVersion === flow.data.version ? session.draft : null
  const graph = draft?.graph
  const node = useMemo(() => graph?.nodes.find((n) => n.id === nodeId), [graph, nodeId])
  const def = node ? defs.get(node.type) : undefined
  const payloads = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n])), [graph])
  //: 全域 AI 助手：知道目前在哪個工具，就能回答此工具的參數要領
  useRegisterAssistantContext({ kind: 'tool', flowId, flowName: flow.data?.name, nodeId, nodeType: node?.type, getGraph: () => getSession(flowId).draft?.graph ?? flow.data?.graph ?? null }, [flowId, nodeId, node?.type, flow.data?.name])
  const edges = graph?.edges ?? []

  const execLocked = auth.lock.locked && auth.me?.kind !== 'integrator' && !isLockHolder(auth.me, auth.lock)
  const readOnly = !auth.isEngineer  // 工具頁會動到所有參數，不只現場參數

  // ---- 結果 ----
  const run = session.previewRun
  const report = run?.nodes[nodeId]
  const lastSourceRef = useMemo(() => sourceRefOf(run, payloads), [run, payloads])
  const scratch = session.scratch
  const pinnedRef = scratch?.ref ?? (reuse ? lastSourceRef : null)
  const pinnedRefRef = useRef(pinnedRef)
  pinnedRefRef.current = pinnedRef

  const input = run && report ? inputImage(run, nodeId, report, edges, defs, payloads) : null
  const output = firstImageOutput(report)
  const inputW = input?.width || analysis?.input?.stats?.width || 0
  const inputH = input?.height || analysis?.input?.stats?.height || 0

  // ---- 試跑到此步驟（取消舊請求，只採用最後一次） ----
  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<number | undefined>(undefined)
  const graphRef = useRef(graph)
  graphRef.current = graph
  const runPreview = useCallback(async () => {
    const g = graphRef.current
    if (!g) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setUpdating(true)
    try {
      const result = await previewFlow({ flowId, graph: g, until_node: nodeId, analysis: true, reuse_image_ref: pinnedRefRef.current, signal: controller.signal })
      if (controller.signal.aborted) return
      updateSession(flowId, { previewRun: result })
      setAnalysis(result.analysis ?? null)
      setPreviewError(null)
    } catch (error) {
      if (controller.signal.aborted) return
      setPreviewError(errorMessage(error))
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null
        setUpdating(false)
      }
    }
  }, [flowId, nodeId])

  const schedulePreview = useCallback(() => {
    window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => void runPreview(), DEBOUNCE_MS)
  }, [runPreview])

  // 進頁面先跑一次，讓前／後影像有東西看。
  const bootedFor = useRef('')
  useEffect(() => {
    if (!graph || !def || execLocked) return
    const key = `${flowId}:${nodeId}`
    if (bootedFor.current === key) return
    bootedFor.current = key
    void runPreview()
  }, [graph, def, execLocked, flowId, nodeId, runPreview])

  // 進頁快照（返回未儲存時還原用）＋有 ROI 參數且已有值 → 直接顯示、可立即拖曳
  useEffect(() => {
    if (!def || !node || !draft) return
    const key = `${flowId}:${nodeId}`
    if (entryRef.current?.key === key) return
    entryRef.current = { key, json: JSON.stringify(node), dirty: draft.dirty }
    const roi = def.params.find((p) => p.kind === 'roi' && node.params?.[p.key])
    if (roi) setRoiEditingKey(roi.key)
  }, [def, node, draft, flowId, nodeId])

  const { confirm, dialog } = useConfirm()

  /** 返回編輯器：本頁改過參數且未儲存 → confirm 後還原此步驟到進頁狀態（放棄編輯）。 */
  async function goBack() {
    const snap = entryRef.current
    // 草稿不 dirty（剛儲存過／沒改過）就直接回去；dirty 才比對本頁是否動過此節點
    const changed = Boolean(draft?.dirty) && snap && node ? JSON.stringify(node) !== snap.json : false
    if (changed && snap) {
      if (!(await confirm(t('tool.discardConfirm'), { confirmLabel: t('tool.discardAndBack') }))) return
      patchDraftNode(flowId, nodeId, JSON.parse(snap.json) as Partial<GraphNode>)
      const cur = getSession(flowId).draft
      if (cur && !snap.dirty) setDraft(flowId, { ...cur, dirty: false })
    }
    navigate(editorPath)
  }
  useEffect(
    () => () => {
      window.clearTimeout(timerRef.current)
      abortRef.current?.abort()
    },
    [],
  )

  const onChange = useCallback(
    (patchData: Partial<GraphNode>) => {
      patchDraftNode(flowId, nodeId, patchData)
      if (autoApply && !execLocked) schedulePreview()
    },
    [flowId, nodeId, autoApply, execLocked, schedulePreview],
  )

  // ---- 儲存 ----
  const save = useCallback(async () => {
    if (!draft) return
    if (readOnly) {
      toast.warning(t('flows.readOnlyHint'))
      return
    }
    setSaving(true)
    try {
      const saved = await patch.mutateAsync({ id: flowId, name: draft.name.trim() || t('editor.untitled'), description: draft.description, graph: draft.graph })
      setDraft(flowId, { ...draft, baseVersion: saved.version, dirty: false })
      // 儲存成功＝新的基準：之後按返回不再詢問、也不會把已儲存的參數還原掉
      const savedNode = draft.graph.nodes.find((n) => n.id === nodeId)
      if (savedNode) entryRef.current = { key: `${flowId}:${nodeId}`, json: JSON.stringify(savedNode), dirty: false }
      toast.success(t('editor.toast.saved'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }, [draft, readOnly, patch, flowId, nodeId, toast, t])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void save()
        return
      }
      // Esc：結束 ROI 編輯／範本框選（與編輯器一致；輸入框內不處理）
      if (event.key === 'Escape' && !isTypingTarget(event.target)) {
        setRoiEditingKey(null)
        setTemplateKey(null)
        setTemplateRegion(null)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [save])

  // ---- 離開攔截（回編輯器經 goBack 處理，不在此攔） ----
  const dirty = Boolean(draft?.dirty)
  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }: { currentLocation: { pathname: string }; nextLocation: { pathname: string } }) => dirty && currentLocation.pathname !== nextLocation.pathname && nextLocation.pathname !== editorPath && !nextLocation.pathname.startsWith(`${editorPath}/tools/`),
      [dirty, editorPath],
    ),
  )
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    void confirm(t('editor.leaveUnsaved'), { title: t('editor.leaveTitle'), confirmLabel: t('editor.leaveAnyway') }).then((ok) => (ok ? blocker.proceed() : blocker.reset()))
  }, [blocker, t, confirm])

  // ---- 暫存影像 ----
  async function uploadScratch(file: File) {
    try {
      const info = await scratchUpload.mutateAsync({ flowId, file })
      updateSession(flowId, { scratch: info })
      toast.success(t('editor.toast.scratchUploaded', { name: info.name, w: info.width, h: info.height }))
      pinnedRefRef.current = info.ref
      void runPreview()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  // ---- ROI／範本 ----
  const roiParam = roiEditingKey ? def?.params.find((p) => p.key === roiEditingKey) : undefined
  const roiValue = roiParam && node ? (node.params?.[roiParam.key] as Region | null | undefined) ?? null : null
  const actions: InspectorActions = {
    roiEditingKey,
    setRoiEditing: setRoiEditingKey,
    templateKey,
    hasImage: Boolean(input?.ref),
    templateFromImage: (key) => {
      setTemplateKey(key || null)
      setTemplateRegion(null)
    },
  }
  async function createTemplate() {
    if (!templateKey || !templateRegion || !input?.ref || !node) return
    try {
      const asset = await fromImage.mutateAsync({ ref: input.ref, region: templateRegion, name: templateName.trim() || undefined })
      onChange({ params: { ...(node.params ?? {}), [templateKey]: asset.id } })
      toast.success(t('editor.toast.templateCreated', { name: asset.name }))
      setAskTemplateName(false)
      setTemplateKey(null)
      setTemplateRegion(null)
      setTemplateName('')
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  if (catalogue.isPending || flow.isPending || !draft) return <LoadingState />
  if (catalogue.isError || flow.isError) return <ErrorState error={flow.error ?? catalogue.error} onRetry={() => void flow.refetch()} />
  if (!node || !def) {
    return (
      <div className="p-6">
        <ErrorState error={new Error(t('tool.notFound', { id: nodeId }))} />
        <div className="text-center"><Link to={editorPath} className="text-sm text-brand hover:underline">{t('tool.back')}</Link></div>
      </div>
    )
  }

  const Icon = iconFor(def.icon)
  const beforeRoi = roiParam
    ? { roi: roiValue, roiShapes: roiParam.shapes.length ? roiParam.shapes : undefined, onRoiChange: (region: Region) => onChange({ params: { ...(node.params ?? {}), [roiParam.key]: region } }) }
    : templateKey
      ? { roi: templateRegion, roiShapes: ['rect' as const], onRoiChange: setTemplateRegion }
      : {}
  const status = report?.status
  const badge = report ? { text: `${t(`status.${status}`)} · ${Math.round(report.duration_ms)} ms`, tone: (status === 'ok' ? 'ok' : status === 'ng' || status === 'error' ? 'ng' : 'neutral') as 'ok' | 'ng' | 'neutral' } : null
  const series = Object.entries(analysis?.series ?? {})

  // 有程式碼參數（Python 腳本）的工具：參數欄加寬給編輯器
  const wideParams = Boolean(def?.params.some((p) => p.kind === 'code'))
  return (
    <div className="flex h-full flex-col" data-testid="tool-page">
      {dialog}
      {/* 頂列 */}
      <header className="flex flex-wrap items-center gap-1.5 border-b border-line bg-surface px-3 py-1.5">
        <button type="button" onClick={() => void goBack()} className="btn-secondary !h-8 !px-2.5 !text-xs" data-testid="btn-back">
          <ArrowLeft size={14} /> {t('tool.back')}
        </button>
        <span className="flex items-center gap-1.5 text-sm font-semibold">
          <span className="flex size-6 items-center justify-center rounded-md bg-brand-soft text-brand"><Icon size={14} /></span>
          {node.label || def.label}
          <span className="font-mono text-[11px] font-normal text-muted">{def.label} · {node.id}</span>
        </span>
        {dirty ? <span className="text-[11px] text-warning">{t('editor.unsaved')}</span> : null}
      </header>

      {/* 三欄（手機：參數／影像／操作直向堆疊，整頁捲動） */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
        {/* 左：參數 */}
        <aside className={`w-full shrink-0 border-b border-line bg-surface p-3 ${wideParams ? 'md:w-[560px]' : 'md:w-80'} md:overflow-y-auto md:border-b-0 md:border-r`} data-testid="tool-params">
          <p className="mb-2 text-xs font-semibold text-muted">{t('editor.parameters')}</p>
          {def.description ? <p className="mb-3 text-xs leading-relaxed text-muted">{def.description}</p> : null}
          <ParamForm node={node} definition={def} edges={edges} actions={actions} onChange={onChange} />
        </aside>

        {/* 中：前／後影像 */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="relative flex min-h-80 flex-1 md:min-h-0">
            <div className="relative min-w-0 flex-1" data-testid="tool-before">
              {/* 執行前一律乾淨（標記只出現在右邊「執行後」；ROI 框是參數顯示，不算標記） */}
              <ImageViewer src={input?.ref ? imageUrl(input.ref, 1600) : null} imageWidth={inputW} imageHeight={inputH} overlays={[]} toolbar className="h-full w-full" badge={null} {...beforeRoi} />
              <span className="pointer-events-none absolute left-2 top-8 rounded bg-black/50 px-1.5 py-0.5 text-[11px] text-white/90">{t('editor.viewer.before')}</span>
              {templateKey ? (
                <div className="absolute right-2 bottom-2 flex items-center gap-1.5 rounded-lg border border-brand bg-surface/95 px-2 py-1 text-[11px]">
                  <span className="text-brand">{t('editor.viewer.templateHint')}</span>
                  <Button size="xs" variant="primary" icon={<Check size={12} />} disabled={!templateRegion} onClick={() => setAskTemplateName(true)}>{t('editor.viewer.templateCreate')}</Button>
                </div>
              ) : null}
              {roiEditingKey ? (
                <div className="absolute right-2 bottom-2 flex items-center gap-1.5 rounded-lg border border-brand bg-surface/95 px-2 py-1 text-[11px]">
                  <span className="text-brand">{t('editor.viewer.roiEditing')}</span>
                  <Button size="xs" variant="primary" icon={<Check size={12} />} onClick={() => setRoiEditingKey(null)}>{t('editor.viewer.done')}</Button>
                </div>
              ) : null}
            </div>
            <div className="relative min-w-0 flex-1 border-l border-line" data-testid="tool-after">
              {output ? (
                <ImageViewer src={output.ref ? imageUrl(output.ref, 1600) : null} imageWidth={output.width} imageHeight={output.height} overlays={[]} toolbar className="h-full w-full" badge={badge} />
              ) : (
                <ImageViewer src={input?.ref ? imageUrl(input.ref, 1600) : null} imageWidth={inputW} imageHeight={inputH} overlays={report?.overlays ?? []} toolbar className="h-full w-full" badge={badge} />
              )}
              <span className="pointer-events-none absolute left-2 top-8 rounded bg-black/50 px-1.5 py-0.5 text-[11px] text-white/90">
                {t('editor.viewer.after')}{output ? '' : ` · ${t('tool.overlaysOnInput')}`}
              </span>
            </div>
          </div>
          {report?.message && status !== 'ok' ? (
            <p className={`border-t border-line px-3 py-1.5 text-xs ${status === 'error' ? 'bg-critical-soft text-critical' : 'bg-warning-soft text-warning'}`} data-testid="tool-message">{report.message}</p>
          ) : null}
          {/* 下：參考資訊（直方圖／統計／series 橫向排列） */}
          <div className="max-h-[34%] min-h-40 shrink-0 overflow-y-auto border-t border-line bg-surface p-3 text-sm" data-testid="tool-reference">
            <div className="grid items-start gap-x-8 gap-y-3 md:grid-cols-2 xl:grid-cols-3">

          <p className="mb-2 text-xs font-semibold text-muted">{t('tool.reference')}</p>
          {report ? (
            <dl className="mb-3">
              <DetailRow label={t('editor.result.status')}><StatusBadge status={report.status} /></DetailRow>
              <DetailRow label={t('editor.result.duration')}><span className="tnum">{report.duration_ms.toFixed(1)} ms</span></DetailRow>
              {report.branch ? <DetailRow label={t('editor.result.branch')} mono>{report.branch}</DetailRow> : null}
              <DetailRow label={t('editor.result.overlays')}>{report.overlays.length}</DetailRow>
            </dl>
          ) : (
            <p className="mb-3 text-xs text-muted">{t('editor.result.noResult')}</p>
          )}
          {report?.message ? <p className={`mb-3 rounded-lg px-3 py-2 text-xs ${status === 'error' ? 'bg-critical-soft text-critical' : status === 'ng' ? 'bg-warning-soft text-warning' : 'bg-surface-muted text-content'}`}>{report.message}</p> : null}

          {analysis?.input?.histogram ? (
            <div className="mb-3 space-y-1">
              <Histogram bins={analysis.input.histogram} title={t('tool.inputHistogram')} labels={['0', '255']} />
              <StatsRows stats={analysis.input.stats} />
            </div>
          ) : null}
          {analysis?.output?.histogram ? (
            <div className="mb-3 space-y-1">
              <Histogram bins={analysis.output.histogram} title={`${t('tool.outputHistogram')} (${analysis.output.port})`} color="var(--ok)" labels={['0', '255']} />
              <StatsRows stats={analysis.output.stats} />
            </div>
          ) : null}
          {series.length ? (
            <div className="mb-3 space-y-2" data-testid="tool-series">
              <p className="label !mb-0">{t('tool.series')}</p>
              {series.map(([key, s]) => {
                const b = binValues(s.values, 32)
                return (
                  <div key={key}>
                    <Histogram bins={b.counts} height={48} color="var(--warning)" title={`${key} · n=${s.count}`} labels={[fmtNum(s.min), fmtNum(s.max)]} />
                    <p className="font-mono text-[10px] text-muted">min {fmtNum(s.min)} · max {fmtNum(s.max)} · mean {fmtNum(s.mean)}</p>
                  </div>
                )
              })}
            </div>
          ) : null}

          {report ? (
            <div className="mb-3">
              <p className="label">{t('editor.result.outputs')}</p>
              <table className="w-full text-xs">
                <tbody className="divide-y divide-line">
                  {Object.entries(report.outputs).map(([key, value]) => (
                    <tr key={key}>
                      <td className="py-1 pr-2 font-mono text-muted">{key}</td>
                      <td className="py-1 text-right font-mono" title={typeof value === 'object' && !isImageRef(value) ? JSON.stringify(value) : undefined}>{formatValue(value)}</td>
                    </tr>
                  ))}
                  {Object.keys(report.outputs).length === 0 ? <tr><td className="py-1 text-muted">—</td></tr> : null}
                </tbody>
              </table>
            </div>
          ) : null}
          {report?.logs.length ? (
            <div>
              <p className="label">{t('editor.result.logs')}</p>
              <ul className="max-h-40 space-y-0.5 overflow-y-auto font-mono text-[11px]">
                {report.logs.map((log, i) => (
                  <li key={i} className={log.level === 'error' ? 'text-critical' : log.level === 'warning' ? 'text-warning' : 'text-muted'}>[{log.level}] {log.message}</li>
                ))}
              </ul>
            </div>
          ) : null}
        
            </div>
          </div>
        </div>

        {/* 右：按鍵 */}
        <aside className="flex w-full shrink-0 flex-col gap-3 border-t border-line bg-surface p-3 md:w-56 md:overflow-y-auto md:border-t-0 md:border-l" data-testid="tool-actions">
          <p className="text-xs font-semibold text-muted">{t('common.actions')}</p>
          <Button variant={dirty ? 'primary' : 'secondary'} icon={<Save size={14} />} loading={saving} disabled={readOnly} onClick={() => void save()} data-testid="tool-save">
            {dirty ? t('editor.save') : t('editor.savedState')}
          </Button>
          <Button icon={<FlaskConical size={14} />} loading={updating && !autoApply} disabled={execLocked} onClick={() => void runPreview()} data-testid="tool-preview">
            {t('tool.previewUntil')}
          </Button>
          <label className="flex items-center gap-1.5 text-[11px] text-muted" title={t('tool.autoApplyHint')}>
            <Switch checked={autoApply} onChange={setAutoApply} label={t('tool.autoApply')} />
            {t('tool.autoApply')}
          </label>
          <label className="flex items-center gap-1 text-[11px] text-muted" title={t('editor.reuseImageHint')}>
            <input type="checkbox" className="accent-[var(--brand)]" checked={reuse} disabled={Boolean(scratch) || !lastSourceRef} onChange={(e) => setReuse(e.target.checked)} />
            {t('editor.reuseImage')}
          </label>
          {scratch ? (
            <ScratchBadge scratch={scratch} onClear={() => updateSession(flowId, { scratch: null })} />
          ) : (
            <Button icon={<ImageUp size={14} />} loading={scratchUpload.isPending} onClick={() => scratchInput.current?.click()} data-testid="tool-scratch">
              {t('editor.scratchUpload')}
            </Button>
          )}
          <input
            ref={scratchInput}
            type="file"
            accept="image/*"
            className="hidden"
            data-testid="scratch-input"
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (file) void uploadScratch(file)
            }}
          />
          {updating ? (
            <span className="flex items-center gap-1 text-[11px] text-brand" data-testid="tool-updating">
              <Loader2 size={12} className="animate-spin" /> {t('tool.updating')}
            </span>
          ) : null}
          {previewError ? <span className="text-[11px] text-critical" data-testid="tool-preview-error">{previewError}</span> : null}
        </aside>

      </div>

      <Modal
        open={askTemplateName}
        onClose={() => setAskTemplateName(false)}
        title={t('editor.viewer.templateCreate')}
        size="sm"
        footer={
          <>
            <Button onClick={() => setAskTemplateName(false)}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={fromImage.isPending} onClick={() => void createTemplate()}>{t('common.create')}</Button>
          </>
        }
      >
        <TextInput label={t('editor.viewer.templateName')} autoFocus value={templateName} onChange={(e) => setTemplateName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void createTemplate()} />
      </Modal>
    </div>
  )
}

export function ToolPage() {
  const { flowId, nodeId } = useParams<{ flowId: string; nodeId: string }>()
  const id = Number(flowId)
  if (!flowId || Number.isNaN(id) || !nodeId) return null
  return <ToolPageInner key={`${id}:${nodeId}`} flowId={id} nodeId={decodeURIComponent(nodeId)} />
}
