import { expect, test, type Page } from '@playwright/test'

import { open, watch } from './helpers'

/**
 * The foolproofing layer: the things that stop an operator from doing the
 * wrong thing by accident. Each test provokes the mistake and checks the
 * console stopped it *before* anything reached the server.
 */

function dialog(page: Page) {
  return page.locator('[role="dialog"]').last()
}

test.describe('guards', () => {
  test('a storage plan with an impossible SOC band cannot be saved', async ({ page }) => {
    const watcher = watch(page)
    await open(page, '/storage-plans')
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: /新增|new plan|create/i }).first().click()
    await page.waitForTimeout(500)

    const name = page.getByLabel(/名稱|name/i).first()
    await name.fill('E2E 防呆')
    const minSoc = page.getByLabel(/SOC 下限|SOC floor/i).first()
    const maxSoc = page.getByLabel(/SOC 上限|SOC ceiling/i).first()
    await minSoc.fill('90')
    await maxSoc.fill('80')
    await expect(page.getByText(/下限必須小於上限|floor must be below/i)).toBeVisible()
    const save = page.getByRole('button', { name: /^儲存$|^save$|保存/i }).first()
    await expect(save).toBeDisabled()

    await maxSoc.fill('95')
    await expect(page.getByText(/下限必須小於上限|floor must be below/i)).toHaveCount(0)
    await expect(save).toBeEnabled()
    expect(watcher.failedRequests.filter((l) => /^5/.test(l))).toEqual([])
  })

  test('an alert rule band with the bounds reversed is refused inline', async ({ page }) => {
    await open(page, '/rules')
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: /新增規則|新增规则|new rule/i }).first().click()
    await expect(dialog(page)).toBeVisible()
    // The operator select is the one offering an "outside" band.
    const operator = dialog(page).locator('select').filter({ has: page.locator('option[value="outside"]') }).first()
    await operator.selectOption('outside')
    await dialog(page).getByLabel(/^閾值|^threshold$|^阈值/i).first().fill('100')
    await dialog(page).getByLabel(/上界|upper/i).first().fill('50')
    await expect(dialog(page).getByText(/上限必須大於下限|upper bound must be above|上限必须大于下限/i)).toBeVisible()
    await page.keyboard.press('Escape')
  })

  test('escaping a dirty dialog asks before discarding', async ({ page }) => {
    await open(page, '/sites')
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: /新增場域|新增场域|new site|add site/i }).first().click()
    await expect(dialog(page)).toBeVisible()
    await dialog(page).getByLabel(/名稱|name/i).first().fill('E2E 未儲存')
    await page.keyboard.press('Escape')
    // Still open, now asking.
    await expect(dialog(page)).toBeVisible()
    await expect(dialog(page).getByText(/放棄|discard/i).first()).toBeVisible()
    await dialog(page).getByRole('button', { name: /繼續編輯|keep editing/i }).click()
    await expect(dialog(page).getByLabel(/名稱|name/i).first()).toHaveValue('E2E 未儲存')
    await page.keyboard.press('Escape')
    await dialog(page).getByRole('button', { name: /放棄變更|放弃更改|discard changes/i }).click()
    await expect(page.locator('[role="dialog"]')).toHaveCount(0)
  })

  test('a clean dialog closes on Escape without asking', async ({ page }) => {
    await open(page, '/sites')
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: /新增場域|新增场域|new site|add site/i }).first().click()
    await expect(dialog(page)).toBeVisible()
    await page.waitForTimeout(300)
    await page.keyboard.press('Escape')
    await expect(page.locator('[role="dialog"]')).toHaveCount(0)
  })

  test('a real workflow run asks for confirmation and names the command nodes', async ({ page }) => {
    await open(page, '/workflows')
    await page.waitForTimeout(1500)
    await page.getByRole('link').filter({ hasText: /需量反應演練/ }).first().click()
    await expect(page.locator('.react-flow')).toBeVisible()
    await page.waitForTimeout(1000)
    await page.getByRole('button', { name: /^執行$|^run$/i }).first().click()
    await expect(dialog(page)).toBeVisible()
    await expect(dialog(page).getByText(/2 個節點|2 node/i)).toBeVisible()
    // Back out: nothing was started.
    await dialog(page).getByRole('button', { name: /取消|cancel/i }).click()
    await expect(page.locator('[role="dialog"]')).toHaveCount(0)
  })

  test('the jump target is a node picker, not a free-text id', async ({ page }) => {
    await open(page, '/workflows')
    await page.waitForTimeout(1500)
    await page.getByRole('link').filter({ hasText: /光電餘電優先充電/ }).first().click()
    await expect(page.locator('.react-flow')).toBeVisible()
    await page.waitForTimeout(1000)
    await page.locator('.react-flow__node').filter({ hasText: /重新檢查/ }).first().click()
    await page.waitForTimeout(400)
    const picker = page.locator('select').filter({ has: page.locator('option[value="if_end-1"]') }).first()
    await expect(picker).toBeVisible()
    await expect(picker).toHaveValue('if_end-1')
  })

  test('an out-of-range command parameter blocks the send button', async ({ page }) => {
    await open(page, '/devices')
    await page.waitForTimeout(1500)
    await page.getByText(/BESS-01/).first().click()
    await page.waitForURL(/\/devices\/[0-9a-f-]+/, { timeout: 20_000 })
    await page.waitForTimeout(1000)
    await page.getByRole('button', { name: /送出指令|下達指令|send command/i }).first().click()
    await expect(dialog(page)).toBeVisible()
    const command = dialog(page).locator('select').first()
    await command.selectOption('set_power_setpoint')
    const power = dialog(page).getByLabel(/功率設定值|power setpoint/i).first()
    await power.fill('99999999')
    await expect(dialog(page).getByText(/不可大於|must be at most/i)).toBeVisible()
    const send = dialog(page).getByRole('button', { name: /送出指令|下達指令|send command/i }).last()
    await expect(send).toBeDisabled()
    await power.fill('100000')
    await expect(send).toBeEnabled()
    await page.keyboard.press('Escape')
  })
})

test.describe('notification channel test button', () => {
  test('explains a failure inline without saving anything', async ({ page }) => {
    await open(page, '/rules')
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: /新增管道|新增渠道|new channel/i }).first().click()
    await expect(dialog(page)).toBeVisible()
    const type = dialog(page).locator('select').filter({ has: page.locator('option[value="line"]') }).first()
    await type.selectOption('line')
    await dialog(page).getByLabel(/名稱|name/i).first().fill('E2E LINE')
    await dialog(page).getByLabel(/channel access token/i).first().fill('not-a-real-token')
    const to = dialog(page).getByLabel(/接收對象|接收对象|recipient id/i).first()
    await to.fill('2008190840')
    // The shape check fires before anything is sent.
    await expect(dialog(page).getByText(/格式不對|格式不对|wrong shape/i)).toBeVisible()
    await to.fill('U' + '0'.repeat(32))
    await dialog(page).getByRole('button', { name: /測試發送|测试发送|send test/i }).click()
    await expect(dialog(page).getByText(/測試失敗|测试失败|test failed/i)).toBeVisible({ timeout: 30_000 })
    await expect(dialog(page).getByText(/401/)).toBeVisible()
    await page.keyboard.press('Escape')
    await dialog(page).getByRole('button', { name: /放棄變更|放弃更改|discard changes/i }).click()
  })

  test('email without any SMTP is reported, not silently accepted', async ({ page }) => {
    await open(page, '/rules')
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: /新增管道|新增渠道|new channel/i }).first().click()
    await expect(dialog(page)).toBeVisible()
    await dialog(page).getByLabel(/名稱|name/i).first().fill('E2E mail')
    await dialog(page).getByLabel(/收件人|recipients/i).first().fill('ops@example.com')
    await dialog(page).getByRole('button', { name: /測試發送|测试发送|send test/i }).click()
    await expect(dialog(page).getByText(/測試失敗|测试失败|test failed/i)).toBeVisible({ timeout: 30_000 })
    await expect(dialog(page).getByText(/No SMTP server configured/)).toBeVisible()
    await page.keyboard.press('Escape')
    await dialog(page).getByRole('button', { name: /放棄變更|放弃更改|discard changes/i }).click()
  })
})

test.describe('energy asset editor', () => {
  test('binds a device to a role from the storage page and unbinds it again', async ({ page }) => {
    await open(page, '/storage')
    await page.waitForTimeout(2000)
    await page.getByRole('button', { name: /綁定資產|bind asset/i }).first().click()
    await expect(dialog(page)).toBeVisible()
    const deviceSelect = dialog(page).locator('select').first()
    // The site's PV unit - it reports pv_power_w, so the metric picker is populated.
    const option = deviceSelect.locator('option').filter({ hasText: /PV-01/ }).first()
    await deviceSelect.selectOption(await option.getAttribute('value') as string)
    const roleSelect = dialog(page).locator('select').filter({ has: page.locator('option[value="ev_charger"]') }).first()
    await roleSelect.selectOption('ev_charger')
    await page.waitForTimeout(1500)
    const powerSelect = dialog(page).locator('select').filter({ has: page.locator('option[value="pv_power_w"]') }).first()
    await powerSelect.selectOption('pv_power_w')
    await dialog(page).getByLabel(/納入能源平衡|include in energy balance/i).uncheck()
    await dialog(page).getByRole('button', { name: /^儲存$|^save$/i }).click()
    await page.waitForTimeout(1500)
    const row = page.locator('tr').filter({ hasText: /充電樁|EV charger/i }).filter({ hasText: /PV-01/ }).first()
    await expect(row).toBeVisible()
    await expect(row.getByText(/不計入平衡|not in balance/i)).toBeVisible()
    // Clean up: unbind it.
    await row.getByRole('button', { name: /刪除|delete/i }).click()
    await page.getByRole('button', { name: /^確認$|^confirm$/i }).click()
    await page.waitForTimeout(1500)
    await expect(page.locator('tr').filter({ hasText: /充電樁|EV charger/i })).toHaveCount(0)
  })
})

test.describe('gateway management', () => {
  test('registers a gateway, shows its credential once, requests rebirth, removes it', async ({ page }) => {
    await open(page, '/integration')
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: /登錄閘道器|登记网关|register gateway/i }).click()
    await expect(dialog(page)).toBeVisible()
    const id = `E2E-GW-${Date.now() % 100000}`
    await dialog(page).getByLabel(/節點 ID|节点 ID|node id/i).fill(id)
    await dialog(page).getByRole('button', { name: /^儲存$|^save$/i }).click()
    // The credential modal shows the one-time password.
    await expect(page.locator('[role="dialog"]').last().getByText(/Password/)).toBeVisible({ timeout: 15_000 })
    await page.locator('[role="dialog"]').last().getByRole('button', { name: /關閉|close/i }).last().click()
    const row = page.locator('tr').filter({ hasText: id }).first()
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: /重生|rebirth/i }).click()
    await expect(page.getByText(/重生要求|rebirth requested/i).first()).toBeVisible()
    await row.getByRole('button', { name: /刪除|delete/i }).click()
    await page.getByRole('button', { name: /^確認$|^confirm$/i }).click()
    await expect(page.locator('tr').filter({ hasText: id })).toHaveCount(0, { timeout: 10_000 })
  })
})

test.describe('scheduled dispatch windows', () => {
  test('creates a charge window, sees it in force, deletes it', async ({ page }) => {
    await open(page, '/storage')
    await page.waitForTimeout(2000)
    await page.getByRole('button', { name: /新增時段|新增时段|add window/i }).click()
    await expect(dialog(page)).toBeVisible()
    await dialog(page).getByLabel(/^功率|^power/i).fill('120')
    const pad = (n: number) => String(n).padStart(2, '0')
    const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
    const start = new Date(Date.now() - 60_000)
    const end = new Date(Date.now() + 30 * 60_000)
    await dialog(page).getByLabel(/^開始|^开始|^from/i).fill(fmt(start))
    await dialog(page).getByLabel(/^結束|^结束|^until/i).fill(fmt(end))
    await dialog(page).getByLabel(/備註|备注|notes/i).fill('E2E window')
    await dialog(page).getByRole('button', { name: /^儲存$|^save$/i }).click()
    const row = page.locator('tr').filter({ hasText: 'E2E window' }).first()
    await expect(row).toBeVisible({ timeout: 10_000 })
    await expect(row.getByText(/生效中|in force/i)).toBeVisible()
    await row.getByRole('button', { name: /刪除|delete/i }).click()
    await page.getByRole('button', { name: /^確認$|^confirm$/i }).click()
    await expect(page.locator('tr').filter({ hasText: 'E2E window' })).toHaveCount(0, { timeout: 10_000 })
  })
})
