/**
 * Playwright 整合冒煙測試（手動執行，不進 CI）。
 *   node frontend/e2e/smoke.mjs
 * 需要：後端 :8000、前端 :5173 已啟動；Playwright 取自 ZQS-Cloud 的 node_modules。
 * 需要登入：以 API 取 token 寫進 localStorage（見下方 CRED）。
 * 截圖寫到 <repo>/Image/。
 */
import { chromium } from 'file:///D:/Working%20Space/Python/ZQS-Cloud/frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import path from 'node:path'

const BASE = 'http://127.0.0.1:5173'
const OUT = 'D:/Working Space/Python/VisionSequence/Image'
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

// 登入：直接呼叫 API 取 token，寫進 localStorage（vs.token）；後續 request 也帶 Bearer。
// 帳號預設 admin/admin123（setup_required 時自動建立；否則先跑 manage.py create_admin admin --password admin123）。
const CRED = { username: process.env.VS_USER || 'admin', password: process.env.VS_PASS || 'admin123' }
const status = await (await context.request.get(`${BASE}/api/auth/status`)).json()
const loginRes = await context.request.post(`${BASE}/api/auth/${status.setup_required ? 'setup' : 'login'}`, { data: CRED })
const loginBody = await loginRes.json()
if (!loginBody.token) throw new Error('login failed: ' + JSON.stringify(loginBody))
const AUTH = { Authorization: `Bearer ${loginBody.token}` }
await context.addInitScript((tk) => localStorage.setItem('vs.token', tk), loginBody.token)
// 之前留下的引擎鎖先解掉，冒煙測試才能執行
await context.request.delete(`${BASE}/api/vision/lock`, { headers: AUTH })

const api = async (p) => (await context.request.get(`${BASE}/api/vision${p}`, { headers: AUTH })).json()

// a. 各頁
await step('dashboard', async () => {
  await page.goto(`${BASE}/`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(800)
  await shot(page, '01-dashboard')
})
await step('flows', async () => {
  await page.goto(`${BASE}/flows`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(500)
  await shot(page, '02-flows')
})
await step('sources', async () => {
  await page.goto(`${BASE}/sources`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(500)
  const btn = page.getByRole('button', { name: '預覽' }).first()
  await btn.click()
  await page.waitForTimeout(1500)
  await shot(page, '03-sources-preview')
  const img = page.locator('[role=dialog] img').first()
  if ((await img.count()) === 0) note('sources preview: no <img> in modal')
  else {
    const ok = await img.evaluate((el) => el.complete && el.naturalWidth > 0)
    if (!ok) note('sources preview: image not loaded')
  }
  await page.keyboard.press('Escape')
})
await step('assets', async () => {
  await page.goto(`${BASE}/assets`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(500)
  await shot(page, '04-assets')
})
await step('settings', async () => {
  await page.goto(`${BASE}/settings`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(500)
  await shot(page, '05-settings')
})

// b. 編輯器
const flows = await api('/flows')
const flow = flows.items.find((f) => f.name.includes('孔數'))
if (!flow) throw new Error('demo flow not found')
const canvasImg = () => page.locator('canvas.absolute').first()
const viewerHasImage = async () => {
  // 影像層 canvas 中央是否有非背景像素（粗略：看 badge 與 src）
  return page.evaluate(() => {
    const c = document.querySelectorAll('canvas')
    if (!c.length) return false
    const ctx = c[0].getContext('2d')
    const d = ctx.getImageData(0, 0, c[0].width, c[0].height).data
    let non = 0
    for (let i = 0; i < d.length; i += 4 * 97) if (d[i + 3] > 0) non++
    return non > 50
  })
}

await step('editor-open', async () => {
  await page.goto(`${BASE}/flows/${flow.id}`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(800)
  const n = await page.locator('.react-flow__node').count()
  console.log('nodes on canvas', n)
  if (n !== flow.graph.nodes.length) note(`canvas nodes ${n} != graph ${flow.graph.nodes.length}`)
  await shot(page, '10-editor')
})

await step('editor-preview', async () => {
  await page.getByRole('button', { name: '試跑' }).click()
  await page.waitForTimeout(3000)
  await shot(page, '11-editor-preview')
  if (!(await viewerHasImage())) note('viewer shows no image after preview')
  const badge = await page.locator('text=/^(OK|NG|失敗|ok|ng)/').count()
  console.log('badge count', badge)
})

await step('editor-select-blob', async () => {
  await page.locator('.react-flow__node[data-id="blob"]').click()
  await page.waitForTimeout(600)
  await shot(page, '12-blob-inspector')
  const txt = await page.locator('aside').last().innerText()
  if (!/面積|area|min/i.test(txt)) note('inspector shows no blob params: ' + txt.slice(0, 120))
  await page.getByRole('tab', { name: /結果/ }).click().catch(async () => page.getByRole('button', { name: /結果/ }).first().click())
  await page.waitForTimeout(500)
  await shot(page, '13-blob-results')
})

await step('editor-preview-reuse', async () => {
  const cb = page.locator('header input[type=checkbox]')
  if (await cb.isDisabled()) note('reuse image checkbox disabled after preview')
  else await cb.check()
  await page.getByRole('button', { name: '試跑' }).click()
  await page.waitForTimeout(2500)
  await shot(page, '14-editor-preview-reuse')
})

// c. 插入裁切 ROI、畫 ROI
await step('insert-crop', async () => {
  await page.getByRole('tab', { name: /檢視/ }).click().catch(async () => page.getByRole('button', { name: /^檢視$/ }).first().click())
  await page.locator('aside').first().getByRole('button', { name: '裁切 ROI' }).click()
  await page.waitForTimeout(500)
  const n = await page.locator('.react-flow__node').count()
  if (n !== flow.graph.nodes.length + 1) note(`after insert nodes=${n}`)
  const edit = page.getByRole('button', { name: '在影像上編輯' })
  if (await edit.isDisabled()) note('edit ROI button disabled (no image?)')
  await edit.click()
  await page.waitForTimeout(300)
  const c = page.locator('canvas.touch-none').first()
  const box = await c.boundingBox()
  const x0 = box.x + box.width * 0.35, y0 = box.y + box.height * 0.3
  await page.mouse.move(x0, y0)
  await page.mouse.down()
  await page.mouse.move(x0 + 60, y0 + 40, { steps: 5 })
  await page.mouse.move(x0 + 160, y0 + 120, { steps: 10 })
  await page.mouse.up()
  await page.waitForTimeout(400)
  await shot(page, '15-crop-roi-drawn')
  const txt = await page.locator('aside').last().innerText()
  console.log('inspector roi text:', txt.slice(0, 200).replace(/\n/g, ' | '))
  if (!/rect|x\s*[:=]?\s*\d/i.test(txt)) note('params.roi seems empty after drawing: ' + txt.slice(0, 100))
  await page.locator('aside').last().getByRole('button', { name: '完成' }).click()
  await page.waitForTimeout(200)
})

await step('undo-delete', async () => {
  await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('Control+z')
  await page.waitForTimeout(300)
  const crop = page.locator('.react-flow__node[data-id^="crop"]')
  console.log('crop nodes after undo', await crop.count())
  if ((await crop.count()) > 0) {
    await crop.first().click()
    await page.keyboard.press('Delete')
    await page.waitForTimeout(300)
  }
  // 再插一個並刪除
  await page.locator('aside').first().getByRole('button', { name: '裁切 ROI' }).click()
  await page.waitForTimeout(300)
  await page.keyboard.press('Delete')
  await page.waitForTimeout(300)
  const n = await page.locator('.react-flow__node').count()
  if (n !== flow.graph.nodes.length) note(`after undo/delete nodes=${n}, expected ${flow.graph.nodes.length}`)
  await shot(page, '16-after-undo-delete')
})

// d. 儲存、重新整理、執行、連續
await step('save-reload', async () => {
  // 移動一個節點讓圖 dirty，再存
  const node = page.locator('.react-flow__node[data-id="n1"]')
  const b = await node.boundingBox()
  await page.mouse.move(b.x + 20, b.y + 10)
  await page.mouse.down()
  await page.mouse.move(b.x + 80, b.y + 60, { steps: 6 })
  await page.mouse.up()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: /^儲存$/ }).click()
  await page.waitForTimeout(1200)
  const before = (await api(`/flows/${flow.id}`))
  console.log('saved version', before.version, 'n1 pos', JSON.stringify(before.graph.nodes.find((n) => n.id === 'n1')?.position))
  if (before.version === flow.version) note('save did not bump version')
  await page.reload()
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(800)
  const n = await page.locator('.react-flow__node').count()
  if (n !== flow.graph.nodes.length) note(`after reload nodes=${n}`)
  await shot(page, '17-after-reload')
})

await step('run-once', async () => {
  const s0 = (await api(`/flows/${flow.id}`)).stats
  await page.getByRole('button', { name: '執行一次' }).click()
  await page.waitForTimeout(3000)
  const s1 = (await api(`/flows/${flow.id}`)).stats
  console.log('stats', JSON.stringify(s0), '->', JSON.stringify(s1))
  if (JSON.stringify(s0) === JSON.stringify(s1)) note('stats unchanged after run once')
  await shot(page, '18-run-once')
})

await step('continuous', async () => {
  await page.getByRole('button', { name: /^連續執行$/ }).click()
  await page.waitForTimeout(3000)
  await shot(page, '19-continuous-on')
  const hdr = await page.locator('header').innerText()
  console.log('header:', hdr.replace(/\n/g, ' | '))
  await page.getByRole('button', { name: /連續執行中/ }).click()
  await page.waitForTimeout(1000)
  const s = (await api(`/flows/${flow.id}`))
  console.log('after continuous stats', JSON.stringify(s.stats), 'continuous', s.continuous)
  if (s.continuous) note('continuous still running after stop')
  await shot(page, '20-continuous-off')
  await page.goto(`${BASE}/`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(800)
  const txt = await page.locator('main').innerText().catch(() => page.innerText('body'))
  console.log('dashboard text sample:', txt.slice(0, 300).replace(/\n/g, ' | '))
  await shot(page, '21-dashboard-after')
})

// e. 主題
await step('theme', async () => {
  await page.goto(`${BASE}/flows/${flow.id}`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.getByRole('button', { name: '試跑' }).click()
  await page.waitForTimeout(2500)
  await page.getByRole('button', { name: '切換深／淺色' }).click()
  await page.waitForTimeout(600)
  await shot(page, '22-theme-toggled')
  await page.getByRole('button', { name: '切換深／淺色' }).click()
  await page.waitForTimeout(600)
  await shot(page, '23-theme-back')
})

await browser.close()
console.log('\n==== ISSUES (' + issues.length + ')')
for (const i of issues) console.log('-', i)
console.log('==== SHOTS')
for (const s of shots) console.log(s)
