/** 恢復摘要與待確認值不能提升為已確認規格。 */
import { fireEvent, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installApiMock } from '@/test/apiMock'
import { renderPage } from '@/test/render'
import i18n from '@/i18n'
import { draftProgress, ResumeCard, ResumeQuestions } from './ResumeCard'
import type { AssistantResume, TaskDraft } from '@/lib/types'

installApiMock()
const draft: TaskDraft = { draft_id: 'd1', op: 'add', kind: 'count_objects', regions: [], fields: {
  min_count: { value: 5, status: 'assumed', source: 'rule', note: 'Review this count' },
  max_count: { value: null, status: 'missing', source: 'default', note: 'Provide the maximum' },
} }
const resume: AssistantResume = { changed: true, diff_summary: 'threshold 60 → 46', flow: { id: 1, name: 'Cup', version: 2, updated_at: 'today' },
  work_state: { ...draftProgress([draft]), last_trial: { at: 'yesterday', status: 'ng', summary: 'One task failed', per_task: [{ task_id: 't1', status: 'fail', value: 9.5 }] } } }

describe('resume progress', () => {
  beforeEach(async () => { await i18n.changeLanguage('en') })
  it('derives questions and assumptions without confirming or mutating drafts', () => {
    const before = JSON.stringify(draft)
    const state = draftProgress([draft])
    expect(state.assumptions?.[0].value).toBe(5)
    expect(state.pending_questions?.[0].text).toBe('Provide the maximum')
    expect(state.drafts?.[0].fields.min_count.status).toBe('assumed')
    expect(JSON.stringify(draft)).toBe(before)
  })
  it('shows the changed flow and prior trial and continues only on a click', () => {
    const next = vi.fn()
    renderPage(<ResumeCard resume={resume} onContinue={next} />)
    expect(screen.getByTestId('assistant-resume').textContent).toContain('threshold 60 → 46')
    expect(screen.getByText('One task failed')).toBeTruthy()
    expect(next).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(next).toHaveBeenCalledOnce()
  })
  it('disables continuation when the bound flow was deleted', () => {
    const next = vi.fn()
    renderPage(<ResumeCard resume={{ ...resume, flow: null, flow_missing: true }} onContinue={next} />)
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    expect(screen.getByRole('alert').textContent).toContain('deleted')
  })
  it('turns a pending question into an answerable card', () => {
    const answer = vi.fn()
    renderPage(<ResumeQuestions questions={[{ id: 'q', text: 'Choose a unit', kind: 'choice', options: [{ value: 'px', label: 'Pixels' }] }]} onAnswer={answer} />)
    expect(screen.getByRole('button', { name: 'Answer' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Choose a unit'), { target: { value: 'px' } })
    fireEvent.click(screen.getByRole('button', { name: 'Answer' }))
    expect(answer).toHaveBeenCalledWith('Choose a unit: px', 'q')
  })
  it('keeps answering disabled until the destination flow is ready', () => {
    const answer = vi.fn()
    renderPage(<ResumeQuestions disabled questions={[{ id: 'q', text: 'Which unit?', kind: 'text' }]} onAnswer={answer} />)
    fireEvent.change(screen.getByLabelText('Which unit?'), { target: { value: 'px' } })
    expect(screen.getByRole('button', { name: 'Answer' })).toBeDisabled()
    fireEvent.submit(screen.getByLabelText('Which unit?').closest('form')!)
    expect(answer).not.toHaveBeenCalled()
  })
  it.each(['en', 'zh-Hant', 'zh-Hans'])('uses translated resume controls in %s', async (lang) => {
    await i18n.changeLanguage(lang)
    renderPage(<ResumeCard resume={resume} onContinue={() => {}} />)
    expect(screen.getByTestId('assistant-resume').textContent).not.toMatch(/assistant\.resume\./)
    expect(screen.getByRole('button', { name: i18n.t('assistant.resume.continue') })).toBeTruthy()
  })
})
