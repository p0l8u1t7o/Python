/**
 * 全頁面截圖：`npx tsx e2e/screenshots.script.ts`（不是測試，是工具）。
 *
 * 產出到專案根目錄 Image/{light,dark}/<nn>-<頁名>.png，deviceScaleFactor 2
 * （3200×1800 實際像素）求清晰。3D 與地圖頁多等幾秒讓動畫與圖磚就位。
 */
import { mkdirSync } from 'node:fs'
import path from 'node:path'

import { chromium, type Page } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173'
const OUT = path.resolve(import.meta.dirname, '..', '..', 'Image')
const EMAIL = 'admin@example.com'
const PASSWORD = 'ChangeMe-2026!'

interface Shot {
  name: string
  path: string
  /** Extra settle time (ms) for canvases, tiles, charts. */
  wait?: number
  fullPage?: boolean
  /** Runs after navigation, before the screenshot. */
  prepare?: (page: Page) => Promise<void>
}

const SHOTS: Shot[] = [
  { name: '01-總覽', path: '/', wait: 3000, fullPage: true },
  { name: '02-設備', path: '/devices', wait: 2000, fullPage: true },
  {
    name: '03-設備詳情',
    path: '/devices',
    wait: 2500,
    fullPage: true,
    prepare: async (page) => {
      await page.getByText(/BESS/).first().click()
      await page.waitForURL(/\/devices\/[0-9a-f-]{36}/)
      await page.waitForTimeout(2500)
    },
  },
  { name: '04-地圖', path: '/map', wait: 4000, fullPage: true },
  { name: '05-警報', path: '/alerts', wait: 1500, fullPage: true },
  { name: '06-儲能', path: '/storage', wait: 4500, fullPage: true },
  { name: '07-儲能規劃', path: '/storage-plans', wait: 1500, fullPage: true },
  { name: '08-時序資料', path: '/telemetry', wait: 2500, fullPage: true },
  { name: '09-場域', path: '/sites', wait: 4000, fullPage: true },
  { name: '10-記錄策略', path: '/recording', wait: 1500, fullPage: true },
  { name: '11-警報規則', path: '/rules', wait: 1500, fullPage: true },
  { name: '12-電價方案', path: '/tariffs', wait: 1500, fullPage: true },
  { name: '13-工作流程', path: '/workflows', wait: 1500, fullPage: true },
  {
    name: '14-工作流程編輯器',
    path: '/workflows',
    wait: 2000,
    prepare: async (page) => {
      await page.locator('table tbody tr a').first().click()
      await page.waitForURL(/\/workflows\/[0-9a-f-]{36}/)
      await page.waitForSelector('.react-flow__node', { timeout: 15_000 })
      await page.waitForTimeout(1500)
    },
  },
  {
    name: '15-工作流程範本庫',
    path: '/workflows',
    wait: 1200,
    prepare: async (page) => {
      await page.getByTestId('open-template-gallery').click()
      await page.waitForSelector('[data-testid=template-gallery]')
      await page.waitForTimeout(800)
    },
  },
  { name: '16-事件紀錄', path: '/events', wait: 1500, fullPage: true },
  { name: '17-稽核紀錄', path: '/audit', wait: 1500, fullPage: true },
  { name: '18-設定', path: '/settings', wait: 1500, fullPage: true },
  { name: '19-外部整合', path: '/integration', wait: 1500, fullPage: true },
  { name: '20-說明', path: '/help', wait: 1500, fullPage: true },
]

async function run() {
  const browser = await chromium.launch({
    args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--force-color-profile=srgb'],
  })
  for (const scheme of ['light', 'dark'] as const) {
    const dir = path.join(OUT, scheme)
    mkdirSync(dir, { recursive: true })
    const context = await browser.newContext({
      viewport: { width: 1600, height: 900 },
      deviceScaleFactor: 2,
      colorScheme: scheme,
      locale: 'zh-TW',
    })
    const page = await context.newPage()
    await page.goto(`${BASE}/login`)
    await page.fill('input[type=email]', EMAIL)
    await page.fill('input[type=password]', PASSWORD)
    await page.click('button[type=submit]')
    await page.waitForURL((url) => !url.pathname.includes('login'), { timeout: 20_000 })

    for (const shot of SHOTS) {
      try {
        await page.goto(`${BASE}${shot.path}`)
        await page.waitForLoadState('networkidle').catch(() => {})
        if (shot.prepare) await shot.prepare(page)
        await page.waitForTimeout(shot.wait ?? 1500)
        await page.screenshot({
          path: path.join(dir, `${shot.name}.png`),
          fullPage: shot.fullPage ?? false,
        })
        console.log(`${scheme}/${shot.name}.png`)
      } catch (error) {
        console.error(`FAILED ${scheme}/${shot.name}:`, (error as Error).message)
      }
    }
    await context.close()
  }
  await browser.close()
}

void run()
