/**
 * Playwright 功能測試（手動執行，不進 CI）：範本庫、批次測試、統計頁、整合頁、收藏工具。
 *   node frontend/e2e/features.mjs
 * 需要：後端 :8000（manage.py serve，含 TCP）、前端 :5173；Playwright 取自 ZQS-Cloud 的 node_modules。
 * 截圖寫到 <repo>/Image/60-*.png。
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const BASE = 'http://127.0.0.1:5173'
// 截圖輸出到專案根目錄的 Image/（.gitignore 已忽略），依本檔位置推算、不寫死
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../Image')
fs.mkdirSync(OUT, { recursive: true })

const issues = []
const shots = []
async function shot(page, name) {
  const p = path.join(OUT, `${name}.png`)
  await page.screenshot({ path: p })
  shots.push(p)
  console.log('shot', name)
}
function note(msg) {
  issues.push(msg)
  console.log('ISSUE', msg)
}
async function step(name, fn) {
  console.log('--- step', name)
  try {
    await fn()
  } catch (e) {
    note(`[${name}] ${e.message.split('\n')[0]}`)
  }
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, locale: 'zh-TW' })
const page = await context.newPage()
page.on('console', (m) => {
  if (m.type() === 'error' || m.type() === 'warning') {
    const text = m.text()
    if (text.includes('React DevTools')) return
    console.log(`console.${m.type()}:`, text.slice(0, 300))
    if (m.type() === 'error') issues.push(`console.error: ${text.slice(0, 200)}`)
  }
})
page.on('pageerror', (e) => note(`pageerror: ${e.message.slice(0, 300)}`))
page.on('response', (r) => {
  if (r.status() >= 500) note(`HTTP ${r.status()} ${r.url()}`)
})
page.on('dialog', (d) => d.accept())

const CRED = { username: process.env.VS_USER || 'admin', password: process.env.VS_PASS || 'admin123' }
const status = await (await context.request.get(`${BASE}/api/auth/status`)).json()
const loginRes = await context.request.post(`${BASE}/api/auth/${status.setup_required ? 'setup' : 'login'}`, { data: CRED })
const loginBody = await loginRes.json()
if (!loginBody.token) throw new Error('login failed: ' + JSON.stringify(loginBody))
const AUTH = { Authorization: `Bearer ${loginBody.token}` }
await context.addInitScript((tk) => localStorage.setItem('vs.token', tk), loginBody.token)
await context.request.delete(`${BASE}/api/vision/lock`, { headers: AUTH })
const api = async (p) => (await context.request.get(`${BASE}/api/vision${p}`, { headers: AUTH })).json()

const sources = await api('/sources')
const synth = sources.items.find((s) => s.kind === 'synthetic') ?? sources.items[0]
const TEMPLATE_FLOW_NAME = `E2E 範本流程 ${Date.now().toString().slice(-5)}`
let flowId = null

// 1. 範本建立流程
await step('template-create-flow', async () => {
  await page.goto(`${BASE}/flows`)
  await page.waitForLoadState('networkidle')
  await page.getByTestId('btn-from-template').click()
  await page.getByTestId('template-card').first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(400)
  await shot(page, '60-01-template-gallery')
  const cards = await page.getByTestId('template-card').count()
  console.log('template cards', cards)
  if (cards < 5) note(`only ${cards} template cards`)
  await page.locator('[data-template-id="builtin:hole_count"]').click()
  if (synth) await page.getByTestId('template-source').selectOption(String(synth.id))
  await page.getByTestId('template-flow-name').fill(TEMPLATE_FLOW_NAME)
  await page.getByTestId('template-confirm').click()
  await page.waitForURL(/\/flows\/\d+$/, { timeout: 10000 })
  flowId = Number(page.url().split('/').pop())
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(800)
  const n = await page.locator('.react-flow__node').count()
  console.log('flow', flowId, 'nodes', n)
  if (n < 5) note(`template flow has only ${n} nodes`)
  await shot(page, '60-02-flow-from-template')
})

// 1b. 存為範本 + 載入範本
await step('template-save-load', async () => {
  await page.getByTestId('btn-templates').click()
  await page.getByTestId('menu-save-template').click()
  await page.getByTestId('save-template-name').fill(`E2E 自訂範本 ${Date.now().toString().slice(-5)}`)
  await page.getByTestId('save-template-confirm').click()
  await page.waitForTimeout(800)
  const tpl = await api('/templates')
  const custom = tpl.items.filter((t) => t.source === 'custom')
  console.log('custom templates', custom.length)
  if (!custom.length) note('custom template not saved')
  await page.getByTestId('btn-templates').click()
  await page.getByTestId('menu-load-template').click()
  await page.getByTestId('template-card').first().waitFor()
  await page.locator('[data-template-id="builtin:exposure"]').click()
  await page.getByTestId('template-confirm').click()
  await page.waitForTimeout(800)
  await shot(page, '60-03-template-loaded')
  const ids = await page.locator('.react-flow__node').evaluateAll((els) => els.map((e) => e.getAttribute('data-id')))
  console.log('node ids after load', ids.join(','))
  if (!ids.some((id) => id.startsWith('t1_'))) note('loaded template nodes lack t1_ prefix')
  // 清掉自訂範本
  for (const c of custom) await context.request.delete(`${BASE}/api/vision/templates/${c.id}`, { headers: AUTH })
  // 回到範本流程（放棄變更）
  await page.goto(`${BASE}/flows/${flowId}`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
})

// 2. 批次測試（canvas 產 5 張 png）
await step('batch-test', async () => {
  const pngs = await page.evaluate(async () => {
    const out = []
    for (let i = 0; i < 5; i += 1) {
      const c = document.createElement('canvas')
      c.width = 320
      c.height = 240
      const ctx = c.getContext('2d')
      ctx.fillStyle = '#d0d0d0'
      ctx.fillRect(0, 0, 320, 240)
      ctx.fillStyle = '#202020'
      for (let k = 0; k < i + 2; k += 1) {
        ctx.beginPath()
        ctx.arc(50 + k * 50, 120, 14, 0, Math.PI * 2)
        ctx.fill()
      }
      out.push(c.toDataURL('image/png').split(',')[1])
    }
    return out
  })
  await page.getByTestId('btn-batch').click()
  await page.getByTestId('batch-input').setInputFiles(pngs.map((b, i) => ({ name: `part-${i + 1}.png`, mimeType: 'image/png', buffer: Buffer.from(b, 'base64') })))
  await page.waitForTimeout(300)
  await page.getByTestId('batch-run').click()
  await page.getByTestId('batch-summary').waitFor({ timeout: 30000 })
  await page.waitForTimeout(800)
  await shot(page, '60-04-batch-result')
  const rows = await page.getByTestId('batch-row').count()
  console.log('batch rows', rows)
  if (rows !== 5) note(`batch rows ${rows} != 5`)
  const summary = await page.getByTestId('batch-summary').innerText()
  console.log('summary', summary.replace(/\n/g, ' | '))
  // 只看 NG
  await page.getByRole('button', { name: '只看 NG' }).click()
  await page.waitForTimeout(200)
  await page.getByRole('button', { name: '全部' }).click()
  // 點一列 → 影像視窗
  await page.getByTestId('batch-row').first().click()
  await page.waitForTimeout(600)
  // 關閉 modal 看影像視窗
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)
  await shot(page, '60-05-batch-view-run')
  const badge = await page.locator('[data-testid=viewer-main]').innerText()
  console.log('viewer badge', badge.slice(0, 80).replace(/\n/g, ' | '))
})

// 3. 統計頁（先跑幾次寫進 DB）
await step('stats-page', async () => {
  for (let i = 0; i < 3; i += 1) await context.request.post(`${BASE}/api/vision/flows/${flowId}/run?wait=1`, { headers: AUTH, data: { context: null, wait: true } })
  await page.getByTestId('btn-stats').click()
  await page.waitForURL(/\/stats$/, { timeout: 10000 })
  await page.getByTestId('stats-kpi').waitFor({ timeout: 10000 })
  await page.waitForTimeout(1200)
  await shot(page, '60-06-stats')
  const kpi = await page.getByTestId('stats-kpi').innerText()
  console.log('kpi', kpi.replace(/\n/g, ' | '))
  if (!/[1-9]/.test(kpi)) note('stats KPI all zero')
  await page.getByRole('button', { name: '7 天' }).click()
  await page.waitForTimeout(600)
  await page.getByTestId('stats-status-filter').selectOption('ok')
  await page.waitForTimeout(600)
  await shot(page, '60-07-stats-filtered')
})

// 4. 整合頁四個分頁
await step('integration-http', async () => {
  await page.goto(`${BASE}/integration`)
  await page.getByTestId('integration-info').waitFor({ timeout: 10000 })
  await page.getByTestId('http-flow').selectOption(String(flowId))
  await page.getByTestId('http-send').click()
  await page.getByTestId('http-result').waitFor({ timeout: 30000 })
  await page.waitForTimeout(500)
  await shot(page, '60-08-integration-http')
  const txt = await page.getByTestId('http-result').innerText()
  console.log('http result', txt.slice(0, 120).replace(/\n/g, ' | '))
  if (!/200/.test(txt)) note('http test did not return 200: ' + txt.slice(0, 80))
  await page.getByRole('tab', { name: 'Python' }).click()
  await page.waitForTimeout(200)
})
await step('integration-tcp', async () => {
  await page.getByRole('tab', { name: 'TCP 測試' }).click()
  await page.getByTestId('tcp-command').fill('PING')
  await page.getByTestId('tcp-send').click()
  await page.getByTestId('tcp-result').waitFor({ timeout: 15000 })
  let txt = await page.getByTestId('tcp-result').innerText()
  console.log('tcp PING', txt.slice(0, 160).replace(/\n/g, ' | '))
  if (!/路徑：tcp/.test(txt)) note('TCP PING did not go through real socket: ' + txt.slice(0, 100))
  await page.getByTestId('tcp-command').fill(`RUN ${flowId}`)
  await page.getByTestId('tcp-send').click()
  await page.waitForTimeout(3000)
  txt = await page.getByTestId('tcp-result').innerText()
  console.log('tcp RUN', txt.slice(0, 200).replace(/\n/g, ' | '))
  if (!/"status"/.test(txt)) note('TCP RUN response lacks status: ' + txt.slice(0, 100))
  await shot(page, '60-09-integration-tcp')
  const hist = await page.getByTestId('tcp-history').locator('li').count()
  if (hist < 2) note(`tcp history has ${hist} entries`)
})
await step('integration-events', async () => {
  await page.getByRole('tab', { name: '事件監看' }).click()
  await page.getByTestId('events-table').waitFor()
  await page.waitForTimeout(800)
  await context.request.post(`${BASE}/api/vision/flows/${flowId}/run?wait=1`, { headers: AUTH, data: { context: null, wait: true } })
  await page.waitForTimeout(1500)
  const rows = await page.getByTestId('event-row').count()
  console.log('event rows', rows)
  if (rows < 1) note('event monitor saw no events')
  await shot(page, '60-10-integration-events')
  await page.getByTestId('events-pause').click()
})
await step('integration-lock-format', async () => {
  await page.getByRole('tab', { name: '鎖定' }).click()
  await page.waitForTimeout(300)
  await shot(page, '60-11-integration-lock')
  await page.getByRole('tab', { name: '回傳格式' }).click()
  await page.waitForTimeout(300)
  await shot(page, '60-12-integration-format')
})

// 5. 收藏工具 + 右鍵選單
await step('favorites-and-menu', async () => {
  await page.goto(`${BASE}/flows/${flowId}`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(500)
  const tool = page.locator('[data-tool-key="blob"]').last()
  await tool.hover()
  await tool.getByTestId('palette-star').click()
  await page.waitForTimeout(300)
  const favCount = await page.getByTestId('palette-favorites').locator('[data-testid=palette-tool]').count()
  console.log('favorites', favCount)
  if (favCount !== 1) note(`favorites count ${favCount}`)
  const stored = await page.evaluate(() => localStorage.getItem('vs.favoriteTools'))
  if (!stored?.includes('blob')) note('favorite not stored: ' + stored)
  // 插入一個工具 → 最近使用
  await page.getByTestId('palette-favorites').locator('[data-testid=palette-tool] button').first().click()
  await page.waitForTimeout(300)
  const recent = await page.getByTestId('palette-recent').count()
  if (!recent) note('recent section missing after insert')
  // 右鍵選單
  const node = page.locator('.react-flow__node').first()
  await node.click({ button: 'right' })
  await page.getByTestId('node-menu').waitFor({ timeout: 3000 })
  await shot(page, '60-13-favorites-context-menu')
  await page.getByRole('menuitem', { name: '複製參數' }).click()
  await page.waitForTimeout(200)
  await page.keyboard.press('Escape')
  // 說明下拉
  await page.getByTestId('menu-help').locator('button').click()
  await page.waitForTimeout(200)
  await shot(page, '60-14-help-menu')
  await page.keyboard.press('Escape')
})

// 清理：刪除 e2e 建立的流程
await step('cleanup', async () => {
  await page.goto(`${BASE}/flows`)
  await page.waitForLoadState('networkidle')
  if (flowId) await context.request.delete(`${BASE}/api/vision/flows/${flowId}`, { headers: AUTH })
})

await browser.close()
console.log('\n==== ISSUES (' + issues.length + ')')
for (const i of issues) console.log('-', i)
console.log('==== SHOTS')
for (const s of shots) console.log(s)
