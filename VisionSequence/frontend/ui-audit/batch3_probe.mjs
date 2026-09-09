import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const H = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
const api = async (m, p, b) => {
  const r = await fetch('http://127.0.0.1:8000/api' + p, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined })
  const t = await r.text(); try { return { s: r.status, j: JSON.parse(t || '{}') } } catch { return { s: r.status, j: t.slice(0, 200) } }
}
const made = []
// 一條含 register_detect（kind=images 參數）與 edge_model_defect（model 參數）的流程
const graph = { nodes: [
  { id: 'src', type: 'image_source', label: 'Acquire', enabled: true, params: { mode: 'input' }, position: { x: 0, y: 0 } },
  { id: 'reg', type: 'register_detect', label: 'Register', enabled: true, params: {}, position: { x: 360, y: -120 } },
  { id: 'emd', type: 'edge_model_defect', label: 'Contour', enabled: true, params: {}, position: { x: 360, y: 120 } },
], edges: [
  { id: 'e1', source: 'src', source_handle: 'image', target: 'reg', target_handle: 'image' },
  { id: 'e2', source: 'src', source_handle: 'image', target: 'emd', target_handle: 'image' },
] }
const flow = await api('POST', '/vision/flows', { name: 'b3-probe', graph })
if (!flow.j.id) { console.log('建流程失敗', flow.s, JSON.stringify(flow.j).slice(0, 200)); process.exit(1) }
made.push(['flow', flow.j.id])
// 子 dashboard 與含 child widget 的父 dashboard
const childDash = await api('POST', '/vision/dashboards', { name: 'b3-child', layout: {
  rows: 1, cols: 1, cells: [{ id: 'c_1_1', row: 1, col: 1 }],
  widgets: [{ id: 'w', type: 'clock', cell: 'c_1_1', props: {} }] } })
made.push(['dashboard', childDash.j.id])
const parentDash = await api('POST', '/vision/dashboards', { name: 'b3-parent', layout: {
  rows: 1, cols: 2, cells: [{ id: 'c_1_1', row: 1, col: 1 }, { id: 'c_1_2', row: 1, col: 2 }],
  widgets: [
    { id: 'w1', type: 'child', cell: 'c_1_1', props: { dashboard_id: childDash.j.id, title: 'Line 2' } },
    { id: 'w2', type: 'child', cell: 'c_1_2', props: { dashboard_id: 999999, title: 'Missing' } },
  ] } })
console.log('父 dashboard 建立：', parentDash.s, parentDash.s === 201 || parentDash.s === 200 ? 'OK' : JSON.stringify(parentDash.j).slice(0, 200))
made.push(['dashboard', parentDash.j.id])

const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const c = await b.newContext({ viewport: { width: 1440, height: 900 } })
await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); const errs = []
p.on('pageerror', (e) => errs.push('pageerror: ' + String(e).slice(0, 140)))
p.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 140)) })

// 1) 工具頁：register_detect 的 images 參數要有「從目前影像加入」
await p.goto(`http://127.0.0.1:5173/flows/${flow.j.id}/tools/reg`, { waitUntil: 'domcontentloaded' })
await p.waitForTimeout(2500)
const addBtns = await p.$$eval('button', (els) => els.filter((e) => /add from current|從目前影像|加入/i.test(e.textContent || '')).map((e) => `${e.textContent.trim()}|disabled=${e.disabled}`))
console.log('工具頁 register_detect 的「加入」鈕：', JSON.stringify(addBtns))
await p.screenshot({ path: path.join(here, 'out', 'b3_toolpage_register.png') })

// 2) 工具頁：edge_model_defect 的 model 參數要有「教導輪廓」
await p.goto(`http://127.0.0.1:5173/flows/${flow.j.id}/tools/emd`, { waitUntil: 'domcontentloaded' })
await p.waitForTimeout(2500)
const teachBtns = await p.$$eval('button', (els) => els.filter((e) => /teach|教導/i.test(e.textContent || '')).map((e) => `${e.textContent.trim()}|disabled=${e.disabled}`))
console.log('工具頁 edge_model_defect 的「教導輪廓」鈕：', JSON.stringify(teachBtns))
await p.screenshot({ path: path.join(here, 'out', 'b3_toolpage_contour.png') })

// 3) 運行介面 kiosk：child widget 一個正常、一個指到不存在
await p.goto(`http://127.0.0.1:5173/dashboard/${parentDash.j.id}`, { waitUntil: 'domcontentloaded' })
await p.waitForTimeout(3000)
const kids = await p.$$eval('[data-testid="dash-widget-child"]', (els) => els.map((e) => (e.textContent || '').trim().slice(0, 80)))
console.log('child widget 數量：', kids.length, JSON.stringify(kids))
const hOver = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
console.log('kiosk 水平溢出：', hOver)
await p.screenshot({ path: path.join(here, 'out', 'b3_dashboard_child.png') })
console.log('PAGE-ERRORS', errs.length, errs.slice(0, 3).join(' // '))
await b.close()
for (const [kind, id] of made.reverse()) if (id) await api('DELETE', `/vision/${kind === 'flow' ? 'flows' : 'dashboards'}/${id}`)
console.log('探針建立的資料已清除')
