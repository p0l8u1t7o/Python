export type ProjectSummary = {
  id: string;
  name: string;
  customer: string;
  product: string;
  latest_version: string | null;
  modified: string;
  checks: { red: number; yellow: number; green: number };
};

export type Version = {
  id: string;
  number: number;
  generated: string;
  checks: { red: number; yellow: number; green: number };
};

export type Project = {
  id: string;
  name: string;
  customer: string;
  product: string;
  description: string;
  versions: Version[];
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
