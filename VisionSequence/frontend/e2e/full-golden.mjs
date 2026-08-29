/** 模組 golden：Golden Set 頁（Y）＋批次測試「存為 Golden Set」。用示範流程副本（E2E Golden）。 */
import { BASE, WORKER } from './full-lib.mjs'
import { ensureWorker } from './full-teach.mjs'

export async function run(h) {
  await h.loginAdmin()
  await h.api.del('/vision/lock')
  await ensureWorker(h)
  const context = await h.newContext({ token: h.token })
  const page = await h.newPage(context, '[golden]')
  const flowId = await h.cloneDemo('E2E Golden')
  const url = `${BASE}/flows/${flowId}/golden`
  const casesOf = async () => (await h.api.get(`/vision/flows/${flowId}/golden`)).items
  const openGolden = async () => {
    await page.goto(url)
    await page.getByTestId('golden-regress').waitFor({ timeout: 15000 })
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(400)
  }
  const files = async (prefix, n) => {
    const out = []
    for (let i = 0; i < n; i += 1) out.push({ name: `${prefix}${i + 1}.png`, mimeType: 'image/png', buffer: await h.makePng(page, { w: 320, h: 240, dots: (i % 5) + 2, seed: i + 11 }) })
    return out
  }
  const regressAndWait = async () => {
    await page.getByTestId('golden-regress').click()
    await page.getByTestId('golden-regress').filter({ hasText: /回歸中/ }).waitFor({ timeout: 3000 }).catch(() => null)
    await page.getByTestId('golden-regress').filter({ hasText: /回歸中/ }).waitFor({ state: 'detached', timeout: 90000 }).catch(() => null)
    await page.getByTestId('golden-result').waitFor({ timeout: 90000 })
    await page.waitForTimeout(500)
  }

  await h.step('Y01 空狀態與控制列', async () => {
    await openGolden()
    const main = await page.locator('main').innerText()
    const useDraft = page.getByRole('checkbox', { name: '用目前畫布未儲存的圖' })
    const saveBaseline = page.getByRole('checkbox', { name: '存為基準' })
    const draftDisabled = await useDraft.isDisabled()
    const baselineEnabled = !(await saveBaseline.isDisabled())
    const failUnder = (await page.getByTestId('golden-fail-under').count()) === 1
    const regressDisabled = await page.getByTestId('golden-regress').isDisabled()
    const baselineTxt = await page.getByTestId('golden-baseline').innerText()
    const back = (await page.getByRole('link', { name: '返回編輯器' }).getAttribute('href')) === `/flows/${flowId}`
    await h.shot(page, 'golden-empty')
    h.item('Y01', main.includes('還沒有案例') && main.includes('Golden Set') && main.includes('E2E Golden') && draftDisabled && baselineEnabled && failUnder && regressDisabled && baselineTxt.includes('尚未儲存基準') && back, `empty=${main.includes('還沒有案例')} draftDis=${draftDisabled} baselineEn=${baselineEnabled} failUnder=${failUnder} regressDis=${regressDisabled} baseline=${baselineTxt} back=${back}`)
  })

  await h.step('Y02 上傳影像', async () => {
    await page.getByTestId('golden-upload-expect').selectOption('ng')
    await page.getByLabel('備註', { exact: true }).fill('e2e note')
    await page.getByTestId('golden-upload-input').setInputFiles(await files('e2e-up', 3))
    const t = await h.toast(page, /已新增 3 個案例/)
    await page.waitForTimeout(800)
    const rows = await page.getByTestId('golden-case-expect').count()
    const expects = await page.getByTestId('golden-case-expect').evaluateAll((els) => els.map((e) => e.value))
    const thumbs = await page.locator('main table img').evaluateAll((els) => els.filter((e) => e.complete && e.naturalWidth > 0).length)
    const notes = await page.locator('main tbody tr').first().locator('td').nth(3).locator('input').inputValue()
    const noBaseline = (await page.locator('main tbody').innerText()).includes('尚無基準')
    const count = await page.locator('main').getByText(/案例\s*\(3\)/).count()
    const noteCleared = (await page.getByLabel('備註', { exact: true }).inputValue()) === ''
    await h.shot(page, 'golden-uploaded')
    h.item('Y02', Boolean(t) && rows === 3 && expects.every((v) => v === 'ng') && thumbs === 3 && notes === 'e2e note' && noBaseline && count === 1 && noteCleared, `t=${t} rows=${rows} expects=${expects} thumbs=${thumbs} note=${notes} noBaseline=${noBaseline} count=${count} noteCleared=${noteCleared}`)
  })

  await h.step('Y03 直接改期望／名稱／備註', async () => {
    const row = page.locator('main tbody tr').first()
    await row.getByTestId('golden-case-expect').selectOption('ok')
    await page.waitForTimeout(600)
    await row.getByTestId('golden-case-name').fill('e2e-renamed')
    await row.getByTestId('golden-case-name').press('Tab')
    await page.waitForTimeout(600)
    await row.locator('td').nth(3).locator('input').fill('note2')
    await row.locator('td').nth(3).locator('input').press('Tab')
    await page.waitForTimeout(600)
    const list = await casesOf()
    const c = list[0]
    h.item('Y03', c.expect_status === 'ok' && c.name === 'e2e-renamed' && c.note === 'note2', `case=${JSON.stringify({ e: c.expect_status, n: c.name, note: c.note })}`)
  })

  await h.step('Y04 刪除案例', async () => {
    const last = page.locator('main tbody tr').last()
    const name = await last.getByTestId('golden-case-name').inputValue()
    await last.getByTestId('golden-case-delete').click()
    const dlg = h.dialog(page)
    await dlg.waitFor()
    const msg = await dlg.innerText()
    const danger = (await dlg.locator('button.btn-danger, button[class*=critical]').count()) >= 1
    await dlg.getByRole('button', { name: '刪除', exact: true }).click()
    const t = await h.toast(page, /已刪除案例/)
    await page.waitForTimeout(500)
    const rows = await page.getByTestId('golden-case-expect').count()
    h.item('Y04', msg.includes(name) && Boolean(t) && rows === 2, `msg=${msg.replace(/\n/g, ' ').slice(0, 60)} danger=${danger} t=${t} rows=${rows}`)
  })

  await h.step('Y05 批次測試存為 Golden Set', async () => {
    await page.goto(`${BASE}/flows/${flowId}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
    await page.getByTestId('btn-batch').click()
    const dlg = h.dialog(page)
    await dlg.waitFor()
    await page.getByTestId('batch-input').setInputFiles(await files('e2e-batch', 3))
    await page.getByTestId('batch-run').click()
    await page.getByTestId('batch-table').waitFor({ timeout: 60000 })
    await page.waitForTimeout(500)
    const disabled0 = await page.getByTestId('batch-save-golden').isDisabled()
    await page.getByTestId('batch-pick-all').click()
    const picked = await page.getByTestId('batch-pick').evaluateAll((els) => els.filter((e) => e.checked).length)
    const enabled = !(await page.getByTestId('batch-save-golden').isDisabled())
    const statuses = await page.getByTestId('batch-row').locator('span.rounded-full').allInnerTexts()
    await h.shot(page, 'golden-batch-pick')
    await page.getByTestId('batch-save-golden').click()
    const t = await h.toast(page, /已存 3 個案例到 Golden Set/)
    await page.waitForTimeout(500)
    await page.getByTestId('batch-open-golden').click()
    await page.waitForURL(/\/golden$/, { timeout: 5000 })
    await page.getByTestId('golden-regress').waitFor({ timeout: 15000 })
    await page.waitForTimeout(800)
    const list = await casesOf()
    const batchCases = list.filter((c) => /^e2e-batch/.test(c.name))
    const expectMatch = batchCases.every((c, i) => statuses[i] ? c.expect_status === (statuses[i] === 'OK' ? 'ok' : statuses[i] === 'NG' ? 'ng' : 'any') : true)
    const rows = await page.getByTestId('golden-case-expect').count()
    await h.shot(page, 'golden-after-batch')
    h.item('Y05', disabled0 && picked === 3 && enabled && Boolean(t) && batchCases.length === 3 && expectMatch && rows === 5, `disabled0=${disabled0} picked=${picked} enabled=${enabled} t=${t} batch=${batchCases.map((c) => `${c.name}:${c.expect_status}`)} statuses=${statuses} rows=${rows}`)
  })

  let caseIds = []
  const casesCard = () => page.locator('main .card').last()
  await h.step('Y06 回歸並存為基準', async () => {
    // 期望先全設 any → 一定全符合
    for (const c of await casesOf()) await h.api.patch(`/vision/flows/${flowId}/golden/${c.id}`, { expect_status: 'any' })
    await openGolden()
    await page.getByRole('checkbox', { name: '存為基準' }).check()
    await page.getByTestId('golden-fail-under').fill('0.5')
    await regressAndWait()
    const t = await h.toast(page, /已存為基準/, 3000)
    const result = page.getByTestId('golden-result')
    const kpis = await page.getByTestId('golden-kpi').locator('> div').count()
    const kpiTxt = await page.getByTestId('golden-kpi').innerText()
    const head = await result.locator('.card').first().innerText()
    const noRegressed = (await page.getByTestId('no-regressed').count()) === 1
    const rows = await page.getByTestId('golden-result-row').count()
    const baselineTxt = await page.getByTestId('golden-baseline').innerText()
    const lastResults = await casesCard().locator('tbody tr td:nth-child(5) span.rounded-full').count()
    const bl = await h.api.get(`/vision/flows/${flowId}/golden/baseline`)
    caseIds = (await casesOf()).map((c) => c.id)
    await h.shot(page, 'golden-regress-baseline', { full: true })
    h.item('Y06', Boolean(t) && kpis === 8 && /符合率\s*100%/.test(kpiTxt.replace(/\n/g, ' ')) && head.includes('通過') && head.includes('已存為基準') && noRegressed && rows === 5 && baselineTxt.includes('基準：流程 v') && lastResults === 5 && Boolean(bl.baseline), `t=${t} kpis=${kpis} kpi=${kpiTxt.replace(/\n/g, ' ').slice(0, 80)} head=${head.replace(/\n/g, ' ').slice(0, 80)} noRegressed=${noRegressed} rows=${rows} baseline=${baselineTxt} last=${lastResults} api=${Boolean(bl.baseline)}`)
  })

  let originalGraph = null
  await h.step('Y07 Y09 退步清單與影像視窗', async () => {
    const bl = await h.api.get(`/vision/flows/${flowId}/golden/baseline`)
    const results = bl.baseline.results
    // 期望 = 基準狀態；再改圖（孔數判斷門檻）讓部分案例狀態翻轉 → 基準符合、這次不符 = 退步
    for (const id of caseIds) {
      const st = results[String(id)]?.status
      await h.api.patch(`/vision/flows/${flowId}/golden/${id}`, { expect_status: st === 'ok' ? 'ok' : st === 'ng' ? 'ng' : 'any' })
    }
    originalGraph = (await h.api.get(`/vision/flows/${flowId}`)).graph
    const changed = structuredClone(originalGraph)
    const cmp = changed.nodes.find((n) => n.id === 'cmp')
    cmp.params.threshold = Number(cmp.params.threshold) === 3 ? 2 : 3
    await h.api.patch(`/vision/flows/${flowId}`, { graph: changed })
    await openGolden()
    await page.getByTestId('golden-fail-under').fill('0.99')
    await regressAndWait()
    const regressed = await page.getByTestId('regressed-row').count()
    const regTxt = regressed ? await page.getByTestId('regressed-row').first().innerText() : ''
    const head = await page.getByTestId('golden-result').locator('.card').first().innerText()
    const notPassed = head.includes('未通過')
    const mismatch = Number(/不符\s*(\d+)/.exec((await page.getByTestId('golden-kpi').innerText()).replace(/\n/g, ' '))?.[1] ?? -1)
    await h.shot(page, 'golden-regressed', { full: true })
    h.item('Y07', regressed >= 1 && regressed === mismatch && /→/.test(regTxt) && /OK|NG/.test(regTxt) && notPassed, `regressed=${regressed} mismatch=${mismatch} txt=${regTxt.replace(/\n/g, ' ').slice(0, 100)} notPassed=${notPassed}`)

    // Y09：退步列有影像 → 影像視窗
    const row = page.getByTestId('regressed-row').first()
    const hasImg = (await row.locator('img').count()) === 1
    await row.getByRole('button', { name: '在影像視窗檢視' }).click()
    const dlg = h.dialog(page)
    await dlg.waitFor()
    const title = await dlg.locator('h2').innerText()
    await dlg.locator('canvas').first().waitFor({ timeout: 20000 })
    await page.waitForTimeout(1500)
    const image = await page.evaluate(() => {
      const c = document.querySelector('[role=dialog] canvas')
      if (!c) return false
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data
      let non = 0
      for (let i = 0; i < d.length; i += 4 * 97) if (d[i + 3] > 0) non++
      return non > 50
    })
    const badge = await dlg.locator('span.rounded-full').first().innerText()
    await h.shot(page, 'golden-viewer')
    await page.keyboard.press('Escape')
    const closed = await h.waitGone(dlg)
    await page.getByTestId('golden-result').getByRole('button', { name: '全部', exact: true }).click()
    const offIcons = await page.getByTestId('golden-cases-result').locator('svg.lucide-image-off').count()
    const nonClickable = await page.getByTestId('golden-result-row').evaluateAll((els) => els.filter((e) => !e.className.includes('cursor-pointer')).length)
    h.item('Y09', hasImg && title.includes('正在檢視') && image && /OK|NG/.test(badge) && closed && offIcons >= 1 && nonClickable === offIcons, `img=${hasImg} title=${title} image=${image} badge=${badge} closed=${closed} off=${offIcons} nonClickable=${nonClickable}`)

    // 進步：把「有不符」的結果存成基準 → 改回圖 → 再回歸
    await page.getByRole('checkbox', { name: '存為基準' }).check()
    await regressAndWait()
    await page.getByRole('checkbox', { name: '存為基準' }).uncheck()
    await h.api.patch(`/vision/flows/${flowId}`, { graph: originalGraph })
    await openGolden()
    await regressAndWait()
    const improved = await page.getByTestId('improved-row').count()
    const impTxt = improved ? await page.getByTestId('improved-row').first().innerText() : ''
    const noRegressed = (await page.getByTestId('no-regressed').count()) === 1
    await h.shot(page, 'golden-improved', { full: true })
    h.item('Y07', improved === regressed && /→/.test(impTxt) && noRegressed, `improved=${improved}（期望 ${regressed}） imp=${impTxt.replace(/\n/g, ' ').slice(0, 60)} noRegressed=${noRegressed}`)
  })

  await h.step('Y08 篩選', async () => {
    // 目前狀態：不符 0、與基準不同 = 進步的案例數
    const improved = await page.getByTestId('improved-row').count()
    const counter = () => page.getByTestId('golden-result').locator('span.tnum.text-xs').first().innerText()
    const c0 = await counter()
    const pressed0 = await page.getByTestId('golden-result').getByRole('button', { name: '全部', exact: true, pressed: true }).count()
    await page.getByTestId('golden-result').getByRole('button', { name: '只看不符' }).click()
    const c1 = await counter()
    const dash = (await page.getByTestId('golden-cases-result').locator('tbody').innerText()).trim()
    await page.getByTestId('golden-result').getByRole('button', { name: '只看與基準不同' }).click()
    const c2 = await counter()
    await h.shot(page, 'golden-filter')
    await page.getByTestId('golden-result').getByRole('button', { name: '全部', exact: true }).click()
    const c3 = await counter()
    h.item('Y08', c0 === '5 / 5' && pressed0 === 1 && c1 === '0 / 5' && dash === '—' && c2 === `${improved} / 5` && improved >= 1 && c3 === '5 / 5', `c0=${c0} pressed=${pressed0} c1=${c1} dash=${dash} c2=${c2} improved=${improved} c3=${c3}`)
  })

  await h.step('Y10 用目前畫布未儲存的圖', async () => {
    await page.goto(`${BASE}/flows/${flowId}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
    const name = page.locator('[data-testid=editor-toolbar] input').first()
    await name.fill('E2E Golden 草稿')
    await page.waitForTimeout(200)
    h.nextDialog(page, true)
    await page.getByTestId('btn-golden').click()
    await page.waitForURL(/\/golden$/, { timeout: 5000 })
    await page.getByTestId('golden-regress').waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
    const cb = page.getByRole('checkbox', { name: '用目前畫布未儲存的圖' })
    const enabled = !(await cb.isDisabled())
    const hint = await page.locator('main').getByText('有未儲存的變更').count()
    await cb.check()
    await regressAndWait()
    const head = await page.getByTestId('golden-result').locator('.card').first().innerText()
    await h.shot(page, 'golden-draft')
    h.item('Y10', enabled && hint === 1 && head.includes('用目前畫布未儲存的圖'), `enabled=${enabled} hint=${hint} head=${head.replace(/\n/g, ' ').slice(0, 80)}`)
  })

  await h.step('Y11 合格門檻非法', async () => {
    const release = h.allowStatus(/422 POST .*\/regress/)
    await page.getByTestId('golden-fail-under').fill('2')
    await page.getByTestId('golden-regress').click()
    const t = await h.toast(page, /fail_under|0 與 1/)
    release()
    await page.getByTestId('golden-fail-under').fill('')
    h.item('Y11', Boolean(t), `toast=${t}`)
  })

  await h.step('Y12 worker 唯讀', async () => {
    const demo = h.demoFlow()
    // 共用示範流程放一個案例，讓 worker 看得到表列（結束時刪）
    const png = await h.makePng(page, { w: 200, h: 150, dots: 3, seed: 5 })
    const up = await h.api.raw('POST', `/vision/flows/${demo.id}/golden`, { multipart: { images: { name: 'e2e-shared.png', mimeType: 'image/png', buffer: png }, expect_status: 'any' } })
    const created = (await up.json().catch(() => null))?.items ?? []
    const wtoken = await h.login(WORKER)
    const wctx = await h.newContext({ token: wtoken })
    const worker = await h.newPage(wctx, '[golden-worker]')
    await worker.goto(`${BASE}/flows/${demo.id}/golden`)
    await worker.getByTestId('golden-regress').waitFor({ timeout: 15000 })
    await worker.waitForLoadState('networkidle')
    await worker.waitForTimeout(500)
    const ro = (await worker.locator('main').innerText()).includes('只有擁有者或管理員能修改案例')
    const noUpload = (await worker.getByTestId('golden-upload').count()) === 0
    const expectDis = await worker.getByTestId('golden-case-expect').first().isDisabled()
    const nameDis = await worker.getByTestId('golden-case-name').first().isDisabled()
    const delDis = await worker.getByTestId('golden-case-delete').first().isDisabled()
    const baselineDis = await worker.getByRole('checkbox', { name: '存為基準' }).isDisabled()
    const regressEnabled = !(await worker.getByTestId('golden-regress').isDisabled())
    await h.shot(worker, 'golden-worker-readonly')
    await wctx.close()
    for (const c of created) await h.api.del(`/vision/flows/${demo.id}/golden/${c.id}`)
    h.item('Y12', ro && noUpload && expectDis && nameDis && delDis && baselineDis && regressEnabled, `ro=${ro} noUpload=${noUpload} expect=${expectDis} name=${nameDis} del=${delDis} baseline=${baselineDis} regress=${regressEnabled} created=${created.length}`)
  })

  await h.step('Y13 1280 與深色', async () => {
    const small = await h.newContext({ token: h.token, viewport: { width: 1280, height: 800 } })
    const sp = await h.newPage(small, '[golden-1280]')
    await sp.goto(url)
    await sp.getByTestId('golden-regress').waitFor({ timeout: 15000 })
    await sp.waitForTimeout(500)
    await sp.getByTestId('golden-regress').click()
    await sp.getByTestId('golden-result').waitFor({ timeout: 90000 })
    await sp.waitForTimeout(500)
    const info = await sp.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
    await h.shot(sp, 'golden-1280', { full: true })
    await small.close()
    const dark = await h.newContext({ token: h.token, colorScheme: 'dark' })
    await dark.addInitScript(() => localStorage.setItem('vs.theme', 'dark'))
    const dp = await h.newPage(dark, '[golden-dark]')
    await dp.goto(url)
    await dp.getByTestId('golden-regress').waitFor({ timeout: 15000 })
    await dp.waitForTimeout(500)
    await dp.getByTestId('golden-regress').click()
    await dp.getByTestId('golden-result').waitFor({ timeout: 90000 })
    await dp.waitForTimeout(500)
    await h.shot(dp, 'golden-dark', { full: true })
    const isDark = await dp.evaluate(() => document.documentElement.classList.contains('dark'))
    await dark.close()
    h.item('Y13', info.sw <= info.cw + 1 && isDark, `scroll=${info.sw}/${info.cw} dark=${isDark}`)
  })

  await context.close()
}
