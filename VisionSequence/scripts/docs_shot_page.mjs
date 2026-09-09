// 只重拍使用者手冊的「一張」截圖：docs_shots.mjs 會把全部 27 張重拍一遍，示範資料不齊時會把既有的好圖換成殘缺版；
// 新增或改了單一頁面時用這支，只更新那一張與 docs_shots_callouts.txt 裡對應的那一行。
// 用法：set VS_TOKEN=<管理員 token> && node scripts/docs_shot_page.mjs integration-devices [more-names…]
//   PW_EXE 可指向系統 Chrome。頁面定義表 PAGES 與 docs_shots.mjs 同一套 callout 寫法（target 是 selector、text=… 或 locator 函式）。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '../frontend/node_modules/playwright/index.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const IMG = path.resolve(here, '..', 'docs', 'img')
const CALLOUTS = path.join(here, 'docs_shots_callouts.txt')
const token = process.env.VS_TOKEN || ''
if (!token) { console.error('VS_TOKEN is required'); process.exit(1) }
const names = process.argv.slice(2)
if (!names.length) { console.error('give at least one page name, e.g. integration-devices'); process.exit(1) }
const FRONT = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000/api'
const H = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
const j = async (p, init = {}) => { const r = await fetch(`${API}${p}`, { ...init, headers: { ...H, ...(init.headers || {}) } }); if (r.status === 204) return null; const t = await r.text(); try { return JSON.parse(t) } catch { return t } }

/** 每頁：路由、等待哪個元素、標記清單（順序＝手冊 figcaption 的編號）；setup 建示範資料、teardown 清掉 */
const PAGES = {
  'integration-devices': {
    route: '/integration/devices', ready: '[data-testid="integration-info"]',
    callouts: [{ target: '[data-testid="conn-create"]', label: 'New connection' }, { target: 'main table', label: 'connections' }, { target: '[data-testid="conn-export"]', label: 'Export' }],
    setup: async () => {
      const made = []
      for (const body of [
        { name: 'ring-light', kind: 'light', is_enabled: true, config: { transport: 'serial', port: 'loop://', preset: 'ccs_pd3', channels: 4, value_max: 255, timeout_s: 1 } },
        { name: 'barcode-reader', kind: 'serial', is_enabled: true, config: { port: 'loop://', baudrate: 9600, end_char: '\n', encoding: 'utf-8', timeout_s: 1 } },
      ]) { const r = await j('/vision/connections', { method: 'POST', body: JSON.stringify(body) }); if (r && r.id) made.push(r.id) }
      return made
    },
    teardown: async (made) => { for (const id of made) await j(`/vision/connections/${id}`, { method: 'DELETE' }) },
  },
}

const OVERLAY = (rects) => {
  document.querySelectorAll('.doc-callout').forEach((e) => e.remove())
  for (const r of rects) {
    const box = document.createElement('div'); box.className = 'doc-callout'
    box.style.cssText = 'position:fixed;z-index:99999;pointer-events:none;border:2px solid #00ff88;border-radius:4px;box-shadow:0 0 0 2px rgba(0,0,0,.55),0 0 12px rgba(0,255,136,.55);left:' + (r.x - 3) + 'px;top:' + (r.y - 3) + 'px;width:' + (r.w + 6) + 'px;height:' + (r.h + 6) + 'px'
    const n = document.createElement('div'); n.className = 'doc-callout'; n.textContent = String(r.n)
    n.style.cssText = 'position:fixed;z-index:100000;pointer-events:none;width:26px;height:26px;border-radius:50%;background:#00ff88;color:#0a0a12;font:700 14px/26px ui-monospace,Consolas,monospace;text-align:center;box-shadow:0 0 0 2px #0a0a12;left:' + Math.max(0, r.x - 16) + 'px;top:' + Math.max(0, r.y - 16) + 'px'
    document.body.appendChild(box); document.body.appendChild(n)
  }
}
const CLEAR = () => document.querySelectorAll('.doc-callout').forEach((e) => e.remove())

async function resolve(page, target) {
  const loc = typeof target === 'string' ? (target.startsWith('text=') ? page.getByText(target.slice(5), { exact: false }) : page.locator(target)) : target(page)
  const first = loc.first()
  if (!(await first.count())) return null
  try { await first.scrollIntoViewIfNeeded({ timeout: 1500 }) } catch { /* 固定元素不用捲 */ }
  const b = await first.boundingBox()
  return b && b.width > 0 && b.height > 0 ? b : null
}

function writeCallouts(name, line) {
  const lines = fs.existsSync(CALLOUTS) ? fs.readFileSync(CALLOUTS, 'utf8').split(/\r?\n/).filter((l) => l && !l.startsWith(`${name}:`)) : []
  lines.push(`${name}: ${line}`)
  fs.writeFileSync(CALLOUTS, lines.join('\n') + '\n')
}

const browser = await chromium.launch(process.env.PW_EXE ? { executablePath: process.env.PW_EXE } : {})
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
await ctx.addInitScript(({ t }) => { localStorage.setItem('vs.token', t); localStorage.setItem('vs.language', 'en'); localStorage.removeItem('vs.assistant.v1') }, { t: token })
const page = await ctx.newPage()
// 語言與主題存在帳號偏好，/auth/me 帶回來會蓋掉 localStorage：手冊一律英文，截完還原
const me = await j('/auth/me')
const prevLanguage = me && me.prefs ? me.prefs.language : undefined
await j('/auth/prefs', { method: 'PATCH', body: JSON.stringify({ language: 'en' }) })
let failures = 0
try {
for (const name of names) {
  const spec = PAGES[name]
  if (!spec) { console.error('unknown page', name, '— add it to PAGES'); failures += 1; continue }
  const made = spec.setup ? await spec.setup() : null
  try {
  await page.goto(`${FRONT}${spec.route}`)
  await page.waitForSelector(spec.ready, { timeout: 30000 })
  await page.waitForTimeout(1400)
  const rects = []
  const resolved = []
  for (const c of spec.callouts) {
    const b = await resolve(page, c.target)
    if (!b) { console.log('missing', name, c.label); continue }
    const n = rects.length + 1
    rects.push({ n, x: Math.max(0, b.x), y: Math.max(0, b.y), w: Math.min(b.width, 1440 - b.x), h: Math.min(b.height, 900 - b.y) })
    resolved.push(`${n}=${c.label}`)
  }
  await page.evaluate(OVERLAY, rects)
  await page.waitForTimeout(150)
  await page.screenshot({ path: path.join(IMG, `${name}.jpg`), type: 'jpeg', quality: 82 })
  await page.evaluate(CLEAR)
  writeCallouts(name, resolved.join(' | '))
  console.log('shot', name, `${rects.length}/${spec.callouts.length}`)
  } finally { if (spec.teardown) await spec.teardown(made) }
}
} finally {
  if (prevLanguage) await j('/auth/prefs', { method: 'PATCH', body: JSON.stringify({ language: prevLanguage }) })
  await browser.close()
}
process.exit(failures ? 1 : 0)
