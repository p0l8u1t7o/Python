// 全站 UI 稽核：32 條路由 × 視角 × 語系，自動檢查＋截圖。給 Codex 跑，視覺判讀由人看截圖。
// 檢查項：主控台錯誤、page error、失敗請求、水平溢出、超出視窗的元素、無名稱按鈕、小點擊目標、
// 截斷文字、固定元素重疊、無 alt 圖片、無標籤輸入、低對比、焦點可見、
// en 介面不得出現全形標點、中文介面不得殘留未翻譯的 i18n key。
// 用法：cd frontend; node ui-audit/audit.mjs   （需要 ui-audit/token.txt；PW_EXE 可指向系統 Chrome）
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const here = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(here, 'out')
fs.mkdirSync(OUT, { recursive: true })
const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const FRONT = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000/api'
const H = { Authorization: `Bearer ${token}` }
const log = (...a) => console.log(...a)
const j = async (p, init) => { const r = await fetch(`${API}${p}`, { headers: H, ...init }); if (!r.ok) throw new Error(`${r.status} ${p}`); return r.json() }

// ---- 0. 連線探針：連不到就明講後停，不要繼續跑出一堆假失敗 ----
async function probe() {
  try {
    const hz = await fetch('http://127.0.0.1:8000/healthz'); if (!hz.ok) throw new Error(`healthz ${hz.status}`)
    const fr = await fetch(FRONT); if (!fr.ok) throw new Error(`front ${fr.status}`)
    const me = await j('/auth/me'); log(`PROBE ok: healthz 200, front 200, 登入者 ${me.username || me.user?.username || '?'}`)
  } catch (e) { log(`PROBE-FAILED 連不到本機伺服器: ${e.message}`); process.exit(2) }
}
await probe()
const launchOpts = process.env.PW_EXE ? { executablePath: process.env.PW_EXE, headless: true } : { channel: 'chrome', headless: true }
let browser
try { browser = await chromium.launch(launchOpts) } catch (e) { log(`PROBE-FAILED 瀏覽器啟動失敗: ${e.message.slice(0, 200)}`); process.exit(2) }
log('PROBE ok: 瀏覽器已啟動')

// ---- 1. 解析參數化路由需要的 id ----
const flows = (await j('/vision/flows?limit=50')).items || []
const flow = flows.find((f) => f.is_enabled) || flows[0]
if (!flow) { log('PROBE-FAILED 沒有任何流程可用'); process.exit(2) }
const full = await j(`/vision/flows/${flow.id}`)
const toolNode = (full.graph?.nodes || []).find((n) => !['image_source', 'fixed_image', 'note'].includes(n.type)) || (full.graph?.nodes || [])[0]
let dashId = null
try { const ds = await j('/vision/dashboards'); dashId = (ds.items || ds)[0]?.id ?? null } catch { /* 沒有看板也沒關係 */ }
log(`flow=${flow.id} "${flow.name}" node=${toolNode?.id} dashboard=${dashId}`)

// ---- 2. 頁面清單（涵蓋 ui_map 的 32 條路由）----
const PAGES = [
  ['home', '/'], ['flows', '/flows'], ['editor', `/flows/${flow.id}`],
  ['tool', `/flows/${flow.id}/tools/${toolNode?.id}`], ['stats', `/flows/${flow.id}/stats`],
  ['teach', `/flows/${flow.id}/teach`], ['station-teach', '/teach'], ['golden', `/flows/${flow.id}/golden`],
  ['dashboards', '/dashboards'], ...(dashId ? [['dashboard-design', `/dashboards/${dashId}/design`], ['dashboard-kiosk', `/dashboard/${dashId}`]] : []),
  ['dashboard-default', '/dashboard'], ['batch', `/batch?flow=${flow.id}`], ['dl', '/dl'], ['agent', '/agent'],
  ['integration', '/integration'], ['int-http', '/integration/http'], ['int-tcp', '/integration/tcp'],
  ['int-events', '/integration/events'], ['int-modbus-server', '/integration/modbus-server'],
  ['int-modbus-client', '/integration/modbus-client'], ['int-capture', '/integration/capture'], ['int-plugins', '/integration/plugins'], ['int-devices', '/integration/devices'],
  ['help', '/help'], ['sources', '/sources'], ['assets', '/assets'], ['calibration', '/calibration'],
  ['users', '/users'], ['audit', '/audit'], ['settings', '/settings'], ['board', `/board/${flow.id}`],
]
// en 跑四個視角；兩種中文只跑桌面（看翻譯覆蓋與版面），控制總時間
const VIEWS = [['desktop', 1440, 900, 'dark'], ['light', 1440, 900, 'light'], ['tablet', 1024, 768, 'dark'], ['mobile', 390, 844, 'dark']]
const LANGS = [['en', VIEWS], ['zh-Hant', [VIEWS[0]]], ['zh-Hans', [VIEWS[0]]]]

const CHECKS = `((lang) => {
  const vw = window.innerWidth
  const out = { hOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1, scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }
  const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' }
  const desc = (el) => { const id = el.getAttribute('data-testid'); const t = (el.textContent || '').trim().slice(0, 40); return el.tagName.toLowerCase() + (id ? '[' + id + ']' : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ').slice(0, 3).join('.') : '') + (t ? ' "' + t + '"' : '') }
  const inFlow = (el) => !!el.closest('[data-testid="react-flow"], .react-flow')
  out.offscreen = [...document.querySelectorAll('body *')].filter((el) => vis(el) && !inFlow(el)).filter((el) => { const r = el.getBoundingClientRect(); return r.right > vw + 2 && r.left < vw }).slice(0, 8).map(desc)
  out.unnamed = [...document.querySelectorAll('button, a')].filter(vis).filter((el) => !(el.getAttribute('aria-label') || el.getAttribute('title') || (el.textContent || '').trim() || el.querySelector('img[alt]'))).slice(0, 10).map(desc)
  out.smallTargets = vw < 500 ? [...document.querySelectorAll('button, a, input[type=checkbox], select')].filter(vis).filter((el) => { const r = el.getBoundingClientRect(); return (r.height < 28 || r.width < 28) && !inFlow(el) }).slice(0, 12).map((el) => desc(el) + ' ' + Math.round(el.getBoundingClientRect().width) + 'x' + Math.round(el.getBoundingClientRect().height)) : []
  out.truncated = [...document.querySelectorAll('body *')].filter(vis).filter((el) => { const cs = getComputedStyle(el); return cs.overflow === 'hidden' && cs.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 2 && el.children.length === 0 }).slice(0, 12).map((el) => desc(el) + ' [' + el.scrollWidth + '>' + el.clientWidth + ']')
  const fixed = [...document.querySelectorAll('body *')].filter(vis).filter((el) => ['fixed', 'sticky'].includes(getComputedStyle(el).position))
  out.fixedOverlaps = []
  for (let a = 0; a < fixed.length; a++) for (let b = a + 1; b < fixed.length; b++) {
    if (fixed[a].contains(fixed[b]) || fixed[b].contains(fixed[a])) continue
    const ra = fixed[a].getBoundingClientRect(), rb = fixed[b].getBoundingClientRect()
    const ix = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left), iy = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top)
    if (ix > 8 && iy > 8) out.fixedOverlaps.push(desc(fixed[a]) + ' × ' + desc(fixed[b]))
  }
  out.noAlt = [...document.querySelectorAll('img')].filter(vis).filter((el) => !el.hasAttribute('alt')).slice(0, 6).map((el) => (el.getAttribute('src') || '').slice(0, 60))
  out.unlabeled = [...document.querySelectorAll('input:not([type=hidden]):not([type=file]), select, textarea')].filter(vis).filter((el) => !(el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') || (el.id && document.querySelector('label[for="' + el.id + '"]')) || el.closest('label'))).slice(0, 10).map(desc)
  const lum = (c) => { const m = c.match(/[\\d.]+/g); if (!m) return null; const [r, g, b] = m.slice(0, 3).map(Number); const a = m[3] !== undefined ? Number(m[3]) : 1; if (a === 0) return null; const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b) }
  const bgOf = (el) => { let e = el; while (e) { const c = getComputedStyle(e).backgroundColor; const l = lum(c); if (l !== null) return l; e = e.parentElement } return lum(getComputedStyle(document.body).backgroundColor) ?? 1 }
  const lowContrast = []
  const textEls = [...document.querySelectorAll('p, span, td, th, li, label, button, a, h1, h2, h3, small, kbd, div')].filter(vis).filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 1))
  for (const el of textEls.slice(0, 600)) {
    const cs = getComputedStyle(el); const fg = lum(cs.color); if (fg === null) continue
    const bg = bgOf(el); const ratio = (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05)
    const size = parseFloat(cs.fontSize); const min = size >= 18 || (size >= 14 && parseInt(cs.fontWeight) >= 700) ? 3 : 4.5
    if (ratio < min * 0.75 && !inFlow(el)) lowContrast.push(desc(el) + ' ' + ratio.toFixed(2) + ':1 @' + Math.round(size) + 'px')
  }
  out.lowContrast = [...new Set(lowContrast)].slice(0, 12)
  // 語系檢查：抓可見文字（略過 code／pre／react-flow 畫布）
  const text = [...document.querySelectorAll('body *')].filter((el) => vis(el) && !inFlow(el) && !el.closest('code, pre, kbd, textarea')).flatMap((el) => [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent)).join('\\n')
  out.fullwidthPunct = lang === 'en' ? [...new Set((text.match(/[：、；（）～　]/g) || []))] : []
  out.rawI18nKeys = lang !== 'en' ? [...new Set((text.match(/\\b[a-z][a-zA-Z]*(?:\\.[a-zA-Z][a-zA-Z0-9]*){2,}\\b/g) || []).filter((k) => !/\\.(png|jpg|svg|ts|tsx|json|py|html|exe|ps1|md|zip|onnx|pt|npz|csv)$/i.test(k) && !/^(www|api|http)/.test(k)))].slice(0, 8) : []
  return out
})`

const report = []
const me0 = await j('/auth/me')
const origTheme = (me0.ui || {}).theme || 'dark'
const origLang = (me0.ui || {}).language || 'en'
const setPrefs = (body) => fetch(`${API}/auth/prefs`, { method: 'PATCH', headers: { ...H, 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

for (const [lang, views] of LANGS) {
  for (const [view, w, h, theme] of views) {
    await setPrefs({ theme, language: lang })
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, locale: lang === 'en' ? 'en-US' : lang === 'zh-Hant' ? 'zh-TW' : 'zh-CN', isMobile: w < 500, hasTouch: w < 500 })
    await ctx.addInitScript(({ t, th, lg }) => { localStorage.setItem('vs.token', t); localStorage.setItem('vs.theme', th); localStorage.setItem('vs.lang', lg); localStorage.removeItem('vs.assistant.v1') }, { t: token, th: theme, lg: lang })
    const page = await ctx.newPage()
    const consoleMsgs = [], failed = []
    page.on('console', (m) => { if (m.type() === 'error') consoleMsgs.push(`error: ${m.text().slice(0, 160)}`) })
    page.on('pageerror', (e) => consoleMsgs.push(`pageerror: ${e.message.slice(0, 160)}`))
    page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('/auth/status')) failed.push(`${r.status()} ${r.url().replace(FRONT, '').replace('http://127.0.0.1:8000', '').slice(0, 90)}`) })
    for (const [name, route] of PAGES) {
      consoleMsgs.length = 0; failed.length = 0
      const t0 = Date.now()
      try {
        await page.goto(`${FRONT}${route}`, { waitUntil: 'domcontentloaded' })
        await page.waitForFunction(() => !document.querySelector('[data-testid="loading"]') && document.body.innerText.length > 30, null, { timeout: 30000 }).catch(() => {})
        await page.waitForTimeout(['editor', 'tool', 'dashboard-design', 'dashboard-kiosk'].includes(name) ? 2500 : 1200)
      } catch (e) { log('goto failed', name, view, e.message.slice(0, 100)) }
      const loadMs = Date.now() - t0
      const checks = await page.evaluate(`${CHECKS}(${JSON.stringify(lang)})`).catch((e) => ({ error: e.message }))
      let focusVisible = null
      try {
        for (let i = 0; i < 3; i++) await page.keyboard.press('Tab')
        focusVisible = await page.evaluate(() => { const el = document.activeElement; if (!el || el === document.body) return 'none'; const cs = getComputedStyle(el); return (cs.outlineStyle !== 'none' && cs.outlineWidth !== '0px') || cs.boxShadow !== 'none' ? 'ok' : 'missing:' + el.tagName + ' ' + (el.textContent || '').trim().slice(0, 30) })
      } catch { /* ignore */ }
      const shot = path.join(OUT, `${lang}-${view}-${name}.png`)
      await page.screenshot({ path: shot, fullPage: false }).catch(() => {})
      const redirected = page.url().includes('/login') && route !== '/login'
      const entry = { lang, page: name, view, theme, route, loadMs, redirectedToLogin: redirected, console: [...new Set(consoleMsgs)].slice(0, 6), failedRequests: [...new Set(failed)].slice(0, 6), focusVisible, ...checks }
      report.push(entry)
      const flags = ['redirectedToLogin', 'hOverflow', 'offscreen', 'unnamed', 'smallTargets', 'truncated', 'fixedOverlaps', 'noAlt', 'unlabeled', 'lowContrast', 'console', 'failedRequests', 'fullwidthPunct', 'rawI18nKeys'].filter((k) => (Array.isArray(entry[k]) ? entry[k].length : entry[k]))
      log(`${lang.padEnd(7)} ${view.padEnd(8)} ${name.padEnd(18)} ${String(loadMs).padStart(5)}ms focus=${focusVisible} flags=${flags.join(',') || '-'}`)
    }
    await ctx.close()
  }
}
// 登入頁（未登入）
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  const errs = []
  page.on('pageerror', (e) => errs.push(e.message.slice(0, 120)))
  await page.goto(`${FRONT}/login`, { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(1200)
  await page.screenshot({ path: path.join(OUT, 'en-desktop-login.png') })
  report.push({ lang: 'en', page: 'login', view: 'desktop', route: '/login', console: errs, ...(await page.evaluate(`${CHECKS}("en")`)) })
  await ctx.close()
}
await setPrefs({ theme: origTheme, language: origLang })
await browser.close()
fs.writeFileSync(path.join(OUT, 'ui_audit.json'), JSON.stringify(report, null, 2))

// ---- 摘要 ----
const KEYS = ['redirectedToLogin', 'hOverflow', 'offscreen', 'unnamed', 'smallTargets', 'truncated', 'fixedOverlaps', 'noAlt', 'unlabeled', 'lowContrast', 'console', 'failedRequests', 'fullwidthPunct', 'rawI18nKeys']
const flagged = report.filter((e) => KEYS.some((k) => (Array.isArray(e[k]) ? e[k].length : e[k])))
const byKey = Object.fromEntries(KEYS.map((k) => [k, report.filter((e) => (Array.isArray(e[k]) ? e[k].length : e[k])).length]))
log('\n==== 摘要 ====')
log(`頁面載入 ${report.length} 次｜有旗標 ${flagged.length} 次`)
log('各項旗標次數:', JSON.stringify(byKey))
log(`AUDIT-DONE loads=${report.length} flagged=${flagged.length} json=${path.join(OUT, 'ui_audit.json')}`)
