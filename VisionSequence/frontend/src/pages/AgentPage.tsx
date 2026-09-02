/**
 * AI 助手（/agent）：上傳影像 → 圈 ROI（可多個、各配提示）→ 描述檢測需求 →
 * 生成流程並在這張影像上實跑（overlay 直接疊圖）→ 口語回饋微調 → 存成流程。
 * 後端 /vision/agent/*；有設定 LLM 金鑰時由 LLM 生成，否則離線規則引擎。
 */
import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Bot, Check, Loader2, Plus, Save, Sparkles, Trash2, Upload, Wand2 } from 'lucide-react'

import { TemplateThumb } from '@/components/templates/TemplateGallery'
import { Badge, Button, Card, PageHeader, TextArea, TextInput } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { api, imageUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useQuery } from '@tanstack/react-query'
import type { FlowGraph, Overlay, Region, RunReport } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

interface RoiItem {
  region: Region
  hint: string
}

interface AgentResult {
  graph: FlowGraph
  rationale: string
  provider: 'llm' | 'rules'
  intent: string
  report: RunReport
}

const EXAMPLES = ['agent.exCount', 'agent.exDiameter', 'agent.exDefect', 'agent.exColor', 'agent.exBarcode'] as const

/** 已加入清單的 ROI 疊回影像（虛線框）。 */
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

export function AgentPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)
  const [image, setImage] = useState<{ ref: string; width: number; height: number; name: string } | null>(null)
  const [prompt, setPrompt] = useState('')
  const [rois, setRois] = useState<RoiItem[]>([])
  const [drawing, setDrawing] = useState<Region | null>(null)
  const [result, setResult] = useState<AgentResult | null>(null)
  const [feedback, setFeedback] = useState('')
  const [flowName, setFlowName] = useState('')
  const [busy, setBusy] = useState<'generate' | 'refine' | 'save' | null>(null)
  const [showOverlays, setShowOverlays] = useState(true)
  const info = useQuery({ queryKey: ['agent-info'], queryFn: () => api.get<{ llm: boolean; model: string }>('/vision/agent/info') })

  const overlays = useMemo<Overlay[]>(() => {
    const list: Overlay[] = rois.map((r, i) => regionToOverlay(r.region, `ROI${i + 1}`)).filter((o): o is Overlay => o !== null)
    if (result && showOverlays) list.push(...Object.values(result.report.nodes).flatMap((n) => n.overlays ?? []))
    return list
  }, [result, showOverlays, rois])

  async function onUpload(file: File | undefined) {
    if (!file) return
    const form = new FormData()
    form.append('image', file)
    try {
      const r = await api.postForm<{ ref: string; width: number; height: number; name: string }>('/vision/agent/image', form)
      setImage(r)
      setRois([])
      setDrawing(null)
      setResult(null)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  function addRoi() {
    if (!drawing) return
    setRois((list) => [...list, { region: drawing, hint: '' }])
    setDrawing(null)
  }

  const payloadRegions = useMemo(() => {
    const list = rois.map((r) => ({ region: r.region as unknown as Record<string, unknown>, hint: r.hint }))
    if (drawing) list.push({ region: drawing as unknown as Record<string, unknown>, hint: '' })
    return list
  }, [rois, drawing])

  async function generate() {
    if (!image) return
    setBusy('generate')
    try {
      const r = await api.post<AgentResult>('/vision/agent/generate', { ref: image.ref, prompt, regions: payloadRegions })
      setResult(r)
      setFeedback('')
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusy(null)
    }
  }

  async function refine() {
    if (!image || !result || !feedback.trim()) return
    setBusy('refine')
    try {
      const r = await api.post<AgentResult>('/vision/agent/refine', {
        ref: image.ref, prompt, regions: payloadRegions, graph: result.graph, feedback,
      })
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

  const report = result?.report
  const verdictTone: 'ok' | 'ng' | 'neutral' = report?.status === 'ok' ? 'ok' : report?.status === 'ng' ? 'ng' : 'neutral'
  const badgeTone = verdictTone === 'ok' ? 'ok' : verdictTone === 'ng' ? 'critical' : 'neutral'

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t('agent.title')}
        description={t('agent.subtitle')}
        actions={info.data ? (
          <Badge tone={info.data.llm ? 'brand' : 'neutral'}>
            <Bot size={12} /> {info.data.llm ? t('agent.providerLlm', { model: info.data.model }) : t('agent.providerRules')}
          </Badge>
        ) : null}
      />
      <div className="flex min-h-0 flex-1 gap-4">
        {/* 左：步驟 */}
        <div className="w-[380px] shrink-0 space-y-3 overflow-y-auto pb-4 pr-1">
          <Card className="space-y-2 p-3">
            <p className="text-xs font-semibold text-muted">1 · {t('agent.stepImage')}</p>
            <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => void onUpload(e.target.files?.[0])} />
            <Button className="w-full !justify-center" icon={<Upload size={14} />} onClick={() => fileRef.current?.click()}>
              {image ? t('agent.reupload') : t('agent.upload')}
            </Button>
            {image ? <p className="truncate text-xs text-muted">{image.name} · {image.width}×{image.height}px</p> : <p className="text-xs text-subtle">{t('agent.uploadHint')}</p>}
          </Card>

          <Card className="space-y-2 p-3">
            <p className="text-xs font-semibold text-muted">2 · {t('agent.stepRoi')}</p>
            <p className="text-xs text-subtle">{t('agent.drawHint')}</p>
            {rois.map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <Badge>{r.region.shape}</Badge>
                <TextInput className="flex-1 text-xs" placeholder={t('agent.roiHint')} value={r.hint}
                  onChange={(e) => setRois((list) => list.map((x, j) => (j === i ? { ...x, hint: e.target.value } : x)))} />
                <button type="button" className="btn-icon text-critical" aria-label={t('common.delete')}
                  onClick={() => setRois((list) => list.filter((_, j) => j !== i))}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            {drawing ? (
              <Button size="sm" className="w-full !justify-center" icon={<Plus size={13} />} onClick={addRoi}>
                {t('agent.addRoi')}（{drawing.shape}）
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
            <Button variant="primary" className="w-full !justify-center" disabled={!image || busy !== null}
              icon={busy === 'generate' ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              onClick={() => void generate()} data-testid="agent-generate">
              {result ? t('agent.regenerate') : t('agent.generate')}
            </Button>
          </Card>

          {result ? (
            <Card className="space-y-2 p-3" data-testid="agent-result">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-muted">4 · {t('agent.stepResult')}</p>
                <Badge tone={badgeTone}>{report?.status?.toUpperCase()} · {Math.round(report?.duration_ms ?? 0)} ms</Badge>
              </div>
              <TemplateThumb graph={result.graph} className="h-20 w-full rounded bg-surface-muted" />
              <p className="text-xs leading-relaxed text-muted">{result.rationale}</p>
              {report && Object.keys(report.outputs).length ? (
                <table className="w-full text-xs">
                  <tbody className="divide-y divide-line">
                    {Object.entries(report.outputs).map(([k, v]) => (
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

        {/* 右：影像＋ROI 圈選＋結果 overlay */}
        <div className="relative min-w-0 flex-1 overflow-hidden rounded-lg border border-line bg-surface">
          {image ? (
            <ImageViewer
              src={imageUrl(image.ref, 1600)}
              imageWidth={image.width}
              imageHeight={image.height}
              overlays={overlays}
              roi={drawing}
              onRoiChange={setDrawing}
              roiShapes={['rect', 'rotated_rect', 'circle', 'annulus', 'polygon', 'line']}
              toolbar
              className="h-full w-full"
              badge={report ? { text: `${report.status.toUpperCase()}`, tone: verdictTone } : null}
            />
          ) : (
            <button type="button" onClick={() => fileRef.current?.click()}
              className="flex h-full w-full flex-col items-center justify-center gap-3 text-muted hover:text-content">
              <Upload size={40} className="opacity-40" />
              <p className="text-sm">{t('agent.emptyState')}</p>
            </button>
          )}
          {rois.length ? (
            <div className="pointer-events-none absolute left-2 top-10 rounded bg-black/50 px-2 py-1 text-[11px] text-white/90">
              <Check size={11} className="mr-1 inline" />{t('agent.roiCount', { count: rois.length })}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
