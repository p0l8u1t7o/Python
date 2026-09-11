import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui'
import { api } from '@/lib/api'
import type { AgentJob, AgentQuestion } from '@/lib/agentJob'

export function ActionApproval({ jobId, question }: { jobId: string; question: AgentQuestion }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const answer = async (value: string) => {
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
  return <div className="space-y-2 rounded-lg border-2 border-warning bg-warning-soft p-3 text-xs" data-testid="agent-action-approval">
    <p className="font-semibold">{t('assistant.approval.title')}</p>
    <p className="break-words font-mono">{question.action}</p>
    <p className="whitespace-pre-wrap break-all">{question.summary || question.text}</p>
    {question.effects != null && <pre className="whitespace-pre-wrap break-all">{JSON.stringify(question.effects, null, 2)}</pre>}
    {question.risk && <p className="break-words">{question.risk}</p>}
    {error && <p role="alert" className="text-critical">{error}</p>}
    <div className="flex flex-wrap gap-2">
      {question.kind === 'confirm' ? <>
        <Button size="xs" variant="danger" disabled={busy} onClick={() => void answer('approve')}>{t('assistant.approval.approve')}</Button>
        <Button size="xs" disabled={busy} onClick={() => void answer('reject')}>{t('assistant.approval.reject')}</Button>
      </> : question.options?.map((option) => <Button key={option.value} size="xs" disabled={busy} onClick={() => void answer(option.value)}>{option.label}</Button>)}
    </div>
  </div>
}
