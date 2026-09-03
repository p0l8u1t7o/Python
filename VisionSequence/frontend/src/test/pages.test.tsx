/**
 * 頁面 smoke 測試：每頁在假後端下都要能 render 出標題／主要區塊，且不丟例外。
 * 抓的是「改了型別或 hook 卻沒開過那一頁」的回歸；互動細節另寫。
 */
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { installApiMock } from './apiMock'
import { renderPage } from './render'

installApiMock()

vi.mock('@/lib/flowStream', () => ({ useLockEvents: () => {}, useFlowEvents: () => {}, useFlowStream: () => ({ events: [], seq: 0 }) }))

describe('pages render (smoke)', () => {
  it('HelpPage shows quickstart and tabs', async () => {
    const { HelpPage } = await import('@/pages/HelpPage')
    renderPage(<HelpPage />, { route: '/help' })
    expect(await screen.findByText('快速上手')).toBeInTheDocument()
    expect(screen.getAllByText('AI 助手').length).toBeGreaterThan(0)
  })

  it('AgentPage renders the three steps and provider badge', async () => {
    const { AgentPage } = await import('@/pages/AgentPage')
    renderPage(<AgentPage />, { route: '/agent' })
    expect(await screen.findByTestId('agent-generate')).toBeDisabled()
    expect(screen.getByTestId('agent-prompt')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('離線規則引擎')).toBeInTheDocument())
  })

  it('BatchPage renders flow picker and empty image sets', async () => {
    const { BatchPage } = await import('@/pages/BatchPage')
    renderPage(<BatchPage />, { route: '/batch' })
    expect((await screen.findAllByText('批次測試')).length).toBeGreaterThan(0)
    expect(await screen.findByTestId('batch-no-sets')).toBeInTheDocument()
    expect(screen.getByTestId('batch-new-set')).toBeInTheDocument()
  })

  it('FlowsPage lists flows from the API', async () => {
    const { FlowsPage } = await import('@/pages/FlowsPage')
    renderPage(<FlowsPage />, { route: '/flows' })
    expect(await screen.findByText('示範流程')).toBeInTheDocument()
  })

  it('SourcesPage lists sources with actions column first', async () => {
    const { SourcesPage } = await import('@/pages/SourcesPage')
    renderPage(<SourcesPage />, { route: '/sources' })
    expect(await screen.findByText('範例：圓孔量測')).toBeInTheDocument()
    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent)
    expect(headers[0]).toBe('操作')
  })

  it('SettingsPage and LoginPage render', async () => {
    const { SettingsPage } = await import('@/pages/SettingsPage')
    renderPage(<SettingsPage />, { route: '/settings' })
    expect((await screen.findAllByText('設定')).length).toBeGreaterThan(0)
    const { LoginPage } = await import('@/pages/LoginPage')
    renderPage(<LoginPage />, { route: '/login' })
    expect((await screen.findAllByText(/登入|帳號|VisionSequence/)).length).toBeGreaterThan(0)
  })

  it('AssetsPage, DlPage, IntegrationPage render without throwing', async () => {
    const { AssetsPage } = await import('@/pages/AssetsPage')
    renderPage(<AssetsPage />, { route: '/assets' })
    expect((await screen.findAllByText('資產庫')).length).toBeGreaterThan(0)
    const { DlPage } = await import('@/pages/DlPage')
    renderPage(<DlPage />, { route: '/dl' })
    expect((await screen.findAllByText('深度學習教導')).length).toBeGreaterThan(0)
    const { IntegrationPage } = await import('@/pages/IntegrationPage')
    renderPage(<IntegrationPage />, { route: '/integration' })
    expect((await screen.findAllByText(/外部整合|整合/)).length).toBeGreaterThan(0)
  })
})
