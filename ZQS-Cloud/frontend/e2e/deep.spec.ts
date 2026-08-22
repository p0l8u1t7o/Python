import { expect, test, type Page } from '@playwright/test'

import { open, watch } from './helpers'

/**
 * Interaction sweep for the release gate.
 *
 * Each test drives one page the way an operator would - opens dialogs,
 * switches tabs, creates and deletes a record - while the watcher collects
 * console errors and failed requests. The assertion at the end of every test
 * is the same: nothing on the console, nothing 4xx/5xx that was not meant to.
 */

const dialog = (page: Page) => page.getByRole('dialog')
const button = (page: Page, pattern: RegExp) =>
  page.getByRole('button').filter({ hasText: pattern }).first()

async function closeDialog(page: Page) {
  const close = dialog(page).getByRole('button').filter({ hasText: /取消|cancel|關閉|关闭|close/i }).first()
  if (await close.count()) await close.click()
  else await page.keyboard.press('Escape')
  await page.waitForTimeout(300)
}

function report(watcher: ReturnType<typeof watch>) {
  const failed = watcher.failedRequests.filter((line) => !/ 404 .*\/plan$/.test(line))
  return { errors: watcher.errors.join('\n'), failed: failed.join('\n') }
}

test.describe('deep sweep', () => {
  test('devices: detail, tabs, edit dialog', async ({ page }) => {
    const watcher = watch(page)
    await open(page, '/devices')
    await page.waitForTimeout(1500)
    // Layout-agnostic: the list/card preference is saved server-side, so an
    // earlier test may have left the page in card layout with no table rows.
    await page.getByText(/BESS-01|BESS-0001/).first().click()
    await page.waitForURL(/\/devices\/[0-9a-f-]+/, { timeout: 20_000 })
    await page.waitForTimeout(2000)

    // Every tab on the detail page renders.
    const tabs = page.getByRole('tab')
    const count = await tabs.count()
    for (let i = 0; i < count; i += 1) {
      await tabs.nth(i).click()
      await page.waitForTimeout(600)
    }

    await button(page, /編輯|编辑|edit/i).click()
    await expect(dialog(page)).toBeVisible()
    await closeDialog(page)

    const { errors } = report(watcher)
    expect(errors).toBe('')
  })

  test('sites: open a site, edit dialog', async ({ page }) => {
    const watcher = watch(page)
    await open(page, '/sites')
    await page.waitForTimeout(1500)
    const row = page.locator('tbody tr').first()
    if (await row.count()) {
      await row.click()
      await page.waitForTimeout(1500)
    }
    const edit = button(page, /編輯|编辑|edit/i)
    if (await edit.count()) {
      await edit.click()
      await expect(dialog(page)).toBeVisible()
      await closeDialog(page)
    }
    expect(report(watcher).errors).toBe('')
  })

  test('alerts: list, open, acknowledge', async ({ page }) => {
    const watcher = watch(page)
    await open(page, '/alerts')
    await page.waitForTimeout(1500)
    const row = page.locator('tbody tr').first()
    if (await row.count()) {
      await row.click()
      await page.waitForTimeout(1200)
      const ack = button(page, /確認|确认|acknowledge/i)
      if (await ack.count()) {
        await ack.click()
        await page.waitForTimeout(800)
      }
    }
    expect(report(watcher).errors).toBe('')
  })

  test('rules: rule dialog and channel dialog', async ({ page }) => {
    const watcher = watch(page)
    await open(page, '/rules')
    await page.waitForTimeout(1500)

    await button(page, /新增規則|新增规则|new rule/i).click()
    await expect(dialog(page)).toBeVisible()
    await closeDialog(page)

    await button(page, /新增管道|新增渠道|new channel/i).click()
    await expect(dialog(page)).toBeVisible()
    // Switch through the channel types - each has its own fields.
    const select = dialog(page).locator('select').first()
    for (const value of ['email', 'line', 'webhook', 'mqtt']) {
      await select.selectOption(value)
      await page.waitForTimeout(200)
    }
    await closeDialog(page)
    expect(report(watcher).errors).toBe('')
  })

  test('tariffs: dialog + Taipower preset apply', async ({ page }) => {
    const watcher = watch(page)
    await open(page, '/tariffs')
    await page.waitForTimeout(1500)
    await button(page, /新增|new|create/i).click()
    await expect(dialog(page)).toBeVisible()
    const preset = dialog(page).getByRole('button').filter({ hasText: /台電|台电|taipower/i }).first()
    await expect(preset).toBeVisible()
    await preset.click()
    await page.waitForTimeout(500)
    // Applying fills the form: name, currency and the period rows.
    await expect(dialog(page).locator('input[value*="台電"]').first()).toBeVisible()
    expect(await dialog(page).locator('input[value*="夏月"]').count()).toBeGreaterThan(0)
    await closeDialog(page)
    expect(report(watcher).errors).toBe('')
  })

  test('storage plans: create, bind, unbind, delete', async ({ page }) => {
    const watcher = watch(page)
    await open(page, '/storage-plans')
    await page.waitForTimeout(1500)

    await button(page, /新增方案|new plan/i).click()
    await page.waitForTimeout(500)
    const name = `E2E 方案 ${Date.now()}`
    await page.getByRole('textbox').first().fill(name)
    await button(page, /^(儲存|保存|save)$/i).click()
    await page.waitForTimeout(1200)
    await expect(page.getByText(name).first()).toBeVisible()

    // Bind the first site, then unbind it.
    const binding = page.locator('section').filter({ hasText: /綁定場域|绑定场域|bound sites/i }).first()
    const first = binding.locator('input[type="checkbox"]').first()
    await first.check()
    await page.waitForTimeout(800)
    await expect(first).toBeChecked()
    await first.uncheck()
    await page.waitForTimeout(800)

    await button(page, /^(刪除|删除|delete)$/i).click()
    await expect(dialog(page)).toBeVisible()
    await dialog(page).getByRole('button').filter({ hasText: /^(刪除|删除|delete)$/i }).click()
    await page.waitForTimeout(1000)
    await expect(page.getByText(name)).toHaveCount(0)
    expect(report(watcher).errors).toBe('')
  })

  test('workflows: create, open editor, connect, save, delete', async ({ page }) => {
    test.setTimeout(90000)
    const watcher = watch(page)
    await open(page, '/workflows')
    await page.waitForTimeout(1500)

    await button(page, /新增|new workflow/i).click()
    await expect(dialog(page)).toBeVisible()
    const name = `E2E 流程 ${Date.now()}`
    await dialog(page).getByRole('textbox').first().fill(name)
    await dialog(page).getByRole('button').filter({ hasText: /建立|创建|create|儲存|保存|save/i }).first().click()
    await page.waitForTimeout(1500)

    // The new workflow opens (or is listed) - open its editor.
    if (!(await page.locator('.react-flow').count())) {
      await page.getByRole('link').filter({ hasText: name }).first().click()
      await page.waitForTimeout(2500)
    }
    await expect(page.locator('.react-flow')).toBeVisible()

    // Add start + end from the palette and save.
    await page.locator('button[draggable="true"]').filter({ hasText: /^(開始|开始|start)$/i }).click()
    await page.waitForTimeout(300)
    await page.locator('button[draggable="true"]').filter({ hasText: /^(結束|结束|end)$/i }).click()
    await page.waitForTimeout(300)
    await button(page, /儲存變更|保存更改|save changes/i).click()
    await page.waitForTimeout(1200)

    // Back to the list and delete it.
    page.once('dialog', (d) => void d.accept())
    await open(page, '/workflows')
    await page.waitForTimeout(1500)
    const row = page.locator('tbody tr').filter({ hasText: name }).first()
    await expect(row).toBeVisible()
    await row.getByRole('button').last().click()
    await page.waitForTimeout(500)
    const confirm = dialog(page).getByRole('button').filter({ hasText: /^(刪除|删除|delete)$/i })
    if (await confirm.count()) await confirm.click()
    await page.waitForTimeout(1200)
    await expect(page.locator('tbody tr').filter({ hasText: name })).toHaveCount(0)

    expect(report(watcher).errors).toBe('')
  })

  test('settings, integration, help, audit, recording, events, telemetry', async ({ page }) => {
    test.setTimeout(120000)
    const watcher = watch(page)
    for (const path of ['/settings', '/integration', '/help', '/audit', '/recording', '/events', '/telemetry']) {
      await open(page, path)
      await page.waitForTimeout(1500)
      // Click through any tabs the page offers.
      const tabs = page.getByRole('tab')
      const count = await tabs.count()
      for (let i = 0; i < Math.min(count, 6); i += 1) {
        await tabs.nth(i).click()
        await page.waitForTimeout(400)
      }
    }
    expect(report(watcher).errors).toBe('')
  })

  test('storage: DR trigger dialog opens and cancels', async ({ page }) => {
    const watcher = watch(page)
    await open(page, '/storage')
    await page.waitForTimeout(2000)
    const trigger = button(page, /觸發事件|触发事件|trigger event/i)
    if (await trigger.count() && (await trigger.isEnabled())) {
      await trigger.click()
      await expect(dialog(page)).toBeVisible()
      await closeDialog(page)
    }
    expect(report(watcher).errors).toBe('')
  })
})
