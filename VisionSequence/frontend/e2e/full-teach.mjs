/**
 * 模組 teach：參數卡頁（X）。用示範流程的副本（E2E 參數卡）做破壞性操作；唯讀／鎖定用 worker 開共用示範流程。
 * 改版後三欄：左＝步驟清單（teach-steps／teach-group）、中＝聚焦步驟的教導參數（teach-params）、右＝影像視窗＋結果摘要；
 * 儲存到配方／存為新配方走「儲存範圍 Check List」；管理配方是側滑面板（recipe-drawer）。
 */
import { BASE, WORKER } from './full-lib.mjs'

export async function ensureWorker(h) {
  const users = await h.api.get('/users')
  const u = users.items.find((x) => x.username === WORKER.username)
  if (!u) await h.api.post('/users', { ...WORKER, is_staff: false, display_name: '產線人員一' })
  else await h.api.patch(`/users/${u.id}`, { password: WORKER.password, is_active: true, is_staff: false })
}

export async function run(h) {
  await h.loginAdmin()
  await h.api.del('/vision/lock')
  await ensureWorker(h)
  const context = await h.newContext({ token: h.token })
  const page = await h.newPage(context, '[teach]')
  const flowId = await h.cloneDemo('E2E 參數卡')
  const url = `${BASE}/flows/${flowId}/teach`
  const group = (id) => page.locator(`[data-testid=teach-group][data-node-id=${id}]`)
  const params = () => page.getByTestId('teach-params')
  const isFocused = (id) => group(id).getAttribute('data-focused').then((v) => v === 'true')
  /** 中欄一次只顯示一個步驟：先點左欄聚焦，再回傳該參數的數字輸入框。 */
  const focus = async (id) => {
    if (!(await isFocused(id))) {
      await group(id).click()
      await page.waitForTimeout(250)
    }
  }
  const numberOf = async (id, key) => {
    await focus(id)
    return params().locator(`[data-param=${key}] input[type=number]`).first()
  }
  const paramsOf = async (id) => {
    await focus(id)
    return params().locator('[data-param]').evaluateAll((els) => els.map((e) => e.getAttribute('data-param')))
  }
  const waitIdle = async () => {
    await page.getByTestId('teach-updating').waitFor({ timeout: 3000 }).catch(() => null)
    await page.getByTestId('teach-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
    await page.waitForTimeout(300)
  }
  const openTeach = async () => {
    await page.goto(url)
    await page.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
    await waitIdle()
  }
  const header = () => page.locator('[data-testid=teach-header]').innerText()
  const overrideCount = () => page.getByTestId('teach-override-count').innerText().catch(() => '')
  const graphOf = async () => (await h.api.get(`/vision/flows/${flowId}`)).graph
  const recipesOf = async () => (await h.api.get(`/vision/flows/${flowId}/recipes`)).items
  const checkList = () => page.getByTestId('check-list')

  await h.step('X01 開啟參數卡', async () => {
    await openTeach()
    const hdr = await header()
    const ids = await page.getByTestId('teach-group').evaluateAll((els) => els.map((e) => e.getAttribute('data-node-id')))
    const first = await group('thr').innerText()
    const focused0 = await isFocused('thr')
    const mid = await params().innerText()
    const statuses = await page.getByTestId('teach-status').count()
    const statusTxt = await page.getByTestId('teach-status').allInnerTexts()
    const back = await page.getByTestId('btn-back').getAttribute('href')
    const rows = await page.locator('[data-testid=teach-header] > div').count()
    const bound = await page.getByTestId('bound-badge').innerText()
    const cols = await page.evaluate(() => ['teach-steps', 'teach-params', 'teach-viewer'].map((id) => document.querySelector(`[data-testid=${id}]`)?.getBoundingClientRect().width ?? 0))
    await h.shot(page, 'teach-open')
    h.item('X01', hdr.includes('參數卡') && hdr.includes('E2E 參數卡') && ids.join(',') === 'thr,blob,cmp' && first.includes('二值化') && focused0 && mid.includes('二值化') && mid.includes('thr') && statuses === 3 && statusTxt.every((s) => /ms/.test(s)) && back === `/flows/${flowId}` && rows === 2 && bound.includes('綁定：圖值') && cols.every((w) => w > 150) && cols[2] > cols[0], `header=${hdr.replace(/\n/g, '|').slice(0, 80)} ids=${ids} first=${first.replace(/\n/g, '|').slice(0, 60)} focused=${focused0} mid=${mid.replace(/\n/g, '|').slice(0, 50)} statuses=${statuses}/${statusTxt.join(',')} back=${back} rows=${rows} bound=${bound} cols=${cols}`)
  })

  await h.step('X02 欄位種類', async () => {
    const thrParams = await paramsOf('thr')
    const thrNumber = await (await numberOf('thr', 'threshold')).count()
    const blobParams = await paramsOf('blob')
    const range = await params().locator('[data-param=min_circularity] input[type=range]').count()
    const rangeNumber = await params().locator('[data-param=min_circularity] input[type=number]').count()
    const cmpNumber = await (await numberOf('cmp', 'threshold')).count()
    // 曝光流程：in_range 的 low/high
    const demo2 = h.demoFlow2()
    let inRange = false
    if (demo2) {
      await page.goto(`${BASE}/flows/${demo2.id}/teach`)
      await page.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
      await waitIdle()
      await page.locator('[data-testid=teach-group][data-node-id=rng]').click()
      await page.waitForTimeout(250)
      const p = await params().locator('[data-param]').evaluateAll((els) => els.map((e) => e.getAttribute('data-param')))
      inRange = p.join(',') === 'low,high'
      await h.shot(page, 'teach-demo2')
      await openTeach()
    }
    h.item('X02', thrNumber === 1 && range === 1 && rangeNumber === 1 && blobParams.join(',') === 'min_area,max_area,min_circularity' && thrParams.join(',') === 'threshold' && cmpNumber === 1 && inRange, `thr=${thrParams} blob=${blobParams} range=${range}/${rangeNumber} cmp=${cmpNumber} inRange=${inRange}`)
  })

  let thrValue = 0
  await h.step('X03 改值即時試跑', async () => {
    const input = await numberOf('thr', 'threshold')
    const before = Number(await input.inputValue())
    thrValue = before > 200 ? 60 : 200
    const statusBefore = await group('thr').getByTestId('teach-status').innerText()
    const t0 = Date.now()
    const reqPromise = page.waitForRequest((r) => r.url().includes('/preview') && r.method() === 'POST', { timeout: 5000 }).then((r) => ({ body: r.postDataJSON(), at: Date.now() - t0 })).catch(() => null)
    await input.fill(String(thrValue))
    const req = await reqPromise
    const updating = Boolean(req) && req.at < 1500 && req.body?.until_node === 'thr' && req.body?.analysis !== true
    await waitIdle()
    const statusAfter = await group('thr').getByTestId('teach-status').innerText()
    const focused = await isFocused('thr')
    const hdr = await header()
    const savePrimary = await page.getByTestId('teach-save').evaluate((el) => el.className.includes('primary') || getComputedStyle(el).backgroundColor !== 'rgba(0, 0, 0, 0)')
    await h.shot(page, 'teach-live-edit')
    h.item('X03', updating && /ms/.test(statusAfter) && focused && hdr.includes('有未儲存的變更') && savePrimary, `preview=${JSON.stringify(req && { at: req.at, until: req.body?.until_node, analysis: req.body?.analysis })} status=${statusBefore.replace(/\n/g, ' ')}→${statusAfter.replace(/\n/g, ' ')} focused=${focused} unsaved=${hdr.includes('有未儲存的變更')} primary=${savePrimary}`)
  })

  await h.step('X04 聚焦切換', async () => {
    await group('blob').click()
    await page.waitForTimeout(400)
    const focused = await isFocused('blob')
    const thrUnfocused = !(await isFocused('thr'))
    const bar = await group('blob').locator('span.bg-brand').count()
    const midTitle = await params().locator('section').getAttribute('data-node-id')
    const viewer = page.getByTestId('teach-viewer')
    const label = await viewer.locator('span.absolute.left-2').innerText()
    const hasImage = await h.viewerHasImage(page, '[data-testid=teach-viewer]')
    const outputs = await page.getByTestId('teach-outputs').innerText().catch(() => '')
    await h.shot(page, 'teach-focus-blob')
    h.item('X04', focused && thrUnfocused && bar >= 1 && midTitle === 'blob' && label.includes('正在檢視') && hasImage && outputs.includes('count'), `focused=${focused}/${thrUnfocused} bar=${bar} mid=${midTitle} label=${label} image=${hasImage} outputs=${outputs.replace(/\n/g, '|').slice(0, 60)}`)
  })

  await h.step('X05 儲存到圖（按鈕＋Ctrl+S）', async () => {
    const patchRes = () => page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes(`/flows/${flowId}`) && !r.url().includes('/recipes'), { timeout: 8000 }).then((r) => r.status()).catch(() => 0)
    let p = patchRes()
    await page.getByTestId('teach-save').click()
    const s1 = await p
    const t1 = await h.toast(page, /流程已儲存/)
    await page.waitForTimeout(500)
    const g1 = await graphOf()
    const v1 = g1.nodes.find((n) => n.id === 'thr').params.threshold
    const header1 = await header()
    // Ctrl+S：再改一次（游標在 body 上，不在輸入框）
    const input = await numberOf('cmp', 'threshold')
    const cmpBefore = Number(await input.inputValue())
    await input.fill(String(cmpBefore + 1))
    await waitIdle()
    await page.locator('[data-testid=teach-header]').click({ position: { x: 5, y: 5 } })
    p = patchRes()
    await page.keyboard.press('Control+s')
    const s2 = await p
    const t2 = await h.toast(page, /流程已儲存/)
    await page.waitForTimeout(500)
    const g2 = await graphOf()
    const v2 = g2.nodes.find((n) => n.id === 'cmp').params.threshold
    await input.fill(String(cmpBefore))
    await waitIdle()
    p = patchRes()
    await page.keyboard.press('Control+s')
    await p
    await page.waitForTimeout(300)
    h.item('X05', s1 === 200 && s2 === 200, `PATCH 狀態 save=${s1} ctrlS=${s2}`)
    h.item('X05', Boolean(t1) && Number(v1) === thrValue && !header1.includes('有未儲存的變更') && Boolean(t2) && Number(v2) === cmpBefore + 1, `t1=${t1} thr=${v1}(期望 ${thrValue}) unsavedGone=${!header1.includes('有未儲存的變更')} t2=${t2} cmp=${v2}(期望 ${cmpBefore + 1})`)
  })

  await h.step('X06 暫存影像', async () => {
    const reuse = page.locator('[data-testid=teach-header] input[type=checkbox]').first()
    const reuseBefore = await reuse.isDisabled()
    const png = await h.makePng(page, { w: 320, h: 240, dots: 4, seed: 7 })
    await page.getByTestId('scratch-input').setInputFiles({ name: 'e2e-scratch.png', mimeType: 'image/png', buffer: png })
    const t = await h.toast(page, /已上傳暫存影像|e2e-scratch/)
    await page.getByTestId('scratch-badge').waitFor({ timeout: 5000 })
    const badge = await page.getByTestId('scratch-badge').innerText()
    await waitIdle()
    const reuseDisabled = await reuse.isDisabled()
    await h.shot(page, 'teach-scratch')
    await page.getByTestId('scratch-clear').click()
    const gone = await h.waitGone(page.getByTestId('scratch-badge'))
    const reuseAfter = await reuse.isDisabled()
    h.item('X06', Boolean(t) && badge.includes('e2e-scratch') && badge.includes('320') && reuseDisabled && gone && !reuseAfter, `t=${t} badge=${badge} reuse=${reuseBefore}/${reuseDisabled}/${reuseAfter} gone=${gone}`)
  })

  let recipeA = null
  await h.step('X07 存為新配方（Check List）', async () => {
    const manage0 = await page.getByTestId('teach-manage').innerText()
    await page.getByTestId('teach-save-as').click()
    await h.dialog(page).waitFor()
    await page.getByTestId('teach-save-as-confirm').click()
    const tEmpty = await h.toast(page, /請輸入名稱/)
    await page.getByTestId('teach-save-as-name').fill('partA')
    await page.keyboard.press('Enter')
    // 圖模式存為新配方：所有教導參數都與圖相同 → Check List 全部 unchanged、預設不勾
    await checkList().waitFor({ timeout: 10000 })
    const title = await h.dialog(page).locator('h2').innerText()
    const items = await page.locator('[data-testid=check-item]').evaluateAll((els) => els.map((e) => `${e.getAttribute('data-key')}:${e.getAttribute('data-status')}:${e.getAttribute('data-checked')}`))
    const count = await page.getByTestId('check-count').innerText()
    await h.shot(page, 'teach-save-as-checklist')
    await page.getByTestId('check-confirm').click()
    const t = await h.toast(page, /已建立配方「partA」/)
    await page.waitForTimeout(500)
    const list = await recipesOf()
    recipeA = list.find((r) => r.name === 'partA')
    const sel = await page.getByTestId('teach-recipe').inputValue()
    const manage1 = await page.getByTestId('teach-manage').innerText()
    const hint = await overrideCount()
    const saveTxt = await page.getByTestId('teach-save').innerText()
    const bound = await page.getByTestId('bound-badge').innerText()
    const editing = await params().innerText()
    await h.shot(page, 'teach-recipe-created')
    h.item('X07', Boolean(tEmpty) && title.includes('partA') && title.includes('Check List') && items.length === 5 && items.every((s) => /:unchanged:false$/.test(s)) && /納入 0 \//.test(count) && Boolean(t) && recipeA && recipeA.is_default && Object.keys(recipeA.param_overrides).length === 0 && sel === String(recipeA.id) && manage0.trim() === '管理配方' && manage1.includes('(1)') && hint.includes('0 個覆寫') && saveTxt.includes('儲存到配方') && bound.includes('綁定：partA') && editing.includes('正在編輯配方「partA」'), `empty=${tEmpty} title=${title} items=${items.join(' ')} count=${count} t=${t} recipe=${JSON.stringify(recipeA)} sel=${sel} manage=${manage0}/${manage1} hint=${hint} save=${saveTxt} bound=${bound}`)
  })

  await h.step('X08 配方模式改值與儲存（Check List）', async () => {
    const g0 = await graphOf()
    const graphMin = g0.nodes.find((n) => n.id === 'blob').params.min_area
    const input = await numberOf('blob', 'min_area')
    await input.fill('123')
    await waitIdle()
    const wrap = params().locator('[data-param=min_area]')
    const marked = await wrap.evaluate((el) => el.className.includes('border-l-2'))
    const info = await wrap.innerText()
    const hint = await overrideCount()
    const stepHint = await group('blob').innerText()
    const status = await group('blob').getByTestId('teach-status').innerText()
    await page.locator('[data-testid=teach-header]').click({ position: { x: 5, y: 5 } })
    await page.keyboard.press('Control+s')
    await checkList().waitFor({ timeout: 10000 })
    // include_all：教導參數區列出全部教導參數（改過的 blob.min_area ok 預設勾、其餘 unchanged 不勾）；其他參數摺疊、未展開
    const items = await page.locator('[data-testid=check-item]').evaluateAll((els) => els.map((e) => `${e.getAttribute('data-key')}:${e.getAttribute('data-status')}:${e.getAttribute('data-checked')}`))
    const okOnly = items.filter((s) => /^blob\.min_area:ok:true$/.test(s)).length === 1 && items.filter((s) => /:unchanged:false$/.test(s)).length === items.length - 1 && items.length === 5
    const othersCollapsed = (await page.getByTestId('check-others').count()) === 1 && (await page.getByTestId('check-list-others').count()) === 0
    const othersTxt = await page.getByTestId('check-others-toggle').innerText()
    const change = await page.locator('[data-testid=check-item][data-key="blob.min_area"] td').nth(2).innerText()
    await h.shot(page, 'teach-recipe-checklist')
    await page.getByTestId('check-confirm').click()
    const t = await h.toast(page, /已儲存配方「partA」/)
    await page.waitForTimeout(500)
    const r = (await recipesOf()).find((x) => x.name === 'partA')
    const g1 = await graphOf()
    const graphAfter = g1.nodes.find((n) => n.id === 'blob').params.min_area
    const hdr = await header()
    await h.shot(page, 'teach-recipe-override')
    h.item('X08', marked && info.includes('配方值') && info.includes('圖值') && hint.includes('1 個覆寫') && stepHint.includes('1 個覆寫') && /ms/.test(status) && okOnly && othersCollapsed && /其他參數（\d+）/.test(othersTxt) && change.includes(String(graphMin)) && change.includes('123') && Boolean(t) && r?.param_overrides?.blob?.min_area === 123 && graphAfter === graphMin && !hdr.includes('有未儲存的變更'), `marked=${marked} info=${info.replace(/\n/g, '|').slice(0, 80)} hint=${hint} step=${stepHint.replace(/\n/g, '|')} t=${t} items=${items} others=${othersCollapsed}/${othersTxt} change=${change} overrides=${JSON.stringify(r?.param_overrides)} graph=${graphMin}→${graphAfter} unsavedGone=${!hdr.includes('有未儲存的變更')}`)
  })

  await h.step('X09 還原為圖值', async () => {
    await params().locator('[data-param=min_area]').getByRole('button', { name: '還原為圖值' }).click()
    await waitIdle()
    const marked = await params().locator('[data-param=min_area]').evaluate((el) => el.className.includes('border-l-2'))
    const hint = await overrideCount()
    const hdr = await header()
    h.item('X09', !marked && hint.includes('0 個覆寫') && hdr.includes('有未儲存的變更'), `marked=${marked} hint=${hint} unsaved=${hdr.includes('有未儲存的變更')}`)
  })

  await h.step('X10 切換配方時的確認', async () => {
    let asked = 0
    h.nextDialog(page, false)
    page.__dialog = (d) => {
      asked += 1
      page.__dialog = null
      d.dismiss()
    }
    await page.getByTestId('teach-recipe').selectOption('')
    await page.waitForTimeout(300)
    const stayed = (await page.getByTestId('teach-recipe').inputValue()) === String(recipeA.id)
    page.__dialog = (d) => {
      asked += 1
      page.__dialog = null
      d.accept()
    }
    await page.getByTestId('teach-recipe').selectOption('')
    await page.waitForTimeout(300)
    const switched = (await page.getByTestId('teach-recipe').inputValue()) === ''
    const saveTxt = await page.getByTestId('teach-save').innerText()
    const opt = await page.locator('[data-testid=teach-recipe] option').allInnerTexts()
    h.item('X10', asked === 2 && stayed && switched && saveTxt.includes('儲存到圖') && opt.some((o) => o.includes('partA') && o.includes('綁定')), `asked=${asked} stayed=${stayed} switched=${switched} save=${saveTxt} opts=${opt.join('/')}`)
  })

  await h.step('X11 管理配方（側滑面板）', async () => {
    await page.getByTestId('teach-manage').click()
    const drawer = page.getByTestId('recipe-drawer')
    await drawer.waitFor({ timeout: 5000 })
    const items0 = await page.getByTestId('recipe-item').allInnerTexts()
    const bound0 = await page.locator('[data-testid=recipe-item][data-bound=true]').count()
    const fromGraphTxt = await drawer.locator('[data-testid=recipe-new] label').filter({ has: page.getByTestId('recipe-new-from-graph') }).innerText()
    // 新增 partB（以圖值 → Check List 全 unchanged → 不勾直接建立）
    await page.getByTestId('recipe-new-name').fill('partB')
    await page.keyboard.press('Enter')
    await checkList().waitFor({ timeout: 10000 })
    const n0 = await page.locator('[data-testid=check-item]').count()
    await page.getByTestId('check-confirm').click()
    const tCreate = await h.toast(page, /已建立配方「partB」/)
    await page.waitForTimeout(500)
    const items1 = await page.getByTestId('recipe-item').count()
    const itemB = () => page.locator('[data-testid=recipe-item]').filter({ hasText: /partB/ }).first()
    const autoExpanded = (await itemB().getByTestId('recipe-detail').count()) === 1
    // 改名 partB → partB2（Enter）
    await itemB().getByTestId('recipe-rename').click()
    await page.getByTestId('recipe-rename-input').fill('partB2')
    await page.keyboard.press('Enter')
    const tRename = await h.toast(page, /已改名為「partB2」/)
    await page.locator('[data-testid=recipe-item]').filter({ hasText: 'partB2' }).first().waitFor({ timeout: 5000 })
    // 設綁定
    await itemB().getByTestId('recipe-bind').click()
    const tBind = await h.toast(page, /已綁定配方「partB2」/)
    await page.waitForTimeout(500)
    const list = await recipesOf()
    const defaultB = list.find((r) => r.name === 'partB2')?.is_default === true && list.find((r) => r.name === 'partA')?.is_default === false
    const boundBadge = (await itemB().innerText()).includes('綁定')
    const topBound = await page.getByTestId('bound-badge').innerText()
    // 覆寫表：從圖值填入／新增一列／移除；儲存 → Check List
    if ((await itemB().getByTestId('recipe-detail').count()) === 0) await itemB().getByTestId('recipe-expand').click()
    const detail = itemB().getByTestId('recipe-detail')
    await detail.waitFor()
    const empty = (await detail.innerText()).includes('沒有覆寫')
    await detail.getByTestId('recipe-fill').click()
    await page.waitForTimeout(200)
    const rowsFilled = await detail.getByTestId('recipe-overrides').locator('tbody tr').count()
    await detail.getByTestId('recipe-add-row').click()
    const rowsAdded = await detail.getByTestId('recipe-overrides').locator('tbody tr').count()
    await detail.getByTestId('recipe-overrides').locator('tbody tr').last().getByTitle('移除').click()
    const rowsRemoved = await detail.getByTestId('recipe-overrides').locator('tbody tr').count()
    const rowTxt = await detail.getByTestId('recipe-overrides').locator('tbody tr').first().innerText()
    await detail.getByTestId('recipe-value').first().fill('111')
    await h.shot(page, 'teach-recipe-drawer')
    await detail.getByTestId('recipe-save').click()
    await checkList().waitFor({ timeout: 10000 })
    const items = await page.locator('[data-testid=check-item]').evaluateAll((els) => els.map((e) => `${e.getAttribute('data-status')}:${e.getAttribute('data-checked')}`))
    const okOne = items.filter((s) => s === 'ok:true').length === 1 && items.filter((s) => s === 'unchanged:false').length === items.length - 1
    await page.getByTestId('check-list-all').check()
    const countAll = await page.getByTestId('check-count').innerText()
    await page.getByTestId('check-confirm').click()
    const tUpdate = await h.toast(page, /已更新配方「partB2」/)
    await page.waitForTimeout(500)
    const bOverrides = (await recipesOf()).find((r) => r.name === 'partB2')?.param_overrides ?? {}
    const bCount = Object.values(bOverrides).reduce((n, p) => n + Object.keys(p).length, 0)
    // 刪除 partB2
    await itemB().getByTestId('recipe-delete').click()
    const confirm = page.locator('[role=dialog]').filter({ hasText: '刪除配方' }).last()
    const msg = await confirm.innerText()
    await confirm.getByRole('button', { name: '刪除', exact: true }).click()
    const tDel = await h.toast(page, /已刪除配方/)
    await page.waitForTimeout(500)
    const items2 = await page.getByTestId('recipe-item').count()
    await page.getByTestId('recipe-drawer-close').click()
    const closed = await h.waitGone(drawer)
    h.item('X11', items0.length === 1 && items0[0].includes('partA') && bound0 === 1 && /5 項/.test(fromGraphTxt) && n0 === 5 && Boolean(tCreate) && items1 === 2 && autoExpanded && Boolean(tRename) && Boolean(tBind) && defaultB && boundBadge && topBound.includes('partB2') && empty && rowsFilled === 5 && rowsAdded === 6 && rowsRemoved === 5 && rowTxt.includes('圖值') && okOne && /納入 5 \/ 5/.test(countAll) && Boolean(tUpdate) && bCount === 5 && bOverrides.thr?.threshold === 111 && msg.includes('partB2') && Boolean(tDel) && items2 === 1 && closed, `items0=${items0.join('|').replace(/\n/g, ' ')} bound0=${bound0} fromGraph=${fromGraphTxt} n0=${n0} create=${tCreate} items1=${items1} autoExpanded=${autoExpanded} rename=${tRename} bind=${tBind} default=${defaultB}/${boundBadge}/${topBound} empty=${empty} rows=${rowsFilled}/${rowsAdded}/${rowsRemoved} row=${rowTxt.replace(/\n/g, ' ').slice(0, 60)} items=${items.join(',')} countAll=${countAll} update=${tUpdate} bCount=${bCount} b=${JSON.stringify(bOverrides)} msg=${msg.replace(/\n/g, ' ').slice(0, 60)} del=${tDel} items2=${items2} closed=${closed}`)
  })

  await h.step('X12 標記已教導／取消', async () => {
    const before = (await h.api.get(`/vision/flows/${flowId}`)).commissioned
    if (before) {
      await page.getByTestId('teach-unmark').click()
      await h.toast(page, /已取消已教導/)
      await page.waitForTimeout(300)
    }
    const badge0 = await header()
    await page.getByTestId('teach-mark').click()
    const t1 = await h.toast(page, /已標記為已教導/)
    await page.waitForTimeout(500)
    const c1 = (await h.api.get(`/vision/flows/${flowId}`)).commissioned
    const badge1 = await header()
    const unmarkShown = (await page.getByTestId('teach-unmark').count()) === 1
    await h.shot(page, 'teach-commissioned')
    await page.getByTestId('teach-unmark').click()
    const t2 = await h.toast(page, /已取消已教導/)
    await page.waitForTimeout(500)
    const c2 = (await h.api.get(`/vision/flows/${flowId}`)).commissioned
    const markShown = (await page.getByTestId('teach-mark').count()) === 1
    // 編輯器頂列
    await page.goto(`${BASE}/flows/${flowId}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    const href = await page.getByTestId('not-commissioned-badge').getAttribute('href')
    const badgeTxt = await page.getByTestId('not-commissioned-badge').innerText()
    await page.getByTestId('not-commissioned-badge').click()
    await page.waitForURL(/\/teach$/, { timeout: 5000 })
    h.item('X12', badge0.includes('未教導') && Boolean(t1) && c1 === true && badge1.includes('已教導') && unmarkShown && Boolean(t2) && c2 === false && markShown && href === `/flows/${flowId}/teach` && badgeTxt.includes('未教導') && /\/teach$/.test(page.url()), `badge0=${badge0.includes('未教導')} t1=${t1} c1=${c1} badge1=${badge1.includes('已教導')} unmark=${unmarkShown} t2=${t2} c2=${c2} mark=${markShown} href=${href} badgeTxt=${badgeTxt} url=${page.url()}`)
  })

  await h.step('X13 返回編輯器與離開攔截', async () => {
    await page.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
    await waitIdle()
    const input = await numberOf('thr', 'threshold')
    const cur = Number(await input.inputValue())
    await input.fill(String(cur + 1))
    await waitIdle()
    let asked = 0
    page.__dialog = (d) => {
      asked += 1
      d.accept()
    }
    await page.getByTestId('btn-back').click()
    await page.waitForURL(new RegExp(`/flows/${flowId}$`), { timeout: 5000 })
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
    const noAsk = asked === 0
    const editorDirty = (await page.locator('[data-testid=editor-toolbar]').innerText()).includes('有未儲存的變更')
    // 編輯器丟掉草稿（重新載入）再進參數卡選配方改值 → 離開要問
    page.__dialog = null
    await page.goto(url)
    await page.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
    await waitIdle()
    await page.getByTestId('teach-recipe').selectOption(String(recipeA.id))
    await page.waitForTimeout(200)
    await (await numberOf('blob', 'min_area')).fill('77')
    await waitIdle()
    let asked2 = 0
    page.__dialog = (d) => {
      asked2 += 1
      page.__dialog = null
      d.dismiss()
    }
    await page.getByTestId('btn-back').click()
    await page.waitForTimeout(500)
    const stayed = /\/teach$/.test(page.url())
    page.__dialog = (d) => {
      asked2 += 1
      page.__dialog = null
      d.accept()
    }
    await page.getByTestId('btn-back').click()
    await page.waitForURL(new RegExp(`/flows/${flowId}$`), { timeout: 5000 })
    page.__dialog = null
    h.item('X13', noAsk && editorDirty && asked2 === 2 && stayed && new RegExp(`/flows/${flowId}$`).test(page.url()), `noAsk=${noAsk} editorDirty=${editorDirty} asked2=${asked2} stayed=${stayed} url=${page.url()}`)
  })

  await h.step('X14 X16 worker 唯讀與鎖定', async () => {
    const demo = h.demoFlow()
    const wtoken = await h.login(WORKER)
    const wctx = await h.newContext({ token: wtoken })
    const worker = await h.newPage(wctx, '[teach-worker]')
    await worker.goto(`${BASE}/flows/${demo.id}/teach`)
    await worker.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
    await worker.getByTestId('teach-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
    await worker.waitForTimeout(300)
    const saveDis = await worker.getByTestId('teach-save').isDisabled()
    const saveAsDis = await worker.getByTestId('teach-save-as').isDisabled()
    const markDis = await worker.locator('[data-testid=teach-mark], [data-testid=teach-unmark]').first().isDisabled()
    await worker.getByTestId('teach-manage').click()
    await worker.getByTestId('recipe-drawer').waitFor({ timeout: 5000 })
    const noCreate = (await worker.getByTestId('recipe-new-name').count()) === 0
    const noSave = (await worker.getByTestId('recipe-save').count()) === 0
    const importDis = await worker.getByTestId('recipe-import').isDisabled()
    await h.shot(worker, 'teach-worker-readonly')
    await worker.getByTestId('recipe-drawer-close').click()
    await worker.waitForTimeout(200)
    // 改值後 Ctrl+S → warning toast
    await worker.locator('[data-testid=teach-params] input[type=number]').first().fill('99')
    await worker.getByTestId('teach-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
    await worker.locator('[data-testid=teach-header]').click({ position: { x: 5, y: 5 } })
    await worker.keyboard.press('Control+s')
    const tRo = await h.toast(worker, /共用流程只有管理員能修改/)
    h.item('X14', saveDis && saveAsDis && markDis && noCreate && noSave && importDis && Boolean(tRo), `save=${saveDis} saveAs=${saveAsDis} mark=${markDis} noCreate=${noCreate} noSave=${noSave} importDis=${importDis} toast=${tRo}`)
    // 鎖定：不自動試跑（左欄每步都是「—」、沒有試跑中、結果摘要「尚未試跑」）
    await h.api.post('/vision/lock', { reason: 'E2E teach lock', ttl_s: 300 })
    await worker.goto(`${BASE}/flows/${demo.id}/teach`)
    await worker.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
    await worker.waitForTimeout(2500)
    const statuses = await worker.getByTestId('teach-status').allInnerTexts()
    const updating = await worker.getByTestId('teach-updating').count()
    const noResult = (await worker.getByTestId('teach-outputs').innerText()).includes('尚未試跑')
    await h.shot(worker, 'teach-worker-locked')
    await h.api.del('/vision/lock')
    h.item('X16', statuses.length === 3 && statuses.every((s) => !/ms/.test(s)) && updating === 0 && noResult, `statuses=${statuses.join(',')} updating=${updating} noResult=${noResult}`)
    await wctx.close()
  })

  await h.step('X15 無教導參數', async () => {
    const empty = await h.api.post('/vision/flows', { name: 'E2E 空流程', description: '' })
    await page.goto(`${BASE}/flows/${empty.id}/teach`)
    await page.getByTestId('teach-page').waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
    const txt = await page.getByTestId('teach-steps').innerText()
    const mid = await params().innerText()
    await h.shot(page, 'teach-empty')
    await h.api.del(`/vision/flows/${empty.id}`)
    h.item('X15', txt.includes('此流程沒有需要教導的參數') && txt.includes('二值化門檻') && mid.includes('從左側選一個步驟'), `txt=${txt.replace(/\n/g, '|').slice(0, 100)} mid=${mid}`)
  })

  await h.step('X17 1280 與深色', async () => {
    const small = await h.newContext({ token: h.token, viewport: { width: 1280, height: 800 } })
    const sp = await h.newPage(small, '[teach-1280]')
    await sp.goto(url)
    await sp.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
    await sp.getByTestId('teach-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
    await sp.waitForTimeout(300)
    const info = await sp.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
    const viewerBox = await sp.getByTestId('teach-viewer').boundingBox()
    await h.shot(sp, 'teach-1280')
    await small.close()
    const dark = await h.newContext({ token: h.token, colorScheme: 'dark' })
    await dark.addInitScript(() => localStorage.setItem('vs.theme', 'dark'))
    const dp = await h.newPage(dark, '[teach-dark]')
    await dp.goto(url)
    await dp.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
    await dp.getByTestId('teach-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
    await dp.waitForTimeout(300)
    await dp.getByTestId('teach-manage').click()
    await dp.getByTestId('recipe-drawer').waitFor({ timeout: 5000 })
    await h.shot(dp, 'teach-dark-drawer')
    const isDark = await dp.evaluate(() => document.documentElement.classList.contains('dark'))
    await dark.close()
    h.item('X17', info.sw <= info.cw + 1 && viewerBox && viewerBox.width >= 440 && isDark, `scroll=${info.sw}/${info.cw} viewerW=${viewerBox?.width} dark=${isDark}`)
  })

  await context.close()
}
