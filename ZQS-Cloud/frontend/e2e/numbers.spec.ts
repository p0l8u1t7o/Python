import { expect, test, type Page } from '@playwright/test'

import { open } from './helpers'

/**
 * The numbers on screen are the numbers the API returned.
 *
 * `scripts/verify_calculations.py` proves the API agrees with itself; this
 * proves the page did not lose anything on the way: the demand-benefit table
 * and the "today" tiles on the dashboard, and a site's summary on the storage
 * page, all match a direct API call made with the same window.
 */

async function api<T>(page: Page, path: string): Promise<T> {
  const token = await page.evaluate(() => localStorage.getItem('zqs.access'))
  const response = await page.request.get(`http://127.0.0.1:8000${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(response.ok(), `${path} -> ${response.status()}`).toBeTruthy()
  return (await response.json()) as T
}

/** Digits only, so "$67,949" and "67949.23" compare as 67949. */
function digits(text: string): number {
  const cleaned = text.replace(/[^\d.-]/g, '')
  return Math.round(Number(cleaned))
}

interface SiteCost {
  site_name: string
  contract_capacity_kw: number | null
  baseline_peak_kw: number | null
  peak_demand_kw: number | null
  demand_savings: number
  energy_cost: number
}
interface CostOverview {
  total_demand_savings: number
  sites: SiteCost[]
}
interface Live {
  today_energy_cost: number
  today_load_kwh: number
  sites: { site_name: string; today_energy_cost: number; device_count: number }[]
}

test.describe('numbers on screen match the API', () => {
  test('dashboard demand-benefit table and today tiles', async ({ page }) => {
    await open(page, '/')
    await page.waitForTimeout(1500)
    // The energy view, whatever view the saved preference left behind.
    await page.getByRole('button', { name: /能源|Energy/ }).first().click()
    await page.waitForTimeout(800)
    // 7-day window, same as the picker's "7d".
    await page.locator('button[aria-pressed]:visible').filter({ hasText: /7 ?天|7 ?d/i }).first().click()
    await page.waitForTimeout(2500)

    const end = new Date()
    const start = new Date(end.getTime() - 7 * 24 * 3600 * 1000)
    const overview = await api<CostOverview>(
      page,
      `/api/ems/cost-overview?start=${start.toISOString()}&end=${end.toISOString()}`,
    )

    const table = page.locator('table').last()
    await expect(table).toBeVisible()
    for (const site of overview.sites) {
      if (site.baseline_peak_kw === null) continue
      const row = table.locator('tr').filter({ hasText: site.site_name }).first()
      await expect(row).toBeVisible()
      const cells = await row.locator('td').allInnerTexts()
      // [name, contract, baseline, actual, reduction, savings]
      if (site.contract_capacity_kw) {
        expect(digits(cells[1])).toBe(Math.round(site.contract_capacity_kw))
      }
      expect(digits(cells[2])).toBe(Math.round(site.baseline_peak_kw))
      expect(digits(cells[3])).toBe(Math.round(site.peak_demand_kw ?? 0))
      expect(digits(cells[4])).toBe(
        Math.round(site.baseline_peak_kw - (site.peak_demand_kw ?? 0)),
      )
      // The savings cell may carry the "(incl. penalty)" suffix; take the first figure.
      const first = cells[5].split(/[（(]/)[0]
      expect(Math.abs(digits(first) - site.demand_savings)).toBeLessThanOrEqual(1)
    }

    // "Today" tiles: cost and load.
    const live = await api<Live>(page, '/api/ems/live')
    const text = await page.locator('body').innerText()
    const cost = Math.round(live.today_energy_cost)
    const formatted = new Intl.NumberFormat('zh-Hant', {
      style: 'currency', currency: 'TWD', maximumFractionDigits: 0,
    }).format(cost)
    expect(text, `today cost ${formatted} missing`).toContain(formatted)

    // The per-site live table: today's cost per site.
    for (const site of live.sites) {
      if (site.device_count === 0) continue
      const row = page.locator('tr').filter({ hasText: site.site_name }).first()
      const rowText = await row.innerText()
      const expected = new Intl.NumberFormat('zh-Hant', {
        style: 'currency', currency: 'TWD', maximumFractionDigits: 0,
      }).format(Math.round(site.today_energy_cost))
      expect(rowText, `${site.site_name} today cost`).toContain(expected)
    }
  })

  test('storage page summary matches the site summary endpoint', async ({ page }) => {
    await open(page, '/storage')
    await page.waitForTimeout(2000)
    // Whatever site the page opened on, read its id from the overview request.
    const [response] = await Promise.all([
      page.waitForResponse((r) => /\/api\/ems\/sites\/[^/]+\/summary/.test(r.url()), {
        timeout: 20_000,
      }),
      page.locator('button[aria-pressed]:visible').filter({ hasText: /7 ?天|7 ?d/i }).first().click(),
    ])
    const summary = (await response.json()) as {
      energy_cost: number
      grid_import_kwh: number
      load_kwh: number
    }
    const cost = new Intl.NumberFormat('zh-Hant', {
      style: 'currency', currency: 'TWD', maximumFractionDigits: 0,
    }).format(Math.round(summary.energy_cost))
    await expect(page.locator('body')).toContainText(cost, { timeout: 15_000 })
    // The two ratios on the tiles reproduce from the same totals.
    const full = (await response.json()) as {
      pv_kwh: number
      grid_export_kwh: number
      load_kwh: number
      grid_import_kwh: number
    }
    const body = await page.locator('body').innerText()
    if (full.pv_kwh > 0) {
      const selfUse = Math.round(((full.pv_kwh - full.grid_export_kwh) / full.pv_kwh) * 1000) / 10
      expect(body).toContain(`${selfUse}%`)
    }
    if (full.load_kwh > 0) {
      const selfSufficient =
        Math.round(((full.load_kwh - full.grid_import_kwh) / full.load_kwh) * 1000) / 10
      expect(body).toContain(`${selfSufficient}%`)
    }
  })
})
