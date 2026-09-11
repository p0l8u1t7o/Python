/** 檢測任務頁：共用流程草稿，任務修改經核心翻譯器序列化送出。 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useBlocker, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight, Plus, Play, Save, Trash2, ImageUp } from 'lucide-react'
import { ImagesField, ParamField, type InspectorActions } from '@/components/editor/ParamField'
import { useSaveConflictDialog } from '@/components/flow/SaveConflictDialog'
import { Button, ErrorState, LoadingState, Modal } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { fixedImageFromRef, imageUrl, teachContourFromImage } from '@/lib/api'
import { GeometrySourceField } from '@/components/inspect/GeometrySourceField'
import { inspectionFieldVisible, inspectionHasImage, inspectionReuseRef, normalizeInspectionSources, inspectionRunFromTrial, inspectionTrialPayload } from '@/lib/inspect'
import { errorMessage } from '@/lib/errors'
import { publishAssistantProgress, useRegisterAssistantContext } from '@/lib/assistantContext'
import { getSession, setDraft, updateSession, useFlowSession } from '@/lib/flowDraft'
import { INSPECT_DOTS, OUTPUT_NAME, forgetInspectionRun, inspectGraphHash, inspectionAdvancedPath, inspectionDefaults, inspectionEditableKind, inspectionOverall, inspectionParam, inspectionReasonKey, inspectionRemovalGraph, inspectionRunFor, inspectionStale, inspectionStatus, inspectionValue, missingInspectionFields, rememberInspectionRun } from '@/lib/inspect'
import { inspectionEvidence, readInspection, readLastInspectionTrial, saveLastInspectionTrial, removeInspection, teachInspectionPose, useFlow, useFlowMutations, useInspectKinds, usePreviewFlow, useScratchImage, useSources, useToolTypes, writeInspection } from '@/lib/queries'
import type { FlowGraph, ImageRef, InspectDependency, InspectField, InspectKind, InspectList, InspectReading, Region, RoiShape, RunReport } from '@/lib/types'
import { useConfirm } from '@/lib/useConfirm'
import { isLockHolder, useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { localiseDataName } from '@/lib/catalogueLocale'
import type { Language } from '@/i18n'

const EMPTY_LIST: InspectList = { tasks: [], shared: [], loose: [] }
/** 欄位改了多久沒再動才送去伺服器；太短會在打字中途送出（中文輸入一個字要好幾個按鍵）。 */
const EDIT_DEBOUNCE_MS = 600
/** 新增精靈：0＝選種類、1＝畫區域（roi／參考圖／幾何）、2＝填規格。 */
type WizardStep = 0 | 1 | 2
function wizardStepOf(field: InspectField): 1 | 2 {
  return ['roi', 'images', 'json'].includes(field.kind) || field.source_type === 'geometry' ? 1 : 2
}

function InspectPageInner({ flowId }: { flowId: number }) {
  const { t, i18n } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const flow = useFlow(flowId)
  const kinds = useInspectKinds()
  const tools = useToolTypes()
  const sources = useSources()
  const { patch } = useFlowMutations()
  const preview = usePreviewFlow()
  const upload = useScratchImage()
  const session = useFlowSession(flowId)
  const cachedRun = useRef(inspectionRunFor(flowId, session.previewRun))
  const { confirm, dialog } = useConfirm()
  const { showConflict, dialog: conflictDialog } = useSaveConflictDialog()
  const [list, setList] = useState<InspectList>(EMPTY_LIST)
  const [readError, setReadError] = useState<string | null>(null)
  const [selected, setSelected] = useState('')
  const [newKind, setNewKind] = useState<string | null>(null)
  const [wizard, setWizard] = useState<WizardStep | null>(null)
  const [fixedOpen, setFixedOpen] = useState<boolean | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(false)
  const [readings, setReadings] = useState<InspectReading[]>(cachedRun.current?.readings ?? [])
  const [run, setRun] = useState<RunReport | null>(cachedRun.current?.report ?? null)
  const [runHash, setRunHash] = useState<string | null>(cachedRun.current?.hash ?? null)
  const [dependencies, setDependencies] = useState<InspectDependency[] | null>(null)
  const [roiKey, setRoiKey] = useState<string | null>('roi')
  const [advancedRoi, setAdvancedRoi] = useState<{ nodeId: string; key: string; shapes: RoiShape[] } | null>(null)
  const [cropKey, setCropKey] = useState<string | null>(null)
  const [cropRegion, setCropRegion] = useState<Region | null>(null)
  const [reuse, setReuse] = useState(true)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [proposals, setProposals] = useState<Region[]>([])
  const [proposalTasks, setProposalTasks] = useState<string[]>([])
  const uploadInput = useRef<HTMLInputElement>(null)
  const baseline = useRef<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const edits = useRef<{ task_id: string; fields: Record<string, unknown> } | null>(null)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const alive = useRef(true)
  const readSequence = useRef(0)
  const trialSequence = useRef(0)
  const readOnly = !auth.can('flows.edit')
  const locked = auth.lock.locked && !isLockHolder(auth.me, auth.lock) && auth.me?.kind !== 'integrator'
  const graph = session.draft?.graph
  const editorPath = `/flows/${flowId}`
  const task = list.tasks.find((item) => item.task_id === selected)
  const kind = newKind ? kinds.data?.items.find((item) => item.kind === newKind) : inspectionEditableKind(task, kinds.data?.items ?? [])
  const stale = Boolean(runHash && (pending || busy || (graph && inspectionStale(graph, runHash))))
  const reading = newKind ? undefined : readings.find((item) => item.task_id === selected)
  const status = inspectionStatus(reading, !newKind && stale, !newKind && task?.custom)
  const defs = useMemo(() => new Map((tools.data?.items ?? []).map((item) => [item.key, item])), [tools.data])

  useEffect(() => {
    if (!auth.can('flows.run')) return
    let cancelled = false
    const sequence = trialSequence.current
    void readLastInspectionTrial(flowId).then(({ trial }) => {
      if (!trial || cancelled || sequence !== trialSequence.current) return
      const cached = cachedRun.current
      // 同一次試執行仍有完整報告時保留影像與教導能力。
      if (cached?.hash === trial.hash && cached.report.id && cached.report.finished_at &&
          Math.abs(cached.report.finished_at * 1000 - Date.parse(trial.executed_at)) < 1) return
      const restored = inspectionRunFromTrial(flowId, trial)
      setRun(restored.report); setReadings(restored.readings); setRunHash(restored.hash)
    }).catch(() => { /* 離線或尚未部署 migration 時沿用裝置摘要。 */ })
    return () => { cancelled = true }
  }, [flowId, auth.me])

  useEffect(() => {
    if (!flow.data || baseline.current !== null) return
    baseline.current = flow.data.updated_at
    const old = getSession(flowId).draft
    if (!old || (!old.dirty && old.baseVersion !== flow.data.version)) {
      const normalized = normalizeInspectionSources(flow.data.graph)
      setDraft(flowId, { baseVersion: flow.data.version, graph: normalized, name: flow.data.name, description: flow.data.description, dirty: normalized !== flow.data.graph })
    } else {
      const normalized = normalizeInspectionSources(old.graph)
      if (normalized !== old.graph) setDraft(flowId, { ...old, graph: normalized, dirty: true })
    }
  }, [flow.data, flowId])

  useEffect(() => {
    if (!graph) return
    const sequence = ++readSequence.current
    void readInspection(graph).then((result) => {
      if (!alive.current || sequence !== readSequence.current) return
      setList(result)
      setReadError(null)
      setSelected((id) => result.tasks.some((item) => item.task_id === id) ? id : result.tasks[0]?.task_id ?? '')
    }).catch((error) => { if (alive.current && sequence === readSequence.current) setReadError(errorMessage(error)) })
  }, [graph])

  useEffect(() => {
    if (!newKind && task && !pending && !busy) setValues(task.fields)
  }, [task, newKind, pending, busy])

  function currentGraph(): FlowGraph {
    const current = getSession(flowId).draft
    if (!current) throw new Error(t('inspect.noDraft'))
    return current.graph
  }
  function putGraph(next: FlowGraph) {
    const current = getSession(flowId).draft
    if (current) setDraft(flowId, { ...current, graph: next, dirty: true })
  }
  function enqueue(operation: () => Promise<void>): Promise<void> {
    const next = queue.current.then(operation)
    queue.current = next.catch(() => undefined)
    return next
  }
  function flushEdits(): Promise<void> {
    clearTimeout(timer.current)
    const pendingChange = edits.current
    if (!pendingChange) return queue.current
    // 還不合法的欄位（打到一半的結果名稱、超出範圍的數字）留在本機，只送合法的；送去只會被伺服器打回並清掉正在打的字
    const activeKind = list.tasks.find((item) => item.task_id === pendingChange.task_id)
    const kindDef = activeKind ? inspectionEditableKind(activeKind, kinds.data?.items ?? []) : undefined
    const invalid = new Set(kindDef ? missingInspectionFields(kindDef, { ...activeKind?.fields, ...pendingChange.fields }) : [])
    const sendable = Object.fromEntries(Object.entries(pendingChange.fields).filter(([key]) => !invalid.has(key)))
    const kept = Object.fromEntries(Object.entries(pendingChange.fields).filter(([key]) => invalid.has(key)))
    edits.current = Object.keys(kept).length ? { task_id: pendingChange.task_id, fields: kept } : null
    if (!Object.keys(sendable).length) return queue.current
    const change = { task_id: pendingChange.task_id, fields: sendable }
    return enqueue(async () => {
      setBusy(true)
      try {
        const next = await writeInspection('update', currentGraph(), change)
        putGraph(next.graph)
        const result = await readInspection(next.graph)
        if (alive.current) setList(result)
        setOperationError(null)
      } catch (error) {
        edits.current = { task_id: change.task_id, fields: { ...change.fields, ...edits.current?.fields } }
        setOperationError(errorMessage(error))
        throw error
      } finally {
        if (alive.current) { setBusy(false); setPending(Boolean(edits.current)) }
      }
    })
  }
  async function action(operation: () => Promise<void>) {
    try { await operation() } catch (error) { toast.error(errorMessage(error)) }
  }
  function changeField(key: string, value: unknown) {
    if (readOnly || task?.custom && !newKind) return
    const changed = { [key]: value, ...(key === 'calibration' ? { unit: value ? 'mm' : kind?.kind === 'inspect_circular_surface' ? 'deg' : 'px' } : {}), ...(key === 'unit' && value !== 'mm' ? { calibration: '' } : {}) }
    const nextValues = { ...values, ...changed }
    setValues(nextValues)
    setOperationError(null)
    if (newKind || !task) return
    edits.current = { task_id: task.task_id, fields: { ...edits.current?.fields, ...changed } }
    setPending(true)
    clearTimeout(timer.current)
    if (kind && !(nextValues.unit === 'mm' && !nextValues.calibration)) {
      timer.current = setTimeout(() => void action(flushEdits), EDIT_DEBOUNCE_MS)
    }
  }
  async function selectTask(id: string) {
    await flushEdits()
    setNewKind(null); setWizard(null); setSelected(id); setRoiKey('roi'); setCropKey(null); setAdvancedRoi(null)
    setValues(list.tasks.find((item) => item.task_id === id)?.fields ?? {})
  }
  async function openWizard() {
    await flushEdits()
    setNewKind(null); setWizard(0); setCropKey(null); setAdvancedRoi(null)
  }
  function cancelWizard() {
    setNewKind(null); setWizard(null); setCropKey(null); setValues(task?.fields ?? {})
  }
  async function beginTask(item: InspectKind) {
    await flushEdits()
    const defaults = inspectionDefaults(item)
    const firstRoi = item.fields.find((field) => field.kind === 'roi' && inspectionFieldVisible(field, defaults))
    setNewKind(item.kind); setValues(defaults); setRoiKey(firstRoi?.key ?? 'roi'); setCropKey(null); setAdvancedRoi(null)
    // 沒有區域類欄位的任務（讀碼等）直接進規格
    setWizard(item.fields.some((field) => wizardStepOf(field) === 1 && inspectionFieldVisible(field, defaults)) ? 1 : 2)
  }
  const invalid = kind ? missingInspectionFields(kind, values) : []
  const needsCalibration = values.unit === 'mm' && !values.calibration
  const formInvalid = invalid.length > 0 || needsCalibration

  async function createTask() {
    if (!kind || readOnly || formInvalid) return
    setBusy(true)
    try {
      const next = await writeInspection('build', currentGraph(), { kind: kind.kind, version: kind.version, fields: values })
      const previousIds = new Set(list.tasks.map((item) => item.task_id))
      const result = await readInspection(next.graph)
      putGraph(next.graph); setList(result); setNewKind(null); setWizard(null); setRoiKey('roi')
      setSelected(result.tasks.find((item) => !previousIds.has(item.task_id))?.task_id ?? '')
    } finally { setBusy(false) }
  }
  async function deleteTask() {
    if (!task || readOnly) return
    await flushEdits()
    if (!await confirm(t('inspect.deleteConfirm'), { title: t('inspect.remove') })) return
    const before = currentGraph()
    const result = await removeInspection(before, task.task_id)
    const next = inspectionRemovalGraph(before, result)
    if (next !== before) putGraph(next)
    else setDependencies(result.dependencies)
  }

  const image = useMemo<ImageRef | null>(() => {
    if (session.scratch) return session.scratch
    const report = run ?? session.previewRun
    if (!report || !graph) return null
    const sourceNodes = graph.nodes.filter((node) => ['image_source', 'fixed_image', 'stereo_grab', 'multi_light_grab'].includes(node.type) && node.params?.role !== 'reference')
    for (const node of sourceNodes) {
      const output = report.nodes[node.id]?.outputs.image
      if (output && typeof output === 'object' && 'ref' in output) return output as ImageRef
    }
    return null
  }, [graph, run, session.previewRun, session.scratch])

  async function runPreview(nextGraph?: FlowGraph) {
    if (locked || !auth.can('flows.run') || formInvalid && pending) return
    ++trialSequence.current
    await flushEdits()
    const snapshot = nextGraph ?? currentGraph()
    const reuseRef = inspectionReuseRef(snapshot, session.scratch?.ref, reuse, image?.ref)
    if (!inspectionHasImage(snapshot, reuseRef)) { setOperationError(t('inspect.missingImage')); return }
    setOperationError(null)
    const report = await preview.mutateAsync({ flowId, graph: snapshot, reuse_image_ref: reuseRef, analysis: false })
    const result = await inspectionEvidence(snapshot, report)
    // 獨立 PUT 不等待落地；頁面卸載也不取消已送出的摘要。
    void saveLastInspectionTrial(flowId, inspectionTrialPayload(snapshot, report, result.items)).catch(() => {
      /* 裝置摘要保留作伺服器失敗時的退路。 */
    })
    publishAssistantProgress(flowId, { last_trial: { at: new Date().toISOString(), status: report.status,
      summary: report.error || `${Math.round(report.duration_ms)} ms`, per_task: result.items.map((item) => ({ task_id: item.task_id, status: item.verdict, value: item.value })) } })
    if (!alive.current) return
    rememberInspectionRun(flowId, snapshot, report, result.items)
    updateSession(flowId, { previewRun: report }); setRun(report); setReadings(result.items); setRunHash(inspectGraphHash(snapshot))
  }
  useRegisterAssistantContext({
    kind: 'inspect', flowId, flowName: flow.data?.name, imageRef: image?.ref, execLocked: locked,
    getGraph: currentGraph, applyGraph: readOnly ? undefined : (next) => putGraph(next),
    prepareGraph: flushEdits, showProposals: setProposals, proposalTasks: setProposalTasks,
    runInspection: auth.can('flows.run') && !locked ? () => runPreview() : undefined,
  }, [flowId, flow.data?.name, image?.ref, locked, readOnly, graph, pending, busy, reuse, auth.me])
  async function teachPose() {
    if (!task || !run?.id || stale || readOnly) return
    const result = await teachInspectionPose(currentGraph(), task.task_id, run)
    putGraph(result.graph)
    await runPreview(result.graph)
  }
  async function saveWithBaseline(updatedAt: string | null) {
    const current = getSession(flowId).draft
    if (!current) return
    const saved = await patch.mutateAsync({ id: flowId, graph: current.graph, name: current.name, description: current.description, expected_updated_at: updatedAt })
    baseline.current = saved.updated_at
    publishAssistantProgress(flowId, { flow_updated_at: saved.updated_at, flow_version: saved.version }, 'Flow saved.')
    const latest = getSession(flowId).draft
    const changedWhileSaving = latest && inspectGraphHash(latest.graph) !== inspectGraphHash(current.graph)
    setDraft(flowId, changedWhileSaving ? { ...latest, baseVersion: saved.version, dirty: true } : { ...current, graph: saved.graph, baseVersion: saved.version, dirty: false })
    toast.success(t('editor.toast.saved'))
  }
  async function save() {
    if (readOnly || newKind || formInvalid) return
    await flushEdits()
    try { await saveWithBaseline(baseline.current) } catch (error) {
      if (!showConflict(error, { flowId, graph: currentGraph(),
        loadServer: (details) => {
          baseline.current = details.updated_at
          const current = getSession(flowId).draft
          if (current) setDraft(flowId, { ...current, graph: details.graph, baseVersion: details.version, dirty: false })
          ++trialSequence.current; forgetInspectionRun(flowId); setRunHash(null); setReadings([]); setRun(null)
        }, overwrite: saveWithBaseline,
      })) throw error
    }
  }
  const saveRef = useRef(save)
  saveRef.current = save
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); void action(() => saveRef.current()) }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])
  const dirty = Boolean(session.draft?.dirty || pending || newKind)
  const blocker = useBlocker(useCallback(({ nextLocation }: { nextLocation: { pathname: string } }) => {
    if (pending || newKind) return true
    return dirty && nextLocation.pathname !== editorPath && !nextLocation.pathname.startsWith(`${editorPath}/`)
  }, [dirty, pending, newKind, editorPath]))
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    void confirm(t('editor.leaveUnsaved'), { title: t('editor.leaveTitle'), confirmLabel: t('editor.leaveAnyway') }).then(async (ok) => {
      if (!ok) return blocker.reset()
      try { await flushEdits(); blocker.proceed() } catch { blocker.reset() }
    })
  }, [blocker, confirm, t])
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [dirty])
  useEffect(() => { alive.current = true; return () => { alive.current = false; clearTimeout(timer.current) } }, [])

  async function changeSource(sourceId: string) {
    if (readOnly) return
    await flushEdits()
    const next = structuredClone(currentGraph())
    let source = next.nodes.find((node) => ['image_source', 'fixed_image'].includes(node.type) && node.params?.role !== 'reference')
    if (!source) {
      let id = 'source'
      while (next.nodes.some((node) => node.id === id)) id += '_'
      source = { id, type: 'image_source', params: {} }
      next.nodes.unshift(source)
    }
    source.type = sourceId === 'fixed' ? 'fixed_image' : 'image_source'
    source.params = sourceId === 'fixed' ? { images: [], mode: 'cycle', role: 'acquire' } : { source_id: sourceId ? Number(sourceId) : null, mode: 'auto' }
    updateSession(flowId, { scratch: null, previewRun: null })
    ++trialSequence.current; forgetInspectionRun(flowId); setRunHash(null); setReadings([]); setRun(null)
    putGraph(next)
  }
  async function changeNodeParam(nodeId: string, key: string, value: unknown) {
    if (readOnly) return
    await flushEdits()
    const next = structuredClone(currentGraph())
    const node = next.nodes.find((entry) => entry.id === nodeId)
    if (!node) return
    node.params = { ...node.params, [key]: value }
    const result = await readInspection(next)
    putGraph(next); setList(result)
  }
  async function uploadImage(file: File) {
    if (!readOnly && !currentGraph().nodes.some((node) => ['image_source', 'fixed_image', 'stereo_grab', 'multi_light_grab'].includes(node.type) && node.params?.role !== 'reference')) await changeSource('')
    updateSession(flowId, { scratch: await upload.mutateAsync({ flowId, file }) })
    ++trialSequence.current; forgetInspectionRun(flowId); setRunHash(null); setReadings([]); setRun(null)
  }
  async function saveCrop() {
    if (!image?.ref || !cropKey || !cropRegion) return
    const desc = await fixedImageFromRef({ ref: image.ref, region: cropRegion, name: t('inspect.locatorMark') })
    changeField(cropKey, [...(Array.isArray(values[cropKey]) ? values[cropKey] as unknown[] : []), desc]); setCropKey(null); setCropRegion(null)
  }
  const actions: InspectorActions = {
    roiEditingKey: roiKey, setRoiEditing: (key) => { setRoiKey(key); setAdvancedRoi(null) }, templateFromImage: () => undefined, templateKey: null, hasImage: Boolean(image?.ref),
    addImageFromCurrent: (key) => { setCropKey(key); setCropRegion(null) },
  }

  if (flow.isError || kinds.isError || tools.isError) return <ErrorState error={flow.error ?? kinds.error ?? tools.error} />
  if (!graph || !session.draft || kinds.isPending || tools.isPending) return <LoadingState />
  const activeRoi = kind?.fields.find((field) => field.key === roiKey && field.kind === 'roi')
  const source = graph.nodes.find((node) => ['image_source', 'fixed_image'].includes(node.type) && node.params?.role !== 'reference')
  const readingUnit = reading && ['defect', 'defects'].includes(reading.unit) ? t('inspect.defectCount', { count: Number(reading.value) }) : reading?.unit
  const taskTitle = (entry: typeof list.tasks[number]) => `${String(entry.fields.result_name || kinds.data?.items.find((item) => item.kind === entry.kind)?.label || entry.kind)} ${list.tasks.filter((item) => item.kind === entry.kind).indexOf(entry) + 1}`
  const taskNodes = graph.nodes.filter((node) => Object.values(task?.nodes ?? {}).includes(node.id))
  const fixedImages = Array.isArray(source?.params?.images) ? (source.params.images as unknown[]) : []
  const visibleFields = kind ? kind.fields.filter((field) => inspectionFieldVisible(field, values)) : []
  const wizardSteps: WizardStep[] = kind && visibleFields.some((field) => wizardStepOf(field) === 1) ? [1, 2] : [2]
  const renderField = (field: InspectField) => <div key={field.key} data-field={field.key} onBlur={() => { if (!newKind && edits.current) void action(flushEdits) }}>
    {field.key === 'locator' ? <label className="label">{field.label}<select className="input" value={String(values.locator ?? '')} onChange={(event) => changeField('locator', event.target.value)}><option value="">{t('common.none')}</option>{list.tasks.filter((entry) => entry.kind === 'locate_part' && (newKind || entry.task_id !== selected) && !entry.custom).map((entry) => <option key={entry.task_id} value={entry.task_id}>{taskTitle(entry)}</option>)}</select></label> : field.source_type === 'geometry' ? <GeometrySourceField field={field} value={values[field.key]} graph={graph} nodeId={newKind ? undefined : task?.nodes.defect} defs={defs} onChange={(value) => changeField(field.key, value)} /> : <ParamField param={inspectionParam(field)} value={values[field.key]} onChange={(value) => changeField(field.key, value)} actions={actions} />}
    {field.kind === 'output_key' && typeof values[field.key] === 'string' && values[field.key] !== '' && !OUTPUT_NAME.test(String(values[field.key])) ? <p className="mt-1 text-xs text-warning" role="alert">{t('inspect.badResultName')}</p> : null}
    {kind?.kind === 'inspect_edge_defect' && field.key === 'model' ? <Button size="sm" disabled={!image?.ref || readOnly || busy} onClick={() => void action(async () => {
      if (!image?.ref) return
      const result = await teachContourFromImage(flowId, { ref: image.ref, roi: values.roi as Region | null })
      changeField('model', result.model)
    })}>{t('editor.teachContour.action')}</Button> : null}
  </div>

  return <div className="flex h-full flex-col" data-testid="inspect-page">
    {dialog}{conflictDialog}
    <header className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-3 py-2">
      <h1 className="mr-auto text-sm font-semibold">{t('inspect.title')} <span className="text-muted">· {session.draft.name}</span></h1>
      {readOnly ? <span className="text-xs text-warning">{t('inspect.readOnly')}</span> : null}
      <Button icon={<Play size={14} />} loading={preview.isPending} disabled={locked || !auth.can('flows.run') || busy || Boolean(newKind) || pending && formInvalid} onClick={() => void action(() => runPreview())} data-testid="inspect-run">{t('inspect.run')}</Button>
      <Button icon={<Save size={14} />} loading={patch.isPending} disabled={readOnly || busy || Boolean(newKind) || formInvalid} onClick={() => void action(save)} data-testid="inspect-save">{t('inspect.save')}</Button>
      {dirty ? <span className="text-xs text-warning">{t('inspect.unsaved')}</span> : null}
      <span className={`rounded px-2 py-1 text-xs ${stale ? 'text-muted' : run?.status === 'ok' ? 'text-ok' : 'text-warning'}`} data-testid="inspect-overall">{stale ? t('inspect.status.stale') : inspectionOverall(run, stale)}</span>
      <Link className="btn-secondary" to={editorPath}>{t('inspect.advancedFlow')}</Link>
      <div className="flex w-full flex-wrap items-center gap-2 text-xs">
        <label>{t('inspect.source')} <select className="input !w-48" value={source?.type === 'fixed_image' ? 'fixed' : String(source?.params?.source_id ?? '')} disabled={readOnly || busy} onChange={(event) => void action(() => changeSource(event.target.value))} data-testid="inspect-source">
          <option value="">{t('common.none')}</option><option value="fixed">{t('inspect.fixedImages')}</option>{(sources.data?.items ?? []).map((item) => <option key={item.id} value={item.id}>{localiseDataName(item.name, i18n.language as Language)}</option>)}
        </select></label>
        <Button size="sm" icon={<ImageUp size={14} />} loading={upload.isPending} onClick={() => uploadInput.current?.click()}>{t('inspect.upload')}</Button>
        <input ref={uploadInput} className="hidden" type="file" accept="image/*" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void action(() => uploadImage(file)) }} />
        {session.scratch ? <Button size="xs" onClick={() => { updateSession(flowId, { scratch: null }); ++trialSequence.current; forgetInspectionRun(flowId); setRunHash(null); setReadings([]); setRun(null) }}>{session.scratch.name} · {t('inspect.clearImage')}</Button> : null}
        {source?.type === 'fixed_image' ? <span className="text-muted">{t('inspect.fixedImageSelection')}</span> : <label><input type="checkbox" checked={reuse} onChange={(event) => setReuse(event.target.checked)} /> {t('inspect.reuseImage')}</label>}
        {locked ? <span className="text-warning">{t('inspect.locked')}</span> : null}
      </div>
    </header>
    {source?.type === 'fixed_image' ? <details className="border-b border-line px-3 py-1" open={fixedOpen ?? fixedImages.length === 0} onToggle={(event) => setFixedOpen(event.currentTarget.open)} data-testid="inspect-fixed-images">
      {/* 收成一列：整條版面被縮圖佔滿時，任務清單與表單都被擠到看不見 */}
      <summary className="cursor-pointer text-xs text-muted">{t('inspect.fixedImages')} · {t('inspect.fixedImagesCount', { count: fixedImages.length })}</summary>
      <div className="max-h-40 overflow-y-auto py-2"><ImagesField label={t('inspect.fixedImages')} value={source.params?.images} readOnly={readOnly || busy} onChange={(value) => void action(() => changeNodeParam(source.id, 'images', value))} /></div>
    </details> : null}
    {(readError || operationError) ? <p role="alert" className="bg-critical-soft p-2 text-sm text-critical">{readError ?? operationError}</p> : null}
    <div className="flex min-h-0 flex-1 flex-col overflow-auto md:flex-row md:overflow-hidden">
      <aside className="w-full shrink-0 border-r border-line bg-surface p-3 md:w-56 md:overflow-y-auto" data-testid="inspect-tasks">
        {/* 新增／移除放在清單上方：使用者回報下拉式的新增不好找、移除藏在表單最底下 */}
        <div className="mb-3 flex gap-2">
          <Button size="sm" variant="primary" icon={<Plus size={14} />} disabled={readOnly || busy || wizard !== null} onClick={() => void action(openWizard)} data-testid="inspect-add">{t('inspect.add')}</Button>
          <Button size="sm" variant="danger" icon={<Trash2 size={14} />} disabled={readOnly || busy || !task || wizard !== null} onClick={() => void action(deleteTask)} data-testid="inspect-remove">{t('inspect.remove')}</Button>
        </div>
        <ul className="space-y-1">{list.tasks.map((item) => {
          const state = inspectionStatus(readings.find((row) => row.task_id === item.task_id), stale, item.custom)
          return <li key={item.task_id}><button className={`flex w-full items-center gap-2 rounded p-2 text-left text-sm ${selected === item.task_id && !newKind ? 'bg-brand-soft' : 'hover:bg-surface-muted'}`} onClick={() => void action(() => selectTask(item.task_id))} data-testid="inspect-task">
            <span className={`size-2.5 shrink-0 rounded-full ${INSPECT_DOTS[state]}`} title={t(`inspect.status.${state}`)} />
            {proposalTasks.includes(item.task_id) && <span className="size-2 shrink-0 rounded-full bg-warning" title={t('assistant.tasklist.status.assumed')} />}
            <span className="min-w-0"><span className="block truncate">{String(item.fields.result_name || kinds.data?.items.find((entry) => entry.kind === item.kind)?.label || item.kind)}</span><span className="block text-xs text-muted">{t(`inspect.status.${state}`)}{item.disabled ? ` · ${t('inspect.disabled')}` : ''}</span></span>
          </button>{item.custom ? <ul className="space-y-1 px-2 pb-2 text-xs text-warning" data-testid="inspect-custom-reasons">{item.reasons.map((reason, index) => <li key={index}><Link to={inspectionAdvancedPath(flowId, graph, { ...item, reasons: [reason] })}>{t(inspectionReasonKey(reason.code))}</Link></li>)}</ul> : null}</li>
        })}</ul>
        {!list.tasks.length ? <div className="my-3 text-xs text-muted"><p>{list.loose.length ? t('inspect.advancedOnly') : t('inspect.noTasks')}</p>{list.loose.length ? <Link className="mt-2 block text-brand" to={editorPath}>{t('inspect.openAdvanced')}</Link> : null}</div> : null}
      </aside>
      <section className="w-full shrink-0 space-y-4 overflow-y-auto border-r border-line bg-surface p-4 md:w-[340px] xl:w-[380px]" data-testid="inspect-form">
        <FlowNotesLink flowId={flowId} />
        {wizard !== null ? <div className="space-y-4" data-testid="inspect-wizard">
            {/* 引導精靈：種類 → 區域 → 規格，每一步只看該步的欄位；步驟標籤可以來回點 */}
            <ol className="flex flex-wrap gap-1 text-xs" aria-label={t('inspect.add')}>
              {([0, ...wizardSteps] as WizardStep[]).map((step, index, all) => <li key={step}>
                <button type="button" className={`rounded-full px-2 py-0.5 ${wizard === step ? 'bg-brand text-white' : 'bg-surface-muted text-muted'}`} disabled={step !== 0 && !newKind} onClick={() => setWizard(step)} aria-current={wizard === step ? 'step' : undefined}>
                  {index + 1}. {t(`inspect.wizard.${step === 0 ? 'kind' : step === 1 ? 'region' : 'spec'}`)}
                </button>{index < all.length - 1 ? <span className="px-1 text-muted">›</span> : null}
              </li>)}
            </ol>
            {wizard === 0 ? <>
              <p className="text-xs text-muted">{t('inspect.wizard.kindHint')}</p>
              <div className="grid gap-2">{kinds.data?.items.map((item) => <button key={item.kind} type="button" className="rounded-md border border-line p-2 text-left hover:border-brand hover:bg-brand-soft" disabled={readOnly || busy} onClick={() => void action(() => beginTask(item))} data-testid={`inspect-kind-${item.kind}`}>
                <span className="block text-sm font-medium">{item.label}</span><span className="block text-xs text-muted">{item.help_text}</span>
              </button>)}</div>
              <Button onClick={cancelWizard}>{t('common.cancel')}</Button>
            </> : kind ? <>
              <h2 className="font-semibold">{kind.label}</h2>
              <p className="text-xs text-muted">{t(wizard === 1 ? 'inspect.wizard.regionHint' : 'inspect.wizard.specHint')}</p>
              <fieldset disabled={readOnly} className="space-y-4">{visibleFields.filter((field) => wizardStepOf(field) === wizard).map(renderField)}</fieldset>
              {wizard === 2 && needsCalibration ? <p className="text-sm text-warning" role="alert">{t('inspect.needsCalibration')} <Link className="underline" to="/calibration">{t('inspect.openCalibration')}</Link></p> : null}
              <div className="flex flex-wrap gap-2">
                <Button icon={<ChevronLeft size={14} />} onClick={() => setWizard(wizard === 2 && wizardSteps.length > 1 ? 1 : 0)} data-testid="inspect-back">{t('inspect.wizard.back')}</Button>
                {wizard === 1 ? <Button variant="primary" icon={<ChevronRight size={14} />} onClick={() => setWizard(2)} data-testid="inspect-next">{t('inspect.wizard.next')}</Button>
                  : <Button variant="primary" icon={<Plus size={14} />} disabled={readOnly || formInvalid || busy} onClick={() => void action(createTask)} data-testid="inspect-create">{t('inspect.wizard.create')}</Button>}
                <Button onClick={cancelWizard}>{t('common.cancel')}</Button>
              </div>
            </> : null}
          </div>
        : task?.custom ? <div data-testid="inspect-custom"><p className="text-warning">{t('inspect.customHint')}</p>{task.reasons.map((reason, index) => <p key={index} className="mt-1 text-xs">{t(inspectionReasonKey(reason.code))}</p>)}<Link className="btn-secondary mt-3" to={inspectionAdvancedPath(flowId, graph, task)}>{t('inspect.openAdvanced')}</Link></div>
        : kind ? <><h2 className="font-semibold">{kind.label}</h2><p className="text-xs text-muted">{kind.help_text}</p>
            {/* 只在唯讀時停用：以前背景送出時也停用，每打幾個字輸入框就失去焦點一次 */}
            <fieldset disabled={readOnly} className="space-y-4">{visibleFields.map(renderField)}</fieldset>
            {needsCalibration ? <p className="text-sm text-warning" role="alert">{t('inspect.needsCalibration')} <Link className="underline" to="/calibration">{t('inspect.openCalibration')}</Link></p> : null}
          <details><summary className="cursor-pointer text-sm font-medium">{t('inspect.advanced')}</summary><fieldset disabled={readOnly || busy} className="space-y-4 pt-3">{taskNodes.map((node) => <section key={node.id}><h3 className="mb-2 text-sm font-semibold">{node.label || defs.get(node.type)?.label || node.type}</h3>{defs.get(node.type)?.params.filter((param) => !param.visible_when || param.visible_when.in.includes(node.params?.[param.visible_when.param])).map((param) => <div className="mb-3" key={param.key}><ParamField param={param} value={node.params?.[param.key] ?? param.default} actions={{ ...actions, addImageFromCurrent: undefined,
            roiEditingKey: advancedRoi?.nodeId === node.id ? advancedRoi.key : null,
            setRoiEditing: (key) => { setRoiKey(null); setAdvancedRoi(key ? { nodeId: node.id, key, shapes: param.shapes } : null) },
          }} onChange={(value) => void action(() => changeNodeParam(node.id, param.key, value))} /></div>)}</section>)}</fieldset></details>
        </> : <p className="text-sm text-muted">{t('inspect.chooseTask')}</p>}
      </section>
      <section className="flex min-h-[420px] min-w-0 flex-1 flex-col" data-testid="inspect-viewer">
        <div className="min-h-[300px] flex-1"><ImageViewer proposals={proposals} src={image?.ref ? imageUrl(image.ref, 1600) : null} imageWidth={image?.width ?? 0} imageHeight={image?.height ?? 0} overlays={reading?.overlays ?? []}
          roi={cropKey ? cropRegion : advancedRoi ? graph.nodes.find((node) => node.id === advancedRoi.nodeId)?.params?.[advancedRoi.key] as Region | null : activeRoi ? values[activeRoi.key] as Region | null : null} roiShapes={cropKey ? ['rect'] : advancedRoi?.shapes ?? activeRoi?.shapes}
          onRoiChange={!readOnly && !busy && (!task?.custom || Boolean(newKind)) ? cropKey ? setCropRegion : advancedRoi ? (region) => void action(() => changeNodeParam(advancedRoi.nodeId, advancedRoi.key, region)) : activeRoi ? (region) => changeField(activeRoi.key, region) : undefined : undefined}
          className="h-full w-full" stateKey={`inspect:${flowId}`} toolbar /></div>
        <div className="space-y-2 border-t border-line bg-surface p-4" data-testid="inspect-reading">
          <p className="text-sm font-semibold">{t(`inspect.status.${status}`)}</p>
          <p title={reading?.value == null ? undefined : `${String(reading.value)} ${readingUnit}`} className={`font-mono text-2xl ${stale ? 'text-muted line-through' : ''}`}>{inspectionValue(reading)} {inspectionValue(reading) !== '—' ? readingUnit : ''}</p>
          {stale && !newKind ? <p className="text-xs text-muted">{t('inspect.staleHint')}</p> : null}
          {reading?.reason ? <p className="text-xs text-muted">{reading.reason}</p> : null}
          {task?.kind === 'locate_part' && !newKind ? <p className="text-xs text-muted" data-testid="inspect-teach-hint">{t('inspect.teachHint')}</p> : null}
          {task?.kind === 'locate_part' && reading?.verdict === 'pass' && !stale && !newKind ? <Button disabled={!run?.id || readOnly || preview.isPending} onClick={() => void action(teachPose)} data-testid="inspect-teach-pose">{t('inspect.teachPose')}</Button> : null}
          {cropKey ? <div className="flex gap-2"><Button disabled={!cropRegion} onClick={() => void action(saveCrop)}>{t('inspect.saveCrop')}</Button><Button onClick={() => setCropKey(null)}>{t('common.cancel')}</Button></div> : null}
        </div>
      </section>
    </div>
    <Modal open={dependencies !== null} onClose={() => setDependencies(null)} title={t('inspect.dependencies')} footer={<Button onClick={() => setDependencies(null)}>{t('common.close')}</Button>}>
      <p className="mb-3 text-sm">{t('inspect.dependenciesHint')}</p><ul>{dependencies?.map((item, index) => {
        const node = graph.nodes.find((entry) => entry.id === item.target)
        const port = defs.get(node?.type ?? '')?.inputs.find((entry) => entry.key === item.target_handle)
        return <li key={index}>{item.title || node?.label || defs.get(node?.type ?? '')?.label || item.target} · {port?.label || item.target_handle}</li>
      })}</ul>
    </Modal>
  </div>
}

export function InspectPage() {
  const { flowId } = useParams<{ flowId: string }>()
  const id = Number(flowId)
  return Number.isInteger(id) && id > 0 ? <InspectPageInner key={id} flowId={id} /> : null
}
import { FlowNotesLink } from '@/components/notes/FlowNotesLink'
