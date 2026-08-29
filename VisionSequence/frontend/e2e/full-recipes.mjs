/**
 * 模組 recipes：配方面板（RC）——流程頁綁定欄與「配方」鈕、側滑面板每個按鈕：新增（Check List）／改名／複製／刪除／設綁定／
 * 匯出／全部匯出／匯入→合理化檢查→接受、展開編輯覆寫表→Check List 只存勾選、面板內綁定下拉、關閉（X／遮罩）、
 * 總覽卡片與統計頁的綁定配方、worker 唯讀。
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { BASE, WORKER } from './full-lib.mjs'
import { ensureWorker } from './full-teach.mjs'

export async function run(h) {
  await h.loginAdmin()
  await h.api.del('/vision/lock')
  await ensureWorker(h)
  const context = await h.newContext({ token: h.token })
  const page = await h.newPage(context, '[recipes]')
  const flowId = await h.cloneDemo('E2E 配方面板')
  const FLOW_NAME = 'E2E 配方面板'
  const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'vs-recipes-'))
  const flowRow = () => page.locator('table tbody tr').filter({ hasText: FLOW_NAME }).first()
  const drawer = () => page.getByTestId('recipe-drawer')
  const item = (name) => drawer().locator('[data-testid=recipe-item]').filter({ hasText: name }).first()
  const recipesOf = async () => (await h.api.get(`/vision/flows/${flowId}/recipes`)).items
  const gotoFlows = async () => {
    await page.goto(`${BASE}/flows`)
    await flowRow().waitFor({ timeout: 15000 })
  }
  const openDrawer = async () => {
    await flowRow().getByTestId('row-recipes').click()
    await drawer().waitFor({ timeout: 5000 })
  }
  const checkItems = () => page.locator('[data-testid=check-item]').evaluateAll((els) => els.map((e) => `${e.getAttribute('data-key')}:${e.getAttribute('data-status')}:${e.getAttribute('data-checked')}`))

  await h.step('RC01 流程頁綁定欄（無配方）與面板開關', async () => {
    await gotoFlows()
    const head = await page.locator('thead').innerText()
    const cell = flowRow().locator('td').nth(6)
    const dash = (await cell.innerText()).includes('—')
    const btn = await flowRow().getByTestId('row-recipes').innerText()
    const noBadge = (await flowRow().getByTestId('bound-badge').count()) === 0
    // 點「配方」鈕不會觸發列導覽
    await openDrawer()
    const stillList = /\/flows$/.test(page.url())
    await drawer().locator('header').filter({ hasText: FLOW_NAME }).waitFor({ timeout: 5000 }).catch(() => null)
    const title = await drawer().locator('header').innerText()
    const empty = (await drawer().getByTestId('recipe-list').innerText()).includes('還沒有配方')
    const boundOpts = await page.getByTestId('drawer-bound').locator('option').allInnerTexts()
    const exportAllDis = await page.getByTestId('recipe-export-all').isDisabled()
    const fromGraphTxt = await drawer().locator('[data-testid=recipe-new] label').filter({ has: page.getByTestId('recipe-new-from-graph') }).innerText()
    await h.shot(page, 'recipes-drawer-empty')
    // X 關閉；再開、點遮罩關閉
    await page.getByTestId('recipe-drawer-close').click()
    const closedX = await h.waitGone(drawer())
    await openDrawer()
    await page.mouse.click(20, 500)
    const closedMask = await h.waitGone(drawer())
    h.item('RC01', head.includes('綁定') && dash && btn.trim() === '配方' && noBadge && stillList && title.includes('配方') && title.includes(FLOW_NAME) && title.includes('0 個配方') && empty && boundOpts.length === 1 && boundOpts[0].includes('不用配方') && exportAllDis && /5 項/.test(fromGraphTxt) && closedX && closedMask, `head=${head.replace(/\n/g, '|')} dash=${dash} btn=${btn} noBadge=${noBadge} url=${page.url()} title=${title.replace(/\n/g, '|')} empty=${empty} boundOpts=${boundOpts} exportAllDis=${exportAllDis} fromGraph=${fromGraphTxt} closed=${closedX}/${closedMask}`)
  })

  await h.step('RC02 新增（以圖值）→ Check List → 建立、自動綁定、自動展開', async () => {
    await openDrawer()
    await page.getByTestId('recipe-create').click()
    const tEmpty = await h.toast(page, /請輸入名稱/)
    await page.getByTestId('recipe-new-name').fill('E2E partA')
    const fromGraph = await page.getByTestId('recipe-new-from-graph').isChecked()
    await page.getByTestId('recipe-create').click()
    await page.getByTestId('check-list').waitFor({ timeout: 10000 })
    const title = await h.dialog(page).locator('h2').innerText()
    const items = await checkItems()
    const count0 = await page.getByTestId('check-count').innerText()
    const cols = await page.locator('[data-testid=check-list] thead').innerText()
    // 點列切換勾選；全選；再全不選；最後全選
    await page.locator('[data-testid=check-item]').first().click()
    const oneOn = (await page.locator('[data-testid=check-item][data-checked=true]').count()) === 1
    await page.getByTestId('check-list-all').check()
    const count1 = await page.getByTestId('check-count').innerText()
    await page.getByTestId('check-list-all').uncheck()
    const noneOn = (await page.locator('[data-testid=check-item][data-checked=true]').count()) === 0
    await page.getByTestId('check-list-all').check()
    await h.shot(page, 'recipes-checklist-create')
    // 取消不會建立
    await h.dialog(page).getByRole('button', { name: '取消' }).click()
    await h.waitGone(page.getByTestId('check-list'))
    const notCreated = (await recipesOf()).length === 0
    await page.getByTestId('recipe-create').click()
    await page.getByTestId('check-list').waitFor({ timeout: 10000 })
    await page.getByTestId('check-list-all').check()
    await page.getByTestId('check-confirm').click()
    const t = await h.toast(page, /已建立配方「E2E partA」/)
    await item('E2E partA').waitFor({ timeout: 8000 })
    const bound = await item('E2E partA').getAttribute('data-bound')
    const expanded = (await item('E2E partA').getByTestId('recipe-detail').count()) === 1
    const nameCleared = (await page.getByTestId('recipe-new-name').inputValue()) === ''
    const a = (await recipesOf()).find((r) => r.name === 'E2E partA')
    const countTxt = await item('E2E partA').innerText()
    const headerCount = (await drawer().locator('header').innerText()).includes('1 個配方')
    await h.shot(page, 'recipes-created')
    h.item('RC02', Boolean(tEmpty) && fromGraph && title.includes('E2E partA') && title.includes('Check List') && items.length === 5 && items.every((s) => /:unchanged:false$/.test(s)) && /納入 0 \/ 5/.test(count0) && cols.includes('步驟 › 參數') && cols.includes('目前值 → 新值') && cols.includes('狀態') && oneOn && /納入 5 \/ 5/.test(count1) && noneOn && notCreated && Boolean(t) && bound === 'true' && expanded && nameCleared && a && a.is_default && Object.keys(a.param_overrides).length === 3 && countTxt.includes('5 個覆寫') && countTxt.includes('綁定') && headerCount, `empty=${tEmpty} fromGraph=${fromGraph} title=${title} items=${items.join(' ')} count=${count0}/${count1} cols=${cols.replace(/\n/g, '|')} oneOn=${oneOn} noneOn=${noneOn} notCreated=${notCreated} toast=${t} bound=${bound} expanded=${expanded} nameCleared=${nameCleared} api=${JSON.stringify(a?.param_overrides)} txt=${countTxt.replace(/\n/g, ' ')} headerCount=${headerCount}`)
  })

  await h.step('RC03 展開編輯覆寫表 → Check List（ok）→ 只存勾選', async () => {
    if ((await item('E2E partA').getByTestId('recipe-detail').count()) === 0) await item('E2E partA').getByTestId('recipe-expand').click()
    const detail = item('E2E partA').getByTestId('recipe-detail')
    await detail.waitFor()
    const ariaExpanded = await item('E2E partA').getByTestId('recipe-expand').getAttribute('aria-expanded')
    const rows0 = await detail.getByTestId('recipe-overrides').locator('tbody tr').count()
    const nodeOpts = await detail.getByTestId('recipe-overrides').locator('tbody tr').first().locator('select').first().locator('option').allInnerTexts()
    const paramOpts = await detail.getByTestId('recipe-overrides').locator('tbody tr').first().locator('select').nth(1).locator('option').allInnerTexts()
    const graphHint = (await detail.getByTestId('recipe-overrides').locator('tbody tr').first().innerText()).includes('圖值')
    const saveBefore = await detail.getByTestId('recipe-save').evaluate((el) => el.className.includes('primary') || el.className.includes('bg-brand'))
    await detail.getByTestId('recipe-value').first().fill('77')
    const savePrimary = await detail.getByTestId('recipe-save').evaluate((el) => el.className.includes('primary') || el.className.includes('bg-brand'))
    // 新增一列（節點下拉預設第一個、參數空）→ 移除
    await detail.getByTestId('recipe-add-row').click()
    const rows1 = await detail.getByTestId('recipe-overrides').locator('tbody tr').count()
    await detail.getByTestId('recipe-overrides').locator('tbody tr').last().getByTitle('移除').click()
    const rows2 = await detail.getByTestId('recipe-overrides').locator('tbody tr').count()
    await h.shot(page, 'recipes-edit-overrides')
    await detail.getByTestId('recipe-save').click()
    await page.getByTestId('check-list').waitFor({ timeout: 10000 })
    const title = await h.dialog(page).locator('h2').innerText()
    const items = await checkItems()
    const change = await page.locator('[data-testid=check-item][data-key="thr.threshold"] td').nth(2).innerText()
    const count = await page.getByTestId('check-count').innerText()
    await h.shot(page, 'recipes-checklist-ok')
    await page.getByTestId('check-confirm').click()
    const t = await h.toast(page, /已更新配方「E2E partA」/)
    await page.waitForTimeout(500)
    const a = (await recipesOf()).find((r) => r.name === 'E2E partA')
    const okOnly = items.filter((s) => /^thr\.threshold:ok:true$/.test(s)).length === 1 && items.filter((s) => /:unchanged:false$/.test(s)).length === items.length - 1
    const countTxt = await item('E2E partA').innerText()
    h.item('RC03', ariaExpanded === 'true' && rows0 === 5 && nodeOpts.length >= 3 && nodeOpts.some((o) => o.includes('(thr)')) && paramOpts.some((o) => o.includes('★')) && graphHint && !saveBefore && savePrimary && rows1 === 6 && rows2 === 5 && title.includes('儲存配方「E2E partA」') && okOnly && change.includes('77') && /納入 1 \/ 5/.test(count) && Boolean(t) && a && Object.keys(a.param_overrides).length === 1 && a.param_overrides.thr?.threshold === 77 && countTxt.includes('1 個覆寫'), `expanded=${ariaExpanded} rows=${rows0}/${rows1}/${rows2} nodeOpts=${nodeOpts.slice(0, 3)} paramOpts=${paramOpts.slice(0, 2)} graphHint=${graphHint} primary=${saveBefore}->${savePrimary} title=${title} items=${items.join(' ')} change=${change} count=${count} toast=${t} api=${JSON.stringify(a?.param_overrides)} txt=${countTxt.replace(/\n/g, ' ').slice(0, 60)}`)
  })

  await h.step('RC04 改名（Enter／✓／Esc 取消）', async () => {
    await item('E2E partA').getByTestId('recipe-rename').click()
    const input = page.getByTestId('recipe-rename-input')
    const prefilled = await input.inputValue()
    await input.fill('E2E partA-x')
    await page.keyboard.press('Escape')
    const cancelled = (await page.getByTestId('recipe-rename-input').count()) === 0 && (await item('E2E partA').getByTestId('recipe-name').innerText()) === 'E2E partA'
    await item('E2E partA').getByTestId('recipe-rename').click()
    await page.getByTestId('recipe-rename-input').fill('E2E partA2')
    await page.getByTestId('recipe-rename-save').click()
    const t1 = await h.toast(page, /已改名為「E2E partA2」/)
    await item('E2E partA2').waitFor({ timeout: 8000 })
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    await item('E2E partA2').getByTestId('recipe-rename').click()
    await page.getByTestId('recipe-rename-input').fill('E2E partA')
    await page.keyboard.press('Enter')
    const t2 = await h.toast(page, /已改名為「E2E partA」/)
    await item('E2E partA').waitFor({ timeout: 8000 })
    const api = (await recipesOf()).map((r) => r.name)
    h.item('RC04', prefilled === 'E2E partA' && cancelled && Boolean(t1) && Boolean(t2) && api.includes('E2E partA') && !api.includes('E2E partA2'), `prefilled=${prefilled} cancelled=${cancelled} t1=${t1} t2=${t2} api=${api}`)
  })

  await h.step('RC05 第二個配方（不以圖值）、複製、設綁定、面板綁定下拉', async () => {
    await page.getByTestId('recipe-new-name').fill('E2E partB')
    await page.getByTestId('recipe-new-from-graph').uncheck()
    await page.getByTestId('recipe-create').click()
    // 不以圖值 → 沒有 Check List，直接建立
    const t0 = await h.toast(page, /已建立配方「E2E partB」/)
    const noCheck = (await page.getByTestId('check-list').count()) === 0
    await item('E2E partB').waitFor({ timeout: 8000 })
    const bNotBound = (await item('E2E partB').getAttribute('data-bound')) === 'false'
    const bZero = (await item('E2E partB').innerText()).includes('0 個覆寫')
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    // 複製 partA → 「E2E partA (2)」帶相同覆寫
    await item('E2E partA').getByTestId('recipe-duplicate').click()
    const t1 = await h.toast(page, /已複製為「E2E partA \(2\)」/)
    await item('E2E partA (2)').waitFor({ timeout: 8000 })
    const dup = (await recipesOf()).find((r) => r.name === 'E2E partA (2)')
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    // 設綁定 partB → partA 的綁定 badge 消失
    await item('E2E partB').getByTestId('recipe-bind').click()
    const t2 = await h.toast(page, /已綁定配方「E2E partB」/)
    await page.waitForTimeout(500)
    const boundB = await item('E2E partB').getAttribute('data-bound')
    const boundA = await item('E2E partA').getAttribute('data-bound')
    const noBindBtnOnBound = (await item('E2E partB').getByTestId('recipe-bind').count()) === 0
    const sel = await page.getByTestId('drawer-bound').locator('option:checked').innerText()
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    // 面板下拉 → 不用配方
    await page.getByTestId('drawer-bound').selectOption('')
    const t3 = await h.toast(page, /已改為不用配方/)
    await page.waitForTimeout(500)
    const none = (await recipesOf()).every((r) => !r.is_default)
    const noneBadge = (await drawer().locator('[data-testid=recipe-item][data-bound=true]').count()) === 0
    await h.shot(page, 'recipes-drawer-three')
    h.item('RC05', Boolean(t0) && noCheck && bNotBound && bZero && Boolean(t1) && dup && dup.param_overrides.thr?.threshold === 77 && !dup.is_default && Boolean(t2) && boundB === 'true' && boundA === 'false' && noBindBtnOnBound && sel === 'E2E partB' && Boolean(t3) && none && noneBadge, `t0=${t0} noCheck=${noCheck} b=${bNotBound}/${bZero} t1=${t1} dup=${JSON.stringify(dup?.param_overrides)} t2=${t2} bound=${boundB}/${boundA} noBindBtn=${noBindBtnOnBound} sel=${sel} t3=${t3} none=${none}/${noneBadge}`)
  })

  await h.step('RC06 列上綁定下拉與「綁定：」標籤、總覽卡片、統計頁', async () => {
    await page.getByTestId('recipe-drawer-close').click()
    await h.waitGone(drawer())
    const sel = flowRow().locator(`[data-testid=row-bound-${flowId}]`)
    await sel.waitFor({ timeout: 5000 })
    const opts = await sel.locator('option').allInnerTexts()
    const badge0 = await flowRow().getByTestId('bound-badge').innerText()
    const btn = await flowRow().getByTestId('row-recipes').innerText()
    const a = (await recipesOf()).find((r) => r.name === 'E2E partA')
    await sel.selectOption(String(a.id))
    const t = await h.toast(page, /已綁定配方「E2E partA」/)
    await page.waitForTimeout(600)
    const badge1 = await flowRow().getByTestId('bound-badge').innerText()
    const bound = (await recipesOf()).find((r) => r.is_default)?.name
    const stillList = /\/flows$/.test(page.url())
    await h.shot(page, 'recipes-flows-bound')
    // 執行一次 → 用綁定配方；總覽卡片 card-meta、統計頁副標
    await h.api.post(`/vision/flows/${flowId}/run?wait=1`, { context: null, wait: true })
    const last = (await h.api.get(`/vision/flows/${flowId}/recent?limit=1`)).items[0]
    await page.goto(`${BASE}/`)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(800)
    const meta = await page.locator('main a.card').filter({ hasText: FLOW_NAME }).getByTestId('card-meta').innerText().catch(() => '')
    await page.goto(`${BASE}/flows/${flowId}/stats`)
    await page.getByTestId('stats-kpi').waitFor({ timeout: 15000 })
    await page.waitForTimeout(400)
    const header = await page.locator('main').locator('h1').first().locator('xpath=..').innerText()
    h.item('RC06', opts.length === 4 && opts[0].includes('不用配方') && badge0.includes('綁定：圖值') && btn.includes('配方 (3)') && Boolean(t) && badge1.includes('綁定：E2E partA') && bound === 'E2E partA' && stillList && last?.recipe === 'E2E partA' && meta.includes('配方') && meta.includes('E2E partA') && header.includes('E2E partA'), `opts=${opts.join('/')} badge=${badge0}->${badge1} btn=${btn} t=${t} bound=${bound} url=${page.url()} run.recipe=${last?.recipe} meta=${meta.replace(/\n/g, ' ')} header=${header.replace(/\n/g, ' ').slice(0, 80)}`)
  })

  let exportedPath = ''
  await h.step('RC07 匯出（單一／全部）', async () => {
    await gotoFlows()
    await openDrawer()
    const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 10000 }), item('E2E partA').getByTestId('recipe-export').click()])
    const t1 = await h.toast(page, /已下載配方「E2E partA」/)
    exportedPath = path.join(TMP, dl.suggestedFilename())
    await dl.saveAs(exportedPath)
    const doc = JSON.parse(fs.readFileSync(exportedPath, 'utf8'))
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    const [dl2] = await Promise.all([page.waitForEvent('download', { timeout: 10000 }), page.getByTestId('recipe-export-all').click()])
    const t2 = await h.toast(page, /已下載 3 個配方/)
    const allPath = path.join(TMP, dl2.suggestedFilename())
    await dl2.saveAs(allPath)
    const all = JSON.parse(fs.readFileSync(allPath, 'utf8'))
    h.item('RC07', dl.suggestedFilename() === `${FLOW_NAME}.E2E partA.recipe.json` && Boolean(t1) && doc.kind === 'recipe' && doc.recipe?.name === 'E2E partA' && doc.recipe?.param_overrides?.thr?.threshold === 77 && doc.flow_fingerprint && doc.flow_name === FLOW_NAME && dl2.suggestedFilename() === `${FLOW_NAME}.recipes.json` && Boolean(t2) && all.kind === 'recipes' && all.recipes.length === 3, `file=${dl.suggestedFilename()} t1=${t1} kind=${doc.kind} name=${doc.recipe?.name} fp=${Boolean(doc.flow_fingerprint)} file2=${dl2.suggestedFilename()} t2=${t2} all=${all.kind}/${all.recipes?.length}`)
  })

  await h.step('RC08 匯入 → 合理化檢查 → 接受', async () => {
    const doc = JSON.parse(fs.readFileSync(exportedPath, 'utf8'))
    doc.recipe.name = 'E2E partC'
    // thr.threshold 99999 超過上限 → value_invalid；ghost_param → param_missing；ghost 節點 → node_missing；blob.min_area 12 → ok；cmp.threshold 與圖相同 → unchanged
    const cmpThreshold = (await h.api.get(`/vision/flows/${flowId}`)).graph.nodes.find((n) => n.id === 'cmp').params.threshold
    doc.recipe.param_overrides = { thr: { threshold: 99999 }, blob: { min_area: 12, ghost_param: 1 }, cmp: { threshold: cmpThreshold }, ghost: { x: 1 } }
    doc.flow_name = '別的流程'
    const importPath = path.join(TMP, 'e2e-partC.recipe.json')
    fs.writeFileSync(importPath, JSON.stringify(doc))
    await page.getByTestId('recipe-import').click()
    const dlg = h.dialog(page)
    await dlg.waitFor()
    const title = await dlg.locator('h2').innerText()
    const runDisabled = await page.getByTestId('import-run').isDisabled()
    await page.getByTestId('recipe-import-input').setInputFiles(importPath)
    await page.getByTestId('import-check').waitFor({ timeout: 10000 })
    const fileShown = (await dlg.innerText()).includes('e2e-partC.recipe.json')
    const badges = await page.locator('[data-testid=import-check] > div').first().innerText()
    const recipeHdr = await page.locator('[data-testid=import-recipe] > p').first().innerText()
    const statuses = await page.locator('[data-testid=import-items] [data-testid=check-item]').evaluateAll((els) => els.map((e) => `${e.getAttribute('data-key')}:${e.getAttribute('data-status')}:${e.getAttribute('data-checked')}`))
    const redDisabled = await page.locator('[data-testid=import-items] [data-testid=check-item][data-status=node_missing] input, [data-testid=import-items] [data-testid=check-item][data-status=param_missing] input, [data-testid=import-items] [data-testid=check-item][data-status=value_invalid] input').evaluateAll((els) => els.length > 0 && els.every((e) => e.disabled))
    const count0 = await page.getByTestId('import-count').innerText()
    // 把 unchanged（cmp.threshold）也勾起來、勾「匯入後設為綁定配方」
    await page.locator('[data-testid=import-items] [data-testid=check-item][data-status=unchanged]').first().click()
    const count1 = await page.getByTestId('import-count').innerText()
    await page.getByTestId('import-bind').check()
    await h.shot(page, 'recipes-import-check')
    await page.getByTestId('import-run').click()
    const t = await h.toast(page, /已匯入 1 個配方/)
    await item('E2E partC').waitFor({ timeout: 8000 })
    const c = (await recipesOf()).find((r) => r.name === 'E2E partC')
    const boundC = await item('E2E partC').getAttribute('data-bound')
    await h.shot(page, 'recipes-imported')
    // 同名再匯入 → 「會覆寫既有同名配方」
    await page.getByTestId('recipe-import').click()
    await h.dialog(page).waitFor()
    await page.getByTestId('recipe-import-input').setInputFiles(importPath)
    await page.getByTestId('import-check').waitFor({ timeout: 10000 })
    const exists = (await page.locator('[data-testid=import-recipe] > p').first().innerText()).includes('會覆寫既有同名配方')
    await h.dialog(page).getByRole('button', { name: '取消' }).click()
    await h.waitGone(page.getByTestId('import-check'))
    const has = (st) => statuses.some((s) => s.includes(`:${st}:`))
    h.item('RC08', title.includes('匯入配方') && runDisabled && fileShown && badges.includes('流程名稱不同') && badges.includes('別的流程') && badges.includes('流程指紋相同') && recipeHdr.includes('E2E partC') && recipeHdr.includes('新建') && /2 \/ 5 項可寫入/.test(recipeHdr) && has('ok') && has('unchanged') && has('node_missing') && has('param_missing') && has('value_invalid') && redDisabled && /納入 1 \/ 2/.test(count0) && /納入 2 \/ 2/.test(count1) && /寫入 2 項、略過 \d+ 項/.test(t ?? '') && c && c.param_overrides.blob?.min_area === 12 && c.param_overrides.cmp?.threshold === cmpThreshold && !c.param_overrides.thr && !c.param_overrides.ghost && c.is_default && boundC === 'true' && exists, `title=${title} runDisabled=${runDisabled} file=${fileShown} badges=${badges.replace(/\n/g, '|')} hdr=${recipeHdr.replace(/\n/g, ' ')} statuses=${statuses.join(' ')} red=${redDisabled} count=${count0}->${count1} toast=${t} api=${JSON.stringify(c?.param_overrides)} default=${c?.is_default}/${boundC} exists=${exists}`)
  })

  await h.step('RC09 刪除 → ConfirmDialog → toast', async () => {
    const n0 = await page.getByTestId('recipe-item').count()
    await item('E2E partA (2)').getByTestId('recipe-delete').click()
    const confirm = page.locator('[role=dialog]').filter({ hasText: '刪除配方' }).last()
    const msg = await confirm.innerText()
    const danger = (await confirm.locator('button.bg-critical').count()) === 1
    await confirm.getByRole('button', { name: '取消' }).click()
    await h.waitGone(confirm)
    const kept = (await page.getByTestId('recipe-item').count()) === n0
    await item('E2E partA (2)').getByTestId('recipe-delete').click()
    await page.locator('[role=dialog]').filter({ hasText: '刪除配方' }).last().getByRole('button', { name: '刪除', exact: true }).click()
    const t = await h.toast(page, /已刪除配方/)
    await page.waitForTimeout(500)
    const n1 = await page.getByTestId('recipe-item').count()
    const gone = !(await recipesOf()).some((r) => r.name === 'E2E partA (2)')
    const headerCount = (await drawer().locator('header').innerText()).includes(`${n1} 個配方`)
    h.item('RC09', n0 === 4 && msg.includes('E2E partA (2)') && danger && kept && Boolean(t) && n1 === 3 && gone && headerCount, `n=${n0}->${n1} msg=${msg.replace(/\n/g, ' ').slice(0, 60)} danger=${danger} kept=${kept} t=${t} gone=${gone} headerCount=${headerCount}`)
  })

  await h.step('RC10 匯入錯誤檔／同名新增 → 錯誤 toast', async () => {
    const bad = path.join(TMP, 'bad.json')
    fs.writeFileSync(bad, '{not json')
    await page.getByTestId('recipe-import').click()
    await h.dialog(page).waitFor()
    await page.getByTestId('recipe-import-input').setInputFiles(bad)
    const tBad = await h.toast(page, /./, 4000)
    const runDisabled = await page.getByTestId('import-run').isDisabled()
    await h.dialog(page).getByRole('button', { name: '取消' }).click()
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    const un = h.allowStatus(/409 POST .*\/recipes/)
    await page.getByTestId('recipe-new-name').fill('E2E partB')
    await page.getByTestId('recipe-new-from-graph').uncheck().catch(() => null)
    await page.getByTestId('recipe-create').click()
    const tDup = await h.toast(page, /同名/, 4000)
    un()
    h.item('RC10', Boolean(tBad) && runDisabled && Boolean(tDup), `bad=${tBad} runDisabled=${runDisabled} dup=${tDup}`)
  })

  await h.step('RC11 參數卡：存為新配方走 Check List、管理配方開同一面板、綁定標籤', async () => {
    await page.goto(`${BASE}/flows/${flowId}/teach`)
    await page.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
    await page.getByTestId('teach-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
    const bound = await page.getByTestId('bound-badge').innerText()
    const opts = await page.locator('[data-testid=teach-recipe] option').allInnerTexts()
    await page.getByTestId('teach-save-as').click()
    await page.getByTestId('teach-save-as-name').fill('E2E partT')
    await page.getByTestId('teach-save-as-confirm').click()
    await page.getByTestId('check-list').waitFor({ timeout: 10000 })
    const n = await page.locator('[data-testid=check-item]').count()
    await page.getByTestId('check-list-all').check()
    await page.getByTestId('check-confirm').click()
    const t = await h.toast(page, /已建立配方「E2E partT」/)
    await page.waitForTimeout(500)
    const target = await page.locator('[data-testid=teach-recipe] option:checked').innerText()
    const overrideCount = await page.getByTestId('teach-override-count').innerText()
    await page.getByTestId('teach-manage').click()
    await drawer().waitFor()
    const names = await drawer().locator('[data-testid=recipe-name]').allInnerTexts()
    const graphBtn = (await drawer().innerText()).includes('新增配方')
    await h.shot(page, 'recipes-teach-drawer')
    await page.getByTestId('recipe-drawer-close').click()
    h.item('RC11', bound.includes('綁定：E2E partC') && opts.some((o) => o.includes('E2E partC') && o.includes('綁定')) && n === 5 && Boolean(t) && target === 'E2E partT' && overrideCount.includes('5 個覆寫') && names.includes('E2E partT') && names.length === 4 && graphBtn, `bound=${bound} opts=${opts.join('/')} n=${n} toast=${t} target=${target} count=${overrideCount} names=${names}`)
  })

  await h.step('RC13 Check List 兩區：教導參數／其他參數（展開勾選）、fromGraph 文案', async () => {
    await gotoFlows()
    await openDrawer()
    const fromGraphTxt = await drawer().locator('[data-testid=recipe-new] label').filter({ has: page.getByTestId('recipe-new-from-graph') }).innerText()
    if (!(await page.getByTestId('recipe-new-from-graph').isChecked())) await page.getByTestId('recipe-new-from-graph').check()
    await page.getByTestId('recipe-new-name').fill('E2E partO')
    await page.getByTestId('recipe-create').click()
    await page.getByTestId('check-list').waitFor({ timeout: 10000 })
    const teachHdr = await page.getByTestId('check-teach').locator('p').first().innerText()
    const teachItems = await checkItems()
    const teachOnly = teachItems.length === 5 && teachItems.every((s) => /:unchanged:false$/.test(s))
    const collapsed = (await page.getByTestId('check-list-others').count()) === 0
    const toggleTxt = await page.getByTestId('check-others-toggle').innerText()
    const n = Number(/其他參數（(\d+)）/.exec(toggleTxt)?.[1] ?? 0)
    await page.getByTestId('check-others-toggle').click()
    await page.getByTestId('check-list-others').waitFor({ timeout: 3000 })
    const others = await page.locator('[data-testid=check-list-others] [data-testid=check-item]').evaluateAll((els) => els.map((e) => `${e.getAttribute('data-key')}:${e.getAttribute('data-status')}:${e.getAttribute('data-checked')}:${e.getAttribute('data-teach')}`))
    const othersUnchecked = others.length === n && n > 0 && others.every((s) => /:unchanged:false:false$/.test(s))
    const stillTeach = (await page.locator('[data-testid=check-teach] [data-testid=check-item]').count()) === 5
    // ROI 類值顯示摘要（示範流程若有 roi 參數）
    const roiTxt = await page.locator('[data-testid=check-list-others] [data-testid=check-item]').evaluateAll((els) => els.map((e) => e.innerText).filter((t) => /(rect|circle|polygon|line|rotated_rect|annulus) /.test(t)))
    const roiSummary = roiTxt.length === 0 || roiTxt.every((t) => /rect \d+×\d+ @ \d+,\d+|circle r=\d+|polygon \d+ pts|line \d+,\d+|rotated_rect \d+×\d+|annulus r=/.test(t))
    // 勾第一個其他參數 → 計數文字多「其他參數 1 項」
    const first = page.locator('[data-testid=check-list-others] [data-testid=check-item]').first()
    const firstKey = await first.getAttribute('data-key')
    await first.click()
    const count = await page.getByTestId('check-count').innerText()
    const teachStillZero = (await page.locator('[data-testid=check-teach] [data-testid=check-item][data-checked=true]').count()) === 0
    await h.shot(page, 'recipes-checklist-others')
    await page.getByTestId('check-confirm').click()
    const t = await h.toast(page, /已建立配方「E2E partO」/)
    await page.waitForTimeout(500)
    const o = (await recipesOf()).find((r) => r.name === 'E2E partO')
    const [nid, pkey] = (firstKey ?? '.').split('.')
    const apiHas = Boolean(o) && Object.keys(o.param_overrides).length === 1 && o.param_overrides[nid] && Object.keys(o.param_overrides[nid]).length === 1 && pkey in o.param_overrides[nid]
    await page.getByTestId('recipe-drawer-close').click()
    h.item('RC13', fromGraphTxt.includes('以目前圖值作為覆寫（教導參數') && teachHdr.includes('教導參數') && teachOnly && collapsed && othersUnchecked && stillTeach && roiSummary && /納入 0 \/ 5/.test(count) && count.includes('其他參數 1 項') && teachStillZero && Boolean(t) && apiHas, `fromGraph=${fromGraphTxt} hdr=${teachHdr} teach=${teachItems.join(' ')} collapsed=${collapsed} toggle=${toggleTxt} others=${others.slice(0, 3).join(' ')}(${others.length}) roi=${JSON.stringify(roiTxt.slice(0, 2))} count=${count} teachZero=${teachStillZero} t=${t} api=${JSON.stringify(o?.param_overrides)}`)
  })

  await h.step('RC12 worker 唯讀面板', async () => {
    // 副本是 admin 的私有流程，worker 看不到；改用共用的示範流程（先用 API 放一個配方，full.mjs 結束時清）
    const demo = h.demoFlow()
    const wr = await h.api.post(`/vision/flows/${demo.id}/recipes`, { name: 'E2E worker', param_overrides: { thr: { threshold: 77 } }, is_default: false })
    const wtoken = await h.login(WORKER)
    const wctx = await h.newContext({ token: wtoken })
    const wp = await h.newPage(wctx, '[recipes-worker]')
    await wp.goto(`${BASE}/flows`)
    const row = wp.locator('table tbody tr').filter({ hasText: demo.name }).filter({ hasNotText: '副本' }).first()
    await row.waitFor({ timeout: 15000 })
    const rowSelDis = await row.locator(`[data-testid=row-bound-${demo.id}]`).isDisabled()
    await row.getByTestId('row-recipes').click()
    await wp.getByTestId('recipe-drawer').waitFor()
    const d = wp.getByTestId('recipe-drawer')
    const noNew = (await d.getByTestId('recipe-new').count()) === 0
    const importDis = await d.getByTestId('recipe-import').isDisabled()
    const exportOk = !(await d.getByTestId('recipe-export-all').isDisabled())
    const first = d.locator('[data-testid=recipe-item]').first()
    const dis = await Promise.all(['recipe-rename', 'recipe-duplicate', 'recipe-delete'].map((id) => first.getByTestId(id).isDisabled()))
    const bindDis = await d.locator('[data-testid=recipe-bind]').first().isDisabled()
    await first.getByTestId('recipe-expand').click()
    const detail = first.getByTestId('recipe-detail')
    await detail.waitFor()
    const noSave = (await detail.getByTestId('recipe-save').count()) === 0
    const inputsDis = await detail.locator('input, select').evaluateAll((els) => els.length > 0 && els.every((e) => e.disabled))
    await h.shot(wp, 'recipes-worker-readonly')
    await wctx.close()
    await h.api.del(`/vision/flows/${demo.id}/recipes/${wr.id}`)
    h.item('RC12', rowSelDis && noNew && importDis && exportOk && dis.every(Boolean) && bindDis && noSave && inputsDis, `rowSel=${rowSelDis} noNew=${noNew} import=${importDis} export=${exportOk} btns=${dis} bind=${bindDis} noSave=${noSave} inputs=${inputsDis}`)
  })

  await context.close()
}
