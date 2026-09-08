import { describe, expect, it } from 'vitest'

import { bindGridCell, gridCellImage, gridPlacement, normalizeGridLayout, setGridCount, type GridLayout } from '@/lib/gridView'
import type { RunReport } from '@/lib/types'

function run(): RunReport {
  return {
    id: 'r1',
    flow_id: 1,
    flow_version: 1,
    trigger: 'ui',
    status: 'ok',
    started_at: 1,
    finished_at: 2,
    duration_ms: 1,
    error: '',
    outputs: {},
    nodes: {
      camera: { status: 'ok', duration_ms: 1, message: '', branch: null, outputs: { image: { ref: 'cam', width: 640, height: 480 } }, overlays: [], overlay_on: null, detail: {}, logs: [] },
      step: { status: 'ok', duration_ms: 1, message: '', branch: null, outputs: { image: { ref: 'step', width: 320, height: 240 }, score: 0.9 }, overlays: [], overlay_on: null, detail: {}, logs: [] },
    },
  }
}

describe('gridView', () => {
  it('maps counts to stable layouts', () => {
    expect(gridPlacement(1)).toEqual({ rows: 1, cols: 1 })
    expect(gridPlacement(2)).toEqual({ rows: 1, cols: 2 })
    expect(gridPlacement(6)).toEqual({ rows: 2, cols: 3 })
    expect(gridPlacement(9)).toEqual({ rows: 3, cols: 3 })
  })

  it('preserves existing bindings when the count changes', () => {
    const layout = normalizeGridLayout({ count: 4, bindings: [{ nodeId: 'camera', port: 'image' }, { nodeId: 'step', port: 'image' }] })
    expect(setGridCount(layout, 2).bindings).toEqual([{ nodeId: 'camera', port: 'image' }, { nodeId: 'step', port: 'image' }])
    expect(setGridCount(layout, 6).bindings.slice(0, 4)).toEqual([{ nodeId: 'camera', port: 'image' }, { nodeId: 'step', port: 'image' }, null, null])
  })

  it('binds, clears and removes nodes that no longer exist', () => {
    let layout: GridLayout = normalizeGridLayout({ count: 4 })
    layout = bindGridCell(layout, 1, { nodeId: 'step', port: 'image' })
    expect(layout.bindings[1]).toEqual({ nodeId: 'step', port: 'image' })
    layout = bindGridCell(layout, 1, null)
    expect(layout.bindings[1]).toBeNull()
    layout = bindGridCell(layout, 0, { nodeId: 'gone', port: 'image' })
    expect(gridCellImage(run(), layout.bindings[0], ['camera', 'step'])).toBeNull()
  })

  it('returns null when the port has no image', () => {
    expect(gridCellImage(run(), { nodeId: 'step', port: 'score' }, ['camera', 'step'])).toBeNull()
    expect(gridCellImage(run(), { nodeId: 'missing', port: 'image' }, ['camera', 'step'])).toBeNull()
  })

  it('gets the requested image from the run report', () => {
    expect(gridCellImage(run(), { nodeId: 'step', port: 'image' }, ['camera', 'step'])).toEqual({ ref: 'step', width: 320, height: 240 })
  })
})
