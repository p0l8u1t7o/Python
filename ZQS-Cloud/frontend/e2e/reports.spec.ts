import { expect, test } from '@playwright/test'

import { open, watch } from './helpers'

/** Reports page: a report renders for the default window, presets switch it, and both exports download. */
test('energy report renders, switches period and exports PDF and Word', async ({ page }, testInfo) => {
  const watcher = watch(page)
  await open(page, '/reports')
  await expect(page.getByTestId('energy-report')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('report-insights').locator('li').first()).toBeVisible()

  // Switch to "last 7 days": the report reloads and still renders.
  await page.getByRole('button', { name: /最近 7 天|Last 7 days/ }).click()
  await expect(page.getByTestId('energy-report')).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: testInfo.outputPath('reports.png'), fullPage: true })

  // Custom range with an inverted window is refused before any request goes out.
  await page.getByRole('button', { name: /自訂|自定义|Custom/ }).click()
  const inputs = page.locator('input[type="date"]')
  await inputs.nth(0).fill('2026-08-20')
  await inputs.nth(1).fill('2026-08-10')
  await expect(page.getByText(/請選擇有效的起迄|Pick a valid date range/)).toBeVisible()
  await inputs.nth(1).fill('2026-08-25')
  await expect(page.getByTestId('energy-report')).toBeVisible({ timeout: 30_000 })

  for (const [id, ext] of [['report-export-pdf', 'pdf'], ['report-export-docx', 'docx']] as const) {
    const download = page.waitForEvent('download', { timeout: 60_000 })
    await page.getByTestId(id).click()
    const file = await download
    expect(file.suggestedFilename()).toMatch(new RegExp(`energy-report_.*\\.${ext}$`))
  }

  expect(watcher.errors).toEqual([])
  expect(watcher.failedRequests.filter((l) => /^5/.test(l))).toEqual([])
})
