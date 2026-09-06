/** 全域 AI 助手：路徑推脈絡、頁面登記脈絡、聊天視窗在假後端下問答（附參考連結）、編輯器脈絡下的修改與套用、對話持久化。 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { installApiMock } from './apiMock'
import { renderPage } from './render'

installApiMock()
vi.mock('@/lib/screenshot', () => ({ captureScreenshot: vi.fn(async () => 'data:image/jpeg;base64,QUJD'), base64Of: (s: string) => s.split(',')[1] ?? s }))

import { AssistantDock, contextPayload } from '@/components/assistant/AssistantDock'
import { clearActivity, logActivity, setShareEnabled, shareEnabled } from '@/lib/activity'
import { resetHints } from '@/lib/hints'
import { api } from '@/lib/api'
import { contextFromPath, getAssistantContext, setAssistantContext } from '@/lib/assistantContext'

describe('assistant context', () => {
  it('maps paths to a coarse context kind', () => {
    expect(contextFromPath('/').kind).toBe('dashboard')
    expect(contextFromPath('/batch?flow=1').kind).toBe('batch')
    expect(contextFromPath('/flows/3/golden').kind).toBe('golden')
    expect(contextFromPath('/settings').kind).toBe('page')
  })

  it('only sends the graph for editor, tool and batch contexts', () => {
    const graph = { nodes: [], edges: [] }
    expect(contextPayload({ kind: 'flow_editor', flowId: 1, getGraph: () => graph }).graph).toBe(graph)
    expect(contextPayload({ kind: 'sources', getGraph: () => graph }).graph).toBeNull()
    expect(contextPayload({ kind: 'batch', batchRunId: 7 }).batch_run_id).toBe(7)
  })
})

describe('AssistantDock', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    clearActivity()
    resetHints()
    setAssistantContext(null)
    vi.mocked(api.post).mockClear()
  })

  it('opens from the floating button and answers a platform question with references', async () => {
    renderPage(<AssistantDock />, { route: '/batch' })
    fireEvent.click(screen.getByTestId('assistant-toggle'))
    expect(screen.getByTestId('assistant-dock')).toBeTruthy()
    expect(screen.getByTestId('assistant-dock').textContent).toContain('Batch test')
    expect(screen.queryByTestId('assistant-mode-edit')).toBeNull()
    const input = screen.getByTestId('assistant-input') as HTMLInputElement
    fireEvent.change(input, { target: { value: '如何建立影像集？' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getAllByTestId('assistant-msg-assistant').length).toBe(1))
    const reply = screen.getByTestId('assistant-msg-assistant')
    expect(reply.textContent).toContain('新增影像集')
    const link = reply.querySelector('a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/docs/user-guide.html#batch')
    const body = vi.mocked(api.post).mock.calls[0][1] as { message: string; context: { kind: string } }
    expect(body.message).toBe('如何建立影像集？')
    expect(body.context.kind).toBe('batch')
    await waitFor(() => expect(JSON.parse(localStorage.getItem('vs.assistant.v1') ?? '{}').messages?.length).toBe(2))
  })

  it('uses the registered editor context and applies an edit to the canvas', async () => {
    const applyGraph = vi.fn()
    const graph = { nodes: [{ id: 'blob', type: 'blob', params: { min_area: 10 } }], edges: [] }
    setAssistantContext({ kind: 'flow_editor', flowId: 1, flowName: '示範流程', getGraph: () => graph, applyGraph })
    expect(getAssistantContext()?.flowName).toBe('示範流程')
    vi.mocked(api.post).mockResolvedValueOnce({ kind: 'edit', answer: 'blob.min_area 10 → 40', provider: 'rules', result: { graph: { ...graph, nodes: [{ id: 'blob', type: 'blob', params: { min_area: 40 } }] }, rationale: 'x', provider: 'rules', changes: ['blob.min_area 10 → 40'], report: null, applied: true } })
    renderPage(<AssistantDock />, { route: '/flows/1' })
    fireEvent.click(screen.getByTestId('assistant-toggle'))
    expect(screen.getByTestId('assistant-dock').textContent).toContain('示範流程')
    expect(screen.getByTestId('assistant-mode-edit')).toBeTruthy()
    const input = screen.getByTestId('assistant-input') as HTMLInputElement
    fireEvent.change(input, { target: { value: '把 blob 的 min_area 改成 40' } })
    fireEvent.click(screen.getByTestId('assistant-send'))
    await waitFor(() => expect(screen.getByTestId('assistant-apply')).toBeTruthy())
    const body = vi.mocked(api.post).mock.calls[0][1] as { context: { graph: unknown; flow_id: number } }
    expect(body.context.graph).toBe(graph)
    expect(body.context.flow_id).toBe(1)
    fireEvent.click(screen.getByTestId('assistant-apply'))
    expect(applyGraph).toHaveBeenCalledTimes(1)
    expect((applyGraph.mock.calls[0][0] as { nodes: { params: { min_area: number } }[] }).nodes[0].params.min_area).toBe(40)
    await waitFor(() => expect(screen.queryByTestId('assistant-apply')).toBeNull())
  })

  it('sends the page snapshot, activity trail and language, and the share toggle turns them off', async () => {
    clearActivity()
    setShareEnabled(true)
    setAssistantContext({ kind: 'sources', route: '/sources', describe: () => ({ selected: 'cam1', rows: 3 }) })
    logActivity('error', 'POST /vision/sources/test -> 422 no_frame', 'Nothing is listening')
    vi.mocked(api.post).mockResolvedValueOnce({ kind: 'help', answer: '最近一次錯誤…', provider: 'rules', sources: [{ title: 'Interface › Source library', page: 'ui', heading: 'Source library', url: '/sources', snippet: '', kind: 'ui' }] })
    renderPage(<AssistantDock />, { route: '/sources' })
    fireEvent.click(screen.getByTestId('assistant-toggle'))
    const input = screen.getByTestId('assistant-input') as HTMLInputElement
    fireEvent.change(input, { target: { value: '為什麼失敗？' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getAllByTestId('assistant-msg-assistant').length).toBe(1))
    const body = vi.mocked(api.post).mock.calls[0][1] as { context: { lang: string; page: Record<string, unknown> | null; activity: { kind: string; text: string }[]; route: string } }
    expect(body.context.lang).toBe('en')
    expect(body.context.route).toBe('/sources')
    expect(body.context.page).toMatchObject({ selected: 'cam1', rows: 3 })
    expect(body.context.activity.some((a) => a.kind === 'error' && a.text.includes('no_frame'))).toBe(true)
    expect(body.context.activity.some((a) => a.kind === 'nav' && a.text === '/sources')).toBe(true)
    // 介面地圖類的參考是站內連結
    expect(screen.getByTestId('assistant-ui-link').getAttribute('href')).toBe('/sources')
    // 關掉分享後只送頁面種類
    fireEvent.click(screen.getByTestId('assistant-share'))
    expect(shareEnabled()).toBe(false)
    vi.mocked(api.post).mockResolvedValueOnce({ kind: 'help', answer: 'ok', provider: 'rules', sources: [] })
    fireEvent.change(input, { target: { value: '再問一次' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getAllByTestId('assistant-msg-assistant').length).toBe(2))
    const second = vi.mocked(api.post).mock.calls[1][1] as { context: { page: unknown; activity: unknown[] } }
    expect(second.context.page).toBeNull()
    expect(second.context.activity).toEqual([])
    setShareEnabled(true)
  })

  it('renders action chips: navigate opens the page and tab, focus_node calls the editor', async () => {
    const focusNode = vi.fn()
    setAssistantContext({ kind: 'flow_editor', flowId: 1, flowName: 'F', focusNode })
    vi.mocked(api.post).mockResolvedValueOnce({ kind: 'help', answer: 'ok', provider: 'openai', sources: [],
      actions: [{ kind: 'navigate', to: '/integration/modbus-server', tab: 'connections', label: '前往從站連線' }, { kind: 'focus_node', node: 'blob', flow_id: 1, label: '看 blob' }],
      lookups: [{ name: 'list_connections', args: {} }, { name: 'list_plugins', args: {}, error: 'Not permitted' }] })
    renderPage(<AssistantDock />, { route: '/flows/1' })
    fireEvent.click(screen.getByTestId('assistant-toggle'))
    const input = screen.getByTestId('assistant-input') as HTMLInputElement
    fireEvent.change(input, { target: { value: '為什麼 PLC 連不上？' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getAllByTestId('assistant-action').length).toBe(2))
    expect(screen.getByTestId('assistant-lookups').textContent).toBe('Checked: list_connections, list_plugins (not permitted)')
    fireEvent.click(screen.getAllByTestId('assistant-action')[1])
    expect(focusNode).toHaveBeenCalledWith('blob')
    fireEvent.click(screen.getAllByTestId('assistant-action')[0])
    expect(sessionStorage.getItem('vs.integrationTab.modbus-server')).toBe('connections')
  })

  it('shows a proactive hint for a recognised failure and asks the assistant about it; screen text is attached on demand', async () => {
    document.body.innerHTML = ''
    renderPage(<AssistantDock />, { route: '/flows/1' })
    logActivity('error', 'POST /vision/flows/1/run -> 423 engine_locked', 'locked by integrator')
    await waitFor(() => expect(screen.getByTestId('assistant-toggle').textContent).toContain('1'))  // 未讀
    fireEvent.click(screen.getByTestId('assistant-toggle'))
    const card = screen.getByTestId('assistant-hint')
    expect(card.textContent).toContain('The engine is locked')
    expect(card.textContent).toContain('locked by integrator')
    // 同一種提示冷卻中不會再出現第二張
    fireEvent.click(screen.getByTestId('assistant-hint-dismiss'))
    expect(screen.queryByTestId('assistant-hint')).toBeNull()
    logActivity('error', 'POST /vision/flows/1/run -> 423 engine_locked')
    expect(screen.queryByTestId('assistant-hint')).toBeNull()
    // 另一種提示：詢問會把問題送給助手，並附上畫面文字
    logActivity('error', 'POST /comm/connections/test -> 422 connection_failed', 'Nothing is listening at 127.0.0.1:9001')
    await waitFor(() => expect(screen.getByTestId('assistant-hint')).toBeTruthy())
    fireEvent.click(screen.getByTestId('assistant-screen'))
    vi.mocked(api.post).mockResolvedValueOnce({ kind: 'help', answer: '先啟動接收程式', provider: 'rules', sources: [] })
    fireEvent.click(screen.getByTestId('assistant-hint-ask'))
    await waitFor(() => expect(screen.getAllByTestId('assistant-msg-assistant').length).toBe(1))
    const body = vi.mocked(api.post).mock.calls[0][1] as { message: string; context: { screen: string } }
    expect(body.message).toContain('Why did this fail')
    expect(body.message).toContain('Nothing is listening at 127.0.0.1:9001')
    expect(body.context.screen).toContain('buttons:')
    expect(screen.queryByTestId('assistant-hint')).toBeNull()
  })

  it('rates a help answer, and the memory panel lists, adds and deletes facts', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ kind: 'help', answer: '到來源庫', provider: 'openai', sources: [], memory_id: 5 })
    renderPage(<AssistantDock />, { route: '/sources' })
    fireEvent.click(screen.getByTestId('assistant-toggle'))
    const input = screen.getByTestId('assistant-input') as HTMLInputElement
    fireEvent.change(input, { target: { value: '如何建立影像來源？' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getByTestId('assistant-rate-up')).toBeTruthy())
    fireEvent.click(screen.getByTestId('assistant-rate-up'))
    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalledWith('/vision/agent/memory/5/rate', { rating: 1 }))
    await waitFor(() => expect(screen.getByTestId('assistant-msg-assistant').textContent).toContain('Noted'))
    fireEvent.click(screen.getByTestId('assistant-memory-toggle'))
    await waitFor(() => expect(screen.getAllByTestId('assistant-memory-fact').length).toBe(1))
    expect(screen.getByTestId('assistant-memory').textContent).toContain('產線 3 用流程「檢測 A」')
    expect(screen.getAllByTestId('assistant-memory-qa').length).toBe(1)
    fireEvent.change(screen.getByTestId('assistant-memory-input'), { target: { value: '我負責 B 線' } })
    fireEvent.click(screen.getByTestId('assistant-memory-add'))
    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalledWith('/vision/agent/memory', { text: '我負責 B 線' }))
    fireEvent.click(screen.getAllByLabelText('Delete')[0])
    await waitFor(() => expect(vi.mocked(api.delete)).toHaveBeenCalledWith('/vision/agent/memory/1'))
    fireEvent.click(screen.getByTestId('assistant-memory-toggle'))
    expect(screen.getByTestId('assistant-messages')).toBeTruthy()
  })

  it('attaches a screenshot to the next question when an LLM is configured', async () => {
    const original = vi.mocked(api.get).getMockImplementation()!
    vi.mocked(api.get).mockImplementation(async (path: string) => (path.startsWith('/vision/agent/info') ? { provider: 'openai', model: 'gpt-4o', llm: true, mode: 'single' } : original(path)))
    try {
      renderPage(<AssistantDock />, { route: '/sources' })
      fireEvent.click(screen.getByTestId('assistant-toggle'))
      await waitFor(() => expect((screen.getByTestId('assistant-shot') as HTMLButtonElement).disabled).toBe(false))
      fireEvent.click(screen.getByTestId('assistant-shot'))
      await waitFor(() => expect(screen.getByTestId('assistant-shot-chip')).toBeTruthy())
      vi.mocked(api.post).mockResolvedValueOnce({ kind: 'help', answer: '看到了', provider: 'openai', sources: [] })
      const input = screen.getByTestId('assistant-input') as HTMLInputElement
      fireEvent.change(input, { target: { value: '這頁在顯示什麼？' } })
      fireEvent.keyDown(input, { key: 'Enter' })
      await waitFor(() => expect(screen.getAllByTestId('assistant-msg-assistant').length).toBe(1))
      const body = vi.mocked(api.post).mock.calls[0][1] as { context: { screenshot: string } }
      expect(body.context.screenshot).toBe('QUJD')
      expect(screen.queryByTestId('assistant-shot-chip')).toBeNull()
      // 沒有 LLM 時相機停用
    } finally {
      vi.mocked(api.get).mockImplementation(original)
    }
    localStorage.clear()  // 第一個視窗把 open 存進 localStorage，清掉再開第二個
    renderPage(<AssistantDock />, { route: '/flows' })
    fireEvent.click(screen.getAllByTestId('assistant-toggle')[1])
    await waitFor(() => expect((screen.getAllByTestId('assistant-shot')[1] as HTMLButtonElement).disabled).toBe(true))
  })

  it('restores a persisted conversation and starts a new one', () => {
    localStorage.setItem('vs.assistant.v1', JSON.stringify({ open: true, sessionId: 7, messages: [{ id: 'a', role: 'user', text: '舊問題', at: 1 }, { id: 'b', role: 'assistant', text: '舊回答', at: 2 }] }))
    renderPage(<AssistantDock />, { route: '/sources' })
    expect(screen.getByTestId('assistant-dock').textContent).toContain('舊回答')
    fireEvent.click(screen.getByTestId('assistant-new-session'))
    expect(screen.queryByTestId('assistant-msg-user')).toBeNull()
    expect(JSON.parse(localStorage.getItem('vs.assistant.v1') ?? '{}').sessionId).toBeNull()
  })

  it('lists past conversations and deletes one', async () => {
    const original = vi.mocked(api.get).getMockImplementation()!
    vi.mocked(api.get).mockImplementation(async (path: string, params?: unknown) => (
      path.startsWith('/vision/agent/chats')
        ? { items: [{ id: 3, title: '怎麼標定？', count: 4, updated_at: '2026-09-06T10:00:00Z' }], limits: { chats: 50, messages: 60 } }
        : original(path, params)
    ))
    try {
      localStorage.clear()
      renderPage(<AssistantDock />, { route: '/flows' })
      fireEvent.click(screen.getAllByTestId('assistant-toggle')[0])
      fireEvent.click(await screen.findByTestId('assistant-history-toggle'))
      const row = await screen.findByTestId('assistant-session')
      expect(row.textContent).toContain('怎麼標定？')
      fireEvent.click(screen.getByTestId('assistant-session-delete'))
      await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/vision/agent/chats/3'))
    } finally {
      vi.mocked(api.get).mockImplementation(original)
    }
  })
})
