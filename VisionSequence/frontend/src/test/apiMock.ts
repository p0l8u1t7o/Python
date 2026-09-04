/** `@/lib/api` 的假後端：依路徑回最小合法資料，讓頁面 render 走完 loading → 內容。 */
import { vi } from 'vitest'

export const ME = {
  kind: 'user', user: { id: 1, username: 'admin', display_name: '管理員', is_staff: true, is_active: true },
  prefs: {}, lock: { locked: false, holder: '', reason: '', expires_at: null },
}

export const FLOW = { id: 1, name: '示範流程', description: '', version: 1, is_enabled: true, continuous_interval_ms: 0, owner_id: 1, owner_name: 'admin', recipe_count: 0, commissioned: false, stats: { last_status: 'ok', total: 3, ok: 3, ng: 0, failed: 0, avg_ms: 5, last_ms: 5, running: false, continuous: false, queued: 0 }, graph: { nodes: [], edges: [] }, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }

export function routes(path: string): unknown {
  if (path.startsWith('/auth/status')) return { setup_required: false }
  if (path.startsWith('/auth/me')) return ME
  if (path.startsWith('/vision/batch/sets/')) return { id: 1, flow_id: 1, name: '影像集 A', source: 'upload', image_count: 0, size_bytes: 0, owner_id: 1, labeled: { ok: 0, ng: 0 }, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', images: [], can_manage: true, items: [], total: 0 }
  if (path.startsWith('/vision/batch/sets')) return { items: [], total: 0, max_images: 200, keep_sets: 10, keep_runs: 20 }
  if (path.startsWith('/vision/batch/runs')) return { id: 1, set_id: 1, flow_id: 1, flow_version: 1, label: '', note: '', origin: 'manual', status: 'done', progress: { done: 0, total: 0, stage: '' }, summary: {}, parent_id: null, owner_id: 1, recipe_name: '', meta: {}, error: '', created_at: '2026-01-01T00:00:00Z', finished_at: null, duration_s: 0, items: [], graph: { nodes: [], edges: [] }, ready: true, labeled: 0, match: 0, match_rate: null, confusion: { tp: 0, fp: 0, tn: 0, fn: 0 }, mismatches: [], error_nodes: [], slowest: [], node_time: [], outputs: [], judges: [], vs_parent: null, text: [], suggestions: [] }
  if (path.startsWith('/vision/agent/consult')) return { answer: '', provider: 'rules', suggestions: [], warnings: [] }
  if (path.startsWith('/vision/agent/chat')) return { kind: 'help', answer: '依平台文件：到「批次測試」頁按「新增影像集」。', provider: 'rules', sources: [{ title: '使用者手冊 › 批次測試頁', page: 'user-guide.html', heading: '批次測試頁', url: '/docs/user-guide.html#batch', snippet: '選擇流程後按「新增影像集」', kind: 'doc' }], warnings: [] }
  if (path.startsWith('/vision/agent/help/search')) return { items: [], sections: 0, pages: 0, tools: 0 }
  if (path.startsWith('/vision/flows')) return { items: [FLOW], total: 1, limit: 100, offset: 0 }
  if (path.startsWith('/vision/tool-types')) return { items: [{ key: 'grayscale', label: '灰階', description: '轉灰階', category: 'preprocess', icon: 'Box', params: [], inputs: [{ key: 'image', label: '影像', type: 'image' }], outputs: [{ key: 'image', label: '影像', type: 'image' }], heavy: false }], categories: [{ key: 'preprocess', label: '影像前處理' }] }
  if (path.startsWith('/vision/capture/download/info')) return { available: false, version: '', filename: '', size: 0, sha256: '', built_at: null, url: '/api/vision/capture/download' }
  if (path.startsWith('/vision/capture/clients')) return { listening: true, host: '0.0.0.0', port: 9100, items: [{ name: 'line-pc', address: '127.0.0.1:50000', version: '0.1.0', hostname: 'LINE-PC', connected_at: '2026-01-01T00:00:00', local: true, prefer_encoding: 'raw', shm: true, channels: [{ id: 'cam1', label: '產線相機 1', driver: 'basler', index: 0, width: 1280, height: 960, channels: 1, dtype: 'u8', pixel_format: 'Mono8', roi: { x: 0, y: 0, w: 1280, h: 960 }, full: { w: 1280, h: 960 }, mode: 'on_demand', enabled: true, streaming: false, seq: 12, last_frame_age_ms: 120, encoding: 'shm', shm: true, last_error: '', in_use_by: [], fps: 9.5, bytes_per_s: 0, frames: 12 }] }] }
  if (path.startsWith('/vision/capture')) return {}
  if (path.startsWith('/vision/sources/kinds')) return { items: [{ kind: 'folder', label: '資料夾', fields: ['path'] }, { kind: 'capture', label: '擷取端相機', fields: ['client', 'channel', 'mode', 'timeout_ms', 'fresh', 'encoding'] }] }
  if (path.startsWith('/vision/sources')) return { items: [{ id: 1, name: '範例：圓孔量測', kind: 'folder', group: '範例', config: { path: 'x' }, status: {}, is_enabled: true }, { id: 2, name: '產線相機', kind: 'capture', group: '', config: { client: 'old-pc', channel: 'cam1', mode: 'on_demand' }, status: { open: false, connected: false, last_error: '' }, is_enabled: true }] }
  if (path.startsWith('/vision/assets')) return { items: [] }
  if (path.startsWith('/vision/groups')) return { items: [{ id: 1, kind: 'source', name: '範例' }] }
  if (path.startsWith('/vision/templates')) return { items: [], can_manage: true }
  if (path.startsWith('/vision/capacity')) return { active: 0, max_workers: 4, flows: [], images: { images: 0, bytes: 0, runs: 0, encoded: 0 }, queue: {} }
  if (path.startsWith('/vision/agent/info')) return { provider: 'offline', model: '', llm: false, has_key: false, key_hint: '', source: 'none', mode: 'single', reason: '', providers: [{ value: 'offline', label: '離線規則引擎', default_model: '' }] }
  if (path.startsWith('/vision/agent/jobs')) return { items: [] }
  if (path.startsWith('/vision/agent/sessions')) return { items: [], total: 0 }
  if (path.startsWith('/vision/agent/skills/custom')) return { items: [] }
  if (path.startsWith('/vision/agent/clarify')) return { ready: true, questions: [], summary: '', intent: 'count', provider: 'rules' }
  if (path.startsWith('/vision/agent/run')) return { graph: { nodes: [], edges: [] }, report: { id: 'r', status: 'ok', outputs: {}, nodes: {}, duration_ms: 1 }, reports: [], main_image: 0 }
  if (path.startsWith('/vision/agent/autotune')) return { graph: { nodes: [], edges: [] }, rationale: '', provider: 'autotune', changes: [], before: { ok: 0, ng: 0, failed: 0 }, after: null, items: [], applied: false }
  if (path.startsWith('/vision/agent/skills')) return { items: [{ key: 'platform', label: '平台規則', category: 'guide', curated: true }] }
  if (path.startsWith('/vision/dl/projects')) return { items: [] }
  if (path.startsWith('/vision/dl/trainers')) return { items: [] }
  if (path.startsWith('/vision/dl/train/status')) return { running: false }
  if (path.startsWith('/vision/dl/devices')) return { available: ['cpu'], preferred: ['cpu'], train_device: 'cpu', accelerators: [], gpus: [], providers: ['CPUExecutionProvider'] }
  if (path.startsWith('/vision/integration/trace')) return { items: [{ seq: 1, ts: 1788500000, channel: 'tcp', direction: 'in', name: '127.0.0.1:5000', summary: 'RUN 1', ok: true, ms: 3.2, detail: { ok: true } }], seq: 1, channels: { http: 0, tcp: 1, modbus: 0, capture: 0 }, keep: 300, watching: true }
  if (path.startsWith('/vision/integration/info')) return { http_base: 'http://127.0.0.1:8000/api', host: '127.0.0.1', http_port: 8000, tcp_host: '0.0.0.0', tcp_port: 9000, tcp_listening: true, api_key_required: false, max_workers: 4, run_timeout_s: 30, commands: ['RUN <flow> [k=v ...]', 'TRIGGER <flow>', 'STATUS [flow]', 'LIST', 'PING'], capture_host: '0.0.0.0', capture_port: 9100, capture_listening: true, capture_download_url: '/api/vision/capture/download' }
  if (path.startsWith('/vision/connections')) return { items: [] }
  if (path.startsWith('/vision/lock')) return { locked: false, holder: '', reason: '', expires_at: null }
  return {}
}

export function installApiMock() {
  vi.mock('@/lib/api', async (importOriginal) => {
    const actual = await importOriginal<typeof import('@/lib/api')>()
    return {
      ...actual,
      api: {
        get: vi.fn(async (path: string) => routes(path)),
        post: vi.fn(async (path: string) => routes(path)),
        postForm: vi.fn(async (path: string) => routes(path)),
        patch: vi.fn(async (path: string) => routes(path)),
        delete: vi.fn(async () => undefined),
      },
      authToken: () => 'test-token',
      apiKey: () => '',
    }
  })
}
