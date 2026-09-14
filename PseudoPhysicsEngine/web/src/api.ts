import type { Job } from "./types";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init.headers
        : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function waitForJob(
  jobId: string,
  onUpdate: (job: Job) => void,
  onEvent?: (event: Record<string, unknown>) => void,
): Promise<Job> {
  const source = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`);
  const eventTypes = ["status", "progress", "agent", "log", "error", "complete"];
  for (const eventType of eventTypes) {
    source.addEventListener(eventType, (raw) => {
      try {
        onEvent?.(JSON.parse((raw as MessageEvent<string>).data) as Record<string, unknown>);
      } catch {
        onEvent?.({ type: "log", message: (raw as MessageEvent<string>).data });
      }
    });
  }
  try {
    for (;;) {
      const job = await api<Job>(`/jobs/${jobId}`);
      onUpdate(job);
      if (["done", "failed", "cancelled"].includes(job.status)) return job;
      await new Promise((resolve) => window.setTimeout(resolve, 250));
    }
  } finally {
    source.close();
  }
}

export function inferKind(file: File): string {
  const name = file.name.toLowerCase();
  if (/\.(jpg|jpeg|png|webp)$/.test(name)) return "product_photo";
  if (/\.(xls|xlsx|csv)$/.test(name)) return "checklist";
  if (name.endsWith(".pdf")) return "inspection_spec";
  if (/\.(step|stp|iges|igs)$/.test(name)) return "cad";
  if (/\.(md|txt)$/.test(name)) return "text";
  return "other";
}
