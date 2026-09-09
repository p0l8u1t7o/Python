import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const api = async (p) => (await fetch('http://127.0.0.1:8000/api' + p, { headers: { Authorization: 'Bearer ' + token } })).json()
const flows = await api('/vision/flows'); const flow = (flows.items || flows).find((f) => (f.graph?.nodes || []).length >= 2) || (flows.items || flows)[0]
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const c = await b.newContext({ viewport: { width: 1440, height: 900 } }); await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); const errors = []; p.on('pageerror', (e) => errors.push(String(e)))
await p.goto(`http://127.0.0.1:5173/flows/${flow.id}`, { waitUntil: 'domcontentloaded' }); await p.waitForSelector('.react-flow__node', { timeout: 20000 }); await p.waitForTimeout(1500)
const before = await p.$$eval('.react-flow__edge', (e) => e.length)
// 找一個「來源把手」與另一個節點的「目標把手」；放開的位置故意離目標把手 55px
const src = await p.$('.react-flow__handle.source'); const tgts = await p.$$('.react-flow__handle.target')
const sb = await src.boundingBox(); let tb = null
for (const t of tgts) { const bb = await t.boundingBox(); if (bb && Math.abs(bb.x - sb.x) > 40) { tb = bb; break } }
if (!sb || !tb) { console.log('SNAP 找不到把手'); await b.close(); process.exit(0) }
await p.mouse.move(sb.x + sb.width / 2, sb.y + sb.height / 2); await p.mouse.down()
await p.mouse.move(tb.x + 300, tb.y + 200, { steps: 8 })
await p.mouse.move(tb.x + tb.width / 2 + 55, tb.y + tb.height / 2, { steps: 8 })  // 距目標把手 55px（< 80）
await p.waitForTimeout(150); await p.mouse.up(); await p.waitForTimeout(500)
const after = await p.$$eval('.react-flow__edge', (e) => e.length)
console.log(`SNAP flow=${flow.id} edges ${before} → ${after} ${after > before ? '✓ 55px 外放開仍接上' : '✗ 沒接上（可能是型別不相容或把手找錯）'} pageErrors=${errors.length}`)
await b.close()
