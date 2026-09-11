/** 核准必須來自明確按鈕，送出中不得重複執行。 */
import { fireEvent, render as renderPage, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import { api } from '@/lib/api'
import { ActionApproval } from './ActionApproval'
import { ResumeQuestions } from './ResumeCard'

vi.mock('@/lib/api', () => ({ api: { post: vi.fn() } }))
const question = { id: 'approval1', text: 'Approve?', kind: 'confirm' as const, action: 'write_output', summary: 'Write DO1 = 1', effects: { connection: 7 }, risk: 'Changes equipment output.' }

describe('action approval', () => {
  beforeEach(async () => { vi.mocked(api.post).mockReset(); await i18n.changeLanguage('en') })
  it('shows action, effects and risk without sending anything automatically', () => {
    const post = vi.mocked(api.post)
    renderPage(<ActionApproval jobId="job1" question={question} />)
    expect(screen.getByText('Write DO1 = 1')).toBeTruthy()
    expect(screen.getByText('Changes equipment output.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Continue' })).toBeNull()
    expect(post).not.toHaveBeenCalled()
  })
  it.each(['approve', 'reject'])('sends %s only for the displayed question id', async (value) => {
    const post = vi.mocked(api.post).mockResolvedValue({ id: 'job1', status: 'running' })
    const updated = vi.fn()
    window.addEventListener('vs:agent-action-answer', updated)
    renderPage(<ActionApproval jobId="job1" question={question} />)
    fireEvent.click(screen.getByRole('button', { name: value === 'approve' ? 'Approve' : 'Reject' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/vision/agent/jobs/job1/answer', { answers: [{ id: 'approval1', value }] }))
    await waitFor(() => expect(updated).toHaveBeenCalledOnce())
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
    window.removeEventListener('vs:agent-action-answer', updated)
  })
  it('shows an answer failure and allows an explicit retry', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('Connection interrupted'))
    renderPage(<ActionApproval jobId="job1" question={question} />)
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Connection interrupted'))
    expect(screen.getByRole('button', { name: 'Approve' })).not.toBeDisabled()
  })
  it('does not restore an old confirmation as a normal question', () => {
    const answer = vi.fn()
    renderPage(<ResumeQuestions questions={[question]} onAnswer={answer} />)
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Answer' })).toBeNull()
    expect(answer).not.toHaveBeenCalled()
  })
})
