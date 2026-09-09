// 專門驗「從目前影像加入」：進入框選模式 → 在檢視器上拖出區域 → 確認鈕由 disabled 變 enabled → 按下 → 參數真的多一張圖
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const H = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
const api = async (m, p, b) => {
  const r = await fetch('http://127.0.0.1:8000/api' + p, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined })
  const t = await r.text(); try { return { s: r.status, j: JSON.parse(t || '{}') } } catch { return { s: r.status, j: t.slice(0, 160) } }
}
const form = new FormData()
form.append('files', new Blob([fs.readFileSync(path.join(here, 'part.png'))], { type: 'image/png' }), 'part.png')
const up = await (await fetch('http://127.0.0.1:8000/api/vision/fixed-images', { method: 'POST', headers: { Authorization: 'Bearer ' + token }, body: form })).json()
const desc = Array.isArray(up.items) ? up.items[0] : up
const flow = await api('POST', '/vision/flows', { name: 'b3-add-probe', graph: { nodes: [
  { id: 'src', type: 'fixed_image', label: 'Pictures', enabled: true, params: { images: [desc], mode: 'fixed', index: 1, role: 'acquire' }, position: { x: 0, y: 0 } },
  { id: 'reg', type: 'register_detect', label: 'Register', enabled: true, params: {}, position: { x: 360, y: 0 } },
], edges: [{ id: 'e1', source: 'src', source_handle: 'image', target: 'reg', target_handle: 'image' }] } })
const fid = flow.j.id
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const c = await b.newContext({ viewport: { width: 1440, height: 900 } })
await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0, 140)))
await p.goto(`http://127.0.0.1:5173/flows/${fid}/tools/reg`, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2000)
const run = await p.$('button:has-text("試執行")'); if (run) { await run.click(); await p.waitForTimeout(3000) }

const addBtns = await p.$$('button:has-text("從目前影像加入")')
console.log('進入前的「加入」鈕數：', addBtns.length)
await addBtns[0].click(); await p.waitForTimeout(800)
// 檢視器的畫布：取最大的那一個（避免縮圖／小地圖）
const boxes = await p.$$eval('canvas', (els) => els.map((e, i) => { const r = e.getBoundingClientRect(); return { i, x: r.x, y: r.y, w: r.width, h: r.height } }))
const big = boxes.sort((a, b2) => b2.w * b2.h - a.w * a.h)[0]
console.log('畫布：', JSON.stringify(big))
await p.mouse.move(big.x + big.w * 0.30, big.y + big.h * 0.30)
await p.mouse.down()
for (let k = 1; k <= 12; k++) await p.mouse.move(big.x + big.w * (0.30 + 0.03 * k), big.y + big.h * (0.30 + 0.025 * k))
await p.mouse.up(); await p.waitForTimeout(900)
const states = await p.$$eval('button', (els) => els.filter((e) => /從目前影像加入/.test(e.textContent || '') && e.offsetParent !== null).map((e) => e.disabled))
console.log('拖曳後三個「加入」鈕的 disabled：', JSON.stringify(states), states.some((d) => d === false) ? '→ 有可按的確認鈕' : '→ 確認鈕仍不可按')
const confirm = (await p.$$('button:has-text("從目前影像加入")')).slice(-1)[0]
if (confirm && !(await confirm.isDisabled())) {
  await confirm.click(); await p.waitForTimeout(2000)
  const save = await p.$('button:has-text("儲存")'); if (save) { await save.click(); await p.waitForTimeout(2000) }
  const after = await api('GET', `/vision/flows/${fid}`)
  const regs = (after.j.graph.nodes.find((n) => n.id === 'reg').params || {}).registrations || []
  console.log('結果：registrations =', regs.length, regs[0] ? `${regs[0].width}x${regs[0].height}（原圖 320x240）` : '')
} else console.log('確認鈕仍不可按，沒有按下去')
await p.screenshot({ path: path.join(here, 'out', 'b3_add_region.png') })
console.log('PAGE-ERRORS', errs.length)
await b.close(); await api('DELETE', `/vision/flows/${fid}`)
