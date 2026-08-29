/** 模組 lang：語言切換 English 後各頁沒有未翻譯 key（U03、W06）。 */
import { BASE } from './full-lib.mjs'

export async function run(h) {
  await h.loginAdmin()
  const context = await h.newContext({ token: h.token, locale: 'en-US' })
  const page = await h.newPage(context, '[lang]')
  const demo = h.demoFlow()

  await h.step('U03 切換 English', async () => {
    await page.goto(`${BASE}/settings`)
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'English', exact: true }).click()
    await page.waitForTimeout(400)
    const stored = await page.evaluate(() => localStorage.getItem('vs.language'))
    const nav = await page.getByTestId('sidebar').innerText()
    const lang = await page.evaluate(() => document.documentElement.lang)
    await h.shot(page, 'en-settings')
    h.item('U03', stored === 'en' && nav.includes('Dashboard') && nav.includes('Flows') && lang === 'en', `stored=${stored} nav=${nav.replace(/\n/g, '|')} lang=${lang}`)
  })

  const pages = [
    ['/', 'en-dashboard', 'main'],
    ['/flows', 'en-flows', 'main'],
    ['/sources', 'en-sources', 'main'],
    ['/assets', 'en-assets', 'main'],
    ['/users', 'en-users', 'main'],
    ['/integration?tab=http', 'en-integration-http', 'main'],
    ['/integration?tab=tcp', 'en-integration-tcp', 'main'],
    ['/integration?tab=events', 'en-integration-events', 'main'],
    ['/integration?tab=lock', 'en-integration-lock', 'main'],
    ['/integration?tab=format', 'en-integration-format', 'main'],
    ['/integration?tab=plc', 'en-integration-plc', 'main'],
    ['/connections', 'en-connections', 'main'],
    [`/flows/${demo.id}/teach`, 'en-teach', 'main'],
    [`/flows/${demo.id}/golden`, 'en-golden', 'main'],
    ['/help?tab=quickstart', 'en-help', 'main'],
    ['/help?tab=tools', 'en-help-tools', 'main'],
    [`/flows/${demo.id}/stats`, 'en-stats', 'main'],
  ]
  for (const [path, name] of pages) {
    await h.step(`U03 ${path}`, async () => {
      await page.goto(`${BASE}${path}`)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(700)
      await h.shot(page, name)
    })
  }

  await h.step('U03 editor / tool page / modals (en)', async () => {
    await page.goto(`${BASE}/flows/${demo.id}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(700)
    await page.getByTestId('btn-preview').click()
    await h.toast(page, /Preview/i, 8000)
    await page.waitForTimeout(500)
    const tb = await page.locator('[data-testid=editor-toolbar]').innerText()
    await h.shot(page, 'en-editor')
    h.item('U03', tb.includes('Preview') && !tb.includes('Run once') && tb.includes('Batch test') && tb.includes('Continuous') && tb.includes('Saved'), `toolbar=${tb.replace(/\n/g, '|').slice(0, 160)}`)
    await page.locator('.react-flow__panel button[title="Fit view"], .react-flow__panel button[title="符合視窗"]').first().click()
    await page.waitForTimeout(300)
    await page.locator('.react-flow__node[data-id="blob"]').click({ button: 'right' })
    await page.getByTestId('node-menu').waitFor()
    await h.shot(page, 'en-context-menu')
    await page.keyboard.press('Escape')
    await page.locator('.react-flow__node[data-id="blob"]').click()
    await page.getByRole('tab', { name: /Results/ }).click()
    await page.waitForTimeout(300)
    await h.shot(page, 'en-results')
    await page.getByTestId('btn-batch').click()
    await h.dialog(page).waitFor()
    await h.shot(page, 'en-batch-modal')
    await page.keyboard.press('Escape')
    await page.getByTestId('btn-templates').click()
    await page.getByTestId('menu-load-template').click()
    await page.getByTestId('template-card').first().waitFor()
    await h.shot(page, 'en-template-gallery')
    await page.keyboard.press('Escape')
    await page.goto(`${BASE}/flows/${demo.id}/tools/blob`)
    await page.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
    await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => null)
    await page.waitForTimeout(500)
    await h.shot(page, 'en-tool-page')
    const hdr = await page.locator('[data-testid=tool-page] header').innerText()
    h.item('U03', hdr.includes('Back to editor') && hdr.includes('Auto apply'), `tool header=${hdr.replace(/\n/g, '|')}`)
  })

  await h.step('U03 login page (en) and switch back', async () => {
    const anon = await h.newContext({ locale: 'en-US' })
    await anon.addInitScript(() => localStorage.setItem('vs.language', 'en'))
    const ap = await h.newPage(anon, '[lang-login]')
    await ap.goto(`${BASE}/login`)
    await ap.waitForSelector('[data-testid=login-form]')
    const txt = await ap.locator('[data-testid=login-form]').innerText()
    await h.shot(ap, 'en-login')
    await anon.close()
    await page.goto(`${BASE}/settings`)
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: '繁體中文', exact: true }).click()
    await page.waitForTimeout(300)
    const back = (await page.getByTestId('sidebar').innerText()).includes('總覽')
    h.item('U03', txt.includes('Sign in') && txt.includes('Username') && back, `login=${txt.replace(/\n/g, '|')} back=${back}`)
  })

  await context.close()
}
