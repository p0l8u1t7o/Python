/** 對話恢復走伺服器狀態；切換對話與延遲寫入不得互相覆蓋。 */
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installApiMock } from './apiMock'
import { renderPage } from './render'
import { AssistantDock } from '@/components/assistant/AssistantDock'
import { api } from '@/lib/api'
import { publishAssistantProgress, setAssistantContext } from '@/lib/assistantContext'
import i18n from '@/i18n'
import type { AssistantResume } from '@/lib/types'

installApiMock()
const restored: AssistantResume = { flow: { id: 1, name: 'Cup', version: 2, updated_at: 'today' }, changed: true, diff_summary: 'threshold 60 → 46',
  work_state: { version: 1, flow_id: 1, flow_version: 1, flow_updated_at: 'yesterday',
    pending_questions: [{ id: 'q', text: 'Which unit?', kind: 'text' }], assumptions: [], decisions: [], drafts: [],
    last_trial: { at: 'yesterday', status: 'ng', summary: 'Last trial failed', per_task: [] } } }
const row = { id: 7, flow_id: 1, flow_name: 'Cup', messages: [{ id: 'm', at: 1, role: 'user', text: 'Inspect the cup' }], work_state: restored.work_state }
let originalGet: ((path: string) => Promise<unknown>) | undefined
let originalPost: ((path: string, body?: unknown) => Promise<unknown>) | undefined
let originalPatch: ((path: string, body: unknown) => Promise<unknown>) | undefined

describe('assistant resume integration', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
    localStorage.clear(); sessionStorage.clear()
    localStorage.setItem('vs.assistant.v1', JSON.stringify({ open: true, sessionId: 7, messages: [] }))
    setAssistantContext({ kind: 'inspect', flowId: 1, flowName: 'Cup', getGraph: () => ({ nodes: [], edges: [] }) })
    originalGet = vi.mocked(api.get).getMockImplementation()
    originalPost = vi.mocked(api.post).getMockImplementation()
    originalPatch = vi.mocked(api.patch).getMockImplementation()
    vi.mocked(api.get).mockImplementation(async (path) => {
      if (path.endsWith('/7/resume')) return structuredClone(restored)
      if (path.endsWith('/chats/7')) return structuredClone(row)
      if (path.endsWith('/chats')) return { items: [{ ...row, title: 'Cup checks', count: 1 }] }
      return originalGet!(path)
    })
    vi.mocked(api.patch).mockResolvedValue(row)
    vi.mocked(api.post).mockImplementation(async (path, body) => path.endsWith('/agent/chat') ? { kind: 'help', answer: 'Review the current flow', provider: 'rules' } : originalPost!(path, body))
    vi.mocked(api.patch).mockClear(); vi.mocked(api.post).mockClear()
  })
  afterEach(() => {
    vi.mocked(api.get).mockImplementation(originalGet!)
    vi.mocked(api.post).mockImplementation(originalPost!)
    vi.mocked(api.patch).mockImplementation(originalPatch!)
    setAssistantContext(null)
  })
  it('loads a bound conversation, shows the diff, and sends answered questions with its id', async () => {
    renderPage(<AssistantDock />, { route: '/flows/1/inspect' })
    expect(await screen.findByTestId('assistant-resume')).toHaveTextContent('threshold 60 → 46')
    expect(screen.getByTestId('assistant-bound-flow')).toHaveTextContent('Cup')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.change(screen.getByLabelText('Which unit?'), { target: { value: 'px' } })
    fireEvent.click(screen.getByRole('button', { name: 'Answer' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vision/agent/chat', expect.objectContaining({ chat_id: 7, message: 'Which unit?: px' }), undefined, expect.any(AbortSignal)))
  })
  it('persists a successful save baseline and trial without graph or image data', async () => {
    renderPage(<AssistantDock />)
    await screen.findByTestId('assistant-resume')
    act(() => publishAssistantProgress(1, { flow_version: 3, flow_updated_at: 'saved', last_trial: { at: 'now', status: 'ok', summary: 'All passed', per_task: [] } }, 'Flow saved.'))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/vision/agent/chats/7', expect.objectContaining({ work_state: expect.objectContaining({ flow_version: 3, last_trial: expect.objectContaining({ status: 'ok' }) }) })), { timeout: 2500 })
    expect(JSON.stringify(vi.mocked(api.patch).mock.calls.at(-1)?.[1])).not.toContain('"graph"')
  })
  it('does not attach a late load to a newly opened conversation', async () => {
    let release!: (value: unknown) => void
    vi.mocked(api.get).mockImplementation(async (path) => path.endsWith('/7/resume') ? new Promise((resolve) => { release = resolve }) : path.endsWith('/chats/7') ? row : originalGet!(path))
    renderPage(<AssistantDock />)
    await waitFor(() => expect(release).toBeTypeOf('function'))
    fireEvent.click(screen.getByTestId('assistant-new-session'))
    await act(async () => { release(restored) })
    expect(screen.queryByTestId('assistant-resume')).toBeNull()
    expect(JSON.parse(localStorage.getItem('vs.assistant.v1')!).sessionId).toBeNull()
  })
  it('offers the most recent conversation for the current flow', async () => {
    localStorage.setItem('vs.assistant.v1', JSON.stringify({ open: true, messages: [] }))
    renderPage(<AssistantDock />)
    fireEvent.click(await screen.findByRole('button', { name: 'Continue the last conversation for this flow' }))
    expect(await screen.findByTestId('assistant-resume')).toBeTruthy()
  })
  it('keeps the final progress write when an earlier write is still pending', async () => {
    let release!: () => void
    vi.mocked(api.patch).mockImplementationOnce(async () => new Promise((resolve) => { release = () => resolve(row) }))
    renderPage(<AssistantDock />)
    await screen.findByTestId('assistant-resume')
    await waitFor(() => expect(release).toBeTypeOf('function'), { timeout: 2500 })
    act(() => publishAssistantProgress(1, { flow_version: 4, flow_updated_at: 'last' }))
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1100)); release() })
    await waitFor(() => expect(vi.mocked(api.patch).mock.calls.at(-1)?.[1]).toEqual(expect.objectContaining({ work_state: expect.objectContaining({ flow_version: 4 }) })))
  })
})
