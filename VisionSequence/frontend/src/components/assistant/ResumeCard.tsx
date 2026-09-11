/** 恢復卡只呈現摘要；正式規格仍由當前流程頁載入。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui'
import type { AssistantResume, AssistantWorkState, TaskDraft } from '@/lib/types'

export function draftProgress(drafts: TaskDraft[]): Pick<AssistantWorkState, 'drafts' | 'assumptions' | 'pending_questions'> {
  return { drafts,
    assumptions: drafts.flatMap((d) => Object.entries(d.fields).filter(([, v]) => v.status === 'assumed').map(([field, v]) => ({ task_id: d.task_id, field, value: v.value, note: v.note }))),
    pending_questions: drafts.flatMap((d) => Object.entries(d.fields).filter(([, v]) => v.status === 'missing').map(([field, v]) => ({ id: `${d.draft_id}:${field}`, text: v.note || field, kind: 'text' }))),
  }
}

export function ResumeCard({ resume, onContinue }: { resume: AssistantResume; onContinue: () => void }) {
  const { t } = useTranslation()
  const state = resume.work_state
  return <section className="space-y-2 rounded border border-line bg-surface-muted p-3 text-xs break-words" data-testid="assistant-resume">
    <h3 className="font-semibold">{t('assistant.resume.title')}</h3>
    {resume.flow_missing && <p role="alert">{t('assistant.resume.missing')}</p>}
    {resume.changed && <p role="status">{t('assistant.resume.changed')} {resume.diff_summary}</p>}
    {!!state.pending_questions?.length && <div><p>{t('assistant.resume.questions')}</p><ul className="list-inside list-disc">{state.pending_questions.map((q, i) => <li key={i}>{q.text}</li>)}</ul></div>}
    {!!state.assumptions?.length && <div><p>{t('assistant.resume.assumptions')}</p>{state.assumptions.map((a, i) => <p key={i}>{a.field}: {JSON.stringify(a.value)} {a.note}</p>)}</div>}
    {state.last_trial && <div><p>{t('assistant.resume.trial')}: {state.last_trial.status} · {state.last_trial.at}</p><p>{state.last_trial.summary}</p>{state.last_trial.per_task.map((task, i) => <p key={i}>{task.task_id}: {task.status} · {JSON.stringify(task.value)}</p>)}</div>}
    <Button size="xs" disabled={resume.flow_missing} onClick={onContinue}>{t('assistant.resume.continue')}</Button>
  </section>
}

export function ResumeQuestions({ questions, onAnswer, disabled = false }: { questions: NonNullable<AssistantWorkState['pending_questions']>; onAnswer: (text: string, id: string) => void; disabled?: boolean }) {
  const { t } = useTranslation()
  const [answers, setAnswers] = useState<Record<string, string>>({})
  return <div className="space-y-2" data-testid="assistant-resume-questions">{questions.map((q) => q.kind === 'confirm' ? <p key={q.id}>{t('assistant.approval.expired')}</p> : <form key={q.id} className="rounded border border-line p-2" onSubmit={(e) => { e.preventDefault(); if (!disabled && answers[q.id]?.trim()) onAnswer(`${q.text}: ${answers[q.id]}`, q.id) }}>
    <label className="block text-xs">{q.text}
      {q.kind === 'choice' && q.options?.length ? <select className="input mt-1 w-full" value={answers[q.id] ?? ''} onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}><option value="">{t('assistant.resume.choose')}</option>{q.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
        : <input className="input mt-1 w-full" type={q.kind === 'number' ? 'number' : 'text'} value={answers[q.id] ?? ''} onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })} />}
    </label><Button size="xs" type="submit" disabled={disabled || !answers[q.id]?.trim()}>{t('assistant.resume.answer')}</Button>
  </form>)}</div>
}
