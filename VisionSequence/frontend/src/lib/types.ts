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
  | 'code'
  | 'output_key'
  | 'images'

/** 固定影像描述子（fixed_image 工具的 images 參數元素；檔案在伺服端 ASSET_DIR/fixed/） */
export interface FixedImageDesc {
  id: string
  name: string
  width: number
  height: number
  size: number
}

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

/** 參數埠的把手前綴（後端 apps/vision/tools/base.py 的 PARAM_PREFIX）。 */
export const PARAM_PREFIX = 'param:'

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
  /** 分支埠的數量由這個多行參數決定（每一行一個 case_N；後端 tools/base.py 的 cases_param） */
  cases_param?: string
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

export interface StationTeachParamItem {
  id: string
  flow_id: number
  flow_name: string
  flow_version: number
  node_id: string
  node_label: string
  tool_type: string
  tool_label: string
  tool_category: string
  param: ToolParam
  value: unknown
}

export interface StationTeachParamList {
  items: StationTeachParamItem[]
  total: number
  flow_count: number
}

export interface StationTeachRef {
  flow_id: number
  node_id: string
  param: string
}

export interface StationTeachGroupItem extends StationTeachRef {
  valid: boolean
  reason?: string
  resolved?: StationTeachParamItem
}

export interface StationTeachGroup {
  id: string
  name: string
  items: StationTeachGroupItem[]
  count: number
}

export interface StationTeachGroupList {
  items: StationTeachGroup[]
  limit: number
}

// ---- ROI（與後端 apps/vision/tools/roi.py 一致） ----
export type RoiShape = 'rect' | 'rotated_rect' | 'circle' | 'ellipse' | 'annulus' | 'polygon' | 'polyline' | 'line' | 'point'

export type Region =
  | { shape: 'rect'; x: number; y: number; w: number; h: number }
  | { shape: 'rotated_rect'; cx: number; cy: number; w: number; h: number; angle: number }
  | { shape: 'circle'; cx: number; cy: number; r: number }
  | { shape: 'ellipse'; cx: number; cy: number; rx: number; ry: number; angle: number }
  | { shape: 'annulus'; cx: number; cy: number; r_inner: number; r_outer: number; a0?: number; a1?: number }
  | { shape: 'polygon'; points: [number, number][] }
  | { shape: 'polyline'; points: [number, number][] }
  | { shape: 'line'; x1: number; y1: number; x2: number; y2: number }
  | { shape: 'point'; x: number; y: number }

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
  /** 外露成輸入埠的參數（`param:<key>`）；接上上游就改吃那個值 */
  exposed_params?: string[]
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
  archive_policy?: ArchivePolicy
  /** 現場看板設定（apps/vision/board.py）；空物件＝預設 */
  board?: import('./board').BoardConfig
  /** 結果回送規則（apps/vision/reporting.py）；空陣列＝不回送 */
  comm?: CommRule[]
  id: number
  name: string
  description: string
  graph: FlowGraph
  is_enabled: boolean
  version: number
  continuous_interval_ms: number
  timeout_s: number
  concurrency: number
  stop_on_ng: boolean
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
  /** 已封存的影像 {ref: 相對路徑}；空＝這次沒有封存，只能看記憶體快取還在不在 */
  images?: Record<string, string>
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
  /** SSE 對不要輸出的訂閱者送的瘦身版：節點只有狀態，outputs／overlays／detail 是空的（別拿它蓋掉完整版） */
  nodes_trimmed?: boolean
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
  configured_max_workers?: number
  cv_threads?: number
  sse_max_streams?: number
  max_queue_per_flow?: number
  run_timeout_s?: number
  stable_cycle_mode?: boolean
  active: number
  workers_busy?: number
  flows: { flow_id: number; flow_name: string; running: number; queued: number; continuous: boolean }[]
  images: { images: number; bytes: number; runs: number }
}

export type DashboardWidgetType =
  | 'image'
  | 'images'
  | 'run_control'
  | 'run_status'
  | 'verdict'
  | 'text'
  | 'button'
  | 'switch'
  | 'param'
  | 'variable'
  | 'traffic_light'
  | 'conditional_light'
  | 'group'
  | 'tabs'
  | 'table'
  | 'line_chart'
  | 'stats'
  | 'pie'
  | 'image_static'
  | 'clock'
  | 'log'
  | 'device_status'
  | 'child'

export type DashboardSourceKind = 'output' | 'variable' | 'image' | 'status' | 'counts' | 'spc' | 'device'
export type DashboardAction =
  | 'run_once'
  | 'continuous_start'
  | 'continuous_stop'
  | 'activate_recipe'
  | 'set_variable'
  | 'navigate'
  | 'lock'
  | 'unlock'

export type DashboardRuleOp = 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'between' | 'contains'

export interface DashboardWidgetSource {
  flow_id?: number | null
  kind?: DashboardSourceKind
  key?: string
}

export interface DashboardCell {
  id: string
  row: number
  col: number
  row_span: number
  col_span: number
}

export interface DashboardBars {
  top?: boolean
  bottom?: boolean
  left?: boolean
  right?: boolean
}

export interface DashboardWidget {
  id: string
  type: DashboardWidgetType
  cell?: string
  props?: Record<string, unknown>
  source?: DashboardWidgetSource
}

export interface DashboardLayout {
  rows: number
  cols: number
  cells: DashboardCell[]
  bars: DashboardBars
  default_flow_id?: number | null
  widgets: DashboardWidget[]
  theme?: Record<string, unknown>
}

export interface DashboardSummary {
  id: number
  name: string
  is_default: boolean
  owner_name?: string
  updated_at: string
  widget_count: number
}

export interface Dashboard extends DashboardSummary {
  layout: DashboardLayout
}

export interface DashboardData {
  generated_at: string
  flows: Record<string, import('./board').BoardData | { missing: true }>
  device: {
    station_id: string
    version: string
    lock: Pick<EngineLock, 'locked' | 'holder' | 'reason'>
    capacity: Capacity
    flows_running: number[]
  }
  variables: { station: Record<string, unknown> }
}

export interface ImageSource {
  id: number
  name: string
  /** 使用者自訂群組（'' = 未分組） */
  group: string
  kind: string
  config: Record<string, unknown>
  is_enabled: boolean
  status: Record<string, unknown>
  created_at: string
  updated_at: string
}

// ---- 擷取端（Capture client）：在相機所在的電腦驅動相機、主動連到伺服端擷取埠 ----
// ---- 整合追蹤（命令與結果） ----
export interface TraceEntry {
  seq: number
  /** epoch 秒（含小數） */
  ts: number
  channel: string
  /** in＝外部送進來、out＝本平台送出去 */
  direction: 'in' | 'out' | string
  /** 來源／連線名稱 */
  name: string
  summary: string
  ok: boolean
  ms: number | null
  detail: unknown
}

export interface CaptureRoi { x: number; y: number; w: number; h: number }
export interface CaptureChannel {
  id: string
  label: string
  driver: string
  index: number
  width: number
  height: number
  channels: number
  dtype: string
  pixel_format: string
  roi: CaptureRoi
  full: { w: number; h: number }
  mode: 'on_demand' | 'stream' | string
  enabled: boolean
  streaming: boolean
  seq: number
  last_frame_age_ms: number | null
  encoding: string
  shm: boolean
  last_error: string
  in_use_by: string[]
  fps: number
  bytes_per_s: number
  frames: number
  /** 伺服端每張影格的接收（複製）耗時 */
  recv_ms?: number
}
export interface CaptureClient {
  name: string
  address: string
  version: string
  hostname: string
  connected_at: string
  local: boolean
  prefer_encoding: string
  shm: boolean
  channels: CaptureChannel[]
}
export interface CaptureClients { listening: boolean; host: string; port: number; items: CaptureClient[] }
export interface CaptureDownloadInfo { available: boolean; version: string; filename: string; size: number; sha256: string; built_at: string | null; url: string }

export interface SourceKind {
  kind: string
  label: string
  fields: string[]
}

export interface Asset {
  id: string
  name: string
  /** 使用者自訂群組（'' = 未分組） */
  group: string
  kind: 'image' | 'model' | 'file' | 'calibration'
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
  role?: Role
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

/** 功能鍵（accounts/permissions.py 的 FEATURES）：管理員勾選哪些角色能用。 */
export type Feature =
  | 'flows.run' | 'flows.teach' | 'flows.edit' | 'sources' | 'assets'
  | 'batch' | 'golden' | 'dl' | 'agent' | 'integration' | 'connections' | 'audit'

export interface RolePermissions {
  features: { key: Feature; default: { engineer: boolean; operator: boolean } }[]
  matrix: Record<string, Feature[]>
  roles: string[]
}

export interface Me {
  role?: Role
  kind: 'user' | 'integrator' | 'bootstrap'
  is_admin: boolean
  /** 這個身分能用的功能；舊版後端沒回時前端退回角色預設。 */
  permissions?: Feature[]
  user: AuthUser | null
  /** 使用者介面偏好（theme 等；整合方/bootstrap 為空物件） */
  prefs: { theme?: string; language?: string }
  lock: EngineLock
  /** 伺服端版本（側欄頁尾顯示；以前另外輪詢 integration/info） */
  version?: string
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
  /** 內建範本附樣本圖：不選來源時取像步驟變成固定影像 */
  has_samples?: boolean
}

/** 資料保留設定（單列，管理員可改；天數 0 = 永久保留） */
export interface RetentionSettings {
  run_days: number
  audit_days: number
  measurement_days: number
  archive_days: number
  archive_max_gb: number
  backup_keep: number
  window_hour: number
  vacuum: boolean
  enabled: boolean
}

export interface RetentionSweepResult {
  runs: number
  measurements: number
  audit: number
  archive_files: number
  archive_freed: number
  backups: number
  vacuum: boolean
  ms?: number
}

export interface RetentionStatus {
  settings: RetentionSettings
  defaults: RetentionSettings
  last_sweep_at: string | null
  last_deep_at: string | null
  last_result: Partial<RetentionSweepResult>
  usage: {
    db_bytes: number
    archive_files: number
    archive_bytes: number
    backup_files: number
    backup_bytes: number
    runs: number
    audit: number
    measurements: number
  }
  busy: boolean
}

export type LogLevel = 'error' | 'info' | 'debug' | 'trace'

export interface VisionRuntimeSettings {
  stable_cycle_mode: boolean
  log_level: LogLevel
  auto_save_enabled: boolean
  auto_save_interval_min: number
}

export interface VisionSettingsStatus {
  settings: VisionRuntimeSettings
  defaults: VisionRuntimeSettings
  last_auto_save_at?: string | null
  last_auto_save_result?: { saved?: number; skipped?: number; flows?: number }
}

/** 資料保留設定（單列，管理員可改；天數 0 = 永久保留） */
export interface RetentionSettings {
  run_days: number
  audit_days: number
  measurement_days: number
  archive_days: number
  archive_max_gb: number
  backup_keep: number
  window_hour: number
  vacuum: boolean
  enabled: boolean
}

export interface RetentionSweepResult {
  runs: number
  measurements: number
  audit: number
  archive_files: number
  archive_freed: number
  backups: number
  vacuum: boolean
  ms?: number
}

export interface RetentionStatus {
  settings: RetentionSettings
  defaults: RetentionSettings
  last_sweep_at: string | null
  last_deep_at: string | null
  last_result: Partial<RetentionSweepResult>
  usage: {
    db_bytes: number
    archive_files: number
    archive_bytes: number
    backup_files: number
    backup_bytes: number
    runs: number
    audit: number
    measurements: number
  }
  busy: boolean
}

export interface TemplateInstance {
  graph: FlowGraph
  /** 有取像步驟但沒選來源 */
  missing_source: boolean
  /** 取像步驟已換成範本的樣本圖 */
  used_samples?: boolean
  name: string
  description: string
}

// ---- 批次測試 ----
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
/** 工廠角色：admin＝系統與帳號；engineer＝建流程、訓練、調任何參數；operator＝執行、換線、只能動現場參數。 */
export type Role = 'admin' | 'engineer' | 'operator'

/** Which runs keep their pictures on disk (see apps/vision/archive.py). */
export interface ArchivePolicy {
  mode: 'off' | 'ng' | 'all'
  pictures: 'result' | 'all'
  sample: number
  format: 'jpeg' | 'png'
  quality: number
}

export interface IntegrationInfo {
  /** 產品版本（後端 apps/vision/__init__.py 是唯一來源） */
  version?: string
  station_id?: string
  http_base: string
  host: string
  http_port: number | string
  tcp_host: string
  /** 外部真的連得到的位址（tcp_host 是 0.0.0.0 這種綁定位址時，這裡給可用的） */
  tcp_connect_host?: string
  tcp_port: number
  tcp_listening: boolean
  api_key_required: boolean
  max_workers: number
  max_queue_per_flow?: number
  run_timeout_s: number
  commands: string[]
  capture_host?: string
  capture_connect_host?: string
  capture_port?: number
  capture_listening?: boolean
  capture_download_url?: string
  events_url?: string
  flow_events_url?: string
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

/** plugins/ 底下一個檔案的載入結果（GET /vision/plugins）。 */
export interface PluginInfo {
  name: string
  path: string
  kind: 'file' | 'package'
  status: 'ok' | 'disabled' | 'error' | 'empty'
  error: string
  /** "tool:key" / "source:kind" / "comm:kind" / "dl:kind" */
  mounted: string[]
  requirements: boolean
  loaded_at: number
}

export interface PluginInventory {
  dir: string
  items: PluginInfo[]
  docs_url: string
  mounted?: string[]
}

export interface ConnectionKind {
  kind: string
  label: string
  fields: string[]
  /** 由哪個整合頁管理（/integration/<section>）；後端 comm.writers.kinds() 決定。 */
  section?: string
  description?: string
}

export interface ConnectionOpResult {
  ok: boolean
  error?: string
  info?: Record<string, unknown>
  result?: Record<string, unknown>
  values?: Record<string, unknown>
}

// ---- 深度學習教導（/vision/dl） ----
export interface DlTrainerDef {
  kind: string
  label: string
  description: string
  label_mode: 'classes' | 'shapes'
  tool_key: string
  devices: string[]
  min_per_class: number
  params: ToolParam[]
}

export interface DlProject {
  id: number
  name: string
  description: string
  trainer_kind: string
  classes: string[]
  params: Record<string, unknown>
  last_asset_id: string
  last_metrics: Record<string, unknown>
  created_at: string
  updated_at: string
  counts?: { total: number; unlabeled: number; per_class: Record<string, number> }
}

export interface DlShape {
  label: string
  kind: 'polygon' | 'bbox'
  /** 0~1 正規化座標；bbox 為 [左上, 右下] 兩點 */
  points: [number, number][]
}

export interface DlSample {
  id: string
  label: string
  labeled_by: '' | 'human' | 'auto'
  score: number
  width: number
  height: number
  created_at: string
  shapes: DlShape[]
  /** 資料集分割：train｜val｜test；'' = 未指定 */
  split: '' | 'train' | 'val' | 'test'
}

export interface DlRetrievalItem {
  index: number
  id: string
  label: string
  thumb: string
}

export interface DlRetrievalClass {
  label: string
  count: number
  items: DlRetrievalItem[]
}

export interface DlRetrievalLibrary {
  asset_id: string
  total: number
  classes: DlRetrievalClass[]
  items: DlRetrievalItem[]
  metrics: Record<string, unknown>
  created?: number
  skipped?: number
  duplicates?: number
}

export interface DlDatasetVersion {
  id: number
  name: string
  note: string
  stats: {
    total?: number
    unlabeled?: number
    per_class?: Record<string, number>
    classes?: string[]
    split?: { train: number; val: number; test: number }
  }
  asset_id: string
  created_at: string
}

export interface DlDevices {
  onnxruntime: string
  providers: string[]
  accelerators: string[]
  gpus: { name: string; memory_total_mb?: number; memory_used_mb?: number; utilization?: number }[]
  preferred_providers: string[]
  train_device: string
  train_devices: string[]
}

export interface DlTrainJob {
  id: string
  project_id: number
  project_name: string
  trainer_kind: string
  device: string
  status: 'running' | 'done' | 'failed' | 'cancelled'
  progress: number
  stage: string
  metrics: Record<string, unknown>
  error: string
  asset_id: string
  asset_name: string
  /** 訓練好但還沒決定要不要存進資產庫 */
  pending?: boolean
  /** 已經存進資產庫（asset_id 才有值） */
  saved?: boolean
  discarded?: boolean
  tool_key: string
  tool_params: Record<string, unknown>
  duration_s: number
  history: Record<string, number>[]
  logs: string[]
  log_from: number
  log_next: number
}

export interface DlQuickRegisterResult {
  job_id: string
  labeled: number
  skipped: number
  params: Record<string, unknown>
}

export interface DlSuggestion {
  id: string
  label: string
  score: number
  shapes?: DlShape[]
}

/** 量測值 SPC（GET /flows/{id}/spc） */
export interface SpcLimits {
  chart: 'imr' | 'xbar_r'
  n: number
  subgroup?: number
  cl?: number | null
  ucl?: number | null
  lcl?: number | null
  sigma?: number | null
  mr_bar?: number | null
  mr_ucl?: number | null
  r_bar?: number
  r_ucl?: number
  r_lcl?: number
  xbar?: number[]
  r?: number[]
}
export interface SpcCapability {
  usl: number | null
  lsl: number | null
  cp?: number
  cpk?: number
  cpu?: number
  cpl?: number
  out_of_spec?: number
}
export interface SpcAlert {
  rule: number
  text: string
  points: number[]
}
export interface SpcResult {
  flow_id: number
  output: string
  outputs: string[]
  hours: number
  chart: 'imr' | 'xbar_r'
  subgroup: number
  enabled: boolean
  retention_days: number
  series: { ts: string; value: number; run_id: string }[]
  analysis: {
    limits: SpcLimits
    capability: SpcCapability
    rules: Record<string, number[]>
    rule_names: Record<string, string>
    flagged: number[]
    summary: { n: number; mean: number | null; std: number | null; min: number | null; max: number | null }
  }
  spec: { usl?: number; lsl?: number; nominal?: number; unit?: string; node_id?: string; source?: string }
  alerts?: SpcAlert[]
}
export interface SpcAlertsResult {
  items: { flow_id: number; flow_name: string; output: string; alerts: SpcAlert[]; last_ts: string; points: number }[]
  cached: boolean
}

/**
 * 觸發規則：設備做了什麼 → 平台做什麼（後端 apps/comm/rules.py）。
 * 連線的規則存在 config.triggers；站台的文字規則存在 /vision/integration/rules。
 */
export type RuleSource = 'value' | 'text'
export type RuleValueMode = 'rising' | 'falling' | 'change' | 'nonzero' | 'equal' | 'not_equal' | 'range'
export type RuleTextMatch = 'exact' | 'contains' | 'prefix' | 'regex'
export type RuleAction = 'run_flow' | 'activate_recipe' | 'set_variable' | 'set_param' | 'calibration_signal' | 'lock' | 'unlock'
export type CalibrationSignalKind = 'start' | 'point' | 'end' | 'teach'

export interface TriggerRule {
  id: string
  name: string
  enabled: boolean
  source: RuleSource
  address: string
  mode: RuleValueMode
  value: number
  value2: number
  match: RuleTextMatch
  pattern: string
  capture: string
  action: RuleAction
  flow: string
  recipe: string
  variable: string
  node: string
  param: string
  scope: 'flow' | 'station'
  set_value: string
  signal_kind: CalibrationSignalKind
  args: Record<string, unknown>
  reason: string
  ttl: number
  clear: boolean
  done: string
  reply: string
}

export interface CalibrationSignal {
  seq: number
  kind: CalibrationSignalKind
  x: number | null
  y: number | null
  r: number | null
  ts: number
  source: string
}

export interface CalibrationSignalList {
  items: CalibrationSignal[]
  last_seq: number
}

/**
 * 結果回送規則：這條流程跑完要把結果送給誰、送什麼（後端 apps/vision/reporting.py，存在 Flow.comm）。
 */
export interface CommRule {
  id: string
  name: string
  enabled: boolean
  connection: string
  when: 'on_finish' | 'interval'
  interval_ms: number
  node: string
  node_status: 'any' | 'ok' | 'ng' | 'error' | 'skipped'
  ok: string
  ng: string
  failed: string
}

/** 站台複製包：整份通訊設定（後端 apps/comm/api.py 的 export／import）。 */
export interface ConnectionsExport {
  version: number
  station_id?: string
  exported_at?: string
  connections: { name: string; kind: string; config: Record<string, unknown>; is_enabled: boolean }[]
  station_rules?: TriggerRule[]
}

export interface ConnectionsImportResult {
  created: string[]
  updated: string[]
  skipped: string[]
  failed: { name: string; error: string }[]
  station_rules: number | null
}
