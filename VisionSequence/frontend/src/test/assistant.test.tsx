/** 全域 AI 助手：路徑推脈絡、頁面登記脈絡、聊天視窗在假後端下問答（附參考連結）、編輯器脈絡下的修改與套用、對話持久化。 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { installApiMock } from './apiMock'
import { renderPage } from './render'

installApiMock()

import { AssistantDock, contextPayload } from '@/components/assistant/AssistantDock'
import { clearActivity, logActivity, setShareEnabled, shareEnabled } from '@/lib/activity'
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

  it('restores a persisted conversation', () => {
    localStorage.setItem('vs.assistant.v1', JSON.stringify({ open: true, messages: [{ id: 'a', role: 'user', text: '舊問題', at: 1 }, { id: 'b', role: 'assistant', text: '舊回答', at: 2 }] }))
    renderPage(<AssistantDock />, { route: '/sources' })
    expect(screen.getByTestId('assistant-dock').textContent).toContain('舊回答')
    fireEvent.click(screen.getByTestId('assistant-clear'))
    expect(screen.queryByTestId('assistant-msg-user')).toBeNull()
  })
})
