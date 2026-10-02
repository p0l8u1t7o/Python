// 各專案各視角截圖，並可與先前一組截圖逐張比對（遷移與優化的回歸檢查）。
//   node core/tools/shots.mjs [專案…] --out <資料夾> [--compare <基準資料夾>] [--tol 24] [--max 0.002]
// 截圖時間取時間軸總長的固定比例，同一專案每次取同樣的視角與時間。
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pickProjects } from './projects.mjs';
import { startServer } from './serve.mjs';
import { openBrowser, sleep } from './cdp.mjs';
import { decodePng, encodePng, diffPng } from './png.mjs';

const argv = process.argv.slice(2), opt = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv.splice(i, 2)[1] : d; };
const OUT = resolve(opt('--out', 'TEMP/shots')), BASE = opt('--compare', null), TOL = +opt('--tol', 24), MAX = +opt('--max', .002);
const PORT = +opt('--port', 8790);
const projects = pickProjects(argv.filter(a => !a.startsWith('--')));
const FRACS = [.12, .31, .5, .69, .88];

// 從 main.js 讀出視角名稱（const views／VIEWS 物件第一層的鍵）
export function viewNames(src) {
  const m = /const\s+(?:views|VIEWS)\s*=\s*\{/.exec(src); if (!m) return ['iso'];
  // 第一層：鍵出現在開頭或逗號之後，緊接冒號
  const names = []; let depth = 1, expectKey = true, tok = '';
  for (let i = m.index + m[0].length; i < src.length && depth > 0; i++) {
    const c = src[i];
    if ('{[('.includes(c)) { depth++; expectKey = false; tok = ''; continue; }
    if ('}])'.includes(c)) { depth--; continue; }
    if (depth !== 1) continue;
    if (c === ',') { expectKey = true; tok = ''; }
    else if (expectKey && /[\w$]/.test(c)) tok += c;
    else if (expectKey && c === ':' && tok) { names.push(tok); expectKey = false; tok = ''; }
    else if (!/\s/.test(c)) { expectKey = false; tok = ''; }
  }
  return [...new Set(names)];
}

const server = await startServer({ port: PORT, quiet: true });
const browser = await openBrowser();
const report = {};
for (const p of projects) {
  const dir = join(OUT, p.id); mkdirSync(dir, { recursive: true });
  const skip = p.shots?.skip || ['follow'];
  const views = (p.shots?.views || viewNames(readFileSync(join(p.web, 'js', 'main.js'), 'utf8'))).filter(v => !skip.includes(v));
  const ok = await browser.goto(`http://127.0.0.1:${PORT}/${encodeURIComponent(p.id)}/?pause`);
  const r = report[p.id] = { ready: ok, views, shots: [], errors: [] };
  if (!ok) { r.errors.push('window.sim 未就緒'); continue; }
  await sleep(1500);
  const total = await browser.evaluate(`+(document.getElementById('timeline')?.max || window.sim.total || 0)`);
  r.total = total;
  const list = [['iso', 0], ...views.map((v, k) => [v, +(total * FRACS[k % FRACS.length]).toFixed(2)]), ['iso', +(total * .97).toFixed(2)]];
  for (const [v, t] of list) {
    await browser.evaluate(`(() => { const s = window.sim; if (s.setView) { s.seekTo(${t}); s.setView(${JSON.stringify(v)}, true); } else if (s.jump) s.jump(0, ${JSON.stringify(v)}, ${t}); else s.seekTo(${t}); return true; })()`).catch(e => r.errors.push(`${v}@${t}: ${e.message.split('\n')[0]}`));
    await browser.frames(); await sleep(400); await browser.frames();
    const name = `${v}@${t}`.replace(/[^\w@.-]/g, '_'), png = await browser.screenshot('png');
    writeFileSync(join(dir, name + '.png'), png);
    const shot = { name };
    if (BASE) {
      const prev = join(resolve(BASE), p.id, name + '.png');
      if (!existsSync(prev)) shot.diff = 'missing-baseline';
      else { const d = diffPng(decodePng(readFileSync(prev)), decodePng(png), TOL); shot.diff = +d.ratio.toFixed(5); if (d.ratio > MAX && d.image) writeFileSync(join(dir, name + '.diff.png'), encodePng(d.image)); }
    }
    r.shots.push(shot);
  }
  r.errors.push(...browser.errors.splice(0));
  const bad = r.shots.filter(s => typeof s.diff === 'number' ? s.diff > MAX : s.diff);
  console.log(`${p.id}: ${r.shots.length} 張${BASE ? `，超過門檻 ${bad.length} 張` : ''}${r.errors.length ? `，錯誤 ${r.errors.length}` : ''}`);
  for (const s of bad) console.log(`   ${s.name}  差異 ${s.diff}`);
  for (const e of r.errors) console.log(`   ✗ ${e.slice(0, 200)}`);
}
writeFileSync(join(OUT, 'shots.json'), JSON.stringify(report, null, 2));
await browser.close(); server.close();
const failed = Object.values(report).some(r => r.errors.length || r.shots.some(s => typeof s.diff === 'number' ? s.diff > MAX : s.diff));
process.exit(failed ? 1 : 0);
