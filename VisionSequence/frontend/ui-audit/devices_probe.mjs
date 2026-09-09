// 設備連線頁：真瀏覽器建一條 loop:// 序列埠連線，確認頁面、欄位與狀態都對。
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const H = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
const api = async (m, p, b) => {
  const r = await fetch('http://127.0.0.1:8000/api' + p, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined })
  const t = await r.text(); try { return { s: r.status, j: JSON.parse(t || '{}') } } catch { return { s: r.status, j: t.slice(0, 200) } }
}
// 連線種類目錄要看得到三種、且都歸 devices 頁
const kinds = await api('GET', '/vision/connections/kinds')
const list = Array.isArray(kinds.j) ? kinds.j : (kinds.j.items || [])
const mine = list.filter((k) => ['serial', 'udp', 'tcp_server_text'].includes(k.kind))
console.log('連線種類目錄：', JSON.stringify(mine.map((k) => `${k.kind}@${k.section}`)))

// 建一條 loop:// 的序列埠連線（無硬體）
const made = await api('POST', '/vision/connections', { name: 'probe-serial', kind: 'serial', is_enabled: true, config: { port: 'loop://', baudrate: 9600, end_char: '\n', encoding: 'utf-8', timeout_s: 1 } })
console.log('建立 loop:// 序列埠連線：', made.s, made.j.id ? 'OK' : JSON.stringify(made.j).slice(0, 200))

const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const c = await b.newContext({ viewport: { width: 1440, height: 900 } })
await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); const errs = []
p.on('pageerror', (e) => errs.push(String(e).slice(0, 140)))
p.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 120)) })
await p.goto('http://127.0.0.1:5173/integration/devices', { waitUntil: 'domcontentloaded' })
await p.waitForTimeout(2500)
const heading = await p.$eval('h1', (e) => e.textContent.trim()).catch(() => '(找不到標題)')
const bodyText = await p.$eval('body', (e) => e.innerText)
console.log('頁面標題：', heading)
console.log('看得到剛建的連線：', bodyText.includes('probe-serial'))
console.log('看得到 loop:// 設定：', bodyText.includes('loop://'))
console.log('側欄有設備連線項目：', await p.$$eval('nav a, aside a', (els) => els.some((e) => /設備連線|Device connections/i.test(e.textContent || ''))))
const hOver = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
console.log('水平溢出：', hOver, ' page errors：', errs.length, errs.slice(0, 2).join(' // '))
await p.screenshot({ path: path.join(here, 'out', 'devices_page.png') })
await b.close()
if (made.j.id) await api('DELETE', `/vision/connections/${made.j.id}`)
console.log('探針連線已刪除')
