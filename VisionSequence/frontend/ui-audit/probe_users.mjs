import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const b = await chromium.launch(process.env.PW_EXE ? { executablePath: process.env.PW_EXE, headless: true } : { channel: 'chrome', headless: true })
const c = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); await p.goto('http://127.0.0.1:5173/users', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2500)
const r = await p.evaluate(() => {
  const W = document.documentElement.clientWidth; const out = []
  for (const el of document.querySelectorAll('body *')) {
    const rc = el.getBoundingClientRect(); if (rc.width === 0) continue
    if (rc.right > W + 1) {
      const cs = getComputedStyle(el)
      out.push({ tag: el.tagName.toLowerCase(), cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 80) : '', tid: el.getAttribute('data-testid') || '', right: Math.round(rc.right), w: Math.round(rc.width), sw: el.scrollWidth, ox: cs.overflowX, depth: (() => { let d = 0, n = el; while (n.parentElement) { d++; n = n.parentElement } return d })() })
    }
  }
  return { W, sw: document.documentElement.scrollWidth, out: out.sort((a, b) => b.depth - a.depth).slice(0, 14) }
})
console.log('W', r.W, 'scrollWidth', r.sw); for (const o of r.out) console.log(JSON.stringify(o))
await b.close()
