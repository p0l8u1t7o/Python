// core 內建檢查的執行入口（由 core/tools/check.mjs 以子程序呼叫，也可單獨執行）：
//   node core/tools/run.mjs <專案> ../core/verify/run.mjs <檢查> [--dt=0.5]
// 檢查：scene（全場干涉＋重合面）、determinism（倒序一致）、layout（空間檢核）
// 讀取專案 web/js/project.js 的 createProject({ scene })，結果寫入 <專案>/review/<檢查>.json。
import './dom-stub.mjs';
import * as THREE from 'three';
import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { verifyScene, sceneText } from './scene.mjs';
import { verifyDeterminism } from './determinism.mjs';

const check = process.argv[2], opts = Object.fromEntries(process.argv.slice(3).filter(a => a.startsWith('--')).map(a => a.slice(2).split('=')).map(([k, v]) => [k, v === undefined ? true : isNaN(+v) ? v : +v]));
const dir = process.cwd(), file = join(dir, 'web', 'js', 'project.js');
if (!existsSync(file)) { console.log(`略過：${file} 不存在`); process.exit(0); }
const { createProject } = await import(pathToFileURL(file).href);
const scene = new THREE.Scene(), project = await createProject({ scene, headless: true });
const t0 = Date.now();
let result;
if (check === 'scene') result = verifyScene(project, scene, { dt: opts.dt, report: s => console.log(s) });
else if (check === 'determinism') result = verifyDeterminism(project, scene);
else if (check === 'layout') {
  const rows = project.layoutChecks?.() || [];
  result = { ok: rows.every(r => r.ok), count: rows.length, failures: rows.filter(r => !r.ok), rows };
} else { console.log('未知檢查：' + check); process.exit(2); }
result.seconds = +((Date.now() - t0) / 1000).toFixed(1);
mkdirSync(join(dir, 'review'), { recursive: true });
const name = { scene: 'scene-verification', determinism: 'determinism', layout: 'layout-checks' }[check];
writeFileSync(join(dir, 'review', name + '.json'), JSON.stringify(result, null, 2));
if (check === 'scene') writeFileSync(join(dir, 'review', name + '.txt'), sceneText(result));

if (check === 'scene') {
  console.log(JSON.stringify({ ok: result.ok, meshes: result.meshes, moving: result.moving, joints: result.joints, samples: result.samples, dynamic: result.dynamic.length, static: result.static.length, zfight: result.zfight.length }));
  if (Object.keys(result.envelope).length) console.log('envelope', JSON.stringify(result.envelope));
  for (const d of result.dynamic.slice(0, 30)) console.log('DYN', d.worst, d.first + '-' + d.last + 's', d.a, '<>', d.b);
  for (const s of result.static.slice(0, 30)) console.log('STA', s.worst, s.a, '<>', s.b);
  for (const z of result.zfight.slice(0, 40)) console.log('ZF ', z.area + 'mm²', 't=' + z.t, z.a, '<>', z.b);
} else if (check === 'determinism') {
  console.log(`${result.ok ? '一致' : '不一致'}：${result.objects} 個物件、${result.samples} 個時間點`);
  for (const f of result.failures) console.log('  ', JSON.stringify(f));
} else {
  console.log(`${result.count - result.failures.length}/${result.count} 通過`);
  for (const f of result.failures) console.log('  ✗', f.group || '', f.name, f.value ?? '', f.note ?? '');
}
process.exit(result.ok ? 0 : 1);
