import { expect, test } from '@playwright/test'

import { open, watch } from './helpers'

/** The 3D energy hero renders a WebGL canvas with the HUD and no console errors. */
for (const scheme of ['light', 'dark'] as const) {
  test(`storage page 3D hero renders (${scheme})`, async ({ page }, testInfo) => {
    await page.emulateMedia({ colorScheme: scheme })
    const watcher = watch(page)
    await open(page, '/storage')
    const hero = page.getByTestId('energy-hero')
    await expect(hero).toBeVisible({ timeout: 20_000 })
    await expect(hero.locator('canvas')).toHaveCount(1, { timeout: 20_000 })
    await expect(hero.getByText('SOC')).toBeVisible()
    await page.waitForTimeout(2000)
    await page.screenshot({ path: testInfo.outputPath(`storage-${scheme}.png`), fullPage: false })
    expect(watcher.errors).toEqual([])
    expect(watcher.failedRequests.filter((l) => /^5/.test(l))).toEqual([])
  })
}
