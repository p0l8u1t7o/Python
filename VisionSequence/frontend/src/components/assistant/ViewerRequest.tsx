/**
 * 助手 ↔ 影像視窗互動協定（PRODUCT-DIRECTION v2 P4）：代理工作的 ask_user 題型 roi／crop／preview 顯示成一張卡——
 * roi／crop 請使用者在目前頁面的影像上畫區域（頁面經 assistantContext.requestRegion 進入畫圖模式），送出的是標準 ROI dict；
 * preview 請頁面顯示某個節點的預覽（assistantContext.showPreview），看過就回「shown」。沒有登記影像視窗的頁面只能提示去有影像的頁面。
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Eye, PenLine, Send } from 'lucide-react'

import { Button } from '@/components/ui'
import { api } from '@/lib/api'
import type { AgentJob, AgentQuestion } from '@/lib/agentJob'
import { useAssistantContext } from '@/lib/assistantContext'
import type { Region } from '@/lib/types'

export const VIEWER_KINDS = new Set<AgentQuestion['kind']>(['roi', 'crop', 'preview'])

/** 區域的一行摘要（形狀＋主要座標，整數） */
export function regionSummary(region: Region | null): string {
  if (!region) return ''
  const r = region as unknown as Record<string, unknown>
  const parts = Object.entries(r).filter(([key, value]) => key !== 'shape' && typeof value === 'number').map(([key, value]) => `${key} ${Math.round(value as number)}`)
  return `${String(r.shape)}${parts.length ? ' · ' + parts.slice(0, 5).join(', ') : ''}`
}

export function ViewerRequest({ jobId, question }: { jobId: string; question: AgentQuestion }) {
  const { t } = useTranslation()
  const ctx = useAssistantContext()
  const [region, setRegion] = useState<Region | null>(null)
  const [drawing, setDrawing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const canDraw = Boolean(ctx?.requestRegion)
  const canPreview = Boolean(ctx?.showPreview)
  const kind = question.kind

  async function send(value: string) {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const job = await api.post<AgentJob>(`/vision/agent/jobs/${jobId}/answer`, { answers: [{ id: question.id, value }] })
      window.dispatchEvent(new CustomEvent('vs:agent-action-answer', { detail: job }))
    } catch (e) {
      setError(e instanceof Error ? e.message : t('assistant.approval.failed'))
      setBusy(false)
    }
  }

  async function draw() {
    if (!ctx?.requestRegion || drawing) return
    setDrawing(true)
    try {
      const drawn = await ctx.requestRegion(question.shapes)
      if (drawn) setRegion(drawn)
    } finally {
      setDrawing(false)
    }
  }

  async function show() {
    if (busy) return
    if (ctx?.showPreview) {
      setBusy(true)
      try {
        await ctx.showPreview({ node: question.node, port: question.port, image: question.image })
      } catch (e) {
        setError(e instanceof Error ? e.message : t('assistant.approval.failed'))
        setBusy(false)
        return
      }
      setBusy(false)
    }
    await send('shown')
  }

  const title = t(kind === 'roi' ? 'assistant.viewer.roiTitle' : kind === 'crop' ? 'assistant.viewer.cropTitle' : 'assistant.viewer.previewTitle')
  return (
    <div className="space-y-2 rounded-lg border-2 border-brand/50 bg-brand-soft/40 p-3 text-xs" data-testid={`agent-viewer-request-${kind}`}>
      <p className="font-semibold">{title}</p>
      <p className="whitespace-pre-wrap break-words">{question.text}</p>
      {question.hint ? <p className="text-[11px] text-muted">{question.hint}</p> : null}
      {kind === 'preview' ? (
        <div className="flex flex-wrap gap-2">
          <Button size="xs" variant="primary" icon={<Eye size={12} />} disabled={busy} onClick={() => void show()} data-testid="agent-viewer-show">{t(canPreview ? 'assistant.viewer.show' : 'assistant.viewer.shown')}</Button>
        </div>
      ) : (
        <>
          {region ? <p className="rounded bg-surface px-2 py-1 font-mono text-[11px]" data-testid="agent-viewer-region">{regionSummary(region)}</p> : null}
          {!canDraw ? <p className="text-[11px] text-warning" data-testid="agent-viewer-noviewer">{t('assistant.viewer.noViewer')}</p> : null}
          <div className="flex flex-wrap gap-2">
            <Button size="xs" variant={region ? 'secondary' : 'primary'} icon={<PenLine size={12} />} disabled={!canDraw || drawing || busy} loading={drawing} onClick={() => void draw()} data-testid="agent-viewer-draw">
              {t(region ? 'assistant.viewer.redraw' : 'assistant.viewer.draw')}
            </Button>
            <Button size="xs" variant="primary" icon={<Send size={12} />} disabled={!region || busy} onClick={() => void send(JSON.stringify(region))} data-testid="agent-viewer-send">{t('assistant.viewer.send')}</Button>
            {question.optional ? <Button size="xs" disabled={busy} onClick={() => void send('')} data-testid="agent-viewer-skip">{t('assistant.viewer.skip')}</Button> : null}
          </div>
        </>
      )}
      {error ? <p role="alert" className="text-critical">{error}</p> : null}
    </div>
  )
}
