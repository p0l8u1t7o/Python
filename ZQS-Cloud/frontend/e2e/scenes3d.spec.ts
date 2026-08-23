import { expect, test } from '@playwright/test'

import { open, watch } from './helpers'

test('sites page shows the selected site constellation and switches on row click', async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  const watcher = watch(page)
  await open(page, '/sites')
  const card = page.getByTestId('site-constellation')
  await expect(card).toBeVisible({ timeout: 20_000 })
  await expect(card.locator('canvas')).toHaveCount(1, { timeout: 20_000 })
  await page.waitForTimeout(2500)
  await page.screenshot({ path: testInfo.outputPath('sites-root.png') })

  // Pick a leaf site from the table: the HUD title follows.
  const leafLink = page.locator('table tbody tr').nth(1).locator('a').first()
  const name = (await leafLink.textContent())?.trim() ?? ''
  // Click the row cell, not the link (the link navigates to the storage page).
  await page.locator('table tbody tr').nth(1).locator('td').nth(1).click()
  await expect(card.getByText(name, { exact: true })).toBeVisible()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: testInfo.outputPath('sites-leaf.png') })
  expect(watcher.errors).toEqual([])
})

test('tariffs page explains each site\'s plan and tariff through the hierarchy', async ({ page }, testInfo) => {
  const watcher = watch(page)
  await open(page, '/tariffs')
  const usage = page.getByTestId('tariff-usage')
  await expect(usage).toBeVisible({ timeout: 20_000 })
  await expect(usage.getByText(/繼承自|inherited from/).first()).toBeVisible()
  await expect(usage.getByText(/直接綁定|bound here/).first()).toBeVisible()
  await expect(page.getByTestId('tariff-coverage').locator('span').first()).toBeVisible()
  await usage.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('tariffs-usage.png') })
  expect(watcher.errors).toEqual([])
})
