// 只重拍使用者手冊的「一張」截圖：docs_shots.mjs 會把全部 27 張重拍一遍，示範資料不齊時會把既有的好圖換成殘缺版；
// 新增或改了單一頁面時用這支，只更新那一張與 docs_shots_callouts.txt 裡對應的那一行。
// 用法：set VS_TOKEN=<管理員 token> && node scripts/docs_shot_page.mjs integration-devices [more-names…]
//   PW_EXE 可指向系統 Chrome。頁面定義表 PAGES 與 docs_shots.mjs 同一套 callout 寫法（target 是 selector、text=… 或 locator 函式）。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '../frontend/node_modules/playwright/index.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const IMG = path.resolve(here, '..', 'docs', 'img')
const CALLOUTS = path.join(here, 'docs_shots_callouts.txt')
const token = process.env.VS_TOKEN || ''
if (!token) { console.error('VS_TOKEN is required'); process.exit(1) }
const names = process.argv.slice(2)
if (!names.length) { console.error('give at least one page name, e.g. integration-devices'); process.exit(1) }
const FRONT = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000/api'
const H = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
const j = async (p, init = {}) => { const r = await fetch(`${API}${p}`, { ...init, headers: { ...H, ...(init.headers || {}) } }); if (r.status === 204) return null; const t = await r.text(); try { return JSON.parse(t) } catch { return t } }

/** 每頁：路由、等待哪個元素、標記清單（順序＝手冊 figcaption 的編號）；setup 建示範資料、teardown 清掉 */
const PAGES = {
  'dl': {
    route: '/dl', ready: 'main',
    // 示範站台有「實例分割」專案；影片抽樣面板在選了專案之後才出現
    before: async (page) => {
      const row = page.locator('button', { hasText: '實例分割' }).first()
      if (await row.count()) { await row.click(); await page.waitForTimeout(1200) } else { console.log('missing dl project button') }
      // 影片面板預設收合，手冊要看到它的欄位：展開它
      const toggle = page.locator('[data-testid="dl-video-extract"] button[aria-expanded="false"]').first()
      if (await toggle.count()) { await toggle.click(); await page.waitForTimeout(400) }
    },
    callouts: [
      { target: '[data-testid="dl-new"]', label: 'dl-new' }, { target: '[data-testid="dl-grid"]', label: 'dl-grid' }, { target: '[data-testid="dl-auto"]', label: 'dl-auto' },
      { target: '[data-testid="dl-split-stats"]', label: 'dl-split-stats' }, { target: '[data-testid="dl-freeze"]', label: 'dl-freeze' }, { target: '[data-testid="dl-train"]', label: 'dl-train' },
      { target: '[data-testid="dl-create-flow"]', label: 'dl-create-flow' }, { target: '[data-testid="dl-video-extract-start"]', label: 'From video' },
    ],
  },
  // 流程編輯器：先選一個節點讓右側顯示參數（與 docs_shots.mjs 同一組標記）；流程與節點在 setup 從 API 現查
  'editor': {
    route: '/flows/__FLOW__', ready: '[data-testid="btn-preview"]',
    setup: async () => {
      const flows = await j('/vision/flows')
      const items = (flows && flows.items) || flows || []
      const flow = items.find((f) => f.graph && f.graph.nodes && f.graph.nodes.length > 1) || items[0]
      if (!flow) throw new Error('no flow to shoot')
      const detail = await j(`/vision/flows/${flow.id}`)
      const node = ((detail && detail.graph && detail.graph.nodes) || []).find((n) => n.type !== 'image_source' && n.type !== 'note') || null
      return { flowId: flow.id, nodeId: node ? node.id : null }
    },
    before: async (page, made) => {
      if (made && made.nodeId) {
        const nodeEl = page.locator(`.react-flow__node[data-id="${made.nodeId}"]`)
        if (await nodeEl.count()) { await nodeEl.first().click({ position: { x: 10, y: 10 } }); await page.waitForTimeout(600) }
      }
    },
    callouts: [
      { target: '[data-testid="toolbar-row-1"]', label: 'toolbar-row-1' }, { target: '[data-testid="toolbar-row-2"]', label: 'toolbar-row-2' }, { target: '[data-testid="btn-add-tool"]', label: 'btn-add-tool' },
      { target: '.react-flow', label: 'canvas' }, { target: '[data-testid="viewer-main"]', label: 'viewer-main' }, { target: '[data-testid="inspector"]', label: 'inspector' },
      { target: '[data-testid="open-tool-page"]', label: 'open-tool-page' }, { target: '[data-testid="btn-preview"]', label: 'btn-preview' }, { target: '[data-testid="btn-teach"]', label: 'btn-teach' },
      { target: '[data-testid="btn-stats"]', label: 'btn-stats' },
    ],
  },
  // 流程編輯器右側「未選取節點」的流程設定：三顆按鈕開變數／看板／結果回報對話框
  'editor-flow-settings': {
    route: '/flows/__FLOW__', ready: '[data-testid="btn-preview"]',
    setup: async () => {
      const flows = await j('/vision/flows')
      const items = (flows && flows.items) || flows || []
      const flow = items[0]
      if (!flow) throw new Error('no flow to shoot')
      return { flowId: flow.id }
    },
    before: async (page) => {
      // 點畫布空白處取消選取，右側才會顯示流程設定
      const pane = page.locator('.react-flow__pane').first()
      if (await pane.count()) { await pane.click({ position: { x: 5, y: 5 } }); await page.waitForTimeout(500) }
    },
    callouts: [
      // 未選節點時右側面板沒有 inspector 的 testid：用「包含三顆按鈕的 aside」當目標
      { target: 'aside:has([data-testid="editor-open-variables"])', label: 'inspector' }, { target: '[data-testid="editor-open-variables"]', label: 'Variables' },
      { target: '[data-testid="editor-open-board"]', label: 'Board settings' }, { target: '[data-testid="editor-open-comm"]', label: 'Result reporting' },
    ],
  },
  'calibration-stereo': {
    route: '/calibration', ready: 'main',
    before: async (page) => { await page.click('[data-testid="calib-mode-stereo"]'); await page.waitForTimeout(600) },
    callouts: [
      { target: '[data-testid="calib-mode-stereo"]', label: 'Stereo mode' }, { target: '[data-testid="calib-stereo-import"]', label: 'Import' },
      { target: '[data-testid="calib-stereo-capture"]', label: 'Capture pair' }, { target: '[data-testid="calib-stereo-reference"]', label: 'Belt reference' },
      { target: '[data-testid="calib-stereo-result"]', label: 'Result' },
    ],
  },
  'integration-devices': {
    route: '/integration/devices', ready: '[data-testid="integration-info"]',
    callouts: [{ target: '[data-testid="conn-create"]', label: 'New connection' }, { target: 'main table', label: 'connections' }, { target: '[data-testid="conn-export"]', label: 'Export' }],
    setup: async () => {
      const made = []
      for (const body of [
        { name: 'ring-light', kind: 'light', is_enabled: true, config: { transport: 'serial', port: 'loop://', preset: 'ccs_pd3', channels: 4, value_max: 255, timeout_s: 1 } },
        { name: 'barcode-reader', kind: 'serial', is_enabled: true, config: { port: 'loop://', baudrate: 9600, end_char: '\n', encoding: 'utf-8', timeout_s: 1 } },
      ]) { const r = await j('/vision/connections', { method: 'POST', body: JSON.stringify(body) }); if (r && r.id) made.push(r.id) }
      return made
    },
    teardown: async (made) => { for (const id of made) await j(`/vision/connections/${id}`, { method: 'DELETE' }) },
  },
}

const OVERLAY = (rects) => {
  document.querySelectorAll('.doc-callout').forEach((e) => e.remove())
  for (const r of rects) {
    const box = document.createElement('div'); box.className = 'doc-callout'
    box.style.cssText = 'position:fixed;z-index:99999;pointer-events:none;border:2px solid #00ff88;border-radius:4px;box-shadow:0 0 0 2px rgba(0,0,0,.55),0 0 12px rgba(0,255,136,.55);left:' + (r.x - 3) + 'px;top:' + (r.y - 3) + 'px;width:' + (r.w + 6) + 'px;height:' + (r.h + 6) + 'px'
    const n = document.createElement('div'); n.className = 'doc-callout'; n.textContent = String(r.n)
    n.style.cssText = 'position:fixed;z-index:100000;pointer-events:none;width:26px;height:26px;border-radius:50%;background:#00ff88;color:#0a0a12;font:700 14px/26px ui-monospace,Consolas,monospace;text-align:center;box-shadow:0 0 0 2px #0a0a12;left:' + Math.max(0, r.x - 16) + 'px;top:' + Math.max(0, r.y - 16) + 'px'
    document.body.appendChild(box); document.body.appendChild(n)
  }
}
const CLEAR = () => document.querySelectorAll('.doc-callout').forEach((e) => e.remove())

async function resolve(page, target) {
  const loc = typeof target === 'string' ? (target.startsWith('text=') ? page.getByText(target.slice(5), { exact: false }) : page.locator(target)) : target(page)
  const first = loc.first()
  if (!(await first.count())) return null
  // 手冊圖是固定 1440×900 的首屏：不捲動頁面（捲了之後各目標的座標會對不上同一張截圖），首屏外的目標當沒抓到
  await page.evaluate(() => window.scrollTo(0, 0))
  const b = await first.boundingBox()
  // 目標的上緣要在首屏內；整欄高的面板（右側 inspector）下緣會貼到或超出視窗底，交給呼叫端裁到 900
  return b && b.width > 0 && b.height > 0 && b.y >= 0 && b.y < 900 ? b : null
}

function writeCallouts(name, line) {
  const lines = fs.existsSync(CALLOUTS) ? fs.readFileSync(CALLOUTS, 'utf8').split(/\r?\n/).filter((l) => l && !l.startsWith(`${name}:`)) : []
  lines.push(`${name}: ${line}`)
  fs.writeFileSync(CALLOUTS, lines.join('\n') + '\n')
}

const browser = await chromium.launch(process.env.PW_EXE ? { executablePath: process.env.PW_EXE } : {})
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
await ctx.addInitScript(({ t }) => { localStorage.setItem('vs.token', t); localStorage.setItem('vs.language', 'en'); localStorage.removeItem('vs.assistant.v1') }, { t: token })
const page = await ctx.newPage()
// 語言與主題存在帳號偏好，/auth/me 帶回來會蓋掉 localStorage：手冊一律英文，截完還原
const me = await j('/auth/me')
const prevLanguage = me && me.prefs ? me.prefs.language : undefined
await j('/auth/prefs', { method: 'PATCH', body: JSON.stringify({ language: 'en' }) })
let failures = 0
try {
for (const name of names) {
  const spec = PAGES[name]
  if (!spec) { console.error('unknown page', name, '— add it to PAGES'); failures += 1; continue }
  const made = spec.setup ? await spec.setup() : null
  try {
  // route 裡的 __FLOW__ 由 setup 回傳的 flowId 代入（編輯器類頁面）
  const route = spec.route.replace('__FLOW__', made && made.flowId ? String(made.flowId) : '')
  await page.goto(`${FRONT}${route}`)
  await page.waitForSelector(spec.ready, { timeout: 30000 })
  await page.waitForTimeout(1400)
  if (spec.before) await spec.before(page, made)
  const rects = []
  const resolved = []
  for (const c of spec.callouts) {
    const b = await resolve(page, c.target)
    if (!b) { console.log('missing', name, c.label); continue }
    const n = rects.length + 1
    rects.push({ n, x: Math.max(0, b.x), y: Math.max(0, b.y), w: Math.min(b.width, 1440 - b.x), h: Math.min(b.height, 900 - b.y) })
    resolved.push(`${n}=${c.label}`)
  }
  await page.evaluate(OVERLAY, rects)
  await page.waitForTimeout(150)
  await page.screenshot({ path: path.join(IMG, `${name}.jpg`), type: 'jpeg', quality: 82 })
  await page.evaluate(CLEAR)
  writeCallouts(name, resolved.join(' | '))
  console.log('shot', name, `${rects.length}/${spec.callouts.length}`)
  } finally { if (spec.teardown) await spec.teardown(made) }
}
} finally {
  if (prevLanguage) await j('/auth/prefs', { method: 'PATCH', body: JSON.stringify({ language: prevLanguage }) })
  await browser.close()
}
process.exit(failures ? 1 : 0)
