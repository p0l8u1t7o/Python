import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const c = await b.newContext({ viewport: { width: 1440, height: 900 } }); await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); const errors = []; p.on('pageerror', (e) => errors.push(String(e))); p.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 120)) })
await p.goto('http://127.0.0.1:5173/calibration', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(1500)
// 切到手眼標定模式（找含 robot 的模式按鈕／選項）
const modeBtn = await p.$('[data-testid="calib-mode-robot"], button:has-text("Robot"), [role="tab"]:has-text("Robot")')
if (modeBtn) await modeBtn.click(); else { const sel = await p.$('select[data-testid="calib-mode"]'); if (sel) await sel.selectOption('robot') }
await p.waitForTimeout(800)
const src = await p.$('[data-testid="calib-robot-coord-source"]')
console.log('coord-source 元件存在：', Boolean(src))
if (src) { const tag = await src.evaluate((e) => e.tagName); if (tag === 'SELECT') await src.selectOption('connection'); else { const opt = await p.$('[data-testid="calib-robot-coord-source"] [value="connection"], [data-testid="calib-robot-coord-source"] button:has-text("onnection")'); if (opt) await opt.click() } }
await p.waitForTimeout(1500)
await p.screenshot({ path: path.join(here, 'out', 'b2_robot_connection.png'), fullPage: false })
const hOver = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
console.log('標定頁 connection 模式：hOverflow=' + hOver + ' errors=' + errors.length)
await p.goto('http://127.0.0.1:5173/integration/tcp', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(1500)
const tab = await p.$('[role="tab"]:has-text("接收規則"), [role="tab"]:has-text("rules"), [role="tab"]:has-text("Rules")'); console.log('rules tab 找到：', Boolean(tab)); if (tab) await tab.click(); await p.waitForTimeout(1000)
const btns = await p.$$eval('button', (els) => els.map((e) => e.textContent.trim()).filter((t) => /規則|rule/i.test(t))); console.log('規則相關按鈕：', JSON.stringify(btns.slice(0, 6)))
const add = await p.$('button:has-text("新增規則"), button:has-text("Add rule"), [data-testid="rule-add"]'); if (add) await add.click(); await p.waitForTimeout(600)
const actionSel = await p.$$('select'); let picked = false
for (const s of actionSel) { const opts = await s.$$eval('option', (o) => o.map((x) => x.value)); if (opts.includes('set_param')) { await s.selectOption('set_param'); picked = true; break } }
await p.waitForTimeout(800); await p.screenshot({ path: path.join(here, 'out', 'b2_rule_set_param.png'), fullPage: false })
console.log('TCP 接收規則 set_param 選項：' + picked + ' errors=' + errors.length); if (errors.length) console.log(errors.slice(0, 4).join('\n'))
await b.close()
