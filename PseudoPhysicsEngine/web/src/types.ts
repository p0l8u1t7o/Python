export type ProjectSummary = {
  id: string;
  name: string;
  customer: string;
  product: string;
  latest_version: string | null;
  modified: string;
  checks: { red: number; yellow: number; green: number };
};

export type TrashItem = {
  trash_id: string;
  original_id: string;
  name: string;
  customer: string;
  product: string;
  deleted_at: string;
  versions: number;
};

export type Version = {
  id: string;
  number: number;
  generated: string;
  checks: { red: number; yellow: number; green: number };
  complete?: boolean;
  level?: "L0" | "L1" | null;
  engineering_status?: "pass" | "warning" | "fail" | "not_evaluated" | null;
};

export type ExportMissing = { kind: string; reason: string };

export type Project = {
  id: string;
  name: string;
  customer: string;
  product: string;
  description: string;
  versions: Version[];
  first_build_summary?: string | null;
};

export type InputEntry = {
  path: string;
  kind: string;
  note: string;
  sha256: string;
  added: string;
};

export type Question = {
  id: string;
  text: string;
  why: string;
  status: "open" | "answered" | "skipped";
  answer: string | null;
  default_if_skipped: string;
};

export type Assumption = {
  id: string;
  from_question: string | null;
  text: string;
  basis: string;
  affects: string[];
  status: "active" | "overridden";
  overridden_by: string | null;
};

export type Job = {
  id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  error?: string;
  result?: Record<string, unknown>;
  warnings?: string[];
};

export type TimelineStation = {
  id: string;
  name?: string;
  t0: number;
  t1: number;
};

export type TimelineNode = {
  type?: string;
  joint_names?: string[];
  joints_deg?: number[][];
  value_deg?: number[][];
  value_mm?: number[][];
  value?: number[][];
  pose_quat?: number[][];
};

export type Timeline = {
  duration_s: number;
  stations: TimelineStation[];
  nodes: Record<string, TimelineNode>;
};

export type Check = {
  id: string;
  severity: "red" | "yellow" | "green";
  type: string;
  t?: number | null;
  detail?: string;
  objects?: string[];
  value?: number | null;
  unit?: string | null;
};

export type PartCheckItem = {
  index: string;
  severity: "fail" | "warn" | "info";
  code: string;
  message: string;
  values: Record<string, unknown>;
};

export type PartCheckResult = {
  module_id: string;
  passed: boolean;
  items: PartCheckItem[];
  source: string;
  params: Record<string, unknown>;
  cache: { key: string; hit: boolean };
};

export type ModuleUsage = {
  machine_id: string;
  instance_id: string;
  stations: string[];
  part: string;
  params: Record<string, unknown>;
  trust?: "inferred" | "confirmed" | null;
};

export type ModuleCheckStatus = {
  status: "passed" | "failed" | "not_checked";
  passed?: boolean;
  counts?: { fail: number; warn: number; info: number };
  cache_key: string;
};

export type ModuleSummary = {
  id: string;
  source: "project" | "library";
  file: string;
  category: string;
  summary: string;
  placeholder: boolean;
  params: Record<string, unknown>;
  parameter_sets: Record<string, unknown>[];
  usages: ModuleUsage[];
  check: ModuleCheckStatus;
};

export type LibraryModuleSummary = {
  id: string;
  file: string;
  tier: string;
  category: string;
  summary: string;
  basis: string;
  params: string[];
  frames: string[];
  axes: string[];
  status: "draft" | "production";
  from_project: string | null;
};

export type FrameInfo = {
  xyz: [number, number, number];
  rpy_deg: [number, number, number];
  trust: "inferred" | "confirmed";
  source?: string | null;
  link?: string | null;
  free_space?: boolean;
};

export type ModuleAxisInfo = {
  id: string;
  type: "revolute" | "prismatic";
  parent: string;
  child?: string | null;
  origin: { xyz: [number, number, number]; rpy_deg: [number, number, number] };
  axis: [number, number, number];
  range_deg?: [number, number] | null;
  range_mm?: [number, number] | null;
  max_speed_dps?: number | null;
  max_speed_mm_s?: number | null;
};

export type ModuleDetail = {
  id: string;
  source: "project" | "library";
  file: string;
  module_def: Record<string, unknown>;
  params: Record<string, unknown>;
  parameter_sets: Record<string, unknown>[];
  params_schema: {
    properties?: Record<
      string,
      { title?: string; type?: string; default?: unknown; minimum?: number; maximum?: number }
    >;
  };
  frames: Record<string, FrameInfo>;
  axes: ModuleAxisInfo[];
  meta: { basis: string; placeholder: boolean };
  usages: ModuleUsage[];
};
