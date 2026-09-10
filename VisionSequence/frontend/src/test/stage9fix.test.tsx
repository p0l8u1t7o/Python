/** 任務頁的新增狀態、固定影像及裝置讀值還原回歸。 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FLOW, INSPECT_GRAPH, INSPECT_KINDS, installApiMock } from './apiMock'
import { InspectPage } from '@/pages/InspectPage'
import { api } from '@/lib/api'
import { clearSession, getSession, setDraft } from '@/lib/flowDraft'
import { forgetInspectionRun, inspectionHasImage, inspectionRunFor, inspectionStale, inspectionValue, rememberInspectionRun } from '@/lib/inspect'
import type { InspectReading, InspectTask, RunReport } from '@/lib/types'
import { AuthProvider } from '@/providers/AuthProvider'
import { ThemeProvider } from '@/providers/ThemeProvider'
import { ToastProvider } from '@/providers/ToastProvider'

installApiMock()
vi.mock('@/lib/flowStream', () => ({ useLockEvents: () => {}, useFlowEvents: () => {}, useFlowStream: () => ({ events: [], seq: 0, connected: false, runningIds: new Set() }), subscribeStream: () => () => {}, setStreamClient: () => {} }))
vi.mock('@/components/viewer/ImageViewer', () => ({ ImageViewer: ({ overlays }: { overlays: unknown[] }) => <div data-testid="scene-overlays">{JSON.stringify(overlays)}</div> }))

const reading: InspectReading = { task_id: 'd', verdict: 'pass', valid: true, detected: true, value: 35.012385823320194, unit: 'mm', reason: '', overlays: [{ kind: 'point', x: 12, y: 14 }], node_id: 'd_tol' }
const report = { id: 'preview', status: 'ok', outputs: { judge: 'OK' }, nodes: { camera: { outputs: { image: { ref: 'secret-image-ref' } } } } } as unknown as RunReport

function showPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  const router = createMemoryRouter([{ path: '/flows/:flowId/inspect', element: <InspectPage /> }], { initialEntries: ['/flows/6/inspect'] })
  return render(<QueryClientProvider client={client}><ThemeProvider><ToastProvider><AuthProvider><RouterProvider router={router} /></AuthProvider></ToastProvider></ThemeProvider></QueryClientProvider>)
}

describe('stage9fix inspection', () => {
  beforeEach(() => { clearSession(6); forgetInspectionRun(6); vi.mocked(api.post).mockClear(); vi.mocked(api.patch).mockClear() })

  it('rounds by unit, keeps zero, and persists only summaries across a page reload', async () => {
    expect(inspectionValue(reading)).toBe('35.012')
    expect(inspectionValue({ ...reading, unit: 'px' })).toBe('35.01')
    expect(inspectionValue({ ...reading, unit: 'deg' })).toBe('35.01')
    expect(inspectionValue({ ...reading, unit: '', value: 12 })).toBe('12')
    expect(inspectionValue({ ...reading, value: 0 })).toBe('0')
    rememberInspectionRun(6, INSPECT_GRAPH, report, [reading])
    const saved = localStorage.getItem('vs.inspectionRun.v1:6')!
    expect(saved).not.toContain('secret-image-ref')
    expect(JSON.parse(saved).readings[0].overlays).toEqual([])
    const first = showPage()
    expect(await screen.findByText('35.012 mm')).toHaveAttribute('title', `${reading.value} mm`)
    expect(screen.getByTestId('scene-overlays')).toHaveTextContent('[]')
    first.unmount(); clearSession(6)
    const changed = structuredClone(INSPECT_GRAPH)
    changed.nodes[1].params!.calibration = 'different'
    setDraft(6, { graph: changed, name: 'Changed', description: '', baseVersion: 1, dirty: true })
    showPage()
    expect(await screen.findByText('35.012 mm')).toBeInTheDocument()
    expect(within(screen.getByTestId('inspect-reading')).getByText('Stale')).toBeInTheDocument()
    expect(inspectionStale(changed, inspectionRunFor(6, null)!.hash)).toBe(true)
    expect(inspectionRunFor(7, null)).toBeUndefined()
  })

  it('clears the previous reading and overlays when adding a task', async () => {
    rememberInspectionRun(6, INSPECT_GRAPH, report, [reading])
    showPage()
    expect(await screen.findByText('35.012 mm')).toBeInTheDocument()
    fireEvent.change(screen.getByTestId('inspect-add'), { target: { value: 'measure_diameter' } })
    expect(await within(screen.getByTestId('inspect-reading')).findByText('Not run')).toBeInTheDocument()
    expect(screen.queryByText('35.012 mm')).not.toBeInTheDocument()
    expect(screen.getByTestId('scene-overlays')).toHaveTextContent('[]')
  })

  it('offers the selected locator by name and number while adding another task', async () => {
    const get = vi.mocked(api.get).getMockImplementation()!
    const post = vi.mocked(api.post).getMockImplementation()!
    const kinds = structuredClone(INSPECT_KINDS)
    kinds[0].fields.push({ ...kinds[0].fields[0], key: 'locator', label: 'Locator', kind: 'text', required: false, default: '' })
    const locator: InspectTask = { task_id: 'raw_locator_id', kind: 'locate_part', version: 1, required: true, nodes: { find: 'loc_find' }, fields: {}, custom: false, reasons: [] }
    await vi.mocked(api.get).withImplementation(async (path) => path === '/vision/inspect/kinds' ? { items: kinds } : get(path), async () => {
      await vi.mocked(api.post).withImplementation(async (path, body) => path === '/vision/inspect/read' ? { tasks: [locator], shared: [], loose: [] } : post(path, body), async () => {
        showPage()
        await screen.findByTestId('inspect-task')
        fireEvent.change(screen.getByTestId('inspect-add'), { target: { value: 'measure_diameter' } })
        expect(await within(await screen.findByLabelText('Locator')).findByRole('option', { name: 'Locate part 1' })).toHaveValue('raw_locator_id')
      })
    })
  })

  it('blocks an empty source before preview and stores multiple uploaded fixed images in the saved graph', async () => {
    const postForm = vi.mocked(api.postForm).getMockImplementation()!
    const pictures = [{ id: 'fixed-one', name: 'one.png', width: 100, height: 80 }, { id: 'fixed-two', name: 'two.png', width: 100, height: 80 }]
    await vi.mocked(api.postForm).withImplementation(async (path, body) => path === '/vision/fixed-images' ? { items: pictures } : postForm(path, body), async () => {
      const page = showPage()
      await screen.findByTestId('inspect-task')
      fireEvent.change(screen.getByTestId('inspect-source'), { target: { value: 'fixed' } })
      const panel = await screen.findByTestId('inspect-fixed-images')
      fireEvent.click(screen.getByTestId('inspect-run'))
      expect(await screen.findByRole('alert')).toHaveTextContent('Select an image source')
      expect(vi.mocked(api.post).mock.calls.some(([path]) => path.includes('/preview'))).toBe(false)
      fireEvent.change(panel.querySelector('input[type="file"]')!, { target: { files: [new File(['1'], 'one.png', { type: 'image/png' }), new File(['2'], 'two.png', { type: 'image/png' })] } })
      await waitFor(() => expect(getSession(6).draft!.graph.nodes[0]).toMatchObject({ type: 'fixed_image', params: { images: pictures } }))
      expect(inspectionHasImage(getSession(6).draft!.graph)).toBe(true)
      await waitFor(() => expect(screen.getByTestId('inspect-save')).toBeEnabled())
      fireEvent.click(screen.getByTestId('inspect-save'))
      await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/vision/flows/6', expect.objectContaining({ graph: expect.objectContaining({ nodes: expect.arrayContaining([expect.objectContaining({ type: 'fixed_image', params: expect.objectContaining({ images: pictures }) })]) }) })))
      const saved = structuredClone(getSession(6).draft!.graph)
      page.unmount(); clearSession(6)
      const get = vi.mocked(api.get).getMockImplementation()!
      await vi.mocked(api.get).withImplementation(async (path) => path === '/vision/flows/6' ? { ...FLOW, id: 6, graph: saved } : get(path), async () => {
        showPage()
        const reopened = await screen.findByTestId('inspect-fixed-images')
        expect(within(reopened).getAllByRole('img')).toHaveLength(2)
        expect(screen.getByTestId('inspect-source')).toHaveValue('fixed')
      })
    })
  })

  it('rejects missing and reference-only images and corrupt local summaries', () => {
    expect(inspectionHasImage({ nodes: [], edges: [] })).toBe(false)
    expect(inspectionHasImage({ nodes: [{ id: 'ref', type: 'fixed_image', params: { role: 'reference', images: [{ id: 'one' }] } }], edges: [] })).toBe(false)
    localStorage.setItem('vs.inspectionRun.v1:6', '{bad')
    expect(inspectionRunFor(6, null)).toBeUndefined()
  })
})
