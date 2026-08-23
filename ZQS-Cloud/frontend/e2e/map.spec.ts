import { expect, test } from '@playwright/test'

import { open, watch } from './helpers'

/** Fleet map: hierarchy links, demand colouring, tree side panel. */
test('map shows site hierarchy and demand standing', async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  const watcher = watch(page)
  await open(page, '/map')
  await expect(page.getByTestId('map-demand-stats')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('map-legend')).toBeVisible()
  // Parent → child links are drawn as dashed polylines on the fleet view.
  await expect(page.locator('.leaflet-overlay-pane path[stroke-dasharray]').first()).toBeAttached({ timeout: 15_000 })
  // The side panel is a tree: the park row has a collapse toggle.
  const park = page.getByTestId('map-site-hsinchu')
  await expect(park).toBeVisible()
  await expect(park.getByRole('button', { name: /收合|Collapse|折叠/ })).toBeVisible()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: testInfo.outputPath('map-fleet.png') })
  // Collapsing hides the children.
  await park.getByRole('button', { name: /收合|Collapse|折叠/ }).click()
  await expect(page.getByTestId('map-site-hsinchu-a')).toHaveCount(0)
  expect(watcher.errors).toEqual([])
})
