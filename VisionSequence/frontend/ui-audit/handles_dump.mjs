import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url'; import { chromium } from 'playwright'
const here = path.dirname(fileURLToPath(import.meta.url)); const token = fs.readFileSync(path.join(here, 'token.txt'), 'utf8').trim()
const H = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
const graph = { nodes: [ { id: 'src', type: 'image_source', label: 'Acquire', enabled: true, params: { mode: 'input' }, position: { x: 0, y: 0 } }, { id: 'blur', type: 'blur', label: 'Blur', enabled: true, params: {}, position: { x: 420, y: 0 } } ], edges: [] }
const created = await (await fetch('http://127.0.0.1:8000/api/vision/flows', { method: 'POST', headers: H, body: JSON.stringify({ name: 'snap-probe', graph }) })).json(); console.log('CREATE', JSON.stringify(created).slice(0, 160))
const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const c = await b.newContext({ viewport: { width: 1440, height: 900 } }); await c.addInitScript(({ t }) => localStorage.setItem('vs.token', t), { t: token })
const p = await c.newPage(); await p.goto(`http://127.0.0.1:5173/flows/${created.id}`, { waitUntil: 'domcontentloaded' }); await p.waitForSelector('.react-flow__node', { timeout: 20000 }); await p.waitForTimeout(1200)
const hs = await p.$$eval('.react-flow__handle', (els) => els.map((e) => `${e.getAttribute('data-nodeid')} ${e.classList.contains('source') ? 'source' : 'target'} id=${e.getAttribute('data-handleid')} class=${[...e.classList].filter((c) => !c.startsWith('react-flow')).join('.')}`))
console.log(hs.join('\n')); await b.close(); await fetch(`http://127.0.0.1:8000/api/vision/flows/${created.id}`, { method: 'DELETE', headers: H })
