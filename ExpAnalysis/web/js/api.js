/**
 * API 客戶端。
 *
 * 約定：成功（2xx）直接回傳 body；失敗一律丟出 ApiError，訊息取自後端
 * 統一錯誤外層。所有呼叫端只要 try/catch 一種東西。
 */

export class ApiError extends Error {
  constructor(message, code, detail, status) {
    super(message);
    this.name = 'ApiError';
    this.code = code; this.detail = detail; this.status = status;
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(path, options);
  } catch (e) {
    throw new ApiError('無法連線到分析服務，請確認 run.py 仍在執行。',
      'NETWORK', String(e), 0);
  }
  let body = null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    try { body = await res.json(); } catch { body = null; }
  } else {
    body = await res.text();
  }
  if (!res.ok) {
    const err = (body && body.error) || {};
    throw new ApiError(err.message || `HTTP ${res.status}`,
      err.code || `HTTP_${res.status}`, err.detail || '', res.status);
  }
  return body;
}

const json = (path, payload) => request(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload || {}),
});

export const api = {
  health: () => request('/api/health'),
  config: () => request('/api/config'),

  listBatches: () => request('/api/batches'),
  getBatch: (id) => request(`/api/batches/${encodeURIComponent(id)}`),
  deleteBatch: (id) => request(`/api/batches/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  clearAll: () => request('/api/batches', { method: 'DELETE' }),
  seedDemo: (payload) => json('/api/batches/seed-demo', payload),
  importFile: (file, dryRun) => {
    const fd = new FormData();
    fd.append('file', file);
    return request(`/api/batches/import?dry_run=${dryRun ? 'true' : 'false'}`,
      { method: 'POST', body: fd });
  },

  overview: () => request('/api/analysis/overview'),
  keff: (element) => request('/api/analysis/keff' + (element ? `?element=${element}` : '')),
  mapping: () => request('/api/analysis/mapping'),
  anomalies: () => request('/api/analysis/anomalies'),
  validation: () => request('/api/analysis/validation'),
  censoringStudy: () => request('/api/analysis/censoring-study'),
  passAdvice: (max) => request(`/api/analysis/pass-advice?n_passes_max=${max || 25}`),

  simulate: (payload) => json('/api/simulate', payload),
  optimizeGrid: (payload) => json('/api/optimize/grid', payload),
  suggest: (payload) => json('/api/optimize/suggest', payload),
  doeComparison: (payload) => json('/api/optimize/doe-comparison', payload),

  assistantStatus: () => request('/api/assistant/status'),
  chat: (payload) => json('/api/assistant/chat', payload),
  suggestedQuestions: () => request('/api/assistant/suggested-questions'),
};
