import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const b = await chromium.launch(process.env.PW_EXE ? { executablePath: process.env.PW_EXE, headless: true } : { channel: 'chrome', headless: true })
async function ctx(w, h, mobile) {
  const c = await b.newContext({ viewport: { width: w, height: h }, isMobile: mobile, hasTouch: mobile })
  await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token }); return c
}
// 1) pointer: coarse 在稽核用的手機 context 裡到底有沒有生效
{ const c = await ctx(390, 844, true); const p = await c.newPage(); await p.goto('http://127.0.0.1:5173/settings', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(1500)
  const r = await p.evaluate(() => ({ coarse: matchMedia('(pointer: coarse)').matches, anyCoarse: matchMedia('(any-pointer: coarse)').matches, cb: (() => { const e = document.querySelector('input[type=checkbox]'); return e ? Math.round(e.getBoundingClientRect().height) : null })() }))
  console.log('POINTER', JSON.stringify(r), '→', r.coarse ? 'coarse 有生效，smallTargets 是真的' : 'coarse 沒生效：稽核的手機 context 沒觸發放大規則，smallTargets 多為量測假象')
  await c.close() }
// 2) users 頁 390px 不得水平溢出
{ const c = await ctx(390, 844, true); const p = await c.newPage(); await p.goto('http://127.0.0.1:5173/users', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2000)
  const r = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
  console.log('USERS@390', JSON.stringify(r), r.sw <= r.cw + 1 ? '✓ 不再溢出' : '✗ 仍溢出'); await c.close() }
// 3) 標定頁 select 有名字、Modbus 開關有名字
{ const c = await ctx(1440, 900, false); const p = await c.newPage()
  await p.goto('http://127.0.0.1:5173/calibration', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(1800)
  console.log('CALIB select aria-label =', JSON.stringify(await p.getAttribute('[data-testid="calib-source"]', 'aria-label')))
  await p.goto('http://127.0.0.1:5173/integration/modbus-server', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2500)
  const names = await p.$$eval('button[role="switch"]', (els) => els.map((e) => e.getAttribute('aria-label')))
  console.log('MODBUS switches aria-label =', JSON.stringify(names), names.length && names.every(Boolean) ? '✓' : (names.length ? '✗ 有沒名字的' : '（頁上沒有開關，可能沒有連線）'))
  await c.close() }
await b.close()
