/**
 * 與後端 API 對應的型別。工具目錄（ToolTypeDef）是抓來的，不在這裡宣告。
 */

export type ParamKind =
  | 'text'
  | 'multiline'
  | 'number'
  | 'boolean'
  | 'select'
  | 'range'
  | 'roi'
  | 'source'
  | 'asset'
  | 'color'
  | 'json'
  | 'expression'
  | 'output_key'

export type PortType =
  | 'image'
  | 'region'
  | 'number'
  | 'bool'
  | 'string'
  | 'points'
  | 'contours'
  | 'matches'
  | 'list'
  | 'any'
  | 'flow'

export interface ToolParam {
  key: string
  label: string
  kind: ParamKind
  required: boolean
  default: unknown
  help_text: string
  options: { value: string; label: string }[]
  unit: string
  minimum: number | null
  maximum: number | null
  step: number | null
  visible_when: { param: string; in: unknown[] } | null
  shapes: RoiShape[]
  accept: string
  group: string
  /** 需要現場教導的參數（參數卡頁只列這些） */
  teach?: boolean
}

export interface ToolPort {
  key: string
  label: string
  type: PortType
  required: boolean
  multiple: boolean
  tone: 'neutral' | 'ok' | 'warn' | 'critical'
  /** 隱含輸出埠（例如 _overlays）：卡片上畫得較小、放最後 */
  implicit?: boolean
}

export interface ToolTypeDef {
  key: string
  label: string
  description: string
  category: string
  category_label: string
  icon: string
  heavy: boolean
  params: ToolParam[]
  inputs: ToolPort[]
  outputs: ToolPort[]
}

export interface ToolCatalogue {
  items: ToolTypeDef[]
  categories: { key: string; label: string }[]
  param_kinds: string[]
  port_types: string[]
}

// ---- ROI（與後端 apps/vision/tools/roi.py 一致） ----
export type RoiShape = 'rect' | 'rotated_rect' | 'circle' | 'annulus' | 'polygon' | 'line'

export type Region =
  | { shape: 'rect'; x: number; y: number; w: number; h: number }
  | { shape: 'rotated_rect'; cx: number; cy: number; w: number; h: number; angle: number }
  | { shape: 'circle'; cx: number; cy: number; r: number }
  | { shape: 'annulus'; cx: number; cy: number; r_inner: number; r_outer: number }
  | { shape: 'polygon'; points: [number, number][] }
  | { shape: 'line'; x1: number; y1: number; x2: number; y2: number }

// ---- Overlay（工具回傳、畫在輸入影像座標上） ----
export type Overlay = {
  color?: string
  label?: string
  width?: number
  dash?: boolean
  fill?: boolean
} & (
  | { kind: 'rect'; x: number; y: number; w: number; h: number; angle?: number }
  | { kind: 'circle'; cx: number; cy: number; r: number }
  | { kind: 'annulus'; cx: number; cy: number; r_inner: number; r_outer: number }
  | { kind: 'polygon'; points: [number, number][] }
  | { kind: 'polyline'; points: [number, number][] }
  | { kind: 'line'; x1: number; y1: number; x2: number; y2: number }
  | { kind: 'point'; x: number; y: number }
  | { kind: 'points'; points: [number, number][] }
  | { kind: 'text'; x: number; y: number; text: string }
  | { kind: 'contours'; contours: [number, number][][] }
)

// ---- Graph ----
export interface GraphNode {
  id: string
  type: string
  label?: string
  description?: string
  enabled?: boolean
  continue_on_error?: boolean
  color?: string
  params?: Record<string, unknown>
  position?: { x: number; y: number }
  width?: number
  height?: number
}

export interface GraphEdge {
  id?: string
  source: string
  target: string
  source_handle?: string
  target_handle?: string
}

export interface FlowGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface FlowStats {
  runs: number
  ok: number
  ng: number
  failed: number
  avg_ms: number
  max_ms: number
  last_ms: number
  last_status: string
  last_run_id: string
  last_finished_at: number
}

export interface Flow {
  id: number
  name: string
  description: string
  graph: FlowGraph
  is_enabled: boolean
  version: number
  continuous_interval_ms: number
  node_count: number
  created_at: string
  updated_at: string
  stats: FlowStats
  continuous: boolean
  /** null / 空字串 = 共用流程 */
  owner_id: number | null
  owner_name: string
  /** 已完成現場教導（參數卡頁「標記為已教導」）；false 時執行會帶 warnings 但不阻擋 */
  commissioned?: boolean
  recipe_count?: number
}

export type RunStatus = 'ok' | 'ng' | 'failed' | 'cancelled'
export type NodeStatus = 'ok' | 'ng' | 'error' | 'skipped'

export interface ImageRef {
  ref: string | null
  width: number
  height: number
  channels?: number
}

export interface NodeReport {
  status: NodeStatus
  duration_ms: number
  message: string
  branch: string | null
  outputs: Record<string, unknown>
  overlays: Overlay[]
  overlay_on: string | null
  detail: Record<string, unknown>
  logs: { level: string; message: string; detail?: unknown }[]
}

export interface RunReport {
  id: string
  flow_id: number
  flow_version: number
  trigger: string
  status: RunStatus
  started_at: number
  finished_at: number | null
  duration_ms: number
  error: string
  outputs: Record<string, unknown>
  nodes: Record<string, NodeReport>
  persisted?: boolean
  station_id?: string
  /** 使用的配方名稱（空字串 = 沒有） */
  recipe?: string
  warnings?: string[]
}

// ---- 工具頁的參考資訊（preview analysis=true） ----
export interface ImageStats {
  mean: number
  std: number
  min: number
  max: number
  width: number
  height: number
}

export interface SeriesStats {
  count: number
  min: number
  max: number
  mean: number
  values: number[]
}

export interface NodeAnalysis {
  node_id: string
  input?: { ref: string | null; histogram: number[] | null; stats?: ImageStats }
  output?: { port: string; ref: string; histogram: number[] | null; stats?: ImageStats }
  series?: Record<string, SeriesStats>
}

export interface PreviewReport extends RunReport {
  analysis?: NodeAnalysis
}

/** 暫存影像（POST scratch-image 回傳） */
export interface ScratchImage {
  ref: string
  width: number
  height: number
  name: string
}

export interface Capacity {
  max_workers: number
  active: number
  flows: { flow_id: number; flow_name: string; running: boolean; queued: number; continuous: boolean }[]
  images: { images: number; bytes: number; runs: number }
}

export interface ImageSource {
  id: number
  name: string
  kind: string
  config: Record<string, unknown>
  is_enabled: boolean
  status: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface SourceKind {
  kind: string
  label: string
  fields: string[]
}

export interface Asset {
  id: string
  name: string
  kind: 'image' | 'model' | 'file'
  size: number
  meta: Record<string, unknown>
  created_at: string
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export function isImageRef(value: unknown): value is ImageRef {
  return (
    typeof value === 'object' &&
    value !== null &&
    'width' in value &&
    'height' in value &&
    'ref' in value
  )
}

// ---- 帳號與引擎鎖定 ----
export interface AuthUser {
  id: number
  username: string
  display_name: string
  is_staff: boolean
  is_active: boolean
  created_at: string
  last_login: string | null
}

export interface EngineLock {
  locked: boolean
  holder: string
  reason: string
  locked_at: string | null
  expires_at: string | null
}

export interface Me {
  kind: 'user' | 'integrator' | 'bootstrap'
  is_admin: boolean
  user: AuthUser | null
  lock: EngineLock
}

// ---- 範本庫（apps/vision/api_more.py） ----
export interface FlowTemplate {
  /** builtin:<key> 或 uuid */
  id: string
  name: string
  description: string
  category: string
  source: 'builtin' | 'custom'
  node_count: number
  graph: FlowGraph
  owner_name: string
  created_at: string | null
}

export interface TemplateInstance {
  graph: FlowGraph
  /** 有取像步驟但沒選來源 */
  missing_source: boolean
  name: string
  description: string
}

// ---- 批次測試 ----
export interface BatchItem {
  name: string
  run_id: string
  status: RunStatus | string
  duration_ms: number
  outputs: Record<string, unknown>
  error: string
  error_node: string | null
  image_ref: string | null
  width: number
  height: number
}

export interface BatchResult {
  items: BatchItem[]
  summary: { total: number; ok: number; ng: number; failed: number; avg_ms: number; max_ms: number; wall_ms: number }
}

// ---- 統計（GET /flows/{id}/stats） ----
export interface FlowStatsDb {
  hours: number
  total: number
  by_status: Record<string, number>
  avg_ms: number
  max_ms: number
  hourly: { hour: string; ok: number; ng: number; failed: number }[]
  live: FlowStats
}

// ---- 整合頁 ----
export interface IntegrationInfo {
  http_base: string
  host: string
  http_port: number | string
  tcp_host: string
  tcp_port: number
  tcp_listening: boolean
  api_key_required: boolean
  max_workers: number
  run_timeout_s: number
  commands: string[]
}

export interface TcpResult {
  command: string
  response: unknown
  via: 'tcp' | 'direct'
  elapsed_ms: number
  tcp_port: number
}

// ---- 配方（FlowRecipe） ----
export interface FlowRecipe {
  id: number
  flow_id: number
  name: string
  description: string
  /** {node_id: {param: value}} */
  param_overrides: Record<string, Record<string, unknown>>
  is_default: boolean
  created_at: string
  updated_at: string
}

// ---- 配方匯出／匯入與合理化檢查（api_recipes.py） ----
export type RecipeCheckStatus = 'ok' | 'unchanged' | 'version_changed' | 'node_missing' | 'type_changed' | 'param_missing' | 'value_invalid'
/** 可勾選接受的狀態（其餘不能寫入） */
export const RECIPE_ACCEPTABLE: ReadonlySet<string> = new Set(['ok', 'unchanged', 'version_changed'])
export interface RecipeCheckItem {
  /** "node_id.param" */
  key: string
  node_id: string
  node_label: string
  param: string
  param_label?: string
  tool?: string
  tool_label?: string
  /** Param.kind（roi 類在 Check List 顯示摘要） */
  kind?: string
  /** 教導參數（teach=true）；include_all 時 teach=false 的放在「其他參數」摺疊區 */
  teach?: boolean
  value: unknown
  current?: unknown
  status: RecipeCheckStatus
  message: string
}
export interface RecipeCheckResult {
  items: RecipeCheckItem[]
  summary: Record<string, number>
  fingerprint?: string
}
export interface RecipeImportCheck {
  flow_name: string | null
  same_flow_name: boolean
  fingerprint_match: boolean
  recipes: { name: string; description: string; is_default: boolean; exists: boolean; items: RecipeCheckItem[]; summary: Record<string, number> }[]
}
export interface RecipeImportResult {
  items: (FlowRecipe & { created: boolean; accepted: number })[]
  skipped: { recipe: string; key: string; status: string; message: string }[]
}

// ---- Golden Set（apps/golden） ----
export type ExpectStatus = 'ok' | 'ng' | 'any'

export interface GoldenCase {
  id: number
  flow_id: number
  name: string
  expect_status: ExpectStatus
  expect_outputs: Record<string, unknown>
  note: string
  created_at: string
  /** 不含 token；用 goldenImageUrl() 組 */
  image_url: string
}

export interface GoldenList {
  items: GoldenCase[]
  total: number
  can_manage: boolean
  baseline_version: number | null
  baseline_at: string | null
  flow_version: number
}

export interface GoldenBaseline {
  id: number
  flow_id: number
  flow_version: number
  results: Record<string, { status: string; outputs: Record<string, unknown>; duration_ms: number }>
  created_at: string
  case_count: number
}

export interface RegressChange {
  case_id: number
  name: string
  was: string | null
  now: string
  node: string | null
  error: string
  reasons?: string[]
}

export interface RegressCase {
  case_id: number
  name: string
  expect: ExpectStatus
  expect_outputs: Record<string, unknown>
  status: string
  outputs: Record<string, unknown>
  duration_ms: number
  match: boolean
  reasons: string[]
  was: string | null
  was_match: boolean | null
  changed_since_baseline: boolean
  node: string | null
  error: string
  /** mismatch 的 case 才有（上限 20 張） */
  image_ref: string | null
}

export interface RegressResult {
  flow_id: number
  flow_name: string
  flow_version: number
  graph_override: boolean
  total: number
  match: number
  mismatch: number
  match_rate: number
  regressed: RegressChange[]
  improved: RegressChange[]
  confusion: { tp: number; fp: number; tn: number; fn: number }
  cases: RegressCase[]
  duration_ms: number
  baseline_version: number | null
  baseline_at: string | null
  fail_under: number | null
  passed: boolean
  baseline_saved: boolean
}

// ---- 連線（apps/comm） ----
export interface Connection {
  id: number
  name: string
  kind: string
  config: Record<string, unknown>
  is_enabled: boolean
  status: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ConnectionKind {
  kind: string
  label: string
  fields: string[]
}

export interface ConnectionOpResult {
  ok: boolean
  error?: string
  info?: Record<string, unknown>
  result?: Record<string, unknown>
  values?: Record<string, unknown>
}
