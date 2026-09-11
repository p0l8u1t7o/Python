/**
 * Playwright UX 走查（手動執行，不進 CI）：
 *   node frontend/e2e/ux.mjs
 * 需要：後端 :8000、前端 :5173 已啟動；Playwright 取自 ZQS-Cloud 的 node_modules。
 * 流程：開示範流程 → 步驟清單聚焦 → 框選兩個步驟 → 上傳暫存影像 → 試跑 → 前／後分割 → blob 工具頁
 *      → 改 min_area 看自動更新與直方圖 → 返回編輯器確認參數保留 → 製造錯誤（image_source mode=input 且清除暫存）
 *      → 重置 → 說明頁各分頁。截圖到 <repo>/Image/50-*.png；console error / pageerror 收集在最後列出。
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
const context = await browser.newContext({ viewport: { width: 1700, height: 1000 }, locale: 'zh-TW' })
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
const flows = await api('/flows')
const flow = flows.items.find((f) => f.name.includes('孔數'))
if (!flow) throw new Error('demo flow not found')
const originalGraph = JSON.parse(JSON.stringify(flow.graph))
const blobNode = flow.graph.nodes.find((n) => n.id === 'blob')
const originalMinArea = blobNode?.params?.min_area
console.log('flow', flow.id, 'blob.min_area', originalMinArea)

const viewerHasImage = (sel) =>
  page.evaluate((s) => {
    const root = s ? document.querySelector(s) : document
    const c = root?.querySelector('canvas')
    if (!c) return false
    const ctx = c.getContext('2d')
    const d = ctx.getImageData(0, 0, c.width, c.height).data
    let non = 0
    for (let i = 0; i < d.length; i += 4 * 97) if (d[i + 3] > 0) non++
    return non > 50
  }, sel)

// 1. 編輯器
await step('editor-open', async () => {
  await page.goto(`${BASE}/flows/${flow.id}`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(800)
  await shot(page, '50-01-editor')
  const nav = await page.locator('nav').innerText()
  if (!nav.includes('影像來源庫') || !nav.includes('資產庫') || !nav.includes('說明')) note('nav labels not renamed: ' + nav.replace(/\n/g, '|'))
})

// 2. 步驟清單點擊聚焦
await step('nodelist-focus', async () => {
  const before = await page.evaluate(() => document.querySelector('.react-flow__viewport')?.style.transform)
  await page.locator('[data-testid=node-list] [data-node-id="blob"]').click()
  await page.waitForTimeout(700)
  const after = await page.evaluate(() => document.querySelector('.react-flow__viewport')?.style.transform)
  const selected = await page.locator('.react-flow__node[data-id="blob"].selected').count()
  if (!selected) note('blob not selected after node list click')
  if (before === after) note('viewport did not move on node list click')
  const txt = await page.locator('[data-testid=inspector]').innerText()
  if (!txt.includes('開啟工具頁')) note('inspector lacks open-tool-page button')
  if (await page.locator('[data-testid=inspector] [data-param]').count()) note('inspector still shows params')
  await shot(page, '50-02-focus-blob')
})

// 3. 框選兩個步驟
await step('box-select', async () => {
  await page.keyboard.press('Escape')
  await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
  await page.locator('.react-flow__panel button[title="符合視窗"]').click()
  await page.waitForTimeout(500)
  const a = await page.locator('.react-flow__node[data-id="gray"]').boundingBox()
  const b = await page.locator('.react-flow__node[data-id="blur"]').boundingBox()
  const x0 = Math.min(a.x, b.x) - 12
  const y0 = Math.min(a.y, b.y) - 12
  const x1 = Math.max(a.x + a.width, b.x + b.width) + 12
  const y1 = Math.max(a.y + a.height, b.y + b.height) + 12
  await page.mouse.move(x0, y0)
  await page.mouse.down()
  await page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, { steps: 5 })
  await page.mouse.move(x1, y1, { steps: 10 })
  await page.mouse.up()
  await page.waitForTimeout(400)
  const n = await page.locator('.react-flow__node.selected').count()
  console.log('selected nodes', n)
  if (n < 2) note(`box select picked ${n} nodes`)
  const multi = await page.locator('[data-testid=multi-select]').count()
  if (n > 1 && !multi) note('inspector did not show multi-select summary')
  await shot(page, '50-03-box-select')
  await page.keyboard.press('Escape')
})

// 4. 上傳暫存影像（canvas 產一張 png）
const scratchPath = path.join(OUT, 'scratch-upload.png')
await step('scratch-upload', async () => {
  const dataUrl = await page.evaluate(() => {
    const c = document.createElement('canvas')
    c.width = 640
    c.height = 480
    const ctx = c.getContext('2d')
    ctx.fillStyle = '#d8d8d8'
    ctx.fillRect(0, 0, 640, 480)
    ctx.fillStyle = '#202020'
    for (const [x, y] of [[120, 120], [320, 110], [520, 130], [200, 340], [440, 350]]) {
      ctx.beginPath()
      ctx.arc(x, y, 28, 0, Math.PI * 2)
      ctx.fill()
    }
    return c.toDataURL('image/png')
  })
  fs.writeFileSync(scratchPath, Buffer.from(dataUrl.split(',')[1], 'base64'))
  await page.locator('[data-testid=editor-toolbar] [data-testid=scratch-input]').setInputFiles(scratchPath)
  await page.locator('[data-testid=scratch-badge]').waitFor({ timeout: 8000 })
  const badge = await page.locator('[data-testid=scratch-badge]').innerText()
  console.log('scratch badge', badge.replace(/\n/g, ' '))
  if (!badge.includes('640')) note('scratch badge lacks size: ' + badge)
  await shot(page, '50-04-scratch-uploaded')
})

// 5. 試跑（用暫存影像）＋ 前／後分割
await step('preview', async () => {
  await page.getByRole('button', { name: '試跑' }).click()
  await page.waitForTimeout(2500)
  if (!(await viewerHasImage('[data-testid=viewer-main]'))) note('viewer shows no image after preview')
  await shot(page, '50-05-preview-scratch')
  await page.locator('[data-testid=btn-split]').click()
  await page.waitForTimeout(800)
  if ((await page.locator('[data-testid=viewer-after]').count()) === 0) note('split view not shown')
  await shot(page, '50-06-split-view')
  await page.locator('[data-testid=btn-split]').click()
})

// 6. blob 工具頁
let newMinArea = 0
await step('tool-page', async () => {
  await page.locator('.react-flow__node[data-id="blob"]').click()
  await page.waitForTimeout(300)
  await page.locator('[data-testid=open-tool-page]').click()
  await page.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
  await page.locator('[data-testid=histogram]').first().waitFor({ timeout: 10000 })
  await page.waitForTimeout(800)
  const hist = await page.locator('[data-testid=histogram]').count()
  console.log('histograms', hist)
  if (hist < 1) note('no histogram in tool page')
  if (!(await viewerHasImage('[data-testid=tool-before]'))) note('tool page: before image empty')
  const ref = await page.locator('[data-testid=tool-reference]').innerText()
  if (!/blobs\.area/.test(ref)) note('tool page reference lacks series blobs.area: ' + ref.slice(0, 120).replace(/\n/g, '|'))
  await shot(page, '50-07-tool-page')
})

await step('tool-page-tune', async () => {
  const input = page.locator('[data-testid=tool-params] [data-param=min_area] input[type=number]')
  await input.waitFor({ timeout: 5000 })
  newMinArea = Number(originalMinArea ?? 300) + 111
  // 改參數後 250 ms 內應自動送出 preview（until_node=blob）；請求很快，用 waitForResponse 抓
  const waitPreview = page.waitForResponse((r) => r.url().includes('/preview') && r.request().method() === 'POST', { timeout: 5000 })
  await input.fill(String(newMinArea))
  const res = await waitPreview.catch(() => null)
  if (!res) note('tool page: no auto preview request after param change')
  else {
    const body = JSON.parse(res.request().postData() || '{}')
    if (body.until_node !== 'blob' || body.analysis !== true) note('auto preview body unexpected: ' + JSON.stringify({ until_node: body.until_node, analysis: body.analysis }))
    if (!body.reuse_image_ref) note('auto preview did not pin the source image')
  }
  await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 10000 }).catch(() => note('tool page: updating never finished'))
  await page.waitForTimeout(500)
  const err = await page.locator('[data-testid=tool-preview-error]').count()
  if (err) note('tool page preview error: ' + (await page.locator('[data-testid=tool-preview-error]').innerText()))
  await shot(page, '50-08-tool-page-tuned')
  const hdr = await page.locator('[data-testid=tool-page] header').innerText()
  if (!hdr.includes('有未儲存的變更')) note('tool page header not dirty after change: ' + hdr.replace(/\n/g, '|'))
})

// 7. 返回編輯器：參數保留
await step('back-to-editor', async () => {
  await page.locator('[data-testid=btn-back]').click()
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(600)
  const hdr = await page.locator('[data-testid=editor-toolbar]').innerText()
  if (!hdr.includes('有未儲存的變更')) note('editor not dirty after returning from tool page')
  await page.keyboard.press('Control+s')
  await page.waitForTimeout(1200)
  const saved = await api(`/flows/${flow.id}`)
  const v = saved.graph.nodes.find((n) => n.id === 'blob')?.params?.min_area
  console.log('saved blob.min_area', v, 'expected', newMinArea)
  if (v !== newMinArea) note(`param not preserved across pages: saved ${v}, expected ${newMinArea}`)
  await shot(page, '50-09-back-in-editor')
})

// 8. 製造錯誤：image_source mode=input 且清除暫存影像
await step('error-display', async () => {
  await page.locator('.react-flow__node[data-id="src"]').click()
  await page.waitForTimeout(300)
  await page.locator('[data-testid=open-tool-page]').click()
  await page.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
  await page.waitForTimeout(500)
  const sel = page.locator('[data-testid=tool-params] [data-param=mode] select')
  await sel.selectOption('input')
  await page.waitForTimeout(1500)
  await page.locator('[data-testid=btn-back]').click()
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.locator('[data-testid=scratch-clear]').click()
  await page.waitForTimeout(200)
  await page.getByRole('button', { name: '試跑' }).click()
  await page.waitForTimeout(2500)
  const red = await page.locator('[data-testid=node-error]').count()
  if (!red) note('no red error message on failed node')
  await page.getByRole('tab', { name: /結果/ }).click()
  await page.waitForTimeout(400)
  const block = page.locator('[data-testid=run-error]')
  if ((await block.count()) === 0) note('results tab has no error block')
  else {
    const txt = await block.innerText()
    console.log('error block:', txt.replace(/\n/g, ' | '))
    if (!txt.includes('暫存影像')) note('error block message unexpected: ' + txt)
  }
  await shot(page, '50-10-error-display')
  await page.locator('[data-testid=goto-failed-node]').click()
  await page.waitForTimeout(500)
  const selected = await page.locator('.react-flow__node[data-id="src"].selected').count()
  if (!selected) note('goto failed node did not select src')
})

// 9. 重置
await step('reset', async () => {
  await page.locator('[data-testid=btn-reset]').click()
  await page.locator('[role=dialog]').waitFor({ timeout: 3000 })
  await page.locator('[role=dialog]').getByRole('button', { name: '重置' }).click()
  await page.waitForTimeout(1200)
  const errs = await page.locator('[data-testid=node-error]').count()
  if (errs) note('node error still shown after reset')
  const aside = await page.locator('[data-testid=inspector-pane]').innerText()
  if (!aside.includes('還沒有執行記錄')) note('recent runs not cleared after reset: ' + aside.slice(0, 120).replace(/\n/g, '|'))
  if (await viewerHasImage('[data-testid=viewer-main]')) note('viewer still has image after reset')
  await shot(page, '50-11-after-reset')
})

// 10. 說明頁
await step('help', async () => {
  await page.goto(`${BASE}/help`)
  await page.waitForLoadState('networkidle')
  const tabs = ['quickstart', 'glossary', 'ports', 'tools', 'shortcuts', 'automation', 'accounts']
  for (let i = 0; i < tabs.length; i += 1) {
    const tab = tabs[i]
    await page.locator('[role=tablist] [role=tab]').nth(i).click()
    await page.locator(`[data-testid=help-${tab}]`).waitFor({ timeout: 5000 })
    await page.waitForTimeout(400)
    if (tab === 'tools') {
      await page.locator('[data-testid=help-tools] .card').first().waitFor({ timeout: 8000 })
      const n = await page.locator('[data-testid=help-tools] .card').count()
      if (!n) note('help tools catalogue empty')
    }
    await shot(page, `50-${12 + i}-help-${tab}`)
  }
})

// 還原示範流程
await context.request.patch(`${BASE}/api/vision/flows/${flow.id}`, { headers: AUTH, data: { graph: originalGraph } })
await browser.close()
console.log('\n==== ISSUES (' + issues.length + ')')
for (const i of issues) console.log('-', i)
console.log('==== SHOTS')
for (const s of shots) console.log(s)
