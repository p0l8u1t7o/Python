/** 模組 layout：1280×800 與 1600×1000 排版（W01、W02、F22）、深色截圖（W03）、SSE 斷線重連（W04）。 */
import { execSync, spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { BASE } from './full-lib.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url)).slice(0, -1)  // 專案根目錄（依本檔位置推算，不寫死）

/** 真的把後端重啟一次：SSE 會斷線（onerror）→ 5 秒後重連。 */
async function restartBackend(h) {
  const out = execSync('netstat -ano -p tcp', { encoding: 'utf8' })
  const pids = new Set()
  for (const line of out.split('\n')) {
    const m = /\s(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):8000\s+\S+\s+LISTENING\s+(\d+)/.exec(line)
    if (m) pids.add(m[1])
  }
  for (const pid of pids) {
    try {
      execSync(`taskkill /PID ${pid} /F`, { stdio: 'ignore' })
    } catch {
      /* ignore */
    }
  }
  await h.sleep(1500)
  const child = spawn(`${REPO}/.venv/Scripts/python.exe`, ['manage.py', 'serve', '--port', '8000'], { cwd: REPO, detached: true, stdio: 'ignore', windowsHide: true })
  child.unref()
  for (let i = 0; i < 40; i += 1) {
    await h.sleep(500)
    try {
      const r = await h.apiCtx.request.get(`${BASE}/api/auth/status`, { timeout: 2000 })
      if (r.ok()) return true
    } catch {
      /* not yet */
    }
  }
  return false
}

export async function run(h) {
  await h.loginAdmin()
  const demo = h.demoFlow()

  for (const [vw, vh, tag, id] of [[1280, 800, 'sm', 'W01'], [1600, 1000, 'lg', 'W02']]) {
    const context = await h.newContext({ token: h.token, viewport: { width: vw, height: vh } })
    const page = await h.newPage(context, `[layout-${tag}]`)
    const routes = [
      ['/', 'dashboard'],
      ['/flows', 'flows'],
      ['/sources', 'sources'],
      ['/assets', 'assets'],
      ['/users', 'users'],
      ['/settings', 'settings'],
      ['/help?tab=glossary', 'help'],
      ['/integration?tab=http', 'integration'],
      ['/integration?tab=plc', 'integration-plc'],
      ['/connections', 'connections'],
      [`/flows/${demo.id}/stats`, 'stats'],
      [`/flows/${demo.id}/teach`, 'teach'],
      [`/flows/${demo.id}/golden`, 'golden'],
    ]
    for (const [path, name] of routes) {
      await h.step(`${id} ${path}`, async () => {
        await page.goto(`${BASE}${path}`)
        await page.waitForLoadState('networkidle')
        await page.waitForTimeout(700)
        await h.shot(page, `${tag}-${name}`)
      })
    }
    await h.step(`${id} F22 editor`, async () => {
      await page.goto(`${BASE}/flows/${demo.id}`)
      await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
      await page.waitForTimeout(600)
      await page.getByTestId('btn-preview').click()
      await h.toast(page, /試跑完成/)
      await page.waitForTimeout(500)
      await h.shot(page, `${tag}-editor`)
      // 三欄都看得到、頂列按鈕沒有重疊（每顆按鈕 bounding box 都在視窗內且互不重疊）
      const boxes = await page.locator('[data-testid=editor-toolbar] button').evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height } }))
      let overlap = 0
      for (let i = 0; i < boxes.length; i += 1)
        for (let j = i + 1; j < boxes.length; j += 1) {
          const a = boxes[i]
          const b = boxes[j]
          if (a.w && b.w && a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1) overlap += 1
        }
      const inside = boxes.every((b) => b.x >= 0 && b.x + b.w <= vw + 1)
      const asides = await page.locator('aside').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().width))
      const canvasVisible = await page.locator('.react-flow').evaluate((el) => el.getBoundingClientRect().height > 100)
      const viewerVisible = await page.locator('[data-testid=viewer-main]').evaluate((el) => el.getBoundingClientRect().height > 100)
      const toolbarH = await page.locator('[data-testid=editor-toolbar]').evaluate((el) => el.getBoundingClientRect().height)
      h.item(id === 'W01' ? 'F22' : 'W02', overlap === 0 && inside && asides.length === 2 && asides.every((w) => w > 150) && canvasVisible && viewerVisible, `overlap=${overlap} inside=${inside} asides=${asides.join(',')} canvas=${canvasVisible} viewer=${viewerVisible} toolbarH=${toolbarH}`)
      // 批次 Modal、範本畫廊在小視窗
      await page.getByTestId('btn-batch').click()
      await h.dialog(page).waitFor()
      await h.shot(page, `${tag}-batch-modal`)
      await page.keyboard.press('Escape')
      await page.getByTestId('btn-templates').click()
      await page.getByTestId('menu-load-template').click()
      await page.getByTestId('template-card').first().waitFor()
      await h.shot(page, `${tag}-template-gallery`)
      await page.keyboard.press('Escape')
      await page.goto(`${BASE}/flows/${demo.id}/tools/blob`)
      await page.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
      await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => null)
      await page.waitForTimeout(500)
      await h.shot(page, `${tag}-tool-page`)
    })
    // 若沒有任何失敗回報，就標為通過
    if (!h.results[id]) h.item(id, true)
    if (id === 'W01' && !h.results.F22) h.item('F22', true)
    await context.close()
  }

  // W03 深色截圖
  await h.step('W03 深色各頁', async () => {
    const context = await h.newContext({ token: h.token, colorScheme: 'dark' })
    await context.addInitScript(() => localStorage.setItem('vs.theme', 'dark'))
    const page = await h.newPage(context, '[dark]')
    for (const [path, name] of [['/', 'dashboard'], ['/flows', 'flows'], ['/sources', 'sources'], ['/assets', 'assets'], ['/users', 'users'], ['/settings', 'settings'], ['/help?tab=ports', 'help'], ['/integration?tab=format', 'integration'], ['/integration?tab=plc', 'integration-plc'], ['/connections', 'connections'], [`/flows/${demo.id}/stats`, 'stats'], [`/flows/${demo.id}/teach`, 'teach'], [`/flows/${demo.id}/golden`, 'golden']]) {
      await page.goto(`${BASE}${path}`)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(600)
      await h.shot(page, `dark-${name}`)
    }
    await page.goto(`${BASE}/flows/${demo.id}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.getByTestId('btn-preview').click()
    await h.toast(page, /試跑完成/)
    await page.waitForTimeout(500)
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(300)
    await page.locator('.react-flow__node[data-id="blob"]').click({ button: 'right' })
    await page.getByTestId('node-menu').waitFor()
    await h.shot(page, 'dark-editor')
    await page.keyboard.press('Escape')
    // 深色下文字對比：主要文字與背景的亮度差
    const contrast = await page.evaluate(() => {
      const lum = (rgb) => {
        const m = /(\d+), (\d+), (\d+)/.exec(rgb)
        if (!m) return 0
        const [r, g, b] = [m[1], m[2], m[3]].map((v) => { const c = Number(v) / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 })
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
      }
      const bg = lum(getComputedStyle(document.body).backgroundColor)
      const fg = lum(getComputedStyle(document.body).color)
      const muted = lum(getComputedStyle(document.querySelector('.text-muted')).color)
      return { text: (Math.max(bg, fg) + 0.05) / (Math.min(bg, fg) + 0.05), muted: (Math.max(bg, muted) + 0.05) / (Math.min(bg, muted) + 0.05) }
    })
    await page.goto(`${BASE}/flows/${demo.id}/tools/blob`)
    await page.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
    await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => null)
    await page.waitForTimeout(500)
    await h.shot(page, 'dark-tool-page')
    const dark = await page.evaluate(() => document.documentElement.classList.contains('dark'))
    h.item('W03', dark && contrast.text >= 7 && contrast.muted >= 4.5, `dark=${dark} contrast text=${contrast.text.toFixed(1)} muted=${contrast.muted.toFixed(1)}`)
    await context.close()
  })

  // W04 SSE 斷線重連
  await h.step('W04 SSE 重連', async () => {
    const context = await h.newContext({ token: h.token })
    const page = await h.newPage(context, '[sse]')
    await page.goto(`${BASE}/flows/${demo.id}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(1000)
    const badge = () => page.locator('[data-testid=editor-toolbar] span.rounded-full').first().innerText()
    const live = await badge()
    // 真的重啟後端：既有 SSE 連線中斷 → 「離線」→ 5 秒後自動重連 → 「即時」
    await page.getByRole('tab', { name: /結果/ }).click()
    await page.waitForTimeout(300)
    const rowsBefore = await page.locator('[data-testid=inspector-pane] table tbody tr').count()
    const topBefore = await page.locator('[data-testid=inspector-pane] table tbody tr').first().innerText().catch(() => '')
    const un = h.allowStatus(/\d+ (GET|POST|PATCH|DELETE) .*\/api\//)
    const restarted = await restartBackend(h)
    // 經 Vite proxy 時後端死掉客戶端連線不會被關，要靠 40 秒心跳看門狗
    const offlineShown = await page.locator('[data-testid=editor-toolbar] span.rounded-full', { hasText: '離線' }).first().waitFor({ timeout: 60000 }).then(() => true).catch(() => false)
    const offline = offlineShown ? '離線' : await badge()
    await h.loginAdmin()
    const restored = await page.locator('[data-testid=editor-toolbar] span.rounded-full', { hasText: '即時' }).first().waitFor({ timeout: 12000 }).then(() => true).catch(() => false)
    await page.waitForTimeout(1500)
    un()
    // 重連後事件仍收得到：API 執行一次 → 最近執行表出現新的一列
    await h.api.post(`/vision/flows/${demo.id}/run?wait=1`, { context: null, wait: true })
    await page.waitForTimeout(1500)
    const rowsAfter = await page.locator('[data-testid=inspector-pane] table tbody tr').count()
    const topAfter = await page.locator('[data-testid=inspector-pane] table tbody tr').first().innerText().catch(() => '')
    const tb = await page.locator('[data-testid=editor-toolbar]').innerText()
    await h.shot(page, 'sse-reconnected')
    h.item('W04', restarted && live === '即時' && offline === '離線' && restored && (rowsAfter >= rowsBefore + 1 || topAfter !== topBefore), `restarted=${restarted} live=${live} offline=${offline} restored=${restored} rows ${rowsBefore}→${rowsAfter} topChanged=${topAfter !== topBefore} toolbar=${tb.includes('即時')}`)
    await context.close()
  })

  // 若整體沒有其他 issue，W05／W06 由 full.mjs 結尾統計；這裡先標 W06 通過（有未翻譯 key 會在 checkPage 時標 ❌）
  if (!h.results.W06) h.item('W06', true)
}
