/**
 * 批次測試（/batch）的型別與資料層：影像集 BatchSet、批次執行 BatchRun、洞察、比較、AI 諮詢。
 * 後端 apps/vision/batch/api.py；執行中每秒輪詢 GET /batch/runs/{id} 顯示進度。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { BASE_URL, api, withKey } from '@/lib/api'
import type { FlowGraph, RunReport } from '@/lib/types'

export type Expected = '' | 'ok' | 'ng'
export type BatchOrigin = 'manual' | 'draft' | 'autotune' | 'ai_tune'
export type BatchRunStatus = 'queued' | 'running' | 'done' | 'cancelled' | 'failed'

export interface BatchImage {
  index: number
  name: string
  width: number
  height: number
  expected: Expected
  expect_outputs: Record<string, unknown>
  note: string
  image_url: string
}

export interface Stats {
  n: number
  min?: number
  max?: number
  mean?: number
  std?: number
}

export interface BatchRunSummary {
  total: number
  ok: number
  ng: number
  failed: number
  avg_ms: number
  max_ms: number
  wall_ms: number
  labeled: number
  match: number
  match_rate: number | null
  confusion: { tp: number; fp: number; tn: number; fn: number }
}

export interface BatchNodeResult {
  status: string
  duration_ms: number
  message: string
  branch: string | null
  outputs: Record<string, unknown>
}

export interface BatchRunItem {
  index: number
  status: string
  duration_ms: number
  outputs: Record<string, unknown>
  error: string
  error_node: string | null
  nodes: Record<string, BatchNodeResult>
  name: string
  expected: Expected
  match: boolean | null
  reasons: string[]
  image_url: string
}

export interface BatchRun {
  id: number
  set_id: number
  flow_id: number
  flow_version: number
  label: string
  note: string
  origin: BatchOrigin
  status: BatchRunStatus
  progress: { done: number; total: number; stage: string }
  summary: Partial<BatchRunSummary>
  parent_id: number | null
  owner_id: number | null
  recipe_name: string
  meta: Record<string, unknown>
  error: string
  created_at: string | null
  finished_at: string | null
  duration_s: number
  items?: BatchRunItem[]
  graph?: FlowGraph
}

export interface BatchSet {
  id: number
  flow_id: number
  name: string
  source: string
  image_count: number
  size_bytes: number
  owner_id: number | null
  labeled: { ok: number; ng: number }
  created_at: string | null
  updated_at: string | null
  images?: BatchImage[]
  latest_run?: BatchRun
  can_manage?: boolean
}

export interface BatchSetList {
  items: BatchSet[]
  total: number
  max_images: number
  keep_sets: number
  keep_runs: number
}

export interface Suggestion {
  node: string
  label: string
  key: string
  value: unknown
  reason: string
}

export interface BatchJudge {
  node: string
  label: string
  type: string
  value_from: { node: string; port: string; label: string }
  current: Record<string, unknown>
  values: Record<'expected_ok' | 'expected_ng' | 'status_ok' | 'status_ng', Stats>
  suggestion: Record<string, number> | null
  acc_now: number | null
  acc_suggested: number | null
  separable: boolean | null
  deviation?: Record<string, Stats>
}

export interface ParamDiff {
  rows: { node: string; label: string; type: string; key: string; from: unknown; to: unknown }[]
  added: string[]
  removed: string[]
}

export interface BatchInsights {
  ready: boolean
  status: string
  labeled: number
  match: number
  match_rate: number | null
  confusion: { tp: number; fp: number; tn: number; fn: number }
  mismatches: { index: number; name: string; expected: string; status: string; error_node: string | null; reasons: string[]; outputs: Record<string, unknown> }[]
  error_nodes: { node: string; label: string; count: number; message: string }[]
  slowest: { index: number; name: string; duration_ms: number }[]
  node_time: { node: string; label: string; avg_ms: number }[]
  outputs: { key: string; all: Stats; by_expected: Record<string, Stats>; by_status: Record<string, Stats> }[]
  judges: BatchJudge[]
  vs_parent: { changed: { index: number; name: string; from: string; to: string }[]; improved: number[]; regressed: number[]; same: number; param_diff: ParamDiff | null } | null
  text: string[]
  suggestions: Suggestion[]
}

export interface BatchCompare {
  a: BatchRun
  b: BatchRun
  rows: { index: number; name: string; expected: string; a_status: string | null; b_status: string | null; a_match: boolean | null; b_match: boolean | null; changed: boolean; a_outputs: Record<string, unknown>; b_outputs: Record<string, unknown>; image_url: string }[]
  summary: { changed: number; improved: number; regressed: number; same: number; a_match: number | null; b_match: number | null; labeled: number | null }
  param_diff: ParamDiff
}

export interface ConsultResult {
  answer: string
  provider: string
  insights: BatchInsights
  suggestions: Suggestion[]
  warnings: string[]
}

export interface TuneResult {
  graph: FlowGraph
  rationale: string
  provider: string
  changes: string[]
  before: { ok: number; ng: number; failed: number }
  after: { ok: number; ng: number; failed: number } | null
  items: { name: string; before: string; after: string }[]
  applied: boolean
  batch_run_id?: number | null
  warnings?: string[]
}

export function batchImageUrl(setId: number, index: number, max = 0): string {
  return withKey(`${BASE_URL}/vision/batch/sets/${setId}/images/${index}${max ? `?max=${max}` : ''}`)
}

export const RUNNING: ReadonlySet<string> = new Set(['queued', 'running'])

export const batchKeys = {
  sets: (flowId: number) => ['batch-sets', flowId] as const,
  set: (id: number) => ['batch-set', id] as const,
  runs: (setId: number) => ['batch-runs', setId] as const,
  run: (id: number) => ['batch-run', id] as const,
  insights: (id: number) => ['batch-insights', id] as const,
}

export function useBatchSets(flowId: number | null) {
  return useQuery({
    queryKey: batchKeys.sets(flowId ?? 0),
    queryFn: () => api.get<BatchSetList>('/vision/batch/sets', { flow_id: flowId }),
    enabled: flowId !== null,
  })
}

export function useBatchSet(id: number | null) {
  return useQuery({
    queryKey: batchKeys.set(id ?? 0),
    queryFn: () => api.get<BatchSet>(`/vision/batch/sets/${id}`),
    enabled: id !== null,
  })
}

export function useBatchRuns(setId: number | null) {
  return useQuery({
    queryKey: batchKeys.runs(setId ?? 0),
    queryFn: () => api.get<{ items: BatchRun[]; total: number }>(`/vision/batch/sets/${setId}/runs`),
    enabled: setId !== null,
    refetchInterval: (q) => (q.state.data?.items.some((r) => RUNNING.has(r.status)) ? 1500 : false),
  })
}

export function useBatchRun(id: number | null) {
  return useQuery({
    queryKey: batchKeys.run(id ?? 0),
    queryFn: () => api.get<BatchRun>(`/vision/batch/runs/${id}`),
    enabled: id !== null,
    refetchInterval: (q) => (q.state.data && RUNNING.has(q.state.data.status) ? 1000 : false),
  })
}

export function useBatchInsights(id: number | null, ready: boolean) {
  return useQuery({
    queryKey: batchKeys.insights(id ?? 0),
    queryFn: () => api.get<BatchInsights>(`/vision/batch/runs/${id}/insights`),
    enabled: id !== null && ready,
  })
}

export function fetchCompare(a: number, b: number): Promise<BatchCompare> {
  return api.get<BatchCompare>(`/vision/batch/runs/${a}/compare`, { other: b })
}

export function previewRow(runId: number, index: number, graph?: FlowGraph | null): Promise<RunReport> {
  return api.post<RunReport>(`/vision/batch/runs/${runId}/rows/${index}/preview`, { graph: graph ?? null })
}

export function consultBatch(body: { batch_run_id: number; question: string; graph?: FlowGraph | null }, signal?: AbortSignal): Promise<ConsultResult> {
  return api.post<ConsultResult>('/vision/agent/consult', body, undefined, signal)
}

export function tuneBatch(body: { batch_run_id: number; instruction: string; graph?: FlowGraph | null }, signal?: AbortSignal): Promise<TuneResult> {
  return api.post<TuneResult>('/vision/agent/tune', body, undefined, signal)
}

export interface RunCreate {
  mode?: 'run' | 'autotune'
  graph?: FlowGraph | null
  recipe_id?: number | null
  label?: string
  note?: string
  parent_run_id?: number | null
  origin?: 'manual' | 'draft'
  max_evals?: number
  deadline_s?: number
}

export function useBatchMutations(flowId: number | null) {
  const client = useQueryClient()
  const invalidateSets = () => {
    if (flowId !== null) void client.invalidateQueries({ queryKey: batchKeys.sets(flowId) })
  }
  const invalidateSet = (setId: number) => {
    invalidateSets()
    void client.invalidateQueries({ queryKey: batchKeys.set(setId) })
    void client.invalidateQueries({ queryKey: batchKeys.runs(setId) })
  }
  const invalidateRun = (run: BatchRun) => {
    invalidateSet(run.set_id)
    void client.invalidateQueries({ queryKey: batchKeys.run(run.id) })
    void client.invalidateQueries({ queryKey: batchKeys.insights(run.id) })
  }
  const createUpload = useMutation({
    mutationFn: ({ files, name }: { files: File[]; name?: string }) => {
      const form = new FormData()
      form.append('flow_id', String(flowId))
      if (name) form.append('name', name)
      for (const f of files) form.append('images', f)
      return api.postForm<BatchSet>('/vision/batch/sets', form)
    },
    onSuccess: invalidateSets,
  })
  const createFromSource = useMutation({
    mutationFn: (body: { source_id: number; count: number; name?: string }) => api.post<BatchSet>('/vision/batch/sets/from-source', { flow_id: flowId, ...body }),
    onSuccess: invalidateSets,
  })
  const patchSet = useMutation({
    mutationFn: ({ id, ...body }: { id: number; name?: string; labels?: { index: number; expected?: Expected; note?: string }[]; remove?: number[] }) =>
      api.patch<BatchSet>(`/vision/batch/sets/${id}`, body),
    onSuccess: (s) => {
      invalidateSet(s.id)
      void client.invalidateQueries({ queryKey: ['batch-run'] })
      void client.invalidateQueries({ queryKey: ['batch-insights'] })
    },
  })
  const deleteSet = useMutation({ mutationFn: (id: number) => api.delete(`/vision/batch/sets/${id}`), onSuccess: invalidateSets })
  const startRun = useMutation({
    mutationFn: ({ setId, ...body }: { setId: number } & RunCreate) => api.post<BatchRun>(`/vision/batch/sets/${setId}/runs`, body),
    onSuccess: (run) => invalidateSet(run.set_id),
  })
  const cancelRun = useMutation({ mutationFn: (id: number) => api.post<{ cancelled: boolean }>(`/vision/batch/runs/${id}/cancel`) })
  const patchRun = useMutation({
    mutationFn: ({ id, ...body }: { id: number; label?: string; note?: string }) => api.patch<BatchRun>(`/vision/batch/runs/${id}`, body),
    onSuccess: invalidateRun,
  })
  const deleteRun = useMutation({ mutationFn: ({ id }: { id: number; setId: number }) => api.delete(`/vision/batch/runs/${id}`), onSuccess: (_d, v) => invalidateSet(v.setId) })
  const toGolden = useMutation({
    mutationFn: ({ setId, ...body }: { setId: number; indexes?: number[]; expect_from: 'label' | 'status'; run_id?: number; note?: string }) =>
      api.post<{ created: number; ids: number[] }>(`/vision/batch/sets/${setId}/to-golden`, body),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['golden'] }),
  })
  const toRecipe = useMutation({
    mutationFn: ({ runId, ...body }: { runId: number; name: string; description?: string; is_default?: boolean }) =>
      api.post<{ id: number; name: string; overrides_json: string }>(`/vision/batch/runs/${runId}/to-recipe`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['recipes'] })
      void client.invalidateQueries({ queryKey: ['flows'] })
    },
  })
  return { createUpload, createFromSource, patchSet, deleteSet, startRun, cancelRun, patchRun, deleteRun, toGolden, toRecipe, invalidateSet }
}

/** 把洞察／諮詢的參數建議套到工作圖（純函式）。 */
export function applySuggestions(graph: FlowGraph, suggestions: Suggestion[]): FlowGraph {
  const patch = new Map<string, Record<string, unknown>>()
  for (const s of suggestions) {
    const cur = patch.get(s.node) ?? {}
    cur[s.key] = s.value
    patch.set(s.node, cur)
  }
  return { ...graph, nodes: graph.nodes.map((n) => (patch.has(n.id) ? { ...n, params: { ...(n.params ?? {}), ...patch.get(n.id) } } : n)) }
}

/** 工作圖與基準圖的參數差異（只比 params）。 */
export function paramDiff(base: FlowGraph, other: FlowGraph): { node: string; key: string; from: unknown; to: unknown }[] {
  const a = new Map(base.nodes.map((n) => [n.id, n.params ?? {}]))
  const out: { node: string; key: string; from: unknown; to: unknown }[] = []
  for (const n of other.nodes) {
    const pa = a.get(n.id)
    if (!pa) continue
    const pb = n.params ?? {}
    for (const key of new Set([...Object.keys(pa), ...Object.keys(pb)])) {
      if (JSON.stringify(pa[key]) !== JSON.stringify(pb[key])) out.push({ node: n.id, key, from: pa[key], to: pb[key] })
    }
  }
  return out
}

export function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${Math.round(v * 1000) / 10}%`
}
