/** 模組 tool：工具頁（N）——頂列、每種 Param kind、進階群組、驗證、自動套用、同步視角、參考資訊、錯誤、儲存／返回。 */
import { BASE } from './full-lib.mjs'

export async function run(h) {
  await h.loginAdmin()
  const context = await h.newContext({ token: h.token })
  const page = await h.newPage(context, '[tool]')
  const flowId = await h.cloneDemo('E2E 工具頁測試')
  // 加上會用到各種 Param kind 的工具
  const g = (await h.api.get(`/vision/flows/${flowId}`)).graph
  g.nodes.push(
    { id: 'tm', type: 'template_match', label: '範本比對', params: {}, position: { x: 400, y: 600 } },
    { id: 'cc', type: 'color_check', label: '顏色檢查', params: {}, position: { x: 700, y: 600 } },
    { id: 'fm', type: 'formula', label: '公式', params: { expression: 'a + 1' }, position: { x: 1000, y: 600 } },
    { id: 'dl', type: 'dl_classify', label: 'DL 分類', params: {}, position: { x: 1300, y: 600 } },
  )
  for (const id of ['tm', 'cc', 'dl']) g.edges.push({ source: 'src', source_handle: 'image', target: id, target_handle: 'image' })
  await h.api.patch(`/vision/flows/${flowId}`, { graph: g })
  // 一個停用的來源（source 下拉要顯示 disabled）
  const disabledSrc = await h.api.post('/vision/sources', { name: 'E2E 停用來源', kind: 'upload', config: {}, is_enabled: false })

  const openTool = async (nodeId) => {
    await page.goto(`${BASE}/flows/${flowId}/tools/${nodeId}`)
    await page.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
    await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
    await page.waitForTimeout(500)
  }
  const params = () => page.locator('[data-testid=tool-params]')
  const field = (key) => params().locator(`[data-param=${key}]`)
  const header = () => page.locator('[data-testid=tool-page] header')
  const waitPreview = (timeout = 4000) => page.waitForRequest((r) => r.url().includes('/preview') && r.method() === 'POST', { timeout }).catch(() => null)

  await h.step('N01 頂列', async () => {
    await openTool('blob')
    const txt = await header().innerText()
    const back = (await page.getByTestId('btn-back').count()) === 1
    const save = page.getByTestId('tool-save')
    const savedLabel = (await save.innerText()).includes('已儲存')
    const preview = (await page.getByTestId('tool-preview').count()) === 1
    const reuse = (await header().locator('input[type=checkbox]').count()) === 1
    const scratch = (await page.getByTestId('tool-scratch').count()) === 1
    // 改版後：前／後影像各自縮放，頂列不再有「同步視角」開關（只剩自動套用）
    const switches = await header().getByRole('switch').count()
    const autoOn = (await header().getByRole('switch', { name: '自動套用' }).getAttribute('aria-checked')) === 'true'
    const noSync = !txt.includes('同步視角')
    await h.shot(page, 'tool-page-blob')
    h.item('N01', txt.includes('返回編輯器') && txt.includes('Blob 分析 · blob') && back && savedLabel && preview && reuse && scratch && switches === 1 && autoOn && noSync, `header=${txt.replace(/\n/g, '|')} switches=${switches} auto=${autoOn} noSync=${noSync}`)
  })

  await h.step('N03 N06 N07 N15 blob 的 number／range／roi／進階', async () => {
    const minArea = field('min_area').locator('input[type=number]')
    const step = await minArea.getAttribute('step')
    const min = await minArea.getAttribute('min')
    const unit = await field('min_area').locator('.absolute.inset-y-0').innerText().catch(() => '')
    const label = await field('min_area').innerText()
    h.item('N03', (await minArea.count()) === 1 && step !== null && label.includes('面積'), `step=${step} min=${min} unit=${unit} label=${label.replace(/\n/g, '|')}`)
    const range = field('min_circularity').locator('input[type=range]')
    const num = field('min_circularity').locator('input[type=number]')
    const attrs = { min: await range.getAttribute('min'), max: await range.getAttribute('max'), step: await range.getAttribute('step') }
    await range.fill('0.75')
    await page.waitForTimeout(200)
    const numVal = await num.inputValue()
    await num.fill('0.4')
    await page.waitForTimeout(200)
    const rangeVal = await range.inputValue()
    h.item('N06', attrs.min === '0' && attrs.max === '1' && numVal === '0.75' && rangeVal === '0.4', `attrs=${JSON.stringify(attrs)} num=${numVal} range=${rangeVal}`)
    const roi = field('roi')
    const roiTxt = await roi.innerText()
    const editBtn = roi.getByRole('button', { name: '在影像上編輯' })
    const editable = !(await editBtn.isDisabled())
    h.item('N07', roiTxt.includes('尚未設定') && roiTxt.includes('形狀') && roiTxt.includes('rect') && editable, `roi=${roiTxt.replace(/\n/g, '|')} editable=${editable}`)
    const adv = params().getByRole('button', { name: /進階（\d+）/ })
    const advLabel = await adv.innerText()
    const hiddenBefore = (await field('fill_holes').count()) === 0
    await adv.click()
    const shown = (await field('fill_holes').count()) === 1 && (await field('external_only').count()) === 1
    await h.shot(page, 'tool-advanced')
    await adv.click()
    const hiddenAfter = (await field('fill_holes').count()) === 0
    h.item('N15', /進階（3）/.test(advLabel) && hiddenBefore && shown && hiddenAfter, `label=${advLabel} before=${hiddenBefore} shown=${shown} after=${hiddenAfter}`)
  })

  await h.step('N17 自動套用', async () => {
    const minArea = field('min_area').locator('input[type=number]')
    const w1 = waitPreview()
    await minArea.fill('333')
    const req = await w1
    const body = req ? JSON.parse(req.postData() || '{}') : {}
    await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => null)
    const dirty = (await header().innerText()).includes('有未儲存的變更')
    await header().getByRole('switch', { name: '自動套用' }).click()
    const w2 = waitPreview(1500)
    await minArea.fill('334')
    const req2 = await w2
    const w3 = waitPreview()
    await page.getByTestId('tool-preview').click()
    const req3 = await w3
    await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => null)
    await header().getByRole('switch', { name: '自動套用' }).click()
    h.item('N17', req && body.until_node === 'blob' && body.analysis === true && typeof body.reuse_image_ref === 'string' && dirty && req2 === null && req3 !== null, `auto=${Boolean(req)} until=${body.until_node} analysis=${body.analysis} reuse=${Boolean(body.reuse_image_ref)} dirty=${dirty} offNoReq=${req2 === null} manual=${req3 !== null}`)
  })

  await h.step('N19 N20 參考資訊與無影像輸出', async () => {
    const ref = page.getByTestId('tool-reference')
    const txt = await ref.innerText()
    const hist = await ref.getByTestId('histogram').count()
    const series = (await page.getByTestId('tool-series').count()) === 1
    const blobAfterLabel = await page.locator('[data-testid=tool-after] .absolute.left-2.top-8').innerText()
    const blobAfterImage = await h.viewerHasImage(page, '[data-testid=tool-after]')
    await h.shot(page, 'tool-reference')
    h.item('N19', hist >= 2 && txt.includes('輸入影像直方圖') && txt.includes('尺寸') && txt.includes('平均') && series && txt.includes('blobs.area') && txt.includes('輸出') && txt.includes('count') && blobAfterImage && !blobAfterLabel.includes('標記疊在'), `hist=${hist} series=${series} afterImage=${blobAfterImage} text=${txt.slice(0, 200).replace(/\n/g, '|')}`)
    // 沒有影像輸出的工具（cmp）：右側標記疊在輸入影像上＋輸出值表
    await openTool('cc')
    const afterLabel = await page.locator('[data-testid=tool-after] .absolute.left-2.top-8').innerText()
    const outVals = await page.getByTestId('tool-output-values').innerText()
    const afterHasInput = await h.viewerHasImage(page, '[data-testid=tool-after]')
    await h.shot(page, 'tool-no-image-output')
    h.item('N20', afterLabel.includes('標記疊在輸入影像上') && outVals.includes('distance') && afterHasInput, `after=${afterLabel} outputs=${outVals.slice(0, 60).replace(/\n/g, '|')} afterImage=${afterHasInput}`)
    await openTool('blob')
  })

  await h.step('N18 前／後影像各自縮放', async () => {
    // 改版後：兩個視窗各自 fit／縮放，左邊放大右邊不動；右邊放大左邊不動；各自「適合視窗」回到相同比例
    const before = page.locator('[data-testid=tool-before]')
    const after = page.locator('[data-testid=tool-after]')
    const label = (sel) => sel.locator('span.font-mono').first().innerText()
    await before.locator('button[title="適合視窗 (F)"]').click()
    await after.locator('button[title="適合視窗 (F)"]').click()
    await page.waitForTimeout(300)
    const l0 = await label(before)
    const r0 = await label(after)
    await before.locator('button[title="放大 (+)"]').click()
    await page.waitForTimeout(300)
    const l1 = await label(before)
    const r1 = await label(after)
    await after.locator('button[title="放大 (+)"]').click()
    await after.locator('button[title="放大 (+)"]').click()
    await page.waitForTimeout(300)
    const l2 = await label(before)
    const r2 = await label(after)
    await before.locator('button[title="適合視窗 (F)"]').click()
    await after.locator('button[title="適合視窗 (F)"]').click()
    await page.waitForTimeout(300)
    const l3 = await label(before)
    const r3 = await label(after)
    h.item('N18', l0 === r0 && parseInt(l1) > parseInt(l0) && r1 === r0 && l2 === l1 && parseInt(r2) > parseInt(r1) && l3 === l0 && r3 === r0, `fit ${l0}/${r0} → left+ ${l1}/${r1} → right++ ${l2}/${r2} → fit ${l3}/${r3}`)
  })

  await h.step('N16 驗證訊息', async () => {
    await openTool('thr')
    const thr = field('threshold').locator('input[type=number]')
    await thr.fill('999')
    await page.waitForTimeout(400)
    const msg = await field('threshold').innerText()
    await thr.fill('')
    await page.waitForTimeout(300)
    const req = await field('threshold').innerText()
    await h.shot(page, 'tool-validation')
    await thr.fill('60')
    h.item('N16', msg.includes('不能大於 255'), `max=${msg.replace(/\n/g, '|')}（必填訊息已在 F04／I20 驗證）`)
  })

  await h.step('N04 N05 boolean／select／visible_when', async () => {
    const invert = field('invert').getByRole('checkbox')
    const checked = await invert.isChecked()
    await invert.click()
    await page.waitForTimeout(300)
    const toggled = (await invert.isChecked()) !== checked
    const method = field('method').locator('select')
    const thrVisible = (await field('threshold').count()) === 1
    await method.selectOption('adaptive_mean')
    await page.waitForTimeout(300)
    const adaptive = (await field('block').count()) === 1 && (await field('c').count()) === 1 && (await field('threshold').count()) === 0
    await method.selectOption('otsu')
    await page.waitForTimeout(300)
    const otsu = (await field('threshold').count()) === 0 && (await field('block').count()) === 0
    await h.shot(page, 'tool-select-visible-when')
    await method.selectOption('fixed')
    await page.waitForTimeout(300)
    const fixed = (await field('threshold').count()) === 1
    await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => null)
    h.item('N04', toggled, 'checkbox 未切換')
    h.item('N05', thrVisible && adaptive && otsu && fixed, `fixed→thr=${thrVisible} adaptive=${adaptive} otsu=${otsu} back=${fixed}`)
  })

  await h.step('N02 N13 text／output_key', async () => {
    await openTool('ok')
    const label = field('label').locator('input')
    await label.fill('PASS')
    const w = waitPreview()
    const r = await w
    const body = r ? JSON.parse(r.postData() || '{}') : {}
    const saved = body.graph?.nodes?.find((n) => n.id === 'ok')?.params?.label
    h.item('N02', (await label.getAttribute('type')) !== 'number' && saved === 'PASS', `type=${await label.getAttribute('type')} draft=${saved}`)
    await openTool('out')
    const name = field('name').locator('input')
    const mono = await name.evaluate((el) => el.className.includes('font-mono'))
    await name.fill('hole_count_2')
    const r2 = await waitPreview()
    const b2 = r2 ? JSON.parse(r2.postData() || '{}') : {}
    h.item('N13', mono && b2.graph?.nodes?.find((n) => n.id === 'out')?.params?.name === 'hole_count_2', `mono=${mono}`)
  })

  await h.step('N08 source', async () => {
    await openTool('src')
    const sel = field('source_id').locator('select')
    const opts = await sel.locator('option').evaluateAll((els) => els.map((o) => ({ v: o.value, t: o.textContent, d: o.disabled })))
    const hasSynthetic = opts.some((o) => o.t.includes('合成'))
    const disabledOpt = opts.find((o) => o.t.includes('E2E 停用來源'))
    const placeholder = opts[0].v === '' && opts[0].t.includes('選擇影像來源')
    const w = waitPreview()
    await sel.selectOption('')
    const r = await w
    const body = r ? JSON.parse(r.postData() || '{}') : {}
    const val = body.graph?.nodes?.find((n) => n.id === 'src')?.params?.source_id
    await sel.selectOption('1')
    await waitPreview()
    h.item('N08', hasSynthetic && disabledOpt?.d === true && placeholder && val === null, `opts=${JSON.stringify(opts)} cleared=${val}`)
  })

  await h.step('N21 錯誤顯示', async () => {
    await header().locator('input[type=checkbox]').uncheck()
    const mode = field('mode').locator('select')
    await mode.selectOption('input')
    await page.locator('[data-testid=tool-message]').waitFor({ timeout: 10000 }).catch(() => null)
    const msg = await page.locator('[data-testid=tool-message]').innerText().catch(() => '')
    const cls = await page.locator('[data-testid=tool-message]').getAttribute('class').catch(() => '')
    const refTxt = await page.getByTestId('tool-reference').innerText()
    await h.shot(page, 'tool-error')
    await mode.selectOption('auto')
    await header().locator('input[type=checkbox]').check().catch(() => null)
    await waitPreview()
    await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => null)
    h.item('N21', msg.includes('暫存影像') && cls.includes('bg-critical-soft') && refTxt.includes('錯誤'), `msg=${msg} class=${cls} ref=${refTxt.slice(0, 80).replace(/\n/g, '|')}`)
  })

  await h.step('N10 color', async () => {
    await openTool('cc')
    const color = field('color').locator('input[type=color]')
    const hex = field('color').locator('input.font-mono')
    await hex.fill('#ff0000')
    await page.waitForTimeout(200)
    const cv = await color.inputValue()
    await color.evaluate((el) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, '#00ff00')
      el.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await page.waitForTimeout(200)
    const hv = await hex.inputValue()
    await h.shot(page, 'tool-color')
    h.item('N10', cv === '#ff0000' && hv === '#00ff00', `color=${cv} hex=${hv}`)
  })

  await h.step('N12 expression', async () => {
    await openTool('fm')
    const ta = field('expression').locator('textarea')
    const mono = await ta.evaluate((el) => el.className.includes('font-mono'))
    await ta.fill('a * 2')
    const r = await waitPreview()
    const body = r ? JSON.parse(r.postData() || '{}') : {}
    h.item('N12', mono && (await ta.getAttribute('rows')) === '2' && body.graph?.nodes?.find((n) => n.id === 'fm')?.params?.expression === 'a * 2', `mono=${mono} rows=${await ta.getAttribute('rows')}`)
  })

  await h.step('N14 multiline 與 model asset', async () => {
    const model = await h.api.raw('POST', '/vision/assets', { multipart: { file: { name: 'e2e-model.onnx', mimeType: 'application/octet-stream', buffer: Buffer.from('x') }, kind: 'model', name: 'e2e-model.onnx' } })
    const modelAsset = await model.json()
    await openTool('dl')
    const ta = field('labels').locator('textarea')
    const rows = await ta.getAttribute('rows')
    await ta.fill('cat\ndog')
    const sel = field('model').locator('select')
    const opts = await sel.locator('option').allInnerTexts()
    const onlyModels = opts.some((o) => o.includes('e2e-model.onnx')) && !opts.some((o) => o.includes('E2E 影像資產'))
    const noScan = (await field('model').getByRole('button', { name: '從目前影像框選建立範本' }).count()) === 0
    const accept = await field('model').locator('input[type=file]').getAttribute('accept')
    await h.shot(page, 'tool-dl-multiline')
    await h.api.del(`/vision/assets/${modelAsset.id}`)
    h.item('N14', rows === '4' && onlyModels && noScan && accept === null, `rows=${rows} opts=${opts.join('|')} noScan=${noScan} accept=${accept}`)
  })

  await h.step('N09 asset（影像）', async () => {
    await openTool('tm')
    const f = field('template')
    const sel = f.locator('select')
    const png = await h.makePng(page, { w: 80, h: 60, dots: 1 })
    await f.locator('input[type=file]').setInputFiles({ name: 'e2e-upload-template.png', mimeType: 'image/png', buffer: png })
    const t1 = await h.toast(page, /已上傳「e2e-upload-template.png」/)
    await page.waitForTimeout(600)
    const v1 = await sel.inputValue()
    const opt1 = await sel.locator(`option[value="${v1}"]`).innerText().catch(() => '')
    // 從目前影像框選建立範本
    const scan = f.getByRole('button', { name: '從目前影像框選建立範本' })
    const scanEnabled = !(await scan.isDisabled())
    await scan.click()
    const hint = (await f.innerText()).includes('在影像上框選範圍後按「建立」')
    const createBtn = page.locator('[data-testid=tool-before]').getByRole('button', { name: '建立範本' })
    const createDisabled = await createBtn.isDisabled()
    const box = await page.locator('[data-testid=tool-before] canvas.touch-none').boundingBox()
    const x0 = box.x + box.width * 0.4
    const y0 = box.y + box.height * 0.4
    await page.mouse.move(x0, y0)
    await page.mouse.down()
    await page.mouse.move(x0 + 40, y0 + 30, { steps: 4 })
    await page.mouse.move(x0 + 120, y0 + 90, { steps: 8 })
    await page.mouse.up()
    await page.waitForTimeout(300)
    const createEnabled = !(await createBtn.isDisabled())
    await createBtn.click()
    const dlg = h.dialog(page)
    await dlg.getByLabel('範本名稱').fill('E2E 框選範本')
    await dlg.getByLabel('範本名稱').press('Enter')
    const t2 = await h.toast(page, /已建立範本「E2E 框選範本」/)
    await h.waitGone(page.locator('[role=dialog]'))
    await page.waitForTimeout(500)
    const v2 = await sel.inputValue()
    const opt2 = await sel.locator(`option[value="${v2}"]`).innerText().catch(() => '')
    const assets = await h.api.get('/vision/assets?kind=image')
    const created = assets.items.find((a) => a.name === 'E2E 框選範本')
    await h.shot(page, 'tool-asset-template')
    h.item('N09', Boolean(t1) && opt1 === 'e2e-upload-template.png' && scanEnabled && hint && createDisabled && createEnabled && Boolean(t2) && opt2 === 'E2E 框選範本' && created && created.meta.width > 20, `t1=${t1} opt1=${opt1} scan=${scanEnabled} hint=${hint} create ${createDisabled}→${createEnabled} t2=${t2} opt2=${opt2} asset=${created ? `${created.meta.width}×${created.meta.height}` : 'none'}`)
  })

  await h.step('N22 儲存與返回', async () => {
    await openTool('blob')
    const minArea = field('min_area').locator('input[type=number]')
    await minArea.fill('456')
    await waitPreview()
    await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => null)
    const dirty = (await header().innerText()).includes('有未儲存的變更')
    // dirty 離開到其他頁 → confirm（取消）
    h.nextDialog(page, false)
    await page.getByTestId('nav-flows').click()
    await page.waitForTimeout(500)
    const stayed = /\/tools\/blob$/.test(page.url())
    // 返回編輯器不攔
    await page.getByTestId('btn-back').click()
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
    const editorDirty = (await page.locator('[data-testid=editor-toolbar]').innerText()).includes('有未儲存的變更')
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(300)
    await page.locator('.react-flow__node[data-id="blob"]').click()
    await page.getByTestId('open-tool-page').click()
    await page.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
    await page.waitForTimeout(500)
    const kept = await field('min_area').locator('input[type=number]').inputValue()
    await page.keyboard.press('Control+s')
    const t = await h.toast(page, /流程已儲存/)
    const saved = (await h.api.get(`/vision/flows/${flowId}`)).graph.nodes.find((n) => n.id === 'blob').params.min_area
    const savedLabel = (await page.getByTestId('tool-save').innerText()).includes('已儲存')
    h.item('N22', dirty && stayed && editorDirty && kept === '456' && Boolean(t) && saved === 456 && savedLabel, `dirty=${dirty} stayed=${stayed} editorDirty=${editorDirty} kept=${kept} toast=${t} saved=${saved} label=${savedLabel}`)
  })

  await h.step('N23 找不到步驟', async () => {
    await page.goto(`${BASE}/flows/${flowId}/tools/nope`)
    await page.waitForTimeout(1500)
    const txt = await page.locator('main').innerText()
    const link = (await page.getByRole('link', { name: '返回編輯器' }).count()) === 1
    await h.shot(page, 'tool-not-found')
    h.item('N23', txt.includes('找不到步驟「nope」') && link, `text=${txt.slice(0, 80).replace(/\n/g, '|')} link=${link}`)
  })

  // N11（kind=json）：v0.2 起由 write_modbus 的 mapping 欄位觸發，在 full-flowio.mjs IO07 回報

  await h.api.del(`/vision/sources/${disabledSrc.id}`)
  await context.close()
}
