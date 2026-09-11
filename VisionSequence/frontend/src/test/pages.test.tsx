/**
 * 頁面 smoke 測試：每頁在假後端下都要能 render 出標題／主要區塊，且不丟例外。
 * 抓的是「改了型別或 hook 卻沒開過那一頁」的回歸；互動細節另寫。
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { FLOW, INSPECT_GRAPH, INSPECT_KINDS, installApiMock } from './apiMock'
import { renderPage } from './render'
import { expandOnDrop } from '@/lib/nodeGroups'
import { AuthProvider } from '@/providers/AuthProvider'
import { ThemeProvider } from '@/providers/ThemeProvider'
import { ToastProvider } from '@/providers/ToastProvider'

installApiMock()

vi.mock('@/lib/flowStream', () => ({ useLockEvents: () => {}, useFlowEvents: () => {}, useFlowStream: () => ({ events: [], seq: 0, connected: false, runningIds: new Set() }), subscribeStream: () => () => {}, setStreamClient: () => {} }))

function renderDataPage(ui: React.ReactElement, route: string, path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  const router = createMemoryRouter([{ path, element: ui }], { initialEntries: [route] })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>
            <RouterProvider router={router} />
          </AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe('pages render (smoke)', () => {
  it('NotesPage renders shared notes and their detail', async () => {
    const { NotesPage } = await import('@/pages/NotesPage')
    renderPage(<NotesPage />, { route: '/notes?note=1' })
    expect(await screen.findByText('A diffuser reduces reflections near the rim.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeInTheDocument()
  })
  it('shows task proposals from the assistant in inspect context', async () => {
    const { AssistantDock } = await import('@/components/assistant/AssistantDock')
    const { api } = await import('@/lib/api')
    const { setAssistantContext } = await import('@/lib/assistantContext')
    localStorage.clear()
    setAssistantContext({ kind: 'inspect', flowId: 1, getGraph: () => INSPECT_GRAPH })
    vi.mocked(api.post).mockResolvedValueOnce({ kind: 'tasklist', drafts: [{ draft_id: 'count', kind: 'count_objects', op: 'add', fields: { min_count: { value: 5, status: 'assumed', source: 'llm', note: '' } }, regions: [] }] })
    const view = renderPage(<AssistantDock />, { route: '/flows/1/inspect' })
    fireEvent.click(screen.getByTestId('assistant-toggle'))
    fireEvent.change(screen.getByTestId('assistant-input'), { target: { value: 'add count 5' } })
    fireEvent.keyDown(screen.getByTestId('assistant-input'), { key: 'Enter' })
    expect(await screen.findByTestId('assistant-tasklist')).toHaveTextContent('Assumption')
    const call = vi.mocked(api.post).mock.calls.find(([path]) => path === '/vision/agent/chat')
    expect(call?.[1]).toMatchObject({ context: { kind: 'inspect', graph: INSPECT_GRAPH } })
    view.unmount(); setAssistantContext(null); localStorage.clear()
  })
  it.each(INSPECT_KINDS.filter((item) => item.kind !== 'measure_diameter'))('offers $kind and renders its active form', async (kind) => {
    const { InspectPage } = await import('@/pages/InspectPage')
    const { clearSession } = await import('@/lib/flowDraft')
    clearSession(6)
    renderDataPage(<InspectPage />, '/flows/6/inspect', '/flows/:flowId/inspect')
    const add = await screen.findByTestId('inspect-add')
    await waitFor(() => expect(add).toBeEnabled())
    fireEvent.click(add)
    expect(await screen.findByTestId(`inspect-kind-${kind.kind}`)).toHaveTextContent(kind.label)
    fireEvent.click(screen.getByTestId(`inspect-kind-${kind.kind}`))
    const form = screen.getByTestId('inspect-form')
    expect(await within(form).findByRole('heading', { name: kind.label })).toBeInTheDocument()
    // 精靈分步顯示：區域那一步與規格那一步的欄位加起來要涵蓋所有不帶條件的欄位
    const seen = new Set<string>()
    const collect = () => form.querySelectorAll('[data-field]').forEach((el) => seen.add(el.getAttribute('data-field') ?? ''))
    collect()
    if (kind.kind === 'inspect_edge_defect') expect(screen.getByTestId('inspect-geometry-source')).toBeInTheDocument()
    if (screen.queryByTestId('inspect-next')) { fireEvent.click(screen.getByTestId('inspect-next')); collect() }
    expect(screen.getByTestId('inspect-create')).toBeInTheDocument()
    for (const field of kind.fields.filter((field) => !field.visible_when)) expect(seen.has(field.key), field.key).toBe(true)
    if (kind.kind === 'inspect_edge_defect') {
      fireEvent.change(within(form).getByLabelText('Method'), { target: { value: 'freeform' } })
      fireEvent.click(screen.getByTestId('inspect-back'))
      expect(await within(form).findByRole('button', { name: 'Teach contour from current image' })).toBeDisabled()
      expect(screen.queryByTestId('inspect-geometry-source')).not.toBeInTheDocument()
    }
  })
  it.each([
    ['managed_edge_missing', 'tol', 'd_tol', 'An internal task connection is missing.', 'measure_diameter'],
    ['unexpected_node', 'extra', 'extra', 'An extra step was added to this task.', 'measure_diameter'],
    ['schema_version_unknown', 'find', 'd_find', 'This task schema version is not supported.', 'future_task'],
  ])('InspectPage hides custom fields and links %s to its problem node', async (code, role, nodeId, message, kind) => {
    const { InspectPage } = await import('@/pages/InspectPage')
    const { api } = await import('@/lib/api')
    const { clearSession, setDraft } = await import('@/lib/flowDraft')
    const { readInspection } = await import('@/lib/queries')
    clearSession(6)
    const graph = structuredClone(INSPECT_GRAPH)
    if (code === 'unexpected_node') graph.nodes.push({ id: 'extra', type: 'blur', params: {} })
    if (code === 'managed_edge_missing') graph.edges = graph.edges.filter((edge) => edge.target !== 'd_tol')
    const response = await readInspection(INSPECT_GRAPH)
    response.tasks[0] = { ...response.tasks[0], kind, custom: true, reasons: [{ code, role, node_id: nodeId, detail: 'Server detail' }] }
    setDraft(6, { baseVersion: 1, graph, name: 'Custom flow', description: '', dirty: true })
    const original = vi.mocked(api.post).getMockImplementation()!
    await vi.mocked(api.post).withImplementation(async (path, body) => path === '/vision/inspect/read' ? response : original(path, body), async () => {
      renderDataPage(<InspectPage />, '/flows/6/inspect', '/flows/:flowId/inspect')
      expect(await screen.findByTestId('inspect-custom')).toBeInTheDocument()
      expect(within(screen.getByTestId('inspect-custom-reasons')).getByText(message)).toHaveAttribute('href', `/flows/6?focus=${nodeId}`)
      expect(screen.getByRole('link', { name: 'Open in advanced flow' })).toHaveAttribute('href', `/flows/6?focus=${nodeId}`)
      expect(screen.queryByLabelText('Nominal')).not.toBeInTheDocument()
      expect(screen.queryByText('Server detail')).not.toBeInTheDocument()
    })
  })

  it('InspectPage rereads a returned advanced draft and retains stale readings until rerun', async () => {
    const { InspectPage } = await import('@/pages/InspectPage')
    const { api } = await import('@/lib/api')
    const { clearSession, getSession, setDraft } = await import('@/lib/flowDraft')
    clearSession(6)
    const first = renderDataPage(<InspectPage />, '/flows/6/inspect', '/flows/:flowId/inspect')
    await screen.findByTestId('inspect-task')
    fireEvent.click(screen.getByTestId('inspect-run'))
    await waitFor(() => expect(screen.getByTestId('inspect-reading')).toHaveTextContent('99.9'))
    first.unmount()
    const draft = structuredClone(getSession(6).draft!)
    draft.graph.nodes[1].position = { x: 800, y: 50 }
    draft.graph.nodes[1].params!.smoothing = 7
    draft.graph.nodes[2].params!.upper_tol = 5
    draft.dirty = true
    setDraft(6, draft)
    renderDataPage(<InspectPage />, '/flows/6/inspect', '/flows/:flowId/inspect')
    expect(await screen.findByLabelText('Upper tolerance')).toHaveValue(5)
    expect(api.post).toHaveBeenCalledWith('/vision/inspect/read', { graph: draft.graph })
    expect(screen.getByTestId('inspect-overall')).toHaveTextContent('Stale')
    expect(screen.getByTestId('inspect-reading').querySelector('.line-through')).toHaveTextContent('99.9')
    fireEvent.click(screen.getByTestId('inspect-run'))
    await waitFor(() => expect(screen.getByTestId('inspect-overall')).not.toHaveTextContent('Stale'))
    expect(screen.getByTestId('inspect-reading').querySelector('.line-through')).toBeNull()
    expect(getSession(6).draft!.graph).toEqual(draft.graph)
  })

  it('InspectPage blocked removal shows dependency titles and ports without changing the graph', async () => {
    const { InspectPage } = await import('@/pages/InspectPage')
    const { clearSession, getSession } = await import('@/lib/flowDraft')
    clearSession(6)
    renderDataPage(<InspectPage />, '/flows/6/inspect', '/flows/:flowId/inspect')
    await screen.findByTestId('inspect-task')
    const before = structuredClone(getSession(6).draft!.graph)
    fireEvent.click(screen.getByRole('button', { name: 'Remove task' }))
    const confirm = await screen.findByRole('dialog')
    fireEvent.click(within(confirm).getByRole('button', { name: 'Confirm' }))
    expect(await screen.findByText('Downstream camera · image')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /force/i })).not.toBeInTheDocument()
    expect(getSession(6).draft!.graph).toEqual(before)
  })

  it('InspectPage identifies advanced-only flows and links to the advanced editor', async () => {
    const { InspectPage } = await import('@/pages/InspectPage')
    const { clearSession, setDraft } = await import('@/lib/flowDraft')
    clearSession(6)
    setDraft(6, { baseVersion: 1, name: 'Advanced', description: '', dirty: true, graph: { nodes: [INSPECT_GRAPH.nodes[0], { id: 'note', type: 'note', params: {} }], edges: [] } })
    renderDataPage(<InspectPage />, '/flows/6/inspect', '/flows/:flowId/inspect')
    expect(await screen.findByText('This flow was created in the advanced editor.')).toBeInTheDocument()
    // 「其他步驟 (N)」連結已依使用者要求拿掉；進階流程仍從頂列與空清單提示進入
    expect(screen.queryByRole('link', { name: /Other steps/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open in advanced flow' })).toHaveAttribute('href', '/flows/6')
    expect(screen.getByTestId('inspect-remove')).toBeDisabled()
  })

  it('FlowEditorPage focuses a node from the URL after the draft loads', async () => {
    localStorage.removeItem('vs.editorCollapsed.v1')
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    const { clearSession } = await import('@/lib/flowDraft')
    clearSession(3)
    const view = renderDataPage(<FlowEditorPage />, '/flows/3?focus=judge_dia', '/flows/:flowId')
    await screen.findByTestId('editor-toolbar')
    await waitFor(() => expect(view.container.querySelector('.react-flow__node.selected[data-id="judge_dia"]')).toBeInTheDocument())
    localStorage.removeItem('vs.editorCollapsed.v1')
  })

  it('FlowEditorPage keeps run settings in the draft until Save', async () => {
    // Suggest5 第 1 點：間隔／逾時／並行度以前每改一下就 PATCH，描述卻要按儲存；現在一律隨儲存寫入
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    const { api } = await import('@/lib/api')
    const { clearSession } = await import('@/lib/flowDraft')
    clearSession(1)
    vi.mocked(api.patch).mockClear()
    renderDataPage(<FlowEditorPage />, '/flows/1', '/flows/:flowId')
    await screen.findByTestId('editor-toolbar')
    const interval = await screen.findByLabelText('Continuous interval (ms)')
    fireEvent.change(interval, { target: { value: '500' } })
    fireEvent.click(screen.getByLabelText('Stop on NG'))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(vi.mocked(api.patch).mock.calls.some(([, body]) => 'continuous_interval_ms' in (body as object))).toBe(false)
    expect(screen.getByText('Applies immediately')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('btn-save'))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/vision/flows/1', expect.objectContaining({ continuous_interval_ms: 500, stop_on_ng: true, timeout_s: 0, concurrency: 1 })))
  })

  it('FlowEditorPage opens the side panes as drawers on narrow screens', async () => {
    // Suggest5 第 2 點：< lg 右側面板、< md 左側工具區整個消失；現在工具列有三顆入口以抽屜開啟
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    const { clearSession } = await import('@/lib/flowDraft')
    clearSession(1)
    const original = window.matchMedia
    const stub = (query: string) => ({ matches: /max-width: (767|1023)px/.test(query), media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false })
    window.matchMedia = stub as unknown as typeof window.matchMedia
    try {
      renderDataPage(<FlowEditorPage />, '/flows/1', '/flows/:flowId')
      await screen.findByTestId('editor-toolbar')
      expect(screen.getByTestId('inspector-pane')).not.toHaveAttribute('data-drawer')
      fireEvent.click(screen.getByTestId('editor-drawer-settings'))
      expect(screen.getByTestId('inspector-pane')).toHaveAttribute('data-drawer', 'open')
      expect(screen.getByText('Flow settings')).toBeInTheDocument()
      fireEvent.keyDown(document, { key: 'Escape' })
      expect(screen.getByTestId('inspector-pane')).not.toHaveAttribute('data-drawer')
      fireEvent.click(screen.getByTestId('editor-drawer-results'))
      expect(screen.getByTestId('inspector-pane')).toHaveAttribute('data-drawer', 'open')
      fireEvent.click(screen.getByTestId('editor-drawer-backdrop'))
      expect(screen.getByTestId('inspector-pane')).not.toHaveAttribute('data-drawer')
      fireEvent.click(screen.getByTestId('editor-drawer-tools'))
      expect(screen.getByTestId('tools-pane')).toHaveAttribute('data-drawer', 'open')
      fireEvent.click(screen.getByTestId('editor-drawer-close'))
      expect(screen.getByTestId('tools-pane')).not.toHaveAttribute('data-drawer')
    } finally {
      window.matchMedia = original
    }
  })

  it('InspectPage successful removal retains the source and unrelated advanced steps', async () => {
    const { InspectPage } = await import('@/pages/InspectPage')
    const { api } = await import('@/lib/api')
    const { clearSession, getSession, setDraft } = await import('@/lib/flowDraft')
    clearSession(6)
    const graph = structuredClone(INSPECT_GRAPH)
    const extra = { id: 'note', type: 'note', params: { text: 'Keep this note' } }
    graph.nodes.push(extra)
    setDraft(6, { graph, baseVersion: 1, name: 'Flow', description: '', dirty: true })
    const remaining = { nodes: [graph.nodes[0], extra], edges: [] }
    const original = vi.mocked(api.post).getMockImplementation()!
    await vi.mocked(api.post).withImplementation(async (path, body) => path === '/vision/inspect/remove' ? { graph: remaining, removed: true, dependencies: [] } : original(path, body), async () => {
      renderDataPage(<InspectPage />, '/flows/6/inspect', '/flows/:flowId/inspect')
      await screen.findByTestId('inspect-task')
      fireEvent.click(screen.getByRole('button', { name: 'Remove task' }))
      fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Confirm' }))
      await waitFor(() => expect(screen.queryByTestId('inspect-task')).not.toBeInTheDocument())
      expect(getSession(6).draft!.graph).toEqual(remaining)
    })
  })

  it('InspectPage renders tasks and viewer, edits through the translator, and saves with a version baseline', async () => {
    const { InspectPage } = await import('@/pages/InspectPage')
    const { api } = await import('@/lib/api')
    const { clearSession } = await import('@/lib/flowDraft')
    clearSession(6)
    renderDataPage(<InspectPage />, '/flows/6/inspect', '/flows/:flowId/inspect')
    expect(await screen.findByTestId('inspect-task')).toHaveTextContent('Diameter')
    expect(screen.getByTestId('inspect-viewer')).toBeInTheDocument()
    expect(screen.getByTestId('inspect-add')).toBeEnabled()
    const nominal = await screen.findByLabelText('Nominal')
    fireEvent.change(nominal, { target: { value: '101' } })
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vision/inspect/update', expect.objectContaining({ task: expect.objectContaining({ fields: { nominal: 101 } }) })))
    await waitFor(() => expect(screen.getByTestId('inspect-save')).toBeEnabled())
    fireEvent.click(screen.getByTestId('inspect-save'))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/vision/flows/6', expect.objectContaining({ expected_updated_at: '2026-01-01T00:00:00Z' })))
  })

  it('InspectPage blocks millimetres without calibration and requires a region for new tasks', async () => {
    const { InspectPage } = await import('@/pages/InspectPage')
    const { clearSession } = await import('@/lib/flowDraft')
    clearSession(6)
    renderDataPage(<InspectPage />, '/flows/6/inspect', '/flows/:flowId/inspect')
    fireEvent.change(await screen.findByLabelText('Unit'), { target: { value: 'mm' } })
    expect(await screen.findByRole('link', { name: 'Open calibration' })).toHaveAttribute('href', '/calibration')
    expect(screen.getByTestId('inspect-save')).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Unit'), { target: { value: 'px' } })
    await waitFor(() => expect(screen.getByTestId('inspect-add')).toBeEnabled())
    fireEvent.click(screen.getByTestId('inspect-add'))
    fireEvent.click(await screen.findByTestId('inspect-kind-measure_diameter'))
    fireEvent.click(await screen.findByTestId('inspect-next'))
    expect(await screen.findByTestId('inspect-create')).toBeDisabled()
  })
  it('AuditPage lists changes for an administrator', async () => {
    const { AuditPage } = await import('@/pages/AuditPage')
    renderPage(<AuditPage />, { route: '/audit' })
    expect(await screen.findByTestId('audit-export')).toBeInTheDocument()
    expect(screen.getByTestId('audit-action')).toBeInTheDocument()
  })

  it('UsersPage shows the role permission matrix for an administrator', async () => {
    const { UsersPage } = await import('@/pages/UsersPage')
    renderPage(<UsersPage />, { route: '/users' })
    expect(await screen.findByTestId('role-permissions')).toBeInTheDocument()
    const row = await screen.findByTestId('permission-flows.edit')
    // 管理員那一欄是固定打勾、不可點：可勾選的只有 engineer 與 operator 兩欄
    expect(row.querySelectorAll('input[type="checkbox"]').length).toBe(2)
  })

  it('HelpPage renders the Markdown guide, its sections and the tool catalogue', async () => {
    const { HelpPage } = await import('@/pages/HelpPage')
    renderPage(<HelpPage />, { route: '/help' })
    const article = await screen.findByTestId('help-article')
    await waitFor(() => expect(article.querySelector('h2')).not.toBeNull(), { timeout: 5000 })
    expect(article.querySelector('h2#shell')).not.toBeNull()
    expect(screen.getByTestId('help-toc').textContent).toContain('Getting around')
    expect(screen.queryByTestId('help-fallback')).toBeNull()
    expect(screen.getByTestId('help-search')).toBeInTheDocument()
  })

  it('HelpPage lists the tool catalogue at /help/tools', async () => {
    const { HelpPage } = await import('@/pages/HelpPage')
    renderPage(<HelpPage />, { route: '/help/tools' })
    expect(await screen.findByTestId('help-tools', {}, { timeout: 5000 })).toBeInTheDocument()
  })

  it('AgentPage renders the three steps and provider badge', async () => {
    const { AgentPage } = await import('@/pages/AgentPage')
    renderPage(<AgentPage />, { route: '/agent' })
    expect(await screen.findByTestId('agent-generate')).toBeDisabled()
    expect(screen.getByTestId('agent-prompt')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Offline rule engine')).toBeInTheDocument())
  })

  it('CalibrationPage offers the five ways and calculates from a board', async () => {
    const { CalibrationPage } = await import('@/pages/CalibrationPage')
    renderPage(<CalibrationPage />, { route: '/calibration' })
    expect(await screen.findByTestId('calib-mode-board')).toBeInTheDocument()
    expect(screen.getByTestId('calib-mode-points')).toBeInTheDocument()
    expect(screen.getByTestId('calib-mode-distance')).toBeInTheDocument()
    expect(screen.getByTestId('calib-mode-robot')).toBeInTheDocument()
    expect(screen.getByTestId('calib-mode-mapping')).toBeInTheDocument()
    // 還沒有影像：不能計算也不能儲存
    expect(screen.getByTestId('calib-solve')).toBeDisabled()
    expect(screen.getByTestId('calib-save')).toBeDisabled()
    // 從影像來源拍一張 → 自動找標定板 → 可以計算（來源清單載完才選得到）
    const picker = screen.getByTestId('calib-source') as HTMLSelectElement
    await waitFor(() => expect(picker.querySelector('option[value="1"]')).not.toBeNull())
    fireEvent.change(picker, { target: { value: '1' } })
    await waitFor(() => expect(screen.getByTestId('calib-capture')).toBeEnabled())
    fireEvent.click(screen.getByTestId('calib-capture'))
    await waitFor(() => expect(screen.getByTestId('calib-solve')).toBeEnabled())
    fireEvent.click(screen.getByTestId('calib-solve'))
    // 算完才給存，且結果用白話呈現
    expect(await screen.findByTestId('calib-result')).toHaveTextContent('0.05000')
    await waitFor(() => expect(screen.getByTestId('calib-save')).toBeEnabled())
  })

  it('CalibrationPage walks through the hand-eye wizard', async () => {
    const { CalibrationPage } = await import('@/pages/CalibrationPage')
    renderPage(<CalibrationPage />, { route: '/calibration' })
    fireEvent.click(await screen.findByTestId('calib-mode-robot'))
    // 三個步驟與平移表先出現，旋轉分頁只在要解旋轉中心時才有
    expect(screen.getByTestId('calib-robot-steps')).toBeInTheDocument()
    expect(screen.queryByTestId('calib-robot-stage')).toBeNull()
    expect(screen.getByTestId('calib-solve')).toBeDisabled()
    // 選了要解旋轉中心才會多出旋轉分頁
    fireEvent.change(screen.getByTestId('calib-robot-kind'), { target: { value: 'translation_rotation' } })
    expect(screen.getByTestId('calib-robot-stage')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('calib-robot-stage-rotation'))
    expect(screen.getByTestId('calib-robot-rotation-hint')).toBeInTheDocument()
    // 改用流程定位：沒有影像時定位鈕是停用的
    fireEvent.click(screen.getByTestId('calib-robot-stage-translation'))
    fireEvent.change(screen.getByTestId('calib-robot-locate'), { target: { value: 'flow' } })
    expect(screen.getByTestId('calib-robot-run-locate')).toBeDisabled()
  })

  it('BatchPage renders flow picker and empty image sets', async () => {
    const { BatchPage } = await import('@/pages/BatchPage')
    renderPage(<BatchPage />, { route: '/batch' })
    expect((await screen.findAllByText('Batch test')).length).toBeGreaterThan(0)
    expect(await screen.findByTestId('batch-no-sets')).toBeInTheDocument()
    expect(screen.getByTestId('batch-new-set')).toBeInTheDocument()
  })

  it('StationTeachPage lists station parameters and custom groups', async () => {
    const { StationTeachPage } = await import('@/pages/StationTeachPage')
    renderPage(<StationTeachPage />, { route: '/teach' })
    expect(await screen.findByTestId('station-teach-page')).toBeInTheDocument()
    expect(screen.getByText('Daily checks')).toBeInTheDocument()
    expect(screen.getAllByTestId('station-teach-row').length).toBeGreaterThan(0)
    expect(screen.getByTestId('station-teach-invalid')).toHaveTextContent('Missing shortcut')
  })

  it('FlowsPage lists flows from the API', async () => {
    const { FlowsPage } = await import('@/pages/FlowsPage')
    renderPage(<FlowsPage />, { route: '/flows' })
    expect(await screen.findByText('示範流程')).toBeInTheDocument()
  })

  it('FlowsPage keeps the missing-name error next to the field and focuses it', async () => {
    // Suggest5 第 7 點：欄位問題留在欄位旁，不用 toast；取消鈕走同一套草稿檢查
    const { FlowsPage } = await import('@/pages/FlowsPage')
    renderPage(<FlowsPage />, { route: '/flows' })
    await screen.findByText('示範流程')
    fireEvent.click(screen.getByRole('button', { name: 'New flow' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveAttribute('aria-labelledby')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    const name = within(dialog).getByTestId('flow-create-name')
    expect(name).toHaveAttribute('aria-invalid', 'true')
    expect(name).toBeRequired()
    expect(within(dialog).getByText('A name is required')).toBeInTheDocument()
    await waitFor(() => expect(name).toHaveFocus())
    fireEvent.change(name, { target: { value: 'x' } })
    expect(name).not.toHaveAttribute('aria-invalid')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(within(dialog).getByRole('alertdialog')).toBeInTheDocument()
  })

  it('CalibrationPage opens the camera mapping wizard', async () => {
    const { CalibrationPage } = await import('@/pages/CalibrationPage')
    renderPage(<CalibrationPage />, { route: '/calibration' })
    fireEvent.click(await screen.findByTestId('calib-mode-mapping'))
    expect(screen.getByTestId('calib-mapping-wizard')).toBeInTheDocument()
    expect(screen.getByTestId('calib-mapping-kind')).toBeInTheDocument()
    expect(screen.getByTestId('calib-mapping-source-a')).toBeInTheDocument()
    expect(screen.getByTestId('calib-mapping-source-b')).toBeInTheDocument()
    expect(screen.getByTestId('calib-solve')).toBeDisabled()
  })

  it('FlowEditorPage searches nodes from the canvas', async () => {
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    renderDataPage(<FlowEditorPage />, '/flows/1', '/flows/:flowId')
    await screen.findByTestId('editor-toolbar')
    expect(await screen.findByTestId('flow-description-panel')).toHaveTextContent('Inspect the sample part')
    expect(screen.queryByTestId('btn-batch')).toBeNull()
    expect(await screen.findByTestId('editor-open-variables')).toBeInTheDocument()
    const boardButton = await screen.findByTestId('editor-open-board')
    expect(screen.getByTestId('editor-open-comm')).toBeInTheDocument()
    fireEvent.click(boardButton)
    const dialog = await screen.findByTestId('editor-board-dialog')
    expect(within(dialog).getByTestId('board-settings')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Save board' })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('editor-board-dialog')).toBeNull())
    fireEvent.keyDown(document, { key: 'f', ctrlKey: true })
    const input = await screen.findByTestId('node-search-input')
    fireEvent.change(input, { target: { value: 'camera' } })
    const results = await screen.findByTestId('node-search-results')
    expect(results).toHaveTextContent('camera')
    fireEvent.click(screen.getByTestId('node-search-result'))
  })

  it('FlowEditorPage shows a save conflict dialog when the backend returns 409', async () => {
    const { api, FlowVersionConflictError } = await import('@/lib/api')
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    const serverGraph = {
      ...FLOW.graph,
      nodes: FLOW.graph.nodes.map((node) => node.id === 'thr' ? { ...node, params: { ...node.params, threshold: 70 } } : node),
    }
    vi.mocked(api.patch).mockRejectedValueOnce(new FlowVersionConflictError(409, 'This flow has changed since it was loaded', {
      version: 2,
      updated_at: '2026-01-01T00:00:02Z',
      last_saved_by: { name: 'alice', kind: 'user', at: '2026-01-01T00:00:02Z' },
      graph: serverGraph,
    }))
    renderDataPage(<FlowEditorPage />, '/flows/1', '/flows/:flowId')
    await screen.findByTestId('editor-toolbar')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Edited flow' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Save' }))
    expect(await screen.findByTestId('save-conflict-dialog')).toBeInTheDocument()
    expect(screen.getByText(/alice/)).toBeInTheDocument()
    expect(await screen.findByText('threshold 60 → 70')).toBeInTheDocument()
    expect(screen.getByTestId('save-conflict-load')).toBeInTheDocument()
    expect(screen.getByTestId('save-conflict-overwrite')).toBeInTheDocument()
    expect(screen.getByTestId('save-conflict-cancel')).toBeInTheDocument()
  })

  it('FlowEditorPage clears visible results without throwing', async () => {
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    renderDataPage(<FlowEditorPage />, '/flows/1', '/flows/:flowId')
    const button = await screen.findByTestId('editor-clear-results')
    fireEvent.click(button)
    expect(button).toBeInTheDocument()
  })

  it('FlowEditorPage collapses inspection task groups and expands them', async () => {
    localStorage.removeItem('vs.editorCollapsed.v1')
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    const view = renderDataPage(<FlowEditorPage />, '/flows/3', '/flows/:flowId')
    await screen.findByTestId('editor-toolbar')
    expect(screen.queryByTestId('group-node')).toBeNull()
    fireEvent.click(await screen.findByTestId('btn-toggle-groups'))
    await waitFor(() => expect(screen.getAllByTestId('group-node')).toHaveLength(2))
    expect(view.container.querySelectorAll('.react-flow__node')).toHaveLength(3)
    fireEvent.click(screen.getAllByTestId('group-expand')[0])
    await waitFor(() => expect(screen.getAllByTestId('group-node')).toHaveLength(1))
    fireEvent.click(screen.getByTestId('btn-toggle-groups'))
    await waitFor(() => expect(screen.queryByTestId('group-node')).toBeNull())
  })

  it('FlowEditorPage group drag applies the group delta to member coordinates', () => {
    const graph = {
      nodes: [
        { id: 'camera', type: 'image_source', position: { x: 0, y: 0 } },
        { id: 'find', type: 'blob', position: { x: 100, y: 50 }, meta: { inspect: { task_id: 'task-a', role: 'find', kind: 'measure_diameter', schema_version: 1, required: true } } },
        { id: 'judge', type: 'in_range', position: { x: 300, y: 70 }, meta: { inspect: { task_id: 'task-a', role: 'judge', kind: 'measure_diameter', schema_version: 1, required: true } } },
      ],
      edges: [{ id: 'e1', source: 'find', target: 'judge', source_handle: 'count', target_handle: 'value' }],
    }
    const moved = expandOnDrop(graph, 'task-a', { x: 25, y: -10 })
    expect(moved.nodes.find((node) => node.id === 'find')?.position).toEqual({ x: 125, y: 40 })
    expect(moved.nodes.find((node) => node.id === 'judge')?.position).toEqual({ x: 325, y: 60 })
    expect(moved.nodes.find((node) => node.id === 'camera')?.position).toEqual({ x: 0, y: 0 })
    expect(moved.edges).toEqual(graph.edges)
  })

  it('FlowEditorPage shows published outputs for a selected node', async () => {
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    const view = renderDataPage(<FlowEditorPage />, '/flows/1', '/flows/:flowId')
    await screen.findByTestId('editor-toolbar')
    const row = view.container.querySelector('[data-node-id="thr"]')
    expect(row).not.toBeNull()
    fireEvent.click(row as Element)
    expect(await screen.findByTestId('published-outputs')).toBeInTheDocument()
    expect(await screen.findByTestId('source-picker')).toBeInTheDocument()
  })

  it('FlowEditorPage opens the image grid viewer mode', async () => {
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    renderDataPage(<FlowEditorPage />, '/flows/1', '/flows/:flowId')
    await screen.findByTestId('editor-toolbar')
    fireEvent.click(await screen.findByTestId('btn-grid-view'))
    expect(await screen.findByTestId('editor-grid-view')).toBeInTheDocument()
    expect(screen.getAllByTestId('editor-grid-cell')).toHaveLength(4)
    // 顯示選項列在宮格模式下仍在（且壓在格子之上），再按一次就回到單一檢視
    expect(screen.getByTestId('viewer-options').className).toContain('z-30')
    fireEvent.click(screen.getByTestId('btn-grid-view'))
    expect(screen.queryByTestId('editor-grid-view')).toBeNull()
    expect(screen.getByTestId('btn-split')).not.toBeDisabled()
  })

  it('FlowEditorPage starts image sequence preview from the toolbar', async () => {
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    renderDataPage(<FlowEditorPage />, '/flows/1', '/flows/:flowId')
    const button = await screen.findByTestId('btn-sequence-preview')
    fireEvent.click(button)
    await waitFor(() => expect(screen.getByTestId('sequence-preview-status')).toHaveTextContent('OK'))
  })

  it('ToolPage toggles automatic parameter preview', async () => {
    localStorage.removeItem('vs.toolAutoPreview.v1')
    const { ToolPage } = await import('@/pages/ToolPage')
    renderDataPage(<ToolPage />, '/flows/1/tools/camera', '/flows/:flowId/tools/:nodeId')
    const row = await screen.findByTestId('tool-auto-preview')
    const toggle = within(row).getByRole('switch')
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    expect(localStorage.getItem('vs.toolAutoPreview.v1')).toBe('1')
  })

  it('DashboardsPage lists operation dashboards from the API', async () => {
    const { DashboardsPage } = await import('@/pages/dashboard/DashboardsPage')
    renderPage(<DashboardsPage />, { route: '/dashboards' })
    expect(await screen.findByText('Line status dashboard')).toBeInTheDocument()
  })

  it('DashboardDesignerPage renders the designer and accepts a dragged widget', async () => {
    const { DashboardDesignerPage } = await import('@/pages/dashboard/DashboardDesignerPage')
    renderDataPage(<DashboardDesignerPage />, '/dashboards/1/design', '/dashboards/:id/design')
    expect(await screen.findByTestId('dash-design-catalog')).toBeInTheDocument()
    expect(await screen.findByTestId('dash-design-grid')).toBeInTheDocument()
    const payload = new Map<string, string>()
    const dataTransfer = {
      setData: (type: string, value: string) => payload.set(type, value),
      getData: (type: string) => payload.get(type) ?? '',
    }
    fireEvent.dragStart(screen.getAllByTestId('dash-design-add-text')[0], { dataTransfer })
    fireEvent.drop(screen.getByTestId('dash-design-cell-verdict'), { dataTransfer })
    expect(await screen.findByTestId('dash-design-properties')).toBeInTheDocument()
    expect(screen.getByTestId('dash-design-props')).toBeInTheDocument()
  })

  it('DashboardPage renders image, verdict and stats widgets', async () => {
    const { DashboardPage } = await import('@/pages/dashboard/DashboardPage')
    renderPage(<DashboardPage />, { route: '/dashboard' })
    expect(await screen.findByTestId('dash-widget-image')).toBeInTheDocument()
    expect(await screen.findByTestId('dash-widget-verdict')).toBeInTheDocument()
    expect(await screen.findByTestId('dash-widget-stats')).toBeInTheDocument()
  })

  it('DlPage shows quick register for box projects and starts it', async () => {
    const { DlPage } = await import('@/pages/DlPage')
    renderPage(<DlPage />, { route: '/dl' })
    expect(await screen.findByTestId('dl-quick-register')).toHaveTextContent('Quick register')
    expect(screen.getByText(/smallest size, 20 epochs/i)).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('dl-quick-register-start'))
    expect(await screen.findByTestId('dl-quick-params')).toHaveTextContent('imgsz: 320')
  })

  it('SourcesPage shows the tree by default and can switch to cards', async () => {
    const { SourcesPage } = await import('@/pages/SourcesPage')
    renderPage(<SourcesPage />, { route: '/sources' })
    expect(await screen.findByText(/範例：圓孔量測/)).toBeInTheDocument()
    // 預設樹狀：種類是父層，來源是葉節點
    expect(screen.getByTestId('source-tree')).toBeInTheDocument()
    expect(screen.queryByTestId('source-cards')).toBeNull()
    expect(screen.getAllByTestId('source-row').length).toBeGreaterThan(0)
    // 擷取端相機來源：離線徽章；頁首「下載擷取端」在未建置時停用
    expect(screen.getByText('Capture client offline')).toBeInTheDocument()
    expect(screen.getByTestId('capture-download')).toBeDisabled()
    fireEvent.click(screen.getByText('Cards'))
    expect(screen.getByTestId('source-cards')).toBeInTheDocument()
    expect(screen.getAllByTestId('source-card').length).toBeGreaterThan(0)
    expect(localStorage.getItem('vs.sourcesView')).toBe('cards')
  })

  it('integration layout titles the section with its own dictionary key (modbus-server -> Modbus server)', async () => {
    const { IntegrationLayout } = await import('@/pages/IntegrationPage')
    renderPage(<IntegrationLayout />, { route: '/integration/modbus-server' })
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('Modbus server'))
    expect(screen.getByRole('heading', { level: 1 }).textContent).not.toContain('integration.tabs')
  })

  it('integration sections are their own pages, each block on its own tab', async () => {
    const { TcpPage } = await import('@/pages/integration/TcpPage')
    renderPage(<TcpPage />, { route: '/integration/tcp' })
    expect(await screen.findByTestId('tcp-command')).toBeInTheDocument()  // 預設分頁：試打
    // Swagger 風格的指令列：展開 RUN 看得到引數表與 Try it out
    fireEvent.click(screen.getByTestId('tcp-cmd-RUN').querySelector('button')!)
    expect(screen.getByTestId('tcp-try')).toBeInTheDocument()
    expect(screen.getByText('RUN <flow> [key=value ...] [fmt=<output>]')).toBeInTheDocument()
    // 接收規則分頁：不是指令的一行也能觸發（規則來自假後端）
    fireEvent.click(await screen.findByRole('tab', { name: 'Receive rules' }))
    expect(await screen.findByTestId('rule-0')).toBeInTheDocument()
    expect(screen.getByDisplayValue(/^SCAN/)).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('tab', { name: 'Commands and results' }))
    expect(await screen.findByTestId('trace-rows-tcp')).toHaveTextContent('RUN 1')  // 假後端的追蹤紀錄
    const { ModbusServerPage } = await import('@/pages/integration/ModbusPage')
    renderPage(<ModbusServerPage />, { route: '/integration/modbus-server' })
    expect(await screen.findByTestId('conn-create')).toBeInTheDocument()  // 預設分頁：連線
    fireEvent.click(screen.getByRole('tab', { name: 'Address format and mapping' }))
    expect(await screen.findByText('Server (modbus_server): the master connects to us')).toBeInTheDocument()
    expect(screen.getAllByText(/master|server/i).length).toBeGreaterThan(0)
  })

  it('DevicesPage lists the stream connections and the command trace', async () => {
    const { DevicesPage } = await import('@/pages/integration/DevicesPage')
    renderPage(<DevicesPage />, { route: '/integration/devices' })
    expect(await screen.findByTestId('conn-create')).toBeInTheDocument()
  })

  it('HttpPage is a Swagger-style explorer built from the OpenAPI description', async () => {
    const { HttpPage } = await import('@/pages/integration/HttpPage')
    renderPage(<HttpPage />, { route: '/integration/http' })
    // 整合必用的端點排最前面（run 在裡面），其餘依 tag 分組
    const run = await screen.findByTestId('op-post-/api/vision/flows/{flow_id}/run')
    expect(screen.getByTestId('tag-lock')).toBeInTheDocument()
    fireEvent.click(run.querySelector('button')!)
    fireEvent.click(screen.getByTestId('op-try'))
    expect(screen.getByTestId('op-execute')).toBeInTheDocument()
    expect(screen.getAllByText(/curl -X POST/).length).toBeGreaterThan(0)
  })

  it('PluginsPage lists what loaded from plugins/ with the error of a broken one', async () => {
    const { PluginsPage } = await import('@/pages/integration/PluginsPage')
    renderPage(<PluginsPage />, { route: '/integration/plugins' })
    expect(await screen.findByTestId('plugin-example_dark_ratio.py')).toHaveTextContent('tool:dark_ratio')
    expect(screen.getByTestId('plugin-broken.py')).toHaveTextContent("Missing package 'foo'")
    expect(screen.getByTestId('plugins-rescan')).toBeInTheDocument()
  })

  it('IntegrationPage capture tab lists connected capture clients and channels', async () => {
    const { IntegrationCapturePage } = await import('@/pages/integration/CapturePage')
    renderPage(<IntegrationCapturePage />, { route: '/integration/capture' })
    expect(await screen.findByText('Connected capture clients')).toBeInTheDocument()
    expect(await screen.findByText('line-pc')).toBeInTheDocument()
    expect(screen.getByText('產線相機 1')).toBeInTheDocument()
    expect(screen.getByText('Setup')).toBeInTheDocument()
  })

  it('SettingsPage and LoginPage render', async () => {
    const { SettingsPage } = await import('@/pages/SettingsPage')
    renderPage(<SettingsPage />, { route: '/settings' })
    expect((await screen.findAllByText('Settings')).length).toBeGreaterThan(0)
    // 管理員才看得到資料保留卡片，且欄位值來自伺服器
    expect(await screen.findByTestId('retention-card')).toBeTruthy()
    expect((await screen.findByTestId('retention-run_days')).getAttribute('value')).toBe('365')
    const { LoginPage } = await import('@/pages/LoginPage')
    renderPage(<LoginPage />, { route: '/login' })
    expect((await screen.findAllByText(/Sign in|Username|VisionSequence/)).length).toBeGreaterThan(0)
  })

  it('AssetsPage, DlPage, IntegrationPage render without throwing', async () => {
    const { AssetsPage } = await import('@/pages/AssetsPage')
    renderPage(<AssetsPage />, { route: '/assets' })
    expect((await screen.findAllByText(/Asset library|Assets/)).length).toBeGreaterThan(0)
    const { DlPage } = await import('@/pages/DlPage')
    renderPage(<DlPage />, { route: '/dl' })
    expect((await screen.findAllByText('DL teaching')).length).toBeGreaterThan(0)
    const { IntegrationLayout } = await import('@/pages/IntegrationPage')
    renderPage(<IntegrationLayout />, { route: '/integration/http' })
    expect((await screen.findAllByText(/integration/i)).length).toBeGreaterThan(0)
  })
})
