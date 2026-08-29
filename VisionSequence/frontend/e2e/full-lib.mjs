/**
 * full-*.mjs 共用的測試骨架：瀏覽器、登入、API、截圖編號、問題收集、清單回報。
 * Playwright 取自 ZQS-Cloud 的 node_modules（與 smoke.mjs 相同）。
 */
import { chromium } from 'file:///D:/Working%20Space/Python/ZQS-Cloud/frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import path from 'node:path'

export const BASE = 'http://127.0.0.1:5173'
export const OUT = 'D:/Working Space/Python/VisionSequence/Image'
export const ADMIN = { username: 'admin', password: 'admin123' }
export const WORKER = { username: 'worker1', password: 'worker123' }

/** i18n 命名空間：畫面上若出現 `ns.key.sub` 這種原始 key 就是漏翻。 */
const I18N_NS = 'app|nav|auth|users|lock|common|errors|capacity|status|dashboard|flows|editor|tool|teach|golden|connections|viewer|help|sources|assets|settings|templates|batch|stats|integration|palette|nodeMenu|helpMenu|recipes|breadcrumb'
export const I18N_RE = new RegExp(`(?:^|[\\s「（(>])(?:${I18N_NS})\\.[a-zA-Z_]+(?:\\.[a-zA-Z_0-9]+)*(?=$|[\\s」）)<:：])`, 'g')

export async function createHarness({ headless = true } = {}) {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await chromium.launch({ headless })
  const h = {
    browser,
    issues: [],
    results: {},
    shots: [],
    shotIndex: 0,
    // 預設允許：未登入時 AuthProvider 先打 /auth/me 會 401（登入頁本來就會遇到）
    allow: [
      /401 GET .*\/api\/auth\/me/,
      // 「用上次影像重跑」的影像被快取淘汰：後端回 404 image_gone，前端 previewFlow 會自動改用來源重試（預期中的 404）
      /404 POST .*\/api\/vision\/flows\/\d+\/preview/,
    ],
    consoleLog: [],
  }

  h.note = (msg) => {
    h.issues.push(msg)
    console.log('ISSUE', msg)
  }
  /** 清單回報：同一 ID 多次回報時，任何一次失敗就算失敗（note 累積）。 */
  h.item = (id, ok, note = '') => {
    const prev = h.results[id]
    const entry = prev ? { ok: prev.ok && Boolean(ok), note: [prev.note, ok ? '' : note].filter(Boolean).join('；') } : { ok: Boolean(ok), note: ok ? '' : note }
    h.results[id] = entry
    console.log(`${ok ? 'PASS' : 'FAIL'} ${id}${ok ? '' : ` — ${note}`}`)
    if (!ok) h.issues.push(`${id}: ${note}`)
    return Boolean(ok)
  }
  h.skip = (id, why) => {
    h.results[id] = { ok: null, note: why }
    console.log(`SKIP ${id} — ${why}`)
  }
  h.step = async (name, fn) => {
    console.log(`--- ${name}`)
    try {
      await fn()
    } catch (e) {
      h.note(`[${name}] ${String(e.message || e).split('\n').filter((l) => l.trim()).slice(0, 3).join(' | ').slice(0, 300)}`)
      // 失敗當下截一張，方便回頭看
      try {
        if (h.currentPage && !h.currentPage.isClosed()) await h.shot(h.currentPage, `fail-${name.replace(/[^\w-]+/g, '_').slice(0, 40)}`)
      } catch {
        /* ignore */
      }
    }
  }
  /** 預期中的 4xx：回傳解除函式。 */
  h.allowStatus = (re) => {
    h.allow.push(re)
    // 解除時延遲一點：response 事件與 console 訊息可能比 UI 反應晚到
    return () =>
      setTimeout(() => {
        const i = h.allow.indexOf(re)
        if (i >= 0) h.allow.splice(i, 1)
      }, 1500)
  }
  const allowed = (status, method, url) => h.allow.some((re) => re.test(`${status} ${method} ${url}`))

  // ---- 瀏覽器 ----
  h.newContext = async ({ viewport = { width: 1600, height: 1000 }, token = null, locale = 'zh-TW', colorScheme = 'light' } = {}) => {
    const context = await browser.newContext({ viewport, locale, colorScheme, acceptDownloads: true })
    if (token) await context.addInitScript((tk) => localStorage.setItem('vs.token', tk), token)
    return context
  }
  h.newPage = async (context, tag = '') => {
    const page = await context.newPage()
    h.currentPage = page
    page.on('console', (m) => {
      const type = m.type()
      if (type !== 'error' && type !== 'warning') return
      const text = m.text()
      if (/React DevTools|\[vite\]|Download the React DevTools/.test(text)) return
      // 測試本身對 viewer canvas 反覆 getImageData 造成的提示，不是產品問題
      if (/willReadFrequently/.test(text)) return
      // React Flow（dev）掛載後 1 秒檢查 attribution 是否可見：測試在 1 秒內離開編輯器會誤報（元素已 unmount），不是產品問題
      if (/hiding the attribution/.test(text)) return
      const url = m.location()?.url ?? ''
      if (/Failed to load resource/.test(text)) {
        const st = /status of (\d+)/.exec(text)?.[1] ?? '0'
        if (['GET', 'POST', 'PATCH', 'DELETE'].some((m) => allowed(st, m, url))) return
      }
      // React 的 %s 佔位：把參數帶進來才看得到是哪個 key
      const args = m.args().length > 1 ? ` args=${m.args().slice(1).map((a) => String(a).slice(0, 60)).join(' , ')}` : ''
      h.consoleLog.push(`${tag} console.${type}: ${text.slice(0, 300)}${args}`)
      h.note(`${tag} console.${type}: ${text.slice(0, 200)}${args}`)
    })
    page.on('pageerror', (e) => h.note(`${tag} pageerror: ${String(e.message).slice(0, 300)}`))
    page.on('response', (r) => {
      const status = r.status()
      if (status < 400) return
      const url = r.url()
      const method = r.request().method()
      if (allowed(status, method, url)) return
      h.note(`${tag} HTTP ${status} ${method} ${url.replace(BASE, '')}`)
    })
    page.on('dialog', (d) => {
      const handler = page.__dialog
      if (handler) handler(d)
      else d.accept()
    })
    return page
  }
  /** 下一個 window.confirm 的回答。 */
  h.nextDialog = (page, accept) => {
    page.__dialog = (d) => {
      page.__dialog = null
      if (accept) d.accept()
      else d.dismiss()
    }
  }

  h.shot = async (page, name, { full = false } = {}) => {
    h.shotIndex += 1
    const file = `120-${String(h.shotIndex).padStart(3, '0')}-${name}.png`
    const p = path.join(OUT, file)
    await page.screenshot({ path: p, fullPage: full })
    h.shots.push(p)
    console.log('shot', file)
    await h.checkPage(page, name)
    return p
  }
  /** 每張截圖順便檢查：未翻譯 key、水平捲軸。 */
  h.checkPage = async (page, tag) => {
    try {
      const info = await page.evaluate(() => ({
        text: document.body.innerText,
        scrollW: document.documentElement.scrollWidth,
        clientW: document.documentElement.clientWidth,
        bodyScrollW: document.body.scrollWidth,
      }))
      const keys = [...info.text.matchAll(I18N_RE)].map((m) => m[0].trim())
      if (keys.length) h.item('W06', false, `${tag}: 未翻譯 key ${[...new Set(keys)].slice(0, 5).join(', ')}`)
      if (info.scrollW > info.clientW + 1 || info.bodyScrollW > info.clientW + 1) {
        const vp = page.viewportSize()
        h.item(vp && vp.width <= 1280 ? 'W01' : 'W02', false, `${tag}: 水平捲軸 scrollWidth=${Math.max(info.scrollW, info.bodyScrollW)} > ${info.clientW}`)
      }
    } catch {
      /* 頁面已關 */
    }
  }

  // ---- API（管理員）----
  const apiCtx = await browser.newContext()
  h.apiCtx = apiCtx
  h.token = null
  h.headers = () => (h.token ? { Authorization: `Bearer ${h.token}` } : {})
  h.login = async (cred = ADMIN) => {
    const r = await apiCtx.request.post(`${BASE}/api/auth/login`, { data: cred })
    const body = await r.json().catch(() => null)
    if (!body?.token) throw new Error(`login ${cred.username} failed: ${r.status()} ${JSON.stringify(body)}`)
    return body.token
  }
  h.loginAdmin = async () => {
    h.token = await h.login(ADMIN)
    return h.token
  }
  const json = async (r) => {
    try {
      return await r.json()
    } catch {
      return null
    }
  }
  h.api = {
    raw: (method, p, opts = {}) => apiCtx.request.fetch(`${BASE}/api${p}`, { method, headers: { ...h.headers(), ...(opts.headers ?? {}) }, data: opts.data, multipart: opts.multipart }),
    get: async (p) => json(await apiCtx.request.get(`${BASE}/api${p}`, { headers: h.headers() })),
    post: async (p, data) => json(await apiCtx.request.post(`${BASE}/api${p}`, { headers: h.headers(), data })),
    patch: async (p, data) => json(await apiCtx.request.patch(`${BASE}/api${p}`, { headers: h.headers(), data })),
    del: async (p) => apiCtx.request.delete(`${BASE}/api${p}`, { headers: h.headers() }),
  }

  // ---- 常用工具 ----
  h.toast = async (page, re, timeout = 5000) => {
    const loc = page.locator('[role=status] .card p').filter({ hasText: re })
    try {
      await loc.first().waitFor({ timeout })
      return (await loc.first().innerText()).trim()
    } catch {
      return null
    }
  }
  h.dialog = (page) => page.locator('[role=dialog]').last()
  h.waitGone = async (loc, timeout = 5000) => {
    try {
      await loc.waitFor({ state: 'detached', timeout })
      return true
    } catch {
      return false
    }
  }
  h.sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  /** 用瀏覽器 canvas 產生 PNG（node 沒有 canvas）。 */
  h.makePng = async (page, { w = 640, h: hh = 480, dots = 5, seed = 0, bg = '#d8d8d8' } = {}) => {
    const dataUrl = await page.evaluate(({ w, hh, dots, seed, bg }) => {
      const c = document.createElement('canvas')
      c.width = w
      c.height = hh
      const ctx = c.getContext('2d')
      ctx.fillStyle = bg
      ctx.fillRect(0, 0, w, hh)
      ctx.fillStyle = '#202020'
      let s = seed + 1
      const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280)
      for (let i = 0; i < dots; i += 1) {
        ctx.beginPath()
        ctx.arc(40 + rnd() * (w - 80), 40 + rnd() * (hh - 80), 18 + rnd() * 14, 0, Math.PI * 2)
        ctx.fill()
      }
      return c.toDataURL('image/png')
    }, { w, hh, dots, seed, bg })
    return Buffer.from(dataUrl.split(',')[1], 'base64')
  }
  h.viewerHasImage = (page, sel) =>
    page.evaluate((s) => {
      const root = s ? document.querySelector(s) : document
      const c = root?.querySelector('canvas')
      if (!c) return false
      const ctx = c.getContext('2d')
      const d = ctx.getImageData(0, 0, c.width, c.height).data
      let non = 0
      for (let i = 0; i < d.length; i += 4 * 97) if (d[i + 3] > 0) non++
      return non > 50
    }, sel)

  h.close = async () => {
    await browser.close()
  }
  h.writeResults = () => {
    const p = path.resolve('D:/Working Space/Python/VisionSequence/frontend/e2e/full-results.json')
    fs.writeFileSync(p, JSON.stringify({ results: h.results, issues: h.issues, shots: h.shots.length }, null, 2))
    return p
  }
  return h
}
