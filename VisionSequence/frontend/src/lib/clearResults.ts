import type { RunReport } from '@/lib/types'

export interface VisibleRunSelection {
  pinnedRunId: string | null
  previewRun: RunReport | null
  recentRuns: RunReport[]
  clearedRunId: string | null
}

/** 選出結果面板目前可見的執行結果並套用清空狀態 */
export function selectVisibleRun({ pinnedRunId, previewRun, recentRuns, clearedRunId }: VisibleRunSelection): RunReport | null {
  let run: RunReport | null
  if (pinnedRunId) {
    run = previewRun?.id === pinnedRunId ? previewRun : recentRuns.find((item) => item.id === pinnedRunId) ?? previewRun ?? recentRuns[0] ?? null
    return run?.id === clearedRunId ? null : run
  }
  const latestRun = recentRuns[0] ?? null
  if (!previewRun) run = latestRun
  else if (!latestRun || previewRun.started_at >= latestRun.started_at) run = previewRun
  else run = latestRun
  return run?.id === clearedRunId ? null : run
}
