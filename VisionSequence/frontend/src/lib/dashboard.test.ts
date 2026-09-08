import { describe, expect, it } from 'vitest'

import { evalRule, imageOf, resolveFlow, templateText, valueOf } from '@/lib/dashboard'
import type { DashboardData, DashboardLayout, DashboardWidget, RunReport } from '@/lib/types'

const layout: DashboardLayout = {
  rows: 1,
  cols: 1,
  cells: [{ id: 'main', row: 1, col: 1, row_span: 1, col_span: 1 }],
  bars: { top: true },
  default_flow_id: 7,
  widgets: [],
}

const data: DashboardData = {
  generated_at: '2026-09-08T00:00:00Z',
  flows: {
    '7': {
      flow: { id: 7, name: 'Gauge', title: 'Gauge' },
      config: { title: 'Gauge', image: 'camera', overlays: true, values: [{ key: 'width' }], variables: ['lot'], show_verdict: true, show_counts: true },
      run: { id: 'r1', status: 'ok', verdict: 'OK', label: '', started_at: 1, duration_ms: 42, trigger: 'ui', recipe: '', error: '', image: { ref: 'run:image', width: 640, height: 480 }, overlays: [] },
      values: [{ key: 'width', label: 'Width', unit: 'mm', value: 10.2, text: '10.2', ok: true, present: true }],
      variables: { lot: 'A1' },
      counts: { date: '2026-09-08', total: 10, ok: 8, ng: 1, failed: 1, yield: 0.8 },
      stats: { cpk: 1.4 },
    },
  },
  device: {
    station_id: 'station-01',
    version: '1.2.3',
    lock: { locked: false, holder: '', reason: '' },
    capacity: { max_workers: 2, active: 1, flows: [], images: { images: 1, bytes: 2, runs: 3 } },
    flows_running: [7],
  },
  variables: { station: { shift: 'day' } },
}

describe('dashboard helpers', () => {
  it('resolves explicit, prop and default flow ids', () => {
    expect(resolveFlow({ id: 'a', type: 'text', source: { flow_id: 9 } }, layout)).toBe(9)
    expect(resolveFlow({ id: 'b', type: 'text', props: { flow_id: '8' } }, layout)).toBe(8)
    expect(resolveFlow({ id: 'c', type: 'text' }, layout)).toBe(7)
  })

  it('reads values from flow data and station data', () => {
    expect(valueOf(data, 7, 'width')).toBe(10.2)
    expect(valueOf(data, 7, 'lot')).toBe('A1')
    expect(valueOf(data, 7, 'yield')).toBe(0.8)
    expect(valueOf(data, 7, 'station.shift')).toBe('day')
  })

  it('evaluates comparison rules', () => {
    expect(evalRule('gt', 5, 4)).toBe(true)
    expect(evalRule('between', '5', 4, 6)).toBe(true)
    expect(evalRule('contains', 'line station', 'station')).toBe(true)
    expect(evalRule('lte', 7, 6)).toBe(false)
  })

  it('renders templates and prefers live images', () => {
    const live: RunReport = {
      id: 'r2',
      flow_id: 7,
      flow_version: 2,
      trigger: 'ui',
      status: 'ng',
      started_at: 10,
      finished_at: 20,
      duration_ms: 50,
      error: '',
      outputs: { width: 12.5, judge: 'NG' },
      nodes: {
        camera: { status: 'ok', duration_ms: 1, message: '', branch: null, outputs: { image: { ref: 'live:image', width: 320, height: 240 } }, overlays: [], overlay_on: null, detail: {}, logs: [] },
      },
    }
    const widget: DashboardWidget = { id: 'img', type: 'image', props: { node: 'camera' } }
    expect(templateText('{flow} {run_id} {width} {station.shift}', data, 7, live)).toBe('Gauge r2 12.5 day')
    expect(imageOf(data, 7, widget, live)?.ref).toBe('live:image')
  })
})
