/** `@/lib/api` 的假後端：依路徑回最小合法資料，讓頁面 render 走完 loading → 內容。 */
import { vi } from 'vitest'

export const ME = {
  // 與真實 /auth/me 一致：帶 is_admin 與 role，否則前端會把測試身分當成工程師
  kind: 'user', is_admin: true, role: 'admin',
  user: { id: 1, username: 'admin', display_name: '管理員', is_staff: true, is_active: true, role: 'admin' },
  permissions: ['flows.run', 'flows.teach', 'flows.edit', 'sources', 'assets', 'batch', 'golden', 'dl', 'agent', 'integration', 'audit'],
  prefs: {}, lock: { locked: false, holder: '', reason: '', expires_at: null },
}

export const FLOW = { id: 1, name: '示範流程', description: '', version: 1, is_enabled: true, continuous_interval_ms: 0, timeout_s: 0, stop_on_ng: false, owner_id: 1, owner_name: 'admin', recipe_count: 0, commissioned: false, stats: { last_status: 'ok', total: 3, ok: 3, ng: 0, failed: 0, avg_ms: 5, last_ms: 5, running: false, continuous: false, queued: 0 }, graph: { nodes: [{ id: 'camera', type: 'image_source', label: 'Camera', params: {} }, { id: 'judge_out', type: 'output', params: { name: 'judge' } }, { id: 'width_out', type: 'output', params: { name: 'width' } }], edges: [] }, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }

export const RUNS = [
  { id: 'run-2', flow_id: 1, flow_version: 1, trigger: 'ui', status: 'ng', started_at: 1788500100, finished_at: 1788500101, duration_ms: 14, error: '', outputs: { judge: 'NG', width: 2.2 }, nodes: { camera: { status: 'ok', duration_ms: 2, message: '', branch: null, outputs: { image: { ref: 'run-2:image', width: 640, height: 480 } }, overlays: [], overlay_on: null, detail: {}, logs: [] } }, persisted: true },
  { id: 'run-1', flow_id: 1, flow_version: 1, trigger: 'ui', status: 'ok', started_at: 1788500000, finished_at: 1788500001, duration_ms: 13.5, error: '', outputs: { judge: 'OK', width: 1.5 }, nodes: { camera: { status: 'ok', duration_ms: 2, message: '', branch: null, outputs: { image: { ref: 'run-1:image', width: 640, height: 480 } }, overlays: [], overlay_on: null, detail: {}, logs: [] } }, persisted: true },
]

export const DASHBOARD_LAYOUT = {
  rows: 2,
  cols: 3,
  cells: [
    { id: 'image', row: 1, col: 1, row_span: 2, col_span: 2 },
    { id: 'verdict', row: 1, col: 3, row_span: 1, col_span: 1 },
    { id: 'stats', row: 2, col: 3, row_span: 1, col_span: 1 },
  ],
  bars: { top: true, bottom: true, left: false, right: false },
  default_flow_id: 1,
  widgets: [
    { id: 'latest_image', type: 'image', cell: 'image', props: { overlays: true, crosshair: true }, source: { flow_id: 1, kind: 'image' } },
    { id: 'verdict', type: 'verdict', cell: 'verdict', props: {}, source: { flow_id: 1, kind: 'status' } },
    { id: 'today', type: 'stats', cell: 'stats', props: {}, source: { flow_id: 1, kind: 'counts' } },
  ],
  theme: {},
}

export const DASHBOARD = { id: 1, name: 'Line status dashboard', is_default: true, owner_name: 'admin', updated_at: '2026-01-01T00:00:00Z', widget_count: 3, layout: DASHBOARD_LAYOUT }

export const DL_PROJECT = {
  id: 1,
  name: 'Fast part',
  description: '',
  trainer_kind: 'ai_detect',
  classes: ['part'],
  params: {},
  last_asset_id: '',
  last_metrics: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  counts: { total: 2, unlabeled: 2, per_class: { part: 0 } },
}

export const DL_TRAINER = {
  kind: 'ai_detect',
  label: 'Object detection',
  description: 'Finds object boxes from labeled examples.',
  label_mode: 'shapes',
  tool_key: 'ai_detect',
  devices: ['cpu'],
  min_per_class: 1,
  params: [
    { key: 'model', label: 'Size', kind: 'select', required: false, default: 'n', help_text: '', options: [{ value: 'n', label: 'Nano' }], unit: '', minimum: null, maximum: null, step: null, visible_when: null, shapes: [], accept: '', group: '' },
    { key: 'epochs', label: 'Epochs', kind: 'number', required: false, default: 100, help_text: '', options: [], unit: '', minimum: 1, maximum: 2000, step: null, visible_when: null, shapes: [], accept: '', group: '' },
    { key: 'imgsz', label: 'Image size', kind: 'select', required: false, default: 640, help_text: '', options: [{ value: '320', label: '320' }, { value: '640', label: '640' }], unit: '', minimum: null, maximum: null, step: null, visible_when: null, shapes: [], accept: '', group: '' },
  ],
}

export const DL_SAMPLES = [
  { id: 's1', label: '', labeled_by: '', score: 0, width: 320, height: 240, created_at: '2026-01-01T00:00:00Z', shapes: [], split: '' },
  { id: 's2', label: '', labeled_by: '', score: 0, width: 320, height: 240, created_at: '2026-01-01T00:00:01Z', shapes: [], split: '' },
]

export const DASHBOARD_DATA = {
  generated_at: '2026-01-01T00:00:00Z',
  flows: {
    '1': {
      flow: { id: 1, name: 'demo', title: 'Line 1' },
      config: { title: 'Line 1', image: '', overlays: true, values: [{ key: 'width', unit: 'mm', low: 1, high: 2 }], variables: ['lot'], show_verdict: true, show_counts: true },
      run: { id: 'run-1', status: 'ok', verdict: 'OK', label: '', started_at: 1788500000, duration_ms: 13.5, trigger: 'ui', recipe: '', error: '', image: { ref: 'run-1:image', width: 640, height: 480 }, overlays: [] },
      values: [{ key: 'width', label: 'width', unit: 'mm', value: 1.5, text: '1.5', ok: true, present: true }],
      variables: { lot: 'A17' },
      counts: { date: '2026-09-08', total: 10, ok: 9, ng: 1, failed: 0, yield: 0.9 },
      stats: {},
    },
  },
  device: {
    station_id: 'ST01',
    version: '1.0.0',
    lock: { locked: false, holder: '', reason: '' },
    capacity: { active: 0, max_workers: 4, flows: [], images: { images: 0, bytes: 0, runs: 0, encoded: 0 } },
    flows_running: [],
  },
  variables: { station: { shift: 'day' } },
}

export function routes(path: string, body?: unknown): unknown {
  if (path.startsWith('/auth/status')) return { setup_required: false }
  if (path.startsWith('/auth/me')) return ME
  if (path.startsWith('/vision/batch/sets/')) return { id: 1, flow_id: 1, name: '影像集 A', source: 'upload', image_count: 0, size_bytes: 0, owner_id: 1, labeled: { ok: 0, ng: 0 }, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', images: [], can_manage: true, items: [], total: 0 }
  if (path.startsWith('/vision/batch/sets')) return { items: [], total: 0, max_images: 200, keep_sets: 10, keep_runs: 20 }
  if (path.startsWith('/vision/batch/runs')) return { id: 1, set_id: 1, flow_id: 1, flow_version: 1, label: '', note: '', origin: 'manual', status: 'done', progress: { done: 0, total: 0, stage: '' }, summary: {}, parent_id: null, owner_id: 1, recipe_name: '', meta: {}, error: '', created_at: '2026-01-01T00:00:00Z', finished_at: null, duration_s: 0, items: [], graph: { nodes: [], edges: [] }, ready: true, labeled: 0, match: 0, match_rate: null, confusion: { tp: 0, fp: 0, tn: 0, fn: 0 }, mismatches: [], error_nodes: [], slowest: [], node_time: [], outputs: [], judges: [], vs_parent: null, text: [], suggestions: [] }
  if (path.startsWith('/vision/agent/consult')) return { answer: '', provider: 'rules', suggestions: [], warnings: [] }
  if (path.startsWith('/vision/agent/memory')) return { facts: [{ id: 1, kind: 'fact', text: '產線 3 用流程「檢測 A」', answer: '', rating: 0, created_at: null }], qa: [{ id: 2, kind: 'qa', text: '如何建立影像來源？', answer: '到來源庫', rating: 1, created_at: null }], limits: { facts: 50, qa: 200 } }
  if (path.startsWith('/vision/agent/chat')) return { kind: 'help', answer: '依平台文件：到「批次測試」頁按「新增影像集」。', provider: 'rules', sources: [{ title: '使用者手冊 › 批次測試頁', page: 'user-guide.html', heading: '批次測試頁', url: '/docs/user-guide.html#batch', snippet: '選擇流程後按「新增影像集」', kind: 'doc' }], warnings: [] }
  if (path.startsWith('/vision/agent/help/search')) return { items: [], sections: 0, pages: 0, tools: 0 }
  if (/\/vision\/flows\/\d+\/spc/.test(path)) return { flow_id: 1, output: 'diameter', outputs: ['diameter'], hours: 24, chart: 'imr', subgroup: 5, enabled: true, retention_days: 365, series: [{ ts: '2026-01-01T00:00:00Z', value: 12.01, run_id: 'a' }, { ts: '2026-01-01T00:00:10Z', value: 12.02, run_id: 'b' }, { ts: '2026-01-01T00:00:20Z', value: 11.99, run_id: 'c' }], analysis: { limits: { chart: 'imr', n: 3, cl: 12.0067, ucl: 12.06, lcl: 11.95, sigma: 0.0177, mr_bar: 0.02, mr_ucl: 0.065 }, capability: { usl: 12.05, lsl: 11.95, cp: 0.94, cpk: 0.8, cpu: 0.8, cpl: 1.07, out_of_spec: 0 }, rules: {}, rule_names: {}, flagged: [], summary: { n: 3, mean: 12.0067, std: 0.0153, min: 11.99, max: 12.02 } }, spec: { usl: 12.05, lsl: 11.95, nominal: 12, unit: 'mm' }, alerts: [] }
  if (path.startsWith('/vision/spc/alerts')) return { items: [], cached: false }
  if (path.startsWith('/vision/summary')) return { station_id: 'ST01', version: '1.0.0', hours: 24, locked: false, totals: { total: 0, ok: 0, ng: 0, failed: 0, yield: null }, flows: [] }
  if (path.startsWith('/vision/audit')) return { items: [{ id: 1, at: '2026-01-01T00:00:00Z', actor: 'admin', actor_kind: 'user', action: 'flow.update', target_type: 'flow', target_id: '1', target_name: '示範流程', summary: 'threshold 60 → 46', detail: {}, ip: '127.0.0.1' }], total: 1, limit: 50, offset: 0, actions: ['flow.update'], actors: ['admin'] }
  if (path === '/vision/dashboards') return { items: [DASHBOARD] }
  if (path === '/vision/dashboards/default') return DASHBOARD
  if (/\/vision\/dashboards\/\d+\/data$/.test(path)) return DASHBOARD_DATA
  if (/\/vision\/dashboards\/\d+$/.test(path)) return DASHBOARD
  if (/\/vision\/flows\/\d+$/.test(path)) return FLOW
  if (/\/vision\/flows\/\d+\/versions/.test(path)) return { items: [], current: 1, keep: 50 }
  if (/\/vision\/flows\/\d+\/recipes/.test(path)) return { items: [] }
  if (/\/vision\/flows\/\d+\/recent/.test(path)) return { items: [] }
  if (/\/vision\/flows\/\d+\/runs/.test(path)) return { items: RUNS, total: RUNS.length, limit: 20, offset: 0 }
  if (/\/vision\/flows\/\d+\/stats/.test(path)) return { hours: 24, total: 8, by_status: { ok: 7, ng: 1 }, avg_ms: 12, max_ms: 30, hourly: [], live: { runs: 0, ok: 0, ng: 0, failed: 0, avg_ms: 0, max_ms: 0, last_ms: 0, last_status: '', last_run_id: '', last_finished_at: 0 } }
  if (path.startsWith('/vision/flows')) return { items: [FLOW], total: 1, limit: 100, offset: 0 }
  if (path.startsWith('/vision/tool-types')) return { items: [{ key: 'grayscale', label: '灰階', description: '轉灰階', category: 'preprocess', icon: 'Box', params: [], inputs: [{ key: 'image', label: '影像', type: 'image' }], outputs: [{ key: 'image', label: '影像', type: 'image' }], heavy: false }], categories: [{ key: 'preprocess', label: '影像前處理' }] }
  if (path.startsWith('/vision/capture/download/info')) return { available: false, version: '', filename: '', size: 0, sha256: '', built_at: null, url: '/api/vision/capture/download' }
  if (path.startsWith('/vision/capture/clients')) return { listening: true, host: '0.0.0.0', port: 9100, items: [{ name: 'line-pc', address: '127.0.0.1:50000', version: '0.1.0', hostname: 'LINE-PC', connected_at: '2026-01-01T00:00:00', local: true, prefer_encoding: 'raw', shm: true, channels: [{ id: 'cam1', label: '產線相機 1', driver: 'basler', index: 0, width: 1280, height: 960, channels: 1, dtype: 'u8', pixel_format: 'Mono8', roi: { x: 0, y: 0, w: 1280, h: 960 }, full: { w: 1280, h: 960 }, mode: 'on_demand', enabled: true, streaming: false, seq: 12, last_frame_age_ms: 120, encoding: 'shm', shm: true, last_error: '', in_use_by: [], fps: 9.5, bytes_per_s: 0, frames: 12 }] }] }
  if (path.startsWith('/vision/capture')) return {}
  if (path.startsWith('/vision/sources/kinds')) return { items: [{ kind: 'folder', label: '資料夾', fields: ['path'] }, { kind: 'capture', label: '擷取端相機', fields: ['client', 'channel', 'mode', 'timeout_ms', 'fresh', 'encoding'] }] }
  if (path.startsWith('/vision/sources')) return { items: [{ id: 1, name: '範例：圓孔量測', kind: 'folder', group: '範例', config: { path: 'x' }, status: {}, is_enabled: true }, { id: 2, name: '產線相機', kind: 'capture', group: '', config: { client: 'old-pc', channel: 'cam1', mode: 'on_demand' }, status: { open: false, connected: false, last_error: '' }, is_enabled: true }] }
  if (/\/vision\/flows\/\d+\/board$/.test(path)) return { flow: { id: 1, name: 'demo', title: 'Line 1' }, config: { title: 'Line 1', image: '', overlays: true, values: [{ key: 'width', unit: 'mm', low: 1, high: 2 }], variables: [], show_verdict: true, show_counts: true }, run: null, values: [{ key: 'width', label: 'width', unit: 'mm', value: null, text: '', ok: null, present: false }], variables: { lot: 'A17' }, counts: { date: '2026-09-06', total: 10, ok: 9, ng: 1, failed: 0, yield: 90 }, stats: {} }
  if (/\/vision\/flows\/\d+\/variables$/.test(path)) return { flow_id: 1, items: { parts: 12, lot: 'A17' }, station: { shift: 'day' } }
  if (path.startsWith('/vision/variables')) return { items: { shift: 'day' } }
  if (path.startsWith('/vision/fixed-images')) return { items: [{ id: 'fixed-1', name: 'Reference' }], count: 1, bytes: 128, orphans: [] }
  if (path.startsWith('/vision/calibration/capture')) return { ref: 'cal:capture:image', width: 640, height: 480, name: 'shot.png' }
  if (path.startsWith('/vision/calibration/detect')) return { found: true, count: 54, corners: [[10, 10], [20, 10]], overlays: [{ kind: 'points', points: [[10, 10], [20, 10]] }] }
  if (path.startsWith('/vision/calibration/solve')) {
    const mode = typeof body === 'object' && body ? (body as { mode?: unknown }).mode : ''
    if (mode === 'mapping') {
      return {
        payload: {
          unit: 'mm',
          image_size: [640, 480],
          mapping: {
            kind: 'affine',
            matrix: [[1, 0, 30], [0, 1, -20], [0, 0, 1]],
            points: [
              { ax: 10, ay: 20, bx: 40, by: 0, error: 0.01 },
              { ax: 80, ay: 20, bx: 110, by: 0, error: 0.02 },
              { ax: 10, ay: 90, bx: 40, by: 70, error: 0.01 },
            ],
            rms: 0.01,
            max_error: 0.02,
          },
        },
        summary: 'camera affine 0.010 px rms',
        quality: { mapping: 'good' },
      }
    }
    return { payload: { unit: 'mm', image_size: [640, 480], world: { kind: 'perspective', matrix: [[0.05, 0, 0], [0, 0.05, 0], [0, 0, 1]], mm_per_px: 0.05, rms: 0.01, max_error: 0.02, points: [] } }, summary: 'perspective 0.05000 mm/px', quality: { world: 'good' } }
  }
  if (path.startsWith('/vision/calibration')) return { items: [] }
  if (path.startsWith('/vision/assets')) return { items: [] }
  if (path.startsWith('/vision/groups')) return { items: [{ id: 1, kind: 'source', name: '範例' }] }
  if (path.startsWith('/vision/agent/chats')) return { items: [], limits: { chats: 50, messages: 60 } }
  if (path.startsWith('/vision/retention')) {
    const settings = { run_days: 365, audit_days: 365, measurement_days: 365, archive_days: 90, archive_max_gb: 20, backup_keep: 10, window_hour: 3, vacuum: true, enabled: true }
    return {
      settings, defaults: settings, last_sweep_at: null, last_deep_at: null, last_result: {}, busy: false,
      usage: { db_bytes: 1048576, archive_files: 0, archive_bytes: 0, backup_files: 0, backup_bytes: 0, runs: 0, audit: 0, measurements: 0 },
    }
  }
  // 內建範本：畫廊預設用範例圖片（has_samples），instantiate 回帶圖的固定影像節點
  if (/\/vision\/templates\/[^/]+\/instantiate/.test(path)) return { graph: { nodes: [{ id: 'src', type: 'fixed_image', params: { images: [{ id: 'abc', name: 'sample 01.png', width: 8, height: 6, size: 99 }], role: 'acquire', mode: 'cycle' } }], edges: [] }, missing_source: false, used_samples: true, name: '孔數檢測', description: '' }
  if (path.startsWith('/vision/templates')) return { items: [{ id: 'builtin:hole_count', name: '孔數檢測', description: '灰階、二值化、blob 計數', category: 'count', source: 'builtin', node_count: 8, graph: { nodes: [{ id: 'src', type: 'image_source', params: {} }], edges: [] }, owner_name: '', created_at: null, has_samples: true }], can_manage: true }
  if (path.startsWith('/vision/capacity')) return { active: 0, max_workers: 4, flows: [], images: { images: 0, bytes: 0, runs: 0, encoded: 0 }, queue: {} }
  if (path.startsWith('/vision/agent/info')) return { provider: 'offline', model: '', llm: false, has_key: false, key_hint: '', source: 'none', mode: 'single', reason: '', providers: [{ value: 'offline', label: '離線規則引擎', default_model: '' }] }
  if (path.startsWith('/vision/agent/jobs')) return { items: [] }
  if (path.startsWith('/vision/agent/sessions')) return { items: [], total: 0 }
  if (path.startsWith('/vision/agent/skills/custom')) return { items: [] }
  if (path.startsWith('/vision/agent/clarify')) return { ready: true, questions: [], summary: '', intent: 'count', provider: 'rules' }
  if (path.startsWith('/vision/agent/run')) return { graph: { nodes: [], edges: [] }, report: { id: 'r', status: 'ok', outputs: {}, nodes: {}, duration_ms: 1 }, reports: [], main_image: 0 }
  if (path.startsWith('/vision/agent/autotune')) return { graph: { nodes: [], edges: [] }, rationale: '', provider: 'autotune', changes: [], before: { ok: 0, ng: 0, failed: 0 }, after: null, items: [], applied: false }
  if (path.startsWith('/vision/agent/skills')) return { items: [{ key: 'platform', label: '平台規則', category: 'guide', curated: true }] }
  if (/\/vision\/dl\/projects\/\d+\/quick-register$/.test(path)) return { job_id: 'job123', labeled: 2, skipped: 0, params: { model: 'n', epochs: 20, imgsz: 320, batch: 4 } }
  if (/\/vision\/dl\/projects\/\d+\/samples$/.test(path)) return { items: DL_SAMPLES }
  if (/\/vision\/dl\/projects\/\d+\/versions$/.test(path)) return { items: [] }
  if (/\/vision\/dl\/projects\/\d+$/.test(path)) return DL_PROJECT
  if (path.startsWith('/vision/dl/projects')) return { items: [DL_PROJECT] }
  if (path.startsWith('/vision/dl/trainers')) return { items: [DL_TRAINER] }
  if (path.startsWith('/vision/dl/train/status')) return { job: null }
  if (path.startsWith('/vision/dl/devices')) return { available: ['cpu'], preferred: ['cpu'], train_device: 'cpu', accelerators: [], gpus: [], providers: ['CPUExecutionProvider'] }
  if (path.startsWith('/vision/integration/rules')) return { items: [{ id: 'r1', name: '', enabled: true, source: 'text', address: '', mode: 'rising', value: 0, value2: 0, match: 'prefix', pattern: 'SCAN ', capture: 'lot', action: 'run_flow', flow: 'demo', recipe: '', variable: '', scope: 'flow', set_value: '', args: {}, reason: '', ttl: 0, clear: false, done: '', reply: '' }] }
  if (path.startsWith('/vision/integration/trace')) return { items: [{ seq: 1, ts: 1788500000, channel: 'tcp', direction: 'in', name: '127.0.0.1:5000', summary: 'RUN 1', ok: true, ms: 3.2, detail: { ok: true } }], seq: 1, channels: { http: 0, tcp: 1, modbus: 0, capture: 0 }, keep: 300, watching: true }
  if (path.startsWith('/vision/integration/info')) return { http_base: 'http://127.0.0.1:8000/api', host: '127.0.0.1', http_port: 8000, tcp_host: '0.0.0.0', tcp_port: 9000, tcp_listening: true, api_key_required: false, max_workers: 4, run_timeout_s: 30, commands: ['RUN <flow> [k=v ...]', 'TRIGGER <flow>', 'STATUS [flow]', 'LIST', 'PING'], capture_host: '0.0.0.0', capture_port: 9100, capture_listening: true, capture_download_url: '/api/vision/capture/download' }
  if (path.startsWith('/openapi.json')) return { openapi: '3.1.0', info: { title: 'VisionSequence API', version: '1.0' }, paths: {
    '/api/vision/flows/{flow_id}/run': { post: { summary: 'Run Flow', tags: ['vision'], parameters: [{ name: 'flow_id', in: 'path', required: true, schema: { type: 'integer' } }, { name: 'wait', in: 'query', schema: { type: 'boolean', default: true } }], requestBody: { content: { 'multipart/form-data': { schema: { properties: { image: { anyOf: [{ type: 'string', format: 'binary' }, { type: 'null' }] }, context: { anyOf: [{ type: 'string' }, { type: 'null' }] } } } } } }, responses: { '200': { description: 'OK' } } } },
    '/api/vision/lock': { get: { summary: 'Get Lock', tags: ['lock'], responses: { '200': { description: 'OK' } } }, post: { summary: 'Acquire Lock', tags: ['lock'], requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/LockIn' } } } }, responses: { '200': { description: 'OK' } } } },
    '/api/auth/me': { get: { summary: 'Me', tags: ['auth'], responses: { '200': { description: 'OK' } } } },
  }, components: { schemas: { LockIn: { type: 'object', properties: { reason: { type: 'string', default: '' }, ttl_s: { anyOf: [{ type: 'integer' }, { type: 'null' }] } } } } } }
  if (path.startsWith('/vision/plugins')) return { dir: 'D:/vs/plugins', docs_url: '/docs/plugins.html', mounted: [], items: [
    { name: 'example_dark_ratio.py', path: 'D:/vs/plugins/example_dark_ratio.py', kind: 'file', status: 'ok', error: '', mounted: ['tool:dark_ratio'], requirements: false, loaded_at: 1 },
    { name: 'broken.py', path: 'D:/vs/plugins/broken.py', kind: 'file', status: 'error', error: "Missing package 'foo'", mounted: [], requirements: true, loaded_at: 1 },
  ] }
  if (path.startsWith('/vision/connections')) return { items: [] }
  if (path.startsWith('/vision/lock')) return { locked: false, holder: '', reason: '', expires_at: null }
  if (path.startsWith('/users/permissions')) return {
    features: [{ key: 'flows.run', default: { engineer: true, operator: true } }, { key: 'flows.edit', default: { engineer: true, operator: false } }, { key: 'dl', default: { engineer: true, operator: false } }],
    matrix: { engineer: ['flows.run', 'flows.edit', 'dl'], operator: ['flows.run'] },
    roles: ['engineer', 'operator'],
  }
  if (path.startsWith('/users')) return { items: [{ id: 1, username: 'admin', display_name: '管理員', is_staff: true, is_active: true, role: 'admin', last_login: '2026-01-01T00:00:00Z' }], roles: ['admin', 'engineer', 'operator'] }
  return {}
}

export function installApiMock() {
  vi.mock('@/lib/api', async (importOriginal) => {
    const actual = await importOriginal<typeof import('@/lib/api')>()
    return {
      ...actual,
      api: {
        get: vi.fn(async (path: string) => routes(path)),
        post: vi.fn(async (path: string, body?: unknown) => routes(path, body)),
        postForm: vi.fn(async (path: string) => routes(path)),
        put: vi.fn(async (path: string) => routes(path)),
        patch: vi.fn(async (path: string) => routes(path)),
        delete: vi.fn(async () => undefined),
      },
      authToken: () => 'test-token',
      apiKey: () => '',
    }
  })
}
