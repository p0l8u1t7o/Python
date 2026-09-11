/**
 * 開發計畫 v0.2 前端功能的 Playwright 實跑（手動執行，不進 CI）。
 *   node frontend/e2e/plan.mjs
 * 需要：後端 :8000（manage.py serve）、前端 :5173（npm run dev）；帳號 admin/admin123（登入方式同 smoke.mjs）。
 * 流程：參數卡改值即時更新 → 執行一次看 warnings → 標記已教導 → 建配方 → 用配方執行 → 上傳 3 張 Golden 案例 → 回歸（存基準）
 *      → 再回歸 → 匯出 → 匯入 → 連線頁建 dio_sim → 測試 → 手動寫入 → 狀態檢視 → 加 write_modbus 到流程跑一次（成功＋降級）→ 英文檢視器文案。
 * 截圖寫到 <repo>/Image/80-*.png；console.error／pageerror 全部列在結尾 ISSUES。
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import os from 'node:os'

const BASE = 'http://127.0.0.1:5173'
// 截圖輸出到專案根目錄的 Image/（.gitignore 已忽略），依本檔位置推算、不寫死
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../Image')
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'vs-plan-'))
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, locale: 'zh-TW', acceptDownloads: true })
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

// 登入（同 smoke.mjs）
const CRED = { username: process.env.VS_USER || 'admin', password: process.env.VS_PASS || 'admin123' }
const status = await (await context.request.get(`${BASE}/api/auth/status`)).json()
const loginRes = await context.request.post(`${BASE}/api/auth/${status.setup_required ? 'setup' : 'login'}`, { data: CRED })
const loginBody = await loginRes.json()
if (!loginBody.token) throw new Error('login failed: ' + JSON.stringify(loginBody))
const AUTH = { Authorization: `Bearer ${loginBody.token}` }
await context.addInitScript((tk) => localStorage.setItem('vs.token', tk), loginBody.token)
await context.request.delete(`${BASE}/api/vision/lock`, { headers: AUTH })

const api = async (p) => (await context.request.get(`${BASE}/api/vision${p}`, { headers: AUTH })).json()
const apiPost = async (p, data) => (await context.request.post(`${BASE}/api/vision${p}`, { headers: AUTH, data })).json()
const apiPatch = async (p, data) => (await context.request.patch(`${BASE}/api/vision${p}`, { headers: AUTH, data })).json()
const apiDelete = async (p) => context.request.delete(`${BASE}/api/vision${p}`, { headers: AUTH })

const flows = await api('/flows')
const flow = flows.items.find((f) => f.name.includes('孔數'))
if (!flow) throw new Error('demo flow not found')
const FID = flow.id
console.log('flow', FID, flow.name, 'commissioned', flow.commissioned)
const originalGraph = flow.graph

// 起始狀態：未教導、沒有配方、沒有 Golden 案例、沒有測試連線
await apiPatch(`/flows/${FID}`, { commissioned: false })
for (const r of (await api(`/flows/${FID}/recipes`)).items) await apiDelete(`/flows/${FID}/recipes/${r.id}`)
for (const c of (await api(`/flows/${FID}/golden`)).items) await apiDelete(`/flows/${FID}/golden/${c.id}`)
for (const c of (await api('/connections')).items) if (c.name === 'sim-e2e') await apiDelete(`/connections/${c.id}`)

// ---------------------------------------------------------------- 1. 參數卡
await step('teach-open', async () => {
  await page.goto(`${BASE}/flows/${FID}/teach`)
  await page.locator('[data-testid=teach-group]').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(2500)
  const groups = await page.locator('[data-testid=teach-group]').count()
  console.log('teach groups', groups)
  if (groups < 2) note(`teach groups=${groups}, expected >= 2 (thr/blob/cmp)`)
  const statuses = await page.locator('[data-testid=teach-status]').count()
  if (statuses === 0) note('no step status after initial preview')
  if ((await page.locator('[data-testid=not-commissioned-badge], [data-testid=teach-mark]').count()) === 0) note('teach page: no "mark as commissioned" button')
  await shot(page, '80-01-teach')
})

await step('teach-edit-live', async () => {
  const before = (await api(`/flows/${FID}`)).graph
  const thrBefore = before.nodes.find((n) => n.id === 'thr').params.threshold
  const group = page.locator('[data-testid=teach-group][data-node-id=thr]')
  const numberInput = group.locator('input[type=number]').first()
  const next = Number(thrBefore) > 200 ? 60 : 200
  await numberInput.fill(String(next))
  await page.waitForTimeout(400)
  await page.locator('[data-testid=teach-updating]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => {})
  await page.waitForTimeout(600)
  const statusText = await group.locator('[data-testid=teach-status]').innerText()
  console.log('thr status after edit:', statusText.replace(/\n/g, ' '))
  if (!/ms/.test(statusText)) note('teach: no duration after live edit')
  await shot(page, '80-02-teach-live-edit')
  // Ctrl+S 存到圖
  await page.keyboard.press('Control+s')
  await page.waitForTimeout(1200)
  const after = (await api(`/flows/${FID}`)).graph
  const thrAfter = after.nodes.find((n) => n.id === 'thr').params.threshold
  console.log('threshold', thrBefore, '->', thrAfter)
  if (Number(thrAfter) !== next) note(`teach save: threshold=${thrAfter}, expected ${next}`)
})

// 未教導 → 編輯器執行一次 → 結果分頁應顯示黃色 warnings
await step('editor-run-warnings', async () => {
  await page.goto(`${BASE}/flows/${FID}`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(800)
  if ((await page.locator('[data-testid=not-commissioned-badge]').count()) === 0) note('editor toolbar: no not-commissioned badge')
  await page.locator('[data-testid=btn-run]').click()
  await page.waitForTimeout(3000)
  await page.getByRole('tab', { name: /結果/ }).click().catch(async () => page.getByRole('button', { name: /結果/ }).first().click())
  await page.waitForTimeout(600)
  const warn = page.locator('[data-testid=run-warnings]')
  if ((await warn.count()) === 0) note('results tab: no run-warnings block for uncommissioned flow')
  else console.log('warnings:', (await warn.innerText()).replace(/\n/g, ' | '))
  await shot(page, '80-03-editor-warnings')
})

await step('teach-mark-commissioned', async () => {
  await page.goto(`${BASE}/flows/${FID}/teach`)
  await page.locator('[data-testid=teach-group]').first().waitFor({ timeout: 15000 })
  await page.locator('[data-testid=teach-mark]').click()
  await page.waitForTimeout(1200)
  const f = await api(`/flows/${FID}`)
  if (!f.commissioned) note('commissioned still false after marking')
  if ((await page.locator('[data-testid=teach-unmark]').count()) === 0) note('no green commissioned badge / unmark button')
  await shot(page, '80-04-teach-commissioned')
})

// ---------------------------------------------------------------- 2. 配方
await step('recipe-create', async () => {
  await page.locator('[data-testid=teach-save-as]').click()
  await page.locator('[data-testid=teach-save-as-name]').fill('partA')
  await page.locator('[data-testid=teach-save-as-confirm]').click()
  await page.waitForTimeout(1200)
  const list = (await api(`/flows/${FID}/recipes`)).items
  console.log('recipes', list.map((r) => `${r.name}${r.is_default ? '*' : ''}`))
  if (!list.some((r) => r.name === 'partA')) note('recipe partA not created')
  const sel = page.locator('[data-testid=teach-recipe]')
  const val = await sel.inputValue()
  if (!val) note('recipe select not switched to new recipe')
  // 改一個值 → 寫進配方（不是圖）
  const group = page.locator('[data-testid=teach-group][data-node-id=blob]')
  const input = group.locator('input[type=number]').first()
  await input.fill('123')
  await page.waitForTimeout(700)
  await page.keyboard.press('Control+s')
  await page.waitForTimeout(1200)
  const r = (await api(`/flows/${FID}/recipes`)).items.find((x) => x.name === 'partA')
  console.log('partA overrides', JSON.stringify(r?.param_overrides))
  const g = (await api(`/flows/${FID}`)).graph
  const blobMin = g.nodes.find((n) => n.id === 'blob').params.min_area
  if (!r || !r.param_overrides.blob || r.param_overrides.blob.min_area !== 123) note('recipe override not saved: ' + JSON.stringify(r?.param_overrides))
  if (blobMin === 123) note('graph was modified instead of recipe')
  await shot(page, '80-05-teach-recipe')
  // 管理配方 Modal
  await page.locator('[data-testid=teach-manage]').click()
  await page.locator('[data-testid=recipe-detail]').waitFor({ timeout: 5000 })
  await page.waitForTimeout(400)
  await shot(page, '80-06-recipe-manager')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)
})

await step('editor-run-with-recipe', async () => {
  await page.goto(`${BASE}/flows/${FID}`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(800)
  const sel = page.locator('[data-testid=editor-recipe]')
  if ((await sel.count()) === 0) return note('editor: recipe dropdown not shown')
  await sel.selectOption('partA')
  await page.locator('[data-testid=btn-run]').click()
  await page.waitForTimeout(3000)
  const recent = await api(`/flows/${FID}/recent?limit=3`)
  const last = recent.items[0]
  console.log('last run recipe:', last?.recipe, 'station', last?.station_id, 'warnings', last?.warnings)
  if (last?.recipe !== 'partA') note(`run recipe=${last?.recipe}, expected partA`)
  if (last?.warnings?.length) note('commissioned flow still has warnings: ' + last.warnings.join(','))
  await page.getByRole('tab', { name: /結果/ }).click().catch(async () => page.getByRole('button', { name: /結果/ }).first().click())
  await page.waitForTimeout(500)
  await shot(page, '80-07-editor-recipe-run')
})

// ---------------------------------------------------------------- 3. Golden Set
const imgFiles = []
await step('golden-upload', async () => {
  // 用最近一次執行的來源影像（影像快取 GET /images/{ref}）當案例；抓不到就用頁面截圖當 PNG
  const recent = (await api(`/flows/${FID}/recent?limit=3`)).items
  const refs = recent.map((r) => r.nodes?.src?.outputs?.image?.ref).filter(Boolean)
  for (let i = 0; i < 3; i++) {
    const p = path.join(TMP, `case${i + 1}.png`)
    let buf = null
    if (refs[i % refs.length]) {
      const res = await context.request.get(`${BASE}/api/vision/images/${encodeURIComponent(refs[i % refs.length])}?fmt=png`, { headers: AUTH })
      if (res.ok()) buf = Buffer.from(await res.body())
    }
    if (!buf || buf.length < 100) buf = await page.screenshot({ clip: { x: 100 + i * 40, y: 100, width: 320, height: 240 } })
    fs.writeFileSync(p, buf)
    imgFiles.push(p)
  }
  console.log('case files', imgFiles.map((f) => fs.statSync(f).size))
  await page.goto(`${BASE}/flows/${FID}/golden`)
  await page.locator('[data-testid=golden-upload]').waitFor({ timeout: 15000 })
  await page.locator('[data-testid=golden-upload-expect]').selectOption('any')
  await page.locator('[data-testid=golden-upload-input]').setInputFiles(imgFiles)
  await page.waitForTimeout(2500)
  const list = await api(`/flows/${FID}/golden`)
  console.log('golden cases', list.total)
  if (list.total !== 3) note(`golden cases=${list.total}, expected 3`)
  // 改期望值：第一張改成 ok
  await page.locator('[data-testid=golden-case-expect]').first().selectOption('ok')
  await page.waitForTimeout(800)
  const after = await api(`/flows/${FID}/golden`)
  if (after.items[0]?.expect_status !== 'ok') note('expect_status inline edit not saved')
  const imgOk = await page.locator('table img').first().evaluate((el) => el.complete && el.naturalWidth > 0).catch(() => false)
  if (!imgOk) note('golden thumbnail not loaded (token?)')
  await shot(page, '80-08-golden-cases')
})

await step('golden-regress-baseline', async () => {
  await page.getByText('存為基準', { exact: true }).click()
  await page.locator('[data-testid=golden-fail-under]').fill('0.5')
  await page.locator('[data-testid=golden-regress]').click()
  await page.locator('[data-testid=golden-result]').waitFor({ timeout: 60000 })
  await page.waitForTimeout(800)
  const kpi = await page.locator('[data-testid=golden-kpi]').innerText()
  console.log('regress kpi:', kpi.replace(/\n/g, ' '))
  const bl = await api(`/flows/${FID}/golden/baseline`)
  if (!bl.baseline) note('baseline not saved after regress with save_baseline')
  if (!/已存為基準|基準/.test(await page.locator('[data-testid=golden-baseline]').innerText())) note('baseline label not updated')
  await shot(page, '80-09-golden-regress-baseline')
})

await step('golden-regress-again', async () => {
  // 取消「存為基準」再跑一次；用草稿改 threshold 極端值讓結果有變化（若草稿存在）
  await page.getByText('存為基準', { exact: true }).click()
  await page.locator('[data-testid=golden-regress]').click()
  await page.waitForTimeout(500)
  await page.locator('[data-testid=golden-result]').waitFor({ timeout: 60000 })
  await page.waitForTimeout(800)
  const regressed = await page.locator('[data-testid=regressed-row]').count()
  const noReg = await page.locator('[data-testid=no-regressed]').count()
  console.log('regressed rows', regressed, 'no-regressed', noReg)
  if (regressed === 0 && noReg === 0) note('regress result: neither regressed rows nor "none" message')
  const rows = await page.locator('[data-testid=golden-result-row]').count()
  console.log('result rows shown', rows)
  await shot(page, '80-10-golden-regress-again')
  // 第一列點開影像視窗（有 image_ref 才可點）
  const clickable = page.locator('[data-testid=golden-result-row] img').first()
  if ((await clickable.count()) > 0) {
    await clickable.click()
    await page.waitForTimeout(2500)
    await shot(page, '80-11-golden-viewer')
    await page.keyboard.press('Escape')
  }
})

// ---------------------------------------------------------------- 4. 匯出／匯入
let exported = ''
await step('export', async () => {
  await page.goto(`${BASE}/flows`)
  await page.locator('[data-testid=row-export]').first().waitFor({ timeout: 15000 })
  if ((await page.getByText('未教導').count()) === 0) console.log('(no uncommissioned flow shown — expected after marking)')
  const row = page.locator('tr', { hasText: flow.name })
  const [download] = await Promise.all([page.waitForEvent('download', { timeout: 15000 }), row.locator('[data-testid=row-export]').click()])
  exported = path.join(TMP, download.suggestedFilename() || 'flow.flow.json')
  await download.saveAs(exported)
  const doc = JSON.parse(fs.readFileSync(exported, 'utf8'))
  console.log('exported', download.suggestedFilename(), 'schema', doc.schema_version, 'name', doc.name)
  if (!doc.name) note('exported file has no name')
  await shot(page, '80-12-flows-export')
})

await step('import', async () => {
  const versionBefore = (await api(`/flows/${FID}`)).version
  await page.locator('[data-testid=btn-import]').click()
  await page.locator('[data-testid=import-input]').setInputFiles(exported)
  const src = (await api('/sources')).items[0]
  await page.locator('[data-testid=import-source]').selectOption(String(src.id))
  await shot(page, '80-13-import-modal')
  await page.locator('[data-testid=import-confirm]').click()
  await page.waitForTimeout(2000)
  const f = await api(`/flows/${FID}`)
  console.log('after import version', versionBefore, '->', f.version, 'url', page.url())
  if (!page.url().includes(`/flows/${FID}`)) note('import did not navigate to the upserted flow')
})

// ---------------------------------------------------------------- 5. 連線
let connId = 0
await step('connections-create', async () => {
  await page.goto(`${BASE}/connections`)
  await page.locator('[data-testid=conn-create]').waitFor({ timeout: 15000 })
  await page.locator('[data-testid=conn-create]').click()
  await page.locator('[data-testid=conn-name-input]').fill('sim-e2e')
  await page.locator('[data-testid=conn-kind]').selectOption('dio_sim')
  await page.waitForTimeout(200)
  await shot(page, '80-14-connection-form')
  await page.locator('[data-testid=conn-save]').click()
  await page.waitForTimeout(1200)
  const list = (await api('/connections')).items
  const c = list.find((x) => x.name === 'sim-e2e')
  if (!c) return note('connection sim-e2e not created')
  connId = c.id
  console.log('connection', c.id, c.kind, JSON.stringify(c.config))
})

await step('connections-test-write-state', async () => {
  const row = page.locator('tr', { hasText: 'sim-e2e' })
  await row.locator('[data-testid=conn-test]').click()
  await page.waitForTimeout(1000)
  await row.locator('[data-testid=conn-write]').click()
  await page.locator('[data-testid=conn-write-values]').fill('{"DO0": 1, "OK": 1}')
  await page.locator('[data-testid=conn-write-send]').click()
  await page.waitForTimeout(1000)
  const res = await page.locator('[data-testid=connection-result]').innerText()
  console.log('write result:', res.replace(/\s+/g, ' ').slice(0, 160))
  if (!/"ok": true/.test(res)) note('manual write failed: ' + res.slice(0, 120))
  await shot(page, '80-15-connection-write')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)
  const st = await api(`/connections/${connId}/state`)
  console.log('state', JSON.stringify(st.values))
  if (st.values?.DO0 !== 1) note('dio_sim state DO0 != 1 after write')
  await row.getByRole('button', { name: '狀態檢視' }).click()
  await page.waitForTimeout(1000)
  if ((await page.locator('[data-testid=conn-state-table]').count()) === 0) note('state modal shows no channel table')
  await shot(page, '80-16-connection-state')
  await page.keyboard.press('Escape')
})

// ---------------------------------------------------------------- 6. write_modbus 進流程
await step('write-plc-run', async () => {
  const f = await api(`/flows/${FID}`)
  const graph = structuredClone(f.graph)
  graph.nodes.push({ id: 'plc1', type: 'write_modbus', label: 'Modbus', position: { x: 1400, y: 300 }, params: { connection: 'sim-e2e', mapping: [{ src: 'judge', address: 'OK', dtype: 'bool' }, { value: 1, address: 'DO1', dtype: 'bool' }], on_error: 'warn' } })
  await apiPatch(`/flows/${FID}`, { graph })
  await page.goto(`${BASE}/flows/${FID}`)
  await page.locator('.react-flow__node[data-id="plc1"]').waitFor({ timeout: 15000 })
  await page.waitForTimeout(600)
  // 工具頁：connection 應是 datalist 欄位
  await page.goto(`${BASE}/flows/${FID}/tools/plc1`)
  await page.locator('[data-testid=param-connection]').waitFor({ timeout: 15000 })
  const listId = await page.locator('[data-testid=param-connection]').getAttribute('list')
  const opts = await page.locator(`datalist[id="${listId}"] option`).count().catch(() => 0)
  console.log('connection datalist options', opts)
  if (opts === 0) note('write_modbus connection field has no datalist options')
  await shot(page, '80-17-write-plc-toolpage')
  await page.goto(`${BASE}/flows/${FID}`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.locator('[data-testid=btn-run]').click()
  await page.waitForTimeout(3000)
  let run = (await api(`/flows/${FID}/recent?limit=1`)).items[0]
  console.log('write_modbus run:', run?.status, 'plc1', run?.nodes?.plc1?.status, run?.nodes?.plc1?.message, 'warnings', run?.warnings)
  if (run?.nodes?.plc1?.status !== 'ok') note('write_modbus node not ok: ' + JSON.stringify(run?.nodes?.plc1?.message))
  if (run?.nodes?.plc1?.outputs?.written < 1) note('write_modbus wrote nothing: ' + JSON.stringify(run?.nodes?.plc1?.outputs))
  const st = await api(`/connections/${connId}/state`)
  console.log('dio state after run', JSON.stringify(st.values))
  // 降級：改成不存在的連線
  graph.nodes.find((n) => n.id === 'plc1').params.connection = 'no-such-conn'
  await apiPatch(`/flows/${FID}`, { graph })
  await page.reload()
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(600)
  await page.locator('[data-testid=btn-run]').click()
  await page.waitForTimeout(3000)
  run = (await api(`/flows/${FID}/recent?limit=1`)).items[0]
  console.log('degraded run:', run?.status, 'warnings', run?.warnings, 'plc1', run?.nodes?.plc1?.status)
  if (run?.status === 'failed') note('degraded write_modbus made the run failed (expected warn only)')
  // 降級是節點層級：status=ok、outputs.ok=false、message「寫入失敗（已降級）」、logs 有 warning（run.warnings 只放流程層級的提醒）
  const plc = run?.nodes?.plc1
  console.log('degraded plc1:', plc?.message, JSON.stringify(plc?.outputs), plc?.logs?.map((l) => l.level))
  if (!plc || plc.outputs?.ok !== false || !/降級/.test(plc.message || '')) note('degraded write_modbus did not report degrade: ' + JSON.stringify(plc?.message))
  await page.getByRole('tab', { name: /結果/ }).click().catch(async () => page.getByRole('button', { name: /結果/ }).first().click())
  await page.waitForTimeout(500)
  if (run?.warnings?.length && (await page.locator('[data-testid=run-warnings]').count()) === 0) note('degrade warnings not shown in results tab')
  await shot(page, '80-18-write-plc-degraded')
})

// ---------------------------------------------------------------- 7. 統計／總覽／整合頁／英文
await step('stats-dashboard', async () => {
  await page.goto(`${BASE}/flows/${FID}/stats`)
  await page.locator('[data-testid=stats-kpi]').waitFor({ timeout: 15000 })
  await page.locator('[data-testid=history-recipe]').first().waitFor({ timeout: 15000 }).catch(() => {})
  await page.waitForTimeout(500)
  const cells = await page.locator('[data-testid=history-recipe]').allInnerTexts()
  console.log('history recipe column:', cells.slice(0, 5))
  if (!cells.some((c) => c === 'partA')) note('stats history: no partA recipe cell')
  await shot(page, '80-19-stats')
  await page.goto(`${BASE}/`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(1200)
  const meta = await page.locator('[data-testid=card-meta]').first().innerText().catch(() => '')
  console.log('dashboard card meta:', meta.replace(/\n/g, ' '))
  if (!meta) note('dashboard: no station/recipe meta on card')
  await shot(page, '80-20-dashboard')
  await page.goto(`${BASE}/integration?tab=plc`)
  await page.locator('[data-testid=plc-go-connections]').waitFor({ timeout: 15000 })
  await shot(page, '80-21-integration-plc')
  await page.goto(`${BASE}/integration?tab=http`)
  await page.locator('[data-testid=http-recipe]').waitFor({ timeout: 15000 })
  await page.locator('[data-testid=http-recipe]').fill('partA')
  await page.waitForTimeout(300)
  const snippet = await page.locator('pre').first().innerText()
  if (!snippet.includes('partA')) note('HTTP snippet does not include recipe')
  await page.goto(`${BASE}/integration?tab=tcp`)
  await page.waitForTimeout(800)
  if ((await page.getByText(/RUN \d+ recipe=<name>/).count()) === 0) note('TCP common commands missing recipe=')
})

await step('english-viewer', async () => {
  await page.evaluate(() => localStorage.setItem('vs.language', 'en'))
  await page.goto(`${BASE}/flows/${FID}/tools/thr`)
  await page.locator('[data-testid=tool-page]').waitFor({ timeout: 15000 })
  await page.waitForTimeout(2500)
  const fit = await page.locator('button[title="Fit (F)"]').count()
  if (fit === 0) note('viewer toolbar not translated to English')
  const zh = await page.locator('button[title="適合視窗 (F)"]').count()
  if (zh > 0) note('viewer toolbar still Chinese in English mode')
  await shot(page, '80-22-english-viewer')
  await page.goto(`${BASE}/sources`)
  await page.waitForTimeout(800)
  await page.evaluate(() => localStorage.setItem('vs.language', 'zh-Hant'))
})

// ---------------------------------------------------------------- 清理：還原示範流程的圖，刪測試資料
await step('cleanup', async () => {
  await apiPatch(`/flows/${FID}`, { graph: originalGraph })
  for (const r of (await api(`/flows/${FID}/recipes`)).items) await apiDelete(`/flows/${FID}/recipes/${r.id}`)
  for (const c of (await api(`/flows/${FID}/golden`)).items) await apiDelete(`/flows/${FID}/golden/${c.id}`)
  if (connId) await apiDelete(`/connections/${connId}`)
})

await browser.close()
console.log('\n==== ISSUES (' + issues.length + ')')
for (const i of issues) console.log('-', i)
console.log('==== SHOTS')
for (const s of shots) console.log(s)
