// 使用者手冊的截圖產生器：英文介面、1440×900，每張疊上編號標記（圓形數字＋外框）指出手冊提到的位置，存成 docs/img/<name>.jpg；
// 每張的標記清單寫到 scripts/docs_shots_callouts.txt（手冊的 figcaption 照這份順序寫）。
// 需要：伺服端與前端都在跑（scripts/dev.ps1）、示範資料（seed_demo）、一個管理員的權杖，以及 playwright 套件與 Chromium：
//   set VS_TOKEN=<管理員 token>    （manage.py shell: AuthToken.issue(user)）
//   set VS_TOKEN2=<另一個管理員 token>   （選填；鎖定橫幅那張要另一個人鎖住）
//   set PW_EXE=%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win64\chrome.exe   （playwright 版本與瀏覽器不合時指定）
//   npm i --no-save playwright && node scripts/docs_shots.mjs   （在 frontend/ 裡執行 npm i，playwright 不進 package.json）
// 找不到的標記會列在 missing 裡略過（例如頁面還沒有資料時），不會讓整批失敗。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '../frontend/node_modules/playwright/index.mjs'  // 從 scripts/ 解析不到 frontend 的套件，走相對路徑

const here = path.dirname(fileURLToPath(import.meta.url))
const IMG = path.resolve(here, '..', 'docs', 'img')
fs.mkdirSync(IMG, { recursive: true })
const token = process.env.VS_TOKEN || ''
const token2 = process.env.VS_TOKEN2 || ''
if (!token) { console.error('VS_TOKEN is required'); process.exit(1) }
const FRONT = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000/api'
const H = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
const j = async (p, init = {}) => { const r = await fetch(`${API}${p}`, { ...init, headers: { ...H, ...(init.headers || {}) } }); if (r.status === 204) return null; const t = await r.text(); try { return JSON.parse(t) } catch { throw new Error(`${init.method || 'GET'} ${p} -> ${r.status}`) } }

const flows = (await j('/vision/flows?limit=50')).items
const flow = flows.find((f) => f.node_count > 3) ?? flows[0]
const full = await j(`/vision/flows/${flow.id}`)
const node = full.graph.nodes.find((n) => n.type !== 'image_source' && n.type !== 'note' && n.type !== 'result') ?? full.graph.nodes[1]
console.log('flow', flow.id, flow.name, 'node', node.id, node.type)
for (const f of flows.filter((x) => /Demo|示範/.test(x.name)).slice(0, 3)) {
  for (let i = 0; i < 3; i++) { try { await j(`/vision/flows/${f.id}/run?wait=1`, { method: 'POST', body: '{}' }) } catch (e) { console.log('run failed', f.name, String(e).slice(0, 80)); break } }
}
const statsFlow = flows.find((x) => /Demo|示範/.test(x.name)) ?? flow

const OVERLAY = (rects) => {
  document.querySelectorAll('.doc-callout').forEach((e) => e.remove())
  for (const r of rects) {
    const box = document.createElement('div'); box.className = 'doc-callout'
    box.style.cssText = 'position:fixed;z-index:99999;pointer-events:none;border:2px solid #00ff88;border-radius:4px;box-shadow:0 0 0 2px rgba(0,0,0,.55),0 0 12px rgba(0,255,136,.55);left:' + (r.x - 3) + 'px;top:' + (r.y - 3) + 'px;width:' + (r.w + 6) + 'px;height:' + (r.h + 6) + 'px'
    const n = document.createElement('div'); n.className = 'doc-callout'; n.textContent = String(r.n)
    n.style.cssText = 'position:fixed;z-index:100000;pointer-events:none;width:26px;height:26px;border-radius:50%;background:#00ff88;color:#0a0a12;font:700 14px/26px ui-monospace,Consolas,monospace;text-align:center;box-shadow:0 0 0 2px #0a0a12,0 0 10px rgba(0,255,136,.8);left:' + (r.x - 14) + 'px;top:' + (r.y - 14) + 'px'
    document.body.appendChild(box); document.body.appendChild(n)
  }
}
const CLEAR = () => document.querySelectorAll('.doc-callout').forEach((e) => e.remove())

async function resolve(page, target) {
  const loc = typeof target === 'string' ? (target.startsWith('text=') ? page.getByText(target.slice(5), { exact: false }) : page.locator(target)) : target
  const first = loc.first()
  if (!(await first.count())) return null
  try { await first.scrollIntoViewIfNeeded({ timeout: 1500 }) } catch { /* 固定元素不用捲 */ }
  const b = await first.boundingBox()
  return b && b.width > 0 && b.height > 0 ? b : null
}

const missing = []
fs.writeFileSync(path.join(here, 'docs_shots_callouts.txt'), '')
async function capture(page, name, callouts) {
  const rects = []
  const resolved = []
  for (const c of callouts) {
    const label = c.label || (typeof c.target === 'string' ? c.target : '?')
    const b = await resolve(page, c.target)
    if (!b) { missing.push(`${name}: ${label}`); continue }
    const n = rects.length + 1  // 只給找得到的編號，圖上不會有跳號
    rects.push({ n, x: Math.max(0, b.x), y: Math.max(0, b.y), w: Math.min(b.width, 1440 - b.x), h: Math.min(b.height, 900 - b.y) })
    resolved.push(`${n}=${label}`)
  }
  fs.appendFileSync(path.join(here, 'docs_shots_callouts.txt'), `${name}: ${resolved.join(' | ')}
`)
  await page.evaluate(OVERLAY, rects)
  await page.waitForTimeout(150)
  await page.screenshot({ path: path.join(IMG, `${name}.jpg`), type: 'jpeg', quality: 82 })
  await page.evaluate(CLEAR)
  console.log('shot', name, rects.length + '/' + callouts.length)
}

const browser = await chromium.launch(process.env.PW_EXE ? { executablePath: process.env.PW_EXE } : {})
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
await ctx.addInitScript(({ t }) => { localStorage.setItem('vs.token', t); localStorage.setItem('vs.language', 'en'); localStorage.removeItem('vs.assistant.v1'); localStorage.setItem('vs.assistant.share', '1'); sessionStorage.clear() }, { t: token })
const page = await ctx.newPage()
const go = async (route, ready = 'main') => { await page.goto(`${FRONT}${route}`); await page.waitForSelector(ready, { timeout: 30000 }); await page.waitForTimeout(1400) }
const T = (s) => `text=${s}`
try {
  // 1 外框：側欄、麵包屑、容量、使用者選單、助手鈕、總覽的流程卡與執行一次
  await go('/', '[data-testid="dash-flow-list"]')
  await capture(page, 'shell', [
    { target: '[data-testid="sidebar"]' }, { target: '[data-testid="breadcrumb"]' }, { target: '[data-testid="capacity-menu"]' }, { target: '[data-testid="user-menu"]' },
    { target: '[data-testid="assistant-toggle"]' }, { target: '[data-testid="dash-flow-list"]' }, { target: '[data-testid="card-run"]' }, { target: '[data-testid="card-stats"]' },
  ])
  // 2 流程頁
  await go('/flows', 'table')
  await capture(page, 'flows', [
    { target: page.getByRole('button', { name: 'New flow' }), label: 'New flow' }, { target: '[data-testid="btn-from-template"]' }, { target: '[data-testid="btn-import"]' },
    { target: '[data-testid="row-teach"]' }, { target: '[data-testid="row-golden"]' }, { target: '[data-testid="row-export"]' }, { target: '[data-testid="row-recipes"]' },
  ])
  // 3 編輯器（先選一個節點讓右側顯示參數）
  await go(`/flows/${flow.id}`, '[data-testid="btn-preview"]')
  const nodeEl = page.locator(`.react-flow__node[data-id="${node.id}"]`)
  if (await nodeEl.count()) { await nodeEl.first().click({ position: { x: 10, y: 10 } }); await page.waitForTimeout(600) }
  await capture(page, 'editor', [
    { target: '[data-testid="toolbar-row-1"]' }, { target: '[data-testid="toolbar-row-2"]' }, { target: '[data-testid="btn-add-tool"]' }, { target: '.react-flow' },
    { target: '[data-testid="viewer-main"]' }, { target: '[data-testid="inspector"]' }, { target: '[data-testid="open-tool-page"]' }, { target: '[data-testid="btn-preview"]' },
    { target: '[data-testid="btn-teach"]' }, { target: '[data-testid="btn-stats"]' },
  ])
  // 4 工具選擇視窗
  await page.click('[data-testid="btn-add-tool"]')
  await page.waitForSelector('[data-testid="tool-picker"]')
  await page.waitForTimeout(500)
  const firstTool = page.locator('[data-testid^="picker-tool-"]').first()
  if (await firstTool.count()) { await firstTool.click(); await page.waitForTimeout(400) }
  await capture(page, 'tool-picker', [
    { target: '[data-testid="picker-search"]' }, { target: '[data-testid^="picker-cat-"]' }, { target: '[data-testid="picker-list"]' }, { target: '[data-testid="picker-detail"]' }, { target: '[data-testid="picker-insert"]' },
  ])
  await page.keyboard.press('Escape')
  // 5 工具頁
  await go(`/flows/${flow.id}/tools/${node.id}`, '[data-testid="tool-page"]')
  await capture(page, 'tool', [
    { target: '[data-testid="tool-params"]' }, { target: '[data-testid="tool-before"]' }, { target: '[data-testid="tool-after"]' }, { target: '[data-testid="tool-reference"]' },
    { target: '[data-testid="tool-preview"]' }, { target: '[data-testid="tool-save"]' }, { target: '[data-testid="tool-scratch"]' }, { target: '[data-testid="btn-back"]' },
  ])
  // 6 參數卡
  await go(`/flows/${flow.id}/teach`, '[data-testid="teach-page"]')
  await capture(page, 'teach', [
    { target: '[data-testid="teach-steps"]' }, { target: '[data-testid="teach-params"]' }, { target: '[data-testid="teach-viewer"]' }, { target: '[data-testid="teach-recipe-row"]' },
    { target: '[data-testid="teach-save"]' }, { target: '[data-testid="teach-mark"]' }, { target: '[data-testid="teach-outputs"]' },
  ])
  // 7 統計
  await go(`/flows/${statsFlow.id}/stats`, '[data-testid="stats-kpi"]')
  try { await page.waitForSelector('[data-testid^="history-row-"]', { timeout: 5000 }) } catch { /* 沒有紀錄也照拍 */ }
  await capture(page, 'stats', [
    { target: '[data-testid="stats-kpi"]' }, { target: '[data-testid="stats-status-filter"]' }, { target: '[data-testid^="history-row-"]' }, { target: T('Keep reject images'), label: 'archive toggle' },
  ])
  // 8 Golden Set
  await go(`/flows/${flow.id}/golden`, 'main')
  await capture(page, 'golden', [
    { target: '[data-testid="golden-upload"]' }, { target: '[data-testid="golden-regress"]' }, { target: '[data-testid="golden-autotune"]' }, { target: '[data-testid="golden-baseline"]' },
    { target: '[data-testid="golden-kpi"]' }, { target: '[data-testid="golden-case-expect"]' },
  ])
  // 9 批次測試
  await go(`/batch?flow=${flow.id}`, '[data-testid="batch-flow"]')
  await capture(page, 'batch', [
    { target: '[data-testid="batch-flow"]' }, { target: page.getByRole('button', { name: 'New image set' }), label: 'New image set' }, { target: '[data-testid="batch-run-start"]' },
    { target: page.getByRole('tab', { name: 'Results' }), label: 'Results tab' }, { target: page.getByRole('tab', { name: 'Insights' }), label: 'Insights tab' },
    { target: page.getByRole('tab', { name: 'Tune' }), label: 'Tune tab' }, { target: '[data-testid="assistant-toggle"]' },
  ])
  // 10 影像來源（清單＋新增表單的測試擷取）
  await go('/sources', 'main')
  await capture(page, 'sources', [
    { target: page.getByRole('button', { name: 'New source' }), label: 'New source' }, { target: T('Download capture client'), label: 'download' }, { target: '[data-testid="manage-groups"]' }, { target: 'main table' },
  ])
  await page.getByRole('button', { name: 'New source' }).first().click()
  await page.waitForTimeout(700)
  await capture(page, 'source-form', [
    { target: '[role="dialog"] select, [role="dialog"] [data-testid="source-kind"]', label: 'kind' }, { target: '[data-testid="cfg-browse"]' }, { target: '[data-testid="source-test"]' }, { target: '[data-testid="source-test-box"]' },
  ])
  await page.keyboard.press('Escape')
  // 7-1 現場看板：示範流程設兩個數值＋公差、變數，跑過之後開全螢幕看板
  {
    const bflow = statsFlow
    const bfull = await j(`/vision/flows/${bflow.id}`)
    const names = bfull.graph.nodes.filter((n) => n.type === 'output').map((n) => n.params?.name).filter(Boolean)
    await j(`/vision/flows/${bflow.id}`, { method: 'PATCH', body: JSON.stringify({ board: { values: names.slice(0, 3).map((k) => ({ key: k, unit: 'px', decimals: 1, low: 0 })), show_counts: true } }) })
    await j(`/vision/flows/${bflow.id}/variables`, { method: 'PUT', body: JSON.stringify({ values: { lot: 'A17', parts: 128 } }) })
    await j(`/vision/flows/${bflow.id}/run?wait=1`, { method: 'POST', body: '{}' })
    await page.goto(`${FRONT}/board/${bflow.id}`)
    await page.waitForSelector('[data-testid="board-page"]', { timeout: 20000 })
    await page.waitForTimeout(1500)
    await capture(page, 'board', [
      { target: '[data-testid="board-title"]' }, { target: '[data-testid="board-verdict"]' }, { target: '[data-testid="board-values"]' },
      { target: '[data-testid="board-counts"]' }, { target: '[data-testid="board-variables"]' }, { target: '[data-testid="board-exit"]' },
    ])
  }
  // 10-2 標定
  await go('/calibration', 'main')
  await capture(page, 'calibration', [
    { target: '[data-testid="calib-mode-board"]' }, { target: '[data-testid="calib-source"]' }, { target: '[data-testid="calib-capture"]' },
    { target: '[data-testid="calib-cols"]' }, { target: '[data-testid="calib-unit"]' }, { target: '[data-testid="calib-solve"]' }, { target: '[data-testid="calib-save"]' },
  ])
  // 11 資產
  await go('/assets', 'main')
  await capture(page, 'assets', [{ target: page.getByRole('button', { name: 'Upload asset' }), label: 'Upload asset' }, { target: '[data-testid="manage-groups"]' }, { target: 'main .grid', label: 'asset cards' }])
  // 12 深度學習
  await go('/dl', 'main')
  await capture(page, 'dl', [
    { target: '[data-testid="dl-new"]' }, { target: '[data-testid="dl-grid"]' }, { target: '[data-testid="dl-auto"]' }, { target: '[data-testid="dl-split-stats"]' }, { target: '[data-testid="dl-freeze"]' }, { target: '[data-testid="dl-train"]' }, { target: '[data-testid="dl-create-flow"]' },
  ])
  // 13 AI 助手頁
  await go('/agent', '[data-testid="agent-upload"]')
  await capture(page, 'agent', [
    { target: '[data-testid="agent-upload"]' }, { target: '[data-testid="agent-images"]' }, { target: '[data-testid="agent-add-roi"]' }, { target: '[data-testid="agent-prompt"]' },
    { target: '[data-testid="agent-generate"]' }, { target: '[data-testid="agent-settings"]' }, { target: '[data-testid="agent-history"]' }, { target: '[data-testid="agent-skills"]' },
  ])
  // 14 全域助手視窗
  await go('/sources', 'main')
  await page.click('[data-testid="assistant-toggle"]')
  await page.waitForSelector('[data-testid="assistant-dock"]')
  await page.waitForTimeout(500)
  await capture(page, 'assistant', [
    { target: '[data-testid="assistant-toggle"]' }, { target: '[data-testid="assistant-mode-auto"]' }, { target: '[data-testid="assistant-memory-toggle"]' }, { target: '[data-testid="assistant-shot"]' },
    { target: '[data-testid="assistant-screen"]' }, { target: '[data-testid="assistant-share"]' }, { target: '[data-testid="assistant-quick"]' }, { target: '[data-testid="assistant-input"]' },
  ])
  await page.click('[data-testid="assistant-toggle"]')
  // 15 整合：HTTP
  await go('/integration/http', '[data-testid="integration-info"]')
  await capture(page, 'integration-http', [
    { target: '[data-testid^="nav-integration-"]' }, { target: '[data-testid="integration-info"]' }, { target: '[data-testid^="section-tab-"]' }, { target: '[data-testid="api-search"]' }, { target: '[data-testid^="op-"]' },
  ])
  // 16 整合：Modbus 從站
  await go('/integration/modbus-server', '[data-testid="integration-info"]')
  await capture(page, 'integration-modbus', [
    { target: page.getByRole('tab', { name: 'Connections' }), label: 'Connections tab' }, { target: page.getByRole('tab', { name: 'Address format and mapping' }), label: 'guide tab' }, { target: page.getByRole('tab', { name: 'Commands and results' }), label: 'trace tab' }, { target: '[data-testid="conn-create"]' }, { target: 'main table' },
  ])
  // 17 整合：擷取端與外掛
  await go('/integration/capture', '[data-testid="integration-info"]')
  await capture(page, 'integration-capture', [{ target: T('Download capture client'), label: 'download' }, { target: 'main table' }])
  await go('/integration/devices', '[data-testid="integration-info"]')
  await capture(page, 'integration-devices', [{ target: '[data-testid="conn-create"]' }, { target: 'main table' }, { target: '[data-testid="conn-export"]' }])
  await go('/integration/plugins', '[data-testid="integration-info"]')
  await capture(page, 'integration-plugins', [{ target: page.getByRole('button', { name: 'Rescan' }), label: 'Rescan' }, { target: 'main table' }, { target: page.getByRole('tab', { name: 'Connections' }), label: 'Connections tab' }])
  // 18 使用者、操作紀錄、設定、說明
  await go('/users', 'main')
  await capture(page, 'users', [{ target: page.getByRole('button', { name: 'New user' }), label: 'New user' }, { target: 'main table' }, { target: T('Role permissions'), label: 'Role permissions' }])
  await go('/audit', 'main')
  try { await page.waitForSelector('[data-testid^="audit-row-"]', { timeout: 5000 }) } catch { /* 沒有紀錄也照拍 */ }
  await capture(page, 'audit', [{ target: '[data-testid="audit-action"]' }, { target: '[data-testid="audit-search"]' }, { target: '[data-testid="audit-export"]' }, { target: '[data-testid^="audit-row-"]' }])
  await go('/settings', 'main')
  await capture(page, 'settings', [{ target: '[data-testid="profile-display-name"]' }, { target: T('Change password'), label: 'password' }, { target: T('Language'), label: 'language' }, { target: '[data-testid="theme-picker"]' }])
  await go('/help', 'main')
  await capture(page, 'help', [{ target: page.getByRole('tab', { name: 'Quick start' }), label: 'Quick start tab' }, { target: page.getByRole('tab', { name: 'Glossary' }), label: 'Glossary tab' }, { target: page.getByRole('tab', { name: 'Tool catalogue' }), label: 'Tool catalogue tab' }, { target: '[data-testid="help-quickstart"]' }])
  // 19 鎖定橫幅（另一個管理員鎖住）
  if (token2) {
    const H2 = { Authorization: `Bearer ${token2}`, 'Content-Type': 'application/json' }
    await j('/vision/lock', { method: 'POST', body: JSON.stringify({ reason: 'maintenance window' }), headers: H2 })
    try {
      await go('/', '[data-testid="lock-banner"]')
      await capture(page, 'lock-banner', [{ target: '[data-testid="lock-banner"]' }, { target: '[data-testid="card-run"]' }])
    } finally {
      await j('/vision/lock', { method: 'DELETE', headers: H2 })
    }
  }
} finally {
  await browser.close()
}
console.log('missing:', JSON.stringify(missing, null, 1))
const sizes = fs.readdirSync(IMG).filter((f) => f.endsWith('.jpg')).map((f) => `${f} ${Math.round(fs.statSync(path.join(IMG, f)).size / 1024)}KB`)
console.log(sizes.join('\n'))
