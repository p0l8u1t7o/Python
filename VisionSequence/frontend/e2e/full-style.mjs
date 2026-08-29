/**
 * 模組 style：風格改版（ST）——Gentelella 風外框：側欄摺疊／展開／tooltip、導覽項、頂列麵包屑／容量／主題／使用者選單、
 * 面板摺疊（設定頁）、深色與 en 模式在新風格下每頁、1280×800 無水平捲軸（含摺疊側欄）、
 * 編輯器頂列配方按鈕／綁定下拉、工具頁無同步視角＋前後各自縮放、編輯器前／後分割各自縮放。
 */
import { BASE, WORKER } from './full-lib.mjs'
import { ensureWorker } from './full-teach.mjs'

const NAV_ZH = ['總覽', '流程', '影像來源庫', '資產庫', '整合', '連線', '使用者', '設定', '說明']
const NAV_EN = ['Dashboard', 'Flows', 'Source library', 'Asset library', 'Integration', 'Connections', 'Users', 'Settings', 'Help']

export async function run(h) {
  await h.loginAdmin()
  await h.api.del('/vision/lock')
  await ensureWorker(h)
  const demo = h.demoFlow()
  const flowId = await h.cloneDemo('E2E 風格')
  const context = await h.newContext({ token: h.token })
  const page = await h.newPage(context, '[style]')
  const sidebar = () => page.getByTestId('sidebar')
  const crumb = () => page.getByTestId('breadcrumb')
  const sidebarWidth = () => sidebar().evaluate((el) => el.getBoundingClientRect().width)
  const scaleOf = (p, sel) => p.locator(`${sel} span.min-w-11`).first().innerText()

  await h.step('ST01 側欄摺疊／展開與持久化', async () => {
    await page.goto(`${BASE}/flows`)
    await sidebar().waitFor()
    await page.locator('table tbody tr').first().waitFor({ timeout: 15000 })
    const nowrap = await page.evaluate(() => [...document.querySelectorAll('[data-testid=sidebar] .nav-item')].every((el) => getComputedStyle(el).whiteSpace === 'nowrap' && el.scrollWidth <= el.clientWidth + 1))
    const w0 = await sidebarWidth()
    const brand = await sidebar().locator('span', { hasText: 'VS' }).first().count()
    const section = (await sidebar().innerText()).includes('功能')
    await h.shot(page, 'style-flows-light')
    await page.getByTestId('sidebar-toggle').click()
    await page.waitForTimeout(300)
    const collapsed = await sidebar().getAttribute('data-collapsed')
    const w1 = await sidebarWidth()
    const stored = await page.evaluate(() => localStorage.getItem('vs.sidebar'))
    const labelHidden = !(await sidebar().innerText()).includes('影像來源庫') || (await sidebar().locator('.nav-tip').count()) === 9
    await page.reload()
    await sidebar().waitFor()
    const persisted = await sidebar().getAttribute('data-collapsed')
    await page.getByTestId('topbar-toggle').click()
    await page.waitForTimeout(300)
    const expanded = await sidebar().getAttribute('data-collapsed')
    const stored2 = await page.evaluate(() => localStorage.getItem('vs.sidebar'))
    const w2 = await sidebarWidth()
    h.item('ST01', nowrap && w0 > 200 && brand === 1 && section && collapsed === 'true' && w1 < 70 && stored === 'collapsed' && labelHidden && persisted === 'true' && expanded === 'false' && stored2 === 'expanded' && w2 > 200, `nowrap=${nowrap} w=${w0}->${w1}->${w2} brand=${brand} section=${section} collapsed=${collapsed} stored=${stored}/${stored2} persisted=${persisted} expanded=${expanded}`)
  })

  await h.step('ST02 摺疊時 tooltip、展開時 title', async () => {
    const titles = await sidebar().locator('a').evaluateAll((els) => els.map((e) => e.getAttribute('title')))
    const expandedNoTip = (await sidebar().locator('.nav-tip').count()) === 0
    await page.getByTestId('sidebar-toggle').click()
    await page.waitForTimeout(300)
    const tipsHidden = await page.locator('[data-testid=nav-sources] .nav-tip').evaluate((el) => getComputedStyle(el).opacity)
    await page.getByTestId('nav-sources').hover()
    await page.waitForTimeout(400)
    const tipOpacity = await page.locator('[data-testid=nav-sources] .nav-tip').evaluate((el) => getComputedStyle(el).opacity)
    const tipText = await page.locator('[data-testid=nav-sources] .nav-tip').innerText()
    const tipRole = await page.locator('[data-testid=nav-sources] .nav-tip').getAttribute('role')
    const toggleTitle = await page.getByTestId('sidebar-toggle').getAttribute('title')
    // tooltip 不能被側欄裁掉：整個落在側欄右側、且祖先沒有任何 overflow 會裁切（pointer-events-none 所以不能用 elementFromPoint）
    const tipOnTop = await page.evaluate(() => {
      const tip = document.querySelector('[data-testid=nav-sources] .nav-tip')
      const side = document.querySelector('[data-testid=sidebar]').getBoundingClientRect()
      const r = tip.getBoundingClientRect()
      // 只看側欄內的祖先（外框 root 的 overflow-hidden 是整個 app 的，不會裁到視窗內的 tooltip）
      const sidebar = document.querySelector('[data-testid=sidebar]')
      let el = tip.parentElement
      while (el && el !== sidebar.parentElement) {
        const cs = getComputedStyle(el)
        if (['hidden', 'auto', 'scroll', 'clip'].includes(cs.overflowX) || ['hidden', 'auto', 'scroll', 'clip'].includes(cs.overflowY)) return false
        el = el.parentElement
      }
      return r.left >= side.right - 1 && r.width > 20 && r.height > 10
    })
    await h.shot(page, 'style-sidebar-collapsed-tooltip')
    await page.getByTestId('sidebar-toggle').click()
    await page.waitForTimeout(300)
    h.item('ST02', titles.length === 9 && titles.every(Boolean) && expandedNoTip && Number(tipsHidden) === 0 && Number(tipOpacity) === 1 && tipText === '影像來源庫' && tipRole === 'tooltip' && toggleTitle === '展開側欄' && tipOnTop, `titles=${titles.join('|')} expandedNoTip=${expandedNoTip} hidden=${tipsHidden} hover=${tipOpacity}/${tipText}/${tipRole} toggleTitle=${toggleTitle} onTop=${tipOnTop}`)
  })

  await h.step('ST03 導覽 9 項與 active 樣式', async () => {
    const labels = await sidebar().locator('a').allInnerTexts()
    const active = await sidebar().locator('a.nav-item.active').allInnerTexts()
    const activeBar = await sidebar().locator('a.nav-item.active').evaluate((el) => getComputedStyle(el, '::before').width)
    await page.getByTestId('nav-sources').click()
    await page.waitForURL(/\/sources$/, { timeout: 5000 })
    await page.waitForTimeout(300)
    const active2 = await sidebar().locator('a.nav-item.active').allInnerTexts()
    const testids = await sidebar().locator('a').evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')))
    h.item('ST03', labels.map((s) => s.trim()).join('|') === NAV_ZH.join('|') && active.length === 1 && active[0].trim() === '流程' && parseInt(activeBar) >= 2 && active2.length === 1 && active2[0].trim() === '影像來源庫' && testids.every((t) => /^nav-/.test(t ?? '')), `labels=${labels.join('|')} active=${active}->${active2} bar=${activeBar} testids=${testids.join(',')}`)
  })

  await h.step('ST04 麵包屑', async () => {
    const got = {}
    for (const [path, wait] of [['/', 'main'], ['/flows', 'table'], ['/sources', 'main'], ['/assets', 'main'], ['/integration', 'main'], ['/connections', 'main'], ['/users', 'main'], ['/settings', 'main'], ['/help', 'main']]) {
      await page.goto(`${BASE}${path}`)
      await page.locator(wait).first().waitFor({ timeout: 15000 })
      await crumb().waitFor()
      got[path] = (await crumb().innerText()).replace(/\s+/g, ' ').trim()
    }
    // 流程子頁：總覽 › 流程 › 名稱 › 子頁；名稱是連結（回編輯器）、「流程」是連結（回列表）
    const sub = {}
    for (const [suffix, label] of [['', null], ['/teach', '參數卡'], ['/golden', 'Golden Set'], ['/stats', '統計'], ['/tools/blob', '工具頁']]) {
      await page.goto(`${BASE}/flows/${flowId}${suffix}`)
      await crumb().locator('a', { hasText: '流程' }).waitFor({ timeout: 15000 })
      await page.waitForTimeout(400)
      const txt = (await crumb().innerText()).replace(/\s+/g, ' ').trim()
      const links = await crumb().locator('a').evaluateAll((els) => els.map((e) => `${e.textContent.trim()}=${e.getAttribute('href')}`))
      sub[suffix || 'editor'] = { txt, links, label }
    }
    await h.shot(page, 'style-breadcrumb-tool-page')
    // 「流程」連結回列表
    await crumb().locator('a', { hasText: '流程' }).click()
    await page.waitForURL(/\/flows$/, { timeout: 5000 })
    const rootOk = got['/'].startsWith('總覽') && got['/flows'].includes('流程') && got['/sources'].includes('影像來源庫') && got['/users'].includes('使用者') && got['/help'].includes('說明') && got['/connections'].includes('連線')
    const editorOk = sub.editor.txt.includes('E2E 風格') && sub.editor.links.some((l) => l === '流程=/flows') && !sub.editor.links.some((l) => l.startsWith('E2E 風格='))
    const subOk = ['/teach', '/golden', '/stats', '/tools/blob'].every((k) => sub[k].txt.endsWith(sub[k].label) && sub[k].links.some((l) => l === `E2E 風格=/flows/${flowId}`))
    h.item('ST04', rootOk && editorOk && subOk && /\/flows$/.test(page.url()), `root=${JSON.stringify(got)} editor=${JSON.stringify(sub.editor)} teach=${sub['/teach'].txt} tools=${sub['/tools/blob'].txt} url=${page.url()}`)
  })

  await h.step('ST05 頂列：容量、主題、使用者選單', async () => {
    const topbar = page.getByTestId('topbar')
    await topbar.waitFor()
    const pill = await topbar.locator('.tnum').first().innerText()
    const inTop = (await topbar.locator('[data-testid=theme-toggle]').count()) === 1 && (await topbar.locator('[data-testid=user-menu]').count()) === 1 && (await topbar.locator('[data-testid=topbar-toggle]').count()) === 1
    const notInSidebar = (await sidebar().locator('[data-testid=user-menu], [data-testid=theme-toggle]').count()) === 0
    const h0 = await topbar.evaluate((el) => el.getBoundingClientRect().height)
    await page.getByTestId('theme-toggle').click()
    await page.waitForTimeout(300)
    const dark = await page.evaluate(() => document.documentElement.classList.contains('dark'))
    const sidebarBgDark = await sidebar().evaluate((el) => getComputedStyle(el).backgroundColor)
    await page.getByTestId('theme-toggle').click()
    await page.waitForTimeout(300)
    const sidebarBgLight = await sidebar().evaluate((el) => getComputedStyle(el).backgroundColor)
    await page.getByTestId('user-menu').click()
    const menu = page.locator('[role=menu]')
    await menu.waitFor({ timeout: 3000 })
    const menuTxt = await menu.innerText()
    const menuBox = await menu.boundingBox()
    await h.shot(page, 'style-topbar-user-menu')
    await page.keyboard.press('Escape')
    await page.mouse.click(700, 500)
    await page.waitForTimeout(200)
    const closed = (await menu.count()) === 0
    h.item('ST05', /\d+\/\d+ 忙碌/.test(pill) && inTop && notInSidebar && h0 >= 40 && h0 <= 56 && dark && sidebarBgDark !== sidebarBgLight && menuTxt.includes('@admin') && menuTxt.includes('登出') && menuBox && menuBox.y > h0 - 4 && closed, `pill=${pill} inTop=${inTop} notInSidebar=${notInSidebar} h=${h0} dark=${dark} sidebar=${sidebarBgLight}->${sidebarBgDark} menu=${menuTxt.replace(/\n/g, '|')} y=${menuBox?.y} closed=${closed}`)
  })

  await h.step('ST06 面板摺疊（設定頁）', async () => {
    await page.goto(`${BASE}/settings`)
    await page.getByTestId('panel-capacity').waitFor({ timeout: 15000 })
    const body0 = (await page.getByTestId('panel-capacity-body').count()) === 1
    const toggle = page.getByTestId('panel-capacity').getByTestId('panel-toggle')
    const exp0 = await toggle.getAttribute('aria-expanded')
    await toggle.click()
    await page.waitForTimeout(200)
    const body1 = (await page.getByTestId('panel-capacity-body').count()) === 0
    const exp1 = await toggle.getAttribute('aria-expanded')
    const titleStill = (await page.getByTestId('panel-capacity').innerText()).includes('執行緒池')
    await h.shot(page, 'style-panel-collapsed')
    await toggle.click()
    await page.waitForTimeout(200)
    const body2 = (await page.getByTestId('panel-capacity-body').count()) === 1
    const helpToggle = (await page.getByTestId('panel-help').getByTestId('panel-toggle').count()) === 1
    // 沒有摺疊鈕的卡片（API 金鑰）不受影響
    const otherToggles = await page.locator('[data-testid=panel-toggle]').count()
    h.item('ST06', body0 && exp0 === 'true' && body1 && exp1 === 'false' && titleStill && body2 && helpToggle && otherToggles === 2, `body=${body0}/${body1}/${body2} expanded=${exp0}/${exp1} title=${titleStill} helpToggle=${helpToggle} toggles=${otherToggles}`)
  })

  await h.step('ST07 編輯器頂列：配方按鈕與綁定下拉', async () => {
    for (const r of (await h.api.get(`/vision/flows/${flowId}/recipes`)).items) await h.api.del(`/vision/flows/${flowId}/recipes/${r.id}`)
    await page.goto(`${BASE}/flows/${flowId}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
    const noSelect = (await page.getByTestId('editor-recipe').count()) === 0
    const btnTxt = await page.getByTestId('btn-recipes').innerText()
    await page.getByTestId('btn-recipes').click()
    const drawer = page.getByTestId('recipe-drawer')
    await drawer.waitFor({ timeout: 5000 })
    const drawerTxt = await drawer.innerText()
    await h.shot(page, 'style-editor-recipe-drawer')
    // 在面板內新增（不用圖值 → 直接建立），第一個自動綁定
    await page.getByTestId('recipe-new-from-graph').uncheck()
    await page.getByTestId('recipe-new-name').fill('E2E partS')
    await page.getByTestId('recipe-create').click()
    const tCreate = await h.toast(page, /已建立配方「E2E partS」/)
    await page.getByTestId('recipe-drawer-close').click()
    await h.waitGone(drawer)
    const sel = page.getByTestId('editor-recipe')
    await sel.waitFor({ timeout: 5000 })
    const opts = await sel.locator('option').allInnerTexts()
    const chosen = await sel.locator('option:checked').innerText()
    const label = await sel.locator('xpath=..').innerText()
    // 切到「不用配方」→ PATCH is_default=false；再綁回
    await sel.selectOption('')
    const tNone = await h.toast(page, /已改為不用配方/)
    await page.waitForTimeout(400)
    const none = (await h.api.get(`/vision/flows/${flowId}/recipes`)).items.every((r) => !r.is_default)
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    const r = (await h.api.get(`/vision/flows/${flowId}/recipes`)).items.find((x) => x.name === 'E2E partS')
    await sel.selectOption(String(r.id))
    const tBound = await h.toast(page, /已綁定配方「E2E partS」/)
    await page.waitForTimeout(400)
    const bound = (await h.api.get(`/vision/flows/${flowId}/recipes`)).items.find((x) => x.is_default)?.name
    // 「執行一次」按鈕已移除：API 執行（未指定 recipe）→ 用綁定配方
    await h.api.post(`/vision/flows/${flowId}/run`, { context: null, wait: true })
    await page.waitForTimeout(800)
    const last = (await h.api.get(`/vision/flows/${flowId}/recent?limit=1`)).items[0]
    await h.shot(page, 'style-editor-bound')
    h.item('ST07', noSelect && btnTxt.includes('配方') && drawerTxt.includes('配方') && drawerTxt.includes('E2E 風格') && drawerTxt.includes('還沒有配方') && Boolean(tCreate) && opts.length === 2 && opts[0].includes('不用配方') && opts[1] === 'E2E partS' && chosen === 'E2E partS' && label.includes('綁定') && Boolean(tNone) && none && Boolean(tBound) && bound === 'E2E partS' && last?.recipe === 'E2E partS', `noSelect=${noSelect} btn=${btnTxt} drawer=${drawerTxt.replace(/\n/g, '|').slice(0, 80)} create=${tCreate} opts=${opts.join('/')} chosen=${chosen} label=${label.replace(/\n/g, ' ')} none=${tNone}/${none} bound=${tBound}/${bound} run.recipe=${last?.recipe}`)
  })

  await h.step('ST08 工具頁無同步視角、前／後各自縮放', async () => {
    await page.goto(`${BASE}/flows/${flowId}/tools/blob`)
    await page.getByTestId('tool-page').waitFor({ timeout: 15000 })
    await page.getByTestId('tool-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
    await page.waitForTimeout(600)
    const header = await page.locator('[data-testid=tool-page] header').innerText()
    const switches = await page.locator('[data-testid=tool-page] header [role=switch]').count()
    const noSync = !header.includes('同步視角') && (await page.getByText('同步視角').count()) === 0
    const b0 = await scaleOf(page, '[data-testid=tool-before]')
    const a0 = await scaleOf(page, '[data-testid=tool-after]')
    const box = await page.locator('[data-testid=tool-before] canvas').first().boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, -600)
    await page.waitForTimeout(400)
    const b1 = await scaleOf(page, '[data-testid=tool-before]')
    const a1 = await scaleOf(page, '[data-testid=tool-after]')
    // 右側單獨縮放
    const box2 = await page.locator('[data-testid=tool-after] canvas').first().boundingBox()
    await page.mouse.move(box2.x + box2.width / 2, box2.y + box2.height / 2)
    await page.mouse.wheel(0, -300)
    await page.waitForTimeout(400)
    const b2 = await scaleOf(page, '[data-testid=tool-before]')
    const a2 = await scaleOf(page, '[data-testid=tool-after]')
    await h.shot(page, 'style-tool-independent-zoom')
    h.item('ST08', switches === 1 && noSync && b0 === a0 && b1 !== b0 && a1 === a0 && b2 === b1 && a2 !== a1, `switches=${switches} noSync=${noSync} before ${b0}->${b1}->${b2} after ${a0}->${a1}->${a2}`)
  })

  await h.step('ST09 編輯器前／後分割各自縮放', async () => {
    await page.goto(`${BASE}/flows/${flowId}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.getByTestId('btn-preview').click()
    await h.toast(page, /試跑完成/, 15000)
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(300)
    await page.locator('.react-flow__node[data-id=thr]').click()
    await page.getByTestId('btn-split').click()
    await page.getByTestId('viewer-after').waitFor()
    await page.waitForTimeout(600)
    const b0 = await scaleOf(page, '[data-testid=viewer-main]')
    const a0 = await scaleOf(page, '[data-testid=viewer-after]')
    const box = await page.locator('[data-testid=viewer-after] canvas').first().boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, -600)
    await page.waitForTimeout(400)
    const b1 = await scaleOf(page, '[data-testid=viewer-main]')
    const a1 = await scaleOf(page, '[data-testid=viewer-after]')
    await h.shot(page, 'style-editor-split-independent-zoom')
    h.item('ST09', a1 !== a0 && b1 === b0, `main ${b0}->${b1} after ${a0}->${a1}`)
  })

  await h.step('ST10 深色模式每頁（含摺疊側欄）', async () => {
    const dark = await h.newContext({ token: h.token, colorScheme: 'dark' })
    await dark.addInitScript(() => localStorage.setItem('vs.theme', 'dark'))
    const dp = await h.newPage(dark, '[style-dark]')
    let ok = true
    const notes = []
    for (const [route, name, wait] of [
      ['/', 'dashboard', 'breadcrumb'],
      ['/flows', 'flows', 'breadcrumb'],
      ['/sources', 'sources', 'breadcrumb'],
      ['/assets', 'assets', 'breadcrumb'],
      ['/integration', 'integration', 'breadcrumb'],
      ['/connections', 'connections', 'breadcrumb'],
      ['/users', 'users', 'breadcrumb'],
      ['/settings', 'settings', 'breadcrumb'],
      ['/help', 'help', 'breadcrumb'],
      [`/flows/${flowId}`, 'editor', 'editor-toolbar'],
      [`/flows/${flowId}/teach`, 'teach', 'teach-group'],
      [`/flows/${flowId}/tools/blob`, 'tool-page', 'tool-page'],
      [`/flows/${flowId}/stats`, 'stats', 'breadcrumb'],
      [`/flows/${flowId}/golden`, 'golden', 'breadcrumb'],
    ]) {
      await dp.goto(`${BASE}${route}`)
      await dp.getByTestId(wait).first().waitFor({ timeout: 15000 })
      await dp.waitForLoadState('networkidle').catch(() => null)
      await dp.waitForTimeout(700)
      const info = await dp.evaluate(() => ({
        dark: document.documentElement.classList.contains('dark'),
        sidebar: getComputedStyle(document.querySelector('[data-testid=sidebar]')).backgroundColor,
        topbar: getComputedStyle(document.querySelector('[data-testid=topbar]')).backgroundColor,
        body: getComputedStyle(document.body).backgroundColor,
      }))
      const lum = (rgb) => { const m = /(\d+), (\d+), (\d+)/.exec(rgb); return m ? (Number(m[1]) + Number(m[2]) + Number(m[3])) / 3 : 255 }
      if (!info.dark || info.sidebar === 'rgb(42, 63, 84)' || lum(info.topbar) > 80 || lum(info.body) > 80) { ok = false; notes.push(`${name}:${JSON.stringify(info)}`) }
      await h.shot(dp, `style-dark-${name}`)
    }
    await dp.goto(`${BASE}/flows`)
    await dp.getByTestId('sidebar').waitFor()
    await dp.getByTestId('sidebar-toggle').click()
    await dp.waitForTimeout(300)
    await dp.getByTestId('nav-settings').hover()
    await dp.waitForTimeout(400)
    const tipBg = await dp.locator('[data-testid=nav-settings] .nav-tip').evaluate((el) => getComputedStyle(el).backgroundColor)
    await h.shot(dp, 'style-dark-sidebar-collapsed')
    await dp.getByTestId('user-menu').click()
    await dp.locator('[role=menu]').waitFor()
    await h.shot(dp, 'style-dark-user-menu')
    await dark.close()
    h.currentPage = page
    h.item('ST10', ok && tipBg !== 'rgb(42, 63, 84)', `${notes.join(' ; ')} tipBg=${tipBg}`)
  })

  await h.step('ST11 en 模式：側欄／麵包屑／tooltip／配方面板', async () => {
    const ctx = await h.newContext({ token: h.token, locale: 'en-US' })
    await ctx.addInitScript(() => localStorage.setItem('vs.language', 'en'))
    const en = await h.newPage(ctx, '[style-en]')
    await en.goto(`${BASE}/flows`)
    await en.getByTestId('sidebar').waitFor()
    await en.locator('table tbody tr').first().waitFor({ timeout: 15000 })
    const labels = (await en.getByTestId('sidebar').locator('a').allInnerTexts()).map((s) => s.trim())
    const collapseTxt = await en.getByTestId('sidebar-toggle').innerText()
    const crumbTxt = (await en.getByTestId('breadcrumb').innerText()).replace(/\s+/g, ' ')
    await h.shot(en, 'style-en-flows')
    await en.getByTestId('sidebar-toggle').click()
    await en.waitForTimeout(300)
    await en.getByTestId('nav-sources').hover()
    await en.waitForTimeout(300)
    const tip = await en.locator('[data-testid=nav-sources] .nav-tip').innerText()
    const toggleTitle = await en.getByTestId('sidebar-toggle').getAttribute('title')
    await h.shot(en, 'style-en-sidebar-collapsed')
    await en.getByTestId('sidebar-toggle').click()
    // 配方面板（en）
    const row = en.locator('table tbody tr').filter({ hasText: 'E2E 風格' }).first()
    await row.getByTestId('row-recipes').click()
    await en.getByTestId('recipe-drawer').waitFor()
    const drawerTxt = await en.getByTestId('recipe-drawer').innerText()
    await h.shot(en, 'style-en-recipe-drawer')
    await en.getByTestId('recipe-new-name').fill('E2E en')
    await en.getByTestId('recipe-create').click()
    await en.locator('[data-testid=check-list], [data-testid=check-list-empty]').first().waitFor({ timeout: 10000 })
    const checkTxt = await h.dialog(en).innerText()
    await h.shot(en, 'style-en-check-list')
    await en.getByRole('button', { name: /Cancel/i }).last().click()
    await en.getByTestId('recipe-import').click()
    await h.dialog(en).waitFor()
    const importTxt = await h.dialog(en).innerText()
    await h.shot(en, 'style-en-import-modal')
    await en.keyboard.press('Escape')
    await en.getByTestId('recipe-drawer-close').click()
    // 流程子頁麵包屑（en）
    await en.goto(`${BASE}/flows/${flowId}/teach`)
    await en.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
    await en.getByTestId('teach-updating').waitFor({ state: 'detached', timeout: 20000 }).catch(() => null)
    const crumbTeach = (await en.getByTestId('breadcrumb').innerText()).replace(/\s+/g, ' ')
    const teachTxt = await en.locator('[data-testid=teach-page] header').innerText()
    await h.shot(en, 'style-en-teach')
    await en.goto(`${BASE}/flows/${flowId}/tools/blob`)
    await en.getByTestId('tool-page').waitFor({ timeout: 15000 })
    const crumbTool = (await en.getByTestId('breadcrumb').innerText()).replace(/\s+/g, ' ')
    await en.goto(`${BASE}/settings`)
    await en.getByTestId('panel-capacity').waitFor({ timeout: 15000 })
    await h.shot(en, 'style-en-settings')
    await ctx.close()
    h.item('ST11', labels.join('|') === NAV_EN.join('|') && /Collapse/i.test(collapseTxt) && /Dashboard.*Flows/.test(crumbTxt) && tip === 'Source library' && /Expand/i.test(toggleTitle ?? '') && /Recipes/i.test(drawerTxt) && /Bound|Binding/i.test(drawerTxt) && /Check List|check list/i.test(checkTxt) && /Import/i.test(importTxt) && /Teach/i.test(crumbTeach) && /Tool page/i.test(crumbTool) && /Teach/i.test(teachTxt) && !/參數卡|返回編輯器|配方|綁定/.test(drawerTxt + checkTxt + importTxt + crumbTeach + teachTxt), `labels=${labels.join('|')} collapse=${collapseTxt} crumb=${crumbTxt}/${crumbTeach}/${crumbTool} tip=${tip} toggle=${toggleTitle} drawer=${drawerTxt.replace(/\n/g, '|').slice(0, 80)} check=${checkTxt.replace(/\n/g, '|').slice(0, 60)} import=${importTxt.replace(/\n/g, '|').slice(0, 40)}`)
  })

  await h.step('ST12 1280×800 各頁（含摺疊側欄）無水平捲軸', async () => {
    const small = await h.newContext({ token: h.token, viewport: { width: 1280, height: 800 } })
    const sp = await h.newPage(small, '[style-1280]')
    const notes = []
    for (const [route, name, wait] of [
      ['/flows', 'flows', 'breadcrumb'],
      [`/flows/${flowId}`, 'editor', 'editor-toolbar'],
      [`/flows/${flowId}/teach`, 'teach', 'teach-group'],
      [`/flows/${flowId}/tools/blob`, 'tool-page', 'tool-page'],
      ['/settings', 'settings', 'panel-capacity'],
    ]) {
      await sp.goto(`${BASE}${route}`)
      await sp.getByTestId(wait).first().waitFor({ timeout: 15000 })
      await sp.waitForTimeout(600)
      const info = await sp.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, main: document.querySelector('main').scrollWidth, mainW: document.querySelector('main').clientWidth }))
      if (info.sw > info.cw + 1 || info.main > info.mainW + 1) notes.push(`${name}:${JSON.stringify(info)}`)
      await h.shot(sp, `style-1280-${name}`)
    }
    // 摺疊側欄後編輯器中欄變寬
    await sp.goto(`${BASE}/flows/${flowId}`)
    await sp.getByTestId('editor-toolbar').waitFor({ timeout: 15000 })
    await sp.waitForTimeout(500)
    const c0 = await sp.locator('.react-flow').evaluate((el) => el.getBoundingClientRect().width)
    await sp.getByTestId('topbar-toggle').click()
    await sp.waitForTimeout(400)
    const c1 = await sp.locator('.react-flow').evaluate((el) => el.getBoundingClientRect().width)
    const info = await sp.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
    await h.shot(sp, 'style-1280-editor-collapsed')
    // 配方面板在 1280 也塞得下
    await sp.getByTestId('btn-recipes').click()
    await sp.getByTestId('recipe-drawer').waitFor()
    const dw = await sp.getByTestId('recipe-drawer').evaluate((el) => el.getBoundingClientRect().width)
    await h.shot(sp, 'style-1280-recipe-drawer')
    await small.close()
    h.currentPage = page
    h.item('ST12', notes.length === 0 && c1 - c0 >= 150 && info.sw <= info.cw + 1 && dw >= 480 && dw <= 560, `${notes.join(' ; ')} canvas=${c0}->${c1} scroll=${info.sw}/${info.cw} drawerW=${dw}`)
  })

  await h.step('ST13 worker 視角：側欄 8 項、配方面板唯讀', async () => {
    const wtoken = await h.login(WORKER)
    const wctx = await h.newContext({ token: wtoken })
    const wp = await h.newPage(wctx, '[style-worker]')
    await wp.goto(`${BASE}/flows`)
    await wp.getByTestId('sidebar').waitFor()
    await wp.locator('table tbody tr').first().waitFor({ timeout: 15000 })
    const labels = (await wp.getByTestId('sidebar').locator('a').allInnerTexts()).map((s) => s.trim())
    const menu = await wp.getByTestId('user-menu').getAttribute('title')
    const row = wp.locator('table tbody tr').filter({ hasText: demo.name }).filter({ hasNotText: '副本' }).first()
    await row.getByTestId('row-recipes').click()
    await wp.getByTestId('recipe-drawer').waitFor()
    const noNew = (await wp.getByTestId('recipe-new').count()) === 0
    const importDis = await wp.getByTestId('recipe-import').isDisabled()
    const boundDis = await wp.getByTestId('drawer-bound').isDisabled()
    await h.shot(wp, 'style-worker-recipe-drawer')
    await wctx.close()
    h.item('ST13', labels.length === 8 && !labels.includes('使用者') && menu && !menu.includes('管理員') && noNew && importDis && boundDis, `labels=${labels.join('|')} menu=${menu} noNew=${noNew} importDis=${importDis} boundDis=${boundDis}`)
  })

  await context.close()
}
