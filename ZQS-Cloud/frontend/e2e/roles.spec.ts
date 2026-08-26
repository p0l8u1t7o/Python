import { expect, test } from '@playwright/test'

import { untranslatedKeys, watch } from './helpers'

/**
 * The console as the least-privileged roles see it.
 *
 * The admin suite proves pages render; this proves they *degrade* correctly:
 * a viewer must get a quieter page, never a crashed one, and no request the
 * page makes on its own may come back 403 - a control the role cannot use
 * should not be drawn, and a query the role cannot read should not be fired.
 */

const ROUTES = [
  '/', '/devices', '/map', '/alerts', '/storage', '/storage-plans', '/telemetry',
  '/events', '/reports', '/tariffs', '/workflows', '/sites', '/recording', '/rules', '/audit',
  '/settings', '/gateways', '/help',
]

for (const account of ['viewer', 'operator'] as const) {
  test.describe(`${account} role`, () => {
    // A fresh session per role: storageState belongs to the admin.
    test.use({ storageState: { cookies: [], origins: [] } })

    test(`${account} can open every route without errors`, async ({ page }) => {
      test.setTimeout(180000)
      const watcher = watch(page)

      await page.goto('/login')
      await page.locator('input[type="email"]').fill(`${account}@example.com`)
      await page.locator('input[type="password"]').fill('ChangeMe-2026!')
      await page.locator('form button[type="submit"]').click()
      await expect(page.getByRole('navigation')).toBeVisible({ timeout: 20_000 })

      const forbidden: string[] = []
      for (const route of ROUTES) {
        await page.goto(route)
        await page.waitForTimeout(1400)
        await expect(page.getByRole('heading').first()).toBeVisible()
        const keys = await untranslatedKeys(page)
        expect(keys, `${route}: untranslated keys`).toEqual([])
      }
      for (const line of watcher.failedRequests) {
        if (/ 403 /.test(line)) forbidden.push(line)
      }

      // Each 403 is a query a page fires for a role that cannot read it.
      console.log(`${account} 403s:`, forbidden.length ? forbidden.join(' | ') : 'none')
      expect(forbidden, 'pages must not fire requests the role cannot read').toEqual([])
      expect(watcher.errors.filter((e) => !/403/.test(e)).join('\n')).toBe('')
    })
  })
}
