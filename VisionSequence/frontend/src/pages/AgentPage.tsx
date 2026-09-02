/**
 * AI 助手（/agent）：上傳多張影像 → 在各張影像上圈 ROI（ROI01、ROI02…各配提示；提示詞可引用，
 * 例「ROI01 是好品、ROI02 是壞品」）→ 描述檢測需求 → 生成流程並在每張影像實跑（overlay 疊圖、
 * 縮圖列標 OK/NG）→ 口語回饋微調 → 存成流程。右上「AI 供應商」可設定自己的供應商與金鑰。
 */
import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Bot, Loader2, Plus, Save, Settings2, Sparkles, Trash2, Upload, Wand2, X } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { TemplateThumb } from '@/components/templates/TemplateGallery'
import { Badge, Button, Card, Modal, PageHeader, Select, TextArea, TextInput } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { api, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import type { FlowGraph, Overlay, Region, RunReport } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

interface UploadedImage {
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

interface AgentResult {
  graph: FlowGraph
  rationale: string
  provider: string
  intent: string
  report: RunReport
  reports: RunReport[]
  main_image: number
}

interface AgentInfo {
  provider: string
  model: string
  llm: boolean
  has_key: boolean
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
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; provider: string; model: string; latency_ms: number; reason: string } | null>(null)
  const current = mine.data
  const effProvider = provider || current?.provider || 'offline'
  const defaultModel = info?.providers.find((p) => p.value === effProvider)?.default_model ?? ''

  async function testConnection() {
    setTesting(true)
    try {
      const r = await api.post<{ ok: boolean; provider: string; model: string; latency_ms: number; reason: string }>('/vision/agent/settings/test')
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
      await api.patch('/vision/agent/settings', { provider: effProvider, model: model || undefined, api_key: apiKey || undefined, clear_key: clearKey })
      await client.invalidateQueries({ queryKey: ['agent-info'] })
      await client.invalidateQueries({ queryKey: ['agent-settings'] })
      setApiKey('')
      // 存完立刻打一次最小請求：成功／失敗原因直接顯示在視窗裡，不用猜
      const r = await testConnection()
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
        <Select label={t('agent.provider')} value={effProvider} onChange={(e) => setProvider(e.target.value)}
          options={(info?.providers ?? []).map((p) => ({ value: p.value, label: p.label }))} data-testid="agent-provider" />
        {effProvider !== 'offline' ? (
          <>
            <TextInput label={t('agent.model')} placeholder={defaultModel} value={model || (provider ? '' : current?.model ?? '')} onChange={(e) => setModel(e.target.value)} />
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
            {testResult.ok
              ? (testResult.provider === 'offline' ? t('agent.testOffline') : t('agent.testOk', { model: testResult.model, ms: testResult.latency_ms }))
              : t('agent.testFailed', { reason: testResult.reason })}
          </div>
        ) : null}
      </div>
    </Modal>
  )
}

/** AI 技能瀏覽：左列表（指南＋各工具）、右 markdown 原文——AI 代理讀的就是這份。 */
function SkillsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const [key, setKey] = useState('platform')
  const list = useQuery({ queryKey: ['agent-skills'], queryFn: () => api.get<{ items: { key: string; label: string; category: string; curated: boolean }[] }>('/vision/agent/skills'), enabled: open })
  const doc = useQuery({ queryKey: ['agent-skill', key], queryFn: () => api.get<{ key: string; markdown: string }>(`/vision/agent/skills/${key}`), enabled: open })
  return (
    <Modal open={open} onClose={onClose} size="xl" title={t('agent.skills')} description={t('agent.skillsHint')}>
      <div className="grid h-[65vh] min-h-0 grid-cols-[220px_minmax(0,1fr)] gap-3 overflow-hidden">
        <div className="min-h-0 space-y-0.5 overflow-y-auto pr-1 text-xs" data-testid="skills-list">
          {(list.data?.items ?? []).map((it) => (
            <button key={it.key} type="button" onClick={() => setKey(it.key)}
              className={`flex w-full items-center justify-between rounded px-2 py-1 text-left ${it.key === key ? 'bg-brand-soft text-brand' : 'hover:bg-surface-muted'}`}>
              <span className="truncate">{it.category === 'guide' ? `📘 ${it.label}` : `${it.label} · ${it.key}`}</span>
              {it.curated && it.category !== 'guide' ? <span className="ml-1 shrink-0 text-[9px] text-subtle" title={t('agent.skillsCurated')}>★</span> : null}
            </button>
          ))}
        </div>
        <pre className="min-h-0 overflow-auto rounded-lg border border-line bg-surface-muted p-3 text-[11px] leading-relaxed whitespace-pre-wrap" data-testid="skills-doc">
          {doc.data?.markdown ?? ''}
        </pre>
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
  const [busy, setBusy] = useState<'generate' | 'refine' | 'save' | null>(null)
  const [showOverlays, setShowOverlays] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [skillsOpen, setSkillsOpen] = useState(false)
  const info = useQuery({ queryKey: ['agent-info'], queryFn: () => api.get<AgentInfo>('/vision/agent/info') })

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

  function removeImage(idx: number) {
    setImages((list) => list.filter((_, i) => i !== idx))
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
    return { images: images.map((im) => im.ref), prompt, regions }
  }, [rois, drawing, images, prompt, active])

  async function generate() {
    if (!images.length) return
    setBusy('generate')
    try {
      const r = await api.post<AgentResult>('/vision/agent/generate', payload)
      setResult(r)
      setActive(Math.min(r.main_image ?? 0, images.length - 1))
      setFeedback('')
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusy(null)
    }
  }

  async function refine() {
    if (!images.length || !result || !feedback.trim()) return
    setBusy('refine')
    try {
      const r = await api.post<AgentResult>('/vision/agent/refine', { ...payload, graph: result.graph, feedback })
      setResult(r)
      setFeedback('')
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusy(null)
    }
  }

  async function saveFlow() {
    if (!result) return
    setBusy('save')
    try {
      const name = flowName.trim() || t('agent.defaultFlowName')
      const r = await api.post<{ id: number }>('/vision/flows', { name, description: result.rationale, graph: result.graph })
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
                  <Bot size={12} /> {info.data.llm ? t('agent.providerLlm', { model: info.data.model }) : t('agent.providerRules')}
                </Badge>
              ) : null}
              <Button size="sm" icon={<BookOpen size={14} />} onClick={() => setSkillsOpen(true)} data-testid="agent-skills">{t('agent.skills')}</Button>
              <Button size="sm" icon={<Settings2 size={14} />} onClick={() => setSettingsOpen(true)} data-testid="agent-settings">{t('agent.settings')}</Button>
            </>
          }
        />
        <div className="flex min-h-0 flex-1 gap-4">
          {/* 左：步驟 */}
          <div className="w-[380px] shrink-0 space-y-3 overflow-y-auto pb-4 pr-1">
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
                    return (
                      <div key={im.ref} className={`group relative overflow-hidden rounded border ${i === active ? 'border-brand ring-2 ring-brand/30' : 'border-line'}`}>
                        <button type="button" onClick={() => { setActive(i); setDrawing(null) }} title={im.name} className="block">
                          <img src={imageUrl(im.ref, 160)} alt="" className="h-12 w-16 object-cover" />
                        </button>
                        <span className="pointer-events-none absolute left-0.5 top-0.5 rounded bg-black/60 px-1 text-[9px] text-white">{t('agent.imageN', { n: i + 1 })}</span>
                        {st ? <span className={`pointer-events-none absolute bottom-0.5 left-0.5 rounded px-1 text-[9px] font-semibold text-white ${st === 'ok' ? 'bg-ok' : st === 'ng' ? 'bg-critical' : 'bg-neutral-500'}`}>{st.toUpperCase()}</span> : null}
                        <button type="button" onClick={() => removeImage(i)} aria-label={t('common.delete')} className="absolute right-0.5 top-0.5 rounded bg-black/60 p-0.5 text-white opacity-0 group-hover:opacity-100"><X size={10} /></button>
                      </div>
                    )
                  })}
                </div>
              ) : <p className="text-xs text-subtle">{t('agent.uploadHint')}</p>}
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
                  {t('agent.addRoi')}（{roiTag(rois.length)} · {drawing.shape}）
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
              <Button variant="primary" className="w-full !justify-center" disabled={!images.length || busy !== null}
                icon={busy === 'generate' ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                onClick={() => void generate()} data-testid="agent-generate">
                {result ? t('agent.regenerate') : t('agent.generate')}
              </Button>
            </Card>

            {result ? (
              <Card className="space-y-2 p-3" data-testid="agent-result">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold text-muted">4 · {t('agent.stepResult')}</p>
                  <Badge tone={badgeTone(activeReport?.status)}>{t('agent.imageN', { n: active + 1 })} · {activeReport?.status?.toUpperCase()} · {Math.round(activeReport?.duration_ms ?? 0)} ms</Badge>
                </div>
                <TemplateThumb graph={result.graph} className="h-20 w-full rounded bg-surface-muted" />
                <p className="text-xs leading-relaxed text-muted">{result.rationale}</p>
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
    </Page>
  )
}
