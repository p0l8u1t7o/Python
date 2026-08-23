import { expect, test } from '@playwright/test'

import { open, watch } from './helpers'

const STAMP = Date.now().toString(36)

test('workflow templates: create from built-in, save canvas as template, load it back', async ({ page }) => {
  const watcher = watch(page)
  await open(page, '/workflows')

  // Gallery lists the six built-ins with their role placeholders.
  await page.getByTestId('open-template-gallery').click()
  const gallery = page.getByTestId('template-gallery')
  await expect(gallery).toBeVisible()
  await expect(gallery.locator('[data-testid^=template-card-builtin]')).toHaveCount(6)
  await gallery.getByTestId('template-card-builtin:0').click()
  await expect(gallery.getByText(/電池（BESS）|市電關口電表/).first()).toBeVisible()
  const name = `範本流程 ${STAMP}`
  await gallery.getByLabel(/名稱|Name/).fill(name)
  // Pick a site with a battery and a meter so every placeholder resolves.
  await gallery.locator('button[aria-haspopup=listbox]').click()
  await gallery.getByRole('button', { name: /台中工業區廠房/ }).first().click()
  await page.getByRole('button', { name: /^建立$|^Create$/ }).click()
  await page.waitForURL(/\/workflows\/[0-9a-f-]{36}/, { timeout: 20_000 })
  await expect(page.locator('.react-flow__node')).not.toHaveCount(0, { timeout: 20_000 })
  const nodeCount = await page.locator('.react-flow__node').count()
  expect(nodeCount).toBeGreaterThan(3)

  // Save the canvas as a custom template.
  await page.getByTestId('save-template').click()
  const templateName = `我的範本 ${STAMP}`
  await page.getByLabel(/名稱|Name/).last().fill(templateName)
  await page.getByRole('button', { name: /^儲存$|^Save$/ }).last().click()
  await expect(page.getByText(new RegExp(`已儲存範本|Saved template`))).toBeVisible({ timeout: 10_000 })

  // Load it back: the custom card is there with role placeholders, and loading keeps the node count.
  await page.getByTestId('load-template').click()
  const loader = page.getByTestId('template-gallery')
  await expect(loader.getByText(templateName)).toBeVisible()
  await loader.getByText(templateName).click()
  await page.getByRole('button', { name: /載入範本|Load template/ }).last().click()
  await expect(page.getByText(/已將.*載入畫布|Loaded .* into the canvas/)).toBeVisible({ timeout: 10_000 })
  await expect(page.locator('.react-flow__node')).toHaveCount(nodeCount)

  expect(watcher.errors).toEqual([])
})
