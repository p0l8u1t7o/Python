/**
 * 頁面 smoke 測試：每頁在假後端下都要能 render 出標題／主要區塊，且不丟例外。
 * 抓的是「改了型別或 hook 卻沒開過那一頁」的回歸；互動細節另寫。
 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { installApiMock } from './apiMock'
import { renderPage } from './render'

installApiMock()

vi.mock('@/lib/flowStream', () => ({ useLockEvents: () => {}, useFlowEvents: () => {}, useFlowStream: () => ({ events: [], seq: 0 }) }))

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

  it('SourcesPage lists sources with actions column last (same as flows)', async () => {
    const { SourcesPage } = await import('@/pages/SourcesPage')
    renderPage(<SourcesPage />, { route: '/sources' })
    expect(await screen.findByText('範例：圓孔量測')).toBeInTheDocument()
    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent)
    expect(headers[0]).toBe('Name')
    expect(headers[headers.length - 1]).toBe('Actions')
    // 擷取端相機來源：離線徽章；頁首「下載擷取端」在未建置時停用
    expect(screen.getByText('Capture client offline')).toBeInTheDocument()
    expect(screen.getByTestId('capture-download')).toBeDisabled()
  })

  it('integration sections are their own pages, each block on its own tab', async () => {
    const { TcpPage } = await import('@/pages/integration/TcpPage')
    renderPage(<TcpPage />, { route: '/integration/tcp' })
    expect(await screen.findByTestId('tcp-command')).toBeInTheDocument()  // 預設分頁：試打
    fireEvent.click(await screen.findByRole('tab', { name: 'Commands and results' }))
    expect(await screen.findByTestId('trace-rows-tcp')).toHaveTextContent('RUN 1')  // 假後端的追蹤紀錄
    const { ModbusServerPage } = await import('@/pages/integration/ModbusPage')
    renderPage(<ModbusServerPage />, { route: '/integration/modbus-server' })
    expect(await screen.findByTestId('conn-create')).toBeInTheDocument()  // 預設分頁：連線
    fireEvent.click(screen.getByRole('tab', { name: 'Address format and mapping' }))
    expect(await screen.findByText('Server (modbus_server): the master connects to us')).toBeInTheDocument()
    expect(screen.getAllByText(/master|server/i).length).toBeGreaterThan(0)
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
