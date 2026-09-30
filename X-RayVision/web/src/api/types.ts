// 後端回應型別 (對應 xrayvision/service/api.py 與分析結果 JSON)
export type Judgment = "pass" | "fail" | "review" | "quality_insufficient" | "not_judged";
export type QualityLevel = "pass" | "warn" | "fail";
export type Locale = "zh-TW" | "en";
export type Labels = Partial<Record<Locale, string>>;

export interface SystemInfo {
  product: string;
  version: string;
  schema_version: number;
  modules: Record<string, string>;
  queue: Partial<Record<"queued" | "running" | "done" | "failed" | "cancelled", number>>;
  workers: number;
  locales: Locale[];
  time: string;
  disk: { total_gb: number; free_gb: number; used_ratio: number; warn_gb: number; low: boolean } | null;
  analysis_allowed: boolean;
}

export interface ParamDef {
  key: string;
  type: "float" | "int" | "bool" | "enum" | "model";
  default: unknown;
  label: Labels;
  min: number | null;
  max: number | null;
  choices: string[];
  unit: string;
  advanced: boolean;
}

export interface QualityRule {
  metric: string;
  warn_below?: number | null;
  warn_above?: number | null;
  fail_below?: number | null;
  fail_above?: number | null;
  kinds?: string[];
}

export interface OverlayStyle {
  color: string;
  thickness?: number;
  scale?: number;
}

export interface ModuleInfo {
  module_id: string;
  version: string;
  names: Labels;
  supported_kinds: string[];
  params: ParamDef[];
  judgment_params: ParamDef[];
  quality_rules: QualityRule[];
  overlay_styles: Record<string, OverlayStyle>;
  summary_vector: string;
  supports_region_arrays?: boolean;
  finding_table?: { category: string; sort: string; columns: string[]; limit: number } | null;
  validation?: "validated" | "unvalidated";
}

export interface ModelRow {
  id: number;
  ref: string;
  model_id: string;
  version: string;
  module_id: string;
  task: string;
  sha256: string;
  status: "active" | "retired";
  imported_by: string;
  imported_at: string;
  meta: { names?: Labels; metrics?: Record<string, number>; training?: { sources?: { kind: string; crops?: number }[] }; created_at?: string };
}

export interface ModuleValidation {
  module_id: string;
  version: string;
  series: string;
  names: Labels;
  status: "validated" | "unvalidated";
  approved_by: string | null;
  approved_at: string | null;
  note: string;
  history: { status: string; note: string; report_name: string; actor: string; created_at: string }[];
}

export interface RecipeModule {
  module_id: string;
  params: Record<string, unknown>;
  enabled?: boolean;
  judgment?: Record<string, unknown>;
  module_version?: string;
}

export interface RecipeBody {
  recipe_id: string;
  version: number;
  name: Labels;
  pixel_size_um: number | null;
  calibration_profile: string | null;
  quality_rules: QualityRule[];
  acquisition_limits: Record<string, [number | null, number | null]>;
  modules: RecipeModule[];
  regions?: Regions | null;
}

export interface RegionShape {
  type: "rect" | "polygon";
  x0?: number; y0?: number; x1?: number; y1?: number;
  points?: number[][];
  label?: string;
  as_array?: boolean;             // 僅包含區域：區域內的目標視為一個陣列
}

export interface Regions {
  reference: { width: number; height: number; run_id?: number };
  include: RegionShape[];
  exclude: RegionShape[];
}

export interface RecipeRow {
  id: number;
  recipe_id: string;
  version: number;
  name: Labels;
  body: RecipeBody;
  status: "draft" | "released" | "retired";
  note: string;
  created_at: string;
  created_by: string;
  released_at: string | null;
  released_by: string | null;
}

export interface RecipeSummary {
  recipe_id: string;
  name: Labels;
  latest_released: number | null;
  versions: { id: number; version: number; status: RecipeRow["status"]; created_at: string; released_at: string | null }[];
}

export interface ShiftEstimate {
  dx: number;
  dy: number;
  mag: number;
  se: number;
  rms: number;
  rot_deg: number;
  scale_ppm: number;
  n: number;
  n_in: number;
  cx: number;
  cy: number;
  dx_um?: number;
  dy_um?: number;
  mag_um?: number;
  se_um?: number;
}

export interface ModuleSummaryLite {
  status: string;
  judgment: Judgment;
  summary: Record<string, unknown> & { die_shift?: ShiftEstimate | null };
}

export interface RunRow {
  id: number;
  created_at: string;
  quality_level: QualityLevel;
  reference_only: boolean;
  auto_judgment: Judgment;
  final_judgment: Judgment;
  summary: { quality: QualityLevel; judgment_reasons: string[]; modules: Record<string, ModuleSummaryLite> };
  elapsed_s: number;
  software_version: string;
  image_id: number;
  job_id: number;
  file_name: string;
  sample_no: string;
  kind: string;
  width: number;
  height: number;
  lot_no: string | null;
  recipe_id: string;
  recipe_version: number;
  recipe_pk: number;
  superseded_by: number | null;   // 已被同一影像較新的紀錄取代時為該紀錄編號
  image_regions?: boolean;        // 使用本影像自訂檢測區域 (PLAN-004)
}

export interface Geometry {
  type: "circle" | "vector" | "bbox" | "polygon";
  x?: number;
  y?: number;
  r?: number;
  dx?: number;
  dy?: number;
  x0?: number;
  y0?: number;
  x1?: number;
  y1?: number;
  points?: [number, number][];
}

export interface Finding {
  id: number;
  category: string;
  geometry: Record<string, Geometry>;
  measurements: Record<string, number>;
  group: number;
  used: boolean;
  reason: string;
  flags: Record<string, unknown>;
}

export interface Group {
  id: number;
  category: string;
  bbox: [number, number, number, number] | null;
  size: number;
  estimate: ShiftEstimate | null;
  grade: string;
  measurements: Record<string, number | null>;
  source?: "auto" | "region";     // region = 檢測區域「視為一個陣列」
  label?: string;
}

export interface QualityCheck {
  metric: string;
  value: number;
  level: QualityLevel;
  rule: QualityRule;
}

export interface ModuleResult {
  module_id: string;
  module_version: string;
  status: "ok" | "no_result" | "error";
  params: Record<string, unknown>;
  findings: Finding[];
  groups: Group[];
  summary: Record<string, unknown> & { die_shift?: ShiftEstimate | null; pixel_size_um?: number | null };
  metrics: Record<string, number>;
  reasons: string[];
  rejects: Record<string, number>;
  rejected: { x: number; y: number; r: number; reason: string }[];
  elapsed_s: number;
  judgment: Judgment;
  judgment_reasons: string[];
}

export interface AnalysisResult {
  image: { path: string; name: string; sha256: string; kind: string; width: number; height: number };
  software_version: string;
  recipe: RecipeBody;
  reference_only: boolean;
  notes: string[];
  quality: { level: QualityLevel; metrics: Record<string, number>; checks: QualityCheck[] };
  judgment: Judgment;
  judgment_reasons: string[];
  acquisition: { source: string; file: string | null; params: Record<string, unknown> };
  calibration: Record<string, unknown> | null;
  modules: ModuleResult[];
  elapsed_s: number;
  started_at: string;
  unvalidated_modules?: string[];
  regions_source?: "recipe" | "image";   // 生效的檢測區域來源 (image = 本影像自訂檢測區域)
  manual?: boolean;                      // 手動檢測 (非正式結果)
}

export interface Review {
  id: number;
  run_id: number;
  judgment: Judgment;
  comment: string;
  reviewer: string;
  created_at: string;
}

export interface RunDetail {
  run: RunRow;
  result: AnalysisResult;
  reviews: Review[];
  history: HistoryItem[];
}

// 分析歷程：同一影像的所有紀錄 (新到舊)
export interface HistoryItem {
  id: number;
  created_at: string;
  auto_judgment: Judgment;
  final_judgment: Judgment;
  quality_level: QualityLevel;
  recipe_id: string;
  recipe_version: number;
  image_regions?: boolean;
  reviews: { judgment: Judgment; comment: string; reviewer: string; created_at: string }[];
}

export interface RecipeDiff {
  base: { id: number; version: number; status: RecipeRow["status"] } | null;
  changes: { path: string; old: unknown; new: unknown }[];
}

export interface ReanalysisScope {
  total: number;
  skipped: number;
  image_regions?: number;         // 其中使用自訂檢測區域的影像數
  lots: { lot_no: string; n: number }[];
  avg_elapsed_s: number | null;
  workers: number;
}

export interface ReanalysisProgress {
  active: boolean;
  total?: number;
  queued?: number;
  running?: number;
  done?: number;
  failed?: number;
  cancelled?: number;
}

export interface Job {
  id: number;
  image_id: number;
  recipe_pk: number;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  priority: number;
  source: string;
  attempts: number;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  file_name: string;
}

export interface Stats {
  since: string;
  by_day: { day: string; judgment: Judgment; n: number }[];
  totals: { judgment: Judgment; n: number }[];
  review_pending: number;
}

export interface WatchFolder {
  id: number;
  path: string;
  recipe_id: string;
  enabled: number;
  recursive: number;
  name_rule: string;
  created_at: string;
  last_scan_at: string | null;
  counts: Record<string, number>;
}

export interface DiagnosticExport {
  id: number;
  created_at: string;
  actor: string;
  file_name: string;
  sha256: string;
  run_ids_json: string;
  options_json: string;
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  detail_json: string;
}

export interface ImportResult {
  file: string;
  image_id?: number;
  job_id?: number;
  error?: string;
  detail?: string;
}

export type Role = "operator" | "engineer" | "admin";

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  active: boolean;
  must_change_password: boolean;
  created_at: string;
  last_login_at: string | null;
  locked: boolean;
}

export interface AuthState {
  setup_required: boolean;
  product: string;
  version: string;
  user: User | null;
  permissions: string[];
  license: { state: string; analysis_allowed: boolean; days_left?: number; expires?: string; warn: boolean; enforced: boolean } | null;
}

// 手動檢測工作區 (PLAN-004 第 4 節)
export interface WorkspaceResultSummary {
  hash: string;
  judgment: Judgment;
  quality: QualityLevel;
  summary: RunRow["summary"];
  elapsed_s: number;
  analyzed_at: string;
  stale?: boolean;
}

export interface WorkspaceItem {
  id: number;
  name: string;
  source: "upload" | "run";
  image_id: number | null;
  run_id: number | null;
  kind: string;
  width: number;
  height: number;
  size_bytes: number;
  added_at: string;
  available: boolean;
  result: WorkspaceResultSummary | null;
}

export interface WorkspaceSource {
  recipe_pk: number;
  recipe_id: string;
  version: number;
  status: RecipeRow["status"];
  name: Labels;
  body: RecipeBody;
}

export interface WorkspaceBatch {
  running: boolean;
  total: number;
  done: number;
  failed: number;
  current: number | null;
  params_hash: string;
}

export interface WorkspaceView {
  params: RecipeBody | null;
  source: WorkspaceSource | null;
  images: WorkspaceItem[];
  params_hash: string | null;
  usage: { images: number; bytes: number; max_images: number; max_bytes: number };
  updated_at: string;
  batch: WorkspaceBatch | null;
  waiting: number;
  analysis_allowed: boolean;
}
