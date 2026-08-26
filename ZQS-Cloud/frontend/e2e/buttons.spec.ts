import { expect, test, type Page } from '@playwright/test'

import { open, watch } from './helpers'

/**
 * Every button on every page gets pressed.
 *
 * The deep sweep exercises the flows a person would follow; this one is the
 * blunt instrument underneath it: open a route, click every visible, enabled
 * button in turn, close whatever opened, and fail on any console error, page
 * error or 5xx. A 4xx from a submit on an empty form is the application doing
 * its job and is allowed; a 5xx never is.
 *
 * Destructive, persisting or outward-facing buttons are skipped by label -
 * saving (a sweep that adds palette nodes and then saves would rewrite the
 * demo workflow under every later test), deleting, rotating credentials,
 * sending commands, starting runs, signing out. Those
 * are covered by the targeted specs where the result is checked, not here
 * where it would only leave the demo database worse than it found it.
 */

const SKIP =
  /儲存|保存|^Save$|套用|Apply|刪除|移除|Delete|Remove|登出|Sign out|Log out|撤銷|輪換|重新產生|Rotate|Revoke|Regenerate|緊急|Emergency|觸發|Trigger|執行|Run\b|Start|停止|Stop|暫停|Pause|送出指令|Send command|下達|Issue|解析|Geocode|重建|Rebuild|清除|Clear|English|简体|繁體|Export|匯出|下載|Download/i

const ROUTES: string[] = [
  '/',
  '/devices',
  '/map',
  '/alerts',
  '/storage',
  '/storage-plans',
  '/telemetry',
  '/events',
  '/tariffs',
  '/workflows',
  '/sites',
  '/recording',
  '/rules',
  '/audit',
  '/settings',
  '/gateways',
  '/reports',
  '/help',
]

/** Press Escape until no dialog remains, then make sure we are still on `path`. */
async function settle(page: Page, path: string): Promise<void> {
  for (let i = 0; i < 3; i += 1) {
    if ((await page.locator('[role="dialog"]:visible').count()) === 0) break
    await page.keyboard.press('Escape')
    await page.waitForTimeout(200)
  }
  if ((await page.locator('[role="dialog"]:visible').count()) > 0) {
    // A dialog that Escape cannot close: use its own close/cancel control.
    const close = page
      .locator('[role="dialog"]:visible')
      .last()
      .getByRole('button', { name: /關閉|取消|Close|Cancel|×/i })
      .first()
    if (await close.count()) await close.click({ timeout: 2000 }).catch(() => {})
    await page.waitForTimeout(200)
  }
  const here = new URL(page.url()).pathname
  if (here !== path) await open(page, path)
}

async function pressEverything(page: Page, path: string): Promise<{ clicked: number; skipped: number }> {
  let clicked = 0
  let skipped = 0
  const seen = new Set<string>()
  // Re-query each round: clicking changes the DOM, and a stale handle is the
  // usual way a sweep like this silently stops early.
  for (let round = 0; round < 120; round += 1) {
    const buttons = page.locator('button:visible, [role="tab"]:visible')
    const total = await buttons.count()
    let target: { index: number; label: string } | null = null
    for (let i = 0; i < total; i += 1) {
      const button = buttons.nth(i)
      const label = (
        (await button.getAttribute('aria-label')) ||
        (await button.getAttribute('title')) ||
        (await button.innerText().catch(() => ''))
      )
        .trim()
        .slice(0, 60)
      const key = `${i}:${label}`
      if (seen.has(key)) continue
      seen.add(key)
      if (!label || SKIP.test(label)) {
        skipped += 1
        continue
      }
      if (await button.isDisabled().catch(() => true)) continue
      target = { index: i, label }
      break
    }
    if (!target) break
    const button = page.locator('button:visible, [role="tab"]:visible').nth(target.index)
    await button.click({ timeout: 3000, trial: false }).catch(() => {})
    clicked += 1
    await page.waitForTimeout(350)
    await settle(page, path)
  }
  return { clicked, skipped }
}

function problems(errors: string[], failed: string[]): string[] {
  const serverErrors = failed.filter((line) => /^5\d\d /.test(line))
  const console = errors.filter(
    // 4xx from a blank-form submit shows up as a console line too.
    (line) => !/(400|401|403|404|409|422)/.test(line),
  )
  return [...console, ...serverErrors]
}

test.describe('press every button', () => {
  for (const path of ROUTES) {
    test(`${path}`, async ({ page }) => {
      test.setTimeout(240_000)
      const watcher = watch(page)
      await open(page, path)
      await page.waitForTimeout(1200)
      const result = await pressEverything(page, path)
      console.log(`${path}: clicked ${result.clicked}, skipped ${result.skipped}`)
      expect(result.clicked, `${path} has no clickable buttons`).toBeGreaterThan(0)
      expect(problems(watcher.errors, watcher.failedRequests)).toEqual([])
    })
  }

  test('device detail', async ({ page }) => {
    test.setTimeout(240_000)
    await open(page, '/devices')
    await page.waitForTimeout(1500)
    // List or card layout - whichever the saved preference left behind.
    await page.getByText(/BESS-01/).first().click()
    await page.waitForURL(/\/devices\/[0-9a-f-]+/, { timeout: 20_000 })
    const path = new URL(page.url()).pathname
    const watcher = watch(page)
    await page.waitForTimeout(1200)
    const result = await pressEverything(page, path)
    console.log(`${path}: clicked ${result.clicked}, skipped ${result.skipped}`)
    expect(problems(watcher.errors, watcher.failedRequests)).toEqual([])
  })

  test('workflow editor', async ({ page }) => {
    test.setTimeout(240_000)
    await open(page, '/workflows')
    await page.waitForTimeout(1500)
    await page.getByRole('link').filter({ hasText: /需量反應演練/ }).first().click()
    await page.waitForURL(/\/workflows\/[0-9a-f-]+/, { timeout: 20_000 })
    await expect(page.locator('.react-flow')).toBeVisible()
    const path = new URL(page.url()).pathname
    const watcher = watch(page)
    await page.waitForTimeout(1500)
    const result = await pressEverything(page, path)
    console.log(`${path}: clicked ${result.clicked}, skipped ${result.skipped}`)
    expect(problems(watcher.errors, watcher.failedRequests)).toEqual([])
  })
})
