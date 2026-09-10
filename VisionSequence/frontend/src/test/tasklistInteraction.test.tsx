/** 卡片只套用同流程當下草稿，並保留未知與缺失欄位供修正。 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installApiMock } from './apiMock'
import { renderPage } from './render'
installApiMock()
import { TaskListCard } from '@/components/assistant/TaskListCard'
import { api } from '@/lib/api'
import { setAssistantContext } from '@/lib/assistantContext'
import type { FlowGraph, TaskDraft } from '@/lib/types'

const graph: FlowGraph = { nodes: [{ id: 'src', type: 'image_source', params: { mode: 'input' } }], edges: [] }
const draft: TaskDraft = { draft_id: 'd', op: 'add', kind: 'count_objects', fields: { min_count: { value: 5, status: 'assumed', source: 'rule', note: '' } }, regions: [] }

describe('task list apply', () => {
  beforeEach(() => { vi.mocked(api.post).mockClear(); setAssistantContext(null) })
  it('uses the current page graph, confirms the proposal, and marks the page draft', async () => {
    const applyGraph = vi.fn(), onChange = vi.fn()
    const context = { kind: 'inspect' as const, flowId: 1, getGraph: () => graph, applyGraph }
    setAssistantContext(context)
    const next = { ...graph, nodes: [...graph.nodes, { id: 'new', type: 'blob', params: {} }] }
    vi.mocked(api.post).mockResolvedValueOnce({ graph: next, tasks: [], applied: ['d'], skipped: [] })
    renderPage(<TaskListCard context={context} flowId={1} drafts={[draft]} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm all' }))
    await waitFor(() => expect(applyGraph).toHaveBeenCalledWith(next, ''))
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ graph, confirmations: { d: { confirmed: true } } })
    expect(onChange).toHaveBeenCalledWith([])
  })
  it('keeps the card and does not overwrite newer graph changes', async () => {
    const applyGraph = vi.fn(), onChange = vi.fn()
    let current = graph
    const context = { kind: 'inspect' as const, flowId: 1, getGraph: () => current, applyGraph }
    setAssistantContext(context)
    let resolve!: (v: unknown) => void
    vi.mocked(api.post).mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    renderPage(<TaskListCard context={context} flowId={1} drafts={[draft]} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm all' }))
    await waitFor(() => expect(resolve).toBeTypeOf('function'))
    current = { ...graph, nodes: [] }
    resolve({ graph, applied: ['d'], tasks: [], skipped: [] })
    expect(await screen.findByRole('alert')).toHaveTextContent('The flow changed')
    expect(applyGraph).not.toHaveBeenCalled()
    expect(onChange).not.toHaveBeenCalled()
  })
  it('disables application from another flow and for a read-only page', () => {
    renderPage(<TaskListCard context={{ kind: 'inspect', flowId: 2 }} flowId={1} drafts={[draft]} onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Confirm all' })).toBeDisabled()
  })
})
