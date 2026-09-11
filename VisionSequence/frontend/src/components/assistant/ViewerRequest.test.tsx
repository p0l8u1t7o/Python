/** 影像視窗互動卡：roi／crop 經頁面登記的 requestRegion 畫區域再送出、preview 經 showPreview 顯示後回 shown、沒有影像視窗的頁面只提示。 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { installApiMock } from '../../test/apiMock'
import { renderPage } from '../../test/render'

installApiMock()

import { api } from '@/lib/api'
import { setAssistantContext } from '@/lib/assistantContext'
import { regionSummary, ViewerRequest } from './ViewerRequest'

const REGION = { shape: 'rect' as const, x: 10, y: 20, w: 30, h: 40 }

describe('ViewerRequest', () => {
  afterEach(() => { setAssistantContext(null); vi.mocked(api.post).mockClear() })

  it('draws through the page context and sends the region as JSON', async () => {
    const requestRegion = vi.fn(async () => REGION)
    setAssistantContext({ kind: 'flow_editor', flowId: 1, requestRegion })
    renderPage(<ViewerRequest jobId="job-1" question={{ id: 'mark', text: 'Draw the mark', kind: 'crop', shapes: ['rect'], target: 'tm' }} />)
    expect(screen.getByTestId('agent-viewer-send')).toBeDisabled()
    fireEvent.click(screen.getByTestId('agent-viewer-draw'))
    await waitFor(() => expect(screen.getByTestId('agent-viewer-region')).toHaveTextContent('rect'))
    expect(requestRegion).toHaveBeenCalledWith(['rect'])
    expect(regionSummary(REGION)).toBe('rect · x 10, y 20, w 30, h 40')
    fireEvent.click(screen.getByTestId('agent-viewer-send'))
    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalledWith('/vision/agent/jobs/job-1/answer', { answers: [{ id: 'mark', value: JSON.stringify(REGION) }] }))
  })

  it('shows a preview through the page context and answers shown', async () => {
    const showPreview = vi.fn(async () => undefined)
    setAssistantContext({ kind: 'flow_editor', flowId: 1, showPreview })
    renderPage(<ViewerRequest jobId="job-2" question={{ id: 'look', text: 'Check it', kind: 'preview', node: 'thr' }} />)
    fireEvent.click(screen.getByTestId('agent-viewer-show'))
    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalledWith('/vision/agent/jobs/job-2/answer', { answers: [{ id: 'look', value: 'shown' }] }))
    expect(showPreview).toHaveBeenCalledWith({ node: 'thr', port: undefined, image: undefined })
  })

  it('explains when the current page has no image viewer', () => {
    setAssistantContext({ kind: 'page' })
    renderPage(<ViewerRequest jobId="job-3" question={{ id: 'area', text: 'Draw the area', kind: 'roi', optional: true }} />)
    expect(screen.getByTestId('agent-viewer-noviewer')).toHaveTextContent('Open the flow editor or the AI assistant page')
    expect(screen.getByTestId('agent-viewer-draw')).toBeDisabled()
    fireEvent.click(screen.getByTestId('agent-viewer-skip'))
    expect(vi.mocked(api.post)).toHaveBeenCalledWith('/vision/agent/jobs/job-3/answer', { answers: [{ id: 'area', value: '' }] })
  })
})
