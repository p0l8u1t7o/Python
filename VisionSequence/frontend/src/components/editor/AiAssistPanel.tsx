/**
 * 編輯器右側「AI」分頁：用一句話請 AI 助手修改目前流程（改參數／啟停／增刪節點）。
 * 送 POST /vision/agent/edit（帶目前畫布 graph 與最近一次影像 ref 供試跑），回來的 graph 由使用者按「套用」寫回畫布。
 * 沒接 LLM 時走離線指令解析（支援的句型見面板提示）。
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Bot, Check, Loader2, Send, Square } from 'lucide-react'

import { AgentTimeline } from '@/components/agent/AgentTimeline'
import { Badge, Button, StatusBadge } from '@/components/ui'
import { useAgentJob } from '@/lib/agentJob'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import type { FlowGraph, RunReport } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

interface EditResult {
  graph: FlowGraph
  rationale: string
  provider: string
  changes: string[]
  report: RunReport | null
  applied: boolean
}

interface Turn {
  role: 'user' | 'assistant'
  text: string
  result?: EditResult
}

export interface AiAssistPanelProps {
  /** 目前畫布的圖 */
  graph: () => FlowGraph
  /** 最近一次執行的來源影像 ref（有就順便試跑） */
  imageRef: string | null
  onApply: (graph: FlowGraph, rationale: string) => void
  execLocked: boolean
}

export function AiAssistPanel({ graph, imageRef, onApply, execLocked }: AiAssistPanelProps) {
  const { t } = useTranslation()
  const toast = useToast()
  const info = useQuery({ queryKey: ['agent-info'], queryFn: () => api.get<{ llm: boolean; provider: string; model: string; mode?: string }>('/vision/agent/info') })
  const jobs = useAgentJob<EditResult>()
  const agentic = Boolean(info.data?.llm && info.data?.mode === 'agentic')
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  function abort() {
    if (jobs.running) {
      void jobs.cancel()
      return
    }
    abortRef.current?.abort()
  }

  // 背景工作結束 → 助手回合
  const jobStatus = jobs.job?.status
  const jobId = jobs.job?.id
  useEffect(() => {
    const j = jobs.job
    if (!j || j.status === 'running') return
    if (j.status === 'done' || j.status === 'budget') {
      if (j.result) setTurns((list) => [...list, { role: 'assistant', text: j.result!.rationale, result: j.result! }])
    } else if (j.status === 'needs_input') {
      setTurns((list) => [...list, { role: 'assistant', text: t('agent.jobAnswerHint', { text: j.questions.map((q) => q.text).join('；') }) }])
    } else if (j.status === 'cancelled') {
      setTurns((list) => [...list, { role: 'assistant', text: t('agent.aborted') }])
    } else if (j.status === 'error') {
      setTurns((list) => [...list, { role: 'assistant', text: j.error || t('agent.jobStatus.error') }])
    }
    setBusy(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobStatus, jobId])

  async function send() {
    const instruction = text.trim()
    if (!instruction || busy) return
    setTurns((list) => [...list, { role: 'user', text: instruction }])
    setText('')
    setBusy(true)
    if (jobs.waiting && jobs.job) {
      const qs = jobs.job.questions
      try {
        await jobs.answer(qs.map((q, i) => ({ id: q.id, answer: i === 0 ? instruction : '' })))
      } catch (error) {
        toast.error(errorMessage(error))
        setBusy(false)
      }
      return
    }
    if (agentic) {
      try {
        await jobs.start({ task: 'edit', graph: graph(), instruction, images: imageRef ? [imageRef] : [] })
      } catch (error) {
        toast.error(errorMessage(error))
        setTurns((list) => [...list, { role: 'assistant', text: errorMessage(error) }])
        setBusy(false)
      }
      return
    }
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const r = await api.post<EditResult>('/vision/agent/edit', { graph: graph(), instruction, image_ref: imageRef ?? '' }, undefined, controller.signal)
      setTurns((list) => [...list, { role: 'assistant', text: r.rationale, result: r }])
    } catch (error) {
      if (controller.signal.aborted) {
        setTurns((list) => [...list, { role: 'assistant', text: t('agent.aborted') }])
      } else {
        toast.error(errorMessage(error))
        setTurns((list) => [...list, { role: 'assistant', text: errorMessage(error) }])
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full flex-col" data-testid="ai-panel">
      <div className="space-y-1 border-b border-line p-3">
        <div className="flex items-center gap-2">
          <Bot size={14} className="text-brand" />
          <span className="text-xs font-semibold">{t('agent.editorTitle')}</span>
          {info.data ? <Badge tone={info.data.llm ? 'brand' : 'neutral'}>{info.data.llm ? info.data.model : t('agent.providerRules')}</Badge> : null}
        </div>
        <p className="text-[11px] leading-relaxed text-muted">{info.data?.llm ? t('agent.editorHintLlm') : t('agent.editorHintRules')}</p>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3 text-xs">
        {turns.length === 0 ? <p className="text-subtle">{t('agent.editorEmpty')}</p> : null}
        {turns.map((turn, i) => (
          <div key={i} className={`rounded-lg px-2.5 py-2 ${turn.role === 'user' ? 'ml-6 bg-brand-soft' : 'mr-4 bg-surface-muted'}`}>
            <p className="whitespace-pre-wrap leading-relaxed">{turn.text}</p>
            {turn.result?.applied ? (
              <div className="mt-2 space-y-1.5">
                {turn.result.changes.length ? (
                  <ul className="list-disc pl-4 text-[11px] text-muted">
                    {turn.result.changes.map((c, j) => <li key={j}>{c}</li>)}
                  </ul>
                ) : null}
                <div className="flex items-center gap-2">
                  {turn.result.report ? <StatusBadge status={turn.result.report.status} /> : null}
                  <Button size="xs" variant="primary" icon={<Check size={12} />} onClick={() => onApply(turn.result!.graph, turn.result!.rationale)} data-testid="ai-apply">
                    {t('agent.apply')}
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        ))}
        {jobs.job && (jobs.running || jobs.waiting) ? (
          <div className="rounded-lg border border-line p-2"><AgentTimeline job={jobs.job} steps={jobs.steps} onCancel={abort} /></div>
        ) : null}
        {busy && !jobs.running ? (
          <p className="flex items-center gap-2 text-subtle">
            <Loader2 size={12} className="animate-spin" /> {t('agent.thinking')}
            <button type="button" onClick={abort} className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-[11px] text-critical hover:bg-surface-muted" data-testid="ai-abort"><Square size={10} /> {t('agent.abort')}</button>
          </p>
        ) : null}
      </div>
      <div className="flex gap-1.5 border-t border-line p-2">
        <input className="input flex-1 !py-1.5 text-xs" placeholder={t('agent.instructionPlaceholder')} value={text}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void send() }}
          disabled={busy || execLocked} data-testid="ai-input" />
        <Button size="sm" variant="primary" icon={<Send size={13} />} disabled={!text.trim() || busy || execLocked} onClick={() => void send()} data-testid="ai-send">
          {t('agent.send')}
        </Button>
      </div>
    </div>
  )
}
