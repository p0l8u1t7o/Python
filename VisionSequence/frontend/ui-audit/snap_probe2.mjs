import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const H = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
const graph = { nodes: [
  { id: 'src', type: 'image_source', label: 'Acquire', enabled: true, params: { mode: 'input' }, position: { x: 0, y: 0 } },
  { id: 'blur', type: 'blur', label: 'Blur', enabled: true, params: {}, position: { x: 420, y: 0 } } ], edges: [] }
const created = await (await fetch('http://127.0.0.1:8000/api/vision/flows', { method: 'POST', headers: H, body: JSON.stringify({ name: 'snap-probe', graph }) })).json()
const id = created.id; if (!id) { console.log('SNAP 建流程失敗', JSON.stringify(created).slice(0, 200)); process.exit(0) }
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const c = await b.newContext({ viewport: { width: 1440, height: 900 } }); await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); const errors = []; p.on('pageerror', (e) => errors.push(String(e)))
async function attempt(distance) {
  await p.goto(`http://127.0.0.1:5173/flows/${id}`, { waitUntil: 'domcontentloaded' }); await p.waitForSelector('.react-flow__node', { timeout: 20000 }); await p.waitForTimeout(1200)
  const src = await p.$('.react-flow__handle.source[data-nodeid="src"][data-handleid="image"]')
  const tgt = await p.$('.react-flow__handle.target[data-nodeid="blur"][data-handleid="image"]')
  const sb = await src.boundingBox(), tb = await tgt.boundingBox()
  await p.mouse.move(sb.x + sb.width / 2, sb.y + sb.height / 2); await p.mouse.down()
  await p.mouse.move(sb.x + 150, sb.y + 120, { steps: 6 })
  await p.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2 + distance, { steps: 8 })  // 正下方 distance px
  await p.waitForTimeout(150); await p.mouse.up(); await p.waitForTimeout(400)
  return await p.$$eval('.react-flow__edge', (e) => e.length)
}
const near = await attempt(55); const far = await attempt(140)
console.log(`SNAP 55px→edges=${near} ${near === 1 ? '✓ 接上' : '✗'}；140px→edges=${far} ${far === 0 ? '✓ 沒接（半徑之外）' : '✗'}；pageErrors=${errors.length}`)
await b.close(); await fetch(`http://127.0.0.1:8000/api/vision/flows/${id}`, { method: 'DELETE', headers: H })
