/**
 * 看板：設定型別，以及在前端依設定評估數值（與後端 apps/vision/board.py 的 build() 同一套規則），
 * 讓 SSE 每來一次 run 就能即時更新，不必每片都回頭打 GET /board。
 */
import type { RunReport } from '@/lib/types'

export interface BoardValueConfig {
  key: string
  label?: string
  unit?: string
  decimals?: number
  low?: number
  high?: number
}

export interface BoardConfig {
  title?: string
  image?: string
  overlays?: boolean
  values?: BoardValueConfig[]
  variables?: string[]
  show_verdict?: boolean
  show_counts?: boolean
}

export interface BoardValue {
  key: string
  label: string
  unit: string
  value: unknown
  text: string
  ok: boolean | null
  present: boolean
}

export interface BoardCounts {
  date: string
  total: number
  ok: number
  ng: number
  failed: number
  yield: number | null
}

export interface BoardRun {
  id: string
  status: string
  verdict: string | null
  label: string
  started_at: number
  duration_ms: number
  trigger: string
  recipe: string
  error: string
  image: { ref: string; width: number; height: number } | null
  overlays: RunReport['nodes'][string]['overlays']
}

export interface BoardData {
  flow: { id: number; name: string; title: string }
  config: Required<Pick<BoardConfig, 'title' | 'image' | 'overlays' | 'values' | 'variables' | 'show_verdict' | 'show_counts'>>
  run: BoardRun | null
  values: BoardValue[]
  variables: Record<string, unknown>
  counts: BoardCounts | null
  stats: Record<string, unknown>
}

const HIDDEN = new Set(['judge', 'judge_label'])

export function formatValue(value: unknown, decimals?: number): string {
  if (typeof value === 'boolean') return value ? 'OK' : 'NG'
  if (typeof value === 'number') {
    if (decimals === undefined) return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)))
    return value.toFixed(decimals)
  }
  if (value === null || value === undefined) return ''
  return String(value).slice(0, 120)
}

/** 依看板設定挑出要顯示的具名輸出並做公差判定；沒設定就顯示全部（judge 除外）。 */
export function evaluateValues(config: BoardConfig | undefined, outputs: Record<string, unknown>): BoardValue[] {
  const wanted: BoardValueConfig[] = config?.values?.length ? config.values : Object.keys(outputs).filter((k) => !HIDDEN.has(k)).map((key) => ({ key }))
  return wanted.map((item) => {
    const value = outputs[item.key]
    const num = typeof value === 'number' && Number.isFinite(value) ? value : typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value)) ? Number(value) : null
    let ok: boolean | null = null
    if (num !== null && (item.low !== undefined || item.high !== undefined)) {
      ok = (item.low === undefined || num >= item.low) && (item.high === undefined || num <= item.high)
    }
    return { key: item.key, label: item.label || item.key, unit: item.unit ?? '', value, text: formatValue(value, item.decimals), ok, present: item.key in outputs }
  })
}

/** 指定節點的影像，否則該次 run 最後一張。 */
export function pickImage(run: RunReport, nodeId?: string): { ref: string; width: number; height: number } | null {
  const nodes = run.nodes ?? {}
  const imageOf = (report: RunReport['nodes'][string]) => {
    const outputs = (report.outputs ?? {}) as Record<string, unknown>
    for (const key of ['image', ...Object.keys(outputs).filter((k) => k !== '_image')]) {
      const v = outputs[key] as { ref?: string; width?: number; height?: number } | undefined
      if (v && typeof v === 'object' && v.ref && typeof v.width === 'number' && typeof v.height === 'number') return { ref: v.ref, width: v.width, height: v.height }
    }
    return null
  }
  if (nodeId && nodes[nodeId]) {
    const found = imageOf(nodes[nodeId])
    if (found) return found
  }
  for (const report of Object.values(nodes).reverse()) {
    const found = imageOf(report)
    if (found) return found
  }
  return null
}

/** RunReport → 看板的 run 摘要（SSE 事件進來時用，與後端 build() 同形）。 */
export function runToBoard(run: RunReport, config?: BoardConfig): BoardRun {
  const outputs = run.outputs as Record<string, unknown>
  const verdict = (outputs.judge as string | undefined) ?? (run.status === 'ok' ? 'OK' : run.status === 'ng' ? 'NG' : run.status.toUpperCase())
  const overlays = config?.overlays === false ? [] : Object.values(run.nodes ?? {}).flatMap((n) => n.overlays ?? [])
  return {
    id: run.id, status: run.status, verdict, label: String(outputs.judge_label ?? ''), started_at: run.started_at, duration_ms: run.duration_ms,
    trigger: run.trigger, recipe: run.recipe ?? '', error: run.error ?? '', image: pickImage(run, config?.image), overlays,
  }
}
