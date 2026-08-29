/** 模組 lock：引擎鎖定與一般使用者視角（V）、設定頁鎖定卡片（U04）、頂列唯讀／鎖定 badge（F19、F20）、工具頁（N24）、批次（M10）。 */
import { BASE, WORKER } from './full-lib.mjs'

export async function run(h) {
  await h.loginAdmin()
  await h.api.del('/vision/lock')
  // 確保 worker1 存在
  const users = await h.api.get('/users')
  if (!users.items.some((u) => u.username === WORKER.username)) await h.api.post('/users', { ...WORKER, is_staff: false, display_name: '產線人員一' })
  else {
    const u = users.items.find((x) => x.username === WORKER.username)
    await h.api.patch(`/users/${u.id}`, { password: WORKER.password, is_active: true, is_staff: false })
  }
  const demo = h.demoFlow()
  const actx = await h.newContext({ token: h.token })
  const admin = await h.newPage(actx, '[lock-admin]')
  const wtoken = await h.login(WORKER)
  const wctx = await h.newContext({ token: wtoken })
  const worker = await h.newPage(wctx, '[lock-worker]')
  const openEditor = async (page, id = demo.id) => {
    await page.goto(`${BASE}/flows/${id}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(800)
  }

  await h.step('V05 V06 F19 worker 流程列表與唯讀編輯器', async () => {
    await worker.goto(`${BASE}/flows`)
    await worker.waitForLoadState('networkidle')
    await worker.waitForTimeout(500)
    const row = worker.locator('tbody tr').filter({ hasText: demo.name })
    const lockIcon = (await row.locator('svg[aria-label="唯讀"]').count()) === 1
    const switchDisabled = await row.getByRole('switch').isDisabled()
    const delDisabled = await row.getByRole('button', { name: '唯讀' }).isDisabled()
    await h.shot(worker, 'worker-flows')
    await worker.getByRole('switch', { name: '只看我的' }).click()
    await worker.waitForTimeout(600)
    const mineEmpty = (await worker.locator('tbody').innerText()).includes('還沒有流程')
    await worker.getByRole('switch', { name: '只看我的' }).click()
    await worker.waitForTimeout(300)
    h.item('V05', lockIcon && switchDisabled && delDisabled && mineEmpty, `lock=${lockIcon} switch=${switchDisabled} del=${delDisabled} mineEmpty=${mineEmpty}`)
    await openEditor(worker)
    const ro = (await worker.getByTestId('readonly-badge').count()) === 1
    const saveDisabled = await worker.locator('[data-testid=editor-toolbar]').getByRole('button', { name: /儲存|已儲存/ }).isDisabled()
    const resetDisabled = await worker.getByTestId('btn-reset').isDisabled()
    await worker.keyboard.press('Control+s')
    const t = await h.toast(worker, /共用流程只有管理員能修改/)
    await h.shot(worker, 'worker-editor-readonly')
    h.item('F19', ro && saveDisabled, `badge=${ro} saveDisabled=${saveDisabled}`)
    // 複製後自己的流程可編輯
    await worker.goto(`${BASE}/flows`)
    await worker.waitForLoadState('networkidle')
    await worker.locator('tbody tr').filter({ hasText: demo.name }).first().getByRole('button', { name: '複製' }).click()
    await h.toast(worker, /已複製流程/)
    await worker.waitForTimeout(600)
    const own = worker.locator('tbody tr').filter({ hasText: '副本' }).first()
    const ownTxt = await own.innerText()
    await own.click()
    await worker.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await worker.waitForTimeout(600)
    const ownRo = (await worker.getByTestId('readonly-badge').count()) === 0
    const ownId = Number(worker.url().split('/').pop())
    h.item('V06', Boolean(t) && resetDisabled && ownTxt.includes('(你)') && ownRo, `toast=${t} reset=${resetDisabled} own=${ownTxt.replace(/\n/g, '|').slice(0, 60)} ownEditable=${ownRo}`)
    h.workerFlowId = ownId
  })

  await h.step('U04 設定頁鎖定', async () => {
    await admin.goto(`${BASE}/settings`)
    await admin.waitForLoadState('networkidle')
    await admin.getByLabel('原因').fill('整合方校正相機')
    await admin.getByLabel('自動解鎖（秒）').fill('600')
    await admin.getByTestId('btn-lock').click()
    const t = await h.toast(admin, /引擎已鎖定/)
    await admin.waitForTimeout(600)
    const st = await admin.getByTestId('lock-status').innerText()
    const banner = admin.getByTestId('lock-banner')
    const btxt = await banner.innerText().catch(() => '')
    await h.shot(admin, 'settings-locked')
    h.item('U04', Boolean(t) && st.includes('已鎖定') && st.includes('admin') && st.includes('整合方校正相機') && st.includes('自動解鎖') && btxt.includes('admin') && btxt.includes('整合方校正相機') && (await banner.getByRole('button', { name: '解鎖' }).count()) === 1, `toast=${t} status=${st} banner=${btxt}`)
  })

  await h.step('V01 V02 V07 worker 鎖定視角', async () => {
    await openEditor(worker)
    const banner = worker.getByTestId('lock-banner')
    const hasBanner = (await banner.count()) === 1
    const noUnlock = (await banner.getByRole('button', { name: '解鎖' }).count()) === 0
    const disabled = {}
    for (const id of ['btn-preview', 'btn-continuous', 'btn-batch']) disabled[id] = await worker.getByTestId(id).isDisabled()
    const badge = (await worker.getByTestId('exec-locked-badge').count()) === 1
    const hint = await worker.getByTestId('btn-preview').locator('..').getAttribute('title')
    await h.shot(worker, 'worker-editor-locked')
    const un = h.allowStatus(/423 POST .*\/api\/vision\/flows\/\d+\/run/)
    const r = await wctx.request.post(`${BASE}/api/vision/flows/${demo.id}/run`, { headers: { Authorization: `Bearer ${wtoken}` }, data: { context: null, wait: true } })
    un()
    h.item('V01', hasBanner && noUnlock && Object.values(disabled).every(Boolean) && r.status() === 423, `banner=${hasBanner} noUnlock=${noUnlock} disabled=${JSON.stringify(disabled)} api=${r.status()}`)
    h.item('F20', badge && Boolean(hint?.includes('鎖定')), `badge=${badge} hint=${hint}`)
    // 工具頁：不自動試跑、按鈕 disabled
    await worker.goto(`${BASE}/flows/${h.workerFlowId}/tools/blob`)
    await worker.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
    await worker.waitForTimeout(1200)
    const previewDisabled = await worker.getByTestId('tool-preview').isDisabled()
    const noResult = (await worker.getByTestId('tool-reference').innerText()).includes('此步驟尚無結果')
    await h.shot(worker, 'worker-tool-locked')
    h.item('N24', previewDisabled && noResult, `previewDisabled=${previewDisabled} noResult=${noResult}`)
    // 批次 Modal 執行按鈕 disabled
    await openEditor(worker, h.workerFlowId)
    const batchDisabled = await worker.getByTestId('btn-batch').isDisabled()
    h.item('M10', batchDisabled, '鎖定時批次測試按鈕未 disabled')
    // worker 設定頁
    await worker.goto(`${BASE}/settings`)
    await worker.waitForLoadState('networkidle')
    const wst = await worker.locator('main').innerText()
    h.item('V07', wst.includes('已鎖定') && wst.includes('目前只能編輯流程') && (await worker.getByTestId('btn-lock').count()) === 0, `settings=${wst.slice(0, 200).replace(/\n/g, '|')}`)
    // 持有者本人仍可試跑
    await openEditor(admin)
    const holderPreview = !(await admin.getByTestId('btn-preview').isDisabled())
    await admin.getByTestId('btn-preview').click()
    const t = await h.toast(admin, /試跑完成/)
    await h.shot(admin, 'admin-holder-locked')
    h.item('V02', holderPreview && Boolean(t), `preview=${holderPreview} toast=${t}`)
  })

  await h.step('V03 V04 解鎖與 SSE', async () => {
    await openEditor(worker)
    await admin.getByTestId('lock-banner').getByRole('button', { name: '解鎖' }).click()
    const t = await h.toast(admin, /引擎已解鎖/)
    await admin.waitForTimeout(600)
    const adminGone = (await admin.getByTestId('lock-banner').count()) === 0
    await worker.waitForTimeout(1500)
    const workerGone = (await worker.getByTestId('lock-banner').count()) === 0
    const workerEnabled = !(await worker.getByTestId('btn-preview').isDisabled())
    h.item('V03', Boolean(t) && adminGone && workerGone && workerEnabled, `toast=${t} adminGone=${adminGone} workerGone=${workerGone} enabled=${workerEnabled}`)
    await h.api.post('/vision/lock', { reason: '透過 API 上鎖', ttl_s: 600 })
    const shown = await worker.getByTestId('lock-banner').waitFor({ timeout: 8000 }).then(() => true).catch(() => false)
    const btxt = await worker.getByTestId('lock-banner').innerText().catch(() => '')
    const runDisabled = await worker.getByTestId('btn-continuous').isDisabled()
    await h.shot(worker, 'worker-lock-via-sse')
    await h.api.del('/vision/lock')
    await worker.waitForTimeout(1500)
    const gone = (await worker.getByTestId('lock-banner').count()) === 0
    h.item('V04', shown && btxt.includes('透過 API 上鎖') && runDisabled && gone, `shown=${shown} banner=${btxt} runDisabled=${runDisabled} gone=${gone}`)
  })

  // worker 的其他頁面也有橫幅（總覽）
  await h.step('V01b 其他頁面橫幅', async () => {
    await h.api.post('/vision/lock', { reason: '橫幅測試', ttl_s: 600 })
    await worker.goto(`${BASE}/`)
    await worker.waitForLoadState('networkidle')
    await worker.waitForTimeout(800)
    const b = (await worker.getByTestId('lock-banner').count()) === 1
    await h.shot(worker, 'worker-dashboard-locked')
    await h.api.del('/vision/lock')
    h.item('V01', b, '總覽頁沒有鎖定橫幅')
  })

  if (h.workerFlowId) await h.api.del(`/vision/flows/${h.workerFlowId}`)
  await actx.close()
  await wctx.close()
}
