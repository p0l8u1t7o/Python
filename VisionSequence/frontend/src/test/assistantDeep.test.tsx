/** 全域 AI 助手深度測試：強制模式、諮詢建議套用、調整產生新執行、代理模式改走背景工作、中斷、關閉時的未讀、跨流程套用擋下、API 錯誤、快速提示、對話上限、IME 組字不送出。 */
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { installApiMock } from './apiMock'
import { renderPage } from './render'

installApiMock()

import { AssistantDock } from '@/components/assistant/AssistantDock'
import { api } from '@/lib/api'
import { setAssistantContext } from '@/lib/assistantContext'

const GRAPH = { nodes: [{ id: 'blob', type: 'blob', params: { min_area: 10 } }], edges: [] }

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function open(route: string) {
  renderPage(<AssistantDock />, { route })
  fireEvent.click(screen.getByTestId('assistant-toggle'))
  return screen.getByTestId('assistant-input') as HTMLInputElement
}

function type(input: HTMLInputElement, text: string) {
  fireEvent.change(input, { target: { value: text } })
  fireEvent.click(screen.getByTestId('assistant-send'))
}

describe('AssistantDock deep', () => {
  beforeEach(() => {
    localStorage.clear()
    setAssistantContext(null)
    vi.mocked(api.post).mockReset()
    vi.mocked(api.post).mockImplementation(async (path: string) => (await import('./apiMock')).routes(path))
  })

  it('forced mode chip is sent in the payload', async () => {
    const input = open('/sources')
    fireEvent.click(screen.getByTestId('assistant-mode-help'))
    type(input, '把門檻改成 80')
    await waitFor(() => expect(screen.getAllByTestId('assistant-msg-assistant').length).toBe(1))
    expect((vi.mocked(api.post).mock.calls[0][1] as { mode: string }).mode).toBe('help')
  })

  it('consult reply offers suggestions that apply through the page callback', async () => {
    const applySuggestions = vi.fn()
    setAssistantContext({ kind: 'batch', flowId: 1, flowName: 'gate', batchRunId: 7, applySuggestions, getGraph: () => GRAPH })
    vi.mocked(api.post).mockResolvedValueOnce({ kind: 'consult', answer: '第 3 張 NG 是門檻太緊', provider: 'rules', suggestions: [{ node: 'rng', label: 'rng', key: 'low', value: 170, reason: '' }], warnings: ['離線'] })
    const input = open('/batch')
    expect(screen.getByTestId('assistant-mode-consult')).toBeTruthy()
    expect(screen.getByTestId('assistant-mode-tune')).toBeTruthy()
    type(input, '為什麼第 3 張 NG？')
    const msg = await screen.findByTestId('assistant-msg-assistant')
    expect(msg.textContent).toContain('門檻太緊')
    expect(msg.textContent).toContain('rng.low → 170')
    expect(msg.textContent).toContain('離線')
    fireEvent.click(msg.querySelector('button') as HTMLButtonElement)
    expect(applySuggestions).toHaveBeenCalledWith([{ node: 'rng', label: 'rng', key: 'low', value: 170, reason: '' }])
    expect((vi.mocked(api.post).mock.calls[0][1] as { context: { batch_run_id: number; graph: unknown } }).context.batch_run_id).toBe(7)
  })

  it('tune reply announces the new run and notifies the page', async () => {
    const onNewRun = vi.fn()
    setAssistantContext({ kind: 'batch', flowId: 1, batchRunId: 7, onNewRun })
    vi.mocked(api.post).mockResolvedValueOnce({ kind: 'tune', answer: 'low 100 → 170', provider: 'rules', batch_run_id: 9, result: {} })
    const input = open('/batch')
    type(input, '把 rng 的 low 改成 170')
    const msg = await screen.findByTestId('assistant-msg-assistant')
    expect(msg.textContent).toContain('#9')
    expect(onNewRun).toHaveBeenCalledWith(9)
  })

  it('agentic flag switches to a background job and shows its result', async () => {
    setAssistantContext({ kind: 'flow_editor', flowId: 1, flowName: 'f', getGraph: () => GRAPH, applyGraph: vi.fn() })
    vi.mocked(api.post)
      .mockResolvedValueOnce({ kind: 'edit', agentic: true, answer: '', provider: 'openai' })
      .mockResolvedValueOnce({ id: 'j1', task: 'edit', status: 'done', provider: 'openai', model: 'm', mode: 'agentic', turns: 1, trials: 1, tool_calls: 1, budget: { max_turns: 1, max_trials: 1, max_tool_calls: 1, deadline_s: 1 }, steps: [], step_next: 0, questions: [], error: '', fallback_reason: '', duration_s: 1,
        result: { graph: GRAPH, rationale: '代理改好了', provider: 'openai', changes: ['blob.min_area 10 → 40'], report: null, applied: true } })
    const input = open('/flows/1')
    type(input, '把 blob 的 min_area 改成 40')
    const msg = await screen.findByTestId('assistant-msg-assistant')
    expect(msg.textContent).toContain('代理改好了')
    expect(screen.getByTestId('assistant-apply')).toBeTruthy()
    const calls = vi.mocked(api.post).mock.calls
    expect(calls[1][0]).toBe('/vision/agent/jobs')
    expect((calls[1][1] as { task: string; instruction: string; graph: unknown }).task).toBe('edit')
    expect((calls[1][1] as { instruction: string }).instruction).toBe('把 blob 的 min_area 改成 40')
  })

  it('abort cancels the pending request and leaves a note', async () => {
    vi.mocked(api.post).mockImplementationOnce((...args: unknown[]) => new Promise((_, reject) => {
      const signal = args.find((a) => a instanceof AbortSignal) as AbortSignal
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    const input = open('/sources')
    type(input, '如何建立流程？')
    await waitFor(() => expect(screen.getByTestId('assistant-abort')).toBeTruthy())
    fireEvent.click(screen.getByTestId('assistant-abort'))
    const msg = await screen.findByTestId('assistant-msg-assistant')
    expect(msg.textContent).toContain('已中斷')
    expect(screen.getByTestId('assistant-send')).toBeTruthy()
  })

  it('counts unread replies that arrive while the dock is closed', async () => {
    const d = deferred<unknown>()
    vi.mocked(api.post).mockImplementationOnce(() => d.promise)
    const input = open('/sources')
    type(input, '如何建立流程？')
    fireEvent.click(screen.getByTestId('assistant-toggle'))
    expect(screen.queryByTestId('assistant-dock')).toBeNull()
    await act(async () => { d.resolve({ kind: 'help', answer: '答', provider: 'rules', sources: [], warnings: [] }) })
    await waitFor(() => expect(screen.getByTestId('assistant-toggle').textContent).toContain('1'))
    fireEvent.click(screen.getByTestId('assistant-toggle'))
    expect(screen.getByTestId('assistant-toggle').textContent).not.toContain('1')
    expect(screen.getByTestId('assistant-msg-assistant').textContent).toContain('答')
  })

  it('refuses to apply an edit that belongs to another flow', async () => {
    const applyGraph = vi.fn()
    setAssistantContext({ kind: 'flow_editor', flowId: 2, getGraph: () => GRAPH, applyGraph })
    localStorage.setItem('vs.assistant.v1', JSON.stringify({ open: true, messages: [{ id: 'e', role: 'assistant', text: '改好', at: 1, kind: 'edit', edit: { graph: GRAPH, changes: [], flowId: 1 } }] }))
    renderPage(<AssistantDock />, { route: '/flows/2' })
    fireEvent.click(screen.getByTestId('assistant-apply'))
    expect(applyGraph).not.toHaveBeenCalled()
    expect(await screen.findByText('請回到該流程的編輯器再套用此修改')).toBeTruthy()
    expect(screen.getByTestId('assistant-apply')).toBeTruthy()
  })

  it('shows API errors as an assistant message and recovers', async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error('供應商逾時'))
    const input = open('/sources')
    type(input, '如何建立流程？')
    const msg = await screen.findByTestId('assistant-msg-assistant')
    expect(msg.textContent).toContain('供應商逾時')
    expect((screen.getByTestId('assistant-input') as HTMLInputElement).disabled).toBe(false)
  })

  it('quick prompts send their text and disappear afterwards', async () => {
    open('/sources')
    const quick = screen.getAllByTestId('assistant-quick')
    expect(quick.length).toBe(3)
    const text = quick[0].textContent
    fireEvent.click(quick[0])
    await waitFor(() => expect(screen.getAllByTestId('assistant-msg-assistant').length).toBe(1))
    expect((vi.mocked(api.post).mock.calls[0][1] as { message: string }).message).toBe(text)
    expect(screen.queryByTestId('assistant-quick')).toBeNull()
  })

  it('keeps at most 60 messages in storage', async () => {
    const many = Array.from({ length: 60 }, (_, i) => ({ id: `m${i}`, role: i % 2 ? 'assistant' : 'user', text: `舊 ${i}`, at: i }))
    localStorage.setItem('vs.assistant.v1', JSON.stringify({ open: true, messages: many }))
    renderPage(<AssistantDock />, { route: '/sources' })
    type(screen.getByTestId('assistant-input') as HTMLInputElement, '新問題')
    // 原本 30 則助理訊息，最舊的一對（舊 0／舊 1）被擠掉、新回覆補上 → 仍是 30 則
    await waitFor(() => expect(screen.getAllByTestId('assistant-msg-assistant').length).toBe(30))
    await waitFor(() => {
      const stored = JSON.parse(localStorage.getItem('vs.assistant.v1') ?? '{}').messages as { text: string }[]
      expect(stored.length).toBe(60)
      expect(stored[0].text).toBe('舊 2')
      expect(stored[58].text).toBe('新問題')
    })
  })

  it('does not send on Enter while composing (IME)', () => {
    const input = open('/sources')
    fireEvent.change(input, { target: { value: '輸入中' } })
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
    expect(vi.mocked(api.post)).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(vi.mocked(api.post)).toHaveBeenCalledTimes(1)
  })
})
