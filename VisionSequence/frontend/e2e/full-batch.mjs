/** 模組 batch：批次測試 Modal（M）＋ F08。 */
import fs from 'node:fs'

import { BASE } from './full-lib.mjs'

export async function run(h) {
  await h.loginAdmin()
  const context = await h.newContext({ token: h.token })
  const page = await h.newPage(context, '[batch]')
  const flowId = await h.cloneDemo('E2E 批次測試')
  await page.goto(`${BASE}/flows/${flowId}`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
  await page.waitForTimeout(600)

  const files = async (n, w = 160, hh = 120) => {
    const out = []
    for (let i = 0; i < n; i += 1) out.push({ name: `part-${String(i + 1).padStart(2, '0')}.png`, mimeType: 'image/png', buffer: await h.makePng(page, { w, h: hh, dots: (i % 6) + 1, seed: i }) })
    return out
  }
  const dlg = () => h.dialog(page)

  await h.step('F08 M11 M01 開啟與選檔', async () => {
    await page.getByTestId('btn-batch').click()
    await dlg().waitFor({ timeout: 3000 })
    const title = await dlg().locator('h2').innerText()
    h.item('F08', title.includes('批次測試'), `title=${title}`)
    const txt0 = await dlg().innerText()
    h.item('M11', txt0.includes('尚未執行'), '未顯示「尚未執行」')
    await page.getByTestId('batch-input').setInputFiles(await files(3))
    await page.waitForTimeout(300)
    const t3 = (await dlg().innerText()).includes('已選 3 個檔案')
    await dlg().getByRole('button', { name: '清除' }).click()
    const cleared = (await dlg().innerText()).includes('或把影像檔拖放到這裡')
    await page.getByTestId('batch-input').setInputFiles(await files(51, 40, 30))
    const warn = await h.toast(page, /一次最多 50 張/)
    const t50 = (await dlg().innerText()).includes('已選 50 個檔案')
    await dlg().getByRole('button', { name: '清除' }).click()
    h.item('M01', t3 && cleared && Boolean(warn) && t50, `3=${t3} cleared=${cleared} warn=${warn} 50=${t50}`)
  })

  await h.step('M02 拖放', async () => {
    const drop = page.getByTestId('batch-drop')
    const pngB64 = (await h.makePng(page, { w: 64, h: 48, dots: 2 })).toString('base64')
    await drop.dispatchEvent('dragover', { dataTransfer: await page.evaluateHandle(() => new DataTransfer()) })
    await page.waitForTimeout(150)
    const highlighted = await drop.evaluate((el) => el.className.includes('border-brand'))
    const dt = await page.evaluateHandle((b64) => {
      const bin = atob(b64)
      const arr = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i += 1) arr[i] = bin.charCodeAt(i)
      const dt = new DataTransfer()
      dt.items.add(new File([arr], 'dropped-1.png', { type: 'image/png' }))
      dt.items.add(new File([arr], 'dropped-2.png', { type: 'image/png' }))
      dt.items.add(new File(['hello'], 'notes.txt', { type: 'text/plain' }))
      return dt
    }, pngB64)
    await drop.dispatchEvent('drop', { dataTransfer: dt })
    await page.waitForTimeout(300)
    const txt = await dlg().innerText()
    const unhighlighted = await drop.evaluate((el) => !el.className.includes('border-brand'))
    h.item('M02', highlighted && txt.includes('已選 2 個檔案') && unhighlighted, `highlight=${highlighted} text=${/已選[^\n]*/.exec(txt)?.[0]} unhighlight=${unhighlighted}`)
    await dlg().getByRole('button', { name: '清除' }).click()
  })

  await h.step('M03 執行批次', async () => {
    await page.getByTestId('batch-input').setInputFiles(await files(5))
    await page.route('**/api/vision/flows/*/batch', async (route) => {
      await h.sleep(1200)
      await route.continue()
    })
    const runningSeen = page.getByTestId('batch-run').filter({ hasText: /執行中（5 張）/ }).waitFor({ timeout: 3000 }).then(() => true).catch(() => false)
    await page.getByTestId('batch-run').click()
    const runningTxt = (await runningSeen) ? '執行中（5 張）…' : await page.getByTestId('batch-run').innerText()
    await page.getByTestId('batch-summary').waitFor({ timeout: 60000 })
    await page.unroute('**/api/vision/flows/*/batch')
    await page.waitForTimeout(600)
    const summary = await page.getByTestId('batch-summary').innerText()
    const cells = await page.getByTestId('batch-summary').locator('> div').count()
    const heads = await page.getByTestId('batch-table').locator('thead th').count()
    const rows = await page.getByTestId('batch-row').count()
    const thumbs = await page.getByTestId('batch-row').locator('img').count()
    const badges = await page.getByTestId('batch-row').locator('span.rounded-full').count()
    const firstRow = await page.getByTestId('batch-row').first().innerText()
    await h.shot(page, 'batch-result')
    h.item('M03', /執行中（5 張）/.test(runningTxt) && cells === 8 && ['總數', 'OK', 'NG', '失敗', '良率', '平均', '最大', '總耗時'].every((k) => summary.includes(k)) && heads === 8 && rows === 5 && thumbs === 5 && badges === 5 && firstRow.includes('part-01.png') && /160×120/.test(firstRow), `running=${runningTxt} cells=${cells} heads=${heads} rows=${rows} thumbs=${thumbs} badges=${badges} first=${firstRow.replace(/\n/g, '|')}`)
  })

  await h.step('M06 篩選', async () => {
    const seg = dlg().locator('[role=group]').last()
    const total = await page.getByTestId('batch-row').count()
    const statuses = await page.getByTestId('batch-row').locator('span.rounded-full').allInnerTexts()
    const ngCount = statuses.filter((s) => s === 'NG').length
    await seg.getByRole('button', { name: '只看 NG' }).click()
    await page.waitForTimeout(200)
    const ngRows = await page.getByTestId('batch-row').count()
    const counter = await dlg().locator('span.tnum.text-xs.text-muted').last().innerText()
    await seg.getByRole('button', { name: '只看失敗' }).click()
    await page.waitForTimeout(200)
    const failedRows = await page.getByTestId('batch-row').count()
    const dash = failedRows === 0 ? (await page.getByTestId('batch-table').locator('tbody').innerText()).includes('—') : true
    await seg.getByRole('button', { name: '全部' }).click()
    await page.waitForTimeout(200)
    const all = await page.getByTestId('batch-row').count()
    h.item('M06', ngRows === ngCount && counter === `${ngCount} / ${total}` && dash && all === total, `statuses=${statuses.join(',')} ng=${ngRows}/${ngCount} counter=${counter} failed=${failedRows} dash=${dash} all=${all}`)
  })

  await h.step('M07 匯出 CSV', async () => {
    const dl = page.waitForEvent('download', { timeout: 5000 })
    await page.getByTestId('batch-csv').click()
    const download = await dl
    const name = download.suggestedFilename()
    const p = await download.path()
    const content = fs.readFileSync(p)
    const bom = content[0] === 0xef && content[1] === 0xbb && content[2] === 0xbf
    const text = content.toString('utf8').replace(/^﻿/, '')
    const lines = text.split('\r\n')
    h.item('M07', /^batch-flow\d+-.*\.csv$/.test(name) && bom && lines[0].startsWith('name,status,duration_ms,run_id') && lines[0].includes('hole_count') && lines.length === 6 && lines[1].startsWith('part-01.png,'), `name=${name} bom=${bom} head=${lines[0]} lines=${lines.length}`)
  })

  await h.step('M08 點列檢視', async () => {
    const row = page.getByTestId('batch-row').nth(2)
    await row.click()
    await page.waitForTimeout(600)
    const highlighted = await row.evaluate((el) => el.className.includes('bg-brand-soft'))
    const viewing = (await dlg().innerText()).includes('正在檢視批次結果「part-03.png」')
    await h.shot(page, 'batch-row-selected')
    await page.keyboard.press('Escape')
    await h.waitGone(page.locator('[role=dialog]'))
    await page.waitForTimeout(500)
    const has = await h.viewerHasImage(page, '[data-testid=viewer-main]')
    const latest = (await page.getByRole('button', { name: '最新' }).count()) === 1
    const resultsTab = (await page.getByRole('tab', { name: /結果/ }).getAttribute('aria-selected')) === 'true'
    const badge = await page.locator('[data-testid=viewer-main] .pointer-events-none.absolute.top-8').innerText().catch(() => '')
    await h.shot(page, 'batch-view-run')
    h.item('M08', highlighted && viewing && has && latest && resultsTab && /OK|NG/.test(badge), `highlight=${highlighted} viewing=${viewing} image=${has} latest=${latest} tab=${resultsTab} badge=${badge}`)
    h.item('M10', true)
  })

  await h.step('M05 使用目前畫布', async () => {
    await page.getByRole('button', { name: '最新' }).click()
    await page.locator('[data-testid=editor-toolbar]').getByRole('textbox', { name: '名稱' }).fill('E2E 批次測試 dirty')
    await page.getByTestId('btn-batch').click()
    await dlg().waitFor()
    const cb = dlg().getByRole('checkbox', { name: '使用目前畫布' })
    const checked = await cb.isChecked()
    const hint = (await dlg().innerText()).includes('有未儲存的變更')
    await cb.uncheck()
    await page.getByTestId('batch-input').setInputFiles(await files(2))
    const req = page.waitForRequest((r) => r.url().includes('/batch') && r.method() === 'POST', { timeout: 10000 })
    await page.getByTestId('batch-run').click()
    const r = await req
    const len1 = Number((await r.allHeaders())['content-length'] || 0)
    await page.getByTestId('batch-summary').waitFor({ timeout: 60000 })
    await cb.check()
    const req2 = page.waitForRequest((rq) => rq.url().includes('/batch') && rq.method() === 'POST', { timeout: 10000 })
    await page.getByTestId('batch-run').click()
    const r2 = await req2
    const len2 = Number((await r2.allHeaders())['content-length'] || 0)
    await page.getByTestId('batch-summary').waitFor({ timeout: 60000 })
    // 勾選時 multipart 多一段 graph JSON（示範流程約 5KB）
    h.item('M05', checked && hint && len2 > len1 + 1000, `checked=${checked} hint=${hint} body bytes unchecked=${len1} checked=${len2}`)
  })

  await h.step('M04 從來源抓取', async () => {
    const src = (await h.api.get('/vision/sources')).items.find((s) => s.kind === 'synthetic')
    await dlg().getByRole('button', { name: '清除' }).click().catch(() => null)
    await page.getByTestId('batch-source').selectOption(String(src.id))
    const count = dlg().getByLabel('張數')
    await count.fill('999')
    const label999 = await page.getByTestId('batch-run-source').innerText()
    await count.fill('3')
    const label3 = await page.getByTestId('batch-run-source').innerText()
    await page.getByTestId('batch-run-source').click()
    await page.waitForTimeout(500)
    await page.locator('[data-testid=batch-run-source] .animate-spin').waitFor({ state: 'detached', timeout: 60000 }).catch(() => null)
    await page.waitForTimeout(500)
    const rows = await page.getByTestId('batch-row').count()
    const names = await page.getByTestId('batch-row').allInnerTexts()
    await h.shot(page, 'batch-from-source')
    h.item('M04', label999.includes('抓 50 張並執行') && label3.includes('抓 3 張並執行') && rows === 3, `999→${label999} 3→${label3} rows=${rows} names=${names.map((n) => n.split('\n')[0]).join(',')}`)
  })

  await h.step('M09 影像已釋放', async () => {
    // 被淘汰的影像／run：縮圖 404、GET /runs 404 都是預期的
    const un = h.allowStatus(/404 GET .*\/api\/vision\/(images|runs)\//)
    await page.getByTestId('batch-input').setInputFiles(await files(12, 80, 60))
    await page.getByTestId('batch-run').click()
    await page.getByTestId('batch-summary').waitFor({ timeout: 90000 })
    await page.waitForTimeout(1500)
    const rows = await page.getByTestId('batch-row').count()
    const released = await page.getByTestId('batch-row').locator('span[title="影像已釋放"]').count()
    await h.shot(page, 'batch-released')
    await page.getByTestId('batch-row').first().click()
    const warn = await h.toast(page, /這次執行的影像已釋放/, 4000)
    un()
    h.item('M09', rows === 12 && released >= 4 && Boolean(warn), `rows=${rows} released=${released} warn=${warn}`)
  })

  await h.step('M10 Esc 關閉', async () => {
    await page.keyboard.press('Escape')
    const gone = await h.waitGone(page.locator('[role=dialog]'))
    h.item('M10', gone, 'Esc 未關閉批次 Modal')
  })

  h.nextDialog(page, true)
  await page.goto(`${BASE}/flows`)
  await page.waitForTimeout(400)
  await context.close()
}
