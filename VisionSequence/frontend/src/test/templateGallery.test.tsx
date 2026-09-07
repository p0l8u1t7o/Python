/**
 * 範本畫廊：選一個內建範本 → 預設就是「使用範例圖片」→ 建立出來的圖以固定影像開頭且帶著圖片。
 * 鎖住「載入範本後還要先選來源才能試執行」這個回歸。
 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { installApiMock } from './apiMock'
import { renderPage } from './render'

installApiMock()

vi.mock('@/lib/flowStream', () => ({ useLockEvents: () => {}, useFlowEvents: () => {}, useFlowStream: () => ({ events: [], seq: 0, connected: false, runningIds: new Set() }), subscribeStream: () => () => {}, setStreamClient: () => {} }))

describe('template gallery', () => {
  it('creates a flow from a builtin template with its sample pictures', async () => {
    const { api } = await import('@/lib/api')
    const { TemplateGallery } = await import('@/components/templates/TemplateGallery')
    const picked = vi.fn()
    renderPage(<TemplateGallery open mode="create" onClose={() => {}} onPick={picked} />, { route: '/flows' })

    const card = await screen.findByTestId('template-card')
    expect(card).toHaveAttribute('data-template-id', 'builtin:hole_count')
    fireEvent.click(card)

    // 來源沒選（預設）＝使用範例圖片
    const source = (await screen.findByTestId('template-source')) as HTMLSelectElement
    expect(source.value).toBe('')
    expect(screen.getByTestId('template-flow-name')).toHaveValue('孔數檢測')
    fireEvent.click(screen.getByTestId('template-confirm'))

    await waitFor(() => expect(picked).toHaveBeenCalled())
    expect(api.post).toHaveBeenCalledWith('/vision/templates/builtin%3Ahole_count/instantiate', { source_id: null, prefix: '', use_samples: true })
    const result = picked.mock.calls[0][0] as { graph: { nodes: { type: string; params: Record<string, unknown> }[] }; missingSource: boolean }
    expect(result.missingSource).toBe(false)
    expect(result.graph.nodes[0].type).toBe('fixed_image')
    expect((result.graph.nodes[0].params.images as unknown[]).length).toBeGreaterThan(0)
  })
})
