/**
 * 深度學習頁（DlPage）`/dl`：平台內教導——建立教導專案、收集與標記樣本、
 * 自動標記（kNN 建議＋批次接受）、伺服端訓練（裝置選擇、進度、指標）、匯出模型到資產庫。
 * UI 由 /dl/trainers 的目錄資料驅動（超參數表單直接用 ParamField），之後導入新模型種類不用改前端。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { Archive, Brain, Camera, Check, Cpu, Database, Download, Image as ImageIcon, LayoutGrid, Play, Plus, Shuffle, Sparkles, Square, Trash2, Upload, X, Wand2 } from 'lucide-react'

import { Legend, Line, LineChart, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from 'recharts'

import { ClassifyWorkspace } from '@/components/dl/ClassifyWorkspace'
import { ShapeWorkspace } from '@/components/dl/ShapeWorkspace'
import { ParamField, type InspectorActions } from '@/components/editor/ParamField'
import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, CardBody, ConfirmDialog, EmptyState, LoadingState, Modal, PageHeader, Panel, SegmentedControl, Select, TextInput } from '@/components/ui'
import { assetUrl, dlSampleUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useConfirm } from '@/lib/useConfirm'
import { useDlDevices, useDlMutations, useDlProject, useDlProjects, useDlRetrievalLibrary, useDlSamples, useDlTrainers, useDlTrainStatus, useDlVersions, useFlowMutations, useSources } from '@/lib/queries'
import type { DlDatasetVersion, DlProject, DlQuickRegisterResult, DlRetrievalLibrary, DlSample, DlShape, DlSuggestion, DlTrainerDef } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'
import { CURVE_COLORS, classColor, classColorAt } from '@/lib/colors'

const NO_ACTIONS: InspectorActions = { roiEditingKey: null, setRoiEditing: () => {}, templateFromImage: () => {}, templateKey: null, hasImage: false }

// ---------------------------------------------------------------------------
// 建立專案
// ---------------------------------------------------------------------------
function CreateProjectModal({ open, onClose, trainers, onCreated }: { open: boolean; onClose: () => void; trainers: DlTrainerDef[]; onCreated: (p: DlProject) => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { createProject } = useDlMutations()
  const [name, setName] = useState('')
  const [kind, setKind] = useState(trainers[0]?.kind ?? '')
  const trainer = trainers.find((x) => x.kind === (kind || trainers[0]?.kind))

  async function submit() {
    try {
      // 類別與超參數都在專案頁內設定（各模型各自的頁面），建立時只要名稱與模型種類。
      const project = await createProject.mutateAsync({ name: name.trim(), trainer_kind: trainer?.kind ?? '', classes: [] })
      toast.success(t('dl.created'))
      onCreated(project)
      onClose()
      setName('')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={t('dl.newProject')} dirty={Boolean(name)}
      footer={<><Button onClick={onClose}>{t('common.cancel')}</Button><Button variant="primary" loading={createProject.isPending} disabled={!name.trim()} onClick={() => void submit()}>{t('common.create')}</Button></>}>
      <div className="space-y-3">
        <TextInput label={t('dl.projectName')} value={name} onChange={(e) => setName(e.target.value)} autoFocus data-testid="dl-name" />
        <Select label={t('dl.trainerKind')} value={kind || trainers[0]?.kind || ''} onChange={(e) => setKind(e.target.value)}
          options={trainers.map((x) => ({ value: x.kind, label: x.label }))} />
        {trainer ? <p className="text-xs text-muted">{trainer.description}</p> : null}
        <p className="text-xs text-subtle">{t('dl.createHint')}</p>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// 類別編輯（專案頁內設定；classes / shapes 兩種模式共用）
// ---------------------------------------------------------------------------
function ClassesModal({ open, onClose, classes, onSave, saving }: { open: boolean; onClose: () => void; classes: string[]; onSave: (list: string[]) => Promise<void>; saving: boolean }) {
  const { t } = useTranslation()
  const [list, setList] = useState<string[]>(classes)
  const [text, setText] = useState('')
  useEffect(() => {
    if (open) {
      setList(classes)
      setText('')
    }
  }, [open, classes])

  function add() {
    // 同一次輸入內也要去重（例如「A,A」），否則 chips 的 key 會撞、顏色索引錯亂
    const names = [...new Set(text.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean))].filter((n) => !list.includes(n))
    if (names.length) setList((old) => [...old, ...names])
    setText('')
  }

  // dirty 涵蓋清單增刪（不只輸入框文字），Esc／點背景才會先確認
  const listDirty = text !== '' || JSON.stringify(list) !== JSON.stringify(classes)

  return (
    <Modal open={open} onClose={onClose} title={t('dl.classesTitle')} description={t('dl.classesRemoveHint')} dirty={listDirty}
      footer={<><Button onClick={onClose}>{t('common.cancel')}</Button><Button variant="primary" loading={saving} onClick={() => void onSave(list).then(onClose).catch(() => {})} data-testid="dl-classes-save">{t('common.save')}</Button></>}>
      <div className="space-y-3">
        <div className="flex min-h-9 flex-wrap items-center gap-1.5">
          {list.map((c, i) => (
            <span key={c} className="flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-xs">
              <span className="size-2 rounded-full" style={{ background: classColorAt(i) }} />
              {c}
              <button type="button" className="text-muted hover:text-critical" aria-label={`${t('common.delete')} ${c}`} onClick={() => setList((old) => old.filter((x) => x !== c))}><X size={12} /></button>
            </span>
          ))}
          {!list.length ? <span className="text-xs text-subtle">{t('dl.noClasses')}</span> : null}
        </div>
        <div className="flex items-end gap-2">
          <TextInput label={t('dl.addClass')} hint={t('dl.classesHint')} value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} data-testid="dl-class-input" />
          <Button className="mb-6" onClick={add} disabled={!text.trim()}><Plus size={14} /></Button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// 從影像來源收集樣本
// ---------------------------------------------------------------------------
function FromSourceModal({ open, onClose, project, showLabel }: { open: boolean; onClose: () => void; project: DlProject; showLabel: boolean }) {
  const { t } = useTranslation()
  const toast = useToast()
  const sources = useSources()
  const { fromSource } = useDlMutations()
  const [sourceId, setSourceId] = useState('')
  const [count, setCount] = useState('5')
  const [label, setLabel] = useState('')

  async function submit() {
    try {
      const r = await fromSource.mutateAsync({ projectId: project.id, source_id: Number(sourceId), count: Number(count) || 1, label })
      toast.success(r.duplicates ? t('dl.grabbedDup', { count: r.items.length, dup: r.duplicates }) : t('dl.grabbed', { count: r.items.length }))
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={t('dl.fromSource')}
      footer={<><Button onClick={onClose}>{t('common.cancel')}</Button><Button variant="primary" loading={fromSource.isPending} disabled={!sourceId} onClick={() => void submit()}>{t('dl.grab')}</Button></>}>
      <div className="space-y-3">
        <Select label={t('dl.source')} value={sourceId} onChange={(e) => setSourceId(e.target.value)} placeholder={t('dl.pickSource')}
          options={(sources.data?.items ?? []).map((s) => ({ value: String(s.id), label: `${s.name} (${s.kind})` }))} />
        <TextInput label={t('dl.grabCount')} type="number" min={1} max={50} value={count} onChange={(e) => setCount(e.target.value)} />
        {showLabel ? (
          <Select label={t('dl.presetLabel')} value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t('dl.unlabeled')}
            options={project.classes.map((c) => ({ value: c, label: c }))} />
        ) : null}
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// 訓練面板
// ---------------------------------------------------------------------------
function TrainPanel({ project, trainer }: { project: DlProject; trainer: DlTrainerDef }) {
  const { t } = useTranslation()
  const toast = useToast()
  const devices = useDlDevices()
  const { startTrain, quickRegister, cancelTrain, saveModel, discardModel } = useDlMutations()
  const { confirm, dialog } = useConfirm()
  const [params, setParams] = useState<Record<string, unknown>>(() => ({ ...project.params }))
  const [assetName, setAssetName] = useState('')
  const [quickResult, setQuickResult] = useState<DlQuickRegisterResult | null>(null)
  /** 訓練完的命名（預設帶開始訓練時填的建議名稱） */
  const [saveName, setSaveName] = useState('')
  const [device, setDevice] = useState('')
  const isRetrieval = trainer.kind === 'retrieval'
  const job = useDlTrainStatus(true)
  const navigate = useNavigate()
  const flowMut = useFlowMutations()
  /** 訓練完一鍵建流程：取像（待選來源）→ 對應工具（已選好模型與建議參數）；編輯器橫幅會提醒選來源。 */
  async function createFlowWithModel() {
    const j = job.data
    if (!j || j.status !== 'done' || !j.asset_id) return
    const tool = j.tool_key || 'dl_classify'
    const graph = {
      nodes: [
        { id: 'src', type: 'image_source', label: '', enabled: true, params: {}, position: { x: 40, y: 40 } },
        { id: 'model', type: tool, label: '', enabled: true, params: { ...(j.tool_params ?? {}), model: j.asset_id }, position: { x: 320, y: 40 } },
      ],
      edges: [{ id: 'e-src-model', source: 'src', target: 'model', source_handle: 'image', target_handle: 'image' }],
    }
    const name = `${j.project_name} · ${j.asset_name}`.slice(0, 100)
    try {
      const flow = await flowMut.create.mutateAsync({ name, description: t('dl.createFlowDesc', { model: j.asset_name }), graph })
      toast.success(t('dl.createFlowDone', { name: flow.name }))
      navigate(`/flows/${flow.id}`)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  const running = job.data?.status === 'running'
  const mine = job.data && job.data.project_id === project.id
  const waiting = Boolean(mine && job.data?.status === 'done' && job.data?.pending)  // 訓練好、還沒決定

  async function keepModel() {
    const j = job.data
    if (!j) return
    try {
      const saved = await saveModel.mutateAsync(saveName.trim() || j.asset_name)
      toast.success(t('dl.saved', { name: saved.asset_name }))
      setSaveName('')
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function dropModel() {
    if (!(await confirm(t('dl.discardConfirm'), { confirmLabel: t('dl.discardModel') }))) return
    try {
      await discardModel.mutateAsync()
      toast.success(t('dl.discarded'))
      setSaveName('')
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function start() {
    try {
      await startTrain.mutateAsync({ projectId: project.id, params, device: device || devices.data?.train_device || 'cpu', asset_name: assetName })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  async function runQuickRegister() {
    try {
      const result = await quickRegister.mutateAsync({ projectId: project.id, device: device || devices.data?.train_device || 'cpu', asset_name: assetName })
      setQuickResult(result)
      setParams(result.params)
      toast.success(t('dl.quickRegisterStarted', { labeled: result.labeled, skipped: result.skipped }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const metrics = (mine ? job.data?.metrics : project.last_metrics) as Record<string, unknown> | undefined
  // 超參數依 Param.group 分組：主要參數直接顯示，其餘（進階…）收進可摺疊區塊，表單才不會過長
  const mainParams = trainer.params.filter((p) => !p.group)
  const groups = trainer.params.reduce<Record<string, typeof trainer.params>>((acc, p) => {
    if (p.group) (acc[p.group] ??= []).push(p)
    return acc
  }, {})
  const field = (p: (typeof trainer.params)[number]) => (
    <ParamField key={p.key} param={p} value={params[p.key] ?? p.default} onChange={(v) => setParams((old) => ({ ...old, [p.key]: v }))} actions={NO_ACTIONS} />
  )
  const percent = Math.round((job.data?.progress ?? 0) * 100)
  const statusTone: Record<string, 'ok' | 'info' | 'warning' | 'critical'> = { running: 'info', done: 'ok', failed: 'critical', cancelled: 'warning' }
  const canQuickRegister = trainer.kind === 'ai_detect'

  return (
    <Panel
      title={<span className="flex items-center gap-2">{isRetrieval ? <Database size={15} className="text-brand" /> : <Cpu size={15} className="text-brand" />}{t(isRetrieval ? 'dl.libraryBuild' : 'dl.train')}</span>}
      description={t(isRetrieval ? 'dl.libraryBuildHint' : 'dl.trainHint')}
      actions={mine && job.data ? <Badge tone={statusTone[job.data.status] ?? 'neutral'}>{t(`dl.status.${job.data.status}`, { defaultValue: job.data.status })}</Badge> : null}
      bodyClassName="space-y-3 p-4 text-sm" testId="dl-train-panel"
    >
      <div className="space-y-3">
        {/* 執行中：進度條（階段 + 百分比）與中止 */}
        {running ? (
          <div className="space-y-1.5 rounded-md border border-line bg-surface-muted px-3 py-2.5" data-testid="dl-progress">
            <div className="h-2 overflow-hidden rounded-full bg-line">
              <div className="h-full rounded-full bg-gradient-to-r from-brand to-info transition-[width] duration-300" style={{ width: `${percent}%` }} />
            </div>
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="min-w-0 truncate text-muted">{job.data?.stage}{mine ? '' : ` (${job.data?.project_name})`}</span>
              <span className="tnum shrink-0 font-medium text-content">{percent}%</span>
            </div>
            <div className="flex items-center gap-2 pt-0.5">
              <Button size="sm" onClick={() => void cancelTrain.mutateAsync()}><Square size={13} /> {t(isRetrieval ? 'dl.cancelBuild' : 'dl.cancel')}</Button>
              <span className="tnum text-xs text-subtle">{t('dl.elapsed', { s: Math.round(job.data?.duration_s ?? 0) })}</span>
            </div>
          </div>
        ) : null}

        {/* 最近一次結果 */}
        {mine && job.data?.status === 'failed' ? <p className="rounded-md bg-critical-soft px-2.5 py-1.5 text-xs text-critical">{job.data.error}</p> : null}
        {waiting ? (
          <div className="space-y-2 rounded-md border border-brand/40 bg-brand-soft px-2.5 py-2 text-xs" data-testid="dl-pending-model">
            <p className="text-content">{t(isRetrieval ? 'dl.libraryBuilt' : 'dl.trained')}</p>
            <TextInput label={t(isRetrieval ? 'dl.libraryAssetName' : 'dl.assetName')} value={saveName} placeholder={job.data?.asset_name} onChange={(e) => setSaveName(e.target.value)} data-testid="dl-save-name" />
            <div className="flex flex-wrap items-center gap-2">
              <Button size="xs" variant="primary" loading={saveModel.isPending} onClick={() => void keepModel()} data-testid="dl-save-model">{t('dl.saveModel')}</Button>
              <Button size="xs" loading={discardModel.isPending} onClick={() => void dropModel()} data-testid="dl-discard-model">{t('dl.discardModel')}</Button>
            </div>
          </div>
        ) : null}
        {mine && job.data?.status === 'done' && job.data?.saved ? (
          <div className="space-y-1.5 rounded-md bg-ok-soft px-2.5 py-1.5 text-xs text-ok">
            <p>{t('dl.done', { name: job.data.asset_name })} <Link to="/assets" className="underline">{t('dl.toAssets')}</Link>{' · '}{t('dl.useInTool', { tool: job.data.tool_key })}</p>
            <Button size="xs" variant="primary" loading={flowMut.create.isPending} onClick={() => void createFlowWithModel()} data-testid="dl-create-flow">{t('dl.createFlow')}</Button>
          </div>
        ) : null}
        {mine && job.data?.discarded ? <p className="rounded-md bg-surface-muted px-2.5 py-1.5 text-xs text-muted" data-testid="dl-discarded">{t('dl.discarded')}</p> : null}

        {/* 指標：大數字磚 */}
        {metrics && Object.keys(metrics).length ? (
          <div className="grid grid-cols-2 gap-1.5" data-testid="dl-metrics">
            {['leave_one_out_accuracy', 'library_size', 'classes', 'train_accuracy', 'val_accuracy', 'mAP50', 'mAP50-95', 'loss', 'samples'].filter((k) => metrics[k] !== undefined && metrics[k] !== null).slice(0, 4).map((k) => (
              <div key={k} className="rounded-md border border-line px-2.5 py-1.5">
                <p className="truncate text-[11px] text-muted">{t(`dl.metrics.${k}`, { defaultValue: k })}</p>
                <p className="tnum text-lg font-semibold leading-tight text-heading">
                  {typeof metrics[k] === 'number' && k !== 'samples' && (metrics[k] as number) <= 1 ? `${Math.round((metrics[k] as number) * 100)}%` : String(metrics[k])}
                </p>
              </div>
            ))}
          </div>
        ) : null}
        {mine && (job.data?.history?.length ?? 0) > 1 ? <TrainCurves history={job.data!.history} /> : null}
        {mine && job.data?.logs?.length ? <TrainLog logs={job.data.logs} /> : null}

        {/* 設定 */}
        {canQuickRegister ? (
          <div className="space-y-2 rounded-md border border-line bg-surface-muted px-3 py-2.5" data-testid="dl-quick-register">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 space-y-1">
                <p className="font-medium text-content">{t('dl.quickRegister')}</p>
                <p className="text-xs text-muted">{t('dl.quickRegisterHint')}</p>
              </div>
              <Button size="sm" variant="primary" loading={quickRegister.isPending} disabled={running || !project.classes.length || (project.counts?.total ?? 0) < 2} onClick={() => void runQuickRegister()} data-testid="dl-quick-register-start">
                <Wand2 size={14} /> {t('dl.quickRegister')}
              </Button>
            </div>
            <ol className="grid gap-1 text-xs text-muted sm:grid-cols-3">
              <li>{t('dl.quickStepUpload')}</li>
              <li>{t('dl.quickStepConfirm')}</li>
              <li>{t('dl.quickStepTrain')}</li>
            </ol>
            <p className="text-xs text-subtle">{t('dl.quickPreset')}</p>
            {quickResult ? (
              <div className="flex flex-wrap gap-1.5 text-[11px]" data-testid="dl-quick-params">
                {Object.entries(quickResult.params).map(([key, value]) => (
                  <span key={key} className="rounded border border-line bg-surface px-1.5 py-0.5 text-muted">{key}: {String(value)}</span>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        {mainParams.map(field)}
        <Select label={t('dl.device')} value={device || devices.data?.train_device || 'cpu'} onChange={(e) => setDevice(e.target.value)}
          hint={devices.data?.gpus?.length ? devices.data.gpus.map((g) => g.name).join(', ') : t('dl.noGpu')}
          options={(devices.data?.train_devices ?? ['cpu']).filter((d) => trainer.devices.includes(d) || d === 'cpu').map((d) => ({ value: d, label: d.toUpperCase() }))} />
        <TextInput label={t(isRetrieval ? 'dl.libraryAssetName' : 'dl.assetName')} placeholder={`${project.name}-${isRetrieval ? 'library' : 'model'}`} value={assetName} onChange={(e) => setAssetName(e.target.value)} />
        {Object.entries(groups).map(([name, list]) => (
          <details key={name} className="rounded-md border border-line px-2.5 py-1.5">
            <summary className="cursor-pointer select-none text-xs font-medium text-muted">{name} ({list.length})</summary>
            <div className="space-y-3 pt-2">{list.map(field)}</div>
          </details>
        ))}

        {!running ? (
          <Button variant="primary" className="w-full" loading={startTrain.isPending} onClick={() => void start()} data-testid="dl-train">
            <Play size={14} /> {t(isRetrieval ? 'dl.buildLibrary' : 'dl.start')}
          </Button>
        ) : null}
      </div>
      {dialog}
    </Panel>
  )
}

/** loss / 正確率 / mAP 曲線：key 從 history 動態取（分割任務的 fitness 可能 > 1，Y 軸不寫死）。 */
function TrainCurves({ history }: { history: Record<string, number>[] }) {
  const keys = useMemo(() => {
    const seen = new Set<string>()
    for (const point of history) for (const k of Object.keys(point)) if (k !== 'epoch') seen.add(k)
    const preferred = ['loss', 'train_accuracy', 'val_accuracy', 'mAP50', 'mAP50-95', 'precision', 'recall']
    const ordered = [...preferred.filter((k) => seen.has(k)), ...[...seen].filter((k) => !preferred.includes(k))]
    return ordered.slice(0, 4)
  }, [history])
  if (!keys.length) return null
  return (
    <div className="h-44 rounded-md border border-line p-1" data-testid="dl-curves">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={history} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
          <XAxis dataKey="epoch" tick={{ fontSize: 10 }} stroke="var(--color-muted, #94a3b8)" />
          <YAxis tick={{ fontSize: 10 }} stroke="var(--color-muted, #94a3b8)" domain={['auto', 'auto']} />
          <ChartTooltip contentStyle={{ fontSize: 11 }} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          {keys.map((k, i) => (
            <Line key={k} type="monotone" dataKey={k} stroke={CURVE_COLORS[i % CURVE_COLORS.length]} dot={false} strokeWidth={1.5} isAnimationActive={false} connectNulls />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/** 訓練 log（環形緩衝的最近 400 行；自動捲到底）。 */
function TrainLog({ logs }: { logs: string[] }) {
  const { t } = useTranslation()
  const ref = useRef<HTMLPreElement>(null)
  useEffect(() => {
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
  }, [logs.length])
  return (
    <div className="overflow-hidden rounded-md border border-line">
      <div className="flex items-center justify-between border-b border-line bg-surface-muted px-2.5 py-1 text-[11px] text-muted">
        <span>{t('dl.trainLog')}</span>
        <span className="tnum">{logs.length}</span>
      </div>
      <pre ref={ref} className="max-h-40 overflow-y-auto bg-[#0f172a] px-2.5 py-2 text-[11px] leading-relaxed text-slate-300" data-testid="dl-train-log">
        {logs.join('\n')}
      </pre>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 資料集面板：train/val/test 分割與版本凍結（zip 存資產庫可下載）
// ---------------------------------------------------------------------------
function DatasetPanel({ project, samples, isShapes }: { project: DlProject; samples: DlSample[]; isShapes: boolean }) {
  const { t } = useTranslation()
  const toast = useToast()
  const versions = useDlVersions(project.id)
  const { autoSplit, freezeVersion, removeVersion, datasetExport, datasetImport } = useDlMutations()
  const [val, setVal] = useState('15')
  const [test, setTest] = useState('10')
  const [verName, setVerName] = useState('')
  const [deletingVersion, setDeletingVersion] = useState<DlDatasetVersion | null>(null)
  //: 標記資料集互通（shapes 專案；伺服器本機路徑）：null = 關閉
  const [interop, setInterop] = useState<'export' | 'import' | null>(null)
  const [interopDir, setInteropDir] = useState('')
  const splitCounts = useMemo(() => {
    const c = { train: 0, val: 0, test: 0, unassigned: 0 }
    for (const s of samples) c[s.split || 'unassigned'] += 1
    return c
  }, [samples])

  async function runSplit() {
    try {
      const r = await autoSplit.mutateAsync({ projectId: project.id, val: (Number(val) || 0) / 100, test: (Number(test) || 0) / 100 })
      toast.success(t('dl.splitDone', r))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  async function runInterop() {
    const dir = interopDir.trim()
    if (!dir) return
    try {
      if (interop === 'export') {
        const r = await datasetExport.mutateAsync({ projectId: project.id, dir, val_ratio: (Number(val) || 0) / 100 })
        toast.success(t('dl.exported', r))
      } else {
        const r = await datasetImport.mutateAsync({ projectId: project.id, dir })
        toast.success(t('dl.importedLabels', r))
      }
      setInterop(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  async function freeze() {
    try {
      const r = await freezeVersion.mutateAsync({ projectId: project.id, name: verName.trim() || undefined })
      setVerName('')
      toast.success(t('dl.frozen', { name: r.name }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Panel
      title={<span className="flex items-center gap-2"><Database size={15} className="text-brand" />{t('dl.dataset')}</span>}
      description={t('dl.datasetHint')} defaultCollapsed bodyClassName="p-4" testId="dl-dataset-panel"
    >
      <div className="space-y-3 text-sm">
        {/* 分割統計（本地即時算，跟著標記與分割操作更新） */}
        <div className="grid grid-cols-4 gap-1.5 text-center" data-testid="dl-split-stats">
          {(['train', 'val', 'test', 'unassigned'] as const).map((k) => (
            <div key={k} className="rounded-md border border-line px-1 py-1.5">
              <p className="truncate text-[11px] text-muted">{t(`dl.split.${k}`)}</p>
              <p className="tnum text-base font-semibold leading-tight text-heading">{splitCounts[k]}</p>
            </div>
          ))}
        </div>
        <div className="flex items-end gap-2">
          <TextInput label={t('dl.valPercent')} type="number" min={0} max={50} value={val} onChange={(e) => setVal(e.target.value)} />
          <TextInput label={t('dl.testPercent')} type="number" min={0} max={50} value={test} onChange={(e) => setTest(e.target.value)} />
          <Button loading={autoSplit.isPending} disabled={!samples.length} title={t('dl.autoSplitHint')} onClick={() => void runSplit()} data-testid="dl-auto-split">
            <Shuffle size={14} /> {t('dl.autoSplit')}
          </Button>
        </div>
        {/* 版本清單與凍結 */}
        <div className="space-y-1.5 border-t border-line pt-2.5">
          <p className="text-xs font-medium text-muted">{t('dl.versions')}</p>
          {(versions.data ?? []).map((v) => (
            <div key={v.id} className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1.5 text-xs">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{v.name}</span>
                <span className="block truncate text-subtle">
                  {new Date(v.created_at).toLocaleString()} · {v.stats.total ?? 0} {t('dl.samplesUnit')}
                </span>
              </span>
              <a className="rounded p-1 text-muted hover:bg-surface-muted hover:text-content" href={assetUrl(v.asset_id)}
                download={`${project.name}-${v.name}.zip`} title={t('dl.download')} aria-label={t('dl.download')}>
                <Download size={13} />
              </a>
              <button type="button" className="rounded p-1 text-muted hover:bg-surface-muted hover:text-critical" title={t('dl.deleteVersion')}
                aria-label={t('dl.deleteVersion')} onClick={() => setDeletingVersion(v)}>
                <Trash2 size={13} />
              </button>
            </div>
          ))}
          {versions.data && !versions.data.length ? <p className="text-xs text-subtle">{t('dl.noVersions')}</p> : null}
          <div className="flex items-end gap-2">
            <TextInput label={t('dl.versionName')} placeholder={`v${(versions.data?.length ?? 0) + 1}`} value={verName} onChange={(e) => setVerName(e.target.value)} />
            <Button loading={freezeVersion.isPending} disabled={!samples.length} onClick={() => void freeze()} data-testid="dl-freeze">
              <Archive size={14} /> {t('dl.freeze')}
            </Button>
          </div>
        </div>
        {/* 標記 txt 互通（shapes 專案；VisionStereo 格式，伺服器本機路徑） */}
        {isShapes ? (
          <div className="space-y-1.5 border-t border-line pt-2.5">
            <p className="text-xs font-medium text-muted">{t('dl.interop')}</p>
            <div className="flex gap-2">
              <Button size="sm" disabled={!samples.length} onClick={() => setInterop('export')} data-testid="dl-labels-export"><Download size={13} /> {t('dl.exportLabels')}</Button>
              <Button size="sm" onClick={() => setInterop('import')} data-testid="dl-labels-import"><Upload size={13} /> {t('dl.importLabels')}</Button>
            </div>
            <p className="text-xs text-subtle">{t('dl.interopHint')}</p>
          </div>
        ) : null}
      </div>
      <Modal open={interop !== null} onClose={() => setInterop(null)} title={interop === 'export' ? t('dl.exportLabels') : t('dl.importLabels')} dirty={Boolean(interopDir)}
        footer={<><Button onClick={() => setInterop(null)}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={datasetExport.isPending || datasetImport.isPending} disabled={!interopDir.trim()} onClick={() => void runInterop()} data-testid="dl-interop-go">
            {interop === 'export' ? t('dl.exportLabels') : t('dl.importLabels')}
          </Button></>}>
        <div className="space-y-3">
          <TextInput label={t('dl.serverDir')} hint={t('dl.serverDirHint')} placeholder="D:\Datasets\part1" value={interopDir}
            onChange={(e) => setInteropDir(e.target.value)} autoFocus data-testid="dl-interop-dir" />
          <p className="text-xs text-subtle">{interop === 'export' ? t('dl.exportLabelsHint', { val }) : t('dl.importLabelsHint')}</p>
        </div>
      </Modal>
      <ConfirmDialog open={deletingVersion !== null} onClose={() => setDeletingVersion(null)} danger title={t('dl.deleteVersion')}
        message={t('dl.deleteVersionMessage', { name: deletingVersion?.name ?? '' })}
        onConfirm={() => {
          if (deletingVersion) void removeVersion.mutateAsync({ id: deletingVersion.id, projectId: project.id }).then(() => setDeletingVersion(null))
        }} />
    </Panel>
  )
}

/** 樣本篩選（網格與大圖檢視共用）：全部／未標記／自動標記待確認／指定類別。 */
function RetrievalLibraryPanel({ project }: { project: DlProject }) {
  const { t } = useTranslation()
  const toast = useToast()
  const fileInput = useRef<HTMLInputElement>(null)
  const library = useDlRetrievalLibrary(project.id, project.trainer_kind === 'retrieval')
  const { addRetrievalItems, removeRetrievalItem } = useDlMutations()
  const { confirm, dialog } = useConfirm()
  const [label, setLabel] = useState(project.classes[0] ?? '')
  const [newLabel, setNewLabel] = useState('')
  const selectedLabel = label === '__new__' ? newLabel.trim() : label
  const metrics = (library.data?.metrics ?? project.last_metrics ?? {}) as DlRetrievalLibrary['metrics']
  const accuracy = typeof metrics.leave_one_out_accuracy === 'number' ? Math.round(metrics.leave_one_out_accuracy * 100) : null

  useEffect(() => {
    if (!label && project.classes.length) setLabel(project.classes[0])
  }, [label, project.classes])

  async function add(list: FileList | null) {
    if (!list?.length || !selectedLabel) return
    try {
      const result = await addRetrievalItems.mutateAsync({ projectId: project.id, files: Array.from(list), label: selectedLabel })
      toast.success(t('dl.librarySaved', { count: result.created ?? 0 }))
      setNewLabel('')
      if (fileInput.current) fileInput.current.value = ''
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function remove(index: number) {
    if (!(await confirm(t('dl.removeReferenceConfirm'), { confirmLabel: t('common.delete') }))) return
    try {
      await removeRetrievalItem.mutateAsync({ projectId: project.id, index })
      toast.success(t('dl.libraryRemoved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Panel
      title={<span className="flex items-center gap-2"><Database size={15} className="text-brand" />{t('dl.referenceLibrary')}</span>}
      description={t('dl.referenceLibraryHint')}
      bodyClassName="space-y-3 p-4 text-sm"
      testId="dl-retrieval-library"
    >
      <div className="grid grid-cols-3 gap-1.5 text-center">
        <div className="rounded-md border border-line px-2 py-1.5">
          <p className="truncate text-[11px] text-muted">{t('dl.referencesUnit')}</p>
          <p className="tnum text-base font-semibold text-heading">{library.data?.total ?? 0}</p>
        </div>
        <div className="rounded-md border border-line px-2 py-1.5">
          <p className="truncate text-[11px] text-muted">{t('dl.classesUnit')}</p>
          <p className="tnum text-base font-semibold text-heading">{library.data?.classes.length ?? project.classes.length}</p>
        </div>
        <div className="rounded-md border border-line px-2 py-1.5">
          <p className="truncate text-[11px] text-muted">{t('dl.leaveOneOutAccuracy')}</p>
          <p className="tnum text-base font-semibold text-heading">{accuracy === null ? '—' : `${accuracy}%`}</p>
        </div>
      </div>

      {project.last_asset_id ? (
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-2">
          <Select
            label={t('dl.referenceLabel')}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            options={[...project.classes.map((c) => ({ value: c, label: c })), { value: '__new__', label: t('dl.newReferenceLabel') }]}
          />
          <Button loading={addRetrievalItems.isPending} disabled={!selectedLabel} onClick={() => fileInput.current?.click()}>
            <Upload size={14} /> {t('dl.addReference')}
          </Button>
          {label === '__new__' ? (
            <TextInput label={t('dl.newReferenceLabel')} value={newLabel} onChange={(e) => setNewLabel(e.target.value)} className="col-span-2" />
          ) : null}
          <input ref={fileInput} type="file" accept="image/*" multiple className="hidden" onChange={(e) => void add(e.currentTarget.files)} />
        </div>
      ) : (
        <EmptyState compact icon={<Database className="size-6" />} title={t('dl.noLibrary')} description={t('dl.noLibraryHint')} />
      )}

      {library.isLoading ? <LoadingState compact /> : null}
      {(library.data?.classes ?? []).map((group) => (
        <div key={group.label} className="space-y-2 border-t border-line pt-3">
          <div className="flex items-center justify-between gap-2">
            <span className="flex min-w-0 items-center gap-2">
              <span className="size-2 rounded-full" style={{ background: classColor(project.classes, group.label) }} />
              <span className="truncate font-medium text-heading">{group.label}</span>
            </span>
            <Badge>{group.count}</Badge>
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(76px,1fr))] gap-2">
            {group.items.map((item) => (
              <div key={item.id} className="group relative overflow-hidden rounded-md border border-line bg-surface-muted">
                {item.thumb ? <img src={item.thumb} alt="" className="aspect-square w-full object-cover" loading="lazy" /> : <div className="aspect-square w-full" />}
                <button
                  type="button"
                  className="absolute right-1 top-1 rounded bg-black/50 p-1 text-white opacity-0 transition-opacity hover:bg-critical group-hover:opacity-100"
                  title={t('dl.removeReference')}
                  aria-label={t('dl.removeReference')}
                  onClick={() => void remove(item.index)}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        </div>
      ))}
      {dialog}
    </Panel>
  )
}

function filterSamples(samples: DlSample[], filter: string): DlSample[] {
  return samples.filter((s) => {
    if (filter === '__all__') return true
    if (filter === '__unlabeled__') return !s.label
    if (filter === '__auto__') return s.labeled_by === 'auto'
    if (filter === '__train__' || filter === '__val__' || filter === '__test__') return s.split === filter.slice(2, -2)
    return s.label === filter
  })
}

// ---------------------------------------------------------------------------
// 匯入進度（分批上傳時顯示 done/total 與失敗數）
// ---------------------------------------------------------------------------
function ImportProgress({ state }: { state: { done: number; total: number; failed: number } | null }) {
  const { t } = useTranslation()
  if (!state) return null
  return (
    <div className="space-y-1" data-testid="dl-import-progress">
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-muted">
        <div className="h-full rounded-full bg-brand transition-[width]" style={{ width: `${Math.round((state.done / Math.max(1, state.total)) * 100)}%` }} />
      </div>
      <p className="text-xs text-muted">
        {t('dl.importing', { done: state.done, total: state.total })}
        {state.failed ? <span className="text-critical"> ({t('dl.importFailedCount', { failed: state.failed })})</span> : null}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 樣本網格
// ---------------------------------------------------------------------------
function SampleGrid({ project, samples, activeClass, filter, suggestions, onPick, onView, onDelete }: {
  project: DlProject
  samples: DlSample[]
  activeClass: string
  filter: string
  suggestions: Map<string, DlSuggestion>
  onPick: (sample: DlSample, alt: boolean) => void
  onView: (sample: DlSample) => void
  onDelete: (sample: DlSample) => void
}) {
  const { t } = useTranslation()
  const shown = filterSamples(samples, filter)
  if (!shown.length) {
    return <EmptyState compact icon={<Camera className="size-6" />} title={t('dl.noSamples')} description={t('dl.noSamplesHint')} />
  }
  return (
    <div className={`grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-2 ${activeClass ? 'cursor-crosshair' : ''}`} data-testid="dl-grid">
      {shown.map((s) => {
        const suggestion = !s.label ? suggestions.get(s.id) : undefined
        const color = s.label ? classColor(project.classes, s.label) : suggestion ? classColor(project.classes, suggestion.label) : 'transparent'
        return (
          <div key={s.id} className="group relative overflow-hidden rounded-md border border-line bg-surface-muted transition-shadow focus-within:ring-2 focus-within:ring-brand hover:ring-2 hover:ring-brand/50">
            <button type="button" onClick={(e) => onPick(s, e.altKey)} title={activeClass ? t('dl.clickToLabel', { label: activeClass }) : undefined}
              className="block w-full text-left focus:outline-none">
            <img src={dlSampleUrl(s.id, 256)} alt="" loading="lazy" className="aspect-square w-full object-cover" />
            {s.label ? (
              <span className={`absolute left-1 top-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-white ${s.labeled_by === 'auto' ? 'opacity-80' : ''}`} style={{ background: color }}>
                {s.label}{s.labeled_by === 'auto' ? ` ~${Math.round(s.score * 100)}%` : ''}
              </span>
            ) : suggestion ? (
              <span className="absolute left-1 top-1 rounded border border-dashed border-white/80 px-1.5 py-0.5 text-[11px] text-white" style={{ background: classColor(project.classes, suggestion.label, 0.8) }}>
                {suggestion.label}? {Math.round(suggestion.score * 100)}%
              </span>
            ) : (
              <span className="absolute left-1 top-1 rounded bg-black/45 px-1.5 py-0.5 text-[11px] text-white">{t('dl.unlabeled')}</span>
            )}
            {s.split ? <span className="absolute bottom-1 left-1 rounded bg-black/45 px-1 py-0.5 text-[10px] text-white">{t(`dl.split.${s.split}`)}</span> : null}
            </button>
            <span className="pointer-events-none absolute right-1 top-1 flex gap-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
              <button type="button" aria-label={t('dl.viewLarge')} title={t('dl.viewLarge')}
                className="pointer-events-none rounded bg-black/50 p-1 text-white focus-visible:pointer-events-auto group-hover:pointer-events-auto hover:!bg-brand"
                onClick={(e) => { e.stopPropagation(); onView(s) }}>
                <ImageIcon size={12} />
              </button>
              <button type="button" aria-label={t('common.delete')} title={t('common.delete')}
                className="pointer-events-none rounded bg-black/50 p-1 text-white focus-visible:pointer-events-auto group-hover:pointer-events-auto hover:!bg-critical"
                onClick={(e) => { e.stopPropagation(); onDelete(s) }}>
                <Trash2 size={12} />
              </button>
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 頁面
// ---------------------------------------------------------------------------
export function DlPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const trainers = useDlTrainers()
  const projects = useDlProjects()
  const devices = useDlDevices()
  const [selected, setSelected] = useState<number | null>(null)
  const projectId = selected ?? projects.data?.[0]?.id ?? null
  const project = useDlProject(projectId)
  const samples = useDlSamples(projectId)
  const { uploadSamples, setLabel, setShapes, setSplit, samPoint, removeSample, bulkLabels, autoLabel, removeProject, patchProject } = useDlMutations()

  const [creating, setCreating] = useState(false)
  const [fromSourceOpen, setFromSourceOpen] = useState(false)
  const [editingClasses, setEditingClasses] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [activeClass, setActiveClass] = useState('')
  const [filter, setFilter] = useState('__all__')
  const [suggestions, setSuggestions] = useState<Map<string, DlSuggestion>>(new Map())
  //: 匯入進度（分批上傳：done/total/failed；null = 沒有匯入在跑）
  const [importing, setImporting] = useState<{ done: number; total: number; failed: number } | null>(null)
  //: classes 模式的檢視方式：grid = 縮圖網格（快速標記）、viewer = 大圖檢視（看細節）
  const [classifyView, setClassifyView] = useState<'grid' | 'viewer'>('grid')
  const [viewingId, setViewingId] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const trainer = useMemo(() => trainers.data?.find((x) => x.kind === project.data?.trainer_kind), [trainers.data, project.data])
  const isShapes = trainer?.label_mode === 'shapes'
  const isRetrieval = trainer?.kind === 'retrieval'
  const accel = devices.data?.accelerators ?? []

  async function onFiles(list: FileList | null) {
    if (!list?.length || projectId === null) return
    if (importing) return // 匯入中不可重入（兩個迴圈會互相覆寫進度）
    // 分批上傳（每批 4 張）：邊傳邊顯示進度與狀態，縮圖牆也會即時長出來。
    const files = Array.from(list)
    const batch = 4
    let done = 0
    let added = 0
    let failed = 0
    let dups = 0
    setImporting({ done: 0, total: files.length, failed: 0 })
    try {
      for (let i = 0; i < files.length; i += batch) {
        const chunk = files.slice(i, i + batch)
        try {
          const r = await uploadSamples.mutateAsync({ projectId, files: chunk, label: isShapes ? '' : activeClass })
          added += r.items.length
          failed += r.skipped // zip 一個檔可能展開多張，改用後端回報的失敗數
          dups += r.duplicates
        } catch {
          failed += chunk.length
        }
        done += chunk.length
        setImporting({ done, total: files.length, failed })
      }
      if (failed) toast.warning(t('dl.importedWithFail', { count: added, failed }))
      else if (dups) toast.success(t('dl.uploadedDup', { count: added, dup: dups }))
      else toast.success(t('dl.uploaded', { count: added }))
    } finally {
      setImporting(null)
    }
  }

  async function saveClasses(list: string[]) {
    if (projectId === null) return
    try {
      await patchProject.mutateAsync({ id: projectId, classes: list })
      if (activeClass && !list.includes(activeClass)) setActiveClass('')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      throw e // Modal 據此保持開啟
    }
  }

  async function pick(sample: DlSample, alt: boolean) {
    if (projectId === null) return
    if (alt) {
      await removeSample.mutateAsync({ id: sample.id, projectId })
      return
    }
    const next = sample.label === activeClass ? '' : activeClass
    if (!activeClass && !sample.label) return
    await setLabel.mutateAsync({ id: sample.id, label: next, projectId })
  }

  async function runAutoLabel(method: 'model' | 'sam' = 'model') {
    if (projectId === null) return
    try {
      const r = await autoLabel.mutateAsync({ projectId, method, maxSamples: method === 'sam' ? 20 : undefined })
      setSuggestions(new Map(r.items.map((s) => [s.id, s])))
      if (!r.items.length) toast.push(t('dl.noSuggestions'), 'info')
      else if (r.remaining) toast.push(t('dl.samRemaining', { count: r.remaining }), 'info')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  async function acceptSuggestions() {
    if (projectId === null || !suggestions.size) return
    const items = Array.from(suggestions.values()).map((s) =>
      s.shapes ? { id: s.id, shapes: s.shapes, score: s.score, by: 'auto' } : { id: s.id, label: s.label, score: s.score, by: 'auto' })
    await bulkLabels.mutateAsync({ projectId, items })
    setSuggestions(new Map())
    toast.success(t('dl.accepted', { count: items.length }))
  }

  async function saveShapes(sampleId: string, shapes: DlShape[]) {
    if (projectId === null) return
    await setShapes.mutateAsync({ id: sampleId, shapes, projectId })
  }

  async function acceptOneSuggestion(sampleId: string, shapes: DlShape[]) {
    if (projectId === null) return
    await bulkLabels.mutateAsync({ projectId, items: [{ id: sampleId, shapes, by: 'auto', score: suggestions.get(sampleId)?.score }] })
    setSuggestions((old) => {
      const next = new Map(old)
      next.delete(sampleId)
      return next
    })
  }

  // classes 模式：數字鍵 0~9 切換目前類別（Modal 開啟或輸入中不觸發）
  useEffect(() => {
    if (isShapes || !project.data || classifyView === 'viewer') return
    const classes = project.data.classes
    function onDigit(e: KeyboardEvent) {
      if (editingClasses || creating || fromSourceOpen || deleting) return
      const el = document.activeElement
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || (el as HTMLElement).isContentEditable)) return
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (!/^[0-9]$/.test(e.key)) return
      const label = classes[Number(e.key)]
      if (!label) return
      setActiveClass((old) => (old === label ? '' : label))
      e.preventDefault()
    }
    window.addEventListener('keydown', onDigit, true)
    return () => window.removeEventListener('keydown', onDigit, true)
  }, [isShapes, project.data, classifyView, editingClasses, creating, fromSourceOpen, deleting])

  const counts = project.data?.counts
  return (
    <Page wide>
      <PageHeader
        title={t('dl.title')}
        description={t('dl.subtitle')}
        actions={
          // 提示文字用後端給的中性名稱；原始 provider 值只當設定值與除錯資料，不進產品表面。
          <span className="flex items-center gap-2 text-xs text-muted" title={(devices.data?.accelerators ?? []).join('\n')}>
            <Cpu size={14} />
            {devices.data ? (accel.length ? t('dl.accelOn', { list: accel.map((p) => p.replace('ExecutionProvider', '')).join(', ') }) : t('dl.cpuOnly')) : '…'}
            {devices.data?.gpus?.length ? <Badge tone="ok">{devices.data.gpus[0].name}</Badge> : null}
          </span>
        }
      />
      {/* lg 只給兩欄（1024~1280 時三欄會把畫布擠到很窄），xl 才把訓練面板收進第三欄 */}
      <div className="grid gap-4 lg:grid-cols-[200px_minmax(0,1fr)] xl:grid-cols-[200px_minmax(0,1fr)_330px]">
        {/* 專案清單 */}
        <Panel title={t('dl.projects')} actions={<Button size="sm" onClick={() => setCreating(true)} data-testid="dl-new"><Plus size={14} /> {t('common.create')}</Button>} bodyClassName="p-1.5">
            {projects.isLoading ? <LoadingState compact /> : null}
            {(projects.data ?? []).map((p) => (
              <button key={p.id} type="button" onClick={() => { setSelected(p.id); setSuggestions(new Map()); setActiveClass(''); setFilter('__all__') }}
                className={`flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm ${p.id === projectId ? 'bg-brand-soft text-brand' : 'hover:bg-surface-muted'}`}>
                <Brain size={15} className="shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{p.name}</span>
                  <span className="block truncate text-xs text-muted">{p.counts?.total ?? 0} {t('dl.samplesUnit')}</span>
                </span>
              </button>
            ))}
            {projects.data && !projects.data.length ? <EmptyState compact title={t('dl.noProjects')} description={t('dl.noProjectsHint')} /> : null}
        </Panel>

        {/* 標記工作區 */}
        <div className="min-w-0 space-y-3">
          {project.data && isShapes ? (
            <>
              <Card>
                <CardBody className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <input ref={fileInput} type="file" accept="image/*,.zip" multiple hidden onChange={(e) => { void onFiles(e.target.files); e.target.value = '' }} />
                    <Button size="sm" disabled={!!importing} onClick={() => fileInput.current?.click()}><Upload size={14} /> {t('dl.upload')}</Button>
                    <Button size="sm" disabled={!!importing} onClick={() => setFromSourceOpen(true)}><Camera size={14} /> {t('dl.fromSource')}</Button>
                    <Button size="sm" variant="primary" loading={autoLabel.isPending} onClick={() => void runAutoLabel()} data-testid="dl-auto"><Sparkles size={14} /> {t('dl.autoLabel')}</Button>
                    <Button size="sm" loading={autoLabel.isPending} title={t('dl.autoLabelSamHint')} onClick={() => void runAutoLabel('sam')} data-testid="dl-auto-sam"><Wand2 size={14} /> {t('dl.autoLabelSam')}</Button>
                    {suggestions.size ? (
                      <>
                        <Button size="sm" variant="primary" onClick={() => void acceptSuggestions()}><Check size={14} /> {t('dl.acceptAll', { count: suggestions.size })}</Button>
                        <Button size="sm" onClick={() => setSuggestions(new Map())}><X size={14} /> {t('dl.clearSuggestions')}</Button>
                      </>
                    ) : null}
                    <Button size="sm" onClick={() => setEditingClasses(true)} data-testid="dl-edit-classes">{t('dl.editClasses')}</Button>
                    <span className="ml-auto text-xs text-muted">{t('dl.progressCount', { labeled: (counts?.total ?? 0) - (counts?.unlabeled ?? 0), total: counts?.total ?? 0 })}</span>
                    <Button size="sm" variant="ghost" title={t('dl.deleteProject')} onClick={() => setDeleting(true)}><Trash2 size={14} /></Button>
                  </div>
                  <ImportProgress state={importing} />
                </CardBody>
              </Card>
              {!project.data.classes.length ? (
                <p className="rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">{t('dl.classesFirst')}</p>
              ) : null}
              {samples.isLoading ? <LoadingState /> : (samples.data ?? []).length ? (
                <ShapeWorkspace key={project.data.id} project={project.data} samples={samples.data ?? []} suggestions={suggestions}
                  onSave={saveShapes} onAcceptSuggestion={acceptOneSuggestion} onEditClasses={() => setEditingClasses(true)}
                  onSamPoint={projectId === null ? undefined : async (sampleId, point) => (await samPoint.mutateAsync({ projectId, sampleId, points: [point] })).shapes}
                  onSamBox={projectId === null ? undefined : async (sampleId, box) => (await samPoint.mutateAsync({ projectId, sampleId, boxes: [box] })).shapes}
                  onSetSplit={(s, split) => { if (projectId !== null) void setSplit.mutateAsync({ id: s.id, split, projectId }) }}
                  hotkeysDisabled={editingClasses || creating || fromSourceOpen || deleting} />
              ) : (
                <EmptyState compact icon={<Camera className="size-6" />} title={t('dl.noSamples')} description={t('dl.noSamplesHint')} />
              )}
            </>
          ) : project.data ? (
            <>
              <Card>
                <CardBody className="space-y-2.5">
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-1.5">
                    {project.data.classes.map((c, i) => {
                      const active = activeClass === c
                      const color = classColor(project.data!.classes, c)
                      return (
                        <button key={c} type="button" onClick={() => setActiveClass(active ? '' : c)} title={t('dl.classButtonTitle', { n: i })}
                          className={`flex h-11 items-center gap-2 rounded-md border px-3 text-sm font-medium transition-colors ${active ? 'border-transparent text-white shadow-sm' : 'border-line text-content hover:bg-surface-muted'}`}
                          style={active ? { background: color } : undefined} data-testid={`dl-class-${c}`}>
                          <span className="size-3 shrink-0 rounded-full border border-black/10" style={{ background: active ? '#fff' : color }} />
                          <span className="min-w-0 truncate">{c}</span>
                          {i <= 9 ? <kbd className={`rounded border px-1 text-[10px] leading-4 ${active ? 'border-white/40 text-white/85' : 'border-line text-subtle'}`}>{i}</kbd> : null}
                          <span className={`ml-auto tnum text-xs ${active ? 'opacity-80' : 'text-muted'}`}>{counts?.per_class[c] ?? 0}</span>
                        </button>
                      )
                    })}
                    <button type="button" className="flex h-11 items-center justify-center gap-1.5 rounded-md border border-dashed border-line px-3 text-sm text-muted hover:bg-surface-muted"
                      onClick={() => setEditingClasses(true)} data-testid="dl-edit-classes">
                      {t('dl.editClasses')}
                    </button>
                  </div>
                  <p className="text-right text-xs text-muted">{t('dl.progressCount', { labeled: (counts?.total ?? 0) - (counts?.unlabeled ?? 0), total: counts?.total ?? 0 })}</p>
                  <p className="text-xs text-subtle">{activeClass ? t('dl.labelingHint', { label: activeClass }) : t('dl.pickClassHint')}</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <input ref={fileInput} type="file" accept="image/*,.zip" multiple hidden onChange={(e) => { void onFiles(e.target.files); e.target.value = '' }} />
                    <Button size="sm" disabled={!!importing} onClick={() => fileInput.current?.click()}><Upload size={14} /> {t('dl.upload')}</Button>
                    <Button size="sm" disabled={!!importing} onClick={() => setFromSourceOpen(true)}><Camera size={14} /> {t('dl.fromSource')}</Button>
                    <Button size="sm" variant="primary" loading={autoLabel.isPending} onClick={() => void runAutoLabel()} data-testid="dl-auto"><Sparkles size={14} /> {t('dl.autoLabel')}</Button>
                    {suggestions.size ? (
                      <>
                        <Button size="sm" variant="primary" onClick={() => void acceptSuggestions()}><Check size={14} /> {t('dl.acceptAll', { count: suggestions.size })}</Button>
                        <Button size="sm" onClick={() => setSuggestions(new Map())}><X size={14} /> {t('dl.clearSuggestions')}</Button>
                      </>
                    ) : null}
                    <span className="ml-auto" />
                    <SegmentedControl size="sm" value={classifyView} onChange={setClassifyView}
                      options={[
                        { value: 'grid', label: <span className="flex items-center gap-1"><LayoutGrid size={13} />{t('dl.viewGrid')}</span>, title: t('dl.viewGrid') },
                        { value: 'viewer', label: <span className="flex items-center gap-1"><ImageIcon size={13} />{t('dl.viewLarge')}</span>, title: t('dl.viewLarge') },
                      ]} />
                    <Select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={t('dl.filterLabel')} className="!h-8 !text-xs"
                      options={[
                        { value: '__all__', label: t('dl.filterAll') },
                        { value: '__unlabeled__', label: `${t('dl.unlabeled')} (${counts?.unlabeled ?? 0})` },
                        { value: '__auto__', label: t('dl.filterAuto') },
                        ...(isRetrieval ? [] : [
                          { value: '__train__', label: `${t('dl.split.train')} (train)` },
                          { value: '__val__', label: `${t('dl.split.val')} (val)` },
                          { value: '__test__', label: `${t('dl.split.test')} (test)` },
                        ]),
                        ...project.data.classes.map((c) => ({ value: c, label: c })),
                      ]} />
                    <Button size="sm" variant="ghost" title={t('dl.deleteProject')} onClick={() => setDeleting(true)}><Trash2 size={14} /></Button>
                  </div>
                  <ImportProgress state={importing} />
                </CardBody>
              </Card>
              {!project.data.classes.length ? (
                <p className="rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">{t('dl.classesFirst')}</p>
              ) : null}
              {samples.isLoading ? <LoadingState /> : classifyView === 'viewer' && filterSamples(samples.data ?? [], filter).length ? (
                <ClassifyWorkspace project={project.data} samples={filterSamples(samples.data ?? [], filter)} suggestions={suggestions}
                  selectedId={viewingId} onSelect={setViewingId}
                  onLabel={(s, label) => { if (projectId !== null) void setLabel.mutateAsync({ id: s.id, label, projectId }) }}
                  onSetSplit={(s, split) => { if (projectId !== null) void setSplit.mutateAsync({ id: s.id, split, projectId }) }}
                  onDelete={(s) => { if (projectId !== null) void removeSample.mutateAsync({ id: s.id, projectId }) }}
                  hotkeysDisabled={editingClasses || creating || fromSourceOpen || deleting} />
              ) : (
                <SampleGrid project={project.data} samples={samples.data ?? []} activeClass={activeClass} filter={filter} suggestions={suggestions}
                  onPick={(s, alt) => void pick(s, alt)}
                  onView={(s) => { setViewingId(s.id); setClassifyView('viewer') }}
                  onDelete={(s) => { if (projectId !== null) void removeSample.mutateAsync({ id: s.id, projectId }) }} />
              )}
            </>
          ) : projects.isLoading || project.isLoading ? <LoadingState /> : (
            <EmptyState icon={<Brain className="size-7" />} title={t('dl.noProjects')} description={t('dl.noProjectsHint')}
              action={<Button variant="primary" onClick={() => setCreating(true)}><Plus size={14} /> {t('dl.newProject')}</Button>} />
          )}
        </div>

        {/* 訓練面板 */}
        <div className="space-y-3">
          {project.data && trainer ? <TrainPanel key={project.data.id} project={project.data} trainer={trainer} /> : null}
          {project.data && isRetrieval ? <RetrievalLibraryPanel key={`lib-${project.data.id}`} project={project.data} /> : null}
          {project.data && !isRetrieval ? <DatasetPanel key={`ds-${project.data.id}`} project={project.data} samples={samples.data ?? []} isShapes={!!isShapes} /> : null}
        </div>
      </div>

      <CreateProjectModal open={creating} onClose={() => setCreating(false)} trainers={trainers.data ?? []} onCreated={(p) => { setSelected(p.id); setEditingClasses(true) }} />
      {project.data ? <ClassesModal open={editingClasses} onClose={() => setEditingClasses(false)} classes={project.data.classes} onSave={saveClasses} saving={patchProject.isPending} /> : null}
      {project.data ? <FromSourceModal open={fromSourceOpen} onClose={() => setFromSourceOpen(false)} project={project.data} showLabel={!isShapes} /> : null}
      <ConfirmDialog open={deleting} onClose={() => setDeleting(false)} danger title={t('dl.deleteProject')}
        message={t('dl.deleteMessage', { name: project.data?.name ?? '' })}
        onConfirm={() => {
          if (projectId !== null) void removeProject.mutateAsync(projectId).then(() => { setDeleting(false); setSelected(null) })
        }} />
    </Page>
  )
}
