// core 內建檢查的執行入口（由 core/tools/check.mjs 以子程序呼叫，也可單獨執行）：
//   node core/tools/run.mjs <專案> ../core/verify/run.mjs <檢查> [--dt=0.5] [--variant=名稱]
// 檢查：scene（全場干涉＋重合面）、determinism（倒序一致）、layout（空間檢核）
// 讀取專案 web/js/project.js 的 createProject({ scene, headless, ...params })，結果寫入 <專案>/review/<檢查>.json。
// project.json 的 "variants": [{ "name": "NG", "params": { "ng": "A1" } }] 會在預設情境之外各跑一次
// （配方、SKU、NG 情境等不同參數會建出不同場景）。
import './dom-stub.mjs';
import * as THREE from 'three';
import { writeFileSync, mkdirSync, existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { verifyScene, sceneText } from './scene.mjs';
import { verifyDeterminism } from './determinism.mjs';

const check = process.argv[2], opts = Object.fromEntries(process.argv.slice(3).filter(a => a.startsWith('--')).map(a => a.slice(2).split('=')).map(([k, v]) => [k, v === undefined ? true : isNaN(+v) ? v : +v]));
const dir = process.cwd(), file = join(dir, 'web', 'js', 'project.js');
if (!existsSync(file)) { console.log(`略過：${file} 不存在`); process.exit(0); }
const { createProject } = await import(pathToFileURL(file).href);
const meta = existsSync(join(dir, 'project.json')) ? JSON.parse(readFileSync(join(dir, 'project.json'), 'utf8')) : {};
const variants = [{ name: '預設', params: {} }, ...(meta.variants || [])].filter(v => !opts.variant || v.name === opts.variant);

const t0 = Date.now(), runs = [];
for (const v of variants) {
  const scene = new THREE.Scene(), project = await createProject({ scene, headless: true, ...v.params });
  let r;
  if (check === 'scene') r = verifyScene(project, scene, { dt: opts.dt, report: s => console.log(`[${v.name}] ${s}`) });
  else if (check === 'determinism') r = verifyDeterminism(project, scene);
  else if (check === 'layout') { const rows = project.layoutChecks?.() || []; r = { ok: rows.every(x => x.ok), count: rows.length, failures: rows.filter(x => !x.ok), rows }; }
  else { console.log('未知檢查：' + check); process.exit(2); }
  runs.push({ variant: v.name, params: v.params, ...r });
}
const result = variants.length === 1 ? runs[0] : { ok: runs.every(r => r.ok), variants: runs };
// 耗時只印在終端機、不寫進 review（提交的報告只在結果改變時才有差異）
const seconds = +((Date.now() - t0) / 1000).toFixed(1);
mkdirSync(join(dir, 'review'), { recursive: true });
const name = { scene: 'scene-verification', determinism: 'determinism', layout: 'layout-checks' }[check];
writeFileSync(join(dir, 'review', name + '.json'), JSON.stringify(result, null, 2));
if (check === 'scene') writeFileSync(join(dir, 'review', name + '.txt'), runs.map(r => (runs.length > 1 ? `# ${r.variant}\n` : '') + sceneText(r)).join('\n'));

for (const r of runs) {
  const tag = runs.length > 1 ? `[${r.variant}] ` : '';
  if (check === 'scene') {
    console.log(tag + JSON.stringify({ ok: r.ok, meshes: r.meshes, moving: r.moving, joints: r.joints, samples: r.samples, dynamic: r.dynamic.length, static: r.static.length, zfight: r.zfight.length }));
    if (Object.keys(r.envelope).length) console.log(tag + 'envelope', JSON.stringify(r.envelope));
    for (const d of r.dynamic.slice(0, 30)) console.log(tag + 'DYN', d.worst, d.first + '-' + d.last + 's', d.a, '<>', d.b);
    for (const s of r.static.slice(0, 30)) console.log(tag + 'STA', s.worst, s.a, '<>', s.b);
    for (const z of r.zfight.slice(0, 40)) console.log(tag + 'ZF ', z.area + 'mm²', 't=' + z.t, z.a, '<>', z.b);
  } else if (check === 'determinism') {
    console.log(`${tag}${r.ok ? '一致' : '不一致'}：${r.objects} 個物件、${r.samples} 個時間點`);
    for (const f of r.failures) console.log('  ', JSON.stringify(f));
  } else {
    console.log(`${tag}${r.count - r.failures.length}/${r.count} 通過`);
    for (const f of r.failures) console.log('  ✗', f.group || '', f.name, f.value ?? '', f.note ?? '');
  }
}
console.log(`（${seconds} s）`);
process.exit(result.ok ? 0 : 1);
