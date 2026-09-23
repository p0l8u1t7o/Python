// 後端 API 呼叫；錯誤一律轉為 ApiError(code, detail)，畫面以語系檔 error.<code> 顯示
export class ApiError extends Error {
  code: string;
  detail: string;
  status: number;
  constructor(status: number, code: string, detail = "") {
    super(`${code}${detail ? ": " + detail : ""}`);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

// 401 (未登入或工作階段失效) 時通知應用程式回到登入畫面
let onUnauthorized: () => void = () => undefined;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function headers(extra?: HeadersInit): Headers {
  return new Headers(extra);
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) {
    const ct = res.headers.get("content-type") || "";
    return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
  }
  let code = `http_${res.status}`;
  let detail = "";
  try {
    const body = await res.json();
    if (body && typeof body.error === "string") {
      code = body.error;
      detail = body.detail ?? "";
    } else if (body && body.detail) {
      code = "invalid_request";
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    }
  } catch {
    /* 非 JSON 錯誤 */
  }
  if (res.status === 401) onUnauthorized();
  throw new ApiError(res.status, code, detail);
}

export async function get<T>(path: string, params?: Record<string, string | number | undefined | null>): Promise<T> {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const url = q.toString() ? `${path}?${q}` : path;
  return handle<T>(await fetch(url, { headers: headers() }));
}

export async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: headers({ "Content-Type": "application/json" }) };
  if (body !== undefined) init.body = JSON.stringify(body);
  return handle<T>(await fetch(path, init));
}

export async function upload<T>(path: string, form: FormData): Promise<T> {
  return handle<T>(await fetch(path, { method: "POST", body: form, headers: headers() }));
}

export function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  return q.toString();
}
