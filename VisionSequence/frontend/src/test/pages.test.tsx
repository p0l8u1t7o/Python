/**
 * 頁面 smoke 測試：每頁在假後端下都要能 render 出標題／主要區塊，且不丟例外。
 * 抓的是「改了型別或 hook 卻沒開過那一頁」的回歸；互動細節另寫。
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { installApiMock } from './apiMock'
import { renderPage } from './render'
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

  it('HelpPage shows quickstart and tabs', async () => {
    const { HelpPage } = await import('@/pages/HelpPage')
    renderPage(<HelpPage />, { route: '/help' })
    expect(await screen.findByText('Quick start')).toBeInTheDocument()
    expect(screen.getAllByText(/quick start|glossary/i).length).toBeGreaterThan(0)
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

  it('FlowsPage lists flows from the API', async () => {
    const { FlowsPage } = await import('@/pages/FlowsPage')
    renderPage(<FlowsPage />, { route: '/flows' })
    expect(await screen.findByText('示範流程')).toBeInTheDocument()
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
    fireEvent.keyDown(document, { key: 'f', ctrlKey: true })
    const input = await screen.findByTestId('node-search-input')
    fireEvent.change(input, { target: { value: 'camera' } })
    const results = await screen.findByTestId('node-search-results')
    expect(results).toHaveTextContent('camera')
    fireEvent.click(screen.getByTestId('node-search-result'))
  })

  it('FlowEditorPage clears visible results without throwing', async () => {
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    renderDataPage(<FlowEditorPage />, '/flows/1', '/flows/:flowId')
    const button = await screen.findByTestId('editor-clear-results')
    fireEvent.click(button)
    expect(button).toBeInTheDocument()
  })

  it('FlowEditorPage opens the image grid viewer mode', async () => {
    const { FlowEditorPage } = await import('@/pages/FlowEditorPage')
    renderDataPage(<FlowEditorPage />, '/flows/1', '/flows/:flowId')
    await screen.findByTestId('editor-toolbar')
    fireEvent.click(await screen.findByTestId('btn-grid-view'))
    expect(await screen.findByTestId('editor-grid-view')).toBeInTheDocument()
    expect(screen.getAllByTestId('editor-grid-cell')).toHaveLength(4)
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
