// 統一檢查：依各專案 project.json 的 checks 設定執行，所有專案用同一套流程。
//   node core/tools/check.mjs [專案…] [--quick] [--only 名稱,…]
// --quick：部署前的快速檢查（GitHub Actions 使用）；不加則跑完整檢查。
//
// project.json：
//   "checks": {
//     "quick": ["tools/verify.mjs"],                      // 快速＋完整都跑
//     "full":  ["tools/verify-scene.mjs --dt=0.5", …]     // 只在完整檢查跑
//   }
// core 內建檢查（每個專案都跑）：imports（靜態 import 路徑）。
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { pickProjects, ROOT } from './projects.mjs';
import { runScript } from './run.mjs';
import { checkProject as checkImports } from './check-imports.mjs';

const argv = process.argv.slice(2), quick = argv.includes('--quick');
const only = (() => { const i = argv.indexOf('--only'); return i >= 0 ? argv.splice(i, 2)[1].split(',') : null; })();
const projects = pickProjects(argv.filter(a => !a.startsWith('--')));
const BUILTIN = {
  imports: async p => { const r = checkImports(p); return { ok: !r.missing.length, note: `${r.modules} 個模組`, detail: r.missing }; },
};

const split = cmd => cmd.match(/"[^"]*"|\S+/g).map(s => s.replace(/^"|"$/g, ''));
const results = [];
for (const p of projects) {
  const scripts = [...(p.checks?.quick || []), ...(quick ? [] : p.checks?.full || [])];
  const jobs = [...Object.keys(BUILTIN).map(k => ({ name: k, run: () => BUILTIN[k](p) })),
    ...scripts.map(cmd => ({ name: cmd, run: async () => { const [script, ...args] = split(cmd); const r = await runScript(p, script, args, { echo: false }); return { ok: r.code === 0, note: `exit ${r.code}`, detail: r.code ? r.out.trim().split('\n').slice(-12) : [] }; } }))];
  for (const job of jobs) {
    if (only && !only.some(o => job.name.includes(o))) continue;
    const t0 = Date.now(); let r;
    try { r = await job.run(); } catch (e) { r = { ok: false, note: e.message.split('\n')[0], detail: [String(e.stack || e)] }; }
    const sec = (Date.now() - t0) / 1000;
    results.push({ project: p.id, check: job.name, ok: r.ok, note: r.note, seconds: +sec.toFixed(1) });
    console.log(`${r.ok ? '✓' : '✗'} ${p.id} · ${job.name}  ${r.note || ''}  (${sec.toFixed(1)} s)`);
    if (!r.ok) for (const d of r.detail || []) console.log('     ' + d);
  }
}
const failed = results.filter(r => !r.ok);
mkdirSync(join(ROOT, 'TEMP'), { recursive: true });
writeFileSync(join(ROOT, 'TEMP', quick ? 'check-quick.json' : 'check-full.json'), JSON.stringify({ at: new Date().toISOString(), quick, results }, null, 2));
console.log(`\n${results.length - failed.length}/${results.length} 通過${failed.length ? '；失敗：' + failed.map(f => `${f.project} · ${f.check}`).join('、') : ''}`);
process.exit(failed.length ? 1 : 0);
