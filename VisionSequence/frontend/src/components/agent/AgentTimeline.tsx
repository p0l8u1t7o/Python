/**
 * 代理模式的步驟時間軸：回合／試跑計數、每個動作（名稱＋摘要＋耗時）、提問、完成或預算用完；執行中可取消。
 */
import { useTranslation } from 'react-i18next'
import { Bot, Check, HelpCircle, Info, Loader2, MessageSquare, Play, Square, TriangleAlert, Wrench } from 'lucide-react'

import { Badge, Button } from '@/components/ui'
import type { AgentJob, AgentStep } from '@/lib/agentJob'
import { ActionApproval } from '@/components/assistant/ActionApproval'

function StepIcon({ step }: { step: AgentStep }) {
  if (step.kind === 'error') return <TriangleAlert size={12} className="text-critical" />
  if (step.kind === 'assistant') return <Bot size={12} className="text-brand" />
  if (step.kind === 'question') return <HelpCircle size={12} className="text-warning" />
  if (step.kind === 'answer') return <MessageSquare size={12} className="text-brand" />
  if (step.kind === 'done') return <Check size={12} className="text-ok" />
  if (step.kind === 'budget' || step.kind === 'info') return <Info size={12} className="text-muted" />
  if (step.title === 'run_trial' || step.title === 'inspect_node' || step.title === 'auto_tune') return <Play size={12} className="text-brand" />
  return <Wrench size={12} className="text-muted" />
}

const TONE: Record<string, 'brand' | 'ok' | 'critical' | 'neutral'> = { running: 'brand', done: 'ok', budget: 'neutral', needs_input: 'brand', cancelled: 'neutral', error: 'critical' }

export function AgentTimeline({ job, steps, onCancel }: { job: AgentJob | null; steps: AgentStep[]; onCancel?: () => void }) {
  const { t } = useTranslation()
  if (!job) return null
  return (
    <div className="space-y-2" data-testid="agent-timeline">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {job.status === 'running' ? <Loader2 size={13} className="animate-spin text-brand" /> : null}
        <span className="font-semibold">{t('agent.jobTitle')}</span>
        <Badge tone={TONE[job.status] ?? 'neutral'}>{t(`agent.jobStatus.${job.status}`)}</Badge>
        <span className="tnum text-muted">{t('agent.jobProgress', { turns: job.turns, maxTurns: job.budget.max_turns, trials: job.trials, maxTrials: job.budget.max_trials })}</span>
        {job.status === 'running' && onCancel ? (
          <Button size="xs" variant="danger" icon={<Square size={11} />} onClick={onCancel} data-testid="agent-job-cancel">{t('agent.abort')}</Button>
        ) : null}
      </div>
      {job.fallback_reason ? <p className="text-[11px] text-warning">{job.fallback_reason}</p> : null}
      {job.error ? <p className="text-[11px] text-critical">{job.error}</p> : null}
      {job.status === 'needs_input' && job.questions.filter((q) => q.kind === 'confirm' || q.action).map((q) => <ActionApproval key={q.id} jobId={job.id} question={q} />)}
      <ol className="max-h-56 space-y-1 overflow-y-auto pr-1 text-[11px]">
        {steps.map((s) => (
          <li key={s.n} className="flex items-start gap-1.5">
            <span className="mt-0.5 shrink-0"><StepIcon step={s} /></span>
            <span className="min-w-0 flex-1">
              <span className={`font-mono ${s.kind === 'error' ? 'text-critical' : ''}`}>{s.title}</span>
              {s.detail ? <span className="ml-1 text-muted">{s.detail}</span> : null}
            </span>
            {typeof s.ms === 'number' ? <span className="tnum shrink-0 text-subtle">{s.ms} ms</span> : null}
          </li>
        ))}
        {steps.length === 0 && job.status === 'running' ? <li className="text-subtle">{t('agent.jobWaiting')}</li> : null}
      </ol>
    </div>
  )
}
