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
