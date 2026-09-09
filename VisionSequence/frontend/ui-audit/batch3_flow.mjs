// 完整走一遍：有影像的工具頁 → 「從目前影像加入」框區域存進參數；「教導輪廓」寫進 model 參數。
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const H = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
const api = async (m, p, b) => {
  const r = await fetch('http://127.0.0.1:8000/api' + p, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined })
  const t = await r.text(); try { return { s: r.status, j: JSON.parse(t || '{}') } } catch { return { s: r.status, j: t.slice(0, 160) } }
}
// 先用 API 造一張固定影像（亮零件，教導輪廓用得到）
const png = fs.readFileSync(path.join(here, 'part.png'))
const form = new FormData()
form.append('files', new Blob([png], { type: 'image/png' }), 'part.png')
const upRes = await fetch('http://127.0.0.1:8000/api/vision/fixed-images', { method: 'POST', headers: { Authorization: 'Bearer ' + token }, body: form })
const up = await upRes.json()
const desc = Array.isArray(up.items) ? up.items[0] : (Array.isArray(up) ? up[0] : up)
console.log('固定影像：', upRes.status, desc && desc.id ? `${desc.width}x${desc.height}` : JSON.stringify(up).slice(0, 160))

const graph = { nodes: [
  { id: 'src', type: 'fixed_image', label: 'Pictures', enabled: true, params: { images: [desc], mode: 'fixed', index: 1, role: 'acquire' }, position: { x: 0, y: 0 } },
  { id: 'reg', type: 'register_detect', label: 'Register', enabled: true, params: {}, position: { x: 360, y: -120 } },
  { id: 'emd', type: 'edge_model_defect', label: 'Contour', enabled: true, params: {}, position: { x: 360, y: 120 } },
], edges: [
  { id: 'e1', source: 'src', source_handle: 'image', target: 'reg', target_handle: 'image' },
  { id: 'e2', source: 'src', source_handle: 'image', target: 'emd', target_handle: 'image' },
] }
const flow = await api('POST', '/vision/flows', { name: 'b3-flow-probe', graph })
const fid = flow.j.id; console.log('流程：', flow.s, fid)

const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const c = await b.newContext({ viewport: { width: 1440, height: 900 } })
await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); const errs = []
p.on('pageerror', (e) => errs.push('pageerror: ' + String(e).slice(0, 140)))

async function runPreview() {
  const btn = await p.$('button:has-text("試執行"), button:has-text("Run")')
  if (btn) { await btn.click(); await p.waitForTimeout(2500) }
  return Boolean(btn)
}

// --- A) register_detect：從目前影像加入 ---
await p.goto(`http://127.0.0.1:5173/flows/${fid}/tools/reg`, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2000)
console.log('A 試執行鈕：', await runPreview())
let addBtn = await p.$('button:has-text("從目前影像加入")')
console.log('A 加入鈕 disabled =', addBtn ? await addBtn.isDisabled() : 'not found')
if (addBtn && !(await addBtn.isDisabled())) {
  await addBtn.click(); await p.waitForTimeout(600)
  const canvas = await p.$('canvas')
  const bb = await canvas.boundingBox()
  await p.mouse.move(bb.x + bb.width * 0.35, bb.y + bb.height * 0.35); await p.mouse.down()
  await p.mouse.move(bb.x + bb.width * 0.6, bb.y + bb.height * 0.6, { steps: 10 }); await p.mouse.up()
  await p.waitForTimeout(500)
  const visible = await p.$$eval('button', (els) => els.filter((e) => e.offsetParent !== null).map((e) => e.textContent.trim()).filter(Boolean).slice(0, 24))
  console.log('A 畫完區域後畫面上的按鈕：', JSON.stringify(visible))
  const confirm = await p.$('button[data-testid="images-add-confirm"], button:has-text("確定"), button:has-text("Add")')
  if (confirm) { await confirm.click(); await p.waitForTimeout(1800) }
  const save = await p.$('button:has-text("儲存")'); if (save) { await save.click(); await p.waitForTimeout(1800) }
  const after = await api('GET', `/vision/flows/${fid}`)
  const regs = (after.j.graph.nodes.find((n) => n.id === 'reg').params || {}).registrations || []
  console.log('A 結果：registrations 筆數 =', regs.length, regs[0] ? `${regs[0].width}x${regs[0].height}` : '')
}
await p.screenshot({ path: path.join(here, 'out', 'b3_flow_register.png') })

// --- B) edge_model_defect：從目前影像教導輪廓 ---
await p.goto(`http://127.0.0.1:5173/flows/${fid}/tools/emd`, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(2000)
console.log('B 試執行鈕：', await runPreview())
const teach = await p.$('button:has-text("從目前影像教導輪廓")')
console.log('B 教導鈕 disabled =', teach ? await teach.isDisabled() : 'not found')
if (teach && !(await teach.isDisabled())) {
  await teach.click(); await p.waitForTimeout(2500)
  const save2 = await p.$('button:has-text("儲存")'); if (save2) { await save2.click(); await p.waitForTimeout(1800) }
  const after = await api('GET', `/vision/flows/${fid}`)
  const model = (after.j.graph.nodes.find((n) => n.id === 'emd').params || {}).model
  console.log('B 結果：model 點數 =', model && model.points ? model.points.length : 'none', 'image_size =', model ? JSON.stringify(model.image_size) : '')
}
await p.screenshot({ path: path.join(here, 'out', 'b3_flow_contour.png') })
console.log('PAGE-ERRORS', errs.length, errs.slice(0, 2).join(' // '))
await b.close()
await api('DELETE', `/vision/flows/${fid}`)
console.log('探針流程已刪除（固定影像留著當孤兒，之後 retention 會清）')
