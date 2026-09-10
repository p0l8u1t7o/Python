/** 看板的前端評估：與後端 board.build() 同一套規則——沒設定就全部具名輸出、公差判定、影像挑選、格式化。 */
import { describe, expect, it } from 'vitest'

import { evaluateValues, formatValue, pickImage, runToBoard } from '@/lib/board'
import { ACQUIRE_TYPES, lastImage } from '@/lib/runImages'
import type { RunReport } from '@/lib/types'

const run: RunReport = {
  id: 'r1', flow_id: 1, flow_version: 1, trigger: 'api', status: 'ng', started_at: 1, finished_at: 2, duration_ms: 12.5, error: '',
  // 10.26 而不是 10.25：JS 的 toFixed 與 Python 的格式化在「剛好一半」的進位方式不同，看板不靠那一位
  outputs: { judge: 'NG', judge_label: 'gap', width: 10.26, height: 4, text: 'OK,10.26' },
  nodes: {
    src: { status: 'ok', duration_ms: 1, message: '', outputs: { image: { ref: 'r1:src:image', width: 64, height: 48 } }, overlays: [] },
    blur: { status: 'ok', duration_ms: 1, message: '', outputs: { image: { ref: 'r1:blur:image', width: 64, height: 48 } }, overlays: [{ kind: 'point', x: 1, y: 2 }] },
    j: { status: 'ng', duration_ms: 1, message: '', outputs: { verdict: 'NG' }, overlays: [] },
  },
} as unknown as RunReport

describe('board evaluation', () => {
  it('uses tool types for arbitrary ids and does not mistake a node named draw for a result', () => {
    const renamed = { ...run, nodes: { n3: run.nodes.src, draw: run.nodes.blur } }
    for (const kind of ACQUIRE_TYPES) {
      const types = { n3: kind, draw: 'threshold' }
      expect(pickImage(renamed, undefined, types)?.ref).toBe('r1:src:image')
      expect(lastImage(renamed, types)?.ref).toBe('r1:src:image')
      expect(runToBoard(renamed, {}, types).image?.ref).toBe('r1:src:image')
      expect(pickImage(renamed, 'draw', types)?.ref).toBe('r1:blur:image')
    }
    const withDraw = { ...renamed, nodes: { ...renamed.nodes, n7: { ...run.nodes.blur, outputs: { image: { ref: 'r1:n7:image', width: 64, height: 48 } } } } }
    const types = { n3: 'multi_light_grab', draw: 'threshold', n7: 'draw_result' }
    expect(lastImage(withDraw, types)?.ref).toBe('r1:n7:image')
    expect(pickImage(withDraw, undefined, types)?.ref).toBe('r1:n7:image')
    expect(lastImage(renamed)?.ref).toBe('r1:blur:image')
    expect(lastImage(renamed, {})?.ref).toBe('r1:blur:image')
  })

  it('prefers the image port and ignores implicit pass-throughs when types are supplied', () => {
    const report = { ...run, nodes: { n3: { ...run.nodes.src, outputs: {
      mask: { ref: 'r1:n3:mask', width: 64, height: 48 },
      image: { ref: 'r1:n3:image', width: 64, height: 48 },
    } } } }
    expect(lastImage(report, {})?.ref).toBe('r1:n3:image')
    expect(pickImage(report, undefined, {})?.ref).toBe('r1:n3:image')
    const implicit = { ...run, nodes: { n3: { ...run.nodes.src, outputs: { _image: { ref: 'r1:n3:_image', width: 64, height: 48 } } } } }
    expect(lastImage(implicit, {})).toBeNull()
    expect(pickImage(implicit, undefined, {})).toBeNull()
    expect(lastImage(implicit)?.ref).toBe('r1:n3:_image')
  })

  it('shows every named output when nothing is configured', () => {
    const values = evaluateValues(undefined, run.outputs as Record<string, unknown>)
    expect(values.map((v) => v.key)).toEqual(['width', 'height', 'text'])
    expect(values.every((v) => v.ok === null)).toBe(true)
  })

  it('applies labels, units, decimals and tolerance like the server', () => {
    const values = evaluateValues({ values: [{ key: 'width', label: 'Width', unit: 'mm', decimals: 1, low: 9.8, high: 10.2 }, { key: 'height', low: 5 }, { key: 'missing' }] }, run.outputs as Record<string, unknown>)
    expect(values[0]).toMatchObject({ label: 'Width', unit: 'mm', text: '10.3', ok: false })
    expect(values[1]).toMatchObject({ text: '4', ok: false })
    expect(values[2]).toMatchObject({ present: false, ok: null, text: '' })
  })

  it('formats numbers and booleans', () => {
    expect(formatValue(3)).toBe('3')
    expect(formatValue(3.14159)).toBe('3.142')
    expect(formatValue(3.14159, 1)).toBe('3.1')
    expect(formatValue(true)).toBe('OK')
    expect(formatValue(null)).toBe('')
  })

  it('picks the configured node image, else draw/source image, and summarises the run', () => {
    expect(pickImage(run)?.ref).toBe('r1:src:image')
    expect(pickImage(run, 'src')?.ref).toBe('r1:src:image')
    expect(pickImage(run, 'nope')?.ref).toBe('r1:src:image')
    const withDraw = { ...run, nodes: { ...run.nodes, draw: { status: 'ok', duration_ms: 1, message: '', outputs: { image: { ref: 'r1:draw:image', width: 64, height: 48 } }, overlays: [] } } } as unknown as RunReport
    expect(pickImage(withDraw)?.ref).toBe('r1:draw:image')
    const summary = runToBoard(run, { image: 'src', overlays: false })
    expect(summary.verdict).toBe('NG')
    expect(summary.label).toBe('gap')
    expect(summary.image?.ref).toBe('r1:src:image')
    expect(summary.overlays).toEqual([])
    expect(runToBoard(run).overlays.length).toBe(1)
  })
})
