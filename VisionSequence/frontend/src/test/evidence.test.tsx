/** 樣本分組、批次頁接線與失敗原因評分。 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installApiMock } from './apiMock'
import { renderPage } from './render'

installApiMock()

import { BatchImagesGrid } from '@/components/batch/BatchImagesGrid'
import { NewSetModal } from '@/components/batch/NewSetModal'
import { LessonRating } from '@/components/assistant/LessonRating'
import { BatchPage } from '@/pages/BatchPage'
import { api } from '@/lib/api'
import { filterSampleGroup, splitSampleGroups, type BatchSet } from '@/lib/batch'
import i18n from '@/i18n'

const batch: BatchSet = { id: 12, flow_id: 1, flow_name: 'Test', name: 'Samples', source: 'upload', image_count: 2, size_bytes: 100, owner_id: 1,
  labeled: { ok: 1, ng: 1 }, created_at: null, updated_at: null, can_manage: true,
  images: [{ index: 0, name: 'Tune sample', width: 30, height: 30, expected: 'ok', note: '', expect_outputs: {}, image_url: '', group: 'tune' },
    { index: 1, name: 'Accept sample', width: 30, height: 30, expected: 'ng', note: '', expect_outputs: {}, image_url: '', group: 'accept' }] }

describe('evidence groups', () => {
  beforeEach(async () => { await i18n.changeLanguage('en') })

  it('filters legacy samples as tune and splits every Nth image', () => {
    expect(splitSampleGroups(5, 2)).toEqual(['tune', 'accept', 'tune', 'accept', 'tune'])
    expect(splitSampleGroups(3, 0)).toEqual(['tune', 'tune', 'tune'])
    expect(filterSampleGroup([{ group: 'accept' }, {}, { group: 'tune' }], 'tune')).toEqual([{}, { group: 'tune' }])
  })

  it('switches groups, filters cards and disables editing for read-only users', () => {
    const change = vi.fn()
    const view = renderPage(<BatchImagesGrid set={batch} run={null} onLabel={vi.fn()} onBulk={vi.fn()} onPreview={vi.fn()} onGroup={change} canManage />)
    fireEvent.change(screen.getAllByTestId('batch-image-group')[0], { target: { value: 'accept' } })
    expect(change).toHaveBeenCalledWith(0, 'accept')
    fireEvent.change(screen.getByTestId('batch-group-filter'), { target: { value: 'accept' } })
    expect(screen.getAllByTestId('batch-image-card')).toHaveLength(1)
    expect(screen.getByText('Accept sample')).toBeInTheDocument()
    view.unmount()
    renderPage(<BatchImagesGrid set={batch} run={null} onLabel={vi.fn()} onBulk={vi.fn()} onPreview={vi.fn()} onGroup={change} canManage={false} />)
    expect(screen.getAllByTestId('batch-image-group')[0]).toBeDisabled()
  })

  it('persists a group change from the actual batch page', async () => {
    const baseGet = vi.mocked(api.get).getMockImplementation()!
    vi.mocked(api.get).mockImplementation(async (path, ...args) => {
      if (path === '/vision/batch/sets/12') return batch as never
      if (path.startsWith('/vision/batch/sets/12/runs')) return { items: [] } as never
      if (path.startsWith('/vision/batch/sets')) return { items: [batch], total: 1, max_images: 200 } as never
      return baseGet(path, ...args)
    })
    renderPage(<BatchPage />, { route: '/batch?flow=1&set=12' })
    fireEvent.click(await screen.findByText('Image set', { selector: 'button' }))
    const selectors = await screen.findAllByTestId('batch-image-group')
    fireEvent.change(selectors[0], { target: { value: 'accept' } })
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/vision/batch/sets/12', { labels: [{ index: 0, group: 'accept' }] }))
    fireEvent.change(screen.getByTestId('batch-group-filter'), { target: { value: 'accept' } })
    expect(screen.queryByText('Tune sample')).not.toBeInTheDocument()
  })

  it('sends the acceptance interval when creating an image set', async () => {
    renderPage(<NewSetModal open onClose={vi.fn()} flowId={1} maxImages={200} onCreated={vi.fn()} />)
    fireEvent.change(screen.getByTestId('batch-set-input'), { target: { files: [new File(['image'], 'sample.png', { type: 'image/png' })] } })
    fireEvent.change(screen.getByTestId('batch-accept-every'), { target: { value: '3' } })
    fireEvent.click(screen.getByTestId('batch-set-create'))
    await waitFor(() => expect(api.postForm).toHaveBeenCalled())
    const form = vi.mocked(api.postForm).mock.calls.at(-1)![1]
    expect(form.get('accept_every')).toBe('3')
  })

  it.each(['en', 'zh-Hant', 'zh-Hans'])('rates failures with translated reasons in %s', async (lang) => {
    await i18n.changeLanguage(lang)
    vi.mocked(api.get).mockResolvedValue({ lessons: { accepted_on: 'accept', conditions: { material: 'steel' } } })
    renderPage(<LessonRating sessionId={19} />)
    const select = screen.getByTestId('agent-failure-reason')
    expect(select.textContent).not.toContain('evidence.')
    fireEvent.change(select, { target: { value: 'glare' } })
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/vision/agent/sessions/19', {
      rating: -1, lessons: { outcome: 'failure', failure_reasons: ['glare'], accepted_on: 'accept', conditions: { material: 'steel' } },
    }))
  })
})
