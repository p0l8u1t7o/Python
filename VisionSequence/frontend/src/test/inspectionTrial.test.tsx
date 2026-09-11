/** 伺服器讀值的跨瀏覽器還原與非阻塞儲存。 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { INSPECT_GRAPH, installApiMock } from './apiMock'
import { InspectPage } from '@/pages/InspectPage'
import { api } from '@/lib/api'
import { clearSession, getSession, setDraft, updateSession } from '@/lib/flowDraft'
import { forgetInspectionRun, inspectGraphHash, inspectionRunFor, inspectionTrialPayload, rememberInspectionRun } from '@/lib/inspect'
import type { FlowGraph, InspectionTrial, InspectReading, RunReport } from '@/lib/types'
import { AuthProvider } from '@/providers/AuthProvider'
import { ThemeProvider } from '@/providers/ThemeProvider'
import { ToastProvider } from '@/providers/ToastProvider'

installApiMock()
vi.mock('@/lib/flowStream', () => ({ useLockEvents: () => {}, useFlowEvents: () => {}, useFlowStream: () => ({ events: [], seq: 0, connected: false, runningIds: new Set() }), subscribeStream: () => () => {}, setStreamClient: () => {} }))
vi.mock('@/components/viewer/ImageViewer', () => ({ ImageViewer: ({ overlays }: { overlays: unknown[] }) => <div data-testid="trial-overlays">{JSON.stringify(overlays)}</div> }))

const reading: InspectReading = { task_id: 'd', verdict: 'pass', valid: true, detected: true, value: 35.125, unit: 'mm', reason: 'Within tolerance', overlays: [], node_id: 'd_tol' }
const report: RunReport = { id: 'preview', flow_id: 6, flow_version: 1, trigger: 'preview', status: 'ok',
  started_at: 1789100000, finished_at: 1789100000, duration_ms: 1, error: '', outputs: { judge: 'OK' }, nodes: {} }
const trial = (): InspectionTrial => ({ ...inspectionTrialPayload(INSPECT_GRAPH, report, [reading]), hash: inspectGraphHash(INSPECT_GRAPH), executed_by: 'another-user' })
const path = '/vision/inspect/6/last-trial'

function showPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  const router = createMemoryRouter([{ path: '/flows/:flowId/inspect', element: <InspectPage /> }], { initialEntries: ['/flows/6/inspect'] })
  return render(<QueryClientProvider client={client}><ThemeProvider><ToastProvider><AuthProvider><RouterProvider router={router} /></AuthProvider></ToastProvider></ThemeProvider></QueryClientProvider>)
}

describe('server inspection trials', () => {
  beforeEach(() => { clearSession(6); forgetInspectionRun(6); vi.mocked(api.put).mockClear() })

  it('saves after preview and restores in a fresh browser without stale or image state', async () => {
    let saved: InspectionTrial | null = null
    const get = vi.mocked(api.get).getMockImplementation()!
    const post = vi.mocked(api.post).getMockImplementation()!
    await vi.mocked(api.get).withImplementation(async (url) => url === path ? { trial: saved } : get(url), async () => {
      await vi.mocked(api.put).withImplementation(async (_url, body) => {
        const payload = body as ReturnType<typeof inspectionTrialPayload>
        saved = { ...payload, hash: inspectGraphHash(payload.graph), executed_by: 'user-a' }
        return { saved: true }
      }, async () => {
        await vi.mocked(api.post).withImplementation(async (url, body) => url === '/vision/inspect/evidence' ? { items: [reading] } : post(url, body), async () => {
          const page = showPage()
          await screen.findByTestId('inspect-task')
          fireEvent.click(screen.getByTestId('inspect-run'))
          await screen.findByText('35.125 mm')
          await waitFor(() => expect(api.put).toHaveBeenCalledWith(path, expect.objectContaining({ readings: [expect.objectContaining({ value: 35.125, status: 'pass' })] })))
          page.unmount(); clearSession(6); forgetInspectionRun(6)
          expect(localStorage.getItem('vs.inspectionRun.v1:6')).toBeNull()
          showPage()
          await screen.findByText('35.125 mm')
          expect(within(screen.getByTestId('inspect-reading')).queryByText('Stale')).not.toBeInTheDocument()
          expect(getSession(6).previewRun).toBeNull()
        })
      })
    })
  })

  it('prefers server over device readings and marks edits or restored versions stale', async () => {
    const get = vi.mocked(api.get).getMockImplementation()!
    await vi.mocked(api.get).withImplementation(async (url) => url === path ? { trial: trial() } : get(url), async () => {
      for (const threshold of [46, 60]) {
        rememberInspectionRun(6, INSPECT_GRAPH, report, [{ ...reading, value: 99 }])
        const changed = structuredClone(INSPECT_GRAPH)
        changed.nodes[0].params = { ...changed.nodes[0].params, threshold }
        setDraft(6, { graph: changed, name: 'Changed', description: '', baseVersion: 1, dirty: true })
        const page = showPage()
        await screen.findByText('35.125 mm')
        expect(within(screen.getByTestId('inspect-reading')).getByText('Stale')).toBeInTheDocument()
        expect(screen.queryByText('99 mm')).not.toBeInTheDocument()
        page.unmount(); clearSession(6)
      }
    })
  })

  it.each(['missing', 'offline'])('falls back to the device when the server is %s', async (mode) => {
    rememberInspectionRun(6, INSPECT_GRAPH, report, [reading])
    const get = vi.mocked(api.get).getMockImplementation()!
    await vi.mocked(api.get).withImplementation(async (url) => {
      if (url !== path) return get(url)
      if (mode === 'offline') throw new Error('Offline')
      return { trial: null }
    }, async () => {
      showPage()
      await screen.findByText('35.125 mm')
      expect(within(screen.getByTestId('inspect-reading')).queryByText('Stale')).not.toBeInTheDocument()
    })
  })

  it('displays a fresh preview while PUT is pending and ignores a delayed old GET', async () => {
    let resolveRead!: (value: { trial: InspectionTrial }) => void
    let rejectWrite!: (error: Error) => void
    const get = vi.mocked(api.get).getMockImplementation()!
    const post = vi.mocked(api.post).getMockImplementation()!
    await vi.mocked(api.get).withImplementation(async (url) => url === path ? new Promise((resolve) => { resolveRead = resolve }) : get(url), async () => {
      await vi.mocked(api.put).withImplementation(async () => new Promise((_resolve, reject) => { rejectWrite = reject }), async () => {
        await vi.mocked(api.post).withImplementation(async (url, body) => url === '/vision/inspect/evidence' ? { items: [{ ...reading, value: 42 }] } : post(url, body), async () => {
          showPage()
          await screen.findByTestId('inspect-task')
          fireEvent.click(screen.getByTestId('inspect-run'))
          await screen.findByText('42 mm')
          expect(screen.getByTestId('inspect-run')).toBeEnabled()
          await act(async () => resolveRead({ trial: trial() }))
          expect(screen.queryByText('35.125 mm')).not.toBeInTheDocument()
          await act(async () => rejectWrite(new Error('Offline')))
          expect(inspectionRunFor(6, null)?.readings[0].value).toBe(42)
        })
      })
    })
  })

  it('matches the backend Unicode and exact-number signature vector and reads legacy device signatures', () => {
    const graph = { nodes: [], edges: [], Z: [1.0, -0, 1e-7, 1e21], a: '杯😀\n', _: true } as FlowGraph
    expect(inspectGraphHash(graph)).toBe('v2:{"Z":[n:3ff0000000000000,n:0000000000000000,n:3e7ad7f29abcaf48,n:444b1ae4d6e2ef50],"_":true,"a":"\\u676f\\ud83d\\ude00\\n","edges":[],"nodes":[]}')
    localStorage.setItem('vs.inspectionRun.v1:6', JSON.stringify({ hash: JSON.stringify(INSPECT_GRAPH), status: 'ok', readings: [reading] }))
    expect(inspectionRunFor(6, null)?.hash).toBe(inspectGraphHash(INSPECT_GRAPH))
    const payload = inspectionTrialPayload(INSPECT_GRAPH, report, [{ ...reading, value: { ref: 'secret' }, overlays: [{ kind: 'point', x: 1, y: 2 }] }])
    expect(payload.readings[0].value).toBeNull()
    expect(JSON.stringify(payload.readings)).not.toContain('secret')
    expect(JSON.stringify(payload.readings)).not.toContain('overlays')
  })

  it('retains the full in-memory report when the server describes the same trial', async () => {
    const overlays: InspectReading['overlays'] = [{ kind: 'point', x: 12, y: 14 }]
    rememberInspectionRun(6, INSPECT_GRAPH, report, [{ ...reading, overlays }])
    updateSession(6, { previewRun: report })
    const get = vi.mocked(api.get).getMockImplementation()!
    await vi.mocked(api.get).withImplementation(async (url) => url === path ? { trial: trial() } : get(url), async () => {
      showPage()
      await screen.findByText('35.125 mm')
      expect(screen.getByTestId('trial-overlays')).toHaveTextContent(JSON.stringify(overlays))
    })
  })

  it('does not resurrect old readings when a delayed GET finishes after changing source', async () => {
    let resolveRead!: (value: { trial: InspectionTrial }) => void
    const get = vi.mocked(api.get).getMockImplementation()!
    await vi.mocked(api.get).withImplementation(async (url) => url === path ? new Promise((resolve) => { resolveRead = resolve }) : get(url), async () => {
      showPage()
      await screen.findByTestId('inspect-task')
      fireEvent.change(screen.getByTestId('inspect-source'), { target: { value: 'fixed' } })
      await screen.findByTestId('inspect-fixed-images')
      await act(async () => resolveRead({ trial: trial() }))
      expect(screen.queryByText('35.125 mm')).not.toBeInTheDocument()
      expect(within(screen.getByTestId('inspect-reading')).getByText('Not run')).toBeInTheDocument()
    })
  })
})
