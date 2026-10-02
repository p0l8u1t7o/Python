// 以 Chrome DevTools Protocol 實際開啟網頁：收集主控台錯誤、跳到各站截圖、檢查相機子畫面與面板。
// 不需 npm 套件（Node 22+ 內建 WebSocket）。先執行 python serve.py --no-open。
//   node tools/browser-check.mjs [--url http://127.0.0.1:8775/] [--out review/screens]
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';

const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const URL0 = arg('--url', 'http://127.0.0.1:8775/'), OUT = resolve(arg('--out', 'review/screens'));
const CHROME = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
mkdirSync(OUT, { recursive: true });
const profile = join(tmpdir(), 'ctw-cdp-' + process.pid), port = 9300 + (process.pid % 500);
const proc = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--window-size=1680,1000', '--hide-scrollbars', '--use-angle=d3d11', '--enable-unsafe-swiftshader', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let target;
for (let i = 0; i < 50 && !target; i++) { await sleep(200); try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === 'page'); } catch { } }
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
const evaluate = async expr => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description); return r.result?.result?.value; };
await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1680, height: 1000, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: URL0 + '?pause' });
for (let i = 0; i < 60; i++) { await sleep(250); if (await evaluate('!!window.sim').catch(() => false)) break; }
const ready = await evaluate('!!window.sim');
const shot = async name => { await sleep(700); const r = await send('Page.captureScreenshot', { format: 'jpeg', quality: 82 }); writeFileSync(join(OUT, name + '.jpg'), Buffer.from(r.result.data, 'base64')); return name; };
const report = { url: URL0, ready, shots: [], checks: {} };
if (ready) {
  report.total = await evaluate('window.sim.total');
  // 以事件名稱定位時刻，流程時間調整後截圖仍對準同一個動作
  const at = (label, off = 0) => evaluate(`(window.sim.seq.events.find(e => e.label.includes(${JSON.stringify(label)}))?.time ?? 0) + ${off}`);
  const scenes = [
    ['01-overview', 0, 'iso'], ['02-plan-dims', 0, 'top', 'dims'], ['03-agv-rack', await at('抬起棧板', .5), 'storage'],
    ['04-gantry-tilt', await at('CTW-2610-0001 翻轉放倒', 1.5), 'gantry'], ['05-label-read', await at('CTW-2610-0001 讀碼', .4), 'label'],
    ['06-upender', await at('CTW-2610-0001 翻正', 2), 'upender'], ['07-decap', await at('拆 2" 桶蓋', 1.2), 'decap'],
    ['08-robot-pick', await at('手臂開始取桶', 3), 'robot'], ['09-booth-spray', await at('沖洗水由 TK-R 供應', 5), 'booth'],
    ['10-booth-pour', await at('倒液進集液漏斗', 2), 'booth'], ['11-hot-air-dry', await at('熱風吹乾內壁附著水', 8), 'booth'],
    ['12-waste', await at('末道沖洗水回收至 TK-R', 1), 'waste'], ['13-inbound-dolly', await at('散桶入庫：台車推入', 3), 'inbound'],
    ['14-inbound-jib', await at('懸臂吊上棧板', 2), 'inbound'], ['15-agv-inbound-arc', await at('AGV 取滿棧板入架', 6), 'inbound'],
    ['16-weigh', await at('秤重確認殘水 < 100 g', 1), 'robot'], ['17-finish', report.total - 1, 'iso'],
  ];
  for (const [name, t, view, flag] of scenes) {
    if (flag === 'dims') await evaluate(`document.getElementById('showDims').click()`);
    await evaluate(`window.sim.seekTo(${t}); window.sim.setView('${view}', true)`);
    report.shots.push(await shot(name));
    if (flag === 'dims') await evaluate(`document.getElementById('showDims').click()`);
  }
  // 面板與狀態健全性：每 2 秒取樣，NaN 或手臂追蹤誤差過大即記錄
  report.checks.samples = await evaluate(`(() => { const bad = []; for (let t = 0; t <= window.sim.total; t += 2) { window.sim.seekTo(t); const s = window.sim.state; const e = s.robot.err; if (e && (e.position > 2 || e.angle > .5)) bad.push({ t, e }); const j = JSON.stringify(s.st); if (/:null/.test(j)) bad.push({ t, nan: true }); } return bad; })()`);
  report.checks.pipShown = await evaluate(`(window.sim.seekTo(${await at('CTW-2610-0001 讀碼', .4)}), new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(!document.getElementById('pip').hidden)))))`);
  report.checks.layoutChecks = await evaluate(`document.getElementById('chkCount').textContent`);
  report.checks.equipRows = await evaluate(`document.querySelectorAll('#equip .row').length`);
}
report.errors = errors; report.logs = logs.slice(0, 20);
writeFileSync(join(OUT, 'browser-check.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
ws.close(); proc.kill(); await sleep(300); try { rmSync(profile, { recursive: true, force: true }); } catch { }
process.exit(errors.length || !ready ? 1 : 0);
