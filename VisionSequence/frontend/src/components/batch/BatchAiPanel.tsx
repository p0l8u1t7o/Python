/** 批次頁的 AI 助手：資料諮詢（問答）、請 AI 調整（單次或代理模式）、自動調參；調整結果直接成為新的一次執行。 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Bot, MessageSquare, Send, Sparkles, Square, Wand2 } from 'lucide-react'

import { AgentTimeline } from '@/components/agent/AgentTimeline'
import { Badge, Button } from '@/components/ui'
import { useAgentJob } from '@/lib/agentJob'
import { api } from '@/lib/api'
import { consultBatch, tuneBatch, type BatchRun, type ConsultResult, type Suggestion, type TuneResult } from '@/lib/batch'
import { errorMessage } from '@/lib/errors'
import type { FlowGraph } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

interface Turn {
  role: 'user' | 'assistant'
  text: string
  provider?: string
  suggestions?: Suggestion[]
  warnings?: string[]
  newRunId?: number | null
}

export function BatchAiPanel({ run, graph, hasLabels, onApply, onNewRun, onAutotune, busy }: {
  run: BatchRun | null
  graph: FlowGraph | null
  hasLabels: boolean
  onApply: (suggestions: Suggestion[]) => void
  onNewRun: (runId: number) => void
  onAutotune: () => void
  busy: boolean
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const info = useQuery({ queryKey: ['agent-info'], queryFn: () => api.get<{ llm: boolean; provider: string; model: string; mode?: string }>('/vision/agent/info') })
  const jobs = useAgentJob<TuneResult>()
  const agentic = Boolean(info.data?.llm && info.data?.mode === 'agentic')
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [instruction, setInstruction] = useState('')
  const [asking, setAsking] = useState(false)
  const [tuning, setTuning] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const ready = Boolean(run && run.status === 'done')

  const jobStatus = jobs.job?.status
  const jobId = jobs.job?.id
  useEffect(() => {
    const j = jobs.job
    if (!j || j.status === 'running') return
    if ((j.status === 'done' || j.status === 'budget') && j.result) {
      const r = j.result
      setTurns((list) => [...list, { role: 'assistant', text: r.rationale, provider: r.provider, warnings: r.warnings, newRunId: r.batch_run_id ?? null }])
      if (r.batch_run_id) onNewRun(r.batch_run_id)
    } else if (j.status === 'needs_input') {
      setTurns((list) => [...list, { role: 'assistant', text: t('agent.jobAnswerHint', { text: j.questions.map((q) => q.text).join('；') }) }])
    } else if (j.status === 'cancelled') {
      setTurns((list) => [...list, { role: 'assistant', text: t('agent.aborted') }])
    } else if (j.status === 'error') {
      setTurns((list) => [...list, { role: 'assistant', text: j.error || t('agent.jobStatus.error') }])
    }
    setTuning(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobStatus, jobId])

  async function ask(q = question.trim()) {
    if (!run || !q || asking) return
    setTurns((list) => [...list, { role: 'user', text: q }])
    setQuestion('')
    setAsking(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const r: ConsultResult = await consultBatch({ batch_run_id: run.id, question: q, graph }, controller.signal)
      setTurns((list) => [...list, { role: 'assistant', text: r.answer, provider: r.provider, suggestions: r.suggestions, warnings: r.warnings }])
    } catch (error) {
      if (!controller.signal.aborted) toast.error(errorMessage(error))
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setAsking(false)
    }
  }

  async function tune() {
    const text = instruction.trim()
    if (!run || !text || tuning) return
    setTurns((list) => [...list, { role: 'user', text }])
    setInstruction('')
    setTuning(true)
    if (jobs.waiting && jobs.job) {
      try {
        await jobs.answer(jobs.job.questions.map((q, i) => ({ id: q.id, answer: i === 0 ? text : '' })))
      } catch (error) {
        toast.error(errorMessage(error))
        setTuning(false)
      }
      return
    }
    if (agentic) {
      try {
        await jobs.start({ task: 'tune', batch_run_id: run.id, instruction: text, graph })
      } catch (error) {
        toast.error(errorMessage(error))
        setTuning(false)
      }
      return
    }
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const r = await tuneBatch({ batch_run_id: run.id, instruction: text, graph }, controller.signal)
      setTurns((list) => [...list, { role: 'assistant', text: r.rationale, provider: r.provider, warnings: r.warnings, newRunId: r.batch_run_id ?? null }])
      if (r.batch_run_id) onNewRun(r.batch_run_id)
    } catch (error) {
      if (!controller.signal.aborted) toast.error(errorMessage(error))
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setTuning(false)
    }
  }

  function abort() {
    if (jobs.running) void jobs.cancel()
    else abortRef.current?.abort()
  }

  const working = asking || tuning || jobs.running
  return (
    <div className="space-y-3" data-testid="batch-ai">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Bot size={14} className="text-brand" />
        <span className="font-semibold">{t('batchPage.ai.title')}</span>
        {info.data ? <Badge tone={info.data.llm ? 'brand' : 'neutral'}>{info.data.llm ? `${info.data.model}${agentic ? ` · ${t('agent.modeAgentic')}` : ''}` : t('agent.providerRules')}</Badge> : null}
        <span className="text-muted">{t('batchPage.ai.hint')}</span>
      </div>
      {!ready ? <p className="rounded bg-surface-muted px-2 py-1 text-xs text-muted">{t('batchPage.ai.needRun')}</p> : null}
      <div className="max-h-[38vh] space-y-2 overflow-y-auto rounded-lg border border-line p-2 text-xs" data-testid="batch-ai-turns">
        {turns.length === 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {(['exampleQ1', 'exampleQ2', 'exampleQ3'] as const).map((k) => (
              <button key={k} type="button" disabled={!ready || working} onClick={() => void ask(t(`batchPage.ai.${k}`))} className="rounded-full border border-line px-2 py-0.5 text-[11px] text-muted hover:bg-surface-muted">{t(`batchPage.ai.${k}`)}</button>
            ))}
          </div>
        ) : null}
        {turns.map((turn, i) => (
          <div key={i} className={`rounded-lg px-2.5 py-2 ${turn.role === 'user' ? 'ml-8 bg-brand-soft' : 'mr-4 bg-surface-muted'}`}>
            <p className="whitespace-pre-wrap leading-relaxed">{turn.text}</p>
            {turn.provider ? <p className="mt-1 text-[10px] text-subtle">{turn.provider}</p> : null}
            {turn.warnings?.length ? <ul className="mt-1 list-disc pl-4 text-[11px] text-warning">{turn.warnings.map((w, j) => <li key={j}>{w}</li>)}</ul> : null}
            {turn.suggestions?.length ? (
              <div className="mt-1.5 space-y-1">
                <p className="text-[11px] font-semibold">{t('batchPage.ai.suggestions')}</p>
                {turn.suggestions.map((s, j) => (
                  <p key={j} className="flex items-center gap-2 text-[11px]"><span className="font-mono">{s.label}.{s.key} → {String(s.value)}</span><span className="text-muted">{s.reason}</span>
                    <Button size="xs" onClick={() => onApply([s])}>{t('batchPage.ai.apply')}</Button></p>
                ))}
                {turn.suggestions.length > 1 ? <Button size="xs" variant="primary" onClick={() => onApply(turn.suggestions ?? [])}>{t('batchPage.ai.applyAll')}</Button> : null}
              </div>
            ) : null}
            {turn.newRunId ? <p className="mt-1 text-[11px] text-brand">{t('batchPage.ai.newRun', { id: turn.newRunId })}</p> : null}
          </div>
        ))}
        {jobs.job && (jobs.running || jobs.waiting) ? <AgentTimeline job={jobs.job} steps={jobs.steps} onCancel={abort} /> : null}
      </div>
      <div className="flex gap-1.5">
        <input className="input flex-1 !py-1.5 text-xs" placeholder={t('batchPage.ai.askPlaceholder')} value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void ask() }} disabled={!ready || working} data-testid="batch-ai-question" />
        {asking ? <Button size="sm" variant="danger" icon={<Square size={13} />} onClick={abort}>{t('agent.abort')}</Button> : <Button size="sm" icon={<MessageSquare size={13} />} disabled={!ready || !question.trim() || working} onClick={() => void ask()} data-testid="batch-ai-ask">{t('batchPage.ai.ask')}</Button>}
      </div>
      <div className="flex gap-1.5">
        <input className="input flex-1 !py-1.5 text-xs" placeholder={t('batchPage.ai.tunePlaceholder')} value={instruction} onChange={(e) => setInstruction(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void tune() }} disabled={!ready || (working && !jobs.waiting)} data-testid="batch-ai-instruction" />
        {tuning || jobs.running ? <Button size="sm" variant="danger" icon={<Square size={13} />} onClick={abort}>{t('agent.abort')}</Button> : (
          <>
            <Button size="sm" variant="primary" icon={<Send size={13} />} disabled={!ready || !instruction.trim() || working} onClick={() => void tune()} data-testid="batch-ai-tune">{t('batchPage.ai.tune')}</Button>
            <Button size="sm" icon={<Wand2 size={13} />} disabled={!ready || busy || !hasLabels} title={hasLabels ? t('batchPage.ai.autotuneHint') : t('batchPage.ai.noLabels')} onClick={onAutotune} data-testid="batch-ai-autotune">{t('batchPage.ai.autotune')}</Button>
          </>
        )}
      </div>
      <p className="flex items-center gap-1 text-[10px] text-subtle"><Sparkles size={10} /> {t('batchPage.ai.footer')}</p>
    </div>
  )
}
