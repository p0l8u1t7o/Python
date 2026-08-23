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

    // Click the battery: the camera glides in and the HUD says what is focused.
    const canvas = hero.locator('canvas')
    const box = await canvas.boundingBox()
    if (!box) throw new Error('no canvas box')
    await page.mouse.click(box.x + box.width * 0.69, box.y + box.height * 0.55)
    await expect(hero.getByText(/再點一次返回|click again to return/)).toBeVisible({ timeout: 5000 })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: testInfo.outputPath(`storage-${scheme}-focus.png`), fullPage: false })
    await page.mouse.click(box.x + box.width * 0.69, box.y + box.height * 0.55)
    await expect(hero.getByText(/點擊節點聚焦|Click a node to focus/)).toBeVisible({ timeout: 5000 })
    expect(watcher.errors).toEqual([])
    expect(watcher.failedRequests.filter((l) => /^5/.test(l))).toEqual([])
  })
}
