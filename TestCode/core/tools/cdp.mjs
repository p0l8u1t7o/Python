// 無頭 Chrome／Edge（DevTools Protocol）：Node 22+ 內建 WebSocket，不需 npm 套件。
import { spawn } from 'node:child_process';
import { existsSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const BROWSERS = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].filter(Boolean);
export const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function openBrowser({ width = 1680, height = 1000 } = {}) {
  const exe = BROWSERS.find(existsSync);
  if (!exe) throw new Error('找不到 Chrome／Edge，可用環境變數 CHROME_PATH 指定');
  const profile = join(tmpdir(), 'core-cdp-' + process.pid + '-' + Date.now()), port = 9300 + Math.floor(Math.random() * 600);
  const proc = spawn(exe, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, `--window-size=${width},${height}`,
    '--hide-scrollbars', '--use-angle=d3d11', '--enable-unsafe-swiftshader', '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  let target;
  for (let i = 0; i < 60 && !target; i++) { await sleep(200); try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === 'page'); } catch { } }
  if (!target) { proc.kill(); throw new Error('Chrome DevTools 未啟動'); }
  const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  let id = 0; const pending = new Map(), errors = [], logs = [];
  ws.onmessage = m => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
    if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    if (msg.method === 'Runtime.consoleAPICalled') { const t = msg.params.args.map(a => a.value ?? a.description).join(' '); (msg.params.type === 'error' ? errors : logs).push(t); }
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') errors.push(msg.params.entry.text + ' ' + (msg.params.entry.url || ''));
  };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const evaluate = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text);
    return r.result?.result?.value;
  };
  await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  return {
    send, evaluate, errors, logs,
    async goto(url, ready = '!!window.sim', timeout = 30000) {
      errors.length = 0; await send('Page.navigate', { url });
      for (let t = 0; t < timeout; t += 250) { await sleep(250); if (await evaluate(ready).catch(() => false)) return true; }
      return false;
    },
    // 等兩個 animation frame，確保畫面已依新狀態重繪
    frames: () => evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))'),
    async screenshot(format = 'png', quality = 85) {
      const r = await send('Page.captureScreenshot', { format, ...(format === 'jpeg' ? { quality } : {}) });
      return Buffer.from(r.result.data, 'base64');
    },
    async close() { try { ws.close(); } catch { } proc.kill(); await sleep(300); try { rmSync(profile, { recursive: true, force: true }); } catch { } },
  };
}
