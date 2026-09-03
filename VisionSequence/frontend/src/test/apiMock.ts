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
  if (path.startsWith('/vision/flows')) return { items: [FLOW], total: 1, limit: 100, offset: 0 }
  if (path.startsWith('/vision/tool-types')) return { items: [{ key: 'grayscale', label: '灰階', description: '轉灰階', category: 'preprocess', icon: 'Box', params: [], inputs: [{ key: 'image', label: '影像', type: 'image' }], outputs: [{ key: 'image', label: '影像', type: 'image' }], heavy: false }], categories: [{ key: 'preprocess', label: '影像前處理' }] }
  if (path.startsWith('/vision/sources/kinds')) return { items: [{ kind: 'folder', label: '資料夾', fields: ['path'] }] }
  if (path.startsWith('/vision/sources')) return { items: [{ id: 1, name: '範例：圓孔量測', kind: 'folder', group: '範例', config: { path: 'x' }, status: {}, is_enabled: true }] }
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
  if (path.startsWith('/vision/integration/info')) return { host: '127.0.0.1', port: 8000, tcp_port: 9000, api_key_set: false, examples: {} }
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
