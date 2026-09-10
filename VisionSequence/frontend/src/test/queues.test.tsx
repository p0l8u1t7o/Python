/** 佇列卡的顯示、清空與角色權限回歸。 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueuesCard } from '@/components/flow/QueuesCard'

const mocks = vi.hoisted(() => ({
  can: vi.fn(), refetch: vi.fn(), remove: vi.fn(), error: vi.fn(),
  state: { isLoading: false, error: null as unknown, data: { items: [{ name: 'parts', size: 5, oldest_age_ms: 120, dropped: 2 }] } },
}))
vi.mock('@/providers/AuthProvider', () => ({ useAuth: () => ({ can: mocks.can }) }))
vi.mock('@/providers/ToastProvider', () => ({ useToast: () => ({ error: mocks.error }) }))
vi.mock('@/lib/queries', () => ({ useQueues: () => ({ ...mocks.state, refetch: mocks.refetch }) }))
vi.mock('@/lib/api', async (original) => ({ ...await original<typeof import('@/lib/api')>(), api: { delete: mocks.remove } }))

describe('queues card', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.can.mockReturnValue(true)
    mocks.remove.mockResolvedValue({ removed: 5 })
    mocks.refetch.mockResolvedValue({})
    mocks.state.data.items = [{ name: 'parts', size: 5, oldest_age_ms: 120, dropped: 2 }]
    mocks.state.error = null
  })
  it('shows the queue summary and clears it through the API', async () => {
    render(<QueuesCard />)
    expect(screen.getByText('5 items · oldest 120 ms · 2 dropped')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith('/vision/queues/parts'))
    await waitFor(() => expect(mocks.refetch).toHaveBeenCalledOnce())
  })
  it('hides the card without integration and hides clearing for a reader', () => {
    mocks.can.mockReturnValue(false)
    const view = render(<QueuesCard />)
    expect(screen.queryByTestId('queues-card')).not.toBeInTheDocument()
    mocks.can.mockImplementation((feature: string) => feature === 'integration')
    view.rerender(<QueuesCard />)
    expect(screen.getByText('parts')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument()
  })
  it('allows flows.edit and reports errors without hiding the queue', async () => {
    mocks.can.mockImplementation((feature: string) => feature === 'integration' || feature === 'flows.edit')
    mocks.remove.mockRejectedValue(new Error('Queue unavailable'))
    render(<QueuesCard />)
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith('Queue unavailable'))
    expect(screen.getByText('parts')).toBeInTheDocument()
  })
  it('shows the empty state and refreshes', () => {
    mocks.state.data.items = []
    render(<QueuesCard />)
    expect(screen.getByText('No queues yet.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(mocks.refetch).toHaveBeenCalledOnce()
  })
})
