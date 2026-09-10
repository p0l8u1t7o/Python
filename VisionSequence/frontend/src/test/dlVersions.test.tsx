/** 模型版本的狀態、比較、衝突基準與誤判回收互動。 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ModelVersionsPanel } from '@/components/dl/ModelVersionsPanel'
import { CorrectionSampleButton } from '@/components/dl/CorrectionSampleButton'
import { api } from '@/lib/api'
import type { DlModelVersion } from '@/lib/types'
import { installApiMock, routes } from './apiMock'
import { renderPage } from './render'

installApiMock()

const first: DlModelVersion = {
  id: 1, number: 1, status: 'active', asset_id: 'old', dataset_version: 1, parent: null,
  metrics: { accuracy: 0.5, error_count: 1 }, failures: [{ sample_id: 'sample1', truth: 'good', prediction: 'bad' }],
  tune_samples: [], holdout_samples: ['sample1'], created_by: 'engineer', created_at: '2026-09-11T01:00:00Z', note: '',
  flows: [{ flow_id: 1, name: 'Line A', node_id: 'classify', updated_at: '2026-09-11T01:02:00Z' }],
}
const second: DlModelVersion = { ...first, id: 2, number: 2, parent: 1, asset_id: 'new', status: 'candidate', metrics: { accuracy: 1, error_count: 0 }, failures: [], flows: [] }

describe('Model versions', () => {
  beforeEach(() => {
    vi.spyOn(api, 'get').mockImplementation((path) => {
      if (path.endsWith('/models')) return Promise.resolve({ items: [second, first] }) as ReturnType<typeof api.get>
      if (path.includes('/models/compare')) return Promise.resolve({ a: first, b: second, fixed: first.failures, new: [], truncated: false }) as ReturnType<typeof api.get>
      return Promise.resolve(routes(path)) as ReturnType<typeof api.get>
    })
  })

  it('activates explicitly and applies with the original flow timestamp', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ version: { ...second, status: 'active' }, flows_using_previous: first.flows })
    renderPage(<ModelVersionsPanel projectId={1} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Activate' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/vision/dl/projects/1/models/2/activate', {}))
    expect(post).toHaveBeenCalledTimes(1)
    fireEvent.click(await screen.findByRole('button', { name: 'Apply to this step' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/vision/dl/projects/1/models/2/apply-to-flow', {
      flow_id: 1, node_id: 'classify', expected_updated_at: first.flows[0].updated_at,
    }))
  })

  it('shows fixed failures and preserves holdout when recovering a correction', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ holdout: true })
    renderPage(<ModelVersionsPanel projectId={1} />)
    fireEvent.change(await screen.findByRole('combobox', { name: 'Compare with' }), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }))
    expect(await screen.findByText('Corrected samples (1)')).toBeInTheDocument()
    expect(screen.getByText('New errors (0)')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add as correction sample' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/vision/dl/projects/1/corrections', { sample_id: 'sample1', model_version: 1 }))
    expect(await screen.findByText(/This picture remains in holdout/)).toBeInTheDocument()
  })

  it('recovers a batch image into the selected project', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ holdout: false })
    renderPage(<CorrectionSampleButton runId={9} index={3} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Add as correction sample' }))
    const project = await screen.findByLabelText('Project')
    await waitFor(() => expect(project.querySelectorAll('option').length).toBeGreaterThan(1))
    fireEvent.change(project, { target: { value: '1' } })
    const buttons = screen.getAllByRole('button', { name: 'Add as correction sample' })
    fireEvent.click(buttons[buttons.length - 1])
    await waitFor(() => expect(post).toHaveBeenCalledWith('/vision/dl/projects/1/corrections', { batch_run_id: 9, index: 3, label: '' }))
  })

  it('shows an unmeasured warning for a version without holdout', async () => {
    vi.spyOn(api, 'get').mockImplementation((path) => Promise.resolve(path.endsWith('/models') ? {
      items: [{ ...second, metrics: { holdout_count: 0, accuracy: null, error_count: 0, warning: 'No holdout set. Accuracy was not measured.' } }],
    } : routes(path)) as ReturnType<typeof api.get>)
    renderPage(<ModelVersionsPanel projectId={1} />)
    expect(await screen.findByText('No holdout set — accuracy not measured')).toBeInTheDocument()
    expect(screen.queryByText(/Accuracy 0\.0%/)).not.toBeInTheDocument()
  })
})
