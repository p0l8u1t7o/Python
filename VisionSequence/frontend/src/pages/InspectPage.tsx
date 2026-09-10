/** 檢測任務頁：共用流程草稿，任務修改經核心翻譯器序列化送出。 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useBlocker, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Plus, Play, Save, Trash2, ImageUp } from 'lucide-react'
import { ParamField, type InspectorActions } from '@/components/editor/ParamField'
import { useSaveConflictDialog } from '@/components/flow/SaveConflictDialog'
import { Button, ErrorState, LoadingState, Modal } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { fixedImageFromRef, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { getSession, setDraft, updateSession, useFlowSession } from '@/lib/flowDraft'
import { INSPECT_DOTS, forgetInspectionRun, inspectGraphHash, inspectionAdvancedPath, inspectionDefaults, inspectionEditableKind, inspectionOverall, inspectionParam, inspectionReasonKey, inspectionRemovalGraph, inspectionRunFor, inspectionStale, inspectionStatus, inspectionValue, missingInspectionFields, rememberInspectionRun } from '@/lib/inspect'
import { inspectionEvidence, readInspection, removeInspection, teachInspectionPose, useFlow, useFlowMutations, useInspectKinds, usePreviewFlow, useScratchImage, useSources, useToolTypes, writeInspection } from '@/lib/queries'
import type { FlowGraph, ImageRef, InspectDependency, InspectKind, InspectList, InspectReading, Region, RoiShape, RunReport } from '@/lib/types'
import { useConfirm } from '@/lib/useConfirm'
import { isLockHolder, useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

const EMPTY_LIST: InspectList = { tasks: [], shared: [], loose: [] }

function InspectPageInner({ flowId }: { flowId: number }) {
  const { t } = useTranslation()
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
  const uploadInput = useRef<HTMLInputElement>(null)
  const baseline = useRef<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const edits = useRef<{ task_id: string; fields: Record<string, unknown> } | null>(null)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const alive = useRef(true)
  const readSequence = useRef(0)
  const readOnly = !auth.can('flows.edit')
  const locked = auth.lock.locked && !isLockHolder(auth.me, auth.lock) && auth.me?.kind !== 'integrator'
  const graph = session.draft?.graph
  const editorPath = `/flows/${flowId}`
  const task = list.tasks.find((item) => item.task_id === selected)
  const kind = newKind ? kinds.data?.items.find((item) => item.kind === newKind) : inspectionEditableKind(task, kinds.data?.items ?? [])
  const stale = Boolean(runHash && (pending || busy || (graph && inspectionStale(graph, runHash))))
  const reading = readings.find((item) => item.task_id === selected)
  const status = inspectionStatus(reading, stale, task?.custom)
  const defs = useMemo(() => new Map((tools.data?.items ?? []).map((item) => [item.key, item])), [tools.data])

  useEffect(() => {
    if (!flow.data || baseline.current !== null) return
    baseline.current = flow.data.updated_at
    const old = getSession(flowId).draft
    if (!old || (!old.dirty && old.baseVersion !== flow.data.version)) {
      setDraft(flowId, { baseVersion: flow.data.version, graph: flow.data.graph, name: flow.data.name, description: flow.data.description, dirty: false })
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
    const change = edits.current
    if (!change) return queue.current
    edits.current = null
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
    const changed = { [key]: value, ...(key === 'calibration' ? { unit: value ? 'mm' : 'px' } : {}), ...(key === 'unit' && value === 'px' ? { calibration: '' } : {}) }
    const nextValues = { ...values, ...changed }
    setValues(nextValues)
    setOperationError(null)
    if (newKind || !task) return
    edits.current = { task_id: task.task_id, fields: { ...edits.current?.fields, ...changed } }
    setPending(true)
    clearTimeout(timer.current)
    if (kind && !missingInspectionFields(kind, nextValues).length && !(nextValues.unit === 'mm' && !nextValues.calibration)) {
      timer.current = setTimeout(() => void action(flushEdits), 250)
    }
  }
  async function selectTask(id: string) {
    await flushEdits()
    setNewKind(null); setSelected(id); setRoiKey('roi'); setCropKey(null); setAdvancedRoi(null)
    setValues(list.tasks.find((item) => item.task_id === id)?.fields ?? {})
  }
  async function beginTask(item: InspectKind) {
    await flushEdits()
    setNewKind(item.kind); setValues(inspectionDefaults(item)); setRoiKey('roi'); setCropKey(null); setAdvancedRoi(null)
  }
  const invalid = kind ? missingInspectionFields(kind, values) : []
  const needsCalibration = values.unit === 'mm' && !values.calibration
  const unsupportedLocator = kind?.kind === 'locate_part' && values.method !== 'template'
  const formInvalid = invalid.length > 0 || needsCalibration || unsupportedLocator

  async function createTask() {
    if (!kind || readOnly || formInvalid) return
    setBusy(true)
    try {
      const next = await writeInspection('build', currentGraph(), { kind: kind.kind, version: kind.version, fields: values })
      const previousIds = new Set(list.tasks.map((item) => item.task_id))
      const result = await readInspection(next.graph)
      putGraph(next.graph); setList(result); setNewKind(null)
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
    await flushEdits()
    const snapshot = nextGraph ?? currentGraph()
    const report = await preview.mutateAsync({ flowId, graph: snapshot, reuse_image_ref: session.scratch?.ref ?? (reuse ? image?.ref : null), analysis: false })
    const result = await inspectionEvidence(snapshot, report)
    if (!alive.current) return
    rememberInspectionRun(flowId, snapshot, report, result.items)
    updateSession(flowId, { previewRun: report }); setRun(report); setReadings(result.items); setRunHash(inspectGraphHash(snapshot))
  }
  async function teachPose() {
    if (!task || !run || stale || readOnly) return
    const result = await teachInspectionPose(currentGraph(), task.task_id, run)
    putGraph(result.graph)
    await runPreview(result.graph)
  }
  async function saveWithBaseline(updatedAt: string | null) {
    const current = getSession(flowId).draft
    if (!current) return
    const saved = await patch.mutateAsync({ id: flowId, graph: current.graph, name: current.name, description: current.description, expected_updated_at: updatedAt })
    baseline.current = saved.updated_at
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
          forgetInspectionRun(flowId); setRunHash(null); setReadings([]); setRun(null)
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
    source.type = 'image_source'
    source.params = { source_id: sourceId ? Number(sourceId) : null, mode: 'auto' }
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
    updateSession(flowId, { scratch: await upload.mutateAsync({ flowId, file }) })
    if (!readOnly && !currentGraph().nodes.some((node) => ['image_source', 'fixed_image', 'stereo_grab', 'multi_light_grab'].includes(node.type) && node.params?.role !== 'reference')) await changeSource('')
    forgetInspectionRun(flowId); setRunHash(null); setReadings([]); setRun(null)
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
  const source = graph.nodes.find((node) => node.type === 'image_source')
  const taskNodes = graph.nodes.filter((node) => Object.values(task?.nodes ?? {}).includes(node.id))

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
        <label>{t('inspect.source')} <select className="input !w-48" value={String(source?.params?.source_id ?? '')} disabled={readOnly || busy} onChange={(event) => void action(() => changeSource(event.target.value))} data-testid="inspect-source">
          <option value="">{t('common.none')}</option>{(sources.data?.items ?? []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <Button size="sm" icon={<ImageUp size={14} />} loading={upload.isPending} onClick={() => uploadInput.current?.click()}>{t('inspect.upload')}</Button>
        <input ref={uploadInput} className="hidden" type="file" accept="image/*" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void action(() => uploadImage(file)) }} />
        {session.scratch ? <Button size="xs" onClick={() => { updateSession(flowId, { scratch: null }); forgetInspectionRun(flowId); setRunHash(null); setReadings([]); setRun(null) }}>{session.scratch.name} · {t('inspect.clearImage')}</Button> : null}
        <label><input type="checkbox" checked={reuse} onChange={(event) => setReuse(event.target.checked)} /> {t('inspect.reuseImage')}</label>
        {locked ? <span className="text-warning">{t('inspect.locked')}</span> : null}
      </div>
    </header>
    {(readError || operationError) ? <p role="alert" className="bg-critical-soft p-2 text-sm text-critical">{readError ?? operationError}</p> : null}
    <div className="flex min-h-0 flex-1 flex-col overflow-auto md:flex-row md:overflow-hidden">
      <aside className="w-full shrink-0 border-r border-line bg-surface p-3 md:w-56 md:overflow-y-auto" data-testid="inspect-tasks">
        <label className="label" htmlFor="inspect-add">{t('inspect.add')}</label>
        <select id="inspect-add" className="input mb-3" value={newKind ?? ''} disabled={readOnly || busy} onChange={(event) => { const item = kinds.data?.items.find((entry) => entry.kind === event.target.value); if (item) void action(() => beginTask(item)) }} data-testid="inspect-add">
          <option value="">{t('inspect.chooseKind')}</option>{kinds.data?.items.map((item) => <option key={item.kind} value={item.kind}>{item.label}</option>)}
        </select>
        <ul className="space-y-1">{list.tasks.map((item) => {
          const state = inspectionStatus(readings.find((row) => row.task_id === item.task_id), stale, item.custom)
          return <li key={item.task_id}><button className={`flex w-full items-center gap-2 rounded p-2 text-left text-sm ${selected === item.task_id && !newKind ? 'bg-brand-soft' : 'hover:bg-surface-muted'}`} onClick={() => void action(() => selectTask(item.task_id))} data-testid="inspect-task">
            <span className={`size-2.5 shrink-0 rounded-full ${INSPECT_DOTS[state]}`} title={t(`inspect.status.${state}`)} />
            <span className="min-w-0"><span className="block truncate">{String(item.fields.result_name || kinds.data?.items.find((entry) => entry.kind === item.kind)?.label || item.kind)}</span><span className="block text-xs text-muted">{t(`inspect.status.${state}`)}{item.disabled ? ` · ${t('inspect.disabled')}` : ''}</span></span>
          </button>{item.custom ? <ul className="space-y-1 px-2 pb-2 text-xs text-warning" data-testid="inspect-custom-reasons">{item.reasons.map((reason, index) => <li key={index}><Link to={inspectionAdvancedPath(flowId, graph, { ...item, reasons: [reason] })}>{t(inspectionReasonKey(reason.code))}</Link></li>)}</ul> : null}</li>
        })}</ul>
        {!list.tasks.length ? <div className="my-3 text-xs text-muted"><p>{list.loose.length ? t('inspect.advancedOnly') : t('inspect.noTasks')}</p>{list.loose.length ? <Link className="mt-2 block text-brand" to={editorPath}>{t('inspect.openAdvanced')}</Link> : null}</div> : null}
        <Link className="mt-4 block text-xs text-brand" to={editorPath}>{t('inspect.otherSteps', { count: list.loose.length })}</Link>
      </aside>
      <section className="w-full shrink-0 space-y-4 overflow-y-auto border-r border-line bg-surface p-4 md:w-[340px] xl:w-[380px]" data-testid="inspect-form">
        {task?.custom && !newKind ? <div data-testid="inspect-custom"><p className="text-warning">{t('inspect.customHint')}</p>{task.reasons.map((reason, index) => <p key={index} className="mt-1 text-xs">{t(inspectionReasonKey(reason.code))}</p>)}<Link className="btn-secondary mt-3" to={inspectionAdvancedPath(flowId, graph, task)}>{t('inspect.openAdvanced')}</Link><Button className="mt-3" variant="danger" disabled={readOnly || busy} onClick={() => void action(deleteTask)}>{t('inspect.remove')}</Button></div> : kind ? <><h2 className="font-semibold">{kind.label}</h2><p className="text-xs text-muted">{kind.help_text}</p>
            <fieldset disabled={readOnly || busy} className="space-y-4">
              {kind.fields.map((field) => <div key={field.key} data-field={field.key}>
                {field.key === 'locator' ? <label className="label">{field.label}<select className="input" value={String(values.locator ?? '')} onChange={(event) => changeField('locator', event.target.value)}><option value="">{t('common.none')}</option>{list.tasks.filter((entry) => entry.kind === 'locate_part' && entry.task_id !== selected && !entry.custom).map((entry) => <option key={entry.task_id} value={entry.task_id}>{String(entry.fields.result_name || entry.task_id)}</option>)}</select></label> : <ParamField param={inspectionParam(field)} value={values[field.key]} onChange={(value) => changeField(field.key, value)} actions={actions} />}
              </div>)}
            </fieldset>
            {needsCalibration ? <p className="text-sm text-warning" role="alert">{t('inspect.needsCalibration')} <Link className="underline" to="/calibration">{t('inspect.openCalibration')}</Link></p> : null}
            {unsupportedLocator ? <p className="text-sm text-warning">{t('inspect.templateOnly')}</p> : null}
            {newKind ? <div className="flex gap-2"><Button icon={<Plus size={14} />} disabled={readOnly || formInvalid || busy} onClick={() => void action(createTask)} data-testid="inspect-create">{t('inspect.add')}</Button><Button onClick={() => { setNewKind(null); setValues(task?.fields ?? {}) }}>{t('common.cancel')}</Button></div> : null}
          {!newKind && !task?.custom ? <details><summary className="cursor-pointer text-sm font-medium">{t('inspect.advanced')}</summary><fieldset disabled={readOnly || busy} className="space-y-4 pt-3">{taskNodes.map((node) => <section key={node.id}><h3 className="mb-2 text-sm font-semibold">{node.label || defs.get(node.type)?.label || node.type}</h3>{defs.get(node.type)?.params.filter((param) => !param.visible_when || param.visible_when.in.includes(node.params?.[param.visible_when.param])).map((param) => <div className="mb-3" key={param.key}><ParamField param={param} value={node.params?.[param.key] ?? param.default} actions={{ ...actions, addImageFromCurrent: undefined,
            roiEditingKey: advancedRoi?.nodeId === node.id ? advancedRoi.key : null,
            setRoiEditing: (key) => { setRoiKey(null); setAdvancedRoi(key ? { nodeId: node.id, key, shapes: param.shapes } : null) },
          }} onChange={(value) => void action(() => changeNodeParam(node.id, param.key, value))} /></div>)}</section>)}</fieldset></details> : null}
          {!newKind ? <Button variant="danger" icon={<Trash2 size={14} />} disabled={readOnly || busy} onClick={() => void action(deleteTask)}>{t('inspect.remove')}</Button> : null}
        </> : <p className="text-sm text-muted">{t('inspect.chooseTask')}</p>}
      </section>
      <section className="flex min-h-[420px] min-w-0 flex-1 flex-col" data-testid="inspect-viewer">
        <div className="min-h-[300px] flex-1"><ImageViewer src={image?.ref ? imageUrl(image.ref, 1600) : null} imageWidth={image?.width ?? 0} imageHeight={image?.height ?? 0} overlays={reading?.overlays ?? []}
          roi={cropKey ? cropRegion : advancedRoi ? graph.nodes.find((node) => node.id === advancedRoi.nodeId)?.params?.[advancedRoi.key] as Region | null : activeRoi ? values[activeRoi.key] as Region | null : null} roiShapes={cropKey ? ['rect'] : advancedRoi?.shapes ?? activeRoi?.shapes}
          onRoiChange={!readOnly && !busy && (!task?.custom || Boolean(newKind)) ? cropKey ? setCropRegion : advancedRoi ? (region) => void action(() => changeNodeParam(advancedRoi.nodeId, advancedRoi.key, region)) : activeRoi ? (region) => changeField(activeRoi.key, region) : undefined : undefined}
          className="h-full w-full" stateKey={`inspect:${flowId}`} toolbar /></div>
        <div className="space-y-2 border-t border-line bg-surface p-4" data-testid="inspect-reading">
          <p className="text-sm font-semibold">{t(`inspect.status.${status}`)}</p>
          <p className={`font-mono text-2xl ${stale ? 'text-muted line-through' : ''}`}>{inspectionValue(reading)} {inspectionValue(reading) !== '—' ? reading?.unit : ''}</p>
          {stale ? <p className="text-xs text-muted">{t('inspect.staleHint')}</p> : null}
          {reading?.reason ? <p className="text-xs text-muted">{reading.reason}</p> : null}
          {task?.kind === 'locate_part' && reading?.verdict === 'pass' && !stale && !newKind ? <Button disabled={readOnly || preview.isPending} onClick={() => void action(teachPose)} data-testid="inspect-teach-pose">{t('inspect.teachPose')}</Button> : null}
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
