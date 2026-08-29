/** 模組 auth：登入頁（A）、外框（B）、使用者管理（R）、設定頁帳號卡片（U05）。 */
import { ADMIN, BASE, WORKER } from './full-lib.mjs'

export async function run(h) {
  const status = await (await h.apiCtx.request.get(`${BASE}/api/auth/status`)).json()
  const context = await h.newContext()
  const page = await h.newPage(context, '[auth]')

  // ---- A. 登入／設定初始化 ----
  await h.step('A01 未登入導向', async () => {
    await page.goto(`${BASE}/flows`)
    await page.waitForURL(/\/login/, { timeout: 10000 })
    h.item('A01', /\/login/.test(page.url()), `url=${page.url()}`)
  })

  if (status.setup_required) {
    await h.step('A07 setup 表單', async () => {
      await page.waitForSelector('[data-testid=login-form]')
      const txt = await page.locator('[data-testid=login-form]').innerText()
      const hasHint = txt.includes('建立第一個管理員') && txt.includes('系統尚未有任何使用者')
      const hasDisplay = (await page.getByLabel('顯示名稱').count()) === 1
      await page.getByLabel('帳號').fill(ADMIN.username)
      await page.getByLabel('密碼', { exact: true }).fill('123')
      await page.getByRole('button', { name: '建立管理員並登入' }).click()
      const weak = (await page.locator('[role=alert]').innerText().catch(() => '')).includes('至少 6 個字元')
      await h.shot(page, 'login-setup-weak')
      await page.getByLabel('密碼', { exact: true }).fill(ADMIN.password)
      await page.getByLabel('顯示名稱').fill('系統管理員')
      await page.getByRole('button', { name: '建立管理員並登入' }).click()
      await page.waitForURL(/\/flows$/, { timeout: 10000 })
      h.item('A07', hasHint && hasDisplay && weak, `hint=${hasHint} display=${hasDisplay} weak=${weak}`)
      // 登出回到登入頁測一般登入
      await page.evaluate(() => localStorage.removeItem('vs.token'))
      await page.goto(`${BASE}/flows`)
      await page.waitForURL(/\/login/, { timeout: 10000 })
    })
  } else {
    h.skip('A07', '本次未帶 --fresh（系統已有使用者）；請以 node full.mjs --fresh auth 驗證')
  }
  await h.loginAdmin()
  await h.api.del('/vision/lock')

  await h.step('A02-A06 登入表單', async () => {
    await page.waitForSelector('[data-testid=login-form]')
    await h.shot(page, 'login-form')
    const focused = await page.evaluate(() => document.activeElement?.id && document.activeElement === document.querySelector('input[autocomplete=username]'))
    const fields = (await page.getByLabel('帳號').count()) === 1 && (await page.getByLabel('密碼', { exact: true }).count()) === 1
    h.item('A02', fields && focused, `fields=${fields} autofocus=${focused}`)

    await page.getByRole('button', { name: '登入' }).click()
    const req = (await page.locator('[role=alert]').innerText().catch(() => '')).trim()
    h.item('A03', req.includes('請輸入帳號與密碼'), `alert=${req}`)

    const un = h.allowStatus(/401 POST .*\/api\/auth\/login/)
    await page.getByLabel('帳號').fill(ADMIN.username)
    await page.getByLabel('密碼', { exact: true }).fill('wrong-password')
    await page.getByRole('button', { name: '登入' }).click()
    await page.waitForTimeout(600)
    const bad = (await page.locator('[role=alert]').innerText().catch(() => '')).trim()
    await h.shot(page, 'login-bad-password')
    h.item('A04', bad.includes('帳號或密碼錯誤'), `alert=${bad}`)
    un()

    await page.getByLabel('密碼', { exact: true }).fill(ADMIN.password)
    // 送出中：按鈕應 disabled（loading）。把登入請求拖慢 800ms 才觀察得到。
    await page.route('**/api/auth/login', async (route) => {
      await h.sleep(800)
      await route.continue()
    })
    const submit = page.getByRole('button', { name: '登入' })
    await submit.click()
    const busy = await submit.isDisabled().catch(() => false)
    await page.waitForURL(/\/flows$/, { timeout: 10000 })
    await page.unroute('**/api/auth/login')
    h.item('A06', busy, `送出中 disabled=${busy}`)
    await page.waitForLoadState('networkidle')
    const menu = await page.getByTestId('user-menu').innerText()
    h.item('A05', /系統管理員|admin/.test(menu) && /\/flows$/.test(page.url()), `menu=${menu} url=${page.url()}`)
    h.item('A01', /\/flows$/.test(page.url()), '登入後未回到原頁 /flows')
  })

  await h.step('A08 已登入開 /login', async () => {
    await page.goto(`${BASE}/login`)
    await page.waitForTimeout(800)
    h.item('A08', !/\/login/.test(page.url()), `url=${page.url()}`)
  })

  await h.step('A09 登入頁深色', async () => {
    const dark = await h.newContext({ colorScheme: 'dark' })
    const dp = await h.newPage(dark, '[auth-dark]')
    await dp.goto(`${BASE}/login`)
    await dp.waitForSelector('[data-testid=login-form]')
    const isDark = await dp.evaluate(() => document.documentElement.classList.contains('dark'))
    await h.shot(dp, 'login-dark')
    h.item('A09', isDark, 'html 未帶 dark class')
    await dark.close()
  })

  // ---- B. 外框 ----
  await h.step('B01-B03 導覽、容量、主題', async () => {
    await page.goto(`${BASE}/`)
    await page.waitForLoadState('networkidle')
    // 改版後：側欄 [data-testid=sidebar]（.nav-item.active 為目前頁）；容量 pill 搬到頂列 [data-testid=topbar]
    const nav = page.locator('[data-testid=sidebar] a')
    const n = await nav.count()
    const labels = await nav.allInnerTexts()
    const active = await page.locator('[data-testid=sidebar] a.nav-item.active').innerText().catch(() => '')
    const titles = await nav.evaluateAll((els) => els.map((e) => e.getAttribute('title')))
    h.item('B01', n === 9 && active.includes('總覽') && titles.every(Boolean), `n=${n} labels=${labels.join('|')} active=${active}`)
    const pill = await page.locator('[data-testid=topbar] .tnum').first().innerText()
    h.item('B02', /\d+\/\d+ 忙碌/.test(pill), `pill=${pill}`)
    const btn = page.getByRole('button', { name: '切換深／淺色' })
    const before = await page.evaluate(() => document.documentElement.classList.contains('dark'))
    const iconBefore = await btn.locator('svg').getAttribute('class')
    await btn.click()
    await page.waitForTimeout(300)
    const after = await page.evaluate(() => document.documentElement.classList.contains('dark'))
    const iconAfter = await btn.locator('svg').getAttribute('class')
    const stored = await page.evaluate(() => localStorage.getItem('vs.theme'))
    await h.shot(page, 'dashboard-theme-toggled')
    h.item('B03', before !== after && iconBefore !== iconAfter && (stored === 'dark' || stored === 'light'), `before=${before} after=${after} stored=${stored}`)
    await btn.click()
    await page.waitForTimeout(200)
  })

  await h.step('B04 使用者選單', async () => {
    await page.getByTestId('user-menu').click()
    const menu = page.locator('[role=menu]')
    await menu.waitFor({ timeout: 3000 })
    const txt = await menu.innerText()
    await h.shot(page, 'user-menu')
    const ok1 = txt.includes('@admin') && txt.includes('管理員') && txt.includes('修改密碼') && txt.includes('登出')
    await page.mouse.click(800, 500)
    await page.waitForTimeout(200)
    const closed = (await menu.count()) === 0
    h.item('B04', ok1 && closed, `menu=${txt.replace(/\n/g, '|')} closedOnOutside=${closed}`)
  })

  await h.step('B05-B06 修改密碼', async () => {
    await page.getByTestId('user-menu').click()
    await page.getByRole('menuitem', { name: '修改密碼' }).click()
    const dlg = h.dialog(page)
    await dlg.waitFor()
    await dlg.getByRole('button', { name: '儲存' }).click()
    const e1 = await dlg.locator('[role=alert]').innerText()
    await dlg.getByLabel('舊密碼').fill('x')
    await dlg.getByLabel('新密碼', { exact: true }).fill('abcdef')
    await dlg.getByLabel('確認新密碼').fill('abcdeg')
    await dlg.getByRole('button', { name: '儲存' }).click()
    const e2 = await dlg.locator('[role=alert]').innerText()
    const un = h.allowStatus(/4\d\d POST .*\/api\/auth\/password/)
    await dlg.getByLabel('確認新密碼').fill('abcdef')
    await dlg.getByRole('button', { name: '儲存' }).click()
    await page.waitForTimeout(600)
    const e3 = await dlg.locator('[role=alert]').innerText()
    un()
    await h.shot(page, 'change-password-errors')
    // Esc → 放棄確認
    await page.keyboard.press('Escape')
    const ask = dlg.locator('[role=alertdialog]')
    const asked = (await ask.count()) === 1
    await ask.getByRole('button', { name: '繼續編輯' }).click()
    const stillOpen = (await dlg.count()) === 1 && (await ask.count()) === 0
    await page.keyboard.press('Escape')
    await ask.getByRole('button', { name: '放棄' }).click()
    const gone = await h.waitGone(page.locator('[role=dialog]'))
    h.item('B06', asked && stillOpen && gone, `asked=${asked} keep=${stillOpen} discard=${gone}`)
    // 成功改密碼再改回
    await page.getByTestId('user-menu').click()
    await page.getByRole('menuitem', { name: '修改密碼' }).click()
    const d2 = h.dialog(page)
    await d2.getByLabel('舊密碼').fill(ADMIN.password)
    await d2.getByLabel('新密碼', { exact: true }).fill('admin456')
    await d2.getByLabel('確認新密碼').fill('admin456')
    await d2.getByLabel('確認新密碼').press('Enter')
    const t1 = await h.toast(page, /密碼已更新/)
    await h.shot(page, 'change-password-ok')
    await h.waitGone(page.locator('[role=dialog]'))
    const r = await h.apiCtx.request.post(`${BASE}/api/auth/login`, { data: { username: 'admin', password: 'admin456' } })
    const loginOk = r.ok()
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    // 改回
    await page.getByTestId('user-menu').click()
    await page.getByRole('menuitem', { name: '修改密碼' }).click()
    const d3 = h.dialog(page)
    await d3.getByLabel('舊密碼').fill('admin456')
    await d3.getByLabel('新密碼', { exact: true }).fill(ADMIN.password)
    await d3.getByLabel('確認新密碼').fill(ADMIN.password)
    await d3.getByRole('button', { name: '儲存' }).click()
    const t2 = await h.toast(page, /密碼已更新/)
    await h.waitGone(page.locator('[role=dialog]'))
    h.item('B05', e1.includes('請輸入') && e2.includes('不一致') && e3.length > 0 && Boolean(t1) && loginOk && Boolean(t2), `e1=${e1} e2=${e2} e3=${e3} toast=${t1} login=${loginOk} back=${t2}`)
    await h.loginAdmin()
  })

  await h.step('B08 toast 手動關閉', async () => {
    await page.goto(`${BASE}/settings`)
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: '儲存' }).first().click()
    const toast = page.locator('[role=status] .card').first()
    await toast.waitFor({ timeout: 3000 })
    await toast.getByRole('button', { name: 'Dismiss' }).click()
    const gone = (await page.locator('[role=status] .card').count()) === 0
    h.item('B08', gone, '手動關閉後 toast 仍在')
  })

  // ---- U05 帳號卡片 ----
  await h.step('U05 帳號卡片', async () => {
    const txt = await page.locator('main').innerText()
    const ok = txt.includes('admin') && txt.includes('系統管理員') && txt.includes('管理員') && (await page.getByRole('button', { name: '修改密碼' }).count()) === 1
    await page.getByRole('button', { name: '修改密碼' }).click()
    const opened = (await h.dialog(page).count()) === 1
    await page.keyboard.press('Escape')
    h.item('U05', ok && opened, `text=${txt.slice(0, 80)} opened=${opened}`)
  })

  // ---- R. 使用者 ----
  const existing = await h.api.get('/users')
  for (const u of existing?.items ?? []) if (u.username !== ADMIN.username) await h.api.del(`/users/${u.id}`)

  await h.step('R02-R03 使用者列表與新增', async () => {
    await page.goto(`${BASE}/users`)
    await page.waitForLoadState('networkidle')
    const head = await page.locator('thead').innerText()
    const selfRow = page.locator('tbody tr').filter({ hasText: 'admin' })
    const youBadge = (await selfRow.locator('text=你').count()) === 1
    const switches = selfRow.getByRole('switch')
    const sDisabled = (await switches.nth(0).isDisabled()) && (await switches.nth(1).isDisabled())
    const delDisabled = await selfRow.getByRole('button', { name: '刪除' }).isDisabled()
    h.item('R02', /帳號/.test(head) && /顯示名稱/.test(head) && /管理員/.test(head) && /啟用/.test(head) && /最近登入/.test(head) && youBadge && sDisabled && delDisabled, `head=${head.replace(/\n/g, '|')} you=${youBadge} sw=${sDisabled} del=${delDisabled}`)
    await h.shot(page, 'users-list')

    await page.getByRole('button', { name: '新增使用者' }).click()
    const dlg = h.dialog(page)
    await dlg.getByRole('button', { name: '新增' }).click()
    const t1 = await h.toast(page, /請輸入帳號與密碼/)
    await dlg.getByLabel('帳號').fill(WORKER.username)
    await dlg.getByLabel('密碼').fill('123')
    await dlg.getByRole('button', { name: '新增' }).click()
    const t2 = await h.toast(page, /至少 6 個字元/)
    const hint = await dlg.innerText()
    await dlg.getByLabel('密碼').fill(WORKER.password)
    await dlg.getByLabel('顯示名稱').fill('產線人員一')
    await h.shot(page, 'users-create-modal')
    await dlg.getByRole('button', { name: '新增' }).click()
    const t3 = await h.toast(page, /已建立使用者/)
    await h.waitGone(page.locator('[role=dialog]'))
    await page.waitForTimeout(400)
    const listed = (await page.locator('tbody').innerText()).includes(WORKER.username)
    // 重複帳號
    const un = h.allowStatus(/4\d\d POST .*\/api\/users/)
    await page.getByRole('button', { name: '新增使用者' }).click()
    const d2 = h.dialog(page)
    await d2.getByLabel('帳號').fill(WORKER.username)
    await d2.getByLabel('密碼').fill(WORKER.password)
    await d2.getByRole('button', { name: '新增' }).click()
    const t4 = await h.toast(page, /./, 4000)
    un()
    const errShown = Boolean(t4) && !/已建立/.test(t4)
    // Esc → 放棄
    await page.keyboard.press('Escape')
    const asked = (await d2.locator('[role=alertdialog]').count()) === 1
    await d2.getByRole('button', { name: '放棄' }).click()
    await h.waitGone(page.locator('[role=dialog]'))
    h.item('R03', Boolean(t1 && t2 && t3) && hint.includes('管理員可管理使用者') && listed && errShown && asked, `t1=${t1} t2=${t2} t3=${t3} listed=${listed} dup=${t4} asked=${asked}`)
  })

  const workerRow = () => page.locator('tbody tr').filter({ hasText: WORKER.username })
  await h.step('R04 管理員開關', async () => {
    await workerRow().getByRole('switch', { name: '管理員' }).click()
    const dlg = h.dialog(page)
    const msg = await dlg.innerText()
    await h.shot(page, 'users-promote-confirm')
    await dlg.getByRole('button', { name: '確定' }).click()
    const t1 = await h.toast(page, /已更新使用者/)
    await page.waitForTimeout(500)
    const on = await workerRow().getByRole('switch', { name: '管理員' }).getAttribute('aria-checked')
    await workerRow().getByRole('switch', { name: '管理員' }).click()
    const msg2 = await h.dialog(page).innerText()
    await h.dialog(page).getByRole('button', { name: '確定' }).click()
    const t2 = await h.toast(page, /已更新使用者/)
    await page.waitForTimeout(500)
    const off = await workerRow().getByRole('switch', { name: '管理員' }).getAttribute('aria-checked')
    h.item('R04', msg.includes('設為管理員') && Boolean(t1) && on === 'true' && msg2.includes('取消') && Boolean(t2) && off === 'false', `msg=${msg} on=${on} msg2=${msg2} off=${off}`)
  })

  await h.step('R05 啟用開關', async () => {
    await workerRow().getByRole('switch', { name: '啟用' }).click()
    const dlg = h.dialog(page)
    const msg = await dlg.innerText()
    const danger = (await dlg.locator('button.bg-critical').count()) === 1
    await dlg.getByRole('button', { name: '確定' }).click()
    const t1 = await h.toast(page, /已更新使用者/)
    await page.waitForTimeout(400)
    const r = await h.apiCtx.request.post(`${BASE}/api/auth/login`, { data: WORKER })
    const denied = r.status() === 401 || r.status() === 403
    await workerRow().getByRole('switch', { name: '啟用' }).click()
    await h.dialog(page).getByRole('button', { name: '確定' }).click()
    const t2 = await h.toast(page, /已更新使用者/)
    await page.waitForTimeout(400)
    const r2 = await h.apiCtx.request.post(`${BASE}/api/auth/login`, { data: WORKER })
    h.item('R05', msg.includes('停用') && danger && Boolean(t1) && denied && Boolean(t2) && r2.ok(), `msg=${msg} danger=${danger} denied=${r.status()} re=${r2.status()}`)
  })

  await h.step('R06 重設密碼', async () => {
    await workerRow().getByRole('button', { name: '重設密碼' }).click()
    const dlg = h.dialog(page)
    const title = await dlg.locator('h2').innerText()
    await dlg.getByLabel('新密碼').fill('123')
    await dlg.getByLabel('新密碼').press('Enter')
    const t1 = await h.toast(page, /至少 6 個字元/)
    await dlg.getByLabel('新密碼').fill('worker456')
    await dlg.getByLabel('新密碼').press('Enter')
    const t2 = await h.toast(page, /密碼已重設/)
    await h.waitGone(page.locator('[role=dialog]'))
    const r = await h.apiCtx.request.post(`${BASE}/api/auth/login`, { data: { username: WORKER.username, password: 'worker456' } })
    await h.api.patch(`/users/${(await h.api.get('/users')).items.find((u) => u.username === WORKER.username).id}`, { password: WORKER.password })
    h.item('R06', title.includes(WORKER.username) && Boolean(t1) && Boolean(t2) && r.ok(), `title=${title} t1=${t1} t2=${t2} login=${r.status()}`)
  })

  await h.step('R07 刪除使用者', async () => {
    await h.api.post('/users', { username: 'e2e_tmp', password: 'tmp123456', is_staff: false, display_name: '暫時' })
    await page.reload()
    await page.waitForLoadState('networkidle')
    const row = page.locator('tbody tr').filter({ hasText: 'e2e_tmp' })
    await row.getByRole('button', { name: '刪除' }).click()
    const dlg = h.dialog(page)
    const msg = await dlg.innerText()
    await dlg.getByRole('button', { name: '刪除' }).click()
    const t = await h.toast(page, /已刪除使用者/)
    await page.waitForTimeout(500)
    const gone = (await page.locator('tbody tr').filter({ hasText: 'e2e_tmp' }).count()) === 0
    h.item('R07', msg.includes('e2e_tmp') && Boolean(t) && gone, `msg=${msg} toast=${t} gone=${gone}`)
  })

  await h.step('R08 空狀態（mock）', async () => {
    await page.route('**/api/users', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) }))
    await page.reload()
    await page.waitForLoadState('networkidle')
    const txt = await page.locator('tbody').innerText()
    await h.shot(page, 'users-empty')
    h.item('R08', txt.includes('還沒有使用者'), `tbody=${txt}`)
    await page.unroute('**/api/users')
  })

  await h.step('R01 一般使用者導向', async () => {
    const wtoken = await h.login(WORKER)
    const wctx = await h.newContext({ token: wtoken })
    const wp = await h.newPage(wctx, '[worker]')
    await wp.goto(`${BASE}/users`)
    await wp.waitForTimeout(1200)
    const nav = await wp.getByTestId('sidebar').innerText()
    h.item('R01', !/\/users/.test(wp.url()) && !nav.includes('使用者'), `url=${wp.url()} nav=${nav.replace(/\n/g, '|')}`)
    await wctx.close()
  })

  // ---- B07 登出 ----
  await h.step('B07 登出', async () => {
    await page.goto(`${BASE}/settings`)
    await page.waitForLoadState('networkidle')
    await page.getByTestId('user-menu').click()
    await page.getByRole('menuitem', { name: '登出' }).click()
    await page.waitForURL(/\/login/, { timeout: 8000 })
    const tk = await page.evaluate(() => localStorage.getItem('vs.token'))
    await h.shot(page, 'after-logout')
    h.item('B07', /\/login/.test(page.url()) && !tk, `url=${page.url()} token=${tk}`)
  })

  await context.close()
}
