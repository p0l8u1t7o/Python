// B4 設備連線頁：真瀏覽器建一條 loop:// 的光源控制器連線，確認預設會把樣板填進表單、存得進去、寫得出去、狀態看得到。
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const H = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
const api = async (m, p, b) => {
  const r = await fetch('http://127.0.0.1:8000/api' + p, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined })
  const t = await r.text(); try { return { s: r.status, j: JSON.parse(t || '{}') } } catch { return { s: r.status, j: t.slice(0, 200) } }
}
let bad = 0
const ok = (label, cond) => { console.log(`  ${cond ? 'OK ' : 'FAIL'} ${label}`); if (!cond) bad += 1 }

const kinds = await api('GET', '/vision/connections/kinds')
const list = Array.isArray(kinds.j) ? kinds.j : (kinds.j.items || [])
const light = list.find((k) => k.kind === 'light')
ok(`連線種類目錄有 light 且歸 devices 頁（${light ? light.section : '無'}）`, light && light.section === 'devices')

// 先清掉上次殘留
const existing = await api('GET', '/vision/connections')
for (const c of (Array.isArray(existing.j) ? existing.j : existing.j.items || [])) if (c.name === 'probe-light') await api('DELETE', `/vision/connections/${c.id}`)

const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const c = await b.newContext({ viewport: { width: 1440, height: 900 } })
await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); const errs = []
p.on('pageerror', (e) => errs.push(String(e).slice(0, 140)))
p.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 120)) })
await p.goto('http://127.0.0.1:5173/integration/devices', { waitUntil: 'domcontentloaded' })
await p.waitForTimeout(2500)

// 建立：選 light、選 preset、看樣板有沒有被填進去
await p.click('[data-testid="conn-create"]')
await p.waitForSelector('[data-testid="conn-name-input"]')
await p.fill('[data-testid="conn-name-input"]', 'probe-light')
await p.selectOption('[data-testid="conn-kind"]', 'light')
await p.waitForTimeout(300)
const dialog = p.locator('[role="dialog"]').last()
const selects = await dialog.locator('select').all()
let presetSel = null
for (const s of selects) { const vals = await s.locator('option').evaluateAll((os) => os.map((o) => o.value)); if (vals.includes('ccs_pd3')) { presetSel = s; break } }
ok('表單有 preset 下拉（含 ccs_pd3）', Boolean(presetSel))
const inputVal = async (name) => {
  // 依 label 文字找 input：label 的文字＝欄位名或翻譯，用 name 的關鍵字比對
  return dialog.locator('label').filter({ hasText: name }).locator('input').first().inputValue().catch(() => null)
}
const before = await dialog.locator('input').evaluateAll((els) => els.map((e) => e.value))
if (presetSel) await presetSel.selectOption('ccs_pd3')
await p.waitForTimeout(300)
const after = await dialog.locator('input').evaluateAll((els) => els.map((e) => e.value))
ok(`選了 ccs_pd3 之後亮度樣板被填成 CCS 格式（${after.find((v) => v.includes('{checksum}')) || '沒找到'}）`, after.some((v) => v === '@{channel0:02d}F{value:03d}{checksum}'))
ok('選預設前的表單並沒有那個樣板（確實是預設填進去的）', !before.some((v) => v.includes('{checksum}')))
// 埠改成 loop://
const portInput = dialog.locator('input').filter({ hasNot: p.locator('nope') })
const portIdx = after.findIndex((v) => v === 'COM3')
ok(`表單有序列埠欄位（預設 COM3，索引 ${portIdx}）`, portIdx >= 0)
if (portIdx >= 0) await dialog.locator('input').nth(portIdx).fill('loop://')
await p.click('[data-testid="conn-save"]')
await p.waitForTimeout(1500)
const bodyText = await p.$eval('body', (e) => e.innerText)
ok('清單看得到 probe-light', bodyText.includes('probe-light'))
const saved = (await api('GET', '/vision/connections')).j
const mine = (Array.isArray(saved) ? saved : saved.items || []).find((x) => x.name === 'probe-light')
ok(`存進去的設定：preset=${mine?.config?.preset} port=${mine?.config?.port} 樣板=${mine?.config?.brightness_template}`,
  mine && mine.config.preset === 'ccs_pd3' && mine.config.port === 'loop://' && mine.config.brightness_template === '@{channel0:02d}F{value:03d}{checksum}')

// 寫入：用清單的寫入鈕送 {"1": 128}
if (mine) {
  const row = p.locator('tr').filter({ hasText: 'probe-light' })
  await row.locator('[data-testid="conn-write"]').click()
  await p.waitForSelector('[data-testid="conn-write-values"]')
  const preset = await p.inputValue('[data-testid="conn-write-values"]')
  ok(`light 的寫入預設值是通道→亮度（${preset}）`, preset.includes('128'))
  await p.click('[data-testid="conn-write-send"]')
  await p.waitForTimeout(1500)
  const result = await p.$eval('[data-testid="connection-result"]', (e) => e.textContent).catch(() => '')
  ok(`寫入結果顯示成功（${result.replace(/\s+/g, ' ').slice(0, 120)}）`, /"ok":\s*true/.test(result))
  await p.keyboard.press('Escape')
  await p.waitForTimeout(300)
  const info = (await api('GET', `/vision/connections/${mine.id}/state`)).j
  console.log('      state 端點：', JSON.stringify(info).slice(0, 300))
  const text = JSON.stringify(info)
  ok('狀態看得到通道亮度與最後命令', /128/.test(text) && /F128|@01/.test(text))
}
const hOver = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
ok(`沒有水平溢出、沒有 page error（${errs.length}）${errs.slice(0, 2).join(' // ')}`, !hOver && errs.length === 0)
await p.screenshot({ path: path.join(here, 'out', 'light_page.png') })
await b.close()
if (mine) await api('DELETE', `/vision/connections/${mine.id}`)
console.log(`PROBE-LIGHT-UI-DONE failures=${bad}`)
