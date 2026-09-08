import { describe, expect, it } from 'vitest'

import { selectVisibleRun } from './clearResults'
import type { RunReport } from '@/lib/types'

function run(id: string, started_at: number): RunReport {
  return {
    id,
    flow_id: 1,
    flow_version: 1,
    trigger: 'preview',
    status: 'ok',
    started_at,
    finished_at: started_at + 1,
    duration_ms: 1,
    error: '',
    outputs: {},
    nodes: {},
  }
}

describe('selectVisibleRun', () => {
  it('hides the currently cleared run', () => {
    const latest = run('latest', 20)
    expect(selectVisibleRun({ pinnedRunId: null, previewRun: latest, recentRuns: [], clearedRunId: 'latest' })).toBeNull()
  })

  it('prefers the newest preview or recent run', () => {
    const preview = run('preview', 30)
    const recent = run('recent', 20)
    expect(selectVisibleRun({ pinnedRunId: null, previewRun: preview, recentRuns: [recent], clearedRunId: null })?.id).toBe('preview')
    expect(selectVisibleRun({ pinnedRunId: null, previewRun: recent, recentRuns: [preview], clearedRunId: null })?.id).toBe('preview')
  })

  it('keeps an explicitly pinned run unless that run was cleared', () => {
    const older = run('older', 10)
    const newer = run('newer', 20)
    expect(selectVisibleRun({ pinnedRunId: 'older', previewRun: null, recentRuns: [newer, older], clearedRunId: null })?.id).toBe('older')
    expect(selectVisibleRun({ pinnedRunId: 'older', previewRun: null, recentRuns: [newer, older], clearedRunId: 'older' })).toBeNull()
  })
})
