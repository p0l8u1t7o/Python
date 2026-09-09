import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const b = await chromium.launch(process.env.PW_EXE ? { executablePath: process.env.PW_EXE, headless: true } : { channel: 'chrome', headless: true })
const c = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); await p.goto('http://127.0.0.1:5173/users', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2500)
const r = await p.evaluate(() => {
  const W = document.documentElement.clientWidth
  let el = [...document.querySelectorAll('input[type=checkbox]')].find((e) => e.getBoundingClientRect().right > W + 1)
  const chain = []
  while (el && el !== document.body) {
    const rc = el.getBoundingClientRect(); const cs = getComputedStyle(el)
    chain.push({ tag: el.tagName.toLowerCase(), cls: (typeof el.className === 'string' ? el.className : '').slice(0, 70), tid: el.getAttribute('data-testid') || '', w: Math.round(rc.width), right: Math.round(rc.right), sw: el.scrollWidth, ox: cs.overflowX, disp: cs.display, minw: cs.minWidth })
    el = el.parentElement
  }
  return chain
})
for (const o of r) console.log(JSON.stringify(o))
await b.close()
