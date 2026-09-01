/**
 * 深度學習頁（DlPage）`/dl`：平台內教導——建立教導專案、收集與標記樣本、
 * 自動標記（kNN 建議＋批次接受）、伺服端訓練（裝置選擇、進度、指標）、匯出模型到資產庫。
 * UI 由 /dl/trainers 的目錄資料驅動（超參數表單直接用 ParamField），之後導入新模型種類不用改前端。
 */
import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Brain, Camera, Check, Cpu, Play, Plus, Sparkles, Square, Trash2, Upload, X } from 'lucide-react'

import { ParamField, type InspectorActions } from '@/components/editor/ParamField'
import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, CardBody, CardHeader, ConfirmDialog, EmptyState, LoadingState, Modal, PageHeader, Select, TextInput } from '@/components/ui'
import { dlSampleUrl } from '@/lib/api'
import { useDlDevices, useDlMutations, useDlProject, useDlProjects, useDlSamples, useDlTrainStatus, useDlTrainers, useSources } from '@/lib/queries'
import type { DlProject, DlSample, DlSuggestion, DlTrainerDef } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

const NO_ACTIONS: InspectorActions = { roiEditingKey: null, setRoiEditing: () => {}, templateFromImage: () => {}, templateKey: null, hasImage: false }
const CLASS_COLORS = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#65a30d']

function classColor(classes: string[], label: string): string {
  const index = classes.indexOf(label)
  return index >= 0 ? CLASS_COLORS[index % CLASS_COLORS.length] : '#94a3b8'
}

// ---------------------------------------------------------------------------
// 建立專案
// ---------------------------------------------------------------------------
function CreateProjectModal({ open, onClose, trainers, onCreated }: { open: boolean; onClose: () => void; trainers: DlTrainerDef[]; onCreated: (p: DlProject) => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { createProject } = useDlMutations()
  const [name, setName] = useState('')
  const [kind, setKind] = useState(trainers[0]?.kind ?? '')
  const [classText, setClassText] = useState('OK, NG')
  const trainer = trainers.find((x) => x.kind === (kind || trainers[0]?.kind))

  async function submit() {
    const classes = classText.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean)
    try {
      const project = await createProject.mutateAsync({ name: name.trim(), trainer_kind: trainer?.kind ?? '', classes })
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
        <TextInput label={t('dl.classesInput')} hint={t('dl.classesHint')} value={classText} onChange={(e) => setClassText(e.target.value)} />
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// 從影像來源收集樣本
// ---------------------------------------------------------------------------
function FromSourceModal({ open, onClose, project }: { open: boolean; onClose: () => void; project: DlProject }) {
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
      toast.success(t('dl.grabbed', { count: r.items.length }))
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
          options={(sources.data?.items ?? []).map((s) => ({ value: String(s.id), label: `${s.name}（${s.kind}）` }))} />
        <TextInput label={t('dl.grabCount')} type="number" min={1} max={50} value={count} onChange={(e) => setCount(e.target.value)} />
        <Select label={t('dl.presetLabel')} value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t('dl.unlabeled')}
          options={project.classes.map((c) => ({ value: c, label: c }))} />
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
  const { startTrain, cancelTrain } = useDlMutations()
  const [params, setParams] = useState<Record<string, unknown>>(() => ({ ...project.params }))
  const [assetName, setAssetName] = useState('')
  const [device, setDevice] = useState('')
  const job = useDlTrainStatus(true)
  const running = job.data?.status === 'running'
  const mine = job.data && job.data.project_id === project.id

  async function start() {
    try {
      await startTrain.mutateAsync({ projectId: project.id, params, device: device || devices.data?.train_device || 'cpu', asset_name: assetName })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const metrics = (mine ? job.data?.metrics : project.last_metrics) as Record<string, unknown> | undefined
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Cpu size={15} className="text-brand" />{t('dl.train')}</span>} description={t('dl.trainHint')} />
      <CardBody className="space-y-3 text-sm">
        {trainer.params.map((p) => (
          <ParamField key={p.key} param={p} value={params[p.key] ?? p.default} onChange={(v) => setParams((old) => ({ ...old, [p.key]: v }))} actions={NO_ACTIONS} />
        ))}
        <Select label={t('dl.device')} value={device || devices.data?.train_device || 'cpu'} onChange={(e) => setDevice(e.target.value)}
          hint={devices.data?.gpus.length ? devices.data.gpus.map((g) => g.name).join('、') : t('dl.noGpu')}
          options={(devices.data?.train_devices ?? ['cpu']).filter((d) => trainer.devices.includes(d) || d === 'cpu').map((d) => ({ value: d, label: d.toUpperCase() }))} />
        <TextInput label={t('dl.assetName')} placeholder={`${project.name}-model`} value={assetName} onChange={(e) => setAssetName(e.target.value)} />
        {running ? (
          <div className="space-y-2">
            <div className="h-2 overflow-hidden rounded-full bg-surface-muted">
              <div className="h-full rounded-full bg-brand transition-[width]" style={{ width: `${Math.round((job.data?.progress ?? 0) * 100)}%` }} />
            </div>
            <p className="text-xs text-muted">{job.data?.stage}（{job.data?.project_name}）</p>
            <Button size="sm" onClick={() => void cancelTrain.mutateAsync()}><Square size={13} /> {t('dl.cancel')}</Button>
          </div>
        ) : (
          <Button variant="primary" loading={startTrain.isPending} onClick={() => void start()} data-testid="dl-train">
            <Play size={14} /> {t('dl.start')}
          </Button>
        )}
        {mine && job.data?.status === 'failed' ? <p className="rounded-md bg-critical-soft px-2.5 py-1.5 text-xs text-critical">{job.data.error}</p> : null}
        {mine && job.data?.status === 'done' ? (
          <p className="rounded-md bg-ok-soft px-2.5 py-1.5 text-xs text-ok">
            {t('dl.done', { name: job.data.asset_name })} <Link to="/assets" className="underline">{t('dl.toAssets')}</Link>
            {' · '}{t('dl.useInTool', { tool: job.data.tool_key })}
          </p>
        ) : null}
        {metrics && Object.keys(metrics).length ? (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 rounded-md border border-line px-3 py-2 text-xs">
            {['train_accuracy', 'val_accuracy', 'loss', 'samples'].filter((k) => metrics[k] !== undefined && metrics[k] !== null).map((k) => (
              <span key={k} className="contents"><dt className="text-muted">{t(`dl.metrics.${k}`)}</dt><dd className="tnum text-right">{String(metrics[k])}</dd></span>
            ))}
          </dl>
        ) : null}
      </CardBody>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// 樣本網格
// ---------------------------------------------------------------------------
function SampleGrid({ project, samples, activeClass, filter, suggestions, onPick }: {
  project: DlProject
  samples: DlSample[]
  activeClass: string
  filter: string
  suggestions: Map<string, DlSuggestion>
  onPick: (sample: DlSample, alt: boolean) => void
}) {
  const { t } = useTranslation()
  const shown = samples.filter((s) => {
    if (filter === '__all__') return true
    if (filter === '__unlabeled__') return !s.label
    if (filter === '__auto__') return s.labeled_by === 'auto'
    return s.label === filter
  })
  if (!shown.length) {
    return <EmptyState compact icon={<Camera className="size-6" />} title={t('dl.noSamples')} description={t('dl.noSamplesHint')} />
  }
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-2" data-testid="dl-grid">
      {shown.map((s) => {
        const suggestion = !s.label ? suggestions.get(s.id) : undefined
        const color = s.label ? classColor(project.classes, s.label) : suggestion ? classColor(project.classes, suggestion.label) : 'transparent'
        return (
          <button key={s.id} type="button" onClick={(e) => onPick(s, e.altKey)} title={activeClass ? t('dl.clickToLabel', { label: activeClass }) : undefined}
            className="group relative overflow-hidden rounded-md border border-line bg-surface-muted text-left focus:outline-none focus:ring-2 focus:ring-brand">
            <img src={dlSampleUrl(s.id, 256)} alt="" loading="lazy" className="aspect-square w-full object-cover" />
            {s.label ? (
              <span className={`absolute left-1 top-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-white ${s.labeled_by === 'auto' ? 'opacity-80' : ''}`} style={{ background: color }}>
                {s.label}{s.labeled_by === 'auto' ? ` ~${Math.round(s.score * 100)}%` : ''}
              </span>
            ) : suggestion ? (
              <span className="absolute left-1 top-1 rounded border border-dashed border-white/80 px-1.5 py-0.5 text-[11px] text-white" style={{ background: `${color}cc` }}>
                {suggestion.label}? {Math.round(suggestion.score * 100)}%
              </span>
            ) : (
              <span className="absolute left-1 top-1 rounded bg-black/45 px-1.5 py-0.5 text-[11px] text-white">{t('dl.unlabeled')}</span>
            )}
          </button>
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
  const { uploadSamples, setLabel, removeSample, bulkLabels, autoLabel, removeProject, patchProject } = useDlMutations()

  const [creating, setCreating] = useState(false)
  const [fromSourceOpen, setFromSourceOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [activeClass, setActiveClass] = useState('')
  const [filter, setFilter] = useState('__all__')
  const [suggestions, setSuggestions] = useState<Map<string, DlSuggestion>>(new Map())
  const fileInput = useRef<HTMLInputElement>(null)

  const trainer = useMemo(() => trainers.data?.find((x) => x.kind === project.data?.trainer_kind), [trainers.data, project.data])
  const accel = devices.data?.accelerators ?? []

  async function onFiles(list: FileList | null) {
    if (!list?.length || projectId === null) return
    try {
      const r = await uploadSamples.mutateAsync({ projectId, files: Array.from(list), label: activeClass })
      toast.success(t('dl.uploaded', { count: r.items.length }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
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

  async function runAutoLabel() {
    if (projectId === null) return
    try {
      const r = await autoLabel.mutateAsync({ projectId })
      setSuggestions(new Map(r.items.map((s) => [s.id, s])))
      if (!r.items.length) toast.push(t('dl.noSuggestions'), 'info')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  async function acceptSuggestions() {
    if (projectId === null || !suggestions.size) return
    const items = Array.from(suggestions.values()).map((s) => ({ id: s.id, label: s.label, score: s.score, by: 'auto' }))
    await bulkLabels.mutateAsync({ projectId, items })
    setSuggestions(new Map())
    toast.success(t('dl.accepted', { count: items.length }))
  }

  const counts = project.data?.counts
  return (
    <Page wide>
      <PageHeader
        title={t('dl.title')}
        description={t('dl.subtitle')}
        actions={
          <span className="flex items-center gap-2 text-xs text-muted" title={(devices.data?.providers ?? []).join('\n')}>
            <Cpu size={14} />
            {devices.data ? (accel.length ? t('dl.accelOn', { list: accel.map((p) => p.replace('ExecutionProvider', '')).join('、') }) : t('dl.cpuOnly')) : '…'}
            {devices.data?.gpus.length ? <Badge tone="ok">{devices.data.gpus[0].name}</Badge> : null}
          </span>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_300px]">
        {/* 專案清單 */}
        <Card>
          <CardHeader title={t('dl.projects')} actions={<Button size="sm" onClick={() => setCreating(true)} data-testid="dl-new"><Plus size={14} /> {t('common.create')}</Button>} />
          <CardBody className="p-1.5">
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
          </CardBody>
        </Card>

        {/* 標記工作區 */}
        <div className="min-w-0 space-y-3">
          {project.data ? (
            <>
              <Card>
                <CardBody className="space-y-2.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {project.data.classes.map((c) => {
                      const active = activeClass === c
                      const color = classColor(project.data!.classes, c)
                      return (
                        <button key={c} type="button" onClick={() => setActiveClass(active ? '' : c)}
                          className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${active ? 'border-transparent text-white' : 'border-line text-content hover:bg-surface-muted'}`}
                          style={active ? { background: color } : undefined} data-testid={`dl-class-${c}`}>
                          <span className="size-2 rounded-full" style={{ background: active ? '#fff' : color }} />
                          {c}
                          <span className={active ? 'opacity-80' : 'text-muted'}>{counts?.per_class[c] ?? 0}</span>
                        </button>
                      )
                    })}
                    <button type="button" className="rounded-full border border-dashed border-line px-2.5 py-1 text-xs text-muted hover:bg-surface-muted"
                      onClick={() => {
                        const value = window.prompt(t('dl.classesPrompt'), project.data!.classes.join(', '))
                        if (value !== null && projectId !== null) void patchProject.mutateAsync({ id: projectId, classes: value.split(/[,，]/).map((s) => s.trim()).filter(Boolean) })
                      }}>
                      {t('dl.editClasses')}
                    </button>
                    <span className="ml-auto text-xs text-muted">{t('dl.progressCount', { labeled: (counts?.total ?? 0) - (counts?.unlabeled ?? 0), total: counts?.total ?? 0 })}</span>
                  </div>
                  <p className="text-xs text-subtle">{activeClass ? t('dl.labelingHint', { label: activeClass }) : t('dl.pickClassHint')}</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <input ref={fileInput} type="file" accept="image/*" multiple hidden onChange={(e) => { void onFiles(e.target.files); e.target.value = '' }} />
                    <Button size="sm" onClick={() => fileInput.current?.click()}><Upload size={14} /> {t('dl.upload')}</Button>
                    <Button size="sm" onClick={() => setFromSourceOpen(true)}><Camera size={14} /> {t('dl.fromSource')}</Button>
                    <Button size="sm" variant="primary" loading={autoLabel.isPending} onClick={() => void runAutoLabel()} data-testid="dl-auto"><Sparkles size={14} /> {t('dl.autoLabel')}</Button>
                    {suggestions.size ? (
                      <>
                        <Button size="sm" variant="primary" onClick={() => void acceptSuggestions()}><Check size={14} /> {t('dl.acceptAll', { count: suggestions.size })}</Button>
                        <Button size="sm" onClick={() => setSuggestions(new Map())}><X size={14} /> {t('dl.clearSuggestions')}</Button>
                      </>
                    ) : null}
                    <span className="ml-auto" />
                    <Select value={filter} onChange={(e) => setFilter(e.target.value)} className="!h-8 !text-xs"
                      options={[
                        { value: '__all__', label: t('dl.filterAll') },
                        { value: '__unlabeled__', label: `${t('dl.unlabeled')}（${counts?.unlabeled ?? 0}）` },
                        { value: '__auto__', label: t('dl.filterAuto') },
                        ...project.data.classes.map((c) => ({ value: c, label: c })),
                      ]} />
                    <Button size="sm" variant="ghost" title={t('dl.deleteProject')} onClick={() => setDeleting(true)}><Trash2 size={14} /></Button>
                  </div>
                </CardBody>
              </Card>
              {samples.isLoading ? <LoadingState /> : (
                <SampleGrid project={project.data} samples={samples.data ?? []} activeClass={activeClass} filter={filter} suggestions={suggestions} onPick={(s, alt) => void pick(s, alt)} />
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
        </div>
      </div>

      <CreateProjectModal open={creating} onClose={() => setCreating(false)} trainers={trainers.data ?? []} onCreated={(p) => setSelected(p.id)} />
      {project.data ? <FromSourceModal open={fromSourceOpen} onClose={() => setFromSourceOpen(false)} project={project.data} /> : null}
      <ConfirmDialog open={deleting} onClose={() => setDeleting(false)} danger title={t('dl.deleteProject')}
        message={t('dl.deleteMessage', { name: project.data?.name ?? '' })}
        onConfirm={() => {
          if (projectId !== null) void removeProject.mutateAsync(projectId).then(() => { setDeleting(false); setSelected(null) })
        }} />
    </Page>
  )
}
