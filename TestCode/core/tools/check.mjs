// 統一檢查：依各專案 project.json 的 checks 設定執行，所有專案用同一套流程。
//   node core/tools/check.mjs [專案…] [--quick] [--only 名稱,…]
// --quick：部署前的快速檢查（GitHub Actions 使用）；不加則跑完整檢查。
//
// project.json：
//   "checks": {
//     "quick": ["tools/verify.mjs"],                      // 快速＋完整都跑
//     "full":  ["tools/verify-scene.mjs --dt=0.5", …]     // 只在完整檢查跑
//   }
// core 本身：models（core/models 每個模型走完狀態範圍的干涉與重合面，快速）。
// core 內建檢查（每個專案都跑；後三項需要 web/js/project.js）：
//   imports      靜態 import 路徑（快速）
//   determinism  倒序／跳播一致（快速）
//   layout       project.layoutChecks() 空間檢核（快速）
//   scene        全場動態／靜態干涉＋重合面閃爍（完整）
// project.json 的 "core" 可覆寫：{ "skip": ["scene"], "quick": ["scene"] }
import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { pickProjects, ROOT, CORE } from './projects.mjs';
import { runScript } from './run.mjs';
import { checkProject as checkImports } from './check-imports.mjs';

const argv = process.argv.slice(2), quick = argv.includes('--quick');
const only = (() => { const i = argv.indexOf('--only'); return i >= 0 ? argv.splice(i, 2)[1].split(',') : null; })();
const projects = pickProjects(argv.filter(a => !a.startsWith('--')));
const RUN = join(CORE, 'verify', 'run.mjs');
const viaRunner = (check, args = []) => async p => {
  const r = await runScript(p, RUN, [check, ...args], { echo: false });
  const lines = r.out.trim().split('\n');
  // 每個情境一行摘要（scene 的 JSON、determinism 的「一致」、layout 的「通過」）
  const summary = lines.filter(l => /^(\[[^\]]+\] )?(\{|一致|不一致|\d+\/\d+ 通過)|略過/.test(l)).map(l => l.replace(/"(meshes|moving|joints|samples)":\d+,?/g, '').slice(0, 140));
  return { ok: r.code === 0, note: summary.join(' ／ ') || `exit ${r.code}`, detail: r.code ? lines.slice(-25) : [] };
};
const BUILTIN = {
  imports: { quick: true, run: async p => { const r = checkImports(p); return { ok: !r.missing.length, note: `${r.modules} 個模組`, detail: r.missing }; } },
  determinism: { quick: true, needsProject: true, run: viaRunner('determinism') },
  layout: { quick: true, needsProject: true, run: viaRunner('layout') },
  scene: { quick: false, needsProject: true, run: viaRunner('scene') },
};

const split = cmd => cmd.match(/"[^"]*"|\S+/g).map(s => s.replace(/^"|"$/g, ''));
const results = [];
// core 本身：共用模型（core/models）的干涉與重合面；指定專案時略過
if (!argv.some(a => !a.startsWith('--')) && (!only || only.includes('models'))) {
  const t0 = Date.now(), r = await runScript({ dir: CORE }, join(CORE, 'verify', 'models.mjs'), [], { echo: false });
  const lines = r.out.trim().split('\n'), sec = (Date.now() - t0) / 1000;
  results.push({ project: 'core', check: 'models', ok: r.code === 0, note: `${lines.filter(l => l.startsWith('✓')).length}/${lines.filter(l => /^[✓✗]/.test(l)).length} 個模型`, seconds: +sec.toFixed(1) });
  console.log(`${r.code === 0 ? '✓' : '✗'} core · models  ${results.at(-1).note}  (${sec.toFixed(1)} s)`);
  if (r.code) for (const l of lines.filter(l => !l.startsWith('✓'))) console.log('     ' + l);
}
for (const p of projects) {
  const scripts = [...(p.checks?.quick || []), ...(quick ? [] : p.checks?.full || [])];
  const hasProject = existsSync(join(p.web, 'js', 'project.js')), cc = p.core || {};
  const builtins = Object.entries(BUILTIN).filter(([k, b]) => (!b.needsProject || hasProject) && !(cc.skip || []).includes(k) && (!quick || b.quick || (cc.quick || []).includes(k)));
  const jobs = [...builtins.map(([k, b]) => ({ name: k, run: () => b.run(p) })),
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
