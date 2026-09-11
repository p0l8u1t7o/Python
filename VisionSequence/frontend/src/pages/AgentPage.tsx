/**
 * AI 助手（/agent）：上傳多張影像 → 在各張影像上圈 ROI（ROI01、ROI02…各配提示；提示詞可引用，
 * 例「ROI01 是好品、ROI02 是壞品」）→ 描述檢測需求 → 生成流程並在每張影像實跑（overlay 疊圖、
 * 縮圖列標 OK/NG）→ 口語回饋微調 → 存成流程。右上「AI 供應商」可設定自己的供應商與金鑰。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Bot, HelpCircle, History, Loader2, Plus, RotateCcw, Save, Settings2, Sparkles, Square, ThumbsDown, ThumbsUp, Trash2, Upload, Wand2, X } from 'lucide-react'

import { AgentTimeline } from '@/components/agent/AgentTimeline'
import { LessonRating } from '@/components/assistant/LessonRating'
import { Page } from '@/components/layout/AppShell'
import { TemplateThumb } from '@/components/templates/TemplateGallery'
import { Badge, Button, Card, Modal, PageHeader, Select, StatusBadge, TextArea, TextInput } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { useAgentJob } from '@/lib/agentJob'
import { api, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import type { FlowGraph, Overlay, Region, RunReport } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

interface UploadedImage {
  group?: 'tune' | 'accept'
  ref: string
  width: number
  height: number
  name: string
}

interface RoiItem {
  region: Region
  hint: string
  image: number
}

interface Question {
  id: string
  text: string
  kind: 'choice' | 'number' | 'text' | 'roi'
  optional?: boolean
  hint?: string
  options?: { value: string; label: string }[]
}

interface ClarifyResult {
  ready: boolean
  questions: Question[]
  summary: string
  intent: string
  provider: string
  /** 代理模式背景工作提出的問題（回答走 /jobs/{id}/answer） */
  fromJob?: boolean
}

interface Candidate {
  key: string
  label: string
  rationale: string
  statuses: string[]
  score: number
  graph: FlowGraph
  chosen: boolean
}

interface AgentResult {
  acceptance?: { ok: number; ng: number; matches: number; labeled: number }
  graph: FlowGraph
  rationale: string
  provider: string
  intent: string
  report: RunReport
  reports: RunReport[]
  main_image: number
  warnings?: string[]
  /** 規則引擎的候選方案（含已選的）；LLM 生成時為空 */
  candidates?: Candidate[]
  labels?: string[]
  autotune?: { before: { match: number; total: number }; after: { match: number; total: number }; change_text: string[]; evals: number; elapsed_ms: number }
  /** 記憶：這次生成存成的工作階段，與參考過的相似成功案例 */
  session_id?: number | null
  similar?: { id: number; prompt: string; distance: number }[]
}

interface SessionRow {
  id: number
  task: string
  prompt: string
  intent: string
  provider: string
  mode: string
  image_count: number
  statuses: string[]
  labels: string[]
  success: boolean | null
  rating: number
  flow_id: number | null
  created_at: string
}

interface SessionFull extends SessionRow {
  images: { ref: string; width: number; height: number; name: string; group?: 'tune' | 'accept' }[]
  regions: { region: Region; hint?: string; image?: number }[]
  answers: { id: string; answer: string }[]
  graph: FlowGraph
  rationale: string
}

type ImageLabel = 'ok' | 'ng'
type BusyKind = 'clarify' | 'generate' | 'refine' | 'save' | 'switch'
const LABEL_CYCLE: (ImageLabel | undefined)[] = [undefined, 'ok', 'ng']

interface AgentInfo {
  provider: string
  model: string
  llm: boolean
  has_key: boolean
  base_url?: string
  mode?: string
  key_hint: string
  source: string
  reason: string
  providers: { value: string; label: string; default_model: string }[]
}

const EXAMPLES = ['agent.exCount', 'agent.exDiameter', 'agent.exDefect', 'agent.exColor', 'agent.exGolden'] as const

/** 已加入清單的 ROI 疊回影像（虛線框＋ROI 編號）。 */
function regionToOverlay(region: Region, label: string): Overlay | null {
  const base = { color: '#38bdf8', dash: true, label } as const
  switch (region.shape) {
    case 'rect':
      return { kind: 'rect', x: region.x, y: region.y, w: region.w, h: region.h, ...base }
    case 'rotated_rect':
      return { kind: 'rect', x: region.cx - region.w / 2, y: region.cy - region.h / 2, w: region.w, h: region.h, angle: region.angle, ...base }
    case 'circle':
      return { kind: 'circle', cx: region.cx, cy: region.cy, r: region.r, ...base }
    case 'annulus':
      return { kind: 'annulus', cx: region.cx, cy: region.cy, r_inner: region.r_inner, r_outer: region.r_outer, ...base }
    case 'line':
      return { kind: 'line', x1: region.x1, y1: region.y1, x2: region.x2, y2: region.y2, ...base }
    case 'polygon':
      return { kind: 'polygon', points: region.points as [number, number][], ...base }
    default:
      return null
  }
}

const roiTag = (i: number) => `ROI${String(i + 1).padStart(2, '0')}`

function ProviderSettingsModal({ open, onClose, info }: { open: boolean; onClose: () => void; info: AgentInfo | undefined }) {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const mine = useQuery({ queryKey: ['agent-settings'], queryFn: () => api.get<AgentInfo & { configured: boolean; server: AgentInfo }>('/vision/agent/settings'), enabled: open })
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [mode, setMode] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; provider: string; model: string; latency_ms: number; reason: string; reason_code?: string } | null>(null)
  const [listing, setListing] = useState(false)
  const [models, setModels] = useState<{ ok: boolean; models: string[]; reason: string; reason_code?: string } | null>(null)

  /** 失敗原因：碼有對照就翻成介面語言，沒有就用伺服器那句英文（供應商原文另外附在下面一行）。 */
  const reasonText = (code: string | undefined, fallback: string) => (code ? t(`agent.reason.${code}`, { defaultValue: fallback }) : fallback)

  /** 畫面上這組設定（還沒儲存也能先試）：沒動過的欄位留空，伺服器沿用已儲存的值。 */
  function probeBody() {
    return { provider: effProvider, model: model || undefined, api_key: apiKey || undefined, base_url: baseUrl || undefined }
  }

  async function listModels() {
    setListing(true)
    try {
      setModels(await api.post<{ ok: boolean; models: string[]; reason: string; reason_code?: string }>('/vision/agent/settings/models', probeBody()))
    } catch (error) {
      setModels({ ok: false, models: [], reason: errorMessage(error) })
    } finally {
      setListing(false)
    }
  }
  const current = mine.data
  const effProvider = provider || current?.provider || 'offline'
  const defaultModel = info?.providers.find((p) => p.value === effProvider)?.default_model ?? ''
  // 換了供應商就要這一家自己的金鑰（伺服器不會拿別家的金鑰去打）；本地端點以 base URL 為準
  const sameProvider = effProvider === current?.provider
  const canProbe = Boolean(apiKey || baseUrl || (sameProvider && (current?.has_key || current?.base_url)))

  /** 預設試畫面上這組；存檔後傳 {} 讓伺服器用剛存好的設定（金鑰欄已清空，不能再拿舊值去試）。 */
  async function testConnection(body: Record<string, string | undefined> = probeBody()) {
    setTesting(true)
    try {
      const r = await api.post<{ ok: boolean; provider: string; model: string; latency_ms: number; reason: string; reason_code?: string }>('/vision/agent/settings/test', body)
      setTestResult(r)
      return r
    } catch (error) {
      const r = { ok: false, provider: effProvider, model: '', latency_ms: 0, reason: errorMessage(error) }
      setTestResult(r)
      return r
    } finally {
      setTesting(false)
    }
  }

  async function save(clearKey = false) {
    setSaving(true)
    try {
      await api.patch('/vision/agent/settings', { provider: effProvider, model: model || undefined, api_key: apiKey || undefined, base_url: baseUrl || undefined, mode: mode || undefined, clear_key: clearKey })
      await client.invalidateQueries({ queryKey: ['agent-info'] })
      await client.invalidateQueries({ queryKey: ['agent-settings'] })
      setApiKey('')
      // 存完立刻打一次最小請求：成功／失敗原因直接顯示在視窗裡，不用猜
      const r = await testConnection({})
      if (r.ok) toast.success(effProvider === 'offline' ? t('agent.settingsSaved') : t('agent.testOk', { model: r.model, ms: r.latency_ms }))
      else toast.error(t('agent.testFailed', { reason: r.reason }))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={t('agent.settings')} description={t('agent.settingsHint')}
      footer={<>
        <Button onClick={onClose}>{t('common.close')}</Button>
        <Button loading={testing} disabled={saving} onClick={() => void testConnection()} data-testid="agent-settings-test">{testing ? t('agent.testing') : t('agent.testConnection')}</Button>
        <Button variant="primary" loading={saving} onClick={() => void save()} data-testid="agent-settings-save">{t('common.save')}</Button>
      </>}>
      <div className="space-y-3">
        <Select label={t('agent.provider')} value={effProvider} onChange={(e) => { setProvider(e.target.value); setModels(null); setTestResult(null) }}
          options={(info?.providers ?? []).map((p) => ({ value: p.value, label: p.label }))} data-testid="agent-provider" />
        {effProvider !== 'offline' ? (
          <>
            {effProvider === 'openai_compatible' ? (
              <TextInput label={t('agent.baseUrl')} placeholder="http://127.0.0.1:11434/v1" value={baseUrl || (provider ? '' : current?.base_url ?? '')} onChange={(e) => setBaseUrl(e.target.value)} data-testid="agent-base-url" />
            ) : null}
            <div className="space-y-1.5">
              <div className="flex items-end gap-2">
                <TextInput label={t('agent.model')} placeholder={defaultModel} value={model || (provider ? '' : current?.model ?? '')} onChange={(e) => setModel(e.target.value)} data-testid="agent-model" />
                <Button loading={listing} disabled={!canProbe} title={canProbe ? t('agent.listModelsHint') : t('agent.listModelsNeedKey')} onClick={() => void listModels()} data-testid="agent-list-models">{t('agent.listModels')}</Button>
              </div>
              {models ? (
                models.ok ? (
                  models.models.length ? (
                    <div className="flex max-h-32 flex-wrap gap-1 overflow-y-auto" data-testid="agent-models">
                      {models.models.map((m) => (
                        <button key={m} type="button" onClick={() => setModel(m)} className={`rounded-full border px-2 py-0.5 font-mono text-[11px] ${m === (model || current?.model) ? 'border-brand bg-brand-soft text-brand' : 'border-line text-muted hover:bg-surface-muted'}`}>{m}</button>
                      ))}
                    </div>
                  ) : <p className="text-[11px] text-subtle">{t('agent.noModels')}</p>
                ) : <p className="text-[11px] text-critical" data-testid="agent-models-error">{reasonText(models.reason_code, models.reason)}</p>
              ) : null}
            </div>
            <div className="space-y-1">
              <Select label={t('agent.mode')} value={mode || current?.mode || 'single'} onChange={(e) => setMode(e.target.value)}
                options={[{ value: 'single', label: t('agent.modeSingle') }, { value: 'agentic', label: t('agent.modeAgentic') }]} data-testid="agent-mode" />
              <p className="text-[11px] text-subtle">{t('agent.modeHint')}</p>
            </div>
            <div className="space-y-1">
              <TextInput label={t('agent.apiKey')} type="password" placeholder={current?.has_key ? t('agent.keySet', { hint: current.key_hint }) : 'sk-…'} value={apiKey} onChange={(e) => setApiKey(e.target.value)} data-testid="agent-key" />
              <p className="text-[11px] text-subtle">{t('agent.apiKeyHint')}</p>
              {current?.has_key ? <button type="button" className="text-[11px] text-critical hover:underline" onClick={() => void save(true)}>{t('agent.clearKey')}</button> : null}
            </div>
          </>
        ) : (
          <p className="text-xs text-muted">{t('agent.offlineHint')}</p>
        )}
        {current?.server?.llm ? <p className="text-[11px] text-subtle">{t('agent.serverHasKey', { provider: current.server.provider })}</p> : null}
        {testResult ? (
          <div className={`rounded-lg border px-3 py-2 text-xs ${testResult.ok ? 'border-ok/40 bg-ok-soft text-ok' : 'border-critical/40 bg-critical-soft text-critical'}`} data-testid="agent-test-result">
            {testResult.ok ? (
              testResult.provider === 'offline' ? t('agent.testOffline') : t('agent.testOk', { model: testResult.model, ms: testResult.latency_ms })
            ) : (
              <>
                <p>{t('agent.testFailed', { reason: reasonText(testResult.reason_code, testResult.reason) })}</p>
                {testResult.reason_code && testResult.reason_code !== 'unknown' ? <p className="mt-1 break-all opacity-70">{testResult.reason}</p> : null}
              </>
            )}
          </div>
        ) : null}
      </div>
    </Modal>
  )
}

interface SkillDoc {
  key: string
  markdown: string
  custom?: { site: string; user: string }
  can_site?: boolean
}

/** AI 技能瀏覽與補充：左列表（指南＋各工具）、右 markdown 原文——AI 代理讀的就是這份；下方可寫站點／個人補充。 */
function SkillsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const [key, setKey] = useState('platform')
  const [scope, setScope] = useState<'user' | 'site'>('user')
  const [customText, setCustomText] = useState('')
  const [saving, setSaving] = useState(false)
  const list = useQuery({ queryKey: ['agent-skills'], queryFn: () => api.get<{ items: { key: string; label: string; category: string; curated: boolean }[] }>('/vision/agent/skills'), enabled: open })
  const doc = useQuery({ queryKey: ['agent-skill', key], queryFn: () => api.get<SkillDoc>(`/vision/agent/skills/${key}`), enabled: open })
  const existing = doc.data?.custom?.[scope] ?? ''
  useEffect(() => {
    setCustomText(existing)
  }, [existing, key, scope])

  async function saveCustom() {
    setSaving(true)
    try {
      await api.put(`/vision/agent/skills/custom/${key}`, { markdown: customText, scope })
      await client.invalidateQueries({ queryKey: ['agent-skill', key] })
      toast.success(t('agent.skillsCustomSaved'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  async function deleteCustom() {
    setSaving(true)
    try {
      await api.delete(`/vision/agent/skills/custom/${key}?scope=${scope}`)
      await client.invalidateQueries({ queryKey: ['agent-skill', key] })
      setCustomText('')
      toast.success(t('agent.skillsCustomDeleted'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} size="xl" title={t('agent.skills')} description={t('agent.skillsHint')}>
      <div className="grid h-[70vh] min-h-0 grid-cols-[220px_minmax(0,1fr)] gap-3 overflow-hidden">
        <div className="min-h-0 space-y-0.5 overflow-y-auto pr-1 text-xs" data-testid="skills-list">
          {(list.data?.items ?? []).map((it) => (
            <button key={it.key} type="button" onClick={() => setKey(it.key)}
              className={`flex w-full items-center justify-between rounded px-2 py-1 text-left ${it.key === key ? 'bg-brand-soft text-brand' : 'hover:bg-surface-muted'}`}>
              <span className="truncate">{it.category === 'guide' ? `📘 ${it.label}` : `${it.label} · ${it.key}`}</span>
              {it.curated && it.category !== 'guide' ? <span className="ml-1 shrink-0 text-[9px] text-subtle" title={t('agent.skillsCurated')}>★</span> : null}
            </button>
          ))}
        </div>
        <div className="flex min-h-0 flex-col gap-2">
          <pre className="min-h-0 flex-1 overflow-auto rounded-lg border border-line bg-surface-muted p-3 text-[11px] leading-relaxed whitespace-pre-wrap" data-testid="skills-doc">
            {doc.data?.markdown ?? ''}
          </pre>
          <div className="space-y-1.5 rounded-lg border border-line p-2" data-testid="skills-custom">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold">{t('agent.skillsCustom')}</span>
              {doc.data?.can_site ? (
                <select className="input !w-auto !py-0.5 text-[11px]" value={scope} onChange={(e) => setScope(e.target.value as 'user' | 'site')} data-testid="skills-scope">
                  <option value="user">{t('agent.skillsScopeUser')}</option>
                  <option value="site">{t('agent.skillsScopeSite')}</option>
                </select>
              ) : null}
              <span className="text-[11px] text-subtle">{t('agent.skillsCustomHint')}</span>
            </div>
            <textarea className="input h-20 w-full resize-y text-[11px]" value={customText} onChange={(e) => setCustomText(e.target.value)} placeholder={t('agent.skillsCustomPlaceholder')} data-testid="skills-custom-text" />
            <div className="flex gap-2">
              <Button size="xs" variant="primary" loading={saving} disabled={!customText.trim()} onClick={() => void saveCustom()} data-testid="skills-custom-save">{t('common.save')}</Button>
              {existing ? <Button size="xs" loading={saving} onClick={() => void deleteCustom()} data-testid="skills-custom-delete">{t('common.delete')}</Button> : null}
            </div>
          </div>
        </div>
      </div>
    </Modal>
  )
}

/** 歷史工作階段：列表、還原（影像重新進快取＋流程重跑）、刪除。 */
function HistoryModal({ open, onClose, onRestore }: { open: boolean; onClose: () => void; onRestore: (s: SessionFull) => Promise<void> }) {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const [busyId, setBusyId] = useState<number | null>(null)
  const sessions = useQuery({ queryKey: ['agent-sessions'], queryFn: () => api.get<{ items: SessionRow[]; total: number }>('/vision/agent/sessions'), enabled: open })

  async function restore(id: number) {
    setBusyId(id)
    try {
      const full = await api.post<SessionFull>(`/vision/agent/sessions/${id}/restore`)
      await onRestore(full)
      onClose()
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusyId(null)
    }
  }

  async function remove(id: number) {
    setBusyId(id)
    try {
      await api.delete(`/vision/agent/sessions/${id}`)
      await client.invalidateQueries({ queryKey: ['agent-sessions'] })
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusyId(null)
    }
  }

  const items = sessions.data?.items ?? []
  return (
    <Modal open={open} onClose={onClose} size="lg" title={t('agent.historyTitle')} description={t('agent.historyHint')}>
      <div className="max-h-[60vh] space-y-1.5 overflow-y-auto pr-1" data-testid="agent-history">
        {items.length === 0 ? <p className="text-xs text-muted">{t('agent.historyEmpty')}</p> : null}
        {items.map((s) => (
          <div key={s.id} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs" data-testid="agent-history-row">
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium" title={s.prompt}>#{s.id} · {s.prompt || '—'}</p>
              <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                <span>{new Date(s.created_at).toLocaleString()}</span>
                <Badge>{s.intent || '?'}</Badge>
                <span>{t('agent.imageN', { n: s.image_count })}</span>
                {s.statuses.map((st, i) => <StatusBadge key={i} status={st} />)}
                {s.success === true ? <span className="text-ok">✓</span> : s.success === false ? <span className="text-critical">✗</span> : null}
                {s.rating === 1 ? <ThumbsUp size={11} className="text-ok" /> : s.rating === -1 ? <ThumbsDown size={11} className="text-critical" /> : null}
                {s.mode === 'agentic' ? <Badge tone="brand">{t('agent.modeAgentic')}</Badge> : null}
              </p>
            </div>
            <Button size="xs" icon={<RotateCcw size={12} />} loading={busyId === s.id} onClick={() => void restore(s.id)} data-testid="agent-history-restore">{t('agent.restore')}</Button>
            <button type="button" className="btn-icon text-critical" aria-label={t('common.delete')} disabled={busyId === s.id} onClick={() => void remove(s.id)}><Trash2 size={14} /></button>
          </div>
        ))}
      </div>
    </Modal>
  )
}

export function AgentPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)
  const [images, setImages] = useState<UploadedImage[]>([])
  const [active, setActive] = useState(0)
  const [prompt, setPrompt] = useState('')
  const [rois, setRois] = useState<RoiItem[]>([])
  const [drawing, setDrawing] = useState<Region | null>(null)
  const [result, setResult] = useState<AgentResult | null>(null)
  const [feedback, setFeedback] = useState('')
  const [flowName, setFlowName] = useState('')
  const [busy, setBusy] = useState<BusyKind | null>(null)
  /** 每張影像的期望判定（OK／NG）：候選排名與自動調參的依據 */
  const [labels, setLabels] = useState<Record<number, ImageLabel>>({})
  const abortRef = useRef<AbortController | null>(null)
  /** 詢問機制：助手提出的問題與使用者的回答（id → answer） */
  const [clarify, setClarify] = useState<ClarifyResult | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [showOverlays, setShowOverlays] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [skillsOpen, setSkillsOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  /** 這次結果的評分（session_id → 1／-1） */
  const [rated, setRated] = useState<{ id: number; rating: number } | null>(null)
  const info = useQuery({ queryKey: ['agent-info'], queryFn: () => api.get<AgentInfo>('/vision/agent/info') })
  /** 代理模式：生成走背景工作＋步驟時間軸 */
  const jobApi = useAgentJob<AgentResult>()
  const agentic = Boolean(info.data?.llm && info.data?.mode === 'agentic')

  const image = images[active] ?? null
  const activeReport = result?.reports[active] ?? null

  const overlays = useMemo<Overlay[]>(() => {
    const list: Overlay[] = rois
      .map((r, i) => (r.image === active ? regionToOverlay(r.region, roiTag(i)) : null))
      .filter((o): o is Overlay => o !== null)
    if (activeReport && showOverlays) list.push(...Object.values(activeReport.nodes).flatMap((n) => n.overlays ?? []))
    return list
  }, [activeReport, showOverlays, rois, active])

  async function onUpload(files: FileList | null) {
    if (!files?.length) return
    const added: UploadedImage[] = []
    for (const file of [...files]) {
      const form = new FormData()
      form.append('image', file)
      try {
        added.push(await api.postForm<UploadedImage>('/vision/agent/image', form))
      } catch (error) {
        toast.error(errorMessage(error))
      }
    }
    if (!added.length) return
    setImages((list) => {
      const next = [...list, ...added]
      setActive(next.length - added.length)
      return next
    })
    setDrawing(null)
    setResult(null)
  }

  function cycleLabel(idx: number) {
    setLabels((m) => {
      const next = { ...m }
      const cur = LABEL_CYCLE.indexOf(m[idx])
      const val = LABEL_CYCLE[(cur + 1) % LABEL_CYCLE.length]
      if (val) next[idx] = val
      else delete next[idx]
      return next
    })
  }

  function removeImage(idx: number) {
    setImages((list) => list.filter((_, i) => i !== idx))
    setLabels((m) => {
      const next: Record<number, ImageLabel> = {}
      for (const [k, v] of Object.entries(m)) {
        const i = Number(k)
        if (i !== idx) next[i > idx ? i - 1 : i] = v
      }
      return next
    })
    setRois((list) => list.filter((r) => r.image !== idx).map((r) => ({ ...r, image: r.image > idx ? r.image - 1 : r.image })))
    setActive((a) => Math.max(0, a >= idx ? a - 1 : a))
    setResult(null)
  }

  function addRoi() {
    if (!drawing) return
    setRois((list) => [...list, { region: drawing, hint: '', image: active }])
    setDrawing(null)
  }

  const payload = useMemo(() => {
    const regions = rois.map((r) => ({ region: r.region as unknown as Record<string, unknown>, hint: r.hint, image: r.image }))
    if (drawing) regions.push({ region: drawing as unknown as Record<string, unknown>, hint: '', image: active })
    return { images: images.map((im) => im.ref), prompt, regions, labels: images.map((_, i) => labels[i] ?? ''), groups: images.map((im) => im.group ?? 'tune') }
  }, [rois, drawing, images, prompt, active, labels])

  function abort() {
    if (jobApi.running) {
      void jobApi.cancel()
      return
    }
    abortRef.current?.abort()
  }

  // 背景工作狀態變化 → 結果／提問／取消／失敗
  const jobStatus = jobApi.job?.status
  const jobId = jobApi.job?.id
  useEffect(() => {
    const j = jobApi.job
    if (!j || j.status === 'running') return
    if (j.status === 'done' || j.status === 'budget') {
      if (j.result) {
        setResult(j.result)
        setActive((a) => Math.min(j.result?.main_image ?? a, Math.max(0, images.length - 1)))
        setFeedback('')
      }
      setBusy(null)
    } else if (j.status === 'needs_input') {
      const questions = j.questions.filter((q) => q.kind !== 'confirm' && !q.action) as Question[]
      setClarify(questions.length ? { ready: false, questions, summary: '', intent: '', provider: j.provider, fromJob: true } : null)
      setBusy(null)
    } else if (j.status === 'cancelled') {
      toast.success(t('agent.aborted'))
      setBusy(null)
    } else if (j.status === 'error') {
      toast.error(j.error || t('agent.jobStatus.error'))
      setBusy(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobStatus, jobId])

  function newController(kind: BusyKind) {
    const controller = new AbortController()
    abortRef.current = controller
    setBusy(kind)
    return controller
  }

  const answerList = useMemo(() => Object.entries(answers).map(([id, answer]) => ({ id, answer })), [answers])

  /** 第一階段：請助手確認資訊是否足夠；不足就顯示問題卡。skip=true 直接生成。 */
  async function generate(skip = false) {
    if (!images.length) return
    if (skip) {
      await runGenerate()
      return
    }
    const controller = newController('clarify')
    try {
      const r = await api.post<ClarifyResult>('/vision/agent/clarify', { ...payload, answers: answerList }, undefined, controller.signal)
      if (r.ready) {
        setClarify(null)
        await runGenerate()
      } else {
        setClarify(r)
      }
    } catch (error) {
      if (!controller.signal.aborted) toast.error(errorMessage(error))
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setBusy((b) => (b === 'clarify' ? null : b))
    }
  }

  /** 回答完目前這一輪問題後再確認一次（可能還有下一輪或直接生成）。 */
  async function continueClarify() {
    // 沒回答的題目也記為「已問過」（空字串），助手不會重問
    const filled = { ...answers }
    for (const q of clarify?.questions ?? []) if (!(q.id in filled)) filled[q.id] = ''
    setAnswers(filled)
    if (clarify?.fromJob) {
      const list = clarify.questions.map((q) => ({ id: q.id, answer: filled[q.id] ?? '' }))
      setClarify(null)
      setBusy('generate')
      try {
        await jobApi.answer(list)
      } catch (error) {
        toast.error(errorMessage(error))
        setBusy(null)
      }
      return
    }
    setClarify(null)
    const controller = newController('clarify')
    try {
      const list = Object.entries(filled).map(([id, answer]) => ({ id, answer }))
      const r = await api.post<ClarifyResult>('/vision/agent/clarify', { ...payload, answers: list }, undefined, controller.signal)
      if (r.ready) await runGenerate(list)
      else setClarify(r)
    } catch (error) {
      if (!controller.signal.aborted) toast.error(errorMessage(error))
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setBusy((b) => (b === 'clarify' ? null : b))
    }
  }

  /** 第二階段：真的生成（帶問答）。 */
  async function runGenerate(list: { id: string; answer: string }[] = answerList) {
    if (agentic) {
      setBusy('generate')
      setClarify(null)
      try {
        await jobApi.start({ ...payload, task: 'generate', answers: list })
      } catch (error) {
        toast.error(errorMessage(error))
        setBusy(null)
      }
      return
    }
    const controller = newController('generate')
    try {
      const r = await api.post<AgentResult>('/vision/agent/generate', { ...payload, answers: list }, undefined, controller.signal)
      setResult(r)
      setClarify(null)
      setActive(Math.min(r.main_image ?? 0, images.length - 1))
      setFeedback('')
    } catch (error) {
      if (controller.signal.aborted) toast.success(t('agent.aborted'))
      else toast.error(errorMessage(error))
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setBusy(null)
    }
  }

  async function refine() {
    if (!images.length || !result || !feedback.trim()) return
    const controller = newController('refine')
    try {
      const r = await api.post<AgentResult>('/vision/agent/refine', { ...payload, graph: result.graph, feedback, answers: answerList }, undefined, controller.signal)
      setResult(r)
      setFeedback('')
    } catch (error) {
      if (!controller.signal.aborted) toast.error(errorMessage(error))
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setBusy(null)
    }
  }

  /** 切換候選方案：把該方案的 graph 在同一批影像重跑（overlay 與判定隨之更新）。 */
  async function switchCandidate(c: Candidate) {
    if (!result || c.chosen || !images.length) return
    const controller = newController('switch')
    try {
      const r = await api.post<AgentResult>('/vision/agent/run', { images: images.map((im) => im.ref), graph: c.graph, main: active }, undefined, controller.signal)
      setResult({ ...result, graph: c.graph, rationale: c.rationale, report: r.report, reports: r.reports, candidates: result.candidates?.map((x) => ({ ...x, chosen: x.key === c.key })) })
    } catch (error) {
      if (!controller.signal.aborted) toast.error(errorMessage(error))
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setBusy(null)
    }
  }

  async function rate(value: 1 | -1) {
    if (!result?.session_id) return
    try {
      await api.patch(`/vision/agent/sessions/${result.session_id}`, { rating: value })
      setRated({ id: result.session_id, rating: value })
      toast.success(t('agent.rated'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  /** 還原歷史工作階段：影像、ROI、需求、標記帶回，流程在同批影像重跑。 */
  async function restoreSession(s: SessionFull) {
    const refs = s.images.map((im) => im.ref)
    const run = await api.post<AgentResult>('/vision/agent/run', { images: refs, graph: s.graph, main: 0 })
    setImages(s.images.map((im) => ({ ref: im.ref, width: im.width, height: im.height, name: im.name, group: im.group ?? 'tune' })))
    setRois((s.regions ?? []).map((r) => ({ region: r.region, hint: r.hint ?? '', image: r.image ?? 0 })))
    setPrompt(s.prompt)
    setAnswers(Object.fromEntries((s.answers ?? []).map((a) => [a.id, a.answer])))
    const nextLabels: Record<number, ImageLabel> = {}
    ;(s.labels ?? []).forEach((lb, i) => { if (lb === 'ok' || lb === 'ng') nextLabels[i] = lb })
    setLabels(nextLabels)
    setDrawing(null)
    setClarify(null)
    setActive(0)
    setResult({ graph: s.graph, rationale: s.rationale, provider: s.provider, intent: s.intent, report: run.report, reports: run.reports, main_image: 0, candidates: [], session_id: s.id })
    setRated(s.rating ? { id: s.id, rating: s.rating } : null)
    toast.success(t('agent.restored', { id: s.id }))
  }

  async function saveFlow() {
    if (!result) return
    setBusy('save')
    try {
      const name = flowName.trim() || t('agent.defaultFlowName')
      const r = await api.post<{ id: number }>('/vision/flows', { name, description: result.rationale, graph: result.graph })
      if (result.session_id) void api.patch(`/vision/agent/sessions/${result.session_id}`, { flow_id: r.id }).catch(() => undefined)
      toast.success(t('agent.saved'))
      navigate(`/flows/${r.id}`)
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusy(null)
    }
  }

  const tone = (status?: string): 'ok' | 'ng' | 'neutral' => (status === 'ok' ? 'ok' : status === 'ng' ? 'ng' : 'neutral')
  const badgeTone = (status?: string) => (status === 'ok' ? 'ok' : status === 'ng' ? 'critical' : 'neutral')

  return (
    <Page wide>
      <div className="flex h-[calc(100vh-7.5rem)] min-h-[560px] flex-col">
        <PageHeader
          title={t('agent.title')}
          description={t('agent.subtitle')}
          actions={
            <>
              {info.data ? (
                <Badge tone={info.data.llm ? 'brand' : 'neutral'} >
                  <Bot size={12} /> {info.data.llm ? t('agent.providerLlm', { model: info.data.model }) : t('agent.providerRules')}{agentic ? ` · ${t('agent.modeAgentic')}` : ''}
                </Badge>
              ) : null}
              <Button size="sm" icon={<History size={14} />} onClick={() => setHistoryOpen(true)} data-testid="agent-history-open">{t('agent.history')}</Button>
              <Button size="sm" icon={<BookOpen size={14} />} onClick={() => setSkillsOpen(true)} data-testid="agent-skills">{t('agent.skills')}</Button>
              <Button size="sm" icon={<Settings2 size={14} />} onClick={() => setSettingsOpen(true)} data-testid="agent-settings">{t('agent.settings')}</Button>
            </>
          }
        />
        <div className="flex min-h-0 flex-1 gap-4">
          {/* 左：步驟 */}
          <div className="w-full shrink-0 space-y-3 overflow-y-auto pb-4 pr-1 md:w-[380px]">
            <Card className="space-y-2 p-3">
              <p className="text-xs font-semibold text-muted">1 · {t('agent.stepImage')}</p>
              <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => { void onUpload(e.target.files); e.target.value = '' }} />
              <Button className="w-full !justify-center" icon={<Upload size={14} />} onClick={() => fileRef.current?.click()} data-testid="agent-upload">
                {images.length ? t('agent.addImage') : t('agent.upload')}
              </Button>
              {images.length ? (
                <div className="flex flex-wrap gap-1.5" data-testid="agent-images">
                  {images.map((im, i) => {
                    const st = result?.reports[i]?.status
                    const lb = labels[i]
                    return (
                      <div key={im.ref} className={`group w-32 overflow-hidden rounded border ${i === active ? 'border-brand ring-2 ring-brand/30' : 'border-line'}`}>
                        <div className="relative">
                        <button type="button" onClick={() => { setActive(i); setDrawing(null) }} title={im.name} className="block">
                          <img src={imageUrl(im.ref, 160)} alt="" className="h-20 w-32 object-cover" />
                        </button>
                        <span className="pointer-events-none absolute left-0.5 top-0.5 rounded bg-black/60 px-1 text-[9px] text-white">{t('agent.imageN', { n: i + 1 })}</span>
                        {st ? <span className={`pointer-events-none absolute bottom-0.5 left-0.5 rounded px-1 text-[9px] font-semibold text-white ${st === 'ok' ? 'bg-ok' : st === 'ng' ? 'bg-critical' : 'bg-neutral-500'}`}>{st.toUpperCase()}</span> : null}
                        <button type="button" onClick={() => removeImage(i)} aria-label={t('common.delete')} className="absolute right-0.5 top-0.5 rounded bg-black/60 p-0.5 text-white opacity-0 group-hover:opacity-100"><X size={10} /></button>
                        <button type="button" onClick={() => cycleLabel(i)} title={t('agent.labelHint')} data-testid="agent-label"
                          className={`absolute bottom-0.5 right-0.5 rounded px-1 text-[9px] font-semibold ${lb === 'ok' ? 'bg-ok text-white' : lb === 'ng' ? 'bg-critical text-white' : 'bg-black/50 text-white/80'}`}>
                          {lb ? lb.toUpperCase() : t('agent.labelNone')}
                        </button>
                        </div>
                        <select className="input !w-full !text-[10px]" aria-label={t('evidence.group')} value={im.group ?? 'tune'} data-testid="agent-image-group"
                          onChange={(e) => setImages((list) => list.map((item, index) => index === i ? { ...item, group: e.target.value as 'tune' | 'accept' } : item))}>
                          <option value="tune">{t('evidence.tune')}</option><option value="accept">{t('evidence.accept')}</option>
                        </select>
                      </div>
                    )
                  })}
                </div>
              ) : <p className="text-xs text-subtle">{t('agent.uploadHint')}</p>}
              {images.length ? <p className="text-[11px] text-subtle">{t('agent.labelHint')}</p> : null}
            </Card>

            <Card className="space-y-2 p-3">
              <p className="text-xs font-semibold text-muted">2 · {t('agent.stepRoi')}</p>
              <p className="text-xs text-subtle">{t('agent.drawHint')}</p>
              {rois.map((r, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Badge tone={r.image === active ? 'brand' : 'neutral'}>{roiTag(i)} · {t('agent.imageN', { n: r.image + 1 })}</Badge>
                  <TextInput className="flex-1 text-xs" placeholder={t('agent.roiHint')} value={r.hint}
                    onChange={(e) => setRois((list) => list.map((x, j) => (j === i ? { ...x, hint: e.target.value } : x)))} />
                  <button type="button" className="btn-icon text-critical" aria-label={t('common.delete')}
                    onClick={() => setRois((list) => list.filter((_, j) => j !== i))}>
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
              {drawing ? (
                <Button size="sm" className="w-full !justify-center" icon={<Plus size={13} />} onClick={addRoi} data-testid="agent-add-roi">
                  {t('agent.addRoi')} ({roiTag(rois.length)} · {drawing.shape})
                </Button>
              ) : null}
            </Card>

            <Card className="space-y-2 p-3">
              <p className="text-xs font-semibold text-muted">3 · {t('agent.stepPrompt')}</p>
              <TextArea rows={3} placeholder={t('agent.promptPlaceholder')} value={prompt} onChange={(e) => setPrompt(e.target.value)} data-testid="agent-prompt" />
              <div className="flex flex-wrap gap-1.5">
                {EXAMPLES.map((key) => (
                  <button key={key} type="button" onClick={() => setPrompt(t(key))}
                    className="rounded-full border border-line px-2 py-0.5 text-[11px] text-muted hover:bg-surface-muted">
                    {t(key)}
                  </button>
                ))}
              </div>
              {busy === 'clarify' || busy === 'generate' ? (
                <div className="flex gap-2">
                  <span className="flex flex-1 items-center gap-2 rounded-md border border-line px-3 text-xs text-muted"><Loader2 size={14} className="animate-spin" /> {busy === 'clarify' ? t('agent.clarifying') : jobApi.running ? t('agent.jobRunning') : t('agent.thinking')}</span>
                  <Button variant="danger" icon={<Square size={14} />} onClick={abort} data-testid="agent-abort">{t('agent.abort')}</Button>
                </div>
              ) : (
                <Button variant="primary" className="w-full !justify-center" disabled={!images.length || busy !== null}
                  icon={<Sparkles size={14} />} onClick={() => void generate()} data-testid="agent-generate">
                  {result ? t('agent.regenerate') : t('agent.generate')}
                </Button>
              )}
              {answerList.length && !clarify ? <p className="text-[11px] text-subtle">{t('agent.answersKept', { count: answerList.length })} <button type="button" className="underline" onClick={() => setAnswers({})}>{t('common.clear')}</button></p> : null}
            </Card>

            {jobApi.job ? (
              <Card className="space-y-2 p-3" testId="agent-job">
                <AgentTimeline job={jobApi.job} steps={jobApi.steps} onCancel={abort} />
              </Card>
            ) : null}

            {clarify && !clarify.ready ? (
              <Card className="space-y-3 border-brand/40 p-3" testId="agent-clarify">
                <div className="flex items-center gap-2">
                  <HelpCircle size={14} className="text-brand" />
                  <p className="text-xs font-semibold">{t('agent.clarifyTitle')}</p>
                </div>
                {clarify.summary ? <p className="text-[11px] text-muted">{t('agent.clarifySummary')}: {clarify.summary}</p> : null}
                {clarify.questions.map((q, i) => (
                  <div key={q.id} className="space-y-1.5" data-testid={`agent-question-${q.id}`}>
                    <p className="text-xs">{i + 1}. {q.text}{q.optional ? <span className="ml-1 text-subtle">{t('agent.optional')}</span> : null}</p>
                    {q.hint ? <p className="text-[11px] text-subtle">{q.hint}</p> : null}
                    {q.kind === 'choice' ? (
                      <div className="flex flex-wrap gap-1.5">
                        {(q.options ?? []).map((o) => (
                          <button key={o.value} type="button" onClick={() => setAnswers((a) => ({ ...a, [q.id]: o.value }))}
                            className={`rounded-full border px-2.5 py-1 text-xs ${answers[q.id] === o.value ? 'border-brand bg-brand-soft text-brand' : 'border-line text-muted hover:bg-surface-muted'}`}>
                            {o.label}
                          </button>
                        ))}
                      </div>
                    ) : q.kind === 'roi' ? (
                      <p className="rounded bg-brand-soft px-2 py-1 text-[11px] text-brand">{t('agent.roiQuestionHint')}</p>
                    ) : (
                      <TextInput className="text-xs" type={q.kind === 'number' ? 'number' : 'text'} value={answers[q.id] ?? ''}
                        onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))} placeholder={t('agent.answerPlaceholder')} />
                    )}
                  </div>
                ))}
                <div className="flex gap-2">
                  <Button variant="primary" className="flex-1 !justify-center" disabled={busy !== null} onClick={() => void continueClarify()} data-testid="agent-clarify-continue">{t('agent.continue')}</Button>
                  <Button disabled={busy !== null} onClick={() => { if (clarify.fromJob) { setClarify(null); setBusy('generate'); void jobApi.answer([]) } else { setClarify(null); void generate(true) } }} data-testid="agent-clarify-skip">{t('agent.skipQuestions')}</Button>
                </div>
              </Card>
            ) : null}

            {result ? (
              <Card className="space-y-2 p-3" testId="agent-result">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold text-muted">4 · {t('agent.stepResult')}</p>
                  <Badge tone={badgeTone(activeReport?.status)}>{t('agent.imageN', { n: active + 1 })} · {activeReport?.status?.toUpperCase()} · {Math.round(activeReport?.duration_ms ?? 0)} ms</Badge>
                </div>
                <TemplateThumb graph={result.graph} className="h-20 w-full rounded bg-surface-muted" />
                <p className="text-xs leading-relaxed text-muted">{result.rationale}</p>
                {result.acceptance ? <p className="text-xs text-muted" data-testid="agent-acceptance">{result.acceptance.labeled
                  ? `${t('evidence.accept')}: ${result.acceptance.matches}/${result.acceptance.labeled}` : t('evidence.noAcceptance')}</p> : null}
                {result.similar?.length ? <p className="text-[11px] text-subtle" data-testid="agent-similar">{t('agent.similarUsed', { count: result.similar.length, ids: result.similar.map((x) => `#${x.id}`).join(', ') })}</p> : null}
                {result.session_id ? (
                  <div className="flex flex-wrap items-center gap-1 text-[11px] text-muted" data-testid="agent-rate">
                    <span>{t('agent.rateHint')}</span>
                    <button type="button" className={`btn-icon ${rated?.id === result.session_id && rated.rating === 1 ? 'text-ok' : ''}`} title={t('agent.rateGood')} onClick={() => void rate(1)} data-testid="agent-rate-good"><ThumbsUp size={13} /></button>
                    <button type="button" className={`btn-icon ${rated?.id === result.session_id && rated.rating === -1 ? 'text-critical' : ''}`} title={t('agent.rateBad')} onClick={() => void rate(-1)} data-testid="agent-rate-bad"><ThumbsDown size={13} /></button>
                    <span className="text-subtle">#{result.session_id}</span>
                    <LessonRating key={result.session_id} sessionId={result.session_id} />
                  </div>
                ) : null}
                {result.warnings?.length ? (
                  <ul className="list-disc rounded bg-warning-soft px-2 py-1 pl-5 text-[11px] text-warning" data-testid="agent-warnings">
                    {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                ) : null}
                {result.candidates && result.candidates.length > 1 ? (
                  <div className="space-y-1" data-testid="agent-candidates">
                    <p className="text-[11px] font-semibold text-muted">{t('agent.candidates')}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {result.candidates.map((c) => (
                        <button key={c.key} type="button" disabled={busy !== null} title={c.rationale} onClick={() => void switchCandidate(c)}
                          className={`rounded-full border px-2 py-0.5 text-[11px] ${c.chosen ? 'border-brand bg-brand-soft text-brand' : 'border-line text-muted hover:bg-surface-muted'}`}>
                          {c.label} · {c.statuses.map((x) => x.toUpperCase()).join('/')}{c.score ? ` · ${c.score}` : ''}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
                {result.autotune ? (
                  <p className="rounded bg-brand-soft px-2 py-1 text-[11px] text-brand" data-testid="agent-autotune">
                    {t('evidence.tune')}{': '}
                    {t('agent.autotuned', { before: result.autotune.before.match, after: result.autotune.after.match, total: result.autotune.after.total, ms: result.autotune.elapsed_ms })}
                  </p>
                ) : null}
                {activeReport && Object.keys(activeReport.outputs).length ? (
                  <table className="w-full text-xs">
                    <tbody className="divide-y divide-line">
                      {Object.entries(activeReport.outputs).map(([k, v]) => (
                        <tr key={k}>
                          <td className="py-1 pr-2 font-mono text-muted">{k}</td>
                          <td className="py-1 text-right font-mono">{typeof v === 'number' ? Math.round(v * 1000) / 1000 : String(v)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : null}
                <label className="flex items-center gap-2 text-xs text-muted">
                  <input type="checkbox" checked={showOverlays} onChange={(e) => setShowOverlays(e.target.checked)} />
                  {t('agent.showOverlays')}
                </label>
                <div className="flex gap-2">
                  <TextInput className="flex-1 text-xs" placeholder={t('agent.feedbackPlaceholder')} value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') void refine() }} data-testid="agent-feedback" />
                  <Button disabled={!feedback.trim() || busy !== null}
                    icon={busy === 'refine' ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                    onClick={() => void refine()}>
                    {t('agent.refine')}
                  </Button>
                </div>
                <div className="flex gap-2 border-t border-line pt-2">
                  <TextInput className="flex-1 text-xs" placeholder={t('agent.flowName')} value={flowName} onChange={(e) => setFlowName(e.target.value)} />
                  <Button variant="primary" disabled={busy !== null}
                    icon={busy === 'save' ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                    onClick={() => void saveFlow()} data-testid="agent-save">
                    {t('agent.saveFlow')}
                  </Button>
                </div>
              </Card>
            ) : null}
          </div>

          {/* 右：目前影像＋ROI 圈選＋結果 overlay */}
          <div className="relative min-w-0 flex-1 overflow-hidden rounded-lg border border-line bg-surface">
            {image ? (
              <ImageViewer
                key={image.ref}
                src={imageUrl(image.ref, 1600)}
                imageWidth={image.width}
                imageHeight={image.height}
                overlays={overlays}
                roi={drawing}
                onRoiChange={setDrawing}
                roiShapes={['rect', 'rotated_rect', 'circle', 'annulus', 'polygon', 'line']}
                toolbar
                className="h-full w-full"
                badge={activeReport ? { text: activeReport.status.toUpperCase(), tone: tone(activeReport.status) } : null}
                stateKey={`agent:${image.ref}`}
              />
            ) : (
              <button type="button" onClick={() => fileRef.current?.click()}
                className="flex h-full w-full flex-col items-center justify-center gap-3 text-muted hover:text-content">
                <Upload size={40} className="opacity-40" />
                <p className="text-sm">{t('agent.emptyState')}</p>
              </button>
            )}
            {image ? (
              <div className="pointer-events-none absolute left-2 top-10 rounded bg-black/50 px-2 py-1 text-[11px] text-white/90">
                {t('agent.imageN', { n: active + 1 })} · {image.name} · {t('agent.roiCount', { count: rois.filter((r) => r.image === active).length })}
              </div>
            ) : null}
          </div>
        </div>
      </div>
      <ProviderSettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} info={info.data} />
      <SkillsModal open={skillsOpen} onClose={() => setSkillsOpen(false)} />
      <HistoryModal open={historyOpen} onClose={() => setHistoryOpen(false)} onRestore={restoreSession} />
    </Page>
  )
}
