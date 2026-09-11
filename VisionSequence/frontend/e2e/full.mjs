/**
 * 全面性 Playwright 走查（手動執行，不進 CI）。
 *   node frontend/e2e/full.mjs [模組...]        模組：auth pages editor canvas viewer tool batch integration lock teach golden connections flowio style recipes lang layout
 *   node frontend/e2e/full.mjs --fresh          先清空所有使用者，測登入頁的「建立第一個管理員」表單
 *   node frontend/e2e/full.mjs --merge layout   只重跑某些模組，結果合併進既有的 full-results.json
 * 需要：後端 :8000（manage.py serve，含 TCP）、前端 :5173。
 * 清單在 CHECKLIST.md；每個模組以 h.item(ID, ok, note) 回報，結果寫到 full-results.json，
 * 再以 `node frontend/e2e/full-mark.mjs` 標回 CHECKLIST.md。截圖：Image/120-*.png（配方儲存範圍／頂列兩列回合；風格改版回合為 110-*、v0.2 回合為 90-*、更早為 70-*）。
 */
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs'

import { ADMIN, BASE, createHarness } from './full-lib.mjs'

const MODULES = ['auth', 'pages', 'editor', 'canvas', 'viewer', 'tool', 'batch', 'integration', 'lock', 'teach', 'golden', 'connections', 'flowio', 'style', 'recipes', 'lang', 'layout']
const args = process.argv.slice(2)
const fresh = args.includes('--fresh')
const merge = args.includes('--merge')
const picked = args.filter((a) => !a.startsWith('--'))
const modules = picked.length ? picked : MODULES

const REPO = fileURLToPath(new URL('../../', import.meta.url)).slice(0, -1)  // 專案根目錄（依本檔位置推算，不寫死）
if (fresh) {
  console.log('--fresh：清空所有使用者（登入頁會進入建立管理員模式）')
  execSync(`"${REPO}/.venv/Scripts/python.exe" manage.py shell -c "from django.contrib.auth import get_user_model; get_user_model().objects.all().delete()"`, { cwd: REPO, stdio: 'inherit' })
}

const h = await createHarness()
if (merge) {
  // 截圖編號接在既有結果之後，不覆蓋
  try {
    h.shotIndex = JSON.parse(fs.readFileSync(new URL('./full-results.json', import.meta.url), 'utf8')).shots ?? 0
  } catch {
    /* ignore */
  }
}
const status = await (await h.apiCtx.request.get(`${BASE}/api/auth/status`)).json()
console.log('auth status', JSON.stringify(status))
if (status.setup_required && !modules.includes('auth')) {
  // 沒有使用者但沒跑 auth 模組：直接用 API 建管理員。
  await h.apiCtx.request.post(`${BASE}/api/auth/setup`, { data: { ...ADMIN, display_name: '系統管理員' } })
}
if (!status.setup_required) {
  await h.loginAdmin()
  await h.api.del('/vision/lock')
}

// 示範流程原圖：結束時還原（含名稱／描述）。--fresh 時要等 auth 模組建好管理員才抓得到。
let flowsBefore = { items: [] }
const originals = new Map()
async function loadFlows() {
  if (!h.token) return
  flowsBefore = (await h.api.get('/vision/flows')) ?? { items: [] }
  for (const f of flowsBefore.items) if (!originals.has(f.id)) originals.set(f.id, { name: f.name, description: f.description, graph: JSON.parse(JSON.stringify(f.graph)), is_enabled: f.is_enabled, continuous_interval_ms: f.continuous_interval_ms, commissioned: f.commissioned })
}
await loadFlows()
h.demoFlow = () => flowsBefore.items.find((f) => f.name.includes('孔數') && !/副本|^E2E /.test(f.name))
h.demoFlow2 = () => flowsBefore.items.find((f) => f.name.includes('曝光') && !/副本|^E2E /.test(f.name))
h.restoreFlow = async (id) => {
  const o = originals.get(id)
  if (o) await h.api.patch(`/vision/flows/${id}`, o)
}
/** 以示範流程複製一份給破壞性測試用（名稱 E2E 開頭，結束時自動刪）。 */
h.cloneDemo = async (name) => {
  const demo = h.demoFlow()
  const copy = await h.api.post(`/vision/flows/${demo.id}/duplicate`)
  // duplicate 預設停用（後端會拒絕執行一次／連續執行），測試用的副本要開啟
  await h.api.patch(`/vision/flows/${copy.id}`, { name, is_enabled: true })
  return copy.id
}

for (const name of modules) {
  console.log(`\n===== 模組 ${name} =====`)
  try {
    const mod = await import(`./full-${name}.mjs`)
    await mod.run(h)
    if (!h.demoFlow()) {
      await h.loginAdmin()
      await loadFlows()
    }
  } catch (e) {
    h.note(`[module ${name}] ${String(e.stack || e).split('\n').slice(0, 3).join(' | ')}`)
  }
}

// 還原示範流程、解鎖、停連續、清掉測試殘留
try {
  if (!h.token) await h.loginAdmin()
  await h.api.del('/vision/lock')
  const now = await h.api.get('/vision/flows')
  for (const f of now?.items ?? []) {
    if (f.continuous) await h.api.post(`/vision/flows/${f.id}/continuous`, { running: false })
    const o = originals.get(f.id)
    if (o) {
      await h.api.patch(`/vision/flows/${f.id}`, o)
      // 示範流程上建立的配方／Golden 案例
      for (const r of (await h.api.get(`/vision/flows/${f.id}/recipes`))?.items ?? []) if (/^E2E /.test(r.name) || /^part[A-Z]/.test(r.name)) await h.api.del(`/vision/flows/${f.id}/recipes/${r.id}`)
      for (const c of (await h.api.get(`/vision/flows/${f.id}/golden`))?.items ?? []) if (/^e2e-|^E2E /.test(c.name)) await h.api.del(`/vision/flows/${f.id}/golden/${c.id}`)
    } else if (/^E2E /.test(f.name) || /\(副本/.test(f.name)) await h.api.del(`/vision/flows/${f.id}`)
  }
  const conns = await h.api.get('/vision/connections')
  for (const c of conns?.items ?? []) if (/^E2E /.test(c.name) || /^sim-e2e/.test(c.name)) await h.api.del(`/vision/connections/${c.id}`)
  const tpl = await h.api.get('/vision/templates')
  for (const t of tpl?.items ?? []) if (t.source === 'custom' && /^E2E /.test(t.name)) await h.api.del(`/vision/templates/${encodeURIComponent(t.id)}`)
  const src = await h.api.get('/vision/sources')
  for (const s of src?.items ?? []) if (/^E2E /.test(s.name)) await h.api.del(`/vision/sources/${s.id}`)
  const assets = await h.api.get('/vision/assets')
  for (const a of assets?.items ?? []) if (/^E2E /.test(a.name) || /^e2e-/.test(a.name)) await h.api.del(`/vision/assets/${a.id}`)
} catch (e) {
  h.note(`[cleanup] ${e.message}`)
}

await h.close()
if (merge) {
  try {
    const prev = JSON.parse(fs.readFileSync(new URL('./full-results.json', import.meta.url), 'utf8'))
    // W05 是整份 issues 的統計，每次都重算（不沿用舊結果，否則一旦失敗就再也翻不回來）
    h.results = { ...prev.results, ...h.results }
    delete h.results.W05
    const rerunIds = new Set(Object.keys(h.results))
    // 舊的 W05 彙總字串也丟掉（否則裡面的「HTTP 404」會被下面的 noise 正則再抓一次，永遠翻不回來）
    h.issues = [...(prev.issues ?? []).filter((i) => !i.startsWith('W05:') && !modules.some((m) => i.startsWith(`[${m}`) || i.startsWith(`[module ${m}]`) || i.includes(`[${m}-`)) && !rerunIds.has(/^\[?([A-Z]{1,2}\d{2})[a-z]?[: ]/.exec(i)?.[1] ?? '')), ...h.issues]
    h.shots = [...new Array(prev.shots ?? 0), ...h.shots]
  } catch {
    /* 沒有舊結果 */
  }
}
// W05：全程 console error／warning、pageerror、非預期 HTTP ≥400
const noise = h.issues.filter((i) => /console\.(error|warning)|pageerror|HTTP \d{3} /.test(i))
h.item('W05', noise.length === 0, noise.slice(0, 3).join(' | '))
const resultPath = h.writeResults()
const ids = Object.keys(h.results)
const pass = ids.filter((k) => h.results[k].ok === true).length
const fail = ids.filter((k) => h.results[k].ok === false).length
const skip = ids.filter((k) => h.results[k].ok === null).length
console.log(`\n==== 清單：${ids.length} 項回報，✅ ${pass}、❌ ${fail}、⏭ ${skip}`)
console.log(`==== ISSUES (${h.issues.length})`)
for (const i of h.issues) console.log('-', i)
console.log(`==== SHOTS ${h.shots.length}（${resultPath}）`)
