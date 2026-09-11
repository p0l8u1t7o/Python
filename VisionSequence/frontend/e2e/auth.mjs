/**
 * Playwright 整合測試：帳號、使用者管理、引擎鎖定（手動執行，不進 CI）。
 *   node frontend/e2e/auth.mjs
 * 需要：後端 :8000、前端 :5173 已啟動；Playwright 取自 ZQS-Cloud 的 node_modules。
 * 流程：setup 管理員（或 create_admin 重設後登入）→ 建使用者 → 設定頁鎖定 → 編輯器橫幅與按鈕 disabled → 解鎖。
 * 截圖寫到 <repo>/Image/30-*.png。
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const BASE = 'http://127.0.0.1:5173'
// 截圖輸出到專案根目錄的 Image/（.gitignore 已忽略），依本檔位置推算、不寫死
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../Image')
const ADMIN = { username: 'admin', password: 'admin123' }
const WORKER = { username: 'worker1', password: 'worker123' }
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
page.on('pageerror', (e) => note(`pageerror: ${e.message.slice(0, 300)}`))
page.on('console', (m) => {
  if (m.type() === 'error' && !m.text().includes('React DevTools') && !/40[13]|423|Failed to load resource/.test(m.text())) note(`console.error: ${m.text().slice(0, 200)}`)
})
page.on('response', (r) => {
  if (r.status() >= 500) note(`HTTP ${r.status()} ${r.url()}`)
})
page.on('dialog', (d) => d.accept())

const req = context.request
const json = async (r) => {
  try {
    return await r.json()
  } catch {
    return null
  }
}

// 0. 系統狀態：沒有使用者就走 UI 的 setup 表單；否則直接登入（密碼由 create_admin 重設）。
const status = await json(await req.get(`${BASE}/api/auth/status`))
console.log('auth status', JSON.stringify(status))

await step('login-page', async () => {
  await page.goto(`${BASE}/flows`)
  await page.waitForURL(/\/login/, { timeout: 10000 })
  await page.waitForTimeout(400)
  await shot(page, status?.setup_required ? '30-setup-form' : '30-login-form')
  await page.getByLabel('帳號').fill(ADMIN.username)
  await page.getByLabel(status?.setup_required ? '密碼' : '密碼', { exact: true }).fill(ADMIN.password)
  if (status?.setup_required) await page.getByLabel('顯示名稱').fill('系統管理員')
  await page.getByRole('button', { name: status?.setup_required ? '建立管理員並登入' : '登入' }).click()
  await page.waitForURL(/\/flows$/, { timeout: 10000 })
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(500)
  const menu = await page.getByTestId('user-menu').innerText()
  console.log('user menu:', menu)
  await shot(page, '31-flows-logged-in')
})

// 管理員 token（API 直接呼叫用）
const login = await json(await req.post(`${BASE}/api/auth/login`, { data: ADMIN }))
if (!login?.token) throw new Error('admin login via API failed: ' + JSON.stringify(login))
const adminHeaders = { Authorization: `Bearer ${login.token}` }
const api = {
  get: async (p) => json(await req.get(`${BASE}/api${p}`, { headers: adminHeaders })),
  post: async (p, data) => req.post(`${BASE}/api${p}`, { headers: adminHeaders, data }),
  del: async (p) => req.delete(`${BASE}/api${p}`, { headers: adminHeaders }),
}
// 若之前留下鎖，先清掉
await api.del('/vision/lock')
// 之前跑過的 worker1 先刪
const existing = await api.get('/users')
for (const u of existing?.items ?? []) if (u.username === WORKER.username) await api.del(`/users/${u.id}`)

await step('users-create', async () => {
  await page.goto(`${BASE}/users`)
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: '新增使用者' }).click()
  await page.getByRole('dialog').getByLabel('帳號').fill(WORKER.username)
  await page.getByRole('dialog').getByLabel('密碼').fill(WORKER.password)
  await page.getByRole('dialog').getByLabel('顯示名稱').fill('產線人員一')
  await shot(page, '32-users-create-modal')
  await page.getByRole('dialog').getByRole('button', { name: '新增' }).click()
  await page.waitForTimeout(800)
  const txt = await page.locator('main').innerText()
  if (!txt.includes(WORKER.username)) note('worker1 not listed after create')
  await shot(page, '33-users-list')
})

await step('settings-lock', async () => {
  await page.goto(`${BASE}/settings`)
  await page.waitForLoadState('networkidle')
  await page.getByLabel('原因').fill('整合方校正相機')
  await page.getByTestId('btn-lock').click()
  await page.waitForTimeout(800)
  const st = await page.getByTestId('lock-status').innerText()
  console.log('lock status:', st.replace(/\n/g, ' '))
  if (!st.includes('已鎖定')) note('settings lock status not locked')
  const banner = page.getByTestId('lock-banner')
  if ((await banner.count()) === 0) note('lock banner missing on settings page')
  else console.log('banner:', (await banner.innerText()).replace(/\n/g, ' '))
  await shot(page, '34-settings-locked')
})

const flows = await api.get('/vision/flows')
const flow = flows?.items?.[0]
if (!flow) note('no flow to open editor')

// 鎖的持有者（admin）本人仍可執行（後端 can_execute），所以用一般使用者 worker1 看鎖定效果。
const workerLogin = await json(await req.post(`${BASE}/api/auth/login`, { data: WORKER }))
if (!workerLogin?.token) throw new Error('worker login failed: ' + JSON.stringify(workerLogin))
const workerHeaders = { Authorization: `Bearer ${workerLogin.token}` }
// 另開一個 context：同一個 context 共用 localStorage，寫 worker 的 token 會把 admin 頁也變成 worker。
const wctx = await browser.newContext({ viewport: { width: 1600, height: 1000 }, locale: 'zh-TW' })
const wpage = await wctx.newPage()
wpage.on('pageerror', (e) => note(`worker pageerror: ${e.message.slice(0, 300)}`))
await wpage.goto(`${BASE}/login`)
await wpage.evaluate((tk) => localStorage.setItem('vs.token', tk), workerLogin.token)

await step('editor-locked-as-worker', async () => {
  await wpage.goto(`${BASE}/flows/${flow.id}`)
  await wpage.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await wpage.waitForTimeout(800)
  if ((await wpage.getByTestId('lock-banner').count()) === 0) note('lock banner missing in worker editor')
  else console.log('worker banner:', (await wpage.getByTestId('lock-banner').innerText()).replace(/\n/g, ' '))
  if ((await wpage.getByTestId('lock-banner').getByRole('button', { name: '解鎖' }).count()) !== 0) note('worker sees unlock button')
  for (const id of ['btn-preview', 'btn-run', 'btn-run-file', 'btn-continuous']) {
    const disabled = await wpage.getByTestId(id).isDisabled()
    console.log(id, 'disabled =', disabled)
    if (!disabled) note(`${id} not disabled while locked (worker)`)
  }
  await shot(wpage, '35-editor-locked-worker')
  // API 直接執行 → 423
  const r = await req.post(`${BASE}/api/vision/flows/${flow.id}/run`, { headers: workerHeaders, data: { context: null, wait: true } })
  const body = await json(r)
  console.log('worker run while locked ->', r.status(), JSON.stringify(body).slice(0, 200))
  if (r.status() !== 423) note(`expected 423 while locked, got ${r.status()}`)
})

await step('editor-locked-as-admin-holder', async () => {
  await page.goto(`${BASE}/flows/${flow.id}`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(800)
  if ((await page.getByTestId('lock-banner').count()) === 0) note('lock banner missing in admin editor')
  // 持有者本人可執行：按鈕保持可用
  if (await page.getByTestId('btn-preview').isDisabled()) note('holder preview disabled')
  await shot(page, '35b-editor-locked-admin-holder')
})

await step('editor-unlock-from-banner', async () => {
  await page.getByTestId('lock-banner').getByRole('button', { name: '解鎖' }).click()
  await page.waitForTimeout(800)
  if ((await page.getByTestId('lock-banner').count()) !== 0) note('banner still visible after unlock')
  // worker 頁不重整，靠 SSE 收到解鎖
  await wpage.waitForTimeout(1200)
  if ((await wpage.getByTestId('lock-banner').count()) !== 0) note('worker banner still visible after unlock (SSE)')
  if (await wpage.getByTestId('btn-preview').isDisabled()) note('worker preview still disabled after unlock')
  await shot(wpage, '36-editor-unlocked-worker')
})

// SSE：由 API 上鎖，畫面應該不用重整就出現橫幅
await step('lock-via-api-sse', async () => {
  await api.post('/vision/lock', { reason: '透過 API 上鎖', ttl_s: 600 })
  await wpage.getByTestId('lock-banner').waitFor({ timeout: 8000 })
  console.log('worker banner via SSE:', (await wpage.getByTestId('lock-banner').innerText()).replace(/\n/g, ' '))
  if (!(await wpage.getByTestId('btn-run').isDisabled())) note('worker run not disabled after SSE lock')
  await shot(wpage, '37-editor-lock-via-sse-worker')
  await api.del('/vision/lock')
  await wpage.waitForTimeout(1200)
  if ((await wpage.getByTestId('lock-banner').count()) !== 0) note('worker banner still visible after API unlock')
})

// 一般使用者：看不到「使用者」導覽；列表只有自己的＋共用；「只看我的」切換。
// 註：後端 can_edit_flow 允許所有人修改共用流程（owner=null），唯讀只會發生在「別人的流程」，而列表本來就看不到。
await step('worker-flows', async () => {
  await wpage.goto(`${BASE}/flows`)
  await wpage.waitForLoadState('networkidle')
  await wpage.waitForTimeout(500)
  const nav = await wpage.locator('nav').innerText()
  if (nav.includes('使用者')) note('worker sees users nav')
  await shot(wpage, '38-worker-flows')
  await wpage.getByRole('switch', { name: '只看我的' }).click()
  await wpage.waitForTimeout(600)
  await shot(wpage, '39-worker-flows-mine')
  const adminFlows = await api.get('/vision/flows?mine=true')
  const own = adminFlows?.items?.[0]
  if (own) {
    const r = await req.get(`${BASE}/api/vision/flows/${own.id}`, { headers: workerHeaders })
    console.log('worker GET admin-owned flow ->', r.status())
  } else console.log('admin owns no flow (demo flows are shared)')
})
await wctx.close()

// 登出
await step('logout', async () => {
  await page.goto(`${BASE}/settings`)
  await page.waitForLoadState('networkidle')
  await page.getByTestId('user-menu').click()
  await page.getByRole('menuitem', { name: '登出' }).click()
  await page.waitForURL(/\/login/, { timeout: 8000 })
  await shot(page, '40-after-logout')
})

await browser.close()
console.log('\n==== ISSUES (' + issues.length + ')')
for (const i of issues) console.log('-', i)
console.log('==== SHOTS')
for (const s of shots) console.log(s)
