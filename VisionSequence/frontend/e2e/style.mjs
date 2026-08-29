/**
 * 風格改版走查（手動執行，不進 CI）：
 *   node frontend/e2e/style.mjs
 * 需要：後端 :8000、前端 :5173 已啟動；Playwright 取自 ZQS-Cloud 的 node_modules（full-lib.mjs）。
 * 內容：側欄摺疊／展開（localStorage、tooltip、不換行）、各頁在 Gentelella 風格下的截圖（淺／深色）、
 *       參數卡三欄新版面、流程頁配方側滑面板（新增→Check List→儲存、設綁定、匯出、匯入→檢查→接受）、
 *       雙擊步驟開工具頁、畫布預設拖移／Shift 框選、前後影像各自縮放。
 * 截圖 Image/100-*.png；console error／pageerror 收集在最後列出；結束清掉 E2E 流程。
 */
import fs from 'node:fs'
import path from 'node:path'

import { BASE, OUT, createHarness } from './full-lib.mjs'

const SCRATCH = 'C:/Users/grown/AppData/Local/Temp/claude/d--Working-Space-Python-VisionSequence/6c0c530e-1ec2-4b18-9f56-572ac47cb72c/scratchpad'
fs.mkdirSync(SCRATCH, { recursive: true })

const h = await createHarness()
// 截圖改用 100-*.png
h.shotIndex = 0
h.shot = async (page, name, { full = false } = {}) => {
  h.shotIndex += 1
  const file = `100-${String(h.shotIndex).padStart(3, '0')}-${name}.png`
  const p = path.join(OUT, file)
  await page.screenshot({ path: p, fullPage: full })
  h.shots.push(p)
  console.log('shot', file)
  await h.checkPage(page, name)
  return p
}

await h.loginAdmin()
await h.api.del('/vision/lock')
const flows = await h.api.get('/vision/flows')
const demo = flows.items.find((f) => f.name.includes('孔數') && !/副本|^E2E /.test(f.name))
if (!demo) throw new Error('找不到示範流程（孔數）')
// 清掉上次殘留
for (const f of flows.items) if (/^E2E 風格/.test(f.name)) await h.api.del(`/vision/flows/${f.id}`)
const copy = await h.api.post(`/vision/flows/${demo.id}/duplicate`)
await h.api.patch(`/vision/flows/${copy.id}`, { name: 'E2E 風格', is_enabled: true })
const flowId = copy.id
const FLOW_NAME = 'E2E 風格'

const context = await h.newContext({ token: h.token })
const page = await h.newPage(context, '[style]')
const sleep = h.sleep
const scaleOf = (sel) => page.locator(`${sel} span.min-w-11`).first().innerText()

// ---------------------------------------------------------------- 側欄
await h.step('S01 側欄摺疊／展開', async () => {
  await page.goto(`${BASE}/flows`)
  await page.getByTestId('sidebar').waitFor()
  await page.locator('table tbody tr').first().waitFor({ timeout: 15000 })
  const nowrap = await page.evaluate(() => [...document.querySelectorAll('[data-testid=sidebar] .nav-item')].every((el) => getComputedStyle(el).whiteSpace === 'nowrap' && el.scrollWidth <= el.clientWidth + 1))
  const w0 = await page.getByTestId('sidebar').evaluate((el) => el.getBoundingClientRect().width)
  await h.shot(page, 'flows-light')
  await page.getByTestId('sidebar-toggle').click()
  await sleep(300)
  const collapsed = await page.getByTestId('sidebar').getAttribute('data-collapsed')
  const w1 = await page.getByTestId('sidebar').evaluate((el) => el.getBoundingClientRect().width)
  const stored = await page.evaluate(() => localStorage.getItem('vs.sidebar'))
  await page.getByTestId('nav-sources').hover()
  await sleep(350)
  const tipOpacity = await page.locator('[data-testid=nav-sources] .nav-tip').evaluate((el) => getComputedStyle(el).opacity)
  const tipText = await page.locator('[data-testid=nav-sources] .nav-tip').innerText()
  await h.shot(page, 'sidebar-collapsed')
  await page.reload()
  await page.getByTestId('sidebar').waitFor()
  const persisted = await page.getByTestId('sidebar').getAttribute('data-collapsed')
  await page.getByTestId('topbar-toggle').click()
  await sleep(300)
  const expanded = await page.getByTestId('sidebar').getAttribute('data-collapsed')
  const stored2 = await page.evaluate(() => localStorage.getItem('vs.sidebar'))
  h.item('S01', nowrap && w0 > 200 && collapsed === 'true' && w1 < 70 && stored === 'collapsed' && Number(tipOpacity) === 1 && tipText === '影像來源庫' && persisted === 'true' && expanded === 'false' && stored2 === 'expanded', `nowrap=${nowrap} w=${w0}->${w1} collapsed=${collapsed} stored=${stored} tip=${tipOpacity}/${tipText} persisted=${persisted} expanded=${expanded}/${stored2}`)
})

// ---------------------------------------------------------------- 各頁截圖（淺色）
await h.step('S02 各頁截圖（淺色）', async () => {
  const pages = [
    ['/', 'dashboard'],
    ['/sources', 'sources'],
    ['/assets', 'assets'],
    ['/integration', 'integration'],
    ['/connections', 'connections'],
    ['/users', 'users'],
    ['/settings', 'settings'],
    ['/help', 'help'],
    [`/flows/${flowId}/stats`, 'stats'],
    [`/flows/${flowId}/golden`, 'golden'],
  ]
  let ok = true
  for (const [route, name] of pages) {
    await page.goto(`${BASE}${route}`)
    await page.getByTestId('breadcrumb').waitFor()
    await sleep(900)
    const crumb = await page.getByTestId('breadcrumb').innerText()
    if (!crumb.trim()) ok = false
    await h.shot(page, name)
  }
  // 編輯器
  await page.goto(`${BASE}/flows/${flowId}`)
  await page.getByTestId('editor-toolbar').waitFor()
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await sleep(800)
  const crumb = await page.getByTestId('breadcrumb').innerText()
  await h.shot(page, 'editor')
  h.item('S02', ok && crumb.includes(FLOW_NAME), `crumb=${crumb}`)
})

// ---------------------------------------------------------------- 參數卡新版面
await h.step('S03 參數卡三欄版面', async () => {
  await page.goto(`${BASE}/flows/${flowId}/teach`)
  await page.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
  await page.getByTestId('teach-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
  await sleep(400)
  const steps = await page.getByTestId('teach-group').evaluateAll((els) => els.map((e) => e.getAttribute('data-node-id')))
  const focused0 = await page.locator('[data-testid=teach-params] section').getAttribute('data-node-id')
  const rows = await page.locator('[data-testid=teach-header] > div').count()
  const bound = await page.getByTestId('bound-badge').innerText()
  const dots = await page.locator('[data-testid=teach-status]').count()
  await h.shot(page, 'teach-three-columns')
  await page.locator('[data-testid=teach-group][data-node-id=blob]').click()
  await sleep(200)
  const focused1 = await page.locator('[data-testid=teach-params] section').getAttribute('data-node-id')
  const params = await page.locator('[data-testid=teach-params] [data-param]').evaluateAll((els) => els.map((e) => e.getAttribute('data-param')))
  const summary = await page.getByTestId('teach-outputs').innerText()
  await h.shot(page, 'teach-focus-blob')
  h.item('S03', steps.join(',') === 'thr,blob,cmp' && focused0 === 'thr' && rows === 2 && bound.includes('綁定') && dots === 3 && focused1 === 'blob' && params.join(',') === 'min_area,max_area,min_circularity' && /ms/.test(summary), `steps=${steps} focus=${focused0}->${focused1} rows=${rows} bound=${bound} params=${params} summary=${summary.slice(0, 40)}`)
})

// ---------------------------------------------------------------- 流程頁配方面板
const flowRow = () => page.locator('table tbody tr').filter({ hasText: FLOW_NAME }).first()
const drawer = () => page.getByTestId('recipe-drawer')
const recipeItem = (name) => drawer().locator('[data-testid=recipe-item]').filter({ hasText: name }).first()

await h.step('S04 新增配方 → Check List → 儲存', async () => {
  await page.goto(`${BASE}/flows`)
  await flowRow().waitFor({ timeout: 15000 })
  await flowRow().getByTestId('row-recipes').click()
  await drawer().waitFor()
  await page.getByTestId('recipe-new-name').fill('E2E partA')
  const fromGraph = await page.getByTestId('recipe-new-from-graph').isChecked()
  await page.getByTestId('recipe-create').click()
  await page.getByTestId('check-list').waitFor({ timeout: 10000 })
  const items = await page.locator('[data-testid=check-item]').evaluateAll((els) => els.map((e) => `${e.getAttribute('data-key')}:${e.getAttribute('data-status')}:${e.getAttribute('data-checked')}`))
  const count0 = await page.getByTestId('check-count').innerText()
  // 新配方的值與圖相同 → unchanged 預設不勾；全選後再存
  await page.getByTestId('check-list-all').check()
  const count1 = await page.getByTestId('check-count').innerText()
  await h.shot(page, 'recipe-checklist')
  await page.getByTestId('check-confirm').click()
  const toast = await h.toast(page, /已建立配方/)
  await recipeItem('E2E partA').waitFor({ timeout: 8000 })
  const bound = await recipeItem('E2E partA').getAttribute('data-bound')
  const list = await h.api.get(`/vision/flows/${flowId}/recipes`)
  const a = list.items.find((r) => r.name === 'E2E partA')
  await h.shot(page, 'recipe-drawer')
  h.item('S04', fromGraph && items.length >= 5 && items.every((s) => /:unchanged:false$/.test(s)) && /0 \//.test(count0) && !/^納入 0/.test(count1) && Boolean(toast) && bound === 'true' && a && a.is_default && Object.keys(a.param_overrides).length === 3, `fromGraph=${fromGraph} items=${items.join(' ')} count=${count0}->${count1} toast=${toast} bound=${bound} api=${JSON.stringify(a?.param_overrides)}`)
})

await h.step('S05 編輯值 → Check List（ok）→ 只存勾選', async () => {
  // 新增後面板會自動展開該配方；沒展開才點
  if ((await recipeItem('E2E partA').getByTestId('recipe-expand').getAttribute('aria-expanded')) !== 'true') await recipeItem('E2E partA').getByTestId('recipe-expand').click()
  await page.getByTestId('recipe-detail').waitFor()
  const first = page.getByTestId('recipe-value').first()
  await first.fill('77')
  await page.getByTestId('recipe-save').click()
  await page.getByTestId('check-list').waitFor({ timeout: 10000 })
  const items = await page.locator('[data-testid=check-item]').evaluateAll((els) => els.map((e) => `${e.getAttribute('data-key')}:${e.getAttribute('data-status')}:${e.getAttribute('data-checked')}`))
  await h.shot(page, 'recipe-checklist-ok')
  await page.getByTestId('check-confirm').click()
  const toast = await h.toast(page, /已更新配方/)
  const list = await h.api.get(`/vision/flows/${flowId}/recipes`)
  const a = list.items.find((r) => r.name === 'E2E partA')
  const okOnly = items.filter((s) => /:ok:true$/.test(s)).length === 1 && items.filter((s) => /:unchanged:false$/.test(s)).length === items.length - 1
  h.item('S05', okOnly && Boolean(toast) && a && Object.keys(a.param_overrides).length === 1 && a.param_overrides.thr?.threshold === 77, `items=${items.join(' ')} toast=${toast} api=${JSON.stringify(a?.param_overrides)}`)
})

await h.step('S06 第二個配方、改名、複製、設綁定、列上綁定下拉', async () => {
  await page.getByTestId('recipe-new-name').fill('E2E partB')
  await page.getByTestId('recipe-new-from-graph').uncheck()
  await page.getByTestId('recipe-create').click()
  await h.toast(page, /已建立配方/)
  await recipeItem('E2E partB').waitFor({ timeout: 8000 })
  await recipeItem('E2E partB').getByTestId('recipe-bind').click()
  const t1 = await h.toast(page, /已綁定配方/)
  await sleep(500)
  const boundB = await recipeItem('E2E partB').getAttribute('data-bound')
  await recipeItem('E2E partB').getByTestId('recipe-rename').click()
  await page.getByTestId('recipe-rename-input').fill('E2E partB2')
  await page.getByTestId('recipe-rename-save').click()
  const t2 = await h.toast(page, /已改名/)
  await recipeItem('E2E partB2').waitFor({ timeout: 8000 })
  await recipeItem('E2E partA').getByTestId('recipe-duplicate').click()
  const t3 = await h.toast(page, /已複製為/)
  await recipeItem('E2E partA (2)').waitFor({ timeout: 8000 })
  // 面板內綁定下拉 → 不用配方
  await page.getByTestId('drawer-bound').selectOption('')
  const t4 = await h.toast(page, /不用配方/)
  await sleep(500)
  const none = (await h.api.get(`/vision/flows/${flowId}/recipes`)).items.every((r) => !r.is_default)
  await h.shot(page, 'recipe-drawer-bound')
  await page.getByTestId('recipe-drawer-close').click()
  await sleep(300)
  // 列上的綁定下拉
  const sel = flowRow().locator(`[data-testid=row-bound-${flowId}]`)
  await sel.waitFor()
  const list = await h.api.get(`/vision/flows/${flowId}/recipes`)
  const a = list.items.find((r) => r.name === 'E2E partA')
  await sel.selectOption(String(a.id))
  const t5 = await h.toast(page, /已綁定配方「E2E partA」/)
  await sleep(600)
  const badge = await flowRow().getByTestId('bound-badge').innerText()
  const boundA = (await h.api.get(`/vision/flows/${flowId}/recipes`)).items.find((r) => r.is_default)?.name
  await h.shot(page, 'flows-bound')
  h.item('S06', Boolean(t1 && t2 && t3 && t4 && t5) && boundB === 'true' && none && badge.includes('E2E partA') && boundA === 'E2E partA', `t=${[t1, t2, t3, t4, t5].map(Boolean)} boundB=${boundB} none=${none} badge=${badge} boundA=${boundA}`)
})

let exportedPath = ''
await h.step('S07 匯出（單一／全部）', async () => {
  await flowRow().getByTestId('row-recipes').click()
  await drawer().waitFor()
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 10000 }), recipeItem('E2E partA').getByTestId('recipe-export').click()])
  exportedPath = path.join(SCRATCH, dl.suggestedFilename())
  await dl.saveAs(exportedPath)
  const doc = JSON.parse(fs.readFileSync(exportedPath, 'utf8'))
  const [dl2] = await Promise.all([page.waitForEvent('download', { timeout: 10000 }), page.getByTestId('recipe-export-all').click()])
  const allPath = path.join(SCRATCH, dl2.suggestedFilename())
  await dl2.saveAs(allPath)
  const all = JSON.parse(fs.readFileSync(allPath, 'utf8'))
  const t = await h.toast(page, /已下載/)
  h.item('S07', doc.kind === 'recipe' && doc.recipe?.name === 'E2E partA' && doc.flow_fingerprint && all.kind === 'recipes' && all.recipes.length >= 3 && Boolean(t), `file=${dl.suggestedFilename()} kind=${doc.kind} all=${all.recipes?.length} toast=${t}`)
})

await h.step('S08 匯入 → 合理化檢查 → 接受', async () => {
  const doc = JSON.parse(fs.readFileSync(exportedPath, 'utf8'))
  doc.recipe.name = 'E2E partC'
  // thr.threshold 99999 超過上限 → value_invalid；ghost_param → param_missing；ghost 節點 → node_missing；blob.min_area 12 → ok
  doc.recipe.param_overrides = { ...doc.recipe.param_overrides, thr: { threshold: 99999 }, blob: { min_area: 12, ghost_param: 1 }, ghost: { x: 1 } }
  doc.flow_name = '別的流程'
  const importPath = path.join(SCRATCH, 'e2e-partC.recipe.json')
  fs.writeFileSync(importPath, JSON.stringify(doc))
  await page.getByTestId('recipe-import').click()
  await page.getByTestId('recipe-import-input').setInputFiles(importPath)
  await page.getByTestId('import-check').waitFor({ timeout: 10000 })
  const badges = await page.locator('[data-testid=import-check] > div').first().innerText()
  const statuses = await page.locator('[data-testid=import-items] [data-testid=check-item]').evaluateAll((els) => els.map((e) => `${e.getAttribute('data-key')}:${e.getAttribute('data-status')}:${e.getAttribute('data-checked')}`))
  const disabledRed = await page.locator('[data-testid=import-items] [data-testid=check-item][data-status=node_missing] input, [data-testid=import-items] [data-testid=check-item][data-status=param_missing] input, [data-testid=import-items] [data-testid=check-item][data-status=value_invalid] input').evaluateAll((els) => els.every((e) => e.disabled))
  await h.shot(page, 'recipe-import-check')
  await page.getByTestId('import-run').click()
  const t = await h.toast(page, /已匯入/)
  await recipeItem('E2E partC').waitFor({ timeout: 8000 })
  const c = (await h.api.get(`/vision/flows/${flowId}/recipes`)).items.find((r) => r.name === 'E2E partC')
  await h.shot(page, 'recipe-imported')
  await page.getByTestId('recipe-drawer-close').click()
  const has = (st) => statuses.some((s) => s.includes(`:${st}:`))
  h.item('S08', badges.includes('流程名稱不同') && badges.includes('流程指紋相同') && has('ok') && has('node_missing') && has('param_missing') && has('value_invalid') && disabledRed && /寫入 \d+ 項、略過 \d+ 項/.test(t ?? '') && c && !c.param_overrides.thr && c.param_overrides.blob?.min_area === 12 && !c.param_overrides.ghost, `badges=${badges.replace(/\n/g, '|')} statuses=${statuses.join(' ')} red=${disabledRed} toast=${t} api=${JSON.stringify(c?.param_overrides)}`)
})

// ---------------------------------------------------------------- 參數卡：存為新配方走 Check List、管理配方開面板
await h.step('S09 參數卡存為新配方 → Check List', async () => {
  await page.goto(`${BASE}/flows/${flowId}/teach`)
  await page.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
  await page.getByTestId('teach-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
  const bound = await page.getByTestId('bound-badge').innerText()
  await page.getByTestId('teach-save-as').click()
  await page.getByTestId('teach-save-as-name').fill('E2E partT')
  await page.getByTestId('teach-save-as-confirm').click()
  await page.getByTestId('check-list').waitFor({ timeout: 10000 })
  const n = await page.locator('[data-testid=check-item]').count()
  await page.getByTestId('check-list-all').check()
  await page.getByTestId('check-confirm').click()
  const t = await h.toast(page, /已建立配方「E2E partT」/)
  await sleep(500)
  const sel = await page.getByTestId('teach-recipe').inputValue()
  const target = await page.locator('[data-testid=teach-recipe] option:checked').innerText()
  await page.getByTestId('teach-manage').click()
  await drawer().waitFor()
  const names = await drawer().locator('[data-testid=recipe-name]').allInnerTexts()
  await h.shot(page, 'teach-recipe-drawer')
  await page.getByTestId('recipe-drawer-close').click()
  h.item('S09', bound.includes('E2E partA') && n >= 5 && Boolean(t) && sel !== '' && target.includes('E2E partT') && names.includes('E2E partT'), `bound=${bound} n=${n} toast=${t} sel=${sel}/${target} names=${names}`)
})

// ---------------------------------------------------------------- 編輯器：綁定下拉、雙擊、拖移、Shift 框選
await h.step('S10 編輯器綁定下拉＋雙擊開工具頁', async () => {
  await page.evaluate(() => localStorage.removeItem('vs.canvasMode'))
  await page.goto(`${BASE}/flows/${flowId}`)
  await page.getByTestId('editor-toolbar').waitFor()
  await page.locator('.react-flow__node[data-id=thr]').waitFor({ timeout: 15000 })
  const sel = page.getByTestId('editor-recipe')
  const selText = await sel.locator('option:checked').innerText()
  const modePan = await page.locator('[aria-pressed=true]', { hasText: '平移' }).count()
  await sleep(500)
  await page.locator('.react-flow__node[data-id=thr]').dblclick()
  await page.waitForURL(/\/tools\/thr$/, { timeout: 8000 })
  await page.getByTestId('tool-page').waitFor()
  const syncSwitch = await page.getByText('同步視角').count()
  await h.shot(page, 'tool-page-after-dblclick')
  h.item('S10', selText === 'E2E partA' && modePan === 1 && syncSwitch === 0, `sel=${selText} pan=${modePan} sync=${syncSwitch}`)
})

await h.step('S11 工具頁前／後各自縮放', async () => {
  await page.getByTestId('tool-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
  await sleep(600)
  const b0 = await scaleOf('[data-testid=tool-before]')
  const a0 = await scaleOf('[data-testid=tool-after]')
  const box = await page.locator('[data-testid=tool-before] canvas').first().boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -600)
  await sleep(400)
  const b1 = await scaleOf('[data-testid=tool-before]')
  const a1 = await scaleOf('[data-testid=tool-after]')
  await h.shot(page, 'tool-independent-zoom')
  h.item('S11', b0 === a0 && b1 !== b0 && a1 === a0, `before ${b0}->${b1} after ${a0}->${a1}`)
})

await h.step('S12 畫布預設拖移、Shift 框選、模式存 localStorage', async () => {
  await page.goto(`${BASE}/flows/${flowId}`)
  await page.getByTestId('editor-toolbar').waitFor()
  await page.locator('.react-flow__node[data-id=thr]').waitFor({ timeout: 15000 })
  await sleep(600)
  const pane = page.locator('.react-flow__pane')
  const box = await pane.boundingBox()
  const tf = () => page.locator('.react-flow__viewport').evaluate((el) => el.style.transform)
  const t0 = await tf()
  // 從空白處拖曳 → 平移
  await page.mouse.move(box.x + 30, box.y + box.height - 30)
  await page.mouse.down()
  await page.mouse.move(box.x + 60, box.y + box.height - 60, { steps: 3 })
  await page.mouse.move(box.x + 150, box.y + box.height - 120, { steps: 6 })
  await page.mouse.up()
  await sleep(200)
  const t1 = await tf()
  const selectedAfterPan = await page.locator('.react-flow__node.selected').count()
  // Shift+拖曳 → 框選
  await page.keyboard.down('Shift')
  await page.mouse.move(box.x + 10, box.y + 10)
  await page.mouse.down()
  await page.mouse.move(box.x + 40, box.y + 40, { steps: 3 })
  await page.mouse.move(box.x + box.width - 10, box.y + box.height - 10, { steps: 8 })
  await page.mouse.up()
  await page.keyboard.up('Shift')
  await sleep(200)
  const selected = await page.locator('.react-flow__node.selected').count()
  const t2 = await tf()
  const delta = (a, b) => { const pa = /translate\(([-\d.]+)px, ([-\d.]+)px\)/.exec(a); const pb = /translate\(([-\d.]+)px, ([-\d.]+)px\)/.exec(b); return pa && pb ? Math.hypot(pa[1] - pb[1], pa[2] - pb[2]) : 999 }
  await h.shot(page, 'canvas-shift-select')
  // 切到選取模式 → localStorage
  await page.locator('[role=group] button', { hasText: '選取' }).click()
  const mode = await page.evaluate(() => localStorage.getItem('vs.canvasMode'))
  await page.reload()
  await page.getByTestId('editor-toolbar').waitFor()
  const pressed = await page.locator('[aria-pressed=true]', { hasText: '選取' }).count()
  await page.locator('[role=group] button', { hasText: '平移' }).click()
  const mode2 = await page.evaluate(() => localStorage.getItem('vs.canvasMode'))
  h.item('S12', delta(t0, t1) > 50 && selectedAfterPan === 0 && selected >= 2 && delta(t1, t2) < 10 && mode === 'select' && pressed === 1 && mode2 === 'pan', `tf ${t0} -> ${t1} -> ${t2} selPan=${selectedAfterPan} sel=${selected} mode=${mode}/${pressed}/${mode2}`)
})

await h.step('S13 編輯器前／後分割各自縮放', async () => {
  await page.getByTestId('btn-scratch').waitFor()
  const png = await h.makePng(page, { seed: 3 })
  await page.getByTestId('scratch-input').setInputFiles({ name: 'e2e-style.png', mimeType: 'image/png', buffer: png })
  await h.toast(page, /暫存影像/)
  await page.getByTestId('btn-preview').click()
  await h.toast(page, /試跑完成|OK|NG/)
  await page.locator('.react-flow__node[data-id=thr]').click()
  await page.getByTestId('btn-split').click()
  await page.getByTestId('viewer-after').waitFor()
  await sleep(600)
  const b0 = await scaleOf('[data-testid=viewer-main]')
  const a0 = await scaleOf('[data-testid=viewer-after]')
  const box = await page.locator('[data-testid=viewer-after] canvas').first().boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -600)
  await sleep(400)
  const b1 = await scaleOf('[data-testid=viewer-main]')
  const a1 = await scaleOf('[data-testid=viewer-after]')
  await h.shot(page, 'editor-split-independent-zoom')
  h.item('S13', a1 !== a0 && b1 === b0, `main ${b0}->${b1} after ${a0}->${a1}`)
})

// ---------------------------------------------------------------- 深色
await h.step('S14 深色截圖', async () => {
  const dark = await h.newContext({ token: h.token, colorScheme: 'dark' })
  await dark.addInitScript(() => localStorage.setItem('vs.theme', 'dark'))
  const p2 = await h.newPage(dark, '[dark]')
  let ok = true
  for (const [route, name, wait] of [
    ['/', 'dark-dashboard', 'breadcrumb'],
    ['/flows', 'dark-flows', 'breadcrumb'],
    [`/flows/${flowId}`, 'dark-editor', 'editor-toolbar'],
    [`/flows/${flowId}/teach`, 'dark-teach', 'teach-group'],
    [`/flows/${flowId}/stats`, 'dark-stats', 'breadcrumb'],
  ]) {
    await p2.goto(`${BASE}${route}`)
    await p2.getByTestId(wait).first().waitFor({ timeout: 15000 })
    await sleep(1000)
    const isDark = await p2.evaluate(() => document.documentElement.classList.contains('dark'))
    const bg = await p2.evaluate(() => getComputedStyle(document.querySelector('[data-testid=sidebar]')).backgroundColor)
    if (!isDark || bg === 'rgb(42, 63, 84)') ok = false
    await h.shot(p2, name)
  }
  await p2.getByTestId('sidebar-toggle').click()
  await sleep(300)
  await h.shot(p2, 'dark-sidebar-collapsed')
  await dark.close()
  h.currentPage = page
  h.item('S14', ok, 'dark class or sidebar colour wrong')
})

// ---------------------------------------------------------------- 收尾
try {
  await h.api.del(`/vision/flows/${flowId}`)
  const now = await h.api.get('/vision/flows')
  for (const f of now?.items ?? []) if (/^E2E 風格/.test(f.name)) await h.api.del(`/vision/flows/${f.id}`)
  // 示範流程上不應有殘留，但保險
  for (const r of (await h.api.get(`/vision/flows/${demo.id}/recipes`))?.items ?? []) if (/^E2E /.test(r.name)) await h.api.del(`/vision/flows/${demo.id}/recipes/${r.id}`)
} catch (e) {
  h.note(`[cleanup] ${e.message}`)
}
await h.close()

console.log('\n===== 結果 =====')
for (const [id, r] of Object.entries(h.results)) console.log(`${r.ok ? 'PASS' : 'FAIL'} ${id}${r.ok ? '' : ` — ${r.note}`}`)
console.log(`截圖 ${h.shots.length} 張；console/pageerror/HTTP 問題 ${h.issues.length} 筆`)
for (const i of h.issues) console.log(' -', i)
fs.writeFileSync(path.join(SCRATCH, 'style-results.json'), JSON.stringify({ results: h.results, issues: h.issues, shots: h.shots }, null, 2))
process.exit(h.issues.length ? 1 : 0)
