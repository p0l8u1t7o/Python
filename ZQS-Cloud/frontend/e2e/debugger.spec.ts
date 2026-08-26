import { expect, test } from '@playwright/test'

import { open, watch } from './helpers'

/** Integration page: the connection debugger switches on, shows a diagnosis, and switches off. */
test('connection debugger toggles and diagnoses a gateway', async ({ page }, testInfo) => {
  const watcher = watch(page)
  await open(page, '/gateways')
  // The debugger lives in the selected gateway's last tab.
  await expect(page.getByTestId('gateway-detail')).toBeVisible({ timeout: 20_000 })
  await page.getByRole('tab', { name: /連線偵錯|连接调试|Connection debugger/ }).click()
  const card = page.getByTestId('connection-debugger')
  await expect(card).toBeVisible({ timeout: 20_000 })

  // Another session may have left capture on: bring it to a known-off state first.
  const toggle = page.getByTestId('debug-toggle')
  if (/停止|Stop/.test((await toggle.textContent()) ?? '')) {
    await toggle.click()
    await expect(toggle).toHaveText(/開始擷取|Start capture/, { timeout: 10_000 })
  }
  await toggle.click()
  await expect(toggle).toHaveText(/停止|Stop/, { timeout: 10_000 })
  await expect(page.getByTestId('debug-diagnosis')).toBeVisible({ timeout: 10_000 })
  await expect(page.getByTestId('debug-diagnosis').locator('span').first()).not.toBeEmpty()
  await page.waitForTimeout(1500)
  await page.screenshot({ path: testInfo.outputPath('debugger-on.png'), fullPage: true })

  // Stop: back to the hint, no console errors along the way.
  await toggle.click()
  await expect(toggle).toHaveText(/開始擷取|Start capture/, { timeout: 10_000 })
  expect(watcher.errors).toEqual([])
  expect(watcher.failedRequests.filter((l) => /^5/.test(l))).toEqual([])
})
